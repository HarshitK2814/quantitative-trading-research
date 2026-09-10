# Wrapper for Windows Task Scheduler. Not part of the research code path --
# it exists only to give the daily automated run a fixed working directory,
# a fixed interpreter, a persistent log, and (below) an automatic push of
# the journal to GitHub, since a scheduled task has none of those by
# default.
#
# Every run appends to logs/live_run.log (never overwritten, gitignored), so
# the unattended history stays auditable exactly like the CSV journals it
# wraps.
#
# All native-command redirection goes through cmd.exe, not PowerShell's own
# >> / *>>. Both Python's logging module and git write routine progress to
# stderr; PowerShell's own redirection wraps every stderr line in an
# ErrorRecord, which aborted the run on its very first log line the first
# time this was tried (see research/daily_log.md). cmd's redirection has no
# such behaviour.

Set-Location "C:\Users\Harshit Kumar\Downloads\Paper Trading"
$env:PYTHONPATH = "."

$logFile = "logs\live_run.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss K"
$dateOnly = Get-Date -Format "yyyy-MM-dd"
$python = "C:\Users\Harshit Kumar\AppData\Local\Programs\Python\Python312\python.exe"

Add-Content -Path $logFile -Value "`n===== SCHEDULED RUN START $stamp ====="
cmd.exe /c "`"$python`" scripts\run_live.py --execute >> `"$logFile`" 2>&1"

if ($LASTEXITCODE -ne 0) {
    Add-Content -Path $logFile -Value "===== EQUITY RUN FAILED (exit $LASTEXITCODE) -- skipping commit/push ====="
    exit $LASTEXITCODE
}
Add-Content -Path $logFile -Value "===== EQUITY RUN OK ====="

# H9's hedge check runs second and its failure is deliberately non-fatal to
# the pipeline -- it is a no-op most nights (rolls only inside 14 DTE), and a
# hedge-leg failure must not block committing/pushing the equity journal,
# which is the primary evidence trail.
cmd.exe /c "`"$python`" scripts\run_hedge.py --execute >> `"$logFile`" 2>&1"
if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $logFile -Value "===== HEDGE RUN OK ====="
} else {
    Add-Content -Path $logFile -Value "===== HEDGE RUN FAILED (exit $LASTEXITCODE) -- continuing to commit/push the equity leg regardless ====="
}

# Regenerate the public track-record page from the freshly-written journals.
# Non-fatal for the same reason as the hedge leg: a rendering problem must not
# block the primary evidence trail from being committed.
cmd.exe /c "`"$python`" scripts\build_dashboard.py >> `"$logFile`" 2>&1"
if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $logFile -Value "===== DASHBOARD OK ====="
} else {
    Add-Content -Path $logFile -Value "===== DASHBOARD FAILED (exit $LASTEXITCODE) -- continuing ====="
}

# ---------------------------------------------------------------------------
# Auto-commit + push -- the journal CSVs only.
#
# Deliberately NOT `git add -A`. This runs unattended for months; sweeping in
# whatever else happens to be sitting in the working tree (a half-finished
# manual edit made earlier that day, a fresh dated cache manifest under
# data/raw/) is not a decision an unattended job should make. Only the
# append-only evidence files this project already treats as the record are
# staged.
# ---------------------------------------------------------------------------
cmd.exe /c "git add portfolio/trades.csv portfolio/daily_snapshot.csv portfolio/hedge_trades.csv docs/index.html >> `"$logFile`" 2>&1"

$staged = git diff --cached --name-only
if (-not $staged) {
    Add-Content -Path $logFile -Value "===== NOTHING TO COMMIT ====="
    exit 0
}

$commitMsgFile = New-TemporaryFile
@"
auto: daily paper-trading journal update $dateOnly

Automated nightly commit via scripts/run_live_scheduled.ps1 (Windows
Task Scheduler, task PaperTradingDailyRun). No code changes -- journal
CSVs and the generated track-record page.
"@ | Set-Content -Path $commitMsgFile -Encoding ascii

cmd.exe /c "git commit -F `"$commitMsgFile`" >> `"$logFile`" 2>&1"
Remove-Item $commitMsgFile -Force -ErrorAction SilentlyContinue

cmd.exe /c "git pull --rebase --autostash >> `"$logFile`" 2>&1"
cmd.exe /c "git push >> `"$logFile`" 2>&1"

if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $logFile -Value "===== AUTO-PUSH OK ====="
} else {
    Add-Content -Path $logFile -Value "===== AUTO-PUSH FAILED (exit $LASTEXITCODE) -- journal is committed locally; push manually when you next open a session ====="
}
