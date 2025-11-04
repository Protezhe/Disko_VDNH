#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Второй вариант скрипта для запуска саундчека.
Сравнивает текущий массив с предыдущим из JSON файла и показывает процент схожести.
Не сохраняет массив в файл.
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


class SoundCheckV2:
    """Класс для запуска саундчека с сравнением массивов"""
    
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
        
        # Путь к файлу с предыдущими данными
        self.previous_data_file = self.project_root / 'soundcheck_data.json'
        
        # Инициализация компонентов
        self.vlc_launcher = VLCPlaylistLauncher()
        self.audio_monitor = audio_monitor  # Используем переданный экземпляр или None
        
        # Загружаем настройки из конфига
        self._load_config()
        
        # Данные для графика
        self.soundcheck_data = {
            'timestamps': [],
            'audio_levels': [],
            'start_time': None,
            'end_time': None
        }
        
        # Предыдущие данные для сравнения
        self.previous_data = None
    
    def _load_config(self):
        """Загружает настройки из конфигурационного файла"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Загружаем длительность саундчека из конфига
                self.delay_before_close = config.get('soundcheck_duration_seconds', 10)
                self.log(f"✓ Загружена длительность саундчека: {self.delay_before_close} секунд")
            else:
                # Значения по умолчанию если конфиг не найден
                self.delay_before_close = 10
                self.log("⚠ Конфиг не найден, используется длительность по умолчанию: 10 секунд")
        except Exception as e:
            # Значения по умолчанию при ошибке загрузки
            self.delay_before_close = 10
            self.log(f"⚠ Ошибка загрузки конфига: {e}, используется длительность по умолчанию: 10 секунд")
        
    def log(self, message):
        """Логирование"""
        print(f"[SoundCheckV2] {message}")
    
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
    
    def load_previous_data(self):
        """
        Загружает предыдущие данные из JSON файла
        
        Returns:
            dict: Предыдущие данные или None если файл не найден
        """
        if not self.previous_data_file.exists():
            self.log("⚠ Файл с предыдущими данными не найден")
            return None
        
        try:
            with open(self.previous_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Проверяем наличие необходимых полей
            if 'audio_levels' not in data:
                self.log("⚠ В файле отсутствуют данные audio_levels")
                return None
            
            self.log(f"✓ Загружены предыдущие данные: {len(data['audio_levels'])} точек")
            return data
            
        except Exception as e:
            self.log(f"❌ Ошибка при загрузке предыдущих данных: {e}")
            return None
    
    def calculate_similarity_percentage(self, current_levels, previous_levels):
        """
        Вычисляет процент схожести между двумя массивами уровней звука
        
        Args:
            current_levels (list): Текущий массив уровней
            previous_levels (list): Предыдущий массив уровней
        
        Returns:
            float: Процент схожести (0-100)
        """
        if not current_levels or not previous_levels:
            return 0.0
        
        # Приводим массивы к одинаковой длине (берем минимальную)
        min_len = min(len(current_levels), len(previous_levels))
        current_array = np.array(current_levels[:min_len])
        previous_array = np.array(previous_levels[:min_len])
        
        # Нормализуем массивы (приводим к диапазону 0-1)
        current_norm = (current_array - current_array.min()) / (current_array.max() - current_array.min() + 1e-10)
        previous_norm = (previous_array - previous_array.min()) / (previous_array.max() - previous_array.min() + 1e-10)
        
        # Вычисляем коэффициент корреляции Пирсона
        correlation = np.corrcoef(current_norm, previous_norm)[0, 1]
        
        # Преобразуем корреляцию в процент схожести
        # Корреляция от -1 до 1, нам нужен процент от 0 до 100
        similarity_percentage = max(0, correlation * 100)
        
        return similarity_percentage
    
    def compare_with_previous(self):
        """
        Сравнивает текущие данные с предыдущими и выводит результат
        
        Returns:
            float: Процент схожести или None если сравнение невозможно
        """
        if not self.soundcheck_data['audio_levels']:
            self.log("❌ Нет текущих данных для сравнения")
            return None
        
        if not self.previous_data:
            self.log("❌ Нет предыдущих данных для сравнения")
            return None
        
        current_levels = self.soundcheck_data['audio_levels']
        previous_levels = self.previous_data['audio_levels']
        
        similarity = self.calculate_similarity_percentage(current_levels, previous_levels)
        
        self.log("=" * 50)
        self.log("РЕЗУЛЬТАТ СРАВНЕНИЯ")
        self.log("=" * 50)
        self.log(f"Текущий массив: {len(current_levels)} точек")
        self.log(f"Предыдущий массив: {len(previous_levels)} точек")
        self.log(f"Процент схожести: {similarity:.2f}%")
        
        # Интерпретация результата
        if similarity >= 90:
            self.log("✓ ОТЛИЧНО: Массивы очень похожи")
        elif similarity >= 75:
            self.log("✓ ХОРОШО: Массивы достаточно похожи")
        elif similarity >= 50:
            self.log("⚠ СРЕДНЕ: Массивы частично похожи")
        else:
            self.log("❌ ПЛОХО: Массивы сильно отличаются")
        
        self.log("=" * 50)
        
        return similarity
    
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
            output_path = self.project_root / "soundcheck_graph_v2.png"
        
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
            plt.title('Изменение громкости во время саундчека (V2)', fontsize=14, fontweight='bold')
            
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
        1. Загружает предыдущие данные
        2. Закрывает VLC если он открыт
        3. Останавливает аудио мониторинг (если включен)
        4. Запускает мониторинг
        5. Включает трек 150_Hz в VLC
        6. Через 2 секунды закрывает VLC
        7. Сравнивает с предыдущими данными
        """
        self.log("=" * 60)
        self.log("ЗАПУСК САУНДЧЕКА V2")
        self.log("=" * 60)
        
        # Шаг 0: Загружаем предыдущие данные
        self.log("Шаг 0/6: Загружаю предыдущие данные...")
        self.previous_data = self.load_previous_data()
        
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
        self.log("Шаг 1/6: Проверяю и закрываю VLC...")
        if self.vlc_launcher.is_vlc_running():
            closed_count = self.vlc_launcher.close_all_vlc()
            self.log(f"✓ VLC закрыт (процессов: {closed_count})")
            time.sleep(1)  # Пауза для завершения процессов
        else:
            self.log("✓ VLC не запущен")
        
        # Шаг 2: Останавливаем аудио мониторинг (если включен)
        self.log("Шаг 2/6: Останавливаю аудио мониторинг...")
        monitoring_was_active = False
        try:
            # Создаем новый экземпляр AudioMonitor только если нужно
            if not self.audio_monitor:
                self.audio_monitor = AudioMonitor(config_file=str(self.config_file))
            
            # Проверяем состояние мониторинга
            monitoring_was_active = self.audio_monitor.is_monitoring
            
            if monitoring_was_active:
                self.log("⏹ Останавливаю активный мониторинг...")
                self.audio_monitor.stop_monitoring()
                self.log("✓ Мониторинг остановлен")
                # Увеличенная задержка для полной остановки потоков
                time.sleep(1.0)
            else:
                self.log("✓ Мониторинг не был запущен")
        except Exception as e:
            self.log(f"⚠ Ошибка при остановке мониторинга: {e}")
            import traceback
            traceback.print_exc()
            # Продолжаем выполнение даже при ошибке
            time.sleep(0.5)
        
        # Шаг 3: Запускаем мониторинг
        self.log("Шаг 3/6: Запускаю аудио мониторинг...")
        try:
            # Включаем мониторинг если он был отключен
            if not self.audio_monitor.monitoring_enabled:
                self.audio_monitor.enable_monitoring()
            
            # Устанавливаем колбэк для сбора данных
            self.audio_monitor.set_callbacks(on_level_updated=self._on_audio_level_updated)
            
            # Запускаем мониторинг
            self.log("▶ Запуск аудио потока...")
            success = self.audio_monitor.start_monitoring()
            if success:
                self.log("✓ Мониторинг запущен с сбором данных")
            else:
                self.log("⚠ Не удалось запустить мониторинг")
                return False
            
            # Увеличенная задержка для полной инициализации
            time.sleep(1.5)
        except Exception as e:
            self.log(f"❌ Ошибка при запуске мониторинга: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Шаг 4: Проверяем наличие трека и запускаем VLC
        self.log("Шаг 4/6: Запускаю трек 150_Hz в VLC...")
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
        self.log(f"Шаг 5/6: Жду {self.delay_before_close} секунд перед закрытием VLC...")
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
        
        # Шаг 6: Сравниваем с предыдущими данными
        self.log("Шаг 6/6: Сравниваю с предыдущими данными...")
        similarity = self.compare_with_previous()
        
        # Генерируем график
        self.log("Генерирую график изменения громкости...")
        graph_path = self.generate_soundcheck_graph()
        if graph_path:
            self.log(f"✓ График создан: {graph_path}")
        else:
            self.log("⚠ Не удалось создать график")
        
        self.log("=" * 60)
        self.log("САУНДЧЕК V2 ЗАВЕРШЕН")
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
    soundcheck = SoundCheckV2()
    
    try:
        soundcheck.run_soundcheck()
    except KeyboardInterrupt:
        print("\n\n[SoundCheckV2] Прервано пользователем")
    except Exception as e:
        print(f"\n[SoundCheckV2] Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        soundcheck.cleanup()


if __name__ == '__main__':
    main()
