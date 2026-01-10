#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единый телеграм-бот для управления и уведомлений о дискотеке.
Совмещает функции:
- Отправку уведомлений о событиях дискотеки (TelegramNotifier)
- Интерактивные команды для управления туннелем (TunnelBot)
"""

import os
import sys
import json
import subprocess
import time
import traceback
import telebot
import requests
from datetime import datetime, timedelta
from mutagen.mp3 import MP3
from requests.exceptions import RequestException, Timeout, ConnectionError


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class DiscoTelegramBot:
    """
    Единый класс для телеграм-бота дискотеки.
    Совмещает функции уведомлений (TelegramNotifier) и команд (TunnelBot).
    """

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
        self.chat_ids = []  # Подписчики для уведомлений
        self.admin_users = []  # Админы для команд
        self.notifications_enabled = True
        self.enabled = False
        self.tunnel_script = os.path.join(get_exe_dir(), 'check_tunnel.sh')

        self.load_config()

        if self.bot_token:
            self.bot = telebot.TeleBot(self.bot_token)
            self.setup_handlers()
            print(f"[Disco Bot] Бот инициализирован с токеном {self.bot_token[:10]}...")
            if self.chat_ids:
                print(f"[Disco Bot] Количество подписчиков: {len(self.chat_ids)}")
            if self.admin_users:
                print(f"[Disco Bot] Количество администраторов: {len(self.admin_users)}")
        else:
            print("[Disco Bot] Ошибка: токен бота не найден в конфигурации")

    def load_config(self):
        """Загрузка конфигурации из файла"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self.bot_token = config.get('telegram_bot_token', '')
                self.chat_ids = config.get('telegram_chat_ids', [])
                self.admin_users = config.get('telegram_admin_users', [])
                self.notifications_enabled = config.get('telegram_notifications_enabled', True)

                # Проверяем, что токен не пустой и есть хотя бы один chat_id
                if self.bot_token and self.chat_ids:
                    self.enabled = True
                    status = "включены" if self.notifications_enabled else "отключены"
                    print(f"[Disco Bot] Уведомления {status}")
                else:
                    self.enabled = False
                    if not self.bot_token:
                        print("[Disco Bot] Токен бота не задан в конфигурации")
                    elif not self.chat_ids:
                        print("[Disco Bot] Нет подписчиков (chat_ids пуст)")

                if not self.admin_users:
                    print("[Disco Bot] Список администраторов пуст")
            else:
                print(f"[Disco Bot] Файл конфигурации не найден: {self.config_file}")
                self.enabled = False

        except Exception as e:
            print(f"[Disco Bot] Ошибка при загрузке конфигурации: {e}")
            self.enabled = False

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

    # ============================================
    # Методы для отправки уведомлений (TelegramNotifier)
    # ============================================

    def send_message(self, message, parse_mode='HTML', max_retries=3, base_timeout=30):
        """
        Отправка сообщения в Telegram всем подписчикам с механизмом повторных попыток

        Args:
            message (str): Текст сообщения
            parse_mode (str): Режим парсинга (HTML, Markdown)
            max_retries (int): Максимальное количество попыток отправки
            base_timeout (int): Базовый таймаут для запроса в секундах

        Returns:
            bool: True если сообщение отправлено успешно хотя бы одному получателю
        """
        if not self.enabled:
            return False

        if not self.notifications_enabled:
            print("[Disco Bot] Уведомления отключены в конфиге")
            return False

        success = False
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        for chat_id in self.chat_ids:
            chat_success = False

            for attempt in range(max_retries):
                try:
                    # Увеличиваем таймаут с каждой попыткой (экспоненциальная задержка)
                    current_timeout = base_timeout * (2 ** attempt)

                    payload = {
                        'chat_id': chat_id,
                        'text': message,
                        'parse_mode': parse_mode
                    }

                    if attempt > 0:
                        print(f"[Disco Bot] Попытка {attempt + 1}/{max_retries} отправки в чат {chat_id} (таймаут: {current_timeout}с)")

                    response = requests.post(api_url, json=payload, timeout=current_timeout)

                    if response.status_code == 200:
                        chat_success = True
                        success = True
                        print(f"[Disco Bot] Сообщение отправлено в чат {chat_id}")
                        break
                    else:
                        print(f"[Disco Bot] Ошибка отправки в чат {chat_id}: {response.status_code} - {response.text}")
                        # Не повторяем при ошибках сервера (не связанных с сетью)
                        if response.status_code < 500:
                            break

                except (Timeout, ConnectionError) as e:
                    # Сетевые ошибки и таймауты - пробуем снова
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Экспоненциальная задержка: 1, 2, 4 секунды
                        print(f"[Disco Bot] Таймаут/сетевая ошибка для чата {chat_id}: {e}")
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить в чат {chat_id} после {max_retries} попыток: {e}")

                except RequestException as e:
                    # Другие ошибки requests
                    print(f"[Disco Bot] Ошибка запроса для чата {chat_id}: {e}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить в чат {chat_id} после {max_retries} попыток")

                except Exception as e:
                    # Неожиданные ошибки
                    print(f"[Disco Bot] Неожиданная ошибка при отправке в чат {chat_id}: {e}")
                    break

        return success

    def send_photo(self, image_path, caption=None, parse_mode='HTML', max_retries=3, base_timeout=30):
        """
        Отправка изображения в Telegram с подписью и механизмом повторных попыток

        Args:
            image_path (str): Путь к изображению
            caption (str): Подпись к фото
            parse_mode (str): Режим парсинга подписи
            max_retries (int): Максимальное количество попыток отправки
            base_timeout (int): Базовый таймаут для запроса в секундах

        Returns:
            bool: True если отправлено хотя бы одному получателю
        """
        if not self.enabled:
            return False
        if not self.notifications_enabled:
            print("[Disco Bot] Уведомления отключены в конфиге")
            return False
        if not image_path or not os.path.exists(image_path):
            print(f"[Disco Bot] Файл изображения не найден: {image_path}")
            return False

        success = False
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"

        for chat_id in self.chat_ids:
            chat_success = False

            for attempt in range(max_retries):
                try:
                    current_timeout = base_timeout * (2 ** attempt)

                    if attempt > 0:
                        print(f"[Disco Bot] Попытка {attempt + 1}/{max_retries} отправки фото в чат {chat_id} (таймаут: {current_timeout}с)")

                    with open(image_path, 'rb') as img_file:
                        files = {'photo': img_file}
                        data = {'chat_id': chat_id}
                        if caption:
                            data['caption'] = caption
                            data['parse_mode'] = parse_mode
                        response = requests.post(api_url, data=data, files=files, timeout=current_timeout)

                    if response.status_code == 200:
                        chat_success = True
                        success = True
                        print(f"[Disco Bot] Фото отправлено в чат {chat_id}")
                        break
                    else:
                        print(f"[Disco Bot] Ошибка отправки фото в чат {chat_id}: {response.status_code} - {response.text}")
                        if response.status_code < 500:
                            break

                except (Timeout, ConnectionError) as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Disco Bot] Таймаут/сетевая ошибка при отправке фото в чат {chat_id}: {e}")
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить фото в чат {chat_id} после {max_retries} попыток: {e}")

                except RequestException as e:
                    print(f"[Disco Bot] Ошибка запроса при отправке фото в чат {chat_id}: {e}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить фото в чат {chat_id} после {max_retries} попыток")

                except Exception as e:
                    print(f"[Disco Bot] Неожиданная ошибка при отправке фото в чат {chat_id}: {e}")
                    break

        return success

    def send_media_group(self, image_paths, caption=None, parse_mode='HTML', max_retries=3, base_timeout=60):
        """
        Отправка нескольких изображений одним сообщением (media group) с механизмом повторных попыток

        Args:
            image_paths (list[str]): Пути к изображениям
            caption (str): Подпись к группе (ставится на первое фото)
            parse_mode (str): Режим парсинга подписи
            max_retries (int): Максимальное количество попыток отправки
            base_timeout (int): Базовый таймаут для запроса в секундах

        Returns:
            bool: True если отправлено хотя бы одному получателю
        """
        if not self.enabled:
            return False
        if not self.notifications_enabled:
            print("[Disco Bot] Уведомления отключены в конфиге")
            return False

        # Фильтруем существующие файлы
        valid_paths = [p for p in (image_paths or []) if p and os.path.exists(p)]
        if not valid_paths:
            print("[Disco Bot] Нет доступных файлов для отправки media group")
            return False

        success = False
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMediaGroup"

        for chat_id in self.chat_ids:
            chat_success = False

            for attempt in range(max_retries):
                files = {}
                try:
                    current_timeout = base_timeout * (2 ** attempt)

                    if attempt > 0:
                        print(f"[Disco Bot] Попытка {attempt + 1}/{max_retries} отправки media group в чат {chat_id} (таймаут: {current_timeout}с)")

                    media = []
                    for idx, path in enumerate(valid_paths):
                        file_key = f"photo{idx}"
                        files[file_key] = open(path, 'rb')
                        item = {
                            'type': 'photo',
                            'media': f"attach://{file_key}"
                        }
                        if idx == 0 and caption:
                            item['caption'] = caption
                            item['parse_mode'] = parse_mode
                        media.append(item)
                    data = {
                        'chat_id': chat_id,
                        'media': json.dumps(media)
                    }
                    response = requests.post(api_url, data=data, files=files, timeout=current_timeout)

                    # Закрываем файлы
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass

                    if response.status_code == 200:
                        chat_success = True
                        success = True
                        print(f"[Disco Bot] Media group отправлена в чат {chat_id}")
                        break
                    else:
                        print(f"[Disco Bot] Ошибка отправки media group в чат {chat_id}: {response.status_code} - {response.text}")
                        if response.status_code < 500:
                            break

                except (Timeout, ConnectionError) as e:
                    # Закрываем файлы при ошибке
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass

                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Disco Bot] Таймаут/сетевая ошибка при отправке media group в чат {chat_id}: {e}")
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить media group в чат {chat_id} после {max_retries} попыток: {e}")

                except RequestException as e:
                    # Закрываем файлы при ошибке
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass

                    print(f"[Disco Bot] Ошибка запроса при отправке media group в чат {chat_id}: {e}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[Disco Bot] Повторная попытка через {wait_time}с...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Disco Bot] Не удалось отправить media group в чат {chat_id} после {max_retries} попыток")

                except Exception as e:
                    # Закрываем файлы при ошибке
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass
                    print(f"[Disco Bot] Неожиданная ошибка при отправке media group в чат {chat_id}: {e}")
                    break

        return success

    def notify_disco_started(self, playlist=None, start_time=None):
        """
        Уведомление о начале дискотеки

        Args:
            playlist (list): Список путей к трекам плейлиста
            start_time (datetime.time): Время начала дискотеки
        """
        now = datetime.now()
        message_lines = [
            f"🎉 <b>Дискотека началась!</b>\n",
            f"⏰ Время: {now.strftime('%d.%m.%Y %H:%M')}\n",
            f"🎵 Музыка запущена"
        ]

        # Отправляем основное сообщение
        base_message = "\n".join(message_lines)
        success = self.send_message(base_message)

        # Добавляем плейлист отдельным сообщением, если он передан
        if playlist and len(playlist) > 0:
            print(f"[Disco Bot] Отправка плейлиста: {len(playlist)} треков")
            playlist_lines = []
            playlist_lines.append("📋 <b>Плейлист на сегодня:</b>\n")

            # Максимальная длина сообщения Telegram (с запасом)
            max_message_length = 4000

            # Вычисляем время начала для каждого трека
            current_time = None
            if start_time:
                # Используем время начала дискотеки
                today = datetime.now().date()
                current_time = datetime.combine(today, start_time)
            else:
                # Если время начала не передано, используем текущее время
                current_time = now

            for track_path in playlist:
                # Получаем длительность трека
                track_duration = 0
                try:
                    audio = MP3(track_path)
                    track_duration = int(audio.info.length)
                except Exception as e:
                    print(f"[Disco Bot] Ошибка получения длительности трека {track_path}: {e}")
                    # Используем среднюю длительность 3 минуты, если не удалось получить
                    track_duration = 180

                # Форматируем время начала трека (только часы:минуты)
                time_str = current_time.strftime('%H:%M')

                # Получаем имя файла без расширения
                track_name = os.path.splitext(os.path.basename(track_path))[0]
                track_line = f"{time_str} - {track_name}\n"

                # Проверяем, нужно ли отправить текущую часть и начать новую
                current_length = len("\n".join(playlist_lines))
                if current_length + len(track_line) > max_message_length and len(playlist_lines) > 1:
                    # Отправляем текущую часть
                    playlist_message = "".join(playlist_lines).rstrip()
                    self.send_message(playlist_message)

                    # Небольшая задержка между сообщениями (защита от флуда Telegram API)
                    time.sleep(0.5)

                    # Начинаем новую часть
                    playlist_lines = []
                    playlist_lines.append(f"📋 <b>Плейлист (продолжение):</b>\n")

                playlist_lines.append(track_line)

                # Обновляем время для следующего трека
                current_time += timedelta(seconds=track_duration)

            # Отправляем оставшуюся часть
            if len(playlist_lines) > 1:  # Больше чем просто заголовок
                # Небольшая задержка перед отправкой плейлиста после основного сообщения
                time.sleep(0.5)
                playlist_message = "".join(playlist_lines).rstrip()
                self.send_message(playlist_message)
                success = True

        return success

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
            f"✅ <b>Звук есть</b>\n\n"
            f"🎵 Все хорошо"
        )
        return self.send_message(message)

    def notify_server_started(self):
        """Уведомление о запуске/перезагрузке сервера"""
        now = datetime.now()
        message = (
            f"🔄 <b>Сервер перезагружен</b>\n\n"
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
            print(f"[Disco Bot] Добавлен новый подписчик: {chat_id}")
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
            print(f"[Disco Bot] Удален подписчик: {chat_id}")
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
            print(f"[Disco Bot] Ошибка при сохранении конфигурации: {e}")

    def enable_notifications(self):
        """Включить уведомления"""
        if not self.enabled:
            print("[Disco Bot] Бот не активирован!")
            return False

        self.notifications_enabled = True
        self.save_config()
        print("[Disco Bot] Уведомления включены")
        return True

    def disable_notifications(self):
        """Отключить уведомления"""
        if not self.enabled:
            print("[Disco Bot] Бот не активирован!")
            return False

        self.notifications_enabled = False
        self.save_config()
        print("[Disco Bot] Уведомления отключены")
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

    # ============================================
    # Обработчики команд (TunnelBot)
    # ============================================

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
                "/tunnel - Получить ссылку на веб-интерфейс"
            )
            self.bot.reply_to(message, help_text, parse_mode='HTML')
            print(f"[Tunnel Bot] Команда /start от пользователя {message.from_user.id}")

        @self.bot.message_handler(commands=['tunnel'])
        def get_tunnel_url(message):
            """Получить URL веб-туннеля (всегда перезапускает туннель)"""
            if not self.is_admin(message.from_user):
                self.bot.reply_to(message, "❌ У вас нет доступа к этой команде")
                print(f"[Tunnel Bot] Отказ в доступе для пользователя {message.from_user.id}")
                return

            print(f"[Tunnel Bot] Команда /tunnel от пользователя {message.from_user.id}")

            status_msg = self.bot.reply_to(message, "🔄 Перезапускаю туннель...\nЭто может занять до 30 секунд.")

            # Всегда перезапускаем туннель
            restart_success, restart_output = self.run_tunnel_command('restart')

            if restart_success:
                url_success, url = self.run_tunnel_command('url')
                if url_success and url and url != "Информация о туннеле не найдена":
                    response = (
                        f"✅ <b>Туннель перезапущен</b>\n\n"
                        f"🔗 Публичная ссылка:\n{url}\n\n"
                        f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}"
                    )
                else:
                    response = (
                        f"⚠️ <b>Туннель перезапущен, но URL не получен</b>\n\n"
                        f"Попробуйте еще раз через минуту"
                    )
            else:
                response = (
                    f"❌ <b>Ошибка перезапуска туннеля</b>\n\n"
                    f"Детали: {restart_output}"
                )

            self.bot.edit_message_text(
                response,
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                parse_mode='HTML'
            )


    def start_polling(self):
        """
        Запустить бота в режиме polling с автовосстановлением.
        При потере интернета бот будет переподключаться бесконечно.
        """
        if not self.bot:
            print("[Disco Bot] Бот не инициализирован")
            return

        print("[Disco Bot] Запуск бота в режиме polling с автовосстановлением...")
        print("[Disco Bot] Бот готов к приему команд!")

        retry_delay = 10  # Начальная задержка между попытками (секунды)
        max_retry_delay = 300  # Максимальная задержка (5 минут)

        while True:
            try:
                # Пытаемся запустить polling
                self.bot.infinity_polling(
                    timeout=30,
                    long_polling_timeout=30,
                    skip_pending=True  # Пропускаем старые сообщения после переподключения
                )
                # Если вышли из infinity_polling без ошибки - значит был KeyboardInterrupt
                break

            except KeyboardInterrupt:
                print("\n[Disco Bot] Остановка бота по запросу пользователя...")
                break

            except Exception as e:
                error_type = type(e).__name__
                print(f"\n[Disco Bot] ❌ Ошибка при работе бота: {error_type}: {e}")

                # Детальная информация об ошибке для отладки
                if "Connection" in str(e) or "Network" in str(e) or "Timeout" in str(e):
                    print(f"[Disco Bot] 🔌 Проблема с интернет-соединением")
                else:
                    # Выводим трассировку для неожиданных ошибок
                    print(f"[Disco Bot] Трассировка ошибки:")
                    traceback.print_exc()

                print(f"[Disco Bot] 🔄 Попытка переподключения через {retry_delay} секунд...")
                print(f"[Disco Bot] ℹ️  Бот будет пытаться переподключиться бесконечно")

                time.sleep(retry_delay)

                # Экспоненциально увеличиваем задержку, но не больше максимума
                retry_delay = min(retry_delay * 1.5, max_retry_delay)

                print(f"[Disco Bot] 🔄 Переподключение...")
                # Цикл продолжится и попытается снова запустить polling

        print("[Disco Bot] Бот остановлен")


def main():
    """Главная функция для запуска бота"""
    print("=== Единый телеграм-бот дискотеки ===\n")
    print("Функции:")
    print("  - Отправка уведомлений о событиях дискотеки")
    print("  - Интерактивные команды управления туннелем\n")

    bot = DiscoTelegramBot()

    if bot.bot:
        bot.start_polling()
    else:
        print("❌ Не удалось запустить бота")
        print("Проверьте наличие telegram_bot_token в scheduler_config.json")


# Для обратной совместимости - экспортируем класс под старым именем
TelegramNotifier = DiscoTelegramBot


if __name__ == '__main__':
    main()
