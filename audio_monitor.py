#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для мониторинга уровня звука с микрофона.
Поддерживает загрузку настроек из конфига и возвращает статус (лампа).
Выводит предупреждение, если уровень звука ниже порогового значения более заданного времени.
"""

import pyaudio
import numpy as np
import time
import threading
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


def get_audio_devices_list():
    """Получение списка доступных аудиоустройств"""
    audio = pyaudio.PyAudio()
    devices = []
    
    for i in range(audio.get_device_count()):
        device_info = audio.get_device_info_by_index(i)
        if device_info['maxInputChannels'] > 0:  # Только устройства ввода
            devices.append({
                'index': i,
                'name': device_info['name'],
                'channels': device_info['maxInputChannels']
            })
    
    audio.terminate()
    return devices


class AudioMonitor:
    def __init__(self, config_file=None, threshold=None, silence_duration=None, 
                 sample_rate=44100, chunk_size=1024, device_index=None, buffer_size=None,
                 sound_confirmation_duration=None):
        """
        Инициализация монитора звука
        
        Args:
            config_file (str): Путь к файлу конфигурации (если None, используется scheduler_config.json)
            threshold (float): Пороговое значение уровня звука (по умолчанию загружается из конфига или 0.01)
            silence_duration (int): Длительность тишины в секундах для предупреждения (по умолчанию из конфига или 20)
            sample_rate (int): Частота дискретизации (по умолчанию 44100)
            chunk_size (int): Размер блока данных (по умолчанию 1024)
            device_index (int): Индекс аудиоустройства (по умолчанию из конфига или None)
            buffer_size (int): Размер буфера RMS (по умолчанию из конфига или 10)
            sound_confirmation_duration (int): Длительность звука для подтверждения в секундах (по умолчанию из конфига или 5)
        """
        # Загружаем настройки из конфига
        self.config_file = config_file if config_file else os.path.join(get_exe_dir(), 'scheduler_config.json')
        config = self._load_config()
        
        # Устанавливаем параметры (приоритет у переданных параметров, затем из конфига, затем дефолтные)
        self.threshold = threshold if threshold is not None else config.get('audio_threshold', 0.01)
        self.silence_duration = silence_duration if silence_duration is not None else config.get('audio_silence_duration', 20)
        self.device_index = device_index if device_index is not None else config.get('audio_device_index', None)
        self.buffer_size = buffer_size if buffer_size is not None else config.get('audio_buffer_size', 10)
        self.sound_confirmation_duration = sound_confirmation_duration if sound_confirmation_duration is not None else config.get('audio_sound_confirmation_duration', 5)
        
        # Логируем загруженные параметры
        print(f"[AudioMonitor] Инициализация с параметрами:")
        print(f"[AudioMonitor]   - Порог звука: {self.threshold}")
        print(f"[AudioMonitor]   - Длительность тишины: {self.silence_duration}с")
        print(f"[AudioMonitor]   - Подтверждение звука: {self.sound_confirmation_duration}с")
        print(f"[AudioMonitor]   - Размер буфера: {self.buffer_size}")
        print(f"[AudioMonitor]   - Устройство: {self.device_index if self.device_index is not None else 'по умолчанию'}")
        
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # Инициализация PyAudio
        self.audio = pyaudio.PyAudio()
        self.stream = None
        
        # Lock для безопасной остановки в многопоточной среде
        self._stop_lock = threading.Lock()
        
        # Переменные для отслеживания тишины
        self.silence_start_time = None
        self.is_monitoring = False
        self.monitor_thread = None
        self.silence_warning_sent = False  # Флаг отправки предупреждения о тишине
        
        # Переменные для отслеживания длительности звука
        self.sound_start_time = None
        self.sound_confirmed = False  # Флаг подтверждения звука после заданного времени
        
        # Статус лампы (True = красная/тишина, False = зеленая/звук есть)
        self.lamp_status = True  # По умолчанию красная (звук не подтвержден)
        
        # Флаг включения/отключения мониторинга (загружается из конфига)
        if 'monitoring_enabled' in config:
            self.monitoring_enabled = config['monitoring_enabled']
            print(f"[AudioMonitor] Состояние мониторинга загружено из конфига: {'включен' if self.monitoring_enabled else 'отключен'}")
        else:
            self.monitoring_enabled = False  # По умолчанию отключен
            print("[AudioMonitor] Состояние мониторинга не найдено в конфиге, используется значение по умолчанию: отключен")
        
        # Буфер для накопления данных для RMS
        self.rms_buffer = []
        
        # Текущий уровень звука
        self.current_level = 0.0
        
        # Текущая конфигурация аудиопотока
        self.current_config = None
        
        # Колбэки для событий
        self.on_silence_detected_callback = None
        self.on_sound_restored_callback = None
        self.on_silence_warning_callback = None
        self.on_level_updated_callback = None
    
    def _load_config(self):
        """Загрузка настроек из конфига"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[AudioMonitor] Ошибка загрузки конфига: {e}")
        return {}
        
    def start_monitoring(self):
        """Запуск мониторинга звука"""
        if not self.monitoring_enabled:
            print("[AudioMonitor] Мониторинг отключен в конфиге")
            return False
            
        # Пробуем разные конфигурации для совместимости с OrangePi/веб-камерами
        configs_to_try = [
            # Стандартная конфигурация (Windows)
            {
                'format': pyaudio.paFloat32,
                'channels': 1,
                'rate': self.sample_rate,
                'frames_per_buffer': self.chunk_size,
                'data_processor': self._process_float32_data
            },
            # Конфигурация для веб-камер (часто используют 16kHz)
            {
                'format': pyaudio.paInt16,
                'channels': 1,
                'rate': 16000,
                'frames_per_buffer': 512,
                'data_processor': self._process_int16_data
            },
            # Конфигурация для USB устройств
            {
                'format': pyaudio.paInt16,
                'channels': 1,
                'rate': 44100,
                'frames_per_buffer': 1024,
                'data_processor': self._process_int16_data
            },
            # Конфигурация для старых устройств
            {
                'format': pyaudio.paInt16,
                'channels': 1,
                'rate': 8000,
                'frames_per_buffer': 256,
                'data_processor': self._process_int16_data
            }
        ]
        
        # Если указано конкретное устройство, пробуем его сначала
        if self.device_index is not None:
            print(f"[AudioMonitor] Используется устройство с индексом: {self.device_index}")
            # Проверяем доступность устройства
            try:
                device_info = self.audio.get_device_info_by_index(self.device_index)
                print(f"[AudioMonitor] Устройство: {device_info['name']}")
                print(f"[AudioMonitor] Максимум входных каналов: {device_info['maxInputChannels']}")
                if device_info['maxInputChannels'] == 0:
                    print(f"[AudioMonitor] ⚠ Устройство не поддерживает ввод!")
            except Exception as e:
                print(f"[AudioMonitor] ⚠ Ошибка получения информации об устройстве: {e}")
        else:
            print(f"[AudioMonitor] Устройство не указано, будет использовано по умолчанию")
        
        # Выводим список доступных устройств для диагностики
        print("[AudioMonitor] Доступные аудиоустройства:")
        try:
            for i in range(self.audio.get_device_count()):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    print(f"  {i}: {device_info['name']} (входов: {device_info['maxInputChannels']})")
        except Exception as e:
            print(f"[AudioMonitor] ⚠ Ошибка получения списка устройств: {e}")
        
        # Дополнительная диагностика для Linux
        import platform
        if platform.system() == "Linux":
            print("[AudioMonitor] Дополнительная диагностика для Linux:")
            try:
                import subprocess
                # Проверяем процессы, использующие аудио
                result = subprocess.run(['lsof', '/dev/snd/*'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    print("[AudioMonitor] Процессы, использующие аудио:")
                    for line in result.stdout.strip().split('\n')[:5]:  # Показываем только первые 5
                        print(f"  {line}")
                else:
                    print("[AudioMonitor] Нет активных процессов, использующих аудио")
            except Exception as diag_error:
                print(f"[AudioMonitor] Ошибка диагностики: {diag_error}")
        
        for i, config in enumerate(configs_to_try):
            try:
                print(f"[AudioMonitor] Попытка {i+1}/4: {config['format']}, {config['rate']}Hz, буфер={config['frames_per_buffer']}")
                
                # Проверяем поддержку формата (пропускаем если устройство недоступно)
                try:
                    is_supported = self.audio.is_format_supported(
                        rate=config['rate'],
                        input_device=self.device_index,
                        input_channels=config['channels'],
                        input_format=config['format']
                    )
                    
                    if not is_supported:
                        print(f"[AudioMonitor] Формат не поддерживается устройством")
                        continue
                except Exception as format_error:
                    print(f"[AudioMonitor] Ошибка проверки формата: {format_error}")
                    # Продолжаем попытку открытия потока
                
                # Открытие аудиопотока с дополнительными параметрами для ALSA
                try:
                    self.stream = self.audio.open(
                        format=config['format'],
                        channels=config['channels'],
                        rate=config['rate'],
                        input=True,
                        input_device_index=self.device_index,
                        frames_per_buffer=config['frames_per_buffer'],
                        # Дополнительные параметры для стабильности ALSA
                        start=False,  # Не начинаем сразу
                        stream_callback=None
                    )
                except Exception as alsa_error:
                    # Если ALSA ошибка, пробуем разные варианты
                    if "Device unavailable" in str(alsa_error) or "ALSA" in str(alsa_error) or "-9985" in str(alsa_error):
                        print(f"[AudioMonitor] ALSA ошибка с устройством {self.device_index}, пробуем альтернативы...")
                        
                        # Попытка 1: Без указания устройства
                        try:
                            print(f"[AudioMonitor] Попытка без указания устройства...")
                            self.stream = self.audio.open(
                                format=config['format'],
                                channels=config['channels'],
                                rate=config['rate'],
                                input=True,
                                input_device_index=None,  # Используем устройство по умолчанию
                                frames_per_buffer=config['frames_per_buffer'],
                                start=False,
                                stream_callback=None
                            )
                        except Exception as fallback_error:
                            # Попытка 2: С устройством по умолчанию (индекс 0)
                            try:
                                print(f"[AudioMonitor] Попытка с устройством по умолчанию (индекс 0)...")
                                self.stream = self.audio.open(
                                    format=config['format'],
                                    channels=config['channels'],
                                    rate=config['rate'],
                                    input=True,
                                    input_device_index=0,  # Первое доступное устройство
                                    frames_per_buffer=config['frames_per_buffer'],
                                    start=False,
                                    stream_callback=None
                                )
                            except Exception as fallback2_error:
                                # Попытка 3: С pulse устройством
                                try:
                                    print(f"[AudioMonitor] Попытка с pulse устройством...")
                                    self.stream = self.audio.open(
                                        format=config['format'],
                                        channels=config['channels'],
                                        rate=config['rate'],
                                        input=True,
                                        input_device_index=6,  # pulse устройство (из списка)
                                        frames_per_buffer=config['frames_per_buffer'],
                                        start=False,
                                        stream_callback=None
                                    )
                                except Exception as fallback3_error:
                                    print(f"[AudioMonitor] Все попытки fallback не удались: {fallback3_error}")
                                    raise alsa_error
                    else:
                        raise alsa_error
                
                # Запускаем поток вручную для лучшего контроля
                self.stream.start_stream()
                
                # Тестовое чтение для проверки работоспособности
                test_data = self.stream.read(config['frames_per_buffer'], exception_on_overflow=False)
                
                # Останавливаем поток после теста
                self.stream.stop_stream()
                
                # Сохраняем рабочую конфигурацию
                self.current_config = config
                self.sample_rate = config['rate']  # Обновляем частоту дискретизации
                self.chunk_size = config['frames_per_buffer']  # Обновляем размер буфера
                
                print(f"[AudioMonitor] ✓ Конфигурация работает: {config['format']}, {config['rate']}Hz")
                break
                
            except Exception as e:
                print(f"[AudioMonitor] Конфигурация {i+1} не работает: {e}")
                if self.stream:
                    try:
                        self.stream.close()
                    except:
                        pass
                    self.stream = None
                continue
        else:
            print("[AudioMonitor] ❌ Не удалось найти рабочую конфигурацию для устройства")
            return False
            
        # Запускаем поток для мониторинга
        self.stream.start_stream()
        
        self.is_monitoring = True
        # Инициализируем лампу в красном состоянии (звук не подтвержден)
        self.lamp_status = True
        self.silence_start_time = None
        self.sound_start_time = None
        self.sound_confirmed = False
        self.silence_warning_sent = False
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        print(f"[AudioMonitor] Мониторинг звука запущен")
        print(f"[AudioMonitor] Пороговое значение: {self.threshold}")
        print(f"[AudioMonitor] Предупреждение при тишине более {self.silence_duration} секунд")
        print(f"[AudioMonitor] Подтверждение звука после {self.sound_confirmation_duration} секунд")
        print("[AudioMonitor] Нажмите Ctrl+C для остановки...")
        return True
    
    def _process_float32_data(self, data):
        """Обработка данных в формате Float32"""
        return np.frombuffer(data, dtype=np.float32)
    
    def _process_int16_data(self, data):
        """Обработка данных в формате Int16"""
        int16_data = np.frombuffer(data, dtype=np.int16)
        return int16_data.astype(np.float32) / 32768.0
    
    def _process_int32_data(self, data):
        """Обработка данных в формате Int32"""
        int32_data = np.frombuffer(data, dtype=np.int32)
        return int32_data.astype(np.float32) / 2147483648.0
            
    def stop_monitoring(self):
        """Остановка мониторинга звука с защитой от Segmentation Fault"""
        with self._stop_lock:
            # Если уже остановлен, просто выходим
            if not self.is_monitoring:
                print("[AudioMonitor] Мониторинг уже остановлен")
                return
            
            print("[AudioMonitor] Начинаем остановку мониторинга...")
            
            # Сначала устанавливаем флаг остановки
            self.is_monitoring = False
            
            # Ждем завершения потока мониторинга ДО закрытия stream
            if self.monitor_thread and self.monitor_thread.is_alive():
                print("[AudioMonitor] Ожидание завершения потока мониторинга...")
                self.monitor_thread.join(timeout=2.0)
                if self.monitor_thread.is_alive():
                    print("[AudioMonitor] ⚠ Поток мониторинга не завершился за 2 секунды")
            
            # Теперь безопасно закрываем stream
            if self.stream:
                try:
                    # Проверяем, что поток еще активен перед остановкой
                    if hasattr(self.stream, 'is_active') and self.stream.is_active():
                        print("[AudioMonitor] Останавливаем аудио поток...")
                        self.stream.stop_stream()
                        time.sleep(0.1)  # Небольшая задержка для корректной остановки
                    
                    print("[AudioMonitor] Закрываем аудио поток...")
                    self.stream.close()
                    time.sleep(0.1)  # Задержка после закрытия
                    
                except Exception as e:
                    print(f"[AudioMonitor] ⚠ Ошибка при закрытии потока: {e}")
                finally:
                    self.stream = None
            
            print("[AudioMonitor] ✓ Мониторинг остановлен")
        
    def _monitor_loop(self):
        """Основной цикл мониторинга"""
        error_count = 0  # Счетчик ошибок подряд
        max_errors = 5   # Максимум ошибок подряд перед остановкой
        
        while self.is_monitoring:
            try:
                # Проверяем, что поток активен
                if self.stream and hasattr(self.stream, 'is_active'):
                    if not self.stream.is_active():
                        print("[AudioMonitor] Поток неактивен, перезапускаем...")
                        try:
                            self.stream.start_stream()
                            time.sleep(0.1)
                        except Exception as start_error:
                            print(f"[AudioMonitor] Ошибка запуска неактивного потока: {start_error}")
                            break
                        continue
                else:
                    print("[AudioMonitor] Поток недоступен")
                    break
                
                # Чтение аудиоданных с дополнительной обработкой ошибок ALSA
                try:
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    error_count = 0  # Сброс счетчика при успешном чтении
                except Exception as read_error:
                    error_count += 1
                    print(f"[AudioMonitor] Ошибка чтения аудио (#{error_count}): {read_error}")
                    
                    if error_count >= max_errors:
                        print(f"[AudioMonitor] Слишком много ошибок подряд ({max_errors}), остановка мониторинга")
                        break
                    
                    # Попробуем переинициализировать поток
                    try:
                        if self.stream and hasattr(self.stream, 'stop_stream'):
                            if self.stream.is_active():
                                self.stream.stop_stream()
                            time.sleep(0.1)
                            self.stream.start_stream()
                            time.sleep(0.1)
                        else:
                            print("[AudioMonitor] Поток недоступен для перезапуска")
                    except Exception as restart_error:
                        print(f"[AudioMonitor] Ошибка перезапуска потока: {restart_error}")
                    
                    time.sleep(0.5)  # Пауза перед следующей попыткой
                    continue
                
                # Преобразование в numpy массив с помощью соответствующего процессора
                if self.current_config and 'data_processor' in self.current_config:
                    audio_data = self.current_config['data_processor'](data)
                else:
                    # Fallback на Float32
                    audio_data = np.frombuffer(data, dtype=np.float32)
                
                # Безопасное вычисление RMS
                if len(audio_data) > 0:
                    current_rms = np.sqrt(np.mean(np.square(audio_data)))
                    if np.isnan(current_rms) or np.isinf(current_rms):
                        current_rms = 0.0
                else:
                    current_rms = 0.0
                
                # Добавляем текущий RMS в буфер
                self.rms_buffer.append(current_rms)
                
                # Ограничиваем размер буфера
                if len(self.rms_buffer) > self.buffer_size:
                    self.rms_buffer.pop(0)
                
                # Вычисляем усредненный RMS
                if len(self.rms_buffer) > 0:
                    avg_rms = np.mean(self.rms_buffer)
                else:
                    avg_rms = current_rms
                
                # Обновляем текущий уровень
                self.current_level = avg_rms
                
                # Вызываем колбэк обновления уровня
                if self.on_level_updated_callback:
                    self.on_level_updated_callback(avg_rms)
                
                # Проверка уровня звука
                if avg_rms < self.threshold:
                    # Звук ниже порога - сбрасываем отслеживание звука
                    if self.sound_start_time is not None:
                        self.sound_start_time = None
                        self.sound_confirmed = False
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Звук прерван, сброс отслеживания")
                    
                    if self.silence_start_time is None:
                        self.silence_start_time = time.time()
                        self.silence_warning_sent = False  # Сброс флага при начале тишины
                        # Лампа становится красной при обнаружении тишины (если звук был подтвержден)
                        if self.sound_confirmed:
                            self.lamp_status = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Тишина обнаружена (уровень: {avg_rms:.6f})")
                        
                        # Вызываем колбэк
                        if self.on_silence_detected_callback:
                            self.on_silence_detected_callback(avg_rms)
                    else:
                        # Проверяем длительность тишины
                        silence_time = time.time() - self.silence_start_time
                        if silence_time >= self.silence_duration:
                            self.lamp_status = True  # Красная лампа
                            
                            # Вызываем колбэк ТОЛЬКО ОДИН РАЗ при первом достижении порога
                            if self.on_silence_warning_callback and not self.silence_warning_sent:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ ТИШИНА {silence_time:.1f}с! (уровень: {avg_rms:.6f}, порог: {self.threshold})")
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] [AudioMonitor] Вызов колбэка on_silence_warning")
                                self.on_silence_warning_callback(silence_time)
                                self.silence_warning_sent = True  # Отмечаем что предупреждение отправлено
                else:
                    # Звук выше порога
                    # Отслеживание длительности звука
                    if self.sound_start_time is None:
                        self.sound_start_time = time.time()
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Начало отслеживания звука (уровень: {avg_rms:.6f})")
                    else:
                        # Проверяем длительность звука
                        sound_time = time.time() - self.sound_start_time
                        if sound_time >= self.sound_confirmation_duration and not self.sound_confirmed:
                            self.sound_confirmed = True
                            self.lamp_status = False  # Зеленая лампа - звук подтвержден
                            print(f"✅ ЗВУК ПОДТВЕРЖДЕН! Непрерывный звук {sound_time:.1f} секунд (уровень: {avg_rms:.6f})")
                            print(f"   Лампа переключена в зеленый режим")
                            
                            # ИСПРАВЛЕНИЕ: Отправляем уведомление о восстановлении только после подтверждения звука
                            # Сбрасываем отслеживание тишины только при подтвержденном звуке
                            if self.silence_start_time is not None:
                                silence_time = time.time() - self.silence_start_time
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] Конец тишины после {silence_time:.1f}с - звук подтвержден!")
                                
                                # Вызываем колбэк при восстановлении звука (только если предупреждение было отправлено)
                                if self.on_sound_restored_callback and self.silence_warning_sent:
                                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [AudioMonitor] Вызов колбэка on_sound_restored")
                                    self.on_sound_restored_callback(silence_time)
                                
                                self.silence_start_time = None
                                self.silence_warning_sent = False  # Сброс флага при восстановлении звука
                        
            except Exception as e:
                print(f"[AudioMonitor] Критическая ошибка в цикле мониторинга: {e}")
                error_count += 1
                if error_count >= max_errors:
                    print(f"[AudioMonitor] Слишком много критических ошибок, остановка мониторинга")
                    break
                time.sleep(0.5)  # Увеличенная пауза при критических ошибках
                
    def get_current_level(self):
        """Получение текущего уровня звука"""
        return self.current_level
    
    def enable_monitoring(self):
        """Включает мониторинг звука (НЕ сохраняет в конфиг - это делает GUI/сервер)"""
        self.monitoring_enabled = True
        print("[AudioMonitor] ✅ Мониторинг включен")
    
    def disable_monitoring(self):
        """Отключает мониторинг звука (НЕ сохраняет в конфиг - это делает GUI/сервер)"""
        self.monitoring_enabled = False
        print("[AudioMonitor] ❌ Мониторинг отключен")
        # Останавливаем мониторинг если он запущен
        if self.is_monitoring:
            self.stop_monitoring()
    
    def toggle_monitoring(self):
        """Переключает состояние мониторинга (НЕ сохраняет в конфиг - это делает GUI/сервер)"""
        if self.monitoring_enabled:
            self.disable_monitoring()
        else:
            self.enable_monitoring()
        return self.monitoring_enabled
    
    def get_lamp_status(self):
        """
        Получение статуса лампы
        
        Returns:
            dict: {'lamp_lit': bool, 'audio_level': float, 'monitoring_active': bool, 'monitoring_enabled': bool}
        """
        return {
            'lamp_lit': self.lamp_status,  # True = красная (тишина), False = зеленая (звук)
            'audio_level': self.current_level,
            'monitoring_active': self.is_monitoring,
            'monitoring_enabled': self.monitoring_enabled
        }
    
    def set_callbacks(self, on_silence_detected=None, on_sound_restored=None, 
                     on_silence_warning=None, on_level_updated=None):
        """
        Установка колбэков для событий
        
        Args:
            on_silence_detected: Колбэк при обнаружении тишины (принимает уровень звука)
            on_sound_restored: Колбэк при восстановлении звука (принимает длительность тишины)
            on_silence_warning: Колбэк при длительной тишине (принимает длительность)
            on_level_updated: Колбэк при обновлении уровня звука (принимает уровень)
        """
        self.on_silence_detected_callback = on_silence_detected
        self.on_sound_restored_callback = on_sound_restored
        self.on_silence_warning_callback = on_silence_warning
        self.on_level_updated_callback = on_level_updated
    
    def cleanup(self):
        """Окончательная очистка ресурсов (вызывать при завершении приложения)"""
        try:
            self.stop_monitoring()
            if hasattr(self, 'audio') and self.audio:
                self.audio.terminate()
                print("[AudioMonitor] PyAudio завершен")
        except Exception as e:
            print(f"[AudioMonitor] Ошибка при очистке: {e}")

def main():
    """Основная функция"""
    print("=== Монитор уровня звука с микрофона ===")
    
    # Настройки по умолчанию
    threshold = 0.01  # Пороговое значение уровня звука
    silence_duration = 20  # Длительность тишины для предупреждения (секунды)
    
    # Создание и запуск монитора
    monitor = AudioMonitor(threshold=threshold, silence_duration=silence_duration)
    
    try:
        monitor.start_monitoring()
        
        # Основной цикл программы
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nПолучен сигнал остановки...")
        monitor.stop_monitoring()
        
    except Exception as e:
        print(f"Ошибка: {e}")
        monitor.stop_monitoring()

if __name__ == "__main__":
    main()
