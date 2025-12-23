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
        self.check_tunnel_script = os.path.join(get_exe_dir(), 'check_tunnel.sh')

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

                if not self.bot_token:
                    print("[Tunnel Bot] Токен бота не задан в конфигурации")
            else:
                print(f"[Tunnel Bot] Файл конфигурации не найден: {self.config_file}")

        except Exception as e:
            print(f"[Tunnel Bot] Ошибка при загрузке конфигурации: {e}")

    def run_tunnel_command(self, command):
        """
        Выполнить команду для управления туннелем

        Args:
            command (str): Команда (status, restart, send, url)

        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            if not os.path.exists(self.check_tunnel_script):
                return False, f"Скрипт туннеля не найден: {self.check_tunnel_script}"

            result = subprocess.run(
                ['bash', self.check_tunnel_script, command],
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

    def setup_handlers(self):
        """Настройка обработчиков команд"""

        @self.bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            """Приветствие и список команд"""
            help_text = (
                "🎵 <b>Бот управления сервером дискотеки</b>\n\n"
                "Доступные команды:\n"
                "/tunnel - Получить текущую ссылку на туннель\n"
                "/restart_tunnel - Перезапустить туннель и получить новую ссылку\n"
                "/status - Проверить статус туннеля\n"
                "/help - Показать это сообщение"
            )
            self.bot.reply_to(message, help_text, parse_mode='HTML')
            print(f"[Tunnel Bot] Команда /start от пользователя {message.from_user.id}")

        @self.bot.message_handler(commands=['tunnel'])
        def get_tunnel_url(message):
            """Получить текущий URL туннеля"""
            print(f"[Tunnel Bot] Команда /tunnel от пользователя {message.from_user.id}")

            # Сначала отправляем сообщение о процессе
            status_msg = self.bot.reply_to(message, "🔍 Проверяю туннель...")

            # Проверяем статус туннеля
            success, output = self.run_tunnel_command('status')

            if success and output:
                # Туннель работает, получаем URL
                url_success, url = self.run_tunnel_command('url')
                if url_success and url and url != "URL не найден":
                    response = (
                        f"✅ <b>Туннель работает</b>\n\n"
                        f"🔗 Публичная ссылка:\n{url}\n\n"
                        f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    )
                    self.bot.edit_message_text(
                        response,
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        parse_mode='HTML'
                    )
                else:
                    response = (
                        "⚠️ <b>Туннель работает, но URL не найден</b>\n\n"
                        "Попробуйте перезапустить: /restart_tunnel"
                    )
                    self.bot.edit_message_text(
                        response,
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        parse_mode='HTML'
                    )
            else:
                # Туннель не работает, предлагаем перезапустить
                response = (
                    "❌ <b>Туннель не работает</b>\n\n"
                    "Используйте /restart_tunnel для запуска"
                )
                self.bot.edit_message_text(
                    response,
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                    parse_mode='HTML'
                )

        @self.bot.message_handler(commands=['restart_tunnel'])
        def restart_tunnel(message):
            """Перезапустить туннель"""
            print(f"[Tunnel Bot] Команда /restart_tunnel от пользователя {message.from_user.id}")

            # Отправляем сообщение о начале процесса
            status_msg = self.bot.reply_to(message, "🔄 Перезапускаю туннель...\nЭто может занять до 30 секунд.")

            # Перезапускаем туннель
            success, output = self.run_tunnel_command('restart')

            if success:
                # Получаем URL после перезапуска
                url_success, url = self.run_tunnel_command('url')
                if url_success and url and url != "URL не найден":
                    response = (
                        f"✅ <b>Туннель перезапущен!</b>\n\n"
                        f"🔗 Новая публичная ссылка:\n{url}\n\n"
                        f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    )
                    self.bot.edit_message_text(
                        response,
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        parse_mode='HTML'
                    )
                else:
                    response = (
                        "⚠️ <b>Туннель перезапущен, но URL не получен</b>\n\n"
                        f"Вывод: {output}\n\n"
                        "Попробуйте еще раз через минуту"
                    )
                    self.bot.edit_message_text(
                        response,
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        parse_mode='HTML'
                    )
            else:
                response = (
                    f"❌ <b>Ошибка перезапуска туннеля</b>\n\n"
                    f"Детали: {output}"
                )
                self.bot.edit_message_text(
                    response,
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                    parse_mode='HTML'
                )

        @self.bot.message_handler(commands=['status'])
        def check_status(message):
            """Проверить статус туннеля"""
            print(f"[Tunnel Bot] Команда /status от пользователя {message.from_user.id}")

            status_msg = self.bot.reply_to(message, "🔍 Проверяю статус...")

            success, output = self.run_tunnel_command('status')

            if success and output:
                url_success, url = self.run_tunnel_command('url')
                response = (
                    f"✅ <b>Статус туннеля: Активен</b>\n\n"
                    f"🔗 URL: {url if url_success and url else 'не определен'}\n"
                    f"⏰ Время проверки: {datetime.now().strftime('%H:%M:%S')}"
                )
            else:
                response = (
                    f"❌ <b>Статус туннеля: Не активен</b>\n\n"
                    f"⏰ Время проверки: {datetime.now().strftime('%H:%M:%S')}\n\n"
                    "Используйте /restart_tunnel для запуска"
                )

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
