#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Бот ВКонтакте для управления и уведомлений о дискотеке.
Функции:
- Отправка уведомлений о событиях дискотеки в беседу/группу ВК
- Интерактивные команды для управления туннелем
"""

import os
import sys
import json
import subprocess
import time
import traceback
import requests
import random
from datetime import datetime, timedelta
from mutagen.mp3 import MP3
from requests.exceptions import RequestException, Timeout, ConnectionError


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class DiscoVKBot:
    """
    Класс для ВК-бота дискотеки.
    Отправка уведомлений и обработка команд через VK API.
    """

    VK_API_VERSION = '5.199'
    VK_API_BASE = 'https://api.vk.com/method'

    def __init__(self, config_file=None):
        if config_file is None:
            config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')

        self.config_file = config_file
        self.vk_token = None
        self.group_id = None
        self.peer_ids = []  # ID бесед/пользователей для уведомлений
        self.admin_users = []  # VK user IDs администраторов
        self.notifications_enabled = True
        self.enabled = False
        self.tunnel_script = os.path.join(get_exe_dir(), 'check_tunnel.sh')

        # Long Poll
        self._lp_server = None
        self._lp_key = None
        self._lp_ts = None

        self.load_config()

        if self.vk_token:
            self.enabled = True
            status = "включены" if self.notifications_enabled else "отключены"
            print(f"[VK Bot] Бот инициализирован, уведомления {status}")
            if self.peer_ids:
                print(f"[VK Bot] Получателей: {len(self.peer_ids)}")
            else:
                print("[VK Bot] Нет получателей — беседа подпишется автоматически при первом сообщении")
        else:
            print("[VK Bot] Токен группы ВК не задан в конфигурации")

        # Имитируем атрибут bot для совместимости с scheduler_server.py
        self.bot = True if self.enabled else None

    def load_config(self):
        """Загрузка конфигурации из файла"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self.vk_token = config.get('vk_group_token', '')
                self.group_id = config.get('vk_group_id', 0)
                self.peer_ids = config.get('vk_peer_ids', [])
                self.admin_users = config.get('vk_admin_users', [])
                self.notifications_enabled = config.get('vk_notifications_enabled', True)

                self.enabled = bool(self.vk_token)
            else:
                print(f"[VK Bot] Файл конфигурации не найден: {self.config_file}")
                self.enabled = False
        except Exception as e:
            print(f"[VK Bot] Ошибка при загрузке конфигурации: {e}")
            self.enabled = False

    # Для совместимости: chat_ids = peer_ids
    @property
    def chat_ids(self):
        return self.peer_ids

    # ============================================
    # VK API вызовы
    # ============================================

    def _vk_api(self, method, **params):
        """Вызов метода VK API"""
        params['access_token'] = self.vk_token
        params['v'] = self.VK_API_VERSION
        url = f"{self.VK_API_BASE}/{method}"
        response = requests.post(url, data=params, timeout=10)
        result = response.json()
        if 'error' in result:
            raise Exception(f"VK API error: {result['error']}")
        return result.get('response')

    # ============================================
    # Отправка сообщений
    # ============================================

    def send_message(self, message, parse_mode=None, max_retries=3, base_timeout=10):
        """
        Отправка текстового сообщения в ВК всем получателям.
        parse_mode игнорируется (для совместимости интерфейса).
        """
        if not self.enabled:
            return False
        if not self.notifications_enabled:
            print("[VK Bot] Уведомления отключены в конфиге")
            return False

        # Убираем HTML-теги из сообщения (VK не поддерживает HTML)
        clean_message = self._strip_html(message)

        success = False
        for peer_id in self.peer_ids:
            for attempt in range(max_retries):
                try:
                    current_timeout = base_timeout * (2 ** attempt)
                    if attempt > 0:
                        print(f"[VK Bot] Попытка {attempt + 1}/{max_retries} отправки в {peer_id}")

                    params = {
                        'access_token': self.vk_token,
                        'v': self.VK_API_VERSION,
                        'peer_id': peer_id,
                        'message': clean_message,
                        'random_id': random.randint(1, 2**31),
                    }
                    resp = requests.post(
                        f"{self.VK_API_BASE}/messages.send",
                        data=params,
                        timeout=current_timeout
                    )
                    result = resp.json()

                    if 'error' in result:
                        print(f"[VK Bot] Ошибка отправки в {peer_id}: {result['error']}")
                        error_code = result['error'].get('error_code', 0)
                        # Не повторяем при ошибках доступа
                        if error_code in (7, 15, 901, 917):
                            break
                    else:
                        success = True
                        print(f"[VK Bot] Сообщение отправлено в {peer_id}")
                        break

                except (Timeout, ConnectionError) as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[VK Bot] Сетевая ошибка для {peer_id}: {e}")
                        time.sleep(wait_time)
                    else:
                        print(f"[VK Bot] Не удалось отправить в {peer_id} после {max_retries} попыток: {e}")
                except Exception as e:
                    print(f"[VK Bot] Неожиданная ошибка при отправке в {peer_id}: {e}")
                    break

        return success

    def send_photo(self, image_path, caption=None, parse_mode=None, max_retries=3, base_timeout=30):
        """Отправка изображения в ВК с подписью"""
        if not self.enabled or not self.notifications_enabled:
            return False
        if not image_path or not os.path.exists(image_path):
            print(f"[VK Bot] Файл изображения не найден: {image_path}")
            return False

        success = False
        for peer_id in self.peer_ids:
            for attempt in range(max_retries):
                try:
                    current_timeout = base_timeout * (2 ** attempt)
                    # 1. Получаем URL для загрузки
                    upload_server = self._vk_api(
                        'photos.getMessagesUploadServer',
                        peer_id=peer_id
                    )
                    upload_url = upload_server['upload_url']

                    # 2. Загружаем файл
                    with open(image_path, 'rb') as f:
                        upload_resp = requests.post(
                            upload_url,
                            files={'photo': f},
                            timeout=current_timeout
                        ).json()

                    # 3. Сохраняем фото
                    saved = self._vk_api(
                        'photos.saveMessagesPhoto',
                        photo=upload_resp['photo'],
                        server=upload_resp['server'],
                        hash=upload_resp['hash']
                    )
                    photo = saved[0]
                    attachment = f"photo{photo['owner_id']}_{photo['id']}"
                    if photo.get('access_key'):
                        attachment += f"_{photo['access_key']}"

                    # 4. Отправляем сообщение с фото
                    clean_caption = self._strip_html(caption) if caption else ''
                    params = {
                        'access_token': self.vk_token,
                        'v': self.VK_API_VERSION,
                        'peer_id': peer_id,
                        'message': clean_caption,
                        'attachment': attachment,
                        'random_id': random.randint(1, 2**31),
                    }
                    resp = requests.post(
                        f"{self.VK_API_BASE}/messages.send",
                        data=params,
                        timeout=current_timeout
                    ).json()

                    if 'error' not in resp:
                        success = True
                        print(f"[VK Bot] Фото отправлено в {peer_id}")
                        break
                    else:
                        print(f"[VK Bot] Ошибка отправки фото в {peer_id}: {resp['error']}")
                        break

                except (Timeout, ConnectionError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        print(f"[VK Bot] Не удалось отправить фото в {peer_id}: {e}")
                except Exception as e:
                    print(f"[VK Bot] Ошибка при отправке фото в {peer_id}: {e}")
                    break

        return success

    def send_media_group(self, image_paths, caption=None, parse_mode=None, max_retries=3, base_timeout=60):
        """Отправка нескольких изображений одним сообщением"""
        if not self.enabled or not self.notifications_enabled:
            return False

        valid_paths = [p for p in (image_paths or []) if p and os.path.exists(p)]
        if not valid_paths:
            return False

        success = False
        for peer_id in self.peer_ids:
            for attempt in range(max_retries):
                try:
                    current_timeout = base_timeout * (2 ** attempt)
                    attachments = []

                    for path in valid_paths:
                        upload_server = self._vk_api(
                            'photos.getMessagesUploadServer',
                            peer_id=peer_id
                        )
                        with open(path, 'rb') as f:
                            upload_resp = requests.post(
                                upload_server['upload_url'],
                                files={'photo': f},
                                timeout=current_timeout
                            ).json()

                        saved = self._vk_api(
                            'photos.saveMessagesPhoto',
                            photo=upload_resp['photo'],
                            server=upload_resp['server'],
                            hash=upload_resp['hash']
                        )
                        photo = saved[0]
                        att = f"photo{photo['owner_id']}_{photo['id']}"
                        if photo.get('access_key'):
                            att += f"_{photo['access_key']}"
                        attachments.append(att)

                    clean_caption = self._strip_html(caption) if caption else ''
                    params = {
                        'access_token': self.vk_token,
                        'v': self.VK_API_VERSION,
                        'peer_id': peer_id,
                        'message': clean_caption,
                        'attachment': ','.join(attachments),
                        'random_id': random.randint(1, 2**31),
                    }
                    resp = requests.post(
                        f"{self.VK_API_BASE}/messages.send",
                        data=params,
                        timeout=current_timeout
                    ).json()

                    if 'error' not in resp:
                        success = True
                        print(f"[VK Bot] Media group отправлена в {peer_id}")
                        break
                    else:
                        print(f"[VK Bot] Ошибка отправки media group в {peer_id}: {resp['error']}")
                        break

                except (Timeout, ConnectionError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        print(f"[VK Bot] Не удалось отправить media group в {peer_id}: {e}")
                except Exception as e:
                    print(f"[VK Bot] Ошибка при отправке media group в {peer_id}: {e}")
                    break

        return success

    # ============================================
    # Уведомления
    # ============================================

    def notify_disco_started(self, playlist=None, start_time=None):
        """Уведомление о начале дискотеки"""
        now = datetime.now()
        message_lines = [
            "Дискотека началась!\n",
            f"Время: {now.strftime('%d.%m.%Y %H:%M')}\n",
            "Музыка запущена"
        ]
        base_message = "\n".join(message_lines)
        success = self.send_message(base_message)

        if playlist and len(playlist) > 0:
            print(f"[VK Bot] Отправка плейлиста: {len(playlist)} треков")
            playlist_lines = ["Плейлист на сегодня:\n"]
            max_message_length = 4000

            current_time = None
            if start_time:
                today = datetime.now().date()
                current_time = datetime.combine(today, start_time)
            else:
                current_time = now

            for track_path in playlist:
                track_duration = 0
                try:
                    audio = MP3(track_path)
                    track_duration = int(audio.info.length)
                except Exception:
                    track_duration = 180

                time_str = current_time.strftime('%H:%M')
                track_name = os.path.splitext(os.path.basename(track_path))[0]
                track_line = f"{time_str} - {track_name}\n"

                current_length = len("".join(playlist_lines))
                if current_length + len(track_line) > max_message_length and len(playlist_lines) > 1:
                    playlist_message = "".join(playlist_lines).rstrip()
                    self.send_message(playlist_message)
                    time.sleep(0.5)
                    playlist_lines = ["Плейлист (продолжение):\n"]

                playlist_lines.append(track_line)
                current_time += timedelta(seconds=track_duration)

            if len(playlist_lines) > 1:
                time.sleep(0.5)
                playlist_message = "".join(playlist_lines).rstrip()
                self.send_message(playlist_message)
                success = True

        return success

    def notify_disco_stopped(self):
        """Уведомление о завершении дискотеки"""
        now = datetime.now()
        message = (
            f"Дискотека завершена\n\n"
            f"Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"До встречи!"
        )
        return self.send_message(message)

    def notify_music_stopped(self, silence_time):
        """Уведомление об остановке музыки (тишина)"""
        message = (
            f"Музыка перестала играть!\n\n"
            f"Тишина: {silence_time:.0f} секунд"
        )
        return self.send_message(message)

    def notify_music_restored(self, silence_duration):
        """Уведомление о восстановлении музыки"""
        message = "Звук есть\n\nВсе хорошо"
        return self.send_message(message)

    def notify_server_started(self):
        """Уведомление о запуске/перезагрузке сервера"""
        now = datetime.now()
        message = (
            f"Сервер перезагружен\n\n"
            f"Время: {now.strftime('%d.%m.%Y %H:%M')}\n"
            f"Система планировщика активна\n"
            f"Готов к работе!"
        )
        return self.send_message(message)

    # ============================================
    # Управление подписчиками
    # ============================================

    def add_chat_id(self, peer_id):
        """Добавление нового peer_id в список получателей"""
        if peer_id not in self.peer_ids:
            self.peer_ids.append(peer_id)
            self.save_config()
            print(f"[VK Bot] Добавлен получатель: {peer_id}")
            return True
        return False

    def remove_chat_id(self, peer_id):
        """Удаление peer_id из списка получателей"""
        if peer_id in self.peer_ids:
            self.peer_ids.remove(peer_id)
            self.save_config()
            print(f"[VK Bot] Удален получатель: {peer_id}")
            return True
        return False

    def save_config(self):
        """Сохранение конфигурации в файл"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                config['vk_group_token'] = self.vk_token
                config['vk_peer_ids'] = self.peer_ids
                config['vk_notifications_enabled'] = self.notifications_enabled

                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)

                self.enabled = bool(self.vk_token)
        except Exception as e:
            print(f"[VK Bot] Ошибка при сохранении конфигурации: {e}")

    def enable_notifications(self):
        """Включить уведомления"""
        if not self.enabled:
            print("[VK Bot] Бот не активирован!")
            return False
        self.notifications_enabled = True
        self.save_config()
        print("[VK Bot] Уведомления включены")
        return True

    def disable_notifications(self):
        """Отключить уведомления"""
        if not self.enabled:
            print("[VK Bot] Бот не активирован!")
            return False
        self.notifications_enabled = False
        self.save_config()
        print("[VK Bot] Уведомления отключены")
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
    # Long Poll для приёма команд
    # ============================================

    def _init_long_poll(self):
        """Инициализация Long Poll сервера"""
        result = self._vk_api('groups.getLongPollServer', group_id=self.group_id)
        self._lp_server = result['server']
        self._lp_key = result['key']
        self._lp_ts = result['ts']

    def _handle_message(self, event):
        """Обработка входящего сообщения. Все участники беседы могут управлять."""
        import re
        raw_text = event.get('text', '').strip()
        # Убираем упоминание сообщества вида [club123|@name]
        raw_text = re.sub(r'\[club\d+\|@[^\]]*\]\s*', '', raw_text)
        text = raw_text.strip().lower()
        from_id = event.get('from_id', 0)
        peer_id = event.get('peer_id', 0)

        print(f"[VK Bot] Сообщение от {from_id} в {peer_id}: '{text}'")

        # Если пишут в ЛС группе — автоматически подписываем на уведомления
        if peer_id > 0 and peer_id not in self.peer_ids:
            self.add_chat_id(peer_id)
            self._send_to_peer(peer_id, "Вы подписаны на уведомления дискотеки! Напишите 'команды' для списка команд.")

        if text in ('/start', 'начать', 'команды', 'помощь'):
            help_text = (
                "Бот управления сервером дискотеки\n\n"
                "Доступные команды:\n"
                "/tunnel - Получить ссылку на веб-интерфейс\n"
                "отписаться - Отключить уведомления"
            )
            self._send_to_peer(peer_id, help_text)

        elif text in ('отписаться', 'отписка', 'стоп', '/stop'):
            if peer_id in self.peer_ids:
                self.remove_chat_id(peer_id)
                self._send_to_peer(peer_id, "Вы отписаны от уведомлений. Напишите что угодно, чтобы подписаться снова.")
            else:
                self._send_to_peer(peer_id, "Вы и так не подписаны.")

        elif text in ('/tunnel', 'tunnel', 'туннель'):
            self._send_to_peer(peer_id, "Перезапускаю туннель... Это может занять до 30 секунд.")
            success, output = self.run_tunnel_command('restart')
            if success:
                url_ok, url = self.run_tunnel_command('url')
                if url_ok and url and url != "Информация о туннеле не найдена":
                    response = f"Туннель перезапущен\n\nСсылка:\n{url}\n\nВремя: {datetime.now().strftime('%H:%M:%S')}"
                else:
                    response = "Туннель перезапущен, но URL не получен. Попробуйте через минуту."
            else:
                response = f"Ошибка перезапуска туннеля\n\n{output}"
            self._send_to_peer(peer_id, response)


    def _send_to_peer(self, peer_id, message):
        """Отправка сообщения в конкретный peer"""
        try:
            self._vk_api(
                'messages.send',
                peer_id=peer_id,
                message=message,
                random_id=random.randint(1, 2**31)
            )
        except Exception as e:
            print(f"[VK Bot] Ошибка отправки в {peer_id}: {e}")

    def run_tunnel_command(self, command, mode=None):
        """Выполнить команду для управления туннелем"""
        try:
            if not os.path.exists(self.tunnel_script):
                return False, f"Скрипт туннеля не найден: {self.tunnel_script}"

            cmd = ['bash', self.tunnel_script, command]
            if mode:
                cmd.append(mode)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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

    def start_polling(self):
        """Запустить Long Poll с автовосстановлением"""
        if not self.enabled or not self.group_id:
            print("[VK Bot] Бот не инициализирован или group_id не задан")
            return

        print("[VK Bot] Запуск Long Poll...")
        retry_delay = 10
        max_retry_delay = 300

        while True:
            try:
                self._init_long_poll()
                print("[VK Bot] Long Poll подключен, слушаю команды...")
                retry_delay = 10  # Сбрасываем задержку при успешном подключении

                while True:
                    resp = requests.get(
                        self._lp_server,
                        params={'act': 'a_check', 'key': self._lp_key, 'ts': self._lp_ts, 'wait': 25},
                        timeout=30
                    ).json()

                    if 'failed' in resp:
                        failed = resp['failed']
                        if failed == 1:
                            self._lp_ts = resp['ts']
                        elif failed in (2, 3):
                            self._init_long_poll()
                        continue

                    self._lp_ts = resp.get('ts', self._lp_ts)
                    for update in resp.get('updates', []):
                        if update.get('type') == 'message_new':
                            msg = update.get('object', {}).get('message', {})
                            if msg:
                                self._handle_message(msg)

            except KeyboardInterrupt:
                print("\n[VK Bot] Остановка по запросу пользователя...")
                break
            except Exception as e:
                error_type = type(e).__name__
                print(f"\n[VK Bot] Ошибка: {error_type}: {e}")
                if "Connection" in str(e) or "Timeout" in str(e):
                    print("[VK Bot] Проблема с интернет-соединением")
                else:
                    traceback.print_exc()

                print(f"[VK Bot] Переподключение через {retry_delay} сек...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, max_retry_delay)

        print("[VK Bot] Бот остановлен")

    # ============================================
    # Вспомогательные методы
    # ============================================

    @staticmethod
    def _strip_html(text):
        """Удаление HTML-тегов из текста"""
        import re
        clean = re.sub(r'<[^>]+>', '', text)
        return clean

    def is_admin(self, user_id):
        """Проверка, является ли пользователь администратором"""
        return user_id in self.admin_users


# Для совместимости — экспортируем под старым именем
TelegramNotifier = DiscoVKBot


def main():
    """Главная функция для запуска бота"""
    print("=== ВК-бот дискотеки ===\n")
    print("Функции:")
    print("  - Отправка уведомлений о событиях дискотеки")
    print("  - Интерактивные команды управления туннелем\n")

    bot = DiscoVKBot()

    if bot.enabled:
        bot.start_polling()
    else:
        print("Не удалось запустить бота")
        print("Проверьте vk_group_token и vk_peer_ids в scheduler_config.json")


if __name__ == '__main__':
    main()
