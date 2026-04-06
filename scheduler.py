#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль планировщика для автоматического запуска плейлистов.
Содержит всю логику планирования и выполнения задач.
"""

import os
import sys
import json
import time as time_module
from datetime import datetime, time, timedelta
from threading import Lock, Thread
from playlist_gen import PlaylistGenerator
from vlc_playlist import VLCPlaylistLauncher
from vk_bot import TelegramNotifier
from config_manager import ConfigManager

# Глобальный lock для синхронизации записи в конфиг из всех компонентов
CONFIG_LOCK = Lock()


def get_resource_path(relative_path):
    """Получает абсолютный путь к ресурсу, работает для dev и для PyInstaller"""
    try:
        # PyInstaller создает временную папку и устанавливает путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # В режиме разработки используем текущую директорию
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        # Если запущено из exe
        return os.path.dirname(sys.executable)
    else:
        # Если запущено из скрипта
        return os.path.dirname(os.path.abspath(__file__))


class DiscoScheduler:
    """Класс планировщика дискотеки"""
    
    # Используем глобальный CONFIG_LOCK для синхронизации записи в конфиг
    _config_lock = CONFIG_LOCK
    
    def __init__(self, config_file=None, log_callback=None):
        """
        Инициализация планировщика
        
        Args:
            config_file (str): Путь к файлу конфигурации
            log_callback (callable): Функция для логирования сообщений
        """
        self.config_file = config_file if config_file else os.path.join(get_exe_dir(), 'scheduler_config.json')
        self.log_callback = log_callback
        
        # Параметры по умолчанию
        self.playlist_duration_hours = 2.583  # 2 часа 35 минут
        self.scheduled_days = [3, 4, 5, 6]  # Четверг, Пятница, Суббота, Воскресенье (0 = понедельник)
        self.start_time = time(14, 55)
        self.stop_time = time(18, 0)
        
        # Флаг активности дискотеки (запущена по расписанию)
        self.disco_is_active = False
        
        # Флаг для отслеживания типа закрытия VLC (True = автоматическое, False = ручное)
        self.is_automatic_close = True
        
        # Флаг включения/отключения планировщика (загружается из конфига)
        self.scheduler_enabled = True  # По умолчанию включен, но будет перезаписан из конфига
        
        # Отслеживание последнего запуска генерации (чтобы не запускать повторно в ту же минуту)
        self.last_generation_time = None
        
        # Отслеживание последнего закрытия VLC (чтобы не закрывать повторно в ту же минуту)
        self.last_close_time = None

        # Отслеживание последнего автоперезапуска VLC (защита от частых перезапусков)
        self.last_vlc_restart_time = None
        self.vlc_restart_cooldown = 30  # Минимум 30 секунд между перезапусками
        
        # Инициализация компонентов
        self.vlc_launcher = VLCPlaylistLauncher()
        self.telegram_bot = TelegramNotifier(self.config_file, config_lock=CONFIG_LOCK)
        self.config_manager = ConfigManager()

        # Загружаем настройки
        self.load_settings()
        
    def log(self, message):
        """Логирование сообщения"""
        if self.log_callback:
            self.log_callback(message)
        else:
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f'[{timestamp}] {message}')
    
    def load_settings(self):
        """Загрузка настроек из конфига"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                # Загружаем дни недели
                if 'scheduled_days' in settings:
                    self.scheduled_days = settings['scheduled_days']
                
                # Загружаем время запуска
                if 'start_time' in settings:
                    start_time_data = settings['start_time']
                    self.start_time = time(start_time_data['hour'], start_time_data['minute'])
                
                # Загружаем время остановки
                if 'stop_time' in settings:
                    stop_time_data = settings['stop_time']
                    self.stop_time = time(stop_time_data['hour'], stop_time_data['minute'])
                
                # Загружаем длительность плейлиста
                if 'playlist_duration_hours' in settings:
                    self.playlist_duration_hours = settings['playlist_duration_hours']
                
                # Загружаем состояние планировщика
                if 'scheduler_enabled' in settings:
                    self.scheduler_enabled = settings['scheduler_enabled']
                    self.log(f'Состояние планировщика загружено из конфига: {"включен" if self.scheduler_enabled else "отключен"}')
                else:
                    self.log('Состояние планировщика не найдено в конфиге, используется значение по умолчанию: включен')
                
                self.log('Настройки планировщика загружены')
                
                # Восстанавливаем флаг активности дискотеки на основе расписания
                self.restore_disco_flag()
            else:
                self.log('Файл настроек не найден, используются значения по умолчанию')
                
        except Exception as e:
            self.log(f'Ошибка загрузки настроек: {str(e)}')
            self.log('Используются значения по умолчанию')
    
    def save_settings(self, settings):
        """
        Сохранение настроек в конфиг
        
        Args:
            settings (dict): Словарь с настройками
        """
        with self._config_lock:
            try:
                # Загружаем существующие настройки, чтобы не потерять другие данные
                existing_settings = {}
                if os.path.exists(self.config_file):
                    try:
                        with open(self.config_file, 'r', encoding='utf-8') as f:
                            existing_settings = json.load(f)
                    except Exception as e:
                        self.log(f'Ошибка загрузки существующих настроек: {e}')
                
                # Обновляем настройки планировщика
                if 'scheduled_days' in settings:
                    existing_settings['scheduled_days'] = settings['scheduled_days']
                    self.scheduled_days = settings['scheduled_days']
                
                if 'start_time' in settings:
                    existing_settings['start_time'] = settings['start_time']
                    self.start_time = time(settings['start_time']['hour'], settings['start_time']['minute'])
                
                if 'stop_time' in settings:
                    existing_settings['stop_time'] = settings['stop_time']
                    self.stop_time = time(settings['stop_time']['hour'], settings['stop_time']['minute'])
                
                if 'playlist_duration_hours' in settings:
                    existing_settings['playlist_duration_hours'] = float(settings['playlist_duration_hours'])
                    self.playlist_duration_hours = float(settings['playlist_duration_hours'])
                
                if 'scheduler_enabled' in settings:
                    existing_settings['scheduler_enabled'] = bool(settings['scheduler_enabled'])
                    self.scheduler_enabled = bool(settings['scheduler_enabled'])
                
                # Создаем временный файл для атомарной записи
                temp_file = self.config_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_settings, f, ensure_ascii=False, indent=2)
                
                # Атомарно заменяем файл
                os.replace(temp_file, self.config_file)
                    
                self.log('Настройки планировщика сохранены')
                
            except Exception as e:
                self.log(f'Ошибка сохранения настроек: {str(e)}')
                # Удаляем временный файл если он остался
                temp_file = self.config_file + '.tmp'
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
    
    def is_disco_scheduled_now(self):
        """Проверяет, должна ли дискотека быть активной в данный момент по расписанию."""
        now = datetime.now()
        current_day = now.weekday()
        current_time = now.time()
        
        # Проверяем, что сегодня запланированный день
        if current_day not in self.scheduled_days:
            return False
        
        # Проверяем, что текущее время находится в диапазоне работы дискотеки
        if self.start_time <= self.stop_time:
            # Обычный случай: начало и конец в один день
            return self.start_time <= current_time <= self.stop_time
        else:
            # Случай, когда дискотека работает через полночь
            return current_time >= self.start_time or current_time <= self.stop_time
    
    def restore_disco_flag(self):
        """Восстанавливает флаг активности дискотеки на основе текущего расписания."""
        try:
            # Проверяем, должна ли дискотека быть активной по расписанию
            should_be_active = self.is_disco_scheduled_now()
            
            if should_be_active:
                # Устанавливаем флаг активности
                self.disco_is_active = True
                self.log('🔄 Флаг дискотеки восстановлен: дискотека должна быть активна по расписанию')
            else:
                # Сбрасываем флаг активности
                self.disco_is_active = False
                self.log('🔄 Флаг дискотеки восстановлен: дискотека не должна быть активна по расписанию')
                
        except Exception as e:
            self.log(f'⚠️ Ошибка восстановления флага дискотеки: {e}')
            # В случае ошибки сбрасываем флаг
            self.disco_is_active = False
    
    def check_schedule(self):
        """
        Проверяет, нужно ли запустить задачу.
        Вызывается каждую секунду для проверки расписания.

        Returns:
            dict: Информация о выполненных действиях
        """
        # Проверяем необходимость смены конфигурации (независимо от состояния планировщика)
        try:
            config_result = self.config_manager.check_and_switch()
            if config_result['switched']:
                self.log(f"🔄 Конфигурация автоматически переключена на: {config_result['current_config']}")
        except Exception as e:
            self.log(f'⚠️ Ошибка проверки смены конфигурации: {e}')

        # Если планировщик отключен, не выполняем автоматические действия
        if not self.scheduler_enabled:
            return {'action': 'scheduler_disabled', 'message': 'Планировщик отключен'}

        now = datetime.now()
        current_day = now.weekday()
        current_time = now.time()
        result = {'action': None, 'message': None}
        
        # Синхронизируем флаг дискотеки с расписанием
        should_be_active = self.is_disco_scheduled_now()
        if should_be_active != self.disco_is_active:
            if should_be_active:
                self.disco_is_active = True
                result['action'] = 'disco_activated'
                self.log('🔄 Флаг дискотеки синхронизирован: дискотека должна быть активна')
            else:
                self.disco_is_active = False
                result['action'] = 'disco_deactivated'
                self.log('🔄 Флаг дискотеки синхронизирован: дискотека не должна быть активна')
        
        # Проверяем время запуска плейлиста
        if (current_day in self.scheduled_days and 
            current_time.hour == self.start_time.hour and 
            current_time.minute == self.start_time.minute):
            
            # Проверяем, не запускали ли мы генерацию уже в эту минуту
            current_minute_key = f"{now.strftime('%Y-%m-%d %H:%M')}"
            if self.last_generation_time != current_minute_key:
                self.log(f'⏰ Запланированный запуск: {now.strftime("%d.%m.%Y %H:%M")}')
                self.generate_and_launch()
                self.last_generation_time = current_minute_key
                result['action'] = 'playlist_generated'
                result['message'] = 'Плейлист сгенерирован и VLC запущен'
        
        # Проверяем время закрытия VLC (только в запланированные дни)
        if (current_day in self.scheduled_days and
            current_time.hour == self.stop_time.hour and 
            current_time.minute == self.stop_time.minute):
            
            # Проверяем, не закрывали ли мы VLC уже в эту минуту
            current_minute_key = f"{now.strftime('%Y-%m-%d %H:%M')}"
            if self.last_close_time != current_minute_key:
                self.log(f'⏰ Запланированное закрытие VLC: {now.strftime("%d.%m.%Y %H:%M")}')
                self.close_vlc(send_notification=True, is_automatic=True)
                self.last_close_time = current_minute_key
                result['action'] = 'vlc_closed'
                result['message'] = 'VLC закрыт'

        # Проверяем, что VLC жив во время активной дискотеки
        if (self.disco_is_active and should_be_active
                and not self.vlc_launcher.is_vlc_running()):
            # Защита от слишком частых перезапусков
            now_ts = time_module.time()
            if (self.last_vlc_restart_time is None
                    or now_ts - self.last_vlc_restart_time > self.vlc_restart_cooldown):
                self.log('⚠️ VLC не запущен во время дискотеки! Автоматический перезапуск...')
                playlists = self.vlc_launcher.find_playlists()
                if playlists:
                    playlist = self.vlc_launcher.get_latest_playlist(playlists)
                    if playlist and self.vlc_launcher.launch_vlc(playlist, close_existing=True):
                        self.last_vlc_restart_time = now_ts
                        self.log('✅ VLC перезапущен автоматически')
                        result['action'] = 'vlc_restarted'
                        result['message'] = 'VLC перезапущен после падения'
                    else:
                        self.log('❌ Не удалось перезапустить VLC')
                else:
                    self.log('❌ Плейлисты не найдены для перезапуска VLC')

        return result
    
    def calculate_disco_duration_hours(self):
        """
        Вычисляет длительность дискотеки в часах на основе start_time и stop_time.
        Уменьшает длительность на 3 минуты для плейлиста.

        Returns:
            float: Длительность в часах (на 3 минуты меньше времени дискотеки)
        """
        start_datetime = datetime.combine(datetime.now().date(), self.start_time)
        stop_datetime = datetime.combine(datetime.now().date(), self.stop_time)

        # Если stop_time меньше start_time, значит дискотека работает через полночь
        if self.stop_time < self.start_time:
            stop_datetime += timedelta(days=1)

        duration = stop_datetime - start_datetime
        # Вычитаем 3 минуты (180 секунд) из длительности
        duration_seconds = duration.total_seconds() - 180
        duration_hours = duration_seconds / 3600.0

        return duration_hours
    
    def generate_and_launch(self):
        """Генерирует плейлист и запускает VLC."""
        try:
            self.log('Начинаю генерацию плейлиста...')

            # Вычисляем длительность дискотеки из расписания
            disco_duration_hours = self.calculate_disco_duration_hours()
            self.log(f'Длительность дискотеки: {disco_duration_hours:.3f} часов ({int(disco_duration_hours)}ч {int((disco_duration_hours % 1) * 60)}м)')

            # Получаем активный конфиг из ConfigManager
            current_config = self.config_manager.state.get('current_config', 'zhenya')
            config_filename = f'config_{current_config}.txt'
            config_path = get_resource_path(config_filename)

            self.log(f'📋 Используется конфиг: {current_config} ({config_filename})')

            # Генерируем плейлист
            generator = PlaylistGenerator(
                music_folder=os.path.join(get_exe_dir(), 'mp3'),
                config_file=config_path
            )
            playlist = generator.create_playlist(disco_duration_hours)
            
            if not playlist:
                self.log('❌ Ошибка: плейлист пуст')
                return False
                
            # Сохраняем плейлист
            playlist_file = generator.save_playlist()
            
            if not playlist_file:
                self.log('❌ Ошибка при сохранении плейлиста')
                return False
                
            info = generator.get_playlist_info()
            self.log(f'✅ Плейлист создан: {info}')
            
            # Запускаем VLC (с автоматическим закрытием старых экземпляров)
            self.log('Запускаю VLC плеер...')
            
            if self.vlc_launcher.launch_vlc(playlist_file, close_existing=True):
                self.log('✅ VLC запущен, ожидаю запуск процесса (до 15 сек)...')
                # На Orange Pi VLC может запускаться до 10 секунд
                vlc_started = False
                for i in range(15):
                    time_module.sleep(1)
                    if self.vlc_launcher.is_vlc_running():
                        vlc_started = True
                        self.log(f'✅ VLC работает (обнаружен через {i + 1} сек)')
                        break
                if not vlc_started:
                    self.log('⚠️ VLC не обнаружен! Повторная попытка запуска...')
                    self.vlc_launcher.launch_vlc(playlist_file, close_existing=True)
                    for i in range(15):
                        time_module.sleep(1)
                        if self.vlc_launcher.is_vlc_running():
                            vlc_started = True
                            self.log(f'✅ VLC запущен со второй попытки (через {i + 1} сек)')
                            break
                    if not vlc_started:
                        self.log('❌ VLC не удалось запустить после 2 попыток')
                        return False
                # Устанавливаем флаг активности дискотеки
                self.disco_is_active = True
                # Сбрасываем флаг автоматического закрытия (при запуске дискотеки)
                self.is_automatic_close = True
                # Отправляем уведомление о начале дискотеки в отдельном потоке (чтобы не блокировать запуск музыки)
                def _send_notification():
                    try:
                        self.log(f'📱 Отправка уведомления в ВК с плейлистом ({len(playlist)} треков)...')
                        self.telegram_bot.notify_disco_started(playlist=playlist, start_time=self.start_time)
                        self.log(f'✅ Уведомление с плейлистом отправлено в ВК')
                    except Exception as e:
                        self.log(f'⚠️ Ошибка отправки ВК уведомления: {e}')
                Thread(target=_send_notification, daemon=True).start()
                return True
            else:
                self.log('❌ Ошибка при запуске VLC')
                return False
                
        except Exception as e:
            self.log(f'❌ Ошибка: {str(e)}')
            return False
    
    def manual_generate_playlist(self):
        """Ручная генерация плейлиста."""
        self.log('Ручная генерация плейлиста...')
        try:
            # Получаем активный конфиг из ConfigManager
            current_config = self.config_manager.state.get('current_config', 'zhenya')
            config_filename = f'config_{current_config}.txt'
            config_path = get_resource_path(config_filename)

            self.log(f'📋 Используется конфиг: {current_config} ({config_filename})')

            generator = PlaylistGenerator(
                music_folder=os.path.join(get_exe_dir(), 'mp3'),
                config_file=config_path
            )
            playlist = generator.create_playlist(self.playlist_duration_hours)

            if playlist:
                playlist_file = generator.save_playlist()
                info = generator.get_playlist_info()
                self.log(f'✅ {info}')
                return True
            else:
                self.log('❌ Плейлист пуст')
                return False

        except Exception as e:
            self.log(f'❌ Ошибка: {str(e)}')
            return False
    
    def manual_launch_vlc(self):
        """Ручной запуск VLC."""
        self.log('Ручной запуск VLC...')
        try:
            playlists = self.vlc_launcher.find_playlists()
            
            if not playlists:
                self.log('❌ Плейлисты не найдены')
                return False
                
            playlist = self.vlc_launcher.get_latest_playlist(playlists)
            
            if playlist and self.vlc_launcher.launch_vlc(playlist, close_existing=True):
                self.log('✅ VLC запущен')
                # Устанавливаем флаг активности дискотеки при ручном запуске
                self.disco_is_active = True
                # Сбрасываем флаг автоматического закрытия (при ручном запуске)
                self.is_automatic_close = True
                return True
            else:
                self.log('❌ Ошибка запуска VLC')
                return False
                
        except Exception as e:
            self.log(f'❌ Ошибка: {str(e)}')
            return False
    
    def close_vlc(self, send_notification=True, is_automatic=True):
        """Закрывает все процессы VLC."""
        try:
            # Устанавливаем флаг типа закрытия
            self.is_automatic_close = is_automatic

            closed_count = self.vlc_launcher.close_all_vlc()

            if closed_count > 0:
                # Отправляем уведомление о завершении дискотеки только если это автоматическое закрытие
                if send_notification and is_automatic:
                    def _send_stop_notification():
                        try:
                            self.telegram_bot.notify_disco_stopped()
                        except Exception as e:
                            self.log(f'⚠️ Ошибка отправки ВК уведомления: {e}')
                    Thread(target=_send_stop_notification, daemon=True).start()
                return True

            return False

        except Exception as e:
            self.log(f'❌ Ошибка при закрытии VLC: {str(e)}')
            return False
    
    def enable_scheduler(self):
        """Включает планировщик"""
        self.scheduler_enabled = True
        self.log('✅ Планировщик включен')
        # Сохраняем только изменение состояния планировщика
        self._save_scheduler_state()
    
    def disable_scheduler(self):
        """Отключает планировщик"""
        self.scheduler_enabled = False
        self.log('❌ Планировщик отключен')
        # Сохраняем только изменение состояния планировщика
        self._save_scheduler_state()
    
    def toggle_scheduler(self):
        """Переключает состояние планировщика"""
        if self.scheduler_enabled:
            self.disable_scheduler()
        else:
            self.enable_scheduler()
        return self.scheduler_enabled
    
    def _save_scheduler_state(self):
        """Сохраняет только состояние планировщика в конфиг"""
        with self._config_lock:
            try:
                # Загружаем существующие настройки
                existing_settings = {}
                if os.path.exists(self.config_file):
                    try:
                        with open(self.config_file, 'r', encoding='utf-8') as f:
                            existing_settings = json.load(f)
                    except Exception as e:
                        self.log(f'Ошибка загрузки существующих настроек: {e}')
                
                # Обновляем только состояние планировщика
                existing_settings['scheduler_enabled'] = bool(self.scheduler_enabled)
                
                # Создаем временный файл для атомарной записи
                temp_file = self.config_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_settings, f, ensure_ascii=False, indent=2)
                
                # Атомарно заменяем файл
                os.replace(temp_file, self.config_file)
                    
                self.log('Состояние планировщика сохранено в конфиг')
                
            except Exception as e:
                self.log(f'Ошибка сохранения состояния планировщика: {str(e)}')
                # Удаляем временный файл если он остался
                temp_file = self.config_file + '.tmp'
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
    
    def get_status(self):
        """
        Получение текущего статуса планировщика
        
        Returns:
            dict: Словарь с информацией о статусе
        """
        return {
            'scheduled_days': self.scheduled_days,
            'start_time': {'hour': self.start_time.hour, 'minute': self.start_time.minute},
            'stop_time': {'hour': self.stop_time.hour, 'minute': self.stop_time.minute},
            'playlist_duration_hours': self.playlist_duration_hours,
            'disco_is_active': self.disco_is_active,
            'scheduler_enabled': self.scheduler_enabled
        }
    
    def get_next_run(self):
        """
        Вычисляет следующий запланированный запуск
        
        Returns:
            dict: Информация о следующем запуске или None
        """
        if not self.scheduled_days or not self.scheduler_enabled:
            return None
        
        now = datetime.now()
        
        # Проверяем на сегодня
        if now.weekday() in self.scheduled_days:
            today_run = now.replace(hour=self.start_time.hour, 
                                   minute=self.start_time.minute, 
                                   second=0, 
                                   microsecond=0)
            if today_run > now:
                return {
                    'date': today_run.strftime('%d.%m.%Y'),
                    'time': today_run.strftime('%H:%M'),
                    'day_name': ['Понедельник', 'Вторник', 'Среда', 'Четверг', 
                                'Пятница', 'Суббота', 'Воскресенье'][today_run.weekday()]
                }
        
        # Ищем в следующие 7 дней
        for days_ahead in range(1, 8):
            check_date = now + timedelta(days=days_ahead)
            if check_date.weekday() in self.scheduled_days:
                next_run = check_date.replace(hour=self.start_time.hour, 
                                             minute=self.start_time.minute, 
                                             second=0, 
                                             microsecond=0)
                return {
                    'date': next_run.strftime('%d.%m.%Y'),
                    'time': next_run.strftime('%H:%M'),
                    'day_name': ['Понедельник', 'Вторник', 'Среда', 'Четверг', 
                                'Пятница', 'Суббота', 'Воскресенье'][next_run.weekday()]
                }
        
        return None
    
    def get_current_track_info(self):
        """
        Получает информацию о текущем воспроизводимом треке.
        
        Returns:
            dict: Информация о треке или None если VLC не запущен или трек недоступен
        """
        try:
            # Сначала проверяем, запущен ли VLC (независимо от флага disco_is_active)
            if not self.vlc_launcher.is_vlc_running():
                return {
                    'is_available': False,
                    'reason': 'VLC не запущен',
                    'title': 'VLC не запущен',
                    'artist': '',
                    'time_str': '',
                    'is_playing': False
                }
            
            # Если VLC запущен, но дискотека не активна по расписанию - все равно показываем трек
            # (это может быть ручной запуск)
            if not self.disco_is_active:
                self.log('VLC запущен вручную, отображаем информацию о треке')
            
            # Получаем информацию о треке от VLC
            track_info = self.vlc_launcher.get_current_track_info()
            
            if track_info:
                result = {
                    'is_available': True,
                    'title': track_info.get('title', 'Неизвестный трек'),
                    'artist': track_info.get('artist', ''),
                    'time_str': track_info.get('time_str', ''),
                    'is_playing': track_info.get('is_playing', False),
                    'filename': track_info.get('filename', '')
                }
                
                # Формируем полное название трека
                if result['artist'] and result['title']:
                    result['full_title'] = f"{result['artist']} - {result['title']}"
                else:
                    result['full_title'] = result['title']
                
                return result
            else:
                return {
                    'is_available': False,
                    'reason': 'HTTP API VLC недоступен',
                    'title': 'Информация недоступна',
                    'artist': '',
                    'time_str': '',
                    'is_playing': False
                }
                
        except Exception as e:
            self.log(f'Ошибка получения информации о треке: {str(e)}')
            return {
                'is_available': False,
                'reason': f'Ошибка: {str(e)}',
                'title': 'Ошибка получения информации',
                'artist': '',
                'time_str': '',
                'is_playing': False
            }
    
    def next_track(self):
        """
        Переключает на следующий трек в VLC.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            if not self.vlc_launcher.is_vlc_running():
                self.log('VLC не запущен, невозможно переключить трек')
                return False
            
            success = self.vlc_launcher.next_track()
            if success:
                self.log('⏭️ Переключен на следующий трек')
            else:
                self.log('❌ Ошибка переключения на следующий трек')
            return success
        except Exception as e:
            self.log(f'Ошибка переключения на следующий трек: {str(e)}')
            return False
    
    def previous_track(self):
        """
        Переключает на предыдущий трек в VLC.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            if not self.vlc_launcher.is_vlc_running():
                self.log('VLC не запущен, невозможно переключить трек')
                return False
            
            success = self.vlc_launcher.previous_track()
            if success:
                self.log('⏮️ Переключен на предыдущий трек')
            else:
                self.log('❌ Ошибка переключения на предыдущий трек')
            return success
        except Exception as e:
            self.log(f'Ошибка переключения на предыдущий трек: {str(e)}')
            return False
    
    def play_pause_track(self):
        """
        Переключает воспроизведение/паузу в VLC.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            if not self.vlc_launcher.is_vlc_running():
                self.log('VLC не запущен, невозможно управлять воспроизведением')
                return False
            
            success = self.vlc_launcher.play_pause()
            if success:
                self.log('⏯️ Переключено воспроизведение/пауза')
            else:
                self.log('❌ Ошибка переключения воспроизведения/паузы')
            return success
        except Exception as e:
            self.log(f'Ошибка управления воспроизведением: {str(e)}')
            return False
    
    def stop_track(self):
        """
        Останавливает воспроизведение в VLC.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            if not self.vlc_launcher.is_vlc_running():
                self.log('VLC не запущен, невозможно остановить воспроизведение')
                return False
            
            success = self.vlc_launcher.stop()
            if success:
                self.log('⏹️ Воспроизведение остановлено')
            else:
                self.log('❌ Ошибка остановки воспроизведения')
            return success
        except Exception as e:
            self.log(f'Ошибка остановки воспроизведения: {str(e)}')
            return False
    
    def set_volume(self, volume):
        """
        Устанавливает громкость VLC.

        Args:
            volume (int): Громкость от 0 до 320 (100 = нормальная громкость)

        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            if not self.vlc_launcher.is_vlc_running():
                self.log('VLC не запущен, невозможно изменить громкость')
                return False

            success = self.vlc_launcher.set_volume(volume)
            if success:
                self.log(f'🔊 Громкость установлена: {volume}%')
            else:
                self.log('❌ Ошибка изменения громкости')
            return success
        except Exception as e:
            self.log(f'Ошибка изменения громкости: {str(e)}')
            return False

    def get_config_status(self):
        """
        Получает информацию о текущей конфигурации.

        Returns:
            dict: Информация о конфигурации
        """
        try:
            return self.config_manager.get_status()
        except Exception as e:
            self.log(f'Ошибка получения статуса конфигурации: {str(e)}')
            return None

    def set_config(self, config_name):
        """
        Устанавливает конкретную конфигурацию.

        Args:
            config_name (str): Имя конфигурации ('zhenya' или 'ruslan')

        Returns:
            bool: True если установка выполнена успешно
        """
        try:
            success = self.config_manager.set_config(config_name)
            if success:
                self.log(f'✅ Конфигурация установлена: {config_name}')
            else:
                self.log(f'❌ Ошибка установки конфигурации: {config_name}')
            return success
        except Exception as e:
            self.log(f'Ошибка установки конфигурации: {str(e)}')
            return False

    def switch_config_manually(self):
        """
        Принудительно переключает конфигурацию на следующую.

        Returns:
            bool: True если переключение выполнено успешно
        """
        try:
            success = self.config_manager.force_switch()
            if success:
                status = self.config_manager.get_status()
                self.log(f'✅ Конфигурация переключена на: {status["current_config"]}')
            else:
                self.log('❌ Ошибка переключения конфигурации')
            return success
        except Exception as e:
            self.log(f'Ошибка переключения конфигурации: {str(e)}')
            return False


def main():
    """Тестовая функция"""
    print("=== Планировщик дискотеки ===")
    
    scheduler = DiscoScheduler()
    
    print(f"Дни запуска: {scheduler.scheduled_days}")
    print(f"Время запуска: {scheduler.start_time}")
    print(f"Время остановки: {scheduler.stop_time}")
    print(f"Длительность плейлиста: {scheduler.playlist_duration_hours} часов")
    print(f"Дискотека активна: {scheduler.disco_is_active}")
    
    # Меню для тестирования
    while True:
        print("\n--- Меню тестирования ---")
        print("1. Проверить расписание")
        print("2. Сгенерировать плейлист")
        print("3. Запустить VLC")
        print("4. Закрыть VLC")
        print("5. Показать статус")
        print("6. Переключить планировщик")
        print("7. Включить планировщик")
        print("8. Отключить планировщик")
        print("0. Выход")
        
        choice = input("\nВыберите действие: ").strip()
        
        if choice == '1':
            result = scheduler.check_schedule()
            print(f"Результат проверки: {result}")
        elif choice == '2':
            scheduler.manual_generate_playlist()
        elif choice == '3':
            scheduler.manual_launch_vlc()
        elif choice == '4':
            scheduler.close_vlc()
        elif choice == '5':
            status = scheduler.get_status()
            print(f"\nСтатус планировщика:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        elif choice == '6':
            enabled = scheduler.toggle_scheduler()
            print(f"Планировщик {'включен' if enabled else 'отключен'}")
        elif choice == '7':
            scheduler.enable_scheduler()
        elif choice == '8':
            scheduler.disable_scheduler()
        elif choice == '0':
            print("Выход...")
            break
        else:
            print("❌ Неверный выбор")


if __name__ == '__main__':
    main()

