#!/bin/bash
# Скрипт создания и проверки SSH-туннеля для удаленного доступа через localhost.run

# Настройки
LOG_FILE="ssh_tunnel_monitor.log"
TUNNEL_PID_FILE="ssh_tunnel.pid"
TUNNEL_INFO_FILE="ssh_tunnel_info.txt"
LOCAL_SSH_PORT=22  # Порт SSH на локальной машине (22 по умолчанию, или другой если SSH на другом порту)
SSH_USER="santamozzarella@gmail.com"
SSH_KEY="$HOME/.ssh/id_rsa"
SCRIPT_DIR="$(dirname "$0")"

# Переходим в директорию скрипта
cd "$SCRIPT_DIR"

# Функция логирования
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Получение текущей информации о туннеле
get_current_info() {
    if [ -f "$TUNNEL_INFO_FILE" ]; then
        cat "$TUNNEL_INFO_FILE"
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

    # Дополнительная проверка: ищем ssh процесс с нужными параметрами
    if pgrep -f "ssh.*-R.*:localhost:${LOCAL_SSH_PORT}.*localhost.run" > /dev/null 2>&1; then
        return 0  # Процесс существует
    fi

    return 1  # Процесс не найден
}

# Запуск SSH туннеля
start_tunnel() {
    log_message "Запуск SSH-туннеля для удаленного доступа..."

    # Создаем временный файл для вывода ssh
    local output_file=$(mktemp)

    # Запускаем ssh в фоне
    # -R 0:localhost:22 означает "проброс случайного порта на удаленной стороне к локальному порту 22"
    # localhost.run автоматически назначит порт и вернет информацию о подключении
    if command -v unbuffer &> /dev/null; then
        unbuffer ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 0:localhost:$LOCAL_SSH_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    elif command -v stdbuf &> /dev/null; then
        stdbuf -oL -eL ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 0:localhost:$LOCAL_SSH_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    else
        ssh -i "$SSH_KEY" -tt -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            -R 0:localhost:$LOCAL_SSH_PORT "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    fi

    local ssh_pid=$!
    echo $ssh_pid > "$TUNNEL_PID_FILE"

    log_message "SSH процесс запущен с PID: $ssh_pid"

    # Ждем появления информации о туннеле в выводе (максимум 30 секунд)
    local counter=0
    local tunnel_host=""
    local tunnel_port=""

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

        # Ищем информацию о туннеле в выводе
        # localhost.run возвращает что-то вроде:
        # Connect to your server via SSH:
        # ssh -p 12345 santamozzarella@localhost.run

        # Извлекаем хост и порт
        tunnel_port=$(grep -oP 'ssh -p \K[0-9]+' "$output_file" | head -1)
        tunnel_host=$(grep -oP 'ssh -p [0-9]+ \K[^@]+@[^\s]+' "$output_file" | head -1)

        if [ -n "$tunnel_port" ] && [ -n "$tunnel_host" ]; then
            local full_info="ssh -p $tunnel_port $tunnel_host"
            log_message "SSH туннель создан: $full_info"
            echo "$full_info" > "$TUNNEL_INFO_FILE"
            rm -f "$output_file"
            return 0
        fi
    done

    log_message "Не удалось получить информацию о SSH туннеле за 30 секунд"
    log_message "Вывод SSH:"
    cat "$output_file" >> "$LOG_FILE"
    rm -f "$output_file"

    # Убиваем процесс если информация не получена
    kill $ssh_pid 2>/dev/null
    rm -f "$TUNNEL_PID_FILE"

    return 1
}

# Остановка туннеля
stop_tunnel() {
    if [ -f "$TUNNEL_PID_FILE" ]; then
        local pid=$(cat "$TUNNEL_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            log_message "Останавливаем SSH туннель (PID: $pid)..."
            kill "$pid" 2>/dev/null
            sleep 2
            # Если не завершился - принудительно
            if ps -p "$pid" > /dev/null 2>&1; then
                kill -9 "$pid" 2>/dev/null
            fi
        fi
        rm -f "$TUNNEL_PID_FILE"
    fi
    rm -f "$TUNNEL_INFO_FILE"
    log_message "SSH туннель остановлен"
}

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
        if check_tunnel_process; then
            info=$(get_current_info)
            log_message "SSH туннель работает: $info"
            echo "$info"
            exit 0
        else
            log_message "SSH туннель не запущен"
            exit 1
        fi
        ;;
    url)
        info=$(get_current_info)
        if [ -n "$info" ]; then
            echo "$info"
            exit 0
        else
            echo "Информация о туннеле не найдена"
            exit 1
        fi
        ;;
esac

# По умолчанию - проверка и запуск если нужно
if check_tunnel_process; then
    info=$(get_current_info)
    log_message "SSH туннель работает: $info"
    exit 0
else
    # Процесса нет - запускаем
    start_tunnel
    exit $?
fi
