#!/bin/bash
# Скрипт запуска сервера дискотеки ВДНХ для Ubuntu

echo "🎀 Запуск веб-сервера планировщика дискотеки ВДНХ"
echo "================================================"
echo ""

# Переходим в директорию скрипта
SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR"

# Проверяем существование виртуального окружения
if [ ! -f "venv/bin/python" ]; then
    echo "❌ Виртуальное окружение не найдено!"
    echo "Запустите сначала скрипт установки:"
    echo "  sudo bash install_ubuntu.sh"
    exit 1
fi

# Проверяем существование файла сервера
if [ ! -f "scheduler_server.py" ]; then
    echo "❌ Файл scheduler_server.py не найден!"
    exit 1
fi

# Проверяем существование веб-интерфейса
if [ ! -f "web_interface.html" ]; then
    echo "⚠️  Файл web_interface.html не найден!"
    echo "Веб-интерфейс будет недоступен"
else
    echo "✅ Веб-интерфейс Hello Kitty найден"
fi

echo ""
echo "🚀 Запускаем сервер и телеграм бота..."
echo "================================================"
echo ""

# Активируем виртуальное окружение
source venv/bin/activate

# Проверяем и устанавливаем pyTelegramBotAPI если нужно
if ! python -c "import telebot" 2>/dev/null; then
    echo "📦 Установка pyTelegramBotAPI..."
    pip install pyTelegramBotAPI
fi

# Запускаем телеграм бота в фоне
if [ -f "telegram_bot_commands.py" ]; then
    echo "🤖 Запуск телеграм-бота в фоне..."
    nohup python telegram_bot_commands.py > telegram_bot.log 2>&1 &
    TELEGRAM_BOT_PID=$!
    echo $TELEGRAM_BOT_PID > telegram_bot.pid
    echo "✅ Телеграм-бот запущен (PID: $TELEGRAM_BOT_PID)"
    echo "📋 Логи бота: tail -f telegram_bot.log"
else
    echo "⚠️  telegram_bot_commands.py не найден, бот не запущен"
fi

echo ""

# Функция для остановки телеграм-бота при выходе
cleanup() {
    echo ""
    echo "🛑 Остановка сервисов..."
    if [ -f "telegram_bot.pid" ]; then
        TELEGRAM_BOT_PID=$(cat telegram_bot.pid)
        if ps -p $TELEGRAM_BOT_PID > /dev/null 2>&1; then
            kill $TELEGRAM_BOT_PID 2>/dev/null
            echo "✅ Телеграм-бот остановлен"
        fi
        rm -f telegram_bot.pid
    fi
    deactivate
}

# Устанавливаем обработчик сигналов
trap cleanup EXIT INT TERM

# Запускаем основной сервер
python scheduler_server.py