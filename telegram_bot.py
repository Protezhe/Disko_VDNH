#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм-бот для отправки уведомлений о дискотеке.
Отправляет уведомления о начале/завершении дискотеки и о состоянии звука.
"""

import requests
import json
import os
import sys
from datetime import datetime


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        # Если запущено из exe
        return os.path.dirname(sys.executable)
    else:
        # Если запущено из скрипта
        return os.path.dirname(os.path.abspath(__file__))


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self, config_file=None):
        """
        Инициализация бота
        
        Args:
            config_file (str): Путь к файлу конфигурации
        """
        if config_file is None:
            config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
        
        self.config_file = config_file
        self.bot_token = None
        self.chat_ids = []
        self.enabled = False
        self.notifications_enabled = True  # По умолчанию уведомления включены
        
        self.load_config()
    
    def load_config(self):
        """Загрузка конфигурации из файла"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                self.bot_token = config.get('telegram_bot_token', '')
                self.chat_ids = config.get('telegram_chat_ids', [])
                self.notifications_enabled = config.get('telegram_notifications_enabled', True)
                
                # Проверяем, что токен не пустой и есть хотя бы один chat_id
                if self.bot_token and self.chat_ids:
                    self.enabled = True
                    status = "включены" if self.notifications_enabled else "отключены"
                    print(f"[Telegram Bot] Бот активирован. Количество подписчиков: {len(self.chat_ids)}. Уведомления {status}")
                else:
                    self.enabled = False
                    if not self.bot_token:
                        print("[Telegram Bot] Бот не активирован: токен не задан")
                    elif not self.chat_ids:
                        print("[Telegram Bot] Бот не активирован: нет подписчиков (chat_ids пуст)")
            else:
                print(f"[Telegram Bot] Файл конфигурации не найден: {self.config_file}")
                self.enabled = False
                
        except Exception as e:
            print(f"[Telegram Bot] Ошибка при загрузке конфигурации: {e}")
            self.enabled = False
    
    def send_message(self, message, parse_mode='HTML'):
        """
        Отправка сообщения в Telegram
        
        Args:
            message (str): Текст сообщения
            parse_mode (str): Режим парсинга (HTML, Markdown)
            
        Returns:
            bool: True если сообщение отправлено успешно хотя бы одному получателю
        """
        if not self.enabled:
            return False
        
        if not self.notifications_enabled:
            print("[Telegram Bot] Уведомления отключены в конфиге")
            return False
        
        success = False
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        for chat_id in self.chat_ids:
            try:
                payload = {
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': parse_mode
                }
                
                response = requests.post(api_url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    success = True
                    print(f"[Telegram Bot] Сообщение отправлено в чат {chat_id}")
                else:
                    print(f"[Telegram Bot] Ошибка отправки в чат {chat_id}: {response.status_code} - {response.text}")
                    
            except Exception as e:
                print(f"[Telegram Bot] Ошибка при отправке сообщения в чат {chat_id}: {e}")
        
        return success
    
    def notify_disco_started(self):
        """Уведомление о начале дискотеки"""
        now = datetime.now()
        message = (
            f"🎉 <b>Дискотека началась!</b>\n\n"
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"🎵 Музыка запущена"
        )
        return self.send_message(message)
    
    def notify_disco_stopped(self):
        """Уведомление о завершении дискотеки"""
        now = datetime.now()
        message = (
            f"🛑 <b>Дискотека завершена</b>\n\n"
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"👋 До встречи!"
        )
        return self.send_message(message)
    
    def notify_music_stopped(self, silence_time):
        """
        Уведомление об остановке музыки (тишина)
        
        Args:
            silence_time (float): Длительность тишины в секундах
        """
        now = datetime.now()
        message = (
            f"⚠️ <b>Музыка перестала играть!</b>\n\n"
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"🔇 Тишина: {silence_time:.0f} секунд\n"
        )
        return self.send_message(message)
    
    def notify_music_restored(self, silence_duration):
        """
        Уведомление о восстановлении музыки
        
        Args:
            silence_duration (float): Длительность предыдущей тишины в секундах
        """
        now = datetime.now()
        message = (
            f"✅ <b>Музыка играет</b>\n\n"
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"🎵 Все хорошо"
        )
        return self.send_message(message)
    
    def notify_server_started(self):
        """Уведомление о запуске сервера"""
        now = datetime.now()
        message = (
            f"🚀 <b>Сервер дискотеки запущен!</b>\n\n"
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"💻 Система планировщика активна\n"
            f"🎵 Готов к работе!"
        )
        return self.send_message(message)
    
    def add_chat_id(self, chat_id):
        """
        Добавление нового chat_id в список подписчиков
        
        Args:
            chat_id (int/str): ID чата для добавления
        """
        chat_id = str(chat_id)
        if chat_id not in self.chat_ids:
            self.chat_ids.append(chat_id)
            self.save_config()
            print(f"[Telegram Bot] Добавлен новый подписчик: {chat_id}")
            return True
        return False
    
    def remove_chat_id(self, chat_id):
        """
        Удаление chat_id из списка подписчиков
        
        Args:
            chat_id (int/str): ID чата для удаления
        """
        chat_id = str(chat_id)
        if chat_id in self.chat_ids:
            self.chat_ids.remove(chat_id)
            self.save_config()
            print(f"[Telegram Bot] Удален подписчик: {chat_id}")
            return True
        return False
    
    def save_config(self):
        """Сохранение конфигурации в файл"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                config['telegram_bot_token'] = self.bot_token
                config['telegram_chat_ids'] = self.chat_ids
                config['telegram_notifications_enabled'] = self.notifications_enabled
                
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                # Обновляем статус enabled
                self.enabled = bool(self.bot_token and self.chat_ids)
                
        except Exception as e:
            print(f"[Telegram Bot] Ошибка при сохранении конфигурации: {e}")
    
    def enable_notifications(self):
        """Включить уведомления"""
        if not self.enabled:
            print("[Telegram Bot] Бот не активирован!")
            return False
        
        self.notifications_enabled = True
        self.save_config()
        print("[Telegram Bot] Уведомления включены")
        return True
    
    def disable_notifications(self):
        """Отключить уведомления"""
        if not self.enabled:
            print("[Telegram Bot] Бот не активирован!")
            return False
        
        self.notifications_enabled = False
        self.save_config()
        print("[Telegram Bot] Уведомления отключены")
        return True
    
    def toggle_notifications(self):
        """Переключить состояние уведомлений"""
        if self.notifications_enabled:
            return self.disable_notifications()
        else:
            return self.enable_notifications()
    
    def get_notifications_status(self):
        """Получить статус уведомлений"""
        if not self.enabled:
            return "Бот не активирован"
        return "включены" if self.notifications_enabled else "отключены"


def main():
    """Тестовая функция"""
    print("=== Телеграм-бот для уведомлений о дискотеке ===\n")
    
    notifier = TelegramNotifier()
    
    if not notifier.enabled:
        print("❌ Бот не активирован!")
        print("Для активации добавьте в scheduler_config.json:")
        print('  "telegram_bot_token": "ваш_токен",')
        print('  "telegram_chat_ids": ["ваш_chat_id"]')
        return
    
    print("✅ Бот активирован!")
    print(f"Токен: {notifier.bot_token[:10]}...")
    print(f"Подписчики: {notifier.chat_ids}\n")
    
    # Меню для тестирования
    while True:
        print("\n--- Меню тестирования ---")
        print("1. Отправить уведомление 'Дискотека началась'")
        print("2. Отправить уведомление 'Дискотека завершена'")
        print("3. Отправить уведомление 'Музыка перестала играть'")
        print("4. Отправить уведомление 'Музыка восстановлена'")
        print("5. Добавить chat_id")
        print("6. Удалить chat_id")
        print("7. Показать текущие chat_ids")
        print("8. Включить уведомления")
        print("9. Отключить уведомления")
        print("10. Переключить уведомления")
        print("11. Показать статус уведомлений")
        print("0. Выход")
        
        choice = input("\nВыберите действие: ").strip()
        
        if choice == '1':
            if notifier.notify_disco_started():
                print("✅ Уведомление отправлено")
            else:
                print("❌ Ошибка отправки")
                
        elif choice == '2':
            if notifier.notify_disco_stopped():
                print("✅ Уведомление отправлено")
            else:
                print("❌ Ошибка отправки")
                
        elif choice == '3':
            silence_time = input("Введите длительность тишины (секунд, по умолчанию 20): ").strip()
            silence_time = float(silence_time) if silence_time else 20.0
            if notifier.notify_music_stopped(silence_time):
                print("✅ Уведомление отправлено")
            else:
                print("❌ Ошибка отправки")
                
        elif choice == '4':
            silence_duration = input("Введите длительность тишины (секунд, по умолчанию 30): ").strip()
            silence_duration = float(silence_duration) if silence_duration else 30.0
            if notifier.notify_music_restored(silence_duration):
                print("✅ Уведомление отправлено")
            else:
                print("❌ Ошибка отправки")
                
        elif choice == '5':
            chat_id = input("Введите chat_id для добавления: ").strip()
            if chat_id:
                if notifier.add_chat_id(chat_id):
                    print(f"✅ Chat ID {chat_id} добавлен")
                else:
                    print(f"⚠️ Chat ID {chat_id} уже существует")
                    
        elif choice == '6':
            chat_id = input("Введите chat_id для удаления: ").strip()
            if chat_id:
                if notifier.remove_chat_id(chat_id):
                    print(f"✅ Chat ID {chat_id} удален")
                else:
                    print(f"⚠️ Chat ID {chat_id} не найден")
                    
        elif choice == '7':
            print(f"\nТекущие chat_ids: {notifier.chat_ids}")
            
        elif choice == '8':
            if notifier.enable_notifications():
                print("✅ Уведомления включены")
            else:
                print("❌ Не удалось включить уведомления")
                
        elif choice == '9':
            if notifier.disable_notifications():
                print("✅ Уведомления отключены")
            else:
                print("❌ Не удалось отключить уведомления")
                
        elif choice == '10':
            if notifier.toggle_notifications():
                status = notifier.get_notifications_status()
                print(f"✅ Уведомления теперь {status}")
                
        elif choice == '11':
            status = notifier.get_notifications_status()
            print(f"\nТекущий статус: уведомления {status}")
            
        elif choice == '0':
            print("Выход...")
            break
            
        else:
            print("❌ Неверный выбор")


if __name__ == '__main__':
    main()

