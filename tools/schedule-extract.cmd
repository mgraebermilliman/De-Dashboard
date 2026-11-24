@echo off
rem Creates two daily scheduled tasks (05:30 and 12:30) that run the extract as the ADM account.
rem Double-click as your normal account; it re-opens itself as the ADM account.
setlocal
for /f "delims=" %%P in ('python "%~dp0..\run.py" unc') do set "PROJECT=%%P"
if not defined PROJECT (
    echo Could not find the project folder.
    pause
    exit /b 1
)
set "ME=%USERNAME%"
if /i not "%ME:~-3%"=="ADM" (
    echo Enter the password for %USERDOMAIN%\%USERNAME%ADM when asked.
    runas /user:%USERDOMAIN%\%USERNAME%ADM "cmd /k \"%PROJECT%\tools\schedule-extract.cmd\""
    pause
    exit /b
)
set "PY=C:\Program Files\Python313\python.exe"
echo Creating tasks for %USERDOMAIN%\%USERNAME%. Windows asks for the password once per task
echo so the task can run when you are signed out.
schtasks /create /f /tn "De-Dashboard\Extract 0530" /sc daily /st 05:30 /ru "%USERDOMAIN%\%USERNAME%" /rp * /tr "\"%PY%\" \"%PROJECT%\run.py\" extract"
schtasks /create /f /tn "De-Dashboard\Extract 1230" /sc daily /st 12:30 /ru "%USERDOMAIN%\%USERNAME%" /rp * /tr "\"%PY%\" \"%PROJECT%\run.py\" extract"
echo.
echo Done. To remove later: schtasks /delete /tn "De-Dashboard\Extract 0530" /f  (and the same for 1230)
