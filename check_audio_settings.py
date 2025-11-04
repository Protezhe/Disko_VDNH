#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки настроек аудиомониторинга.
Показывает значения из конфига и из работающего сервера.
"""

import json
import os
import requests


def check_config():
    """Проверка значений в конфиге"""
    config_file = 'scheduler_config.json'
    
    if not os.path.exists(config_file):
        print(f"❌ Файл конфига не найден: {config_file}")
        return None
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print("📄 Настройки из конфига (scheduler_config.json):")
        print(f"   audio_threshold: {config.get('audio_threshold', 'НЕ ЗАДАНО')}")
        print(f"   audio_silence_duration: {config.get('audio_silence_duration', 'НЕ ЗАДАНО')}с")
        print(f"   audio_sound_confirmation_duration: {config.get('audio_sound_confirmation_duration', 'НЕ ЗАДАНО')}с")
        print(f"   audio_buffer_size: {config.get('audio_buffer_size', 'НЕ ЗАДАНО')}")
        print(f"   audio_device_index: {config.get('audio_device_index', 'НЕ ЗАДАНО')}")
        print(f"   monitoring_enabled: {config.get('monitoring_enabled', 'НЕ ЗАДАНО')}")
        print()
        
        return config
        
    except Exception as e:
        print(f"❌ Ошибка чтения конфига: {e}")
        return None


def check_server():
    """Проверка значений на работающем сервере"""
    try:
        response = requests.get('http://localhost:5002/api/settings', timeout=5)
        
        if response.status_code == 200:
            settings = response.json()
            print("🌐 Настройки с работающего сервера (API):")
            print(f"   audio_threshold: {settings.get('audio_threshold', 'НЕ ЗАДАНО')}")
            print(f"   audio_silence_duration: {settings.get('audio_silence_duration', 'НЕ ЗАДАНО')}с")
            print(f"   audio_sound_confirmation_duration: {settings.get('audio_sound_confirmation_duration', 'НЕ ЗАДАНО')}с")
            print(f"   audio_buffer_size: {settings.get('audio_buffer_size', 'НЕ ЗАДАНО')}")
            print(f"   audio_device_index: {settings.get('audio_device_index', 'НЕ ЗАДАНО')}")
            print(f"   monitoring_enabled: {settings.get('monitoring_enabled', 'НЕ ЗАДАНО')}")
            print()
            
            return settings
        else:
            print(f"❌ Ошибка получения настроек с сервера: HTTP {response.status_code}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("❌ Не удалось подключиться к серверу (возможно он не запущен)")
        print("   Запустите сервер: ./start_server.sh")
        return None
    except Exception as e:
        print(f"❌ Ошибка при обращении к серверу: {e}")
        return None


def compare_settings(config, server):
    """Сравнение настроек из конфига и сервера"""
    if not config or not server:
        return
    
    print("🔍 Сравнение настроек:")
    
    keys = ['audio_threshold', 'audio_silence_duration', 'audio_sound_confirmation_duration', 
            'audio_buffer_size', 'audio_device_index', 'monitoring_enabled']
    
    differences = []
    for key in keys:
        config_val = config.get(key)
        server_val = server.get(key)
        
        if config_val != server_val:
            differences.append(key)
            print(f"   ⚠️  {key}: конфиг={config_val}, сервер={server_val}")
    
    if not differences:
        print("   ✅ Все настройки совпадают")
    else:
        print()
        print("💡 Обнаружены расхождения!")
        print("   Это нормально если настройки были изменены через веб-интерфейс")
        print("   после запуска сервера. Значения из памяти сервера будут сохранены")
        print("   в конфиг при следующем изменении настроек.")


def main():
    print("=" * 60)
    print("🎵 ПРОВЕРКА НАСТРОЕК АУДИОМОНИТОРИНГА")
    print("=" * 60)
    print()
    
    # Проверяем конфиг
    config = check_config()
    
    # Проверяем сервер
    server = check_server()
    
    # Сравниваем
    compare_settings(config, server)
    
    print()
    print("=" * 60)


if __name__ == '__main__':
    main()

