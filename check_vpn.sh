#!/bin/bash
# Скрипт проверки и восстановления VPN-соединения

# Настройки
VPN_CONFIG="Disco.ovpn"
LOG_FILE="vpn_monitor.log"
TEST_HOST="10.8.0.9"  # IP адрес в VPN сети для проверки доступности
MAX_RETRIES=50

# Переходим в директорию скрипта
cd "$(dirname "$0")"

# Функция логирования
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Проверка 1: Проверяем, активна ли сессия VPN
check_vpn_session() {
    if openvpn3 sessions-list 2>/dev/null | grep -q "$VPN_CONFIG"; then
        return 0  # VPN сессия активна
    else
        return 1  # VPN сессия не активна
    fi
}

# Проверка 2: Проверяем реальную доступность через ping
check_vpn_connectivity() {
    if ping -c 2 -W 3 "$TEST_HOST" >/dev/null 2>&1; then
        return 0  # Соединение работает
    else
        return 1  # Соединение не работает
    fi
}

# Функция переподключения VPN
reconnect_vpn() {
    log_message "Попытка переподключения VPN..."
    
    # Сначала отключаем все активные сессии
    openvpn3 sessions-list 2>/dev/null | grep "$VPN_CONFIG" >/dev/null
    if [ $? -eq 0 ]; then
        log_message "Отключаем существующую сессию VPN..."
        SESSION_PATH=$(openvpn3 sessions-list | grep "$VPN_CONFIG" -A 1 | grep "Path:" | awk '{print $2}')
        if [ ! -z "$SESSION_PATH" ]; then
            openvpn3 session-manage --session-path "$SESSION_PATH" --disconnect 2>/dev/null
            sleep 3
        fi
    fi
    
    # Подключаемся заново
    log_message "Запускаем новую VPN сессию..."
    if openvpn3 session-start --config "$VPN_CONFIG" 2>&1 | tee -a "$LOG_FILE"; then
        sleep 5
        
        # Проверяем, что соединение установлено
        if check_vpn_connectivity; then
            log_message "VPN успешно переподключен"
            return 0
        else
            log_message "VPN подключен, но сеть недоступна"
            return 1
        fi
    else
        log_message "Ошибка при подключении VPN"
        return 1
    fi
}

# Основная логика
log_message "=== Проверка VPN соединения ==="

# Проверяем наличие VPN сессии
if ! check_vpn_session; then
    log_message "VPN сессия не активна"
    reconnect_vpn
    exit $?
fi

# Проверяем реальную доступность
if ! check_vpn_connectivity; then
    log_message "VPN сессия активна, но сеть недоступна (хост $TEST_HOST не отвечает)"
    
    # Пробуем переподключиться несколько раз
    for i in $(seq 1 $MAX_RETRIES); do
        log_message "Попытка восстановления $i из $MAX_RETRIES..."
        if reconnect_vpn; then
            exit 0
        fi
        sleep 5
    done
    
    log_message "Не удалось восстановить VPN после $MAX_RETRIES попыток"
    exit 1
fi

log_message "VPN работает нормально"
exit 0

