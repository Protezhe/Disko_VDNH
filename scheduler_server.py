#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автономный сервер планировщика дискотеки без GUI.
Запускает планировщик, мониторинг звука и веб-API на основе конфига.
Для production использования. 123
"""

import sys
import os
import json
import time
import signal
import socket
import subprocess
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from threading import Thread, Lock

from scheduler import DiscoScheduler
from soundcheck import SoundCheck
from soundcheck_v2 import SoundCheckV2
from audio_monitor import AudioMonitor, get_audio_devices_list
from cleanup_utils import cleanup_on_startup


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_local_ip():
    """Получает локальный IP адрес машины."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            return ip
        except:
            return "127.0.0.1"


class DiscoServer:
    """Автономный сервер планировщика дискотеки"""
    
    def __init__(self):
        self.config_file = os.path.join(get_exe_dir(), 'scheduler_config.json')
        self.running = True

        # Очистка служебных файлов при запуске
        music_folder = os.path.join(get_exe_dir(), 'mp3')
        cleanup_on_startup(music_folder)

        # Lock для безопасной записи в конфиг из разных потоков
        self.config_lock = Lock()
        
        # Флаг автозапуска саундчека и время запуска до старта дискотеки
        self.soundcheck_schedule_enabled = False
        self.soundcheck_minutes_before_disco = 30  # по умолчанию 30 минут
        self.soundcheck_last_trigger_key = None  # защита от повторов на один и тот же запуск
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    self.soundcheck_schedule_enabled = bool(cfg.get('soundcheck_schedule_enabled', False))
                    self.soundcheck_minutes_before_disco = int(cfg.get('soundcheck_minutes_before_disco', 30))
        except Exception as e:
            # Не критично
            self.log(f"⚠️ Не удалось прочитать состояние автосаундчека из конфига: {e}")
        
        # Инициализация планировщика
        self.scheduler = DiscoScheduler(config_file=self.config_file, log_callback=self.log)

        # Инициализация мониторинга звука
        self.audio_monitor = None
        self.init_audio_monitor()

        # Запуск VK-бота в отдельном потоке
        self.vk_bot_thread = None
        self.init_vk_bot()

        # Инициализация Flask приложения
        self.app = Flask(__name__)
        CORS(self.app)
        self.setup_routes()

        # Обработка сигналов завершения
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def log(self, message):
        """Логирование с timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] {message}')
    
    def init_audio_monitor(self):
        """Инициализация мониторинга звука"""
        try:
            self.audio_monitor = AudioMonitor(config_file=self.config_file)
            
            # Устанавливаем колбэки
            self.audio_monitor.set_callbacks(
                on_silence_detected=self.on_silence_detected,
                on_sound_restored=self.on_sound_restored,
                on_silence_warning=self.on_silence_warning,
                on_level_updated=self.on_level_updated
            )
            
            # Запускаем мониторинг если он включен в конфиге
            if self.audio_monitor.monitoring_enabled:
                self.audio_monitor.start_monitoring()
                self.log("✅ Мониторинг звука запущен")
            else:
                self.log("ℹ️ Мониторинг звука отключен в конфиге")
                
        except Exception as e:
            self.log(f"❌ Ошибка инициализации мониторинга звука: {e}")

    def init_vk_bot(self):
        """Инициализация и запуск VK-бота в отдельном потоке"""
        try:
            if self.scheduler.telegram_bot and self.scheduler.telegram_bot.bot:
                self.log("🤖 Запуск VK-бота в отдельном потоке...")

                def run_bot():
                    try:
                        self.scheduler.telegram_bot.start_polling()
                    except Exception as e:
                        self.log(f"❌ Ошибка в работе VK-бота: {e}")

                self.vk_bot_thread = Thread(target=run_bot, daemon=True, name="VKBot")
                self.vk_bot_thread.start()
                self.log("✅ VK-бот запущен (уведомления + команды)")
            else:
                self.log("ℹ️ VK-бот не активирован")
        except Exception as e:
            self.log(f"❌ Ошибка запуска VK-бота: {e}")

    def on_silence_detected(self, level):
        """Обработчик обнаружения тишины"""
        self.log(f"🔇 Обнаружена тишина (уровень: {level:.6f})")
    
    def on_sound_restored(self, silence_time):
        """Обработчик восстановления звука"""
        self.log(f"🔊 Звук восстановлен после {silence_time:.1f}с тишины")
        
        # Отправляем уведомление если сейчас время дискотеки по расписанию
        if self.scheduler.is_disco_scheduled_now():
            try:
                result = self.scheduler.telegram_bot.notify_music_restored(silence_time)
                if result:
                    self.log(f"✅ Уведомление о восстановлении отправлено в ВК")
                else:
                    self.log(f"ℹ️ Уведомление о восстановлении не отправлено")
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки ВК уведомления: {e}')
        else:
            self.log(f"ℹ️ Уведомление не отправлено: вне расписания дискотеки")

    def on_silence_warning(self, silence_time):
        """Обработчик предупреждения о длительной тишине"""
        self.log(f"⚠️ ТИШИНА! {silence_time:.0f}с")
        
        # Отправляем уведомление если сейчас время дискотеки по расписанию
        if self.scheduler.is_disco_scheduled_now():
            try:
                self.log(f"📱 Отправка уведомления о тишине в ВК...")
                result = self.scheduler.telegram_bot.notify_music_stopped(silence_time)
                if result:
                    self.log(f"✅ Уведомление о тишине отправлено в ВК")
                else:
                    self.log(f"❌ Уведомление не отправлено (бот не активирован или уведомления отключены)")
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки ВК уведомления: {e}')
        else:
            now = datetime.now()
            self.log(f"ℹ️ Уведомление не отправлено: вне расписания (день: {now.weekday()}, время: {now.strftime('%H:%M')})")
    
    def on_level_updated(self, level):
        """Обработчик обновления уровня звука (без вывода в лог, чтобы не засорять)"""
        pass
    
    def _safe_update_config(self, updates):
        """
        Безопасное обновление конфига с блокировкой
        
        Args:
            updates (dict): Словарь с обновлениями для конфига
        """
        with self.config_lock:
            try:
                # Загружаем существующие настройки
                existing_settings = {}
                if os.path.exists(self.config_file):
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing_settings = json.load(f)
                
                # Применяем обновления
                existing_settings.update(updates)
                
                # Создаем временный файл для атомарной записи
                temp_file = self.config_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_settings, f, ensure_ascii=False, indent=2)
                
                # Атомарно заменяем файл
                os.replace(temp_file, self.config_file)
                
                return True
            except Exception as e:
                self.log(f"❌ Ошибка обновления конфига: {e}")
                # Удаляем временный файл если он остался
                temp_file = self.config_file + '.tmp'
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass
                return False
    
    def _save_monitoring_enabled_to_config(self, enabled):
        """Сохраняет состояние мониторинга в конфиг"""
        try:
            success = self._safe_update_config({'monitoring_enabled': enabled})
            if success:
                self.log(f"💾 Состояние мониторинга сохранено в конфиг: {'включен' if enabled else 'отключен'}")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения состояния мониторинга: {e}")
    
    def _save_audio_settings_to_config(self):
        """Сохраняет настройки аудио мониторинга в конфиг"""
        try:
            # Подготавливаем обновления
            updates = {}
            if self.audio_monitor:
                updates['audio_threshold'] = float(self.audio_monitor.threshold)
                updates['audio_silence_duration'] = int(self.audio_monitor.silence_duration)
                updates['audio_sound_confirmation_duration'] = int(self.audio_monitor.sound_confirmation_duration)
                updates['audio_buffer_size'] = int(self.audio_monitor.buffer_size)
                if self.audio_monitor.device_index is not None:
                    updates['audio_device_index'] = int(self.audio_monitor.device_index)
            
            success = self._safe_update_config(updates)
            if success:
                self.log("💾 Настройки аудио мониторинга сохранены в конфиг")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения настроек аудио мониторинга: {e}")
    
    def _save_soundcheck_schedule_enabled_to_config(self, enabled):
        """Сохраняет состояние автосаундчека в конфиг"""
        try:
            success = self._safe_update_config({'soundcheck_schedule_enabled': bool(enabled)})
            if success:
                self.log(f"💾 Авто-саундчек по расписанию: {'включен' if enabled else 'отключен'}")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения состояния авто-саундчека: {e}")
    
    def _save_soundcheck_minutes_to_config(self, minutes):
        """Сохраняет количество минут до запуска саундчека в конфиг"""
        try:
            success = self._safe_update_config({'soundcheck_minutes_before_disco': int(minutes)})
            if success:
                self.log(f"💾 Авто-саундчек: за {minutes} минут до дискотеки")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения времени авто-саундчека: {e}")
    
    def _save_soundcheck_duration_to_config(self, duration):
        """Сохраняет длительность саундчека в конфиг"""
        try:
            success = self._safe_update_config({'soundcheck_duration_seconds': int(duration)})
            if success:
                self.log(f"💾 Длительность саундчека: {duration} секунд")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения длительности саундчека: {e}")

    def run_soundcheck_and_notify(self):
        """Запуск саундчека V2, расчет схожести и отправка в ВК при необходимости"""
        sc2 = SoundCheckV2(audio_monitor=self.audio_monitor)
        sc2.run_soundcheck()
        similarity = sc2.compare_with_previous()
        similarity = float(similarity) if similarity is not None else None
        verdict = None
        if similarity is not None:
            if similarity >= 90:
                verdict = 'Саундчек — ОК'
            else:
                verdict = 'Громкость изменилась'
        image_path_new = os.path.join(get_exe_dir(), 'soundcheck_graph_v2.png')
        image_path_ref = os.path.join(get_exe_dir(), 'soundcheck_graph.png')
        sent = False
        if self.scheduler.telegram_bot and self.scheduler.telegram_bot.enabled and self.scheduler.telegram_bot.notifications_enabled:
            caption_lines = []
            if verdict:
                caption_lines.append(verdict)
            if similarity is not None:
                caption_lines.append(f"Схожесть: {similarity:.2f}%")
            caption = "\n".join(caption_lines) if caption_lines else 'Саундчек'
            try:
                paths = []
                if os.path.exists(image_path_ref):
                    paths.append(image_path_ref)
                if os.path.exists(image_path_new):
                    paths.append(image_path_new)
                if len(paths) >= 2:
                    sent = self.scheduler.telegram_bot.send_media_group(paths, caption=caption)
                elif len(paths) == 1:
                    sent = self.scheduler.telegram_bot.send_photo(paths[0], caption=caption)
                else:
                    sent = self.scheduler.telegram_bot.send_message(caption)
            except Exception as te:
                self.log(f"⚠️ Ошибка отправки ВК сообщения: {te}")
        return {
            'success': True,
            'similarity': similarity,
            'verdict': verdict,
            'vk_sent': sent,
            'graph_paths': [p for p in [image_path_ref, image_path_new] if os.path.exists(p)]
        }
    
    def setup_routes(self):
        """Настройка маршрутов API"""
        
        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            # Получаем информацию о следующем запуске
            next_run = self.scheduler.get_next_run()
            
            return jsonify({
                'status': 'running',
                'current_time': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                'scheduled_days': self.scheduler.scheduled_days,
                'start_time': f"{self.scheduler.start_time.hour:02d}:{self.scheduler.start_time.minute:02d}",
                'stop_time': f"{self.scheduler.stop_time.hour:02d}:{self.scheduler.stop_time.minute:02d}",
                'disco_is_active': self.scheduler.disco_is_active,
                'scheduler_enabled': self.scheduler.scheduler_enabled,
                'next_run': next_run
            })
        
        @self.app.route('/api/generate', methods=['POST'])
        def generate_playlist():
            try:
                success = self.scheduler.manual_generate_playlist()
                if success:
                    return jsonify({'success': True, 'message': 'Плейлист сгенерирован'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка генерации плейлиста'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/launch', methods=['POST'])
        def launch_vlc():
            try:
                success = self.scheduler.manual_launch_vlc()
                if success:
                    return jsonify({'success': True, 'message': 'VLC запущен'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка запуска VLC'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/close', methods=['POST'])
        def close_vlc():
            try:
                success = self.scheduler.close_vlc(send_notification=False)
                if success:
                    return jsonify({'success': True, 'message': 'VLC закрыт'})
                else:
                    return jsonify({'success': False, 'message': 'Процессы VLC не найдены'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/settings', methods=['GET'])
        def get_settings():
            settings = {
                'scheduled_days': self.scheduler.scheduled_days,
                'start_time': {
                    'hour': self.scheduler.start_time.hour,
                    'minute': self.scheduler.start_time.minute
                },
                'stop_time': {
                    'hour': self.scheduler.stop_time.hour,
                    'minute': self.scheduler.stop_time.minute
                },
                'playlist_duration_hours': self.scheduler.playlist_duration_hours,
                'scheduler_enabled': self.scheduler.scheduler_enabled,
                'soundcheck_minutes_before_disco': self.soundcheck_minutes_before_disco
            }
            
            # Загружаем дополнительные настройки из конфига
            try:
                if os.path.exists(self.config_file):
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        settings['soundcheck_duration_seconds'] = config.get('soundcheck_duration_seconds', 10)
            except Exception as e:
                self.log(f"⚠️ Ошибка загрузки настроек саундчека из конфига: {e}")
                settings['soundcheck_duration_seconds'] = 10
            
            if self.audio_monitor:
                settings.update({
                    'audio_threshold': self.audio_monitor.threshold,
                    'audio_silence_duration': self.audio_monitor.silence_duration,
                    'audio_sound_confirmation_duration': self.audio_monitor.sound_confirmation_duration,
                    'audio_buffer_size': self.audio_monitor.buffer_size,
                    'audio_device_index': self.audio_monitor.device_index,
                    'monitoring_enabled': self.audio_monitor.monitoring_enabled
                })
            
            return jsonify(settings)
        
        @self.app.route('/api/settings', methods=['POST'])
        def update_settings():
            try:
                data = request.get_json()
                
                # Обновляем настройки планировщика
                settings = {}
                
                if 'scheduled_days' in data:
                    settings['scheduled_days'] = data['scheduled_days']
                if 'start_time' in data:
                    settings['start_time'] = data['start_time']
                if 'stop_time' in data:
                    settings['stop_time'] = data['stop_time']
                if 'playlist_duration_hours' in data:
                    settings['playlist_duration_hours'] = data['playlist_duration_hours']
                if 'scheduler_enabled' in data:
                    settings['scheduler_enabled'] = data['scheduler_enabled']
                
                # Сохраняем настройки
                self.scheduler.save_settings(settings)
                
                # Обновляем настройки мониторинга
                if self.audio_monitor:
                    audio_settings_updated = False
                    if 'audio_threshold' in data:
                        old_threshold = self.audio_monitor.threshold
                        self.audio_monitor.threshold = data['audio_threshold']
                        self.log(f"📊 Порог звука изменен: {old_threshold} → {self.audio_monitor.threshold}")
                        audio_settings_updated = True
                    if 'audio_silence_duration' in data:
                        old_duration = self.audio_monitor.silence_duration
                        self.audio_monitor.silence_duration = data['audio_silence_duration']
                        self.log(f"⏱️ Длительность тишины изменена: {old_duration}с → {self.audio_monitor.silence_duration}с")
                        audio_settings_updated = True
                    if 'audio_sound_confirmation_duration' in data:
                        self.audio_monitor.sound_confirmation_duration = data['audio_sound_confirmation_duration']
                        audio_settings_updated = True
                    if 'audio_buffer_size' in data:
                        self.audio_monitor.buffer_size = data['audio_buffer_size']
                        audio_settings_updated = True
                    if 'audio_device_index' in data:
                        self.audio_monitor.device_index = data['audio_device_index']
                        audio_settings_updated = True
                    
                    # Сохраняем аудио настройки в конфиг если они изменились
                    if audio_settings_updated:
                        self._save_audio_settings_to_config()
                    
                    # Обновляем состояние мониторинга, если оно изменилось
                    if 'monitoring_enabled' in data:
                        new_monitoring_enabled = data['monitoring_enabled']
                        current_enabled = self.audio_monitor.monitoring_enabled
                        
                        if new_monitoring_enabled != current_enabled:
                            # Изменяем состояние
                            self.audio_monitor.monitoring_enabled = new_monitoring_enabled
                            
                            # Запускаем или останавливаем мониторинг
                            if new_monitoring_enabled and not self.audio_monitor.is_monitoring:
                                self.audio_monitor.start_monitoring()
                                self.log("✅ Мониторинг звука запущен через API")
                            elif not new_monitoring_enabled and self.audio_monitor.is_monitoring:
                                self.audio_monitor.stop_monitoring()
                                self.log("⏹️ Мониторинг звука остановлен через API")
                            
                            # Сохраняем состояние в конфиг
                            self._save_monitoring_enabled_to_config(new_monitoring_enabled)
                
                return jsonify({'success': True, 'message': 'Настройки обновлены'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/audio_status', methods=['GET'])
        def get_audio_status():
            """Получение статуса мониторинга звука"""
            try:
                if self.audio_monitor:
                    status = self.audio_monitor.get_lamp_status()
                    # Преобразуем float32 в обычный float для JSON сериализации
                    if 'audio_level' in status:
                        status['audio_level'] = float(status['audio_level'])
                    status['disco_is_active'] = self.scheduler.disco_is_active
                    return jsonify(status)
                else:
                    return jsonify({
                        'lamp_lit': False,
                        'audio_level': 0.0,
                        'monitoring_active': False,
                        'monitoring_enabled': False,
                        'disco_is_active': self.scheduler.disco_is_active
                    })
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/audio_devices', methods=['GET'])
        def api_get_audio_devices():
            """Получение списка доступных аудиоустройств"""
            try:
                devices = get_audio_devices_list()
                return jsonify(devices)
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/scheduler/toggle', methods=['POST'])
        def toggle_scheduler():
            """Переключение состояния планировщика"""
            try:
                enabled = self.scheduler.toggle_scheduler()
                status = 'включен' if enabled else 'отключен'
                return jsonify({'success': True, 'message': f'Планировщик {status}', 'enabled': enabled})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/scheduler/status', methods=['GET'])
        def get_scheduler_status():
            """Получение статуса планировщика"""
            try:
                status = self.scheduler.get_status()
                return jsonify(status)
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/monitoring/toggle', methods=['POST'])
        def toggle_monitoring():
            """Переключение состояния мониторинга звука"""
            try:
                if self.audio_monitor:
                    enabled = self.audio_monitor.toggle_monitoring()
                    
                    # Сохраняем состояние в конфиг
                    self._save_monitoring_enabled_to_config(enabled)
                    
                    # Если мониторинг включен, запускаем его
                    if enabled and not self.audio_monitor.is_monitoring:
                        self.audio_monitor.start_monitoring()
                    
                    status = 'включен' if enabled else 'отключен'
                    return jsonify({'success': True, 'message': f'Мониторинг звука {status}', 'enabled': enabled})
                else:
                    return jsonify({'success': False, 'message': 'Мониторинг не инициализирован'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/monitoring/status', methods=['GET'])
        def get_monitoring_status():
            """Получение статуса мониторинга звука"""
            try:
                if self.audio_monitor:
                    status = self.audio_monitor.get_lamp_status()
                    return jsonify(status)
                else:
                    return jsonify({'error': 'Мониторинг не инициализирован'})
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/telegram/notifications/toggle', methods=['POST'])
        @self.app.route('/api/vk/notifications/toggle', methods=['POST'])
        def toggle_vk_notifications():
            """Переключение состояния ВК уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    enabled = self.scheduler.telegram_bot.toggle_notifications()
                    self.log(f"ВК уведомления {'включены' if enabled else 'отключены'}")
                    return jsonify({'success': True, 'enabled': enabled})
                else:
                    return jsonify({'success': False, 'message': 'VK bot not initialized'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/telegram/notifications/status', methods=['GET'])
        @self.app.route('/api/vk/notifications/status', methods=['GET'])
        def get_vk_notifications_status():
            """Получение статуса ВК уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    return jsonify({
                        'bot_enabled': self.scheduler.telegram_bot.enabled,
                        'notifications_enabled': self.scheduler.telegram_bot.notifications_enabled,
                        'chat_ids_count': len(self.scheduler.telegram_bot.chat_ids),
                        'status_text': self.scheduler.telegram_bot.get_notifications_status()
                    })
                else:
                    return jsonify({'error': 'VK bot not initialized'})
            except Exception as e:
                return jsonify({'error': str(e)})

        @self.app.route('/api/telegram/notifications/enable', methods=['POST'])
        @self.app.route('/api/vk/notifications/enable', methods=['POST'])
        def enable_vk_notifications():
            """Включение ВК уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    success = self.scheduler.telegram_bot.enable_notifications()
                    if success:
                        self.log("ВК уведомления включены")
                        return jsonify({'success': True, 'enabled': True})
                    else:
                        return jsonify({'success': False, 'message': 'Failed to enable notifications'})
                else:
                    return jsonify({'success': False, 'message': 'VK bot not initialized'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/telegram/notifications/disable', methods=['POST'])
        @self.app.route('/api/vk/notifications/disable', methods=['POST'])
        def disable_vk_notifications():
            """Отключение ВК уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    success = self.scheduler.telegram_bot.disable_notifications()
                    if success:
                        self.log("ВК уведомления отключены")
                        return jsonify({'success': True, 'enabled': False})
                    else:
                        return jsonify({'success': False, 'message': 'Failed to disable notifications'})
                else:
                    return jsonify({'success': False, 'message': 'VK bot not initialized'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/current_track', methods=['GET'])
        def get_current_track():
            """Получение информации о текущем воспроизводимом треке"""
            try:
                track_info = self.scheduler.get_current_track_info()
                return jsonify(track_info)
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/track/next', methods=['POST'])
        def next_track():
            """Переключение на следующий трек"""
            try:
                success = self.scheduler.next_track()
                if success:
                    return jsonify({'success': True, 'message': 'Следующий трек'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка переключения трека'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/track/previous', methods=['POST'])
        def previous_track():
            """Переключение на предыдущий трек"""
            try:
                success = self.scheduler.previous_track()
                if success:
                    return jsonify({'success': True, 'message': 'Предыдущий трек'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка переключения трека'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/track/play_pause', methods=['POST'])
        def play_pause_track():
            """Переключение воспроизведения/паузы"""
            try:
                success = self.scheduler.play_pause_track()
                if success:
                    return jsonify({'success': True, 'message': 'Переключено воспроизведение/пауза'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка управления воспроизведением'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/track/stop', methods=['POST'])
        def stop_track():
            """Остановка воспроизведения"""
            try:
                success = self.scheduler.stop_track()
                if success:
                    return jsonify({'success': True, 'message': 'Воспроизведение остановлено'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка остановки воспроизведения'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/volume', methods=['POST'])
        def set_volume():
            """Установка громкости"""
            try:
                data = request.get_json()
                volume = data.get('volume', 100)
                
                # Проверяем диапазон громкости
                if not isinstance(volume, (int, float)) or volume < 0 or volume > 320:
                    return jsonify({'success': False, 'message': 'Громкость должна быть от 0 до 320'})
                
                success = self.scheduler.set_volume(int(volume))
                if success:
                    return jsonify({'success': True, 'message': f'Громкость установлена: {volume}%'})
                else:
                    return jsonify({'success': False, 'message': 'Ошибка изменения громкости'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck/reference', methods=['POST'])
        def api_soundcheck_reference():
            """Запуск эталонного саундчека (создает образец и график)"""
            try:
                sc = SoundCheck(audio_monitor=self.audio_monitor)
                ok = sc.run_soundcheck()
                return jsonify({'success': bool(ok), 'message': 'Эталонный саундчек выполнен' if ok else 'Ошибка выполнения саундчека'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck', methods=['POST'])
        def api_soundcheck_run():
            """Запуск сравнения саундчека и отправка результата в ВК (если включены уведомления)"""
            try:
                result = self.run_soundcheck_and_notify()
                return jsonify(result)
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck/schedule/toggle', methods=['POST'])
        def toggle_soundcheck_schedule():
            """Переключение состояния автосаундчека"""
            try:
                self.soundcheck_schedule_enabled = not self.soundcheck_schedule_enabled
                self._save_soundcheck_schedule_enabled_to_config(self.soundcheck_schedule_enabled)
                status = 'включен' if self.soundcheck_schedule_enabled else 'отключен'
                self.log(f"🔁 Авто-саундчек {status}")
                return jsonify({'success': True, 'enabled': self.soundcheck_schedule_enabled})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/soundcheck/schedule/minutes', methods=['POST'])
        def update_soundcheck_minutes():
            """Обновление количества минут до запуска саундчека"""
            try:
                data = request.get_json()
                minutes = data.get('minutes', 30)
                
                # Проверяем диапазон минут
                if not isinstance(minutes, (int, float)) or minutes < 1 or minutes > 120:
                    return jsonify({'success': False, 'message': 'Минуты должны быть от 1 до 120'})
                
                self.soundcheck_minutes_before_disco = int(minutes)
                self._save_soundcheck_minutes_to_config(minutes)
                
                return jsonify({'success': True, 'minutes': minutes})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck/duration', methods=['POST'])
        def update_soundcheck_duration():
            """Обновление длительности саундчека в секундах"""
            try:
                data = request.get_json()
                duration = data.get('duration', 10)
                
                # Проверяем диапазон секунд
                if not isinstance(duration, (int, float)) or duration < 1 or duration > 60:
                    return jsonify({'success': False, 'message': 'Длительность должна быть от 1 до 60 секунд'})
                
                self._save_soundcheck_duration_to_config(duration)
                
                return jsonify({'success': True, 'duration': duration})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck/schedule/status', methods=['GET'])
        def get_soundcheck_schedule_status():
            """Статус автосаундчека и ближайшее время срабатывания"""
            try:
                next_info = self.scheduler.get_next_run()
                next_trigger = None
                if next_info and 'date' in next_info and 'time' in next_info:
                    try:
                        dt = datetime.strptime(f"{next_info['date']} {next_info['time']}", "%d.%m.%Y %H:%M")
                        trig = dt - timedelta(minutes=self.soundcheck_minutes_before_disco)
                        next_trigger = trig.strftime("%d.%m.%Y %H:%M")
                    except Exception:
                        next_trigger = None
                return jsonify({
                    'enabled': self.soundcheck_schedule_enabled,
                    'minutes_before_disco': self.soundcheck_minutes_before_disco,
                    'next_disco': next_info,
                    'next_trigger': next_trigger
                })
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/config/status', methods=['GET'])
        def get_config_status():
            """Получение информации о текущей конфигурации плейлиста"""
            try:
                config_status = self.scheduler.get_config_status()
                if config_status:
                    return jsonify(config_status)
                else:
                    return jsonify({'error': 'Не удалось получить статус конфигурации'})
            except Exception as e:
                return jsonify({'error': str(e)})

        @self.app.route('/api/config/switch', methods=['POST'])
        def switch_config():
            """Принудительное переключение конфигурации"""
            try:
                success = self.scheduler.switch_config_manually()
                if success:
                    config_status = self.scheduler.get_config_status()
                    return jsonify({
                        'success': True,
                        'message': f'Конфигурация переключена на: {config_status["current_config"]}',
                        'current_config': config_status["current_config"]
                    })
                else:
                    return jsonify({'success': False, 'message': 'Ошибка переключения конфигурации'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/config/set', methods=['POST'])
        def set_config():
            """Установка конкретной конфигурации"""
            try:
                data = request.get_json()
                config_name = data.get('config_name')

                if config_name not in ['zhenya', 'ruslan']:
                    return jsonify({'success': False, 'message': 'Неверное имя конфигурации. Используйте zhenya или ruslan'})

                success = self.scheduler.set_config(config_name)
                if success:
                    return jsonify({
                        'success': True,
                        'message': f'Конфигурация установлена: {config_name}',
                        'current_config': config_name
                    })
                else:
                    return jsonify({'success': False, 'message': 'Ошибка установки конфигурации'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/config/content', methods=['GET'])
        def get_config_content():
            """Получение содержимого конфигурационного файла"""
            try:
                config_name = request.args.get('name', 'zhenya')
                if config_name not in ['zhenya', 'ruslan']:
                    return jsonify({'success': False, 'message': 'Неверное имя конфигурации'})

                config_path = os.path.join(get_exe_dir(), f'config_{config_name}.txt')
                if not os.path.exists(config_path):
                    return jsonify({'success': False, 'message': f'Файл {config_name} не найден'})

                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                return jsonify({'success': True, 'content': content, 'name': config_name})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/config/save', methods=['POST'])
        def save_config_content():
            """Сохранение содержимого конфигурационного файла"""
            try:
                data = request.get_json()
                config_name = data.get('name')
                content = data.get('content')

                if config_name not in ['zhenya', 'ruslan']:
                    return jsonify({'success': False, 'message': 'Неверное имя конфигурации'})

                if content is None:
                    return jsonify({'success': False, 'message': 'Содержимое не указано'})

                config_path = os.path.join(get_exe_dir(), f'config_{config_name}.txt')

                # Создаем резервную копию
                if os.path.exists(config_path):
                    backup_path = config_path + '.bak'
                    with open(config_path, 'r', encoding='utf-8') as f:
                        backup_content = f.read()
                    with open(backup_path, 'w', encoding='utf-8') as f:
                        f.write(backup_content)

                # Сохраняем новое содержимое
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                self.log(f"💾 Конфигурация {config_name} сохранена")
                return jsonify({'success': True, 'message': f'Конфигурация {config_name} сохранена'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/mp3/folders', methods=['GET'])
        def get_mp3_folders():
            """Получение списка папок с mp3"""
            try:
                mp3_dir = os.path.join(get_exe_dir(), 'mp3')
                if not os.path.exists(mp3_dir):
                    return jsonify({'success': False, 'message': 'Папка mp3 не найдена'})

                folders = []
                for item in os.listdir(mp3_dir):
                    item_path = os.path.join(mp3_dir, item)
                    if os.path.isdir(item_path):
                        # Подсчитываем количество mp3 файлов
                        mp3_count = len([f for f in os.listdir(item_path) if f.lower().endswith('.mp3')])
                        folders.append({
                            'name': item,
                            'path': item_path,
                            'mp3_count': mp3_count
                        })

                folders.sort(key=lambda x: x['name'])
                return jsonify({'success': True, 'folders': folders})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/mp3/files', methods=['GET'])
        def get_mp3_files():
            """Получение списка mp3 файлов в папке"""
            try:
                folder_name = request.args.get('folder')
                if not folder_name:
                    return jsonify({'success': False, 'message': 'Папка не указана'})

                folder_path = os.path.join(get_exe_dir(), 'mp3', folder_name)
                if not os.path.exists(folder_path):
                    return jsonify({'success': False, 'message': 'Папка не найдена'})

                files = []
                for item in os.listdir(folder_path):
                    if item.lower().endswith('.mp3'):
                        item_path = os.path.join(folder_path, item)
                        file_size = os.path.getsize(item_path)
                        files.append({
                            'name': item,
                            'size': file_size,
                            'size_mb': round(file_size / (1024 * 1024), 2)
                        })

                files.sort(key=lambda x: x['name'])
                return jsonify({'success': True, 'files': files, 'folder': folder_name})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/mp3/delete', methods=['POST'])
        def delete_mp3_file():
            """Удаление mp3 файла"""
            try:
                data = request.get_json()
                folder_name = data.get('folder')
                file_name = data.get('file')

                if not folder_name or not file_name:
                    return jsonify({'success': False, 'message': 'Папка или файл не указаны'})

                file_path = os.path.join(get_exe_dir(), 'mp3', folder_name, file_name)
                if not os.path.exists(file_path):
                    return jsonify({'success': False, 'message': 'Файл не найден'})

                os.remove(file_path)
                self.log(f"🗑️ Удален файл: {folder_name}/{file_name}")
                return jsonify({'success': True, 'message': f'Файл {file_name} удален'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/mp3/upload', methods=['POST'])
        def upload_mp3_file():
            """Загрузка mp3 файла"""
            try:
                folder_name = request.form.get('folder')
                if not folder_name:
                    return jsonify({'success': False, 'message': 'Папка не указана'})

                if 'file' not in request.files:
                    return jsonify({'success': False, 'message': 'Файл не найден'})

                file = request.files['file']
                if file.filename == '':
                    return jsonify({'success': False, 'message': 'Файл не выбран'})

                if not file.filename.lower().endswith('.mp3'):
                    return jsonify({'success': False, 'message': 'Разрешены только MP3 файлы'})

                folder_path = os.path.join(get_exe_dir(), 'mp3', folder_name)
                if not os.path.exists(folder_path):
                    return jsonify({'success': False, 'message': 'Папка не найдена'})

                file_path = os.path.join(folder_path, file.filename)
                file.save(file_path)

                file_size = os.path.getsize(file_path)
                self.log(f"📤 Загружен файл: {folder_name}/{file.filename} ({round(file_size / (1024 * 1024), 2)} MB)")
                return jsonify({'success': True, 'message': f'Файл {file.filename} загружен'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/', methods=['GET'])
        def serve_web_interface():
            """Обслуживание веб-интерфейса"""
            try:
                web_interface_path = os.path.join(get_exe_dir(), 'web_interface.html')
                self.log(f"🔍 Поиск веб-интерфейса: {web_interface_path}")
                self.log(f"📁 Файл существует: {os.path.exists(web_interface_path)}")

                if os.path.exists(web_interface_path):
                    self.log("✅ Загружаем веб-интерфейс Hello Kitty")
                    with open(web_interface_path, 'r', encoding='utf-8') as f:
                        return Response(f.read(), mimetype='text/html')
                else:
                    self.log("⚠️ Веб-интерфейс не найден, показываем fallback")
                    fallback_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Планировщик Дискотеки ВДНХ</title>
                        <meta charset="UTF-8">
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 40px; background: #ffb6c1; }}
                            h1 {{ color: #ff1493; }}
                            .info {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                        </style>
                    </head>
                    <body>
                        <h1>🎵 Планировщик Дискотеки ВДНХ</h1>
                        <div class="info">
                            <p><strong>Веб-интерфейс не найден!</strong></p>
                            <p>Путь к файлу: <code>{web_interface_path}</code></p>
                            <p>Убедитесь, что файл web_interface.html находится в директории сервера.</p>
                            <p>API доступно по адресу: <a href="/api/status">/api/status</a></p>
                        </div>
                    </body>
                    </html>
                    """
                    return Response(fallback_html, mimetype='text/html', status=404)
            except Exception as e:
                self.log(f"❌ Ошибка загрузки веб-интерфейса: {str(e)}")
                return Response(f"Ошибка загрузки веб-интерфейса: {str(e)}", mimetype='text/plain', status=500)

        @self.app.route('/admin', methods=['GET'])
        def serve_admin_interface():
            """Обслуживание интерфейса администрирования"""
            try:
                admin_interface_path = os.path.join(get_exe_dir(), 'admin.html')

                if os.path.exists(admin_interface_path):
                    self.log("✅ Загружаем интерфейс администрирования")
                    with open(admin_interface_path, 'r', encoding='utf-8') as f:
                        return Response(f.read(), mimetype='text/html')
                else:
                    return Response("Интерфейс администрирования не найден", mimetype='text/plain', status=404)
            except Exception as e:
                self.log(f"❌ Ошибка загрузки интерфейса администрирования: {str(e)}")
                return Response(f"Ошибка загрузки: {str(e)}", mimetype='text/plain', status=500)

        @self.app.route('/api/git_pull_reboot', methods=['POST'])
        def git_pull_and_reboot():
            """Git pull и перезагрузка Orange Pi"""
            try:
                self.log("🔄 Получен запрос на обновление кода и перезагрузку")

                # Останавливаем VLC
                try:
                    self.scheduler.close_vlc(send_notification=False)
                    self.log("⏹️ VLC остановлен")
                except Exception as e:
                    self.log(f"⚠️ Ошибка остановки VLC: {e}")

                # Запускаем git pull и reboot в фоновом режиме
                def run_git_pull_and_reboot():
                    try:
                        import time
                        time.sleep(2)  # Даем время на отправку ответа

                        # Git pull
                        self.log("🔄 Выполняем git pull...")
                        git_result = subprocess.run(
                            ['git', 'pull'],
                            cwd=get_exe_dir(),
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        self.log(f"Git pull stdout: {git_result.stdout}")
                        if git_result.stderr:
                            self.log(f"Git pull stderr: {git_result.stderr}")

                        # Перезагрузка
                        self.log("🔄 Перезагрузка Orange Pi...")
                        subprocess.run(['sudo', 'reboot'], check=False)
                    except Exception as e:
                        self.log(f"❌ Ошибка при выполнении git pull/reboot: {e}")

                # Запускаем в отдельном потоке
                thread = Thread(target=run_git_pull_and_reboot, daemon=True)
                thread.start()

                return jsonify({'success': True, 'message': 'Git pull и перезагрузка запущены'})
            except Exception as e:
                self.log(f"❌ Ошибка git pull/reboot: {str(e)}")
                return jsonify({'success': False, 'message': str(e)})
    
    def run_scheduler_loop(self):
        """Основной цикл проверки расписания"""
        self.log("✅ Цикл планировщика запущен")
        
        while self.running:
            try:
                # Проверяем расписание
                self.scheduler.check_schedule()
                
                # Автоматический саундчек за настроенное количество минут до старта дискотеки
                if self.soundcheck_schedule_enabled:
                    next_info = self.scheduler.get_next_run()
                    if next_info and 'date' in next_info and 'time' in next_info:
                        try:
                            next_key = f"{next_info['date']} {next_info['time']}"
                            dt = datetime.strptime(next_key, "%d.%m.%Y %H:%M")
                            trigger_dt = dt - timedelta(minutes=self.soundcheck_minutes_before_disco)
                            now = datetime.now()
                            # Строго один запуск на одно ближайшее срабатывание
                            if now >= trigger_dt and (self.soundcheck_last_trigger_key != next_key):
                                self.log(f"🧪 Авто-саундчек: запускаем проверку за {self.soundcheck_minutes_before_disco} минут до дискотеки")
                                try:
                                    self.run_soundcheck_and_notify()
                                except Exception as se:
                                    self.log(f"❌ Ошибка автосаундчека: {se}")
                                # Запомнить, что на этот ближайший запуск проверка уже выполнена
                                self.soundcheck_last_trigger_key = next_key
                            # Если ближайшее событие прошло (дальше чем на 1 минуту), сбрасываем ключ при смене ближайшего запуска
                            if now > dt + timedelta(minutes=1):
                                # Это позволит при обновлении next_run снова отработать за настроенное время
                                self.soundcheck_last_trigger_key = None
                        except Exception as pe:
                            # Не критично для основного цикла
                            self.log(f"⚠️ Ошибка расчета времени автосаундчека: {pe}")
                
                # Спим секунду
                time.sleep(1)
                
            except Exception as e:
                self.log(f"❌ Ошибка в цикле планировщика: {e}")
                time.sleep(1)
    
    def run_flask_server(self):
        """Запуск Flask сервера"""
        try:
            server_ip = get_local_ip()
            self.log(f'🌐 Веб-сервер запущен: http://{server_ip}:5002')
            self.log(f'🎀 Веб-интерфейс Hello Kitty: http://{server_ip}:5002/')
            self.log(f'📡 API документация: http://{server_ip}:5002/api/status')
            self.app.run(host='0.0.0.0', port=5002, debug=False, use_reloader=False)
        except Exception as e:
            self.log(f'❌ Ошибка веб-сервера: {str(e)}')
    
    def start(self):
        """Запуск сервера"""
        self.log("=" * 60)
        self.log("🎵 СЕРВЕР ПЛАНИРОВЩИКА ДИСКОТЕКИ ВДНХ")
        self.log("=" * 60)
        self.log(f"📁 Конфиг: {self.config_file}")
        self.log(f"📅 Дни запуска: {self.scheduler.scheduled_days}")
        self.log(f"⏰ Время запуска: {self.scheduler.start_time.strftime('%H:%M')}")
        self.log(f"⏰ Время остановки: {self.scheduler.stop_time.strftime('%H:%M')}")
        self.log(f"⚙️ Планировщик: {'включен' if self.scheduler.scheduler_enabled else 'отключен'}")
        if self.audio_monitor:
            self.log(f"🎤 Мониторинг звука: {'включен' if self.audio_monitor.monitoring_enabled else 'отключен'}")
        self.log("=" * 60)
        self.log("🎀 ВЕБ-ИНТЕРФЕЙС В СТИЛЕ HELLO KITTY ДОСТУПЕН! 🎀")
        self.log("=" * 60)

        # Отправляем уведомление о перезагрузке сервера в ВК
        if self.scheduler.telegram_bot and self.scheduler.telegram_bot.enabled and self.scheduler.telegram_bot.notifications_enabled:
            try:
                self.scheduler.telegram_bot.notify_server_started()
                self.log("📱 Уведомление о перезагрузке сервера отправлено в ВК")
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки ВК уведомления о перезагрузке: {e}')

        # Запускаем цикл планировщика в отдельном потоке
        scheduler_thread = Thread(target=self.run_scheduler_loop, daemon=True)
        scheduler_thread.start()
        
        # Запускаем Flask сервер (блокирующий вызов)
        self.run_flask_server()
    
    def signal_handler(self, signum, frame):
        """Обработчик сигналов завершения"""
        self.log("\n🛑 Получен сигнал завершения, останавливаем сервер...")
        self.running = False
        
        # Корректно завершаем мониторинг звука
        if self.audio_monitor:
            self.audio_monitor.cleanup()
        
        # Принудительно завершаем процесс (Flask может держать поток)
        self.log("✅ Все компоненты остановлены, завершаем процесс...")
        os._exit(0)


def main():
    """Главная функция"""
    server = DiscoServer()
    server.start()


if __name__ == '__main__':
    main()

