@echo off
echo 🎀 Запуск веб-сервера планировщика дискотеки ВДНХ
echo ================================================
echo.

REM Проверяем существование виртуального окружения
if not exist "venv\Scripts\python.exe" (
    echo ❌ Виртуальное окружение не найдено!
    echo Создайте виртуальное окружение командой:
    echo python -m venv venv
    pause
    exit /b 1
)

REM Проверяем существование файла сервера
if not exist "scheduler_server.py" (
    echo ❌ Файл scheduler_server.py не найден!
    pause
    exit /b 1
)

REM Проверяем существование веб-интерфейса
if not exist "web_interface.html" (
    echo ⚠️ Файл web_interface.html не найден!
    echo Веб-интерфейс будет недоступен
) else (
    echo ✅ Веб-интерфейс Hello Kitty найден
)

echo.
echo 🚀 Запускаем сервер...
echo ================================================
echo.

REM Запускаем сервер через виртуальное окружение
venv\Scripts\python.exe scheduler_server.py

pause
