#!/bin/bash
# Скрипт запуска сервера дискотеки ВДНХ для Ubuntu

echo "Запуск веб-сервера планировщика дискотеки ВДНХ"
echo "================================================"
echo ""

# Переходим в директорию скрипта
SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR"

# Проверяем существование виртуального окружения
if [ ! -f "venv/bin/python" ]; then
    echo "Виртуальное окружение не найдено!"
    echo "Запустите сначала скрипт установки:"
    echo "  sudo bash install_ubuntu.sh"
    exit 1
fi

# Проверяем существование файла сервера
if [ ! -f "scheduler_server.py" ]; then
    echo "Файл scheduler_server.py не найден!"
    exit 1
fi

# Проверяем существование веб-интерфейса
if [ ! -f "web_interface.html" ]; then
    echo "Файл web_interface.html не найден!"
    echo "Веб-интерфейс будет недоступен"
else
    echo "Веб-интерфейс Hello Kitty найден"
fi

echo ""
echo "Запускаем сервер..."
echo "================================================"
echo ""

# Активируем виртуальное окружение
source venv/bin/activate

# Запускаем сервер в фоне
python scheduler_server.py &
SERVER_PID=$!

# Функция для завершения всех процессов при выходе
cleanup() {
    echo ""
    echo "Завершение работы..."
    kill $SERVER_PID 2>/dev/null
    kill $TUNNEL_PID 2>/dev/null
    deactivate
    exit 0
}

trap cleanup SIGINT SIGTERM

# Ждем пока сервер запустится
echo "Ожидание запуска сервера..."
sleep 3

# Проверяем что сервер запустился
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Сервер не запустился!"
    exit 1
fi

echo "Сервер запущен (PID: $SERVER_PID)"
echo ""
echo "Запускаем SSH туннель для публичного доступа..."
echo "================================================"

# Создаем временный файл для захвата вывода SSH
TUNNEL_OUTPUT=$(mktemp)

# Запускаем SSH туннель в фоне, записывая вывод в файл
ssh -o StrictHostKeyChecking=no -R 80:localhost:5002 nokey@localhost.run > "$TUNNEL_OUTPUT" 2>&1 &
TUNNEL_PID=$!

# Ждем и ищем URL в выводе
PUBLIC_URL=""
for i in {1..30}; do
    sleep 1
    
    # Проверяем что сервер еще жив
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Сервер неожиданно остановился!"
        kill $TUNNEL_PID 2>/dev/null
        rm -f "$TUNNEL_OUTPUT"
        deactivate
        exit 1
    fi
    
    # Проверяем что SSH процесс еще жив
    if ! kill -0 $TUNNEL_PID 2>/dev/null; then
        echo "SSH туннель завершился. Вывод:"
        cat "$TUNNEL_OUTPUT"
        break
    fi
    
    # Ищем URL в выводе (localhost.run выдает URL в формате https://xxxxx.lhr.life или https://xxxxx.lhrtunnel.link)
    PUBLIC_URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.(lhr\.life|lhrtunnel\.link|localhost\.run)' "$TUNNEL_OUTPUT" 2>/dev/null | head -1)
    if [ -n "$PUBLIC_URL" ]; then
        echo ""
        echo "================================================"
        echo "Публичный URL: $PUBLIC_URL"
        echo "================================================"
        
        # Отправляем URL в Telegram
        python -c "
import sys
sys.path.insert(0, '.')
from telegram_bot import TelegramNotifier
notifier = TelegramNotifier()
if notifier.enabled:
    message = '<b>Сервер дискотеки запущен!</b>\n\nПубличный URL: $PUBLIC_URL'
    notifier.send_message(message)
    print('URL отправлен в Telegram')
else:
    print('Telegram бот не настроен')
"
        break
    fi
done

# Удаляем временный файл
rm -f "$TUNNEL_OUTPUT"

if [ -z "$PUBLIC_URL" ]; then
    echo "Не удалось получить публичный URL за 30 секунд"
    echo "Проверьте подключение к интернету"
fi

# Ждем завершения сервера (туннель продолжает работать в фоне)
echo ""
echo "Сервер работает. Для остановки нажмите Ctrl+C"
wait $SERVER_PID