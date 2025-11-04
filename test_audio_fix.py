#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для тестирования исправлений Segmentation Fault
Проверяет корректность остановки/запуска аудио мониторинга
"""

import os
import sys
import time
from pathlib import Path

# Получаем директорию скрипта
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from audio_monitor import AudioMonitor

def log(message):
    """Вывод с временной меткой"""
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

def test_audio_monitor():
    """Тест цикла запуск-остановка аудио мониторинга"""
    
    print("=" * 70)
    print("ТЕСТ ИСПРАВЛЕНИЯ SEGMENTATION FAULT")
    print("=" * 70)
    print()
    
    # Находим конфиг
    config_file = script_dir / 'scheduler_config.json'
    if not config_file.exists():
        log("❌ Файл конфигурации не найден: scheduler_config.json")
        return False
    
    log(f"✓ Найден конфиг: {config_file}")
    
    # Количество тестовых циклов
    test_cycles = 5
    log(f"Запускаем {test_cycles} циклов теста запуска/остановки")
    print()
    
    for cycle in range(1, test_cycles + 1):
        print("-" * 70)
        log(f"ЦИКЛ {cycle}/{test_cycles}")
        print("-" * 70)
        
        try:
            # Создаем экземпляр AudioMonitor
            log("Создаю AudioMonitor...")
            monitor = AudioMonitor(config_file=str(config_file))
            monitor.enable_monitoring()
            
            # Запускаем мониторинг
            log("▶ Запускаю мониторинг...")
            success = monitor.start_monitoring()
            
            if not success:
                log("❌ Не удалось запустить мониторинг")
                return False
            
            log("✓ Мониторинг запущен")
            
            # Даем поработать немного
            log("Работа мониторинга 3 секунды...")
            for i in range(3, 0, -1):
                print(f"  {i}...", end='\r', flush=True)
                time.sleep(1)
            print()
            
            # Останавливаем мониторинг
            log("⏹ Останавливаю мониторинг...")
            monitor.stop_monitoring()
            log("✓ Мониторинг остановлен")
            
            # Пауза между циклами
            log("Пауза 2 секунды...")
            time.sleep(2)
            
            # Очистка
            log("Очистка ресурсов...")
            del monitor
            
        except Exception as e:
            log(f"❌ ОШИБКА в цикле {cycle}: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        print()
    
    print("=" * 70)
    log("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    log("Segmentation Fault не обнаружен")
    print("=" * 70)
    return True

def test_quick_stop_start():
    """Тест быстрого запуска/остановки (стресс-тест)"""
    
    print()
    print("=" * 70)
    print("СТРЕСС-ТЕСТ: БЫСТРЫЙ ЗАПУСК/ОСТАНОВКА")
    print("=" * 70)
    print()
    
    config_file = script_dir / 'scheduler_config.json'
    
    try:
        log("Создаю AudioMonitor...")
        monitor = AudioMonitor(config_file=str(config_file))
        monitor.enable_monitoring()
        
        # Быстрые циклы запуск-остановка
        for i in range(1, 11):
            log(f"Быстрый цикл {i}/10...")
            
            monitor.start_monitoring()
            time.sleep(0.5)  # Очень короткая работа
            monitor.stop_monitoring()
            time.sleep(0.3)  # Короткая пауза
        
        log("✅ Стресс-тест пройден успешно!")
        del monitor
        return True
        
    except Exception as e:
        log(f"❌ ОШИБКА в стресс-тесте: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция"""
    
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЙ AUDIO MONITOR" + " " * 15 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    
    # Базовый тест
    log("Запускаю базовый тест...")
    test1_ok = test_audio_monitor()
    
    if not test1_ok:
        log("❌ Базовый тест не пройден!")
        return 1
    
    # Стресс-тест
    log("Запускаю стресс-тест...")
    test2_ok = test_quick_stop_start()
    
    if not test2_ok:
        log("❌ Стресс-тест не пройден!")
        return 1
    
    # Финальное сообщение
    print()
    print("=" * 70)
    print()
    print("  ✅ ✅ ✅  ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ!  ✅ ✅ ✅")
    print()
    print("  Исправления работают корректно.")
    print("  Segmentation Fault не обнаружен.")
    print("  Можно запускать сервер и тестировать саундчек.")
    print()
    print("=" * 70)
    print()
    
    return 0

if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        log("⚠️ Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print()
        log(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

