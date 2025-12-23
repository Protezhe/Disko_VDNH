#!/bin/bash
# Скрипт остановки сервера дискотеки ВДНХ

echo "Остановка сервера дискотеки ВДНХ"
echo "================================================"
echo ""

# Переходим в директорию скрипта
cd "$(dirname "$0")"

STOPPED_SOMETHING=false

# Останавливаем телеграм-бота
if [ -f "telegram_bot.pid" ]; then
    BOT_PID=$(cat telegram_bot.pid)
    if ps -p $BOT_PID > /dev/null 2>&1; then
        echo "🤖 Останавливаем телеграм-бота (PID: $BOT_PID)..."
        kill $BOT_PID 2>/dev/null
        sleep 2
        if ps -p $BOT_PID > /dev/null 2>&1; then
            kill -9 $BOT_PID 2>/dev/null
        fi
        echo "✅ Телеграм-бот остановлен"
        STOPPED_SOMETHING=true
    fi
    rm -f telegram_bot.pid
else
    # Ищем процесс по имени если нет PID файла
    BOT_PID=$(ps aux | grep '[t]elegram_bot_commands.py' | awk '{print $2}')
    if [ -n "$BOT_PID" ]; then
        echo "🤖 Останавливаем телеграм-бота (PID: $BOT_PID)..."
        kill $BOT_PID 2>/dev/null
        sleep 2
        if ps -p $BOT_PID > /dev/null 2>&1; then
            kill -9 $BOT_PID 2>/dev/null
        fi
        echo "✅ Телеграм-бот остановлен"
        STOPPED_SOMETHING=true
    fi
fi

# Ищем процесс scheduler_server.py
PID=$(ps aux | grep '[s]cheduler_server.py' | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "ℹ️  Сервер не запущен"
else
    echo "🖥️  Найден процесс сервера (PID: $PID)"
    echo "Останавливаем сервер..."

    # Останавливаем процесс
    kill $PID

    # Ждем завершения
    sleep 2

    # Проверяем, остановился ли процесс
    if ps -p $PID > /dev/null 2>&1; then
        echo "Процесс не остановился, принудительная остановка..."
        kill -9 $PID
        sleep 1
    fi

    # Финальная проверка
    if ps -p $PID > /dev/null 2>&1; then
        echo "❌ Не удалось остановить сервер (PID: $PID)"
        exit 1
    else
        echo "✅ Сервер успешно остановлен"
        STOPPED_SOMETHING=true
    fi
fi

if [ "$STOPPED_SOMETHING" = false ]; then
    echo "ℹ️  Ничего не было запущено"
fi

echo ""
echo "ℹ️  VPN-соединение и туннель оставлены активными"
echo "================================================"

