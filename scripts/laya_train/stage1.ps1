# Laya stage 1, unattended: free the GPU and RAM, build the public set, full fine-tune,
# keep the result only if it beats the current stage 1 (else stock) on sector or direction.
# Progress and ETA: laya-ft\progress.txt, shown live by Desktop\Laya progress.cmd.
# Started from Desktop\Laya stage 1.cmd; the verdict lands in laya-ft\history.jsonl.
# Rerunning after a crash or reboot resumes from the last checkpoint (every 45 min).

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Home2 = Join-Path $env:USERPROFILE "laya-ft"
$Py = "$Home2\.venv\Scripts\python.exe"
Set-Location $Repo
New-Item -ItemType Directory -Force "$Home2\logs" | Out-Null
Start-Transcript -Path "$Home2\logs\stage1-$(Get-Date -Format yyyyMMdd-HHmm).log"
$env:PYTHONIOENCODING = "utf8"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"

function Stop-Early($Why) {
  Write-Host "NOT STARTED: $Why"
  "$(Get-Date -Format 'dd MMM HH:mm')  stage 1 not started: $Why" | Set-Content -Encoding utf8 "$Home2\progress.txt"
  Stop-Transcript
  exit 1
}
# Preflight: fail in seconds, before anything is stopped or disabled.
Add-Type -AssemblyName System.Windows.Forms
if ([System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus -ne "Online") { Stop-Early "the laptop is on battery; plug it in" }
if ((Get-PSDrive C).Free -lt 10GB) { Stop-Early "less than 10 GB free on C:" }
if (-not (Test-Path $Py)) { Stop-Early "CUDA venv missing at $Py" }
# cmd swallows torch's stderr warnings, which PowerShell 5.1 would turn into errors.
cmd /c "`"$Py`" -c `"import torch, bitsandbytes; assert torch.cuda.is_available()`" >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Stop-Early "torch cannot see the GPU or bitsandbytes is missing" }

# Stay awake until this process exits; children inherit the lower priority.
Add-Type -Namespace Laya -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[Laya.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null
(Get-Process -Id $PID).PriorityClass = "BelowNormal"

schtasks /Change /TN "WorldFin Laya daily" /DISABLE | Out-Null
Get-Process ollama, "ollama app", "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
cmd /c "wsl --shutdown >nul 2>&1"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'server\.main|worker\.main|laya_train' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

try {
  if (-not (Test-Path "$Home2\data\pretrain.json")) {
    & $Py -W ignore -u scripts\laya_train\build_pretrain.py "$Home2\data\pretrain.json" --per-sector 50000 --max-rows 20000000 --extra "$Home2\data\train.json"
    if ($LASTEXITCODE -ne 0) { throw "build_pretrain failed" }
  }
  $Next = "$Home2\stage1-next"
  # Two minutes on the longest items: loss must fall and memory must fit, or stop now.
  "$(Get-Date -Format 'dd MMM HH:mm')  smoke test" | Set-Content -Encoding utf8 "$Home2\progress.txt"
  & $Py -W ignore -u scripts\laya_train\train.py "$Home2\stage1-smoke" --data "$Home2\data\pretrain.json" --mode full --micro-batch 8 --no-grad-ckpt --balance-direction --no-distill --smoke
  $Smoke = $LASTEXITCODE
  Remove-Item -Recurse -Force "$Home2\stage1-smoke" -ErrorAction SilentlyContinue
  if ($Smoke -ne 0) { throw "smoke test failed; see the lines above" }
  # The transcript dropped most of the 12-hour training output, so it gets its own log.
  # One epoch: on the 362k corpus the second raised held-out loss from 0.533 to 0.695.
  $TrainLog = "$Home2\logs\stage1-train-$(Get-Date -Format yyyyMMdd-HHmm).log"
  cmd /c "`"$Py`" -W ignore -u scripts\laya_train\train.py `"$Next`" --data `"$Home2\data\pretrain.json`" --mode full --epochs 1 --micro-batch 8 --grad-accum 4 --no-grad-ckpt --balance-direction --no-distill 2>&1" |
    ForEach-Object { $_; Add-Content -Encoding utf8 $TrainLog $_ }
  if ($LASTEXITCODE -ne 0) { throw "training failed; see $TrainLog" }
  Get-ChildItem $Next -Directory -Filter "epoch*" | Remove-Item -Recurse -Force
  "$(Get-Date -Format 'dd MMM HH:mm')  scoring stage1-next against the incumbent on CPU (about 75 min)" |
    Set-Content -Encoding utf8 "$Home2\progress.txt"

  # Compare the raw models; the neutral discount is tuned later for the daily LoRA.
  $env:FINSCRAPE_LAYA_NEUTRAL_SCALE = "1.0"
  @'
import json, shutil, sys
from datetime import UTC, datetime
sys.path.insert(0, r"scripts\laya_train")
import daily as d

# The incumbent is the kept stage 1, else the stock model; the new one must win on
# sector or on direction without losing on the other.
test = d.load(d.GOLD) + d.load(d.DATA / "holdout.json")
stage1, nxt = d.HOME / "stage1", d.HOME / "stage1-next"
d.use_model(stage1 if stage1.exists() else None)
old, old_dir = d.hits(test)
d.use_model(nxt)
new, new_dir = d.hits(test)
kept = (new - old >= d.MIN_GAIN and new_dir >= old_dir - d.DIRECTION_SLACK) or (
    new_dir - old_dir >= d.DIRECTION_SLACK and old - new < d.MIN_GAIN
)
if kept:
    shutil.rmtree(stage1, ignore_errors=True)
    shutil.move(str(nxt), str(stage1))
else:
    shutil.rmtree(nxt)
line = {"date": datetime.now(UTC).strftime("%Y%m%d"), "stage1": True, "test_cases": len(test),
        "incumbent": old, "stage1_right": new, "incumbent_direction": round(old_dir, 4),
        "stage1_direction": round(new_dir, 4), "kept": kept}
with (d.HOME / "history.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps(line) + "\n")
msg = f"INCUMBENT {old} ({old_dir:.3f})  NEW {new} ({new_dir:.3f}) of {len(test)}: " + ("kept" if kept else "deleted")
(d.HOME / "progress.txt").write_text(f"{datetime.now():%d %b %H:%M}  stage 1 done. {msg}\n", "utf-8")
print(msg)
'@ | & "$Repo\.venv\Scripts\python.exe" -W ignore -
}
finally {
  schtasks /Change /TN "WorldFin Laya daily" /ENABLE | Out-Null
  Write-Host "STAGE 1 DONE"
  Stop-Transcript
}
