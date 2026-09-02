@echo off
rem ===========================================================================
rem  MediaSort - instalator dla Windows.
rem  Uruchamia install_windows.ps1 z pominieciem polityki wykonywania skryptow.
rem ===========================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
    echo Instalacja nie powiodla sie - sprawdz komunikat powyzej.
) else (
    echo Gotowe.
)
echo.
pause
exit /b %RC%
