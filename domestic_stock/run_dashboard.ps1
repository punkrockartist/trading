param(
    [string]$PythonExe = "py",
    [string]$PythonArgs = "-3.12 .\quant_dashboard.py"
)

$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$logDir = Join-Path $scriptDir "logs"
if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$transcriptPath = Join-Path $logDir "dashboard_transcript_$ts.log"
$runnerPath = Join-Path $logDir "dashboard_runner_$ts.log"

Start-Transcript -Path $transcriptPath -Append | Out-Null

function Write-RunnerLog([string]$msg) {
    $line = "$(Get-Date -Format s)`t$msg"
    Add-Content -Path $runnerPath -Value $line
}

Write-RunnerLog "launcher start cwd=$scriptDir command=$PythonExe $PythonArgs"

try {
    & $PythonExe $PythonArgs.Split(" ")
    $exitCode = $LASTEXITCODE
    Write-RunnerLog "process exited exit_code=$exitCode"
}
catch {
    Write-RunnerLog "launcher exception $($_.Exception.GetType().Name): $($_.Exception.Message)"
    throw
}
finally {
    Write-RunnerLog "launcher end"
    try { Stop-Transcript | Out-Null } catch {}
}
