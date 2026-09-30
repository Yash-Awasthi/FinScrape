# Laya stage 1, unattended: free the GPU and RAM, build the public set, full fine-tune,
# keep the result only if it beats the current stage 1 (else stock) on sector or direction.
# Progress and ETA: laya-ft\progress.txt, shown live by Desktop\Laya progress.cmd.
# Started from Desktop\Laya stage 1.cmd; the verdict lands in laya-ft\history.jsonl.

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
    & $Py -W ignore -u scripts\laya_train\build_pretrain.py "$Home2\data\pretrain.json"
    if ($LASTEXITCODE -ne 0) { throw "build_pretrain failed" }
  }
  $Next = "$Home2\stage1-next"
  & $Py -W ignore -u scripts\laya_train\train.py $Next --data "$Home2\data\pretrain.json" --mode full --epochs 1 --micro-batch 2 --grad-accum 16
  if ($LASTEXITCODE -ne 0) { throw "training failed" }
  Get-ChildItem $Next -Directory -Filter "epoch*" | Remove-Item -Recurse -Force
  "$(Get-Date -Format 'dd MMM HH:mm')  scoring stage1-next against the incumbent on CPU (about 25 min)" |
    Set-Content -Encoding utf8 "$Home2\progress.txt"

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
