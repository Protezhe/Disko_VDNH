#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска саундчека.
Простой и удобный для редактирования.
"""

import os
import sys
import time
import json
from pathlib import Path
import matplotlib
# Используем безоконный backend, чтобы работать из серверных потоков
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np

# Импортируем наши классы
from vlc_playlist import VLCPlaylistLauncher
from audio_monitor import AudioMonitor


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class SoundCheck:
    """Класс для запуска саундчека"""
    
    def __init__(self, audio_monitor=None):
        """
        Инициализация
        
        Args:
            audio_monitor (AudioMonitor, optional): Существующий экземпляр AudioMonitor для переиспользования
        """
        self.project_root = Path(get_exe_dir())
        self.config_file = self.project_root / 'scheduler_config.json'
        
        # Путь к саундчек треку
        self.soundcheck_track = self.project_root / 'mp3' / 'Саундчек' / '150_Hz.mp3'
        
        # Инициализация компонентов
        self.vlc_launcher = VLCPlaylistLauncher()
        self.audio_monitor = audio_monitor  # Используем переданный экземпляр или None
        
        # Настройки (можно легко редактировать)
        self.delay_before_close = 10  # секунд до закрытия VLC
        
        # Данные для графика
        self.soundcheck_data = {
            'timestamps': [],
            'audio_levels': [],
            'start_time': None,
            'end_time': None
        }
        
    def log(self, message):
        """Логирование"""
        print(f"[SoundCheck] {message}")
    
    def _on_audio_level_updated(self, level):
        """Колбэк для сбора данных уровня звука"""
        current_time = datetime.now()
        # Добавляем данные синхронно
        self.soundcheck_data['timestamps'].append(current_time)
        self.soundcheck_data['audio_levels'].append(float(level))
    
    def _reset_soundcheck_data(self):
        """Сброс данных саундчека"""
        self.soundcheck_data = {
            'timestamps': [],
            'audio_levels': [],
            'start_time': None,
            'end_time': None
        }
    
    def save_soundcheck_data(self, output_path=None):
        """
        Сохраняет данные саундчека в JSON файл (перезаписывает файл)
        
        Args:
            output_path (str): Путь для сохранения данных (по умолчанию soundcheck_data.json)
        
        Returns:
            str: Путь к созданному файлу данных
        """
        if not self.soundcheck_data['timestamps']:
            self.log("❌ Нет данных для сохранения")
            return None
        
        # Определяем путь для сохранения
        if output_path is None:
            output_path = self.project_root / "soundcheck_data.json"
        
        try:
            # Получаем массивы данных
            timestamps = self.soundcheck_data['timestamps']
            audio_levels = self.soundcheck_data['audio_levels']
            
            # Выравниваем длину массивов если необходимо
            if len(timestamps) != len(audio_levels):
                min_len = min(len(timestamps), len(audio_levels))
                timestamps = timestamps[:min_len]
                audio_levels = audio_levels[:min_len]
                self.log(f"⚠ Обрезаны массивы до одинаковой длины: {min_len}")
            
            # Конвертируем в обычные Python типы для JSON
            audio_levels_converted = [float(level) for level in audio_levels]
            
            # Подготавливаем данные для сохранения
            data_to_save = {
                'start_time': self.soundcheck_data['start_time'].isoformat() if self.soundcheck_data['start_time'] else None,
                'end_time': self.soundcheck_data['end_time'].isoformat() if self.soundcheck_data['end_time'] else None,
                'duration_seconds': (self.soundcheck_data['end_time'] - self.soundcheck_data['start_time']).total_seconds() if self.soundcheck_data['start_time'] and self.soundcheck_data['end_time'] else None,
                'data_points': len(timestamps),
                'timestamps': [ts.isoformat() for ts in timestamps],
                'audio_levels': audio_levels_converted,
                'max_level': float(max(audio_levels_converted)) if audio_levels_converted else 0.0,
                'avg_level': float(np.mean(audio_levels_converted)) if audio_levels_converted else 0.0,
                'min_level': float(min(audio_levels_converted)) if audio_levels_converted else 0.0
            }
            
            # Сохраняем в JSON файл (перезаписываем)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            
            self.log(f"✓ Данные саундчека сохранены: {output_path}")
            return str(output_path)
            
        except Exception as e:
            self.log(f"❌ Ошибка при сохранении данных: {e}")
            return None
    
    def generate_soundcheck_graph(self, output_path=None):
        """
        Генерирует PNG график изменения громкости во время саундчека
        
        Args:
            output_path (str): Путь для сохранения графика (по умолчанию в папке проекта)
        
        Returns:
            str: Путь к созданному файлу графика
        """
        if not self.soundcheck_data['timestamps']:
            self.log("❌ Нет данных для создания графика")
            return None
        
        # Определяем путь для сохранения
        if output_path is None:
            output_path = self.project_root / "soundcheck_graph.png"
        
        try:
            # Проверяем одинаковую длину массивов
            timestamps = self.soundcheck_data['timestamps'].copy()
            audio_levels = self.soundcheck_data['audio_levels'].copy()
            
            if len(timestamps) != len(audio_levels):
                min_len = min(len(timestamps), len(audio_levels))
                timestamps = timestamps[:min_len]
                audio_levels = audio_levels[:min_len]
                self.log(f"⚠ Обрезаны массивы до одинаковой длины: {min_len}")
            
            # Дополнительная проверка на пустые массивы
            if not timestamps or not audio_levels:
                self.log("❌ Пустые массивы данных")
                return None
            
            # Создаем график
            plt.figure(figsize=(12, 6))
            
            # Конвертируем timestamps в числовой формат для matplotlib
            times = mdates.date2num(timestamps)
            
            # Строим график
            plt.plot(times, audio_levels, 
                    linewidth=2, color='blue', alpha=0.7)
            
            # Добавляем заливку под графиком
            plt.fill_between(times, audio_levels, 
                           alpha=0.3, color='blue')
            
            # Настройка осей
            plt.xlabel('Время', fontsize=12)
            plt.ylabel('Уровень звука (RMS)', fontsize=12)
            plt.title('Изменение громкости во время саундчека', fontsize=14, fontweight='bold')
            
            # Форматирование оси времени
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.gca().xaxis.set_major_locator(mdates.SecondLocator(interval=2))
            plt.xticks(rotation=45)
            
            # Добавляем сетку
            plt.grid(True, alpha=0.3)
            
            # Добавляем статистику
            if audio_levels:
                max_level = max(audio_levels)
                avg_level = np.mean(audio_levels)
                duration = (timestamps[-1] - timestamps[0]).total_seconds()
                
                stats_text = f"Макс: {max_level:.4f}\nСреднее: {avg_level:.4f}\nДлительность: {duration:.1f}с"
                plt.text(0.02, 0.98, stats_text, transform=plt.gca().transAxes, 
                        verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
            
            # Настройка layout
            plt.tight_layout()
            
            # Сохраняем график
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.log(f"✓ График сохранен: {output_path}")
            return str(output_path)
            
        except Exception as e:
            self.log(f"❌ Ошибка при создании графика: {e}")
            return None
    
    def run_soundcheck(self):
        """
        Запускает саундчек:
        1. Закрывает VLC если он открыт
        2. Останавливает аудио мониторинг (если включен)
        3. Запускает мониторинг
        4. Включает трек 150_Hz в VLC
        5. Через 2 секунды закрывает VLC
        """
        self.log("=" * 60)
        self.log("ЗАПУСК САУНДЧЕКА")
        self.log("=" * 60)
        
        # Сбрасываем данные предыдущего саундчека
        self._reset_soundcheck_data()
        self.soundcheck_data['start_time'] = datetime.now()
        
        # Проверяем наличие VLC перед началом
        if not self.vlc_launcher.vlc_paths:
            self.log("❌ ОШИБКА: VLC плеер не найден!")
            self.log("Убедитесь, что VLC установлен и доступен в системе.")
            self.log("Попробуйте установить VLC или добавить его в PATH")
            return False
        
        self.log(f"✓ VLC найден: {self.vlc_launcher.vlc_paths[0]}")
        
        # Шаг 1: Закрываем VLC если он открыт
        self.log("Шаг 1/5: Проверяю и закрываю VLC...")
        if self.vlc_launcher.is_vlc_running():
            closed_count = self.vlc_launcher.close_all_vlc()
            self.log(f"✓ VLC закрыт (процессов: {closed_count})")
            time.sleep(1)  # Пауза для завершения процессов
        else:
            self.log("✓ VLC не запущен")
        
        # Шаг 2: Останавливаем аудио мониторинг (если включен)
        self.log("Шаг 2/5: Останавливаю аудио мониторинг...")
        try:
            # Создаем новый экземпляр AudioMonitor только если нужно
            if not self.audio_monitor:
                self.audio_monitor = AudioMonitor(config_file=str(self.config_file))
            
            if self.audio_monitor.is_monitoring:
                self.audio_monitor.stop_monitoring()
                self.log("✓ Мониторинг остановлен")
            else:
                self.log("✓ Мониторинг не был запущен")
            time.sleep(0.5)
        except Exception as e:
            self.log(f"⚠ Ошибка при остановке мониторинга: {e}")
        
        # Шаг 3: Запускаем мониторинг
        self.log("Шаг 3/5: Запускаю аудио мониторинг...")
        try:
            # Включаем мониторинг если он был отключен
            if not self.audio_monitor.monitoring_enabled:
                self.audio_monitor.enable_monitoring()
            
            # Устанавливаем колбэк для сбора данных
            self.audio_monitor.set_callbacks(on_level_updated=self._on_audio_level_updated)
            
            # Запускаем мониторинг
            success = self.audio_monitor.start_monitoring()
            if success:
                self.log("✓ Мониторинг запущен с сбором данных")
            else:
                self.log("⚠ Не удалось запустить мониторинг")
            time.sleep(1)
        except Exception as e:
            self.log(f"⚠ Ошибка при запуске мониторинга: {e}")
        
        # Шаг 4: Проверяем наличие трека и запускаем VLC
        self.log("Шаг 4/5: Запускаю трек 150_Hz в VLC...")
        if not self.soundcheck_track.exists():
            self.log(f"❌ ОШИБКА: Трек не найден: {self.soundcheck_track}")
            self.log("Проверьте наличие файла mp3/Саундчек/150_Hz.mp3")
            return False
        
        try:
            success = self.vlc_launcher.launch_vlc(
                str(self.soundcheck_track),
                close_existing=False,  # Мы уже закрыли VLC на шаге 1
                enable_http=True  # Включаем HTTP для возможного управления
            )
            if success:
                self.log(f"✓ VLC запущен с треком: {self.soundcheck_track.name}")
            else:
                self.log("❌ Не удалось запустить VLC")
                return False
        except Exception as e:
            self.log(f"❌ Ошибка при запуске VLC: {e}")
            return False
        
        # Шаг 5: Ждем и закрываем VLC
        self.log(f"Шаг 5/5: Жду {self.delay_before_close} секунд перед закрытием VLC...")
        for i in range(self.delay_before_close, 0, -1):
            print(f"  {i}...", end='\r')
            time.sleep(1)
        print()  # Новая строка после обратного отсчета
        
        self.log("Закрываю VLC...")
        try:
            closed_count = self.vlc_launcher.close_all_vlc()
            self.log(f"✓ VLC закрыт (процессов: {closed_count})")
        except Exception as e:
            self.log(f"⚠ Ошибка при закрытии VLC: {e}")
        
        # Фиксируем время окончания саундчека
        self.soundcheck_data['end_time'] = datetime.now()
        
        # Сохраняем данные саундчека в JSON
        self.log("Сохраняю данные саундчека...")
        data_path = self.save_soundcheck_data()
        if data_path:
            self.log(f"✓ Данные сохранены: {data_path}")
        else:
            self.log("⚠ Не удалось сохранить данные")
        
        # Генерируем график
        self.log("Генерирую график изменения громкости...")
        graph_path = self.generate_soundcheck_graph()
        if graph_path:
            self.log(f"✓ График создан: {graph_path}")
        else:
            self.log("⚠ Не удалось создать график")
        
        self.log("=" * 60)
        self.log("САУНДЧЕК ЗАВЕРШЕН")
        self.log("=" * 60)
        
        return True
    
    def cleanup(self):
        """Очистка ресурсов"""
        if self.audio_monitor:
            try:
                # НЕ вызываем cleanup() чтобы не завершать PyAudio
                # Просто останавливаем мониторинг
                if self.audio_monitor.is_monitoring:
                    self.audio_monitor.stop_monitoring()
            except Exception as e:
                self.log(f"⚠ Ошибка при очистке: {e}")


def main():
    """Главная функция"""
    soundcheck = SoundCheck()
    
    try:
        soundcheck.run_soundcheck()
    except KeyboardInterrupt:
        print("\n\n[SoundCheck] Прервано пользователем")
    except Exception as e:
        print(f"\n[SoundCheck] Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        soundcheck.cleanup()


if __name__ == '__main__':
    main()

