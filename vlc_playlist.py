#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска плейлиста в VLC плеере.
Поддерживает автоматический поиск плейлистов в корневой папке.
Включает функции для управления процессами VLC.
"""

import os
import subprocess
import sys
import glob
import datetime
import time
import psutil
import requests
import xml.etree.ElementTree as ET
import base64
from pathlib import Path


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


class VLCPlaylistLauncher:
    """Класс для запуска плейлистов в VLC плеере."""
    
    def __init__(self):
        """Инициализация лаунчера."""
        self.vlc_paths = self._find_vlc_paths()
        self.project_root = Path(get_exe_dir())
    
    def _find_vlc_paths(self):
        """Находит возможные пути к VLC плееру."""
        import platform
        
        if platform.system() == "Windows":
            possible_paths = [
                # Стандартные пути для Windows
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
                r"C:\Users\{}\AppData\Local\VLC\vlc.exe".format(os.getenv('USERNAME')),
                "vlc.exe",
                "vlc",
            ]
        else:
            # Пути для Linux (включая Orange Pi)
            possible_paths = [
                "/usr/bin/vlc",
                "/usr/local/bin/vlc", 
                "/snap/bin/vlc",
                "vlc",  # Из PATH
            ]
        
        found_paths = []
        for path in possible_paths:
            if os.path.exists(path) or self._check_command_exists(path):
                found_paths.append(path)
        
        return found_paths
    
    def _check_command_exists(self, command):
        """Проверяет, существует ли команда в PATH."""
        try:
            subprocess.run([command, "--version"], 
                         capture_output=True, 
                         timeout=5, 
                         check=False)
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False
    
    def find_playlists(self):
        """Находит все плейлисты в корневой папке проекта."""
        playlist_extensions = ['*.m3u', '*.m3u8', '*.pls', '*.xspf']
        playlists = []
        
        for ext in playlist_extensions:
            playlists.extend(glob.glob(str(self.project_root / ext)))
        
        return sorted(playlists)
    
    def get_latest_playlist(self, playlists):
        """Возвращает самый новый плейлист по времени модификации."""
        if not playlists:
            print("Плейлисты не найдены в корневой папке!")
            return None
        
        if len(playlists) == 1:
            print(f"Найден плейлист: {os.path.basename(playlists[0])}")
            return playlists[0]
        
        # Сортируем по времени модификации (самый новый первым)
        playlists_with_time = []
        for playlist in playlists:
            try:
                mtime = os.path.getmtime(playlist)
                playlists_with_time.append((playlist, mtime))
            except OSError:
                # Если не удается получить время модификации, пропускаем
                continue
        
        if not playlists_with_time:
            print("Не удалось определить время модификации плейлистов")
            return playlists[0]  # Возвращаем первый доступный
        
        # Сортируем по времени модификации (убывание)
        playlists_with_time.sort(key=lambda x: x[1], reverse=True)
        latest_playlist = playlists_with_time[0][0]
        
        print(f"Найдены плейлисты:")
        for i, (playlist, mtime) in enumerate(playlists_with_time[:5], 1):  # Показываем только первые 5
            time_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{i}. {os.path.basename(playlist)} ({time_str})")
        
        print(f"\nАвтоматически выбран самый новый плейлист: {os.path.basename(latest_playlist)}")
        return latest_playlist
    
    def close_all_vlc(self):
        """
        Закрывает все процессы VLC.
        
        Returns:
            int: Количество закрытых процессов
        """
        closed_count = 0
        
        # Список возможных имен процессов VLC
        import platform
        if platform.system() == "Windows":
            vlc_process_names = ['vlc.exe', 'vlc', 'vlc-qt.exe']
        else:
            # Linux процессы (включая Orange Pi)
            vlc_process_names = ['vlc', 'vlc-bin', 'vlc-wrapper']
        
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    proc_name = proc.info['name']
                    if proc_name and any(vlc_name in proc_name.lower() for vlc_name in vlc_process_names):
                        print(f'Закрываю процесс VLC: {proc_name} (PID: {proc.info["pid"]})')
                        proc.terminate()
                        closed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Ждем завершения процессов
            if closed_count > 0:
                time.sleep(1)
                
                # Проверяем, что процессы действительно закрылись
                remaining_count = 0
                for proc in psutil.process_iter(['name']):
                    try:
                        proc_name = proc.info['name']
                        if proc_name and any(vlc_name in proc_name.lower() for vlc_name in vlc_process_names):
                            remaining_count += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                if remaining_count == 0:
                    print(f'✅ Все процессы VLC закрыты ({closed_count})')
                else:
                    print(f'⚠️ Закрыто {closed_count} процессов, осталось {remaining_count}')
            else:
                print('ℹ️ Процессы VLC не найдены')
                
        except Exception as e:
            print(f'❌ Ошибка при закрытии VLC: {str(e)}')
            
        return closed_count
    
    def launch_vlc(self, playlist_path, close_existing=True, enable_http=True):
        """
        Запускает VLC с выбранным плейлистом.
        
        Args:
            playlist_path (str): Путь к плейлисту
            close_existing (bool): Закрыть существующие экземпляры VLC перед запуском
            enable_http (bool): Включить HTTP интерфейс для мониторинга воспроизведения
            
        Returns:
            bool: True если запуск успешен
        """
        if not self.vlc_paths:
            print("VLC плеер не найден!")
            print("Убедитесь, что VLC установлен и доступен в системе.")
            return False
        
        # Закрываем существующие экземпляры VLC если требуется
        if close_existing:
            print('Проверяю и закрываю открытые экземпляры VLC...')
            self.close_all_vlc()
            time.sleep(2)  # Пауза для завершения процессов
        
        vlc_executable = self.vlc_paths[0]  # Используем первый найденный путь
        
        try:
            # Базовая команда запуска VLC с плейлистом
            cmd = [vlc_executable, playlist_path]
            
            # Добавляем HTTP интерфейс для мониторинга воспроизведения
            if enable_http:
                cmd.extend([
                    '--extraintf', 'http',  # Дополнительный интерфейс, не заменяет GUI
                    '--http-host', '127.0.0.1',
                    '--http-port', '8080',
                    '--http-password', 'vlcremote'
                ])
                print("HTTP интерфейс VLC будет доступен на http://127.0.0.1:8080 (пароль: vlcremote)")
            
            print(f"Запуск VLC с плейлистом: {os.path.basename(playlist_path)}")
            print(f"Команда: {' '.join(cmd)}")
            
            subprocess.Popen(cmd, 
                           stdout=subprocess.DEVNULL, 
                           stderr=subprocess.DEVNULL)
            
            print("VLC успешно запущен!")
            return True
            
        except Exception as e:
            print(f"Ошибка при запуске VLC: {e}")
            return False
    
    def get_current_track_info(self, vlc_host='127.0.0.1', vlc_port=8080, vlc_password='vlcremote'):
        """
        Получает информацию о текущем воспроизводимом треке через HTTP API VLC.
        
        Args:
            vlc_host (str): Хост VLC HTTP интерфейса
            vlc_port (int): Порт VLC HTTP интерфейса
            vlc_password (str): Пароль для доступа к HTTP интерфейсу
            
        Returns:
            dict: Информация о треке или None если не удалось получить
        """
        try:
            # Создаем URL для запроса статуса
            url = f'http://{vlc_host}:{vlc_port}/requests/status.xml'
            
            # Создаем авторизационные данные
            auth_string = f':{vlc_password}'
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_b64}'
            }
            
            # Выполняем запрос с таймаутом
            response = requests.get(url, headers=headers, timeout=2)
            
            if response.status_code == 200:
                # Парсим XML ответ с правильной кодировкой
                response.encoding = 'utf-8'
                xml_content = response.content.decode('utf-8', errors='ignore')
                root = ET.fromstring(xml_content)
                
                # Извлекаем информацию о треке
                track_info = {
                    'is_playing': False,
                    'title': 'Неизвестно',
                    'artist': '',
                    'filename': '',
                    'position': 0,
                    'length': 0,
                    'time_str': '00:00 / 00:00'
                }
                
                # Проверяем статус воспроизведения
                state_elem = root.find('state')
                if state_elem is not None:
                    track_info['is_playing'] = state_elem.text == 'playing'
                
                # Получаем позицию и длительность
                position_elem = root.find('position')
                length_elem = root.find('length')
                time_elem = root.find('time')
                
                if position_elem is not None:
                    track_info['position'] = float(position_elem.text)
                if length_elem is not None:
                    track_info['length'] = int(length_elem.text)
                if time_elem is not None:
                    track_info['current_time'] = int(time_elem.text)
                
                # Получаем информацию из мета-данных
                information = root.find('information')
                if information is not None:
                    category = information.find('category[@name="meta"]')
                    if category is not None:
                        # Ищем название
                        title_elem = category.find('info[@name="title"]')
                        if title_elem is not None:
                            track_info['title'] = title_elem.text
                        
                        # Ищем исполнителя
                        artist_elem = category.find('info[@name="artist"]')
                        if artist_elem is not None:
                            track_info['artist'] = artist_elem.text
                        
                        # Ищем имя файла
                        filename_elem = category.find('info[@name="filename"]')
                        if filename_elem is not None:
                            track_info['filename'] = filename_elem.text
                
                # Если нет title в мета-данных, пытаемся извлечь из filename
                if track_info['title'] == 'Неизвестно' and track_info['filename']:
                    # Убираем путь и расширение из имени файла
                    base_name = os.path.splitext(os.path.basename(track_info['filename']))[0]
                    track_info['title'] = base_name
                
                # Форматируем время
                if track_info['length'] > 0:
                    current_min = track_info.get('current_time', 0) // 60
                    current_sec = track_info.get('current_time', 0) % 60
                    total_min = track_info['length'] // 60
                    total_sec = track_info['length'] % 60
                    track_info['time_str'] = f"{current_min:02d}:{current_sec:02d} / {total_min:02d}:{total_sec:02d}"
                
                return track_info
            else:
                return None
                
        except requests.RequestException:
            # VLC HTTP интерфейс недоступен
            return None
        except ET.ParseError:
            # Ошибка парсинга XML
            return None
        except Exception as e:
            # Другие ошибки
            print(f"Ошибка получения информации о треке: {e}")
            return None
    
    def is_vlc_running(self):
        """
        Проверяет, запущены ли процессы VLC.
        
        Returns:
            bool: True если VLC запущен
        """
        import platform
        if platform.system() == "Windows":
            vlc_process_names = ['vlc.exe', 'vlc', 'vlc-qt.exe']
        else:
            # Linux процессы (включая Orange Pi)
            vlc_process_names = ['vlc', 'vlc-bin', 'vlc-wrapper']
        
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name']
                    if proc_name and any(vlc_name in proc_name.lower() for vlc_name in vlc_process_names):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except Exception:
            return False
    
    def send_vlc_command(self, command, vlc_host='127.0.0.1', vlc_port=8080, vlc_password='vlcremote'):
        """
        Отправляет команду в VLC через HTTP API.
        
        Args:
            command (str): Команда для VLC (pl_next, pl_previous, pl_pause, pl_play, pl_stop)
            vlc_host (str): Хост VLC HTTP интерфейса
            vlc_port (int): Порт VLC HTTP интерфейса  
            vlc_password (str): Пароль для доступа к HTTP интерфейсу
            
        Returns:
            bool: True если команда выполнена успешно
        """
        try:
            # Создаем URL для отправки команды
            url = f'http://{vlc_host}:{vlc_port}/requests/status.xml'
            
            # Создаем авторизационные данные
            auth_string = f':{vlc_password}'
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_b64}'
            }
            
            # Параметры команды
            params = {'command': command}
            
            # Выполняем запрос
            response = requests.get(url, headers=headers, params=params, timeout=3)
            
            return response.status_code == 200
            
        except requests.RequestException:
            return False
        except Exception as e:
            print(f"Ошибка отправки команды VLC: {e}")
            return False
    
    def next_track(self):
        """
        Переключает на следующий трек.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command('pl_next')
    
    def previous_track(self):
        """
        Переключает на предыдущий трек.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command('pl_previous')
    
    def play_pause(self):
        """
        Переключает воспроизведение/паузу.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command('pl_pause')
    
    def play(self):
        """
        Запускает воспроизведение.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command('pl_play')
    
    def stop(self):
        """
        Останавливает воспроизведение.
        
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command('pl_stop')
    
    def set_volume(self, volume):
        """
        Устанавливает громкость VLC.
        
        Args:
            volume (int): Громкость от 0 до 320 (100 = нормальная громкость)
            
        Returns:
            bool: True если команда выполнена успешно
        """
        return self.send_vlc_command(f'volume&val={volume}')
    
    def run(self):
        """Основной метод запуска."""
        print("=== VLC Плейлист Лаунчер ===")
        
        # Проверяем наличие VLC
        if not self.vlc_paths:
            print("VLC плеер не найден!")
            print("Убедитесь, что VLC установлен и доступен в системе.")
            return
        
        print(f"Найден VLC: {self.vlc_paths[0]}")
        
        # Ищем плейлисты
        playlists = self.find_playlists()
        
        if not playlists:
            print("Плейлисты не найдены в корневой папке!")
            print("Создайте плейлист с помощью playlist_gen.py или demo_playlist.py")
            return
        
        # Выбираем плейлист
        selected_playlist = self.get_latest_playlist(playlists)
        
        if selected_playlist:
            # Запускаем VLC
            self.launch_vlc(selected_playlist)
        else:
            print("Запуск отменен.")


def main():
    """Основная функция."""
    try:
        launcher = VLCPlaylistLauncher()
        launcher.run()
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")


if __name__ == '__main__':
    main()
