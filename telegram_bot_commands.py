#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм-бот с командами для управления туннелем и сервером дискотеки.
Позволяет получать ссылку на туннель по команде, перезапускать туннель и проверять статус.
"""

import os
import sys
import json
import subprocess
import telebot
from datetime import datetime


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class TunnelBot:
    """Класс для управления телеграм-ботом с командами"""

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
        self.bot = None
        self.admin_users = []
        self.tunnel_script = os.path.join(get_exe_dir(), 'check_tunnel.sh')

        self.load_config()

        if self.bot_token:
            self.bot = telebot.TeleBot(self.bot_token)
            self.setup_handlers()
            print(f"[Tunnel Bot] Бот инициализирован с токеном {self.bot_token[:10]}...")
        else:
            print("[Tunnel Bot] Ошибка: токен бота не найден в конфигурации")

    def load_config(self):
        """Загрузка конфигурации из файла"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self.bot_token = config.get('telegram_bot_token', '')
                self.admin_users = config.get('telegram_admin_users', [])

                if not self.bot_token:
                    print("[Tunnel Bot] Токен бота не задан в конфигурации")

                if not self.admin_users:
                    print("[Tunnel Bot] Список администраторов пуст в конфигурации")
                else:
                    print(f"[Tunnel Bot] Загружено администраторов: {len(self.admin_users)}")
            else:
                print(f"[Tunnel Bot] Файл конфигурации не найден: {self.config_file}")

        except Exception as e:
            print(f"[Tunnel Bot] Ошибка при загрузке конфигурации: {e}")

    def run_tunnel_command(self, command, mode=None):
        """
        Выполнить команду для управления туннелем

        Args:
            command (str): Команда (status, restart, url, mode, web, ssh)
            mode (str): Опциональный режим для переключения (web или ssh)

        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            if not os.path.exists(self.tunnel_script):
                return False, f"Скрипт туннеля не найден: {self.tunnel_script}"

            cmd = ['bash', self.tunnel_script, command]
            if mode:
                cmd.append(mode)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            output = result.stdout.strip()
            error = result.stderr.strip()

            if result.returncode == 0:
                return True, output
            else:
                return False, error if error else output

        except subprocess.TimeoutExpired:
            return False, "Команда выполнялась слишком долго (таймаут 60 сек)"
        except Exception as e:
            return False, f"Ошибка выполнения команды: {e}"

    def is_admin(self, user):
        """Проверка, является ли пользователь администратором"""
        # Проверяем по ID
        if user.id in self.admin_users:
            return True
        # Проверяем по username (без @)
        if user.username and user.username in self.admin_users:
            return True
        return False

    def setup_handlers(self):
        """Настройка обработчиков команд"""

        @self.bot.message_handler(commands=['start'])
        def send_start(message):
            """Приветствие и список команд"""
            if not self.is_admin(message.from_user):
                self.bot.reply_to(message, "❌ У вас нет доступа к этому боту")
                print(f"[Tunnel Bot] Отказ в доступе для пользователя {message.from_user.id}")
                return

            help_text = (
                "🎵 <b>Бот управления сервером дискотеки</b>\n\n"
                "Доступные команды:\n"
                "/tunnel - Получить ссылку на туннель\n"
                "/ssh - Получить SSH доступ к серверу"
            )
            self.bot.reply_to(message, help_text, parse_mode='HTML')
            print(f"[Tunnel Bot] Команда /start от пользователя {message.from_user.id}")

        @self.bot.message_handler(commands=['tunnel'])
        def get_tunnel_url(message):
            """Получить URL веб-туннеля (автоматически переключит на web режим)"""
            if not self.is_admin(message.from_user):
                self.bot.reply_to(message, "❌ У вас нет доступа к этой команде")
                print(f"[Tunnel Bot] Отказ в доступе для пользователя {message.from_user.id}")
                return

            print(f"[Tunnel Bot] Команда /tunnel от пользователя {message.from_user.id}")

            status_msg = self.bot.reply_to(message, "🔍 Проверяю/переключаю туннель на web режим...")

            # Переключаем на web режим (если туннель работает, он переключится, если нет - запустится)
            success, output = self.run_tunnel_command('web')

            if success:
                # Получаем URL
                url_success, url = self.run_tunnel_command('url')
                if url_success and url and url != "Информация о туннеле не найдена":
                    response = (
                        f"✅ <b>Веб-туннель работает</b>\n\n"
                        f"🔗 Публичная ссылка:\n{url}\n\n"
                        f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    )
                else:
                    response = "⚠️ Туннель запущен, но URL не получен. Попробуйте еще раз через минуту."
            else:
                response = f"❌ Ошибка запуска веб-туннеля:\n{output}"

            self.bot.edit_message_text(
                response,
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                parse_mode='HTML'
            )

        @self.bot.message_handler(commands=['ssh'])
        def get_ssh_tunnel(message):
            """Получить SSH туннель для подключения к серверу (автоматически переключит на ssh режим)"""
            if not self.is_admin(message.from_user):
                self.bot.reply_to(message, "❌ У вас нет доступа к этой команде")
                print(f"[Tunnel Bot] Отказ в доступе для пользователя {message.from_user.id}")
                return

            print(f"[Tunnel Bot] Команда /ssh от пользователя {message.from_user.id}")

            status_msg = self.bot.reply_to(message, "🔍 Проверяю/переключаю туннель на SSH режим...")

            # Переключаем на ssh режим (если туннель работает, он переключится, если нет - запустится)
            success, output = self.run_tunnel_command('ssh')

            if success:
                # Получаем информацию о подключении
                info_success, ssh_info = self.run_tunnel_command('url')
                if info_success and ssh_info and ssh_info != "Информация о туннеле не найдена":
                    # ssh_info содержит две строки: команда и пароль
                    response = (
                        f"✅ <b>SSH туннель активен</b>\n\n"
                        f"🔐 Данные для подключения:\n"
                        f"<code>{ssh_info}</code>\n\n"
                        f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    )
                else:
                    response = "⚠️ SSH туннель запущен, но данные для подключения не получены. Попробуйте еще раз через минуту."
            else:
                response = f"❌ Ошибка запуска SSH туннеля:\n{output}"

            self.bot.edit_message_text(
                response,
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                parse_mode='HTML'
            )


    def start_polling(self):
        """Запустить бота в режиме polling"""
        if self.bot:
            print("[Tunnel Bot] Запуск бота в режиме polling...")
            print("[Tunnel Bot] Бот готов к приему команд!")
            try:
                self.bot.infinity_polling(timeout=30, long_polling_timeout=30)
            except KeyboardInterrupt:
                print("\n[Tunnel Bot] Остановка бота...")
            except Exception as e:
                print(f"[Tunnel Bot] Ошибка при работе бота: {e}")
        else:
            print("[Tunnel Bot] Бот не инициализирован")


def main():
    """Главная функция для запуска бота"""
    print("=== Телеграм-бот управления туннелем ===\n")

    bot = TunnelBot()

    if bot.bot:
        bot.start_polling()
    else:
        print("❌ Не удалось запустить бота")
        print("Проверьте наличие telegram_bot_token в scheduler_config.json")


if __name__ == '__main__':
    main()
