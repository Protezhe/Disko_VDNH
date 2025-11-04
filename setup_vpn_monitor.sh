#!/bin/bash
# Скрипт установки автоматического мониторинга VPN

echo "Установка мониторинга VPN соединения"
echo "================================================"
echo ""

# Переходим в директорию скрипта
cd "$(dirname "$0")"

# Делаем скрипт проверки исполняемым
chmod +x check_vpn.sh

echo "Выберите метод автоматического мониторинга:"
echo ""
echo "1) systemd timer (рекомендуется для Ubuntu/Debian)"
echo "2) cron (универсальный метод)"
echo ""
read -p "Ваш выбор (1 или 2): " choice

case $choice in
    1)
        echo ""
        echo "Настройка через systemd..."
        echo ""
        
        # Копируем файлы в systemd
        sudo cp vpn-monitor.service /etc/systemd/system/
        sudo cp vpn-monitor.timer /etc/systemd/system/
        
        # Перезагружаем systemd
        sudo systemctl daemon-reload
        
        # Включаем и запускаем timer
        sudo systemctl enable vpn-monitor.timer
        sudo systemctl start vpn-monitor.timer
        
        echo ""
        echo "Мониторинг VPN настроен через systemd"
        echo ""
        echo "Полезные команды:"
        echo "  Статус таймера:  sudo systemctl status vpn-monitor.timer"
        echo "  Статус сервиса:  sudo systemctl status vpn-monitor.service"
        echo "  Просмотр логов:  sudo journalctl -u vpn-monitor.service -f"
        echo "  Остановить:      sudo systemctl stop vpn-monitor.timer"
        echo "  Запустить:       sudo systemctl start vpn-monitor.timer"
        echo "  Ручная проверка: sudo systemctl start vpn-monitor.service"
        ;;
        
    2)
        echo ""
        echo "Настройка через cron..."
        echo ""
        
        # Получаем полный путь к скрипту
        SCRIPT_PATH="$(pwd)/check_vpn.sh"
        
        # Добавляем задачу в crontab (каждый час)
        (crontab -l 2>/dev/null; echo "0 * * * * $SCRIPT_PATH >> $(pwd)/vpn_monitor.log 2>&1") | crontab -
        
        echo ""
        echo "Мониторинг VPN настроен через cron"
        echo ""
        echo "Полезные команды:"
        echo "  Просмотр crontab: crontab -l"
        echo "  Просмотр логов:   tail -f vpn_monitor.log"
        echo "  Удалить задачу:   crontab -e (удалить строку с check_vpn.sh)"
        echo "  Ручная проверка:  bash check_vpn.sh"
        ;;
        
    *)
        echo "Неверный выбор. Выход."
        exit 1
        ;;
esac

echo ""
echo "================================================"
echo "Настройка завершена!"
echo ""
echo "Проверка VPN будет выполняться каждый час"
echo "Логи сохраняются в: $(pwd)/vpn_monitor.log"
echo ""
echo "Для ручной проверки VPN выполните:"
echo "  bash check_vpn.sh"

