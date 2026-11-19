@echo off
rem Double-click from File Explorer as your normal account. It asks for the ADM password.
setlocal
for /f "delims=" %%P in ('python "%~dp0..\run.py" unc') do set "PROJECT=%%P"
if not defined PROJECT (
    echo Could not find the project folder.
    pause
    exit /b 1
)
echo Project folder: %PROJECT%
echo.
echo Enter the password for %USERDOMAIN%\%USERNAME%ADM when asked.
echo A new window will open and run the probe as the ADM account.
echo.
runas /user:%USERDOMAIN%\%USERNAME%ADM "cmd /k python \"%PROJECT%\run.py\" probe"
pause
