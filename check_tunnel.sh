#!/bin/bash
# Скрипт создания и проверки SSH-туннеля через localhost.run

# Настройки
LOG_FILE="tunnel_monitor.log"
TUNNEL_PID_FILE="tunnel.pid"
TUNNEL_URL_FILE="tunnel_url.txt"
LOCAL_PORT=5002
SSH_USER="santamozzarella@gmail.com"
SSH_KEY="$HOME/.ssh/id_rsa"
SCRIPT_DIR="$(dirname "$0")"

# Переходим в директорию скрипта
cd "$SCRIPT_DIR"

# Функция логирования
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Получение текущего URL
get_current_url() {
    if [ -f "$TUNNEL_URL_FILE" ]; then
        cat "$TUNNEL_URL_FILE"
    else
        echo ""
    fi
}

# Проверка, запущен ли процесс туннеля
check_tunnel_process() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        local pid=$(cat "$TUNNEL_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0  # Процесс с таким PID существует
        fi
        # PID файл есть, но процесс не найден - удаляем файл
        rm -f "$TUNNEL_PID_FILE"
    fi
    
    # Дополнительная проверка: ищем любой ssh процесс с localhost.run
    if pgrep -f "ssh.*localhost.run" > /dev/null 2>&1; then
        return 0  # Процесс существует
    fi
    
    return 1  # Процесс не найден
}

# Проверка, работает ли туннель реально (URL отвечает)
check_tunnel_health() {
    local url=$(get_current_url)
    
    if [ -z "$url" ]; then
        return 1  # URL не найден
    fi
    
    # Делаем запрос к туннелю и проверяем ответ
    local response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null)
    
    # Если получили ответ (любой код кроме 000 = timeout)
    if [ "$response" != "000" ]; then
        # Проверяем что это не "no tunnel here" (обычно 404 или специфичный текст)
        local body=$(curl -s --max-time 10 "$url" 2>/dev/null)
        if echo "$body" | grep -qi "no tunnel"; then
            log_message "Туннель не работает: 'no tunnel here'"
            return 1
        fi
        return 0  # Туннель работает
    fi
    
    log_message "Туннель не отвечает (timeout)"
    return 1
}

# Проверка, запущен ли туннель и работает ли он
check_tunnel_running() {
    # Сначала проверяем процесс
    if ! check_tunnel_process; then
        return 1
    fi
    
    # Затем проверяем что URL реально работает
    if ! check_tunnel_health; then
        return 1
    fi
    
    return 0
}

# Отправка URL в Telegram через Python
send_telegram_message() {
    local url="$1"
    
    # Используем Python из виртуального окружения
    local venv_python="$SCRIPT_DIR/venv/bin/python"
    if [ ! -f "$venv_python" ]; then
        venv_python="python3"
        log_message "Виртуальное окружение не найдено, используем системный Python"
    fi
    
    cd "$SCRIPT_DIR"
    "$venv_python" - "$url" << 'PYTHON_SCRIPT'
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')
from telegram_bot import TelegramNotifier

url = sys.argv[1] if len(sys.argv) > 1 else "URL не определен"
notifier = TelegramNotifier()
message = f"<b>Туннель создан!</b>\n\nПубличная ссылка:\n{url}"
if notifier.send_message(message):
    print("[Tunnel] Ссылка отправлена в Telegram")
else:
    print("[Tunnel] Не удалось отправить ссылку в Telegram")
PYTHON_SCRIPT
}

# Запуск туннеля
start_tunnel() {
    log_message "Запуск SSH-туннеля..."
    
    # Создаем временный файл для вывода ssh
    local output_file=$(mktemp)
    
    # Запускаем ssh в фоне и перенаправляем вывод
    # Используем unbuffer если доступен, иначе stdbuf, иначе напрямую
    if command -v unbuffer &> /dev/null; then
        unbuffer ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 80:localhost:$LOCAL_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    elif command -v stdbuf &> /dev/null; then
        stdbuf -oL -eL ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 80:localhost:$LOCAL_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    else
        ssh -i "$SSH_KEY" -tt -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 80:localhost:$LOCAL_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    fi
    
    local ssh_pid=$!
    echo $ssh_pid > "$TUNNEL_PID_FILE"
    
    log_message "SSH процесс запущен с PID: $ssh_pid"
    
    # Ждем появления URL в выводе (максимум 30 секунд)
    local counter=0
    local tunnel_url=""
    
    while [ $counter -lt 30 ]; do
        sleep 1
        counter=$((counter + 1))
        
        # Проверяем, что процесс еще жив
        if ! ps -p $ssh_pid > /dev/null 2>&1; then
            log_message "SSH процесс завершился преждевременно"
            cat "$output_file" >> "$LOG_FILE"
            rm -f "$output_file" "$TUNNEL_PID_FILE"
            return 1
        fi
        
        # Ищем URL в выводе (формат: https://634bfe45ae6b61.lhr.life)
        tunnel_url=$(grep -oE 'https://[a-zA-Z0-9]+\.lhr\.life' "$output_file" | head -1)
        
        if [ -n "$tunnel_url" ]; then
            log_message "Туннель создан: $tunnel_url"
            echo "$tunnel_url" > "$TUNNEL_URL_FILE"
            rm -f "$output_file"

            # Отправляем URL в Telegram (отключено, теперь отправляет только бот)
            # send_telegram_message "$tunnel_url"

            return 0
        fi
    done
    
    log_message "Не удалось получить URL туннеля за 30 секунд"
    log_message "Вывод SSH:"
    cat "$output_file" >> "$LOG_FILE"
    rm -f "$output_file"
    
    # Убиваем процесс если URL не получен
    kill $ssh_pid 2>/dev/null
    rm -f "$TUNNEL_PID_FILE"
    
    return 1
}

# Остановка туннеля
stop_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        local pid=$(cat "$TUNNEL_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            log_message "Останавливаем туннель (PID: $pid)..."
            kill "$pid" 2>/dev/null
            sleep 2
            # Если не завершился - принудительно
            if ps -p "$pid" > /dev/null 2>&1; then
                kill -9 "$pid" 2>/dev/null
            fi
        fi
        rm -f "$TUNNEL_PID_FILE"
    fi
    rm -f "$TUNNEL_URL_FILE"
    log_message "Туннель остановлен"
}

# Основная логика
log_message "=== Проверка SSH-туннеля ==="

# Обработка аргументов командной строки
case "${1:-}" in
    stop)
        stop_tunnel
        exit 0
        ;;
    restart)
        stop_tunnel
        sleep 2
        start_tunnel
        exit $?
        ;;
    status)
        if check_tunnel_running; then
            url=$(get_current_url)
            log_message "Туннель работает. URL: $url"
            echo "$url"
            exit 0
        else
            log_message "Туннель не запущен"
            exit 1
        fi
        ;;
    url)
        url=$(get_current_url)
        if [ -n "$url" ]; then
            echo "$url"
            exit 0
        else
            echo "URL не найден"
            exit 1
        fi
        ;;
    send)
        # Отправить текущий URL в Telegram
        url=$(get_current_url)
        if [ -n "$url" ]; then
            send_telegram_message "$url"
            exit 0
        else
            log_message "Нет активного URL для отправки"
            exit 1
        fi
        ;;
esac

# По умолчанию - проверка и запуск/перезапуск если нужно

# Проверяем процесс
if check_tunnel_process; then
    # Процесс есть, проверяем здоровье
    if check_tunnel_health; then
        url=$(get_current_url)
        log_message "Туннель работает нормально. URL: $url"
        exit 0
    else
        # Процесс есть, но туннель не работает - перезапускаем
        log_message "Туннель не отвечает, перезапуск..."
        stop_tunnel
        sleep 2
        start_tunnel
        exit $?
    fi
fi

# Процесса нет - запускаем
start_tunnel
exit $?

