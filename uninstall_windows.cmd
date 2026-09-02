@echo off
rem ===========================================================================
rem  MediaSort - dezinstalator dla Windows.
rem  Uruchamia uninstall_windows.ps1 z pominieciem polityki wykonywania skryptow.
rem  Opcje (przekazywane dalej):  -Force  -DeleteData
rem ===========================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_windows.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo Odinstalowanie anulowane lub zakonczone bledem - sprawdz komunikat powyzej.
) else (
    echo Gotowe.
)
echo.
pause
exit /b %RC%
