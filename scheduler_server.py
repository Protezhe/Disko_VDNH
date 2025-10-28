#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автономный сервер планировщика дискотеки без GUI.
Запускает планировщик, мониторинг звука и веб-API на основе конфига.
Для production использования.
"""

import sys
import os
import json
import time
import signal
import socket
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from threading import Thread

from scheduler import DiscoScheduler
from soundcheck import SoundCheck
from soundcheck_v2 import SoundCheckV2
from audio_monitor import AudioMonitor, get_audio_devices_list


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
    
    def on_silence_detected(self, level):
        """Обработчик обнаружения тишины"""
        self.log(f"🔇 Обнаружена тишина (уровень: {level:.6f})")
    
    def on_sound_restored(self, silence_time):
        """Обработчик восстановления звука"""
        self.log(f"🔊 Звук восстановлен после {silence_time:.1f}с тишины")
        
        # Отправляем уведомление только если дискотека активна
        if self.scheduler.disco_is_active:
            try:
                self.scheduler.telegram_bot.notify_music_restored(silence_time)
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки Telegram уведомления: {e}')
    
    def on_silence_warning(self, silence_time):
        """Обработчик предупреждения о длительной тишине"""
        self.log(f"⚠️ ТИШИНА! {silence_time:.0f}с")
        
        # Отправляем уведомление только если дискотека активна
        if self.scheduler.disco_is_active:
            try:
                self.scheduler.telegram_bot.notify_music_stopped(silence_time)
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки Telegram уведомления: {e}')
    
    def on_level_updated(self, level):
        """Обработчик обновления уровня звука (без вывода в лог, чтобы не засорять)"""
        pass
    
    def _save_monitoring_enabled_to_config(self, enabled):
        """Сохраняет состояние мониторинга в конфиг"""
        try:
            # Загружаем существующие настройки
            existing_settings = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            
            # Обновляем только состояние мониторинга
            existing_settings['monitoring_enabled'] = enabled
            
            # Сохраняем в файл
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, ensure_ascii=False, indent=2)
            
            self.log(f"💾 Состояние мониторинга сохранено в конфиг: {'включен' if enabled else 'отключен'}")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения состояния мониторинга: {e}")
    
    def _save_audio_settings_to_config(self):
        """Сохраняет настройки аудио мониторинга в конфиг"""
        try:
            # Загружаем существующие настройки
            existing_settings = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            
            # Обновляем аудио настройки
            if self.audio_monitor:
                existing_settings['audio_threshold'] = self.audio_monitor.threshold
                existing_settings['audio_silence_duration'] = self.audio_monitor.silence_duration
                existing_settings['audio_sound_confirmation_duration'] = self.audio_monitor.sound_confirmation_duration
                existing_settings['audio_buffer_size'] = self.audio_monitor.buffer_size
                if self.audio_monitor.device_index is not None:
                    existing_settings['audio_device_index'] = self.audio_monitor.device_index
            
            # Сохраняем в файл
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, ensure_ascii=False, indent=2)
            
            self.log("💾 Настройки аудио мониторинга сохранены в конфиг")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения настроек аудио мониторинга: {e}")
    
    def _save_soundcheck_schedule_enabled_to_config(self, enabled):
        """Сохраняет состояние автосаундчека в конфиг"""
        try:
            existing_settings = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            existing_settings['soundcheck_schedule_enabled'] = bool(enabled)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, ensure_ascii=False, indent=2)
            self.log(f"💾 Авто-саундчек по расписанию: {'включен' if enabled else 'отключен'}")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения состояния авто-саундчека: {e}")
    
    def _save_soundcheck_minutes_to_config(self, minutes):
        """Сохраняет количество минут до запуска саундчека в конфиг"""
        try:
            existing_settings = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            existing_settings['soundcheck_minutes_before_disco'] = int(minutes)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(existing_settings, f, ensure_ascii=False, indent=2)
            self.log(f"💾 Авто-саундчек: за {minutes} минут до дискотеки")
        except Exception as e:
            self.log(f"❌ Ошибка сохранения времени авто-саундчека: {e}")

    def run_soundcheck_and_notify(self):
        """Запуск саундчека V2, расчет схожести и отправка в Telegram при необходимости"""
        sc2 = SoundCheckV2()
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
                self.log(f"⚠️ Ошибка отправки Telegram сообщения: {te}")
        return {
            'success': True,
            'similarity': similarity,
            'verdict': verdict,
            'telegram_sent': sent,
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
                'scheduler_enabled': self.scheduler.scheduler_enabled
            }
            
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
                        self.audio_monitor.threshold = data['audio_threshold']
                        audio_settings_updated = True
                    if 'audio_silence_duration' in data:
                        self.audio_monitor.silence_duration = data['audio_silence_duration']
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
        def toggle_telegram_notifications():
            """Переключение состояния Telegram уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    enabled = self.scheduler.telegram_bot.toggle_notifications()
                    self.log(f"Telegram уведомления {'включены' if enabled else 'отключены'}")
                    return jsonify({'success': True, 'enabled': enabled})
                else:
                    return jsonify({'success': False, 'message': 'Telegram bot not initialized'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/telegram/notifications/status', methods=['GET'])
        def get_telegram_notifications_status():
            """Получение статуса Telegram уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    return jsonify({
                        'bot_enabled': self.scheduler.telegram_bot.enabled,
                        'notifications_enabled': self.scheduler.telegram_bot.notifications_enabled,
                        'chat_ids_count': len(self.scheduler.telegram_bot.chat_ids),
                        'status_text': self.scheduler.telegram_bot.get_notifications_status()
                    })
                else:
                    return jsonify({'error': 'Telegram bot not initialized'})
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/api/telegram/notifications/enable', methods=['POST'])
        def enable_telegram_notifications():
            """Включение Telegram уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    success = self.scheduler.telegram_bot.enable_notifications()
                    if success:
                        self.log("Telegram уведомления включены")
                        return jsonify({'success': True, 'enabled': True})
                    else:
                        return jsonify({'success': False, 'message': 'Failed to enable notifications'})
                else:
                    return jsonify({'success': False, 'message': 'Telegram bot not initialized'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})
        
        @self.app.route('/api/telegram/notifications/disable', methods=['POST'])
        def disable_telegram_notifications():
            """Отключение Telegram уведомлений"""
            try:
                if self.scheduler.telegram_bot:
                    success = self.scheduler.telegram_bot.disable_notifications()
                    if success:
                        self.log("Telegram уведомления отключены")
                        return jsonify({'success': True, 'enabled': False})
                    else:
                        return jsonify({'success': False, 'message': 'Failed to disable notifications'})
                else:
                    return jsonify({'success': False, 'message': 'Telegram bot not initialized'})
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
                sc = SoundCheck()
                ok = sc.run_soundcheck()
                return jsonify({'success': bool(ok), 'message': 'Эталонный саундчек выполнен' if ok else 'Ошибка выполнения саундчека'})
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)})

        @self.app.route('/api/soundcheck', methods=['POST'])
        def api_soundcheck_run():
            """Запуск сравнения саундчека и отправка результата в Telegram (если включены уведомления)"""
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
        
        # Отправляем уведомление о запуске сервера в Telegram
        if self.scheduler.telegram_bot and self.scheduler.telegram_bot.enabled and self.scheduler.telegram_bot.notifications_enabled:
            try:
                self.scheduler.telegram_bot.notify_server_started()
                self.log("📱 Уведомление о запуске сервера отправлено в Telegram")
            except Exception as e:
                self.log(f'⚠️ Ошибка отправки Telegram уведомления о запуске: {e}')
        
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

