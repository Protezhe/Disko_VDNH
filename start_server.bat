@echo off
chcp 65001 >nul
echo ========================================
echo Запуск сервера дискотеки
echo ========================================
echo.

REM Проверка наличия виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo ОШИБКА: Виртуальное окружение не найдено!
    echo Создайте виртуальное окружение командой: python -m venv venv
    pause
    exit /b 1
)

echo Активация виртуального окружения...
call venv\Scripts\activate.bat

echo.
echo Проверка зависимостей...
if not exist "venv\.dependencies_installed" (
    echo Первый запуск - установка зависимостей из requirements.txt...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ОШИБКА: Не удалось установить зависимости!
        pause
        exit /b 1
    )
    echo. > venv\.dependencies_installed
    echo Зависимости успешно установлены!
) else (
    echo Зависимости уже установлены.
)

echo.
echo Запуск сервера...
python scheduler_server.py

REM Если сервер завершился с ошибкой
if errorlevel 1 (
    echo.
    echo ОШИБКА: Сервер завершился с ошибкой!
    pause
)

deactivate
