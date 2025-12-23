#!/bin/bash
# Скрипт для запуска телеграм-бота с командами управления туннелем

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Проверяем наличие виртуального окружения
if [ ! -d "venv" ]; then
    echo "❌ Виртуальное окружение не найдено!"
    echo "Создайте его командой: python3 -m venv venv"
    exit 1
fi

# Активируем виртуальное окружение
source venv/bin/activate

# Проверяем наличие pyTelegramBotAPI
if ! python -c "import telebot" 2>/dev/null; then
    echo "📦 Установка pyTelegramBotAPI..."
    pip install pyTelegramBotAPI
fi

# Запускаем бота
echo "🚀 Запуск телеграм-бота..."
python telegram_bot_commands.py
