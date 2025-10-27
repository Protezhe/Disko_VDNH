#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска веб-сервера планировщика с активацией виртуального окружения
"""

import os
import sys
import subprocess
import platform

def activate_venv_and_run():
    """Активирует виртуальное окружение и запускает сервер"""
    
    print("🎀 Запуск веб-сервера планировщика дискотеки ВДНХ")
    print("=" * 60)
    
    # Определяем путь к виртуальному окружению
    if platform.system() == "Windows":
        venv_python = os.path.join("venv", "Scripts", "python.exe")
        venv_activate = os.path.join("venv", "Scripts", "activate.bat")
    else:
        venv_python = os.path.join("venv", "bin", "python")
        venv_activate = os.path.join("venv", "bin", "activate")
    
    # Проверяем существование виртуального окружения
    if not os.path.exists(venv_python):
        print("❌ Виртуальное окружение не найдено!")
        print("Создайте виртуальное окружение командой:")
        print("python -m venv venv")
        return False
    
    print(f"✅ Виртуальное окружение найдено: {venv_python}")
    
    # Проверяем существование файла сервера
    server_file = "scheduler_server.py"
    if not os.path.exists(server_file):
        print(f"❌ Файл {server_file} не найден!")
        return False
    
    print(f"✅ Файл сервера найден: {server_file}")
    
    # Проверяем существование веб-интерфейса
    web_interface = "web_interface.html"
    if not os.path.exists(web_interface):
        print(f"⚠️ Файл {web_interface} не найден!")
        print("Веб-интерфейс будет недоступен")
    else:
        print(f"✅ Веб-интерфейс Hello Kitty найден: {web_interface}")
    
    print("=" * 60)
    print("🚀 Запускаем сервер...")
    print("=" * 60)
    
    try:
        # Запускаем сервер через виртуальное окружение
        print(f"🚀 Запускаем: {venv_python} {server_file}")
        subprocess.run([venv_python, server_file], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка запуска сервера: {e}")
        return False
    except KeyboardInterrupt:
        print("\n🛑 Сервер остановлен пользователем")
        return True
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    activate_venv_and_run()
