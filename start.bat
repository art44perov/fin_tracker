@echo off

REM Переход в папку со скриптами
cd /d "%~dp0"

REM Запуск первого скрипта без консоли
start "" pythonw.exe "C:\Users\Honor\Desktop\Работа\TimeTracker\tracker.py"

REM Запуск второго скрипта без консоли
start "" pythonw.exe "C:\Users\Honor\Desktop\Работа\ЛичныйСекретарь\app.py"

exit