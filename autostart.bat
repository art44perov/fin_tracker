@echo off
:: Этот скрипт добавляет ФинЛичный в автозагрузку Windows
set "APP_DIR=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\ФинЛичный.bat"

echo @echo off > "%SHORTCUT%"
echo cd /d "%APP_DIR%" >> "%SHORTCUT%"
echo start /min python "%APP_DIR%app.py" >> "%SHORTCUT%"

echo.
echo ✓ ФинЛичный добавлен в автозагрузку Windows!
echo   Приложение будет запускаться при старте системы.
echo   Файл: %SHORTCUT%
echo.
pause
