# Backup trigger for GitHub cron: runs one session locally, then pushes state.
# Duplicate-safe: session state marks a session as already run.
Set-Location "C:\Users\Harshit Kumar\Downloads\Paper Trading"
$env:PYTHONPATH = "."
$py = "C:\Users\Harshit Kumar\AppData\Local\Programs\Python\Python312\python.exe"
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\session_local.log"
cmd /c "echo === %DATE% %TIME% >> $log"
cmd /c "git stash -q >> $log 2>&1"
cmd /c "git pull -q --rebase origin main >> $log 2>&1"
cmd /c "git stash pop -q >> $log 2>&1"
cmd /c "`"$py`" scripts/run_session.py --execute >> $log 2>&1"
cmd /c "git add portfolio/session_log.csv portfolio/session_state.json >> $log 2>&1"
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
  cmd /c "git commit -q -m `"session: local trigger`" >> $log 2>&1"
  for ($i=0; $i -lt 3; $i++) {
    cmd /c "git push -q origin main >> $log 2>&1"
    if ($LASTEXITCODE -eq 0) { break }
    cmd /c "git pull -q --rebase origin main >> $log 2>&1"
  }
}
