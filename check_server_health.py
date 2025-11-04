#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки здоровья сервера и диагностики проблем
"""

import os
import sys
import json
import traceback
from pathlib import Path


def get_exe_dir():
    """Получает директорию где находится скрипт"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def check_config_file():
    """Проверяет файл конфигурации на валидность"""
    config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
    
    print("=" * 60)
    print("ПРОВЕРКА КОНФИГУРАЦИОННОГО ФАЙЛА")
    print("=" * 60)
    print(f"Путь: {config_file}")
    
    if not os.path.exists(config_file):
        print("❌ ОШИБКА: Файл не существует!")
        return False
    
    print("✓ Файл существует")
    
    # Проверяем размер файла
    file_size = os.path.getsize(config_file)
    print(f"Размер файла: {file_size} байт")
    
    if file_size == 0:
        print("❌ ОШИБКА: Файл пустой!")
        return False
    
    if file_size > 1024 * 1024:  # Больше 1 МБ
        print("⚠ ПРЕДУПРЕЖДЕНИЕ: Файл слишком большой!")
    
    # Проверяем содержимое
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"Содержимое файла ({len(content)} символов):")
        print("-" * 60)
        print(content[:500])  # Первые 500 символов
        if len(content) > 500:
            print("...")
        print("-" * 60)
        
    except Exception as e:
        print(f"❌ ОШИБКА чтения файла: {e}")
        return False
    
    # Проверяем парсинг JSON
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print("✓ JSON валиден")
        print(f"Ключей в конфиге: {len(config)}")
        
        # Проверяем каждое значение на наличие некорректных типов
        problematic_values = []
        
        def check_value(key, value, path=""):
            """Рекурсивная проверка значений"""
            current_path = f"{path}.{key}" if path else key
            
            if isinstance(value, dict):
                for k, v in value.items():
                    check_value(k, v, current_path)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    check_value(f"[{i}]", item, current_path)
            elif isinstance(value, float):
                # Проверяем на NaN и Infinity
                import math
                if math.isnan(value):
                    problematic_values.append(f"{current_path} = NaN")
                elif math.isinf(value):
                    problematic_values.append(f"{current_path} = Infinity")
            elif value is None:
                # None это нормально для JSON
                pass
            elif not isinstance(value, (str, int, bool)):
                problematic_values.append(f"{current_path} = {type(value).__name__} (некорректный тип)")
        
        for key, value in config.items():
            check_value(key, value)
        
        if problematic_values:
            print("⚠ НАЙДЕНЫ ПРОБЛЕМНЫЕ ЗНАЧЕНИЯ:")
            for problem in problematic_values:
                print(f"  - {problem}")
        else:
            print("✓ Все значения корректны")
        
        # Проверяем ключевые поля
        required_fields = ['scheduled_days', 'start_time', 'stop_time', 'scheduler_enabled']
        missing_fields = [field for field in required_fields if field not in config]
        
        if missing_fields:
            print(f"⚠ ОТСУТСТВУЮТ ОБЯЗАТЕЛЬНЫЕ ПОЛЯ: {missing_fields}")
        else:
            print("✓ Все обязательные поля присутствуют")
        
        # Показываем текущие настройки
        print("\nТЕКУЩИЕ НАСТРОЙКИ:")
        for key, value in sorted(config.items()):
            print(f"  {key}: {value}")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ ОШИБКА парсинга JSON: {e}")
        print(f"Строка {e.lineno}, позиция {e.colno}")
        return False
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        traceback.print_exc()
        return False


def check_file_permissions():
    """Проверяет права доступа к файлу"""
    config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
    
    print("\n" + "=" * 60)
    print("ПРОВЕРКА ПРАВ ДОСТУПА")
    print("=" * 60)
    
    if not os.path.exists(config_file):
        print("❌ Файл не существует")
        return False
    
    # Проверяем права на чтение
    if os.access(config_file, os.R_OK):
        print("✓ Права на чтение: ДА")
    else:
        print("❌ Права на чтение: НЕТ")
        return False
    
    # Проверяем права на запись
    if os.access(config_file, os.W_OK):
        print("✓ Права на запись: ДА")
    else:
        print("❌ Права на запись: НЕТ")
        return False
    
    # Проверяем права на директорию
    config_dir = os.path.dirname(config_file)
    if os.access(config_dir, os.W_OK):
        print("✓ Права на запись в директорию: ДА")
    else:
        print("❌ Права на запись в директорию: НЕТ")
        return False
    
    return True


def check_disk_space():
    """Проверяет свободное место на диске"""
    config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
    
    print("\n" + "=" * 60)
    print("ПРОВЕРКА ДИСКОВОГО ПРОСТРАНСТВА")
    print("=" * 60)
    
    try:
        stat = os.statvfs(os.path.dirname(config_file))
        free_space = stat.f_bavail * stat.f_frsize
        total_space = stat.f_blocks * stat.f_frsize
        used_space = total_space - free_space
        
        free_mb = free_space / (1024 * 1024)
        total_mb = total_space / (1024 * 1024)
        used_mb = used_space / (1024 * 1024)
        percent_used = (used_space / total_space) * 100
        
        print(f"Всего: {total_mb:.2f} МБ")
        print(f"Использовано: {used_mb:.2f} МБ ({percent_used:.1f}%)")
        print(f"Свободно: {free_mb:.2f} МБ")
        
        if free_mb < 100:
            print("⚠ ПРЕДУПРЕЖДЕНИЕ: Мало свободного места (< 100 МБ)")
            return False
        else:
            print("✓ Достаточно свободного места")
            return True
            
    except Exception as e:
        print(f"⚠ Не удалось проверить: {e}")
        return True  # Не критично


def create_backup():
    """Создает резервную копию конфига"""
    config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
    backup_file = os.path.join(get_exe_dir(), 'scheduler_config.json.backup')
    
    print("\n" + "=" * 60)
    print("СОЗДАНИЕ РЕЗЕРВНОЙ КОПИИ")
    print("=" * 60)
    
    if not os.path.exists(config_file):
        print("❌ Файл конфига не существует")
        return False
    
    try:
        import shutil
        shutil.copy2(config_file, backup_file)
        print(f"✓ Резервная копия создана: {backup_file}")
        return True
    except Exception as e:
        print(f"❌ Ошибка создания резервной копии: {e}")
        return False


def test_json_write():
    """Тестирует запись в JSON файл"""
    config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
    test_file = os.path.join(get_exe_dir(), 'test_write.json')
    
    print("\n" + "=" * 60)
    print("ТЕСТ ЗАПИСИ JSON")
    print("=" * 60)
    
    try:
        # Пробуем прочитать существующий конфиг
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Пробуем записать в тестовый файл
        with open(test_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"✓ Тестовая запись успешна: {test_file}")
        
        # Проверяем, что файл можно прочитать обратно
        with open(test_file, 'r', encoding='utf-8') as f:
            test_config = json.load(f)
        
        print("✓ Тестовое чтение успешно")
        
        # Удаляем тестовый файл
        os.remove(test_file)
        print("✓ Тестовый файл удален")
        
        return True
        
    except Exception as e:
        print(f"❌ ОШИБКА тестовой записи: {e}")
        traceback.print_exc()
        
        # Пробуем удалить тестовый файл если он остался
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except:
                pass
        
        return False


def main():
    """Главная функция"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "ДИАГНОСТИКА СЕРВЕРА ДИСКОТЕКИ" + " " * 18 + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    
    all_checks_passed = True
    
    # 1. Проверка конфига
    if not check_config_file():
        all_checks_passed = False
    
    # 2. Проверка прав доступа
    if not check_file_permissions():
        all_checks_passed = False
    
    # 3. Проверка дискового пространства
    if not check_disk_space():
        all_checks_passed = False
    
    # 4. Тест записи
    if not test_json_write():
        all_checks_passed = False
    
    # 5. Создание резервной копии
    create_backup()
    
    # Итоговый результат
    print("\n" + "=" * 60)
    if all_checks_passed:
        print("✓✓✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ✓✓✓")
        print("\nСервер должен работать нормально.")
        print("Если проблемы продолжаются, проверьте:")
        print("  1. Логи сервера (вывод в консоль)")
        print("  2. Системные логи Ubuntu (/var/log/syslog)")
        print("  3. Использование памяти (free -h)")
        print("  4. Использование CPU (top)")
    else:
        print("❌❌❌ ОБНАРУЖЕНЫ ПРОБЛЕМЫ ❌❌❌")
        print("\nРекомендуемые действия:")
        print("  1. Проверьте права доступа к файлам")
        print("  2. Освободите место на диске если нужно")
        print("  3. Восстановите конфиг из резервной копии")
        print("  4. Перезапустите сервер")
    print("=" * 60)
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        traceback.print_exc()

