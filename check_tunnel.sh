#!/bin/bash
# Универсальный скрипт создания и проверки SSH-туннеля через localhost.run
# Поддерживает два режима: web (проброс веб-порта) и ssh (проброс SSH)

# Настройки
LOG_FILE="tunnel_monitor.log"
TUNNEL_PID_FILE="tunnel.pid"
TUNNEL_INFO_FILE="tunnel_info.txt"
TUNNEL_MODE_FILE="tunnel_mode.txt"
WEB_PORT=5002
SSH_PORT=22
SSH_USER="santamozzarella@gmail.com"
SSH_KEY="$HOME/.ssh/id_rsa"
SCRIPT_DIR="$(dirname "$0")"

# Переходим в директорию скрипта
cd "$SCRIPT_DIR"

# Функция логирования
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Получение текущего режима туннеля
get_current_mode() {
    if [ -f "$TUNNEL_MODE_FILE" ]; then
        cat "$TUNNEL_MODE_FILE"
    else
        echo "web"  # По умолчанию web режим
    fi
}

# Установка режима туннеля
set_mode() {
    echo "$1" > "$TUNNEL_MODE_FILE"
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

    # Дополнительная проверка: ищем ssh процесс с localhost.run
    if pgrep -f "ssh.*localhost.run" > /dev/null 2>&1; then
        return 0  # Процесс существует
    fi

    return 1  # Процесс не найден
}

# Проверка работоспособности web туннеля
check_web_tunnel_health() {
    local url=$(get_current_info)

    if [ -z "$url" ]; then
        return 1  # URL не найден
    fi

    # Делаем запрос к туннелю и проверяем ответ
    local response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null)

    # Если получили ответ (любой код кроме 000 = timeout)
    if [ "$response" != "000" ]; then
        # Проверяем что это не "no tunnel here"
        local body=$(curl -s --max-time 10 "$url" 2>/dev/null)
        if echo "$body" | grep -qi "no tunnel"; then
            return 1
        fi
        return 0  # Туннель работает
    fi

    return 1
}

# Отправка уведомления в Telegram через Python
send_telegram_notification() {
    local mode="$1"
    local info="$2"

    local venv_python="$SCRIPT_DIR/venv/bin/python"
    if [ ! -f "$venv_python" ]; then
        venv_python="python3"
    fi

    cd "$SCRIPT_DIR"
    "$venv_python" - "$mode" "$info" << 'PYTHON_SCRIPT'
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')
from telegram_bot import TelegramNotifier

mode = sys.argv[1] if len(sys.argv) > 1 else "unknown"
info = sys.argv[2] if len(sys.argv) > 2 else "Информация не определена"

notifier = TelegramNotifier()

if mode == "web":
    message = f"<b>Веб-туннель создан!</b>\n\nПубличная ссылка:\n{info}"
elif mode == "ssh":
    message = f"<b>SSH туннель создан!</b>\n\nКоманда для подключения:\n<code>{info}</code>"
else:
    message = f"<b>Туннель создан!</b>\n\n{info}"

if notifier.send_message(message):
    print("[Tunnel] Уведомление отправлено в Telegram")
else:
    print("[Tunnel] Не удалось отправить уведомление в Telegram")
PYTHON_SCRIPT
}

# Запуск туннеля
start_tunnel() {
    local mode="${1:-$(get_current_mode)}"

    log_message "Запуск туннеля в режиме: $mode"
    set_mode "$mode"

    # Проверяем наличие SSH ключа
    if [ ! -f "$SSH_KEY" ]; then
        log_message "ОШИБКА: SSH ключ не найден: $SSH_KEY"
        log_message "Создайте SSH ключ командой: ssh-keygen -t rsa -b 4096"
        return 1
    fi

    # Создаем временный файл для вывода ssh
    local output_file=$(mktemp)

    # Определяем параметры в зависимости от режима
    local ssh_args=""
    if [ "$mode" = "web" ]; then
        ssh_args="-R 80:localhost:$WEB_PORT"
    elif [ "$mode" = "ssh" ]; then
        ssh_args="-R 0:localhost:$SSH_PORT"
    else
        log_message "Неизвестный режим: $mode"
        rm -f "$output_file"
        return 1
    fi

    # Запускаем ssh в фоне
    if command -v unbuffer &> /dev/null; then
        unbuffer ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            $ssh_args "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    elif command -v stdbuf &> /dev/null; then
        stdbuf -oL -eL ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            $ssh_args "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    else
        ssh -i "$SSH_KEY" -tt -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
            $ssh_args "$SSH_USER@localhost.run" > "$output_file" 2>&1 &
    fi

    local ssh_pid=$!
    echo $ssh_pid > "$TUNNEL_PID_FILE"

    log_message "SSH процесс запущен с PID: $ssh_pid"

    # Ждем появления информации о туннеле в выводе (максимум 30 секунд)
    local counter=0
    local tunnel_info=""

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

        # Ищем информацию в зависимости от режима
        if [ "$mode" = "web" ]; then
            # Ищем URL вида https://xxxxx.lhr.life
            tunnel_info=$(grep -oE 'https://[a-zA-Z0-9]+\.lhr\.life' "$output_file" | head -1)
        elif [ "$mode" = "ssh" ]; then
            # Для SSH ищем хост и пароль
            # Формат вывода localhost.run:
            # ssh user@xxxxxx.lhr.life
            # password

            log_message "Парсинг SSH туннеля из вывода..."

            # Ищем строку вида: ssh user@xxxxx.lhr.life
            local ssh_host=$(grep -oE 'ssh [^@]+@[a-zA-Z0-9]+\.lhr\.life' "$output_file" | head -1)
            log_message "Найден SSH хост: $ssh_host"

            if [ -n "$ssh_host" ]; then
                # Ищем пароль (обычно следует после строки с ssh)
                # Пароль может содержать буквы, цифры, точки, дефисы, подчеркивания и символ |
                local password=$(grep -A 10 "$ssh_host" "$output_file" | grep -E '^[a-zA-Z0-9|.\-_]+$' | head -1 | tr -d ' ')
                log_message "Найден пароль: ${password:0:3}***" # логируем только первые 3 символа

                # Формируем вывод: заменяем user на orangepi
                local final_host=$(echo "$ssh_host" | sed 's/ssh [^@]*@/ssh orangepi@/')

                if [ -n "$password" ]; then
                    tunnel_info="${final_host}"$'\n'"${password}"
                else
                    tunnel_info="${final_host}"
                fi
            else
                log_message "SSH хост не найден в выводе, сохраняем полный вывод в лог"
                cat "$output_file" >> "$LOG_FILE"
            fi
        fi

        if [ -n "$tunnel_info" ]; then
            log_message "Туннель ($mode) создан: $tunnel_info"
            echo "$tunnel_info" > "$TUNNEL_INFO_FILE"
            rm -f "$output_file"

            # Отправляем уведомление (отключено, отправляет только бот по запросу)
            # send_telegram_notification "$mode" "$tunnel_info"

            return 0
        fi
    done

    log_message "Не удалось получить информацию о туннеле за 30 секунд"
    log_message "Вывод SSH:"
    cat "$output_file" >> "$LOG_FILE"

    # Проверяем на типичные ошибки
    if grep -q "Permission denied" "$output_file"; then
        log_message "ОШИБКА: Проблема с SSH ключом или аутентификацией"
    elif grep -q "Address already in use" "$output_file"; then
        log_message "ОШИБКА: Порт уже используется"
    elif grep -q "Connection refused" "$output_file"; then
        log_message "ОШИБКА: Не удалось подключиться к localhost.run"
    fi

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
    rm -f "$TUNNEL_INFO_FILE"
    log_message "Туннель остановлен"
}

# Переключение режима туннеля
switch_mode() {
    local new_mode="$1"
    local current_mode=$(get_current_mode)

    if [ "$new_mode" = "$current_mode" ]; then
        log_message "Туннель уже работает в режиме $new_mode"
        return 0
    fi

    log_message "Переключение туннеля с $current_mode на $new_mode"
    stop_tunnel
    sleep 2
    start_tunnel "$new_mode"
    return $?
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
            mode=$(get_current_mode)
            log_message "Туннель ($mode) работает: $info"
            echo "$info"
            exit 0
        else
            log_message "Туннель не запущен"
            exit 1
        fi
        ;;
    info|url)
        info=$(get_current_info)
        if [ -n "$info" ]; then
            echo "$info"
            exit 0
        else
            echo "Информация о туннеле не найдена"
            exit 1
        fi
        ;;
    mode)
        echo $(get_current_mode)
        exit 0
        ;;
    web)
        # Запустить или переключить на web режим
        if check_tunnel_process; then
            switch_mode "web"
        else
            start_tunnel "web"
        fi
        exit $?
        ;;
    ssh)
        # Запустить или переключить на ssh режим
        if check_tunnel_process; then
            switch_mode "ssh"
        else
            start_tunnel "ssh"
        fi
        exit $?
        ;;
esac

# По умолчанию - проверка и запуск если нужно (в текущем режиме)
if check_tunnel_process; then
    mode=$(get_current_mode)

    # Для web режима дополнительно проверяем здоровье
    if [ "$mode" = "web" ]; then
        if check_web_tunnel_health; then
            info=$(get_current_info)
            log_message "Туннель ($mode) работает нормально: $info"
            exit 0
        else
            # Процесс есть, но туннель не работает - перезапускаем
            log_message "Туннель не отвечает, перезапуск..."
            stop_tunnel
            sleep 2
            start_tunnel "$mode"
            exit $?
        fi
    else
        info=$(get_current_info)
        log_message "Туннель ($mode) работает: $info"
        exit 0
    fi
fi

# Процесса нет - запускаем в текущем режиме
start_tunnel
exit $?
