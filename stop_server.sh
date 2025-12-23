#!/bin/bash
# Скрипт остановки сервера дискотеки ВДНХ

echo "Остановка сервера дискотеки ВДНХ"
echo "================================================"
echo ""

# Переходим в директорию скрипта
cd "$(dirname "$0")"

# Флаг для отслеживания, были ли остановлены процессы
STOPPED_SOMETHING=0

# Ищем процесс scheduler_server.py
SERVER_PID=$(ps aux | grep '[s]cheduler_server.py' | awk '{print $2}')

if [ -n "$SERVER_PID" ]; then
    echo "Найден процесс сервера (PID: $SERVER_PID)"
    echo "Останавливаем сервер..."
    kill $SERVER_PID
    sleep 2
    
    if ps -p $SERVER_PID > /dev/null 2>&1; then
        echo "Процесс не остановился, принудительная остановка..."
        kill -9 $SERVER_PID
        sleep 1
    fi
    
    if ps -p $SERVER_PID > /dev/null 2>&1; then
        echo "Не удалось остановить сервер (PID: $SERVER_PID)"
    else
        echo "Сервер успешно остановлен"
        STOPPED_SOMETHING=1
    fi
else
    echo "Сервер не запущен"
fi

echo ""

# Ищем процесс SSH туннеля localhost.run
TUNNEL_PID=$(ps aux | grep '[s]sh.*localhost.run' | awk '{print $2}')

if [ -n "$TUNNEL_PID" ]; then
    echo "Найден SSH туннель (PID: $TUNNEL_PID)"
    echo "Останавливаем туннель..."
    kill $TUNNEL_PID
    sleep 1
    
    if ps -p $TUNNEL_PID > /dev/null 2>&1; then
        kill -9 $TUNNEL_PID
        sleep 1
    fi
    
    if ps -p $TUNNEL_PID > /dev/null 2>&1; then
        echo "Не удалось остановить туннель (PID: $TUNNEL_PID)"
    else
        echo "SSH туннель успешно остановлен"
        STOPPED_SOMETHING=1
    fi
else
    echo "SSH туннель не запущен"
fi

echo ""
echo "================================================"

if [ $STOPPED_SOMETHING -eq 0 ]; then
    echo "Ничего не было запущено"
fi

