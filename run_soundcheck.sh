#!/bin/bash
# Скрипт для запуска саундчека

# Получаем директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Активируем виртуальное окружение если оно существует
if [ -f "venv/bin/activate" ]; then
    echo "Активирую виртуальное окружение..."
    source venv/bin/activate
fi

# Запускаем скрипт саундчека
echo "Запуск саундчека..."
python3 soundcheck.py

# Ждем нажатия клавиши перед закрытием (опционально)
# read -p "Нажмите Enter для выхода..."

