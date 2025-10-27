#!/bin/bash
# Скрипт запуска сервера дискотеки ВДНХ для Ubuntu

echo "🎀 Запуск веб-сервера планировщика дискотеки ВДНХ"
echo "================================================"
echo ""

# --- 🔹 ДОБАВЛЕНО: подключаем VPN перед запуском сервера ---
VPN_NAME="Disco.ovpn"
echo "🔌 Проверяем VPN-соединение..."

# Проверяем, активен ли VPN
if ! openvpn3 sessions-list | grep -q "$VPN_NAME"; then
    echo "🌐 VPN не активен, подключаем..."
    openvpn3 session-start --config "$VPN_NAME"
    sleep 5
else
    echo "✅ VPN уже подключен"
fi
# ------------------------------------------------------------

# Переходим в директорию скрипта
cd "$(dirname "$0")"

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
echo "🚀 Запускаем сервер..."
echo "================================================"
echo ""

# Активируем виртуальное окружение и запускаем сервер
source venv/bin/activate
python scheduler_server.py

# Деактивируем виртуальное окружение при выходе
deactivate