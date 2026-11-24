@echo off
rem "Run extract now": double-click from File Explorer as your normal account. It asks for the ADM password.
setlocal
for /f "delims=" %%P in ('python "%~dp0..\run.py" unc') do set "PROJECT=%%P"
if not defined PROJECT (
    echo Could not find the project folder.
    pause
    exit /b 1
)
echo Enter the password for %USERDOMAIN%\%USERNAME%ADM when asked.
echo A new window will run the extract as the ADM account. When it finishes, click Refresh in Power BI.
echo.
runas /user:%USERDOMAIN%\%USERNAME%ADM "cmd /k python \"%PROJECT%\run.py\" extract"
pause
