@echo off
setlocal
set "REWIND_APP_ROOT=%~dp0"
powershell -NoProfile -Command "$appRoot=$env:REWIND_APP_ROOT; $pythonExe=Join-Path $env:USERPROFILE '.local\share\lecture-narration-venv\Scripts\python.exe'; if(-not(Test-Path -LiteralPath $pythonExe)){ $candidate=Get-Command python -ErrorAction SilentlyContinue; if($candidate){$pythonExe=$candidate.Source}else{Write-Host 'Python 3.10 or later is required.'; exit 1} }; Start-Process -FilePath $pythonExe -ArgumentList @('service/server.py','--open-browser') -WorkingDirectory $appRoot -WindowStyle Hidden"
if errorlevel 1 pause
