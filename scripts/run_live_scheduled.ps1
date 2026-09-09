# Wrapper for Windows Task Scheduler. Not part of the research code path --
# it exists only to give the daily automated run a fixed working directory,
# a fixed interpreter, and a persistent log, since a scheduled task has none
# of those by default.
#
# Every run appends to logs/live_run.log (never overwritten), so the
# unattended history stays auditable exactly like the CSV journals it wraps.
#
# Redirection is done through cmd.exe, not PowerShell's own >> / *>>. Python's
# logging module writes INFO lines to stderr; PowerShell's native-command
# redirection wraps every stderr line in a terminating ErrorRecord, which
# aborted the run on its first log line the first time this was tried. cmd's
# redirection has no such behaviour.

Set-Location "C:\Users\Harshit Kumar\Downloads\Paper Trading"
$env:PYTHONPATH = "."

$logFile = "logs\live_run.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
$python = "C:\Users\Harshit Kumar\AppData\Local\Programs\Python\Python312\python.exe"

Add-Content -Path $logFile -Value "`n===== SCHEDULED RUN START $stamp ====="
cmd.exe /c "`"$python`" scripts\run_live.py --execute >> `"$logFile`" 2>&1"

if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $logFile -Value "===== SCHEDULED RUN OK ====="
} else {
    Add-Content -Path $logFile -Value "===== SCHEDULED RUN FAILED (exit $LASTEXITCODE) ====="
}
