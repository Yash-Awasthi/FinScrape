# Laya stage 1, unattended: free the GPU and RAM, build the public set, full fine-tune,
# keep the result only if it beats the stock model by MIN_GAIN gold + holdout cases.
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
  & $Py -W ignore -u scripts\laya_train\train.py "$Home2\stage1" --data "$Home2\data\pretrain.json" --mode full --epochs 1 --micro-batch 2 --grad-accum 16
  if ($LASTEXITCODE -ne 0) { throw "training failed" }
  Get-ChildItem "$Home2\stage1" -Directory -Filter "epoch*" | Remove-Item -Recurse -Force

  @'
import json, shutil, sys
from datetime import UTC, datetime
sys.path.insert(0, r"scripts\laya_train")
import daily as d

test = d.load(d.GOLD) + d.load(d.DATA / "holdout.json")
stage1 = d.HOME / "stage1"
d.use_model(None)
stock = round(d.accuracy(test) * len(test))
d.use_model(stage1)
new = round(d.accuracy(test) * len(test))
kept = new - stock >= d.MIN_GAIN
if not kept:
    shutil.rmtree(stage1)
line = {"date": datetime.now(UTC).strftime("%Y%m%d"), "stage1": True, "test_cases": len(test),
        "stock": stock, "stage1_right": new, "kept": kept}
with (d.HOME / "history.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps(line) + "\n")
print(f"STOCK {stock}  STAGE1 {new}  of {len(test)}: " + ("kept" if kept else "deleted"))
'@ | & "$Repo\.venv\Scripts\python.exe" -W ignore -
}
finally {
  schtasks /Change /TN "WorldFin Laya daily" /ENABLE | Out-Null
  Write-Host "STAGE 1 DONE"
  Stop-Transcript
}
