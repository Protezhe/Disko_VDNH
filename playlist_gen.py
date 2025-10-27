import os
import random
from mutagen.mp3 import MP3


class PlaylistGenerator:
    """Класс для генерации плейлистов дискотеки."""
    
    def __init__(self, music_folder='mp3', config_file='config.txt'):
        """
        Инициализация генератора плейлистов.
        
        Args:
            music_folder (str): Путь к папке с музыкой
            config_file (str): Путь к файлу конфигурации
        """
        self.music_folder = music_folder
        self.config_file = config_file
        self.playlist = []
    
    def read_config(self):
        """Читает конфиг и возвращает список папок."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f.readlines()]
        except Exception as e:
            print(f"Ошибка при чтении файла конфигурации: {e}")
            return []
    
    def get_tracks_from_folder(self, folder_path):
        """Возвращает список всех треков в указанной папке."""
        try:
            if os.path.exists(folder_path):
                return [os.path.join(folder_path, track) for track in os.listdir(folder_path) if track.endswith('.mp3')]
            else:
                print(f"Папка не найдена: {folder_path}")
                return []
        except Exception as e:
            print(f"Ошибка при получении треков из папки {folder_path}: {e}")
            return []
    
    def create_playlist(self, duration_hours):
        """
        Создает плейлист с указанной длительностью в часах.
        
        Args:
            duration_hours (float): Длительность плейлиста в часах
            
        Returns:
            list: Список треков в плейлисте
        """
        config = self.read_config()
        max_duration = duration_hours * 60 * 60  # Переводим часы в секунды
        
        self.playlist = []
        total_duration = 0
        track_history = {}
        
        while total_duration < max_duration:
            for folder in config:
                folder_path = os.path.join(self.music_folder, folder)
                
                if folder not in track_history:
                    track_history[folder] = self.get_tracks_from_folder(folder_path)
                    if not track_history[folder]:
                        continue
                    random.shuffle(track_history[folder])
                
                if track_history[folder]:
                    track = track_history[folder].pop(0)
                    try:
                        audio = MP3(track)
                        track_length = int(audio.info.length)
                    except Exception as e:
                        print(f"Ошибка при получении информации о треке {track}: {e}")
                        continue
                    
                    if total_duration + track_length > max_duration:
                        return self.playlist
                    
                    self.playlist.append(track)
                    total_duration += track_length
        
        return self.playlist
    
    def get_next_playlist_filename(self, directory, base_filename='playlist', extension='.m3u'):
        """Возвращает следующее уникальное имя для плейлиста в указанной директории."""
        index = 1
        while True:
            filename = f"{base_filename}{index}{extension}"
            file_path = os.path.join(directory, filename)
            if not os.path.exists(file_path):
                return file_path
            index += 1
    
    def clear_old_playlists(self, output_dir='.', base_filename='playlist', extension='.m3u'):
        """
        Удаляет все старые плейлисты в указанной директории.
        
        Args:
            output_dir (str): Папка с плейлистами
            base_filename (str): Базовое имя файла плейлиста
            extension (str): Расширение файла
        """
        try:
            if not os.path.exists(output_dir):
                return
            
            # Ищем все файлы плейлистов
            for filename in os.listdir(output_dir):
                if filename.startswith(base_filename) and filename.endswith(extension):
                    file_path = os.path.join(output_dir, filename)
                    try:
                        os.remove(file_path)
                        print(f'Удален старый плейлист: {filename}')
                    except Exception as e:
                        print(f'Ошибка при удалении {filename}: {e}')
                        
        except Exception as e:
            print(f'Ошибка при очистке старых плейлистов: {e}')
    
    def save_playlist(self, output_dir='.'):
        """
        Сохраняет плейлист в формате M3U.
        Перед сохранением удаляет все старые плейлисты.
        
        Args:
            output_dir (str): Папка для сохранения плейлиста (по умолчанию корневая директория)
            
        Returns:
            str: Путь к сохраненному файлу
        """
        if not self.playlist:
            print("Плейлист пуст! Сначала создайте плейлист.")
            return None
        
        # Удаляем все старые плейлисты перед созданием нового
        self.clear_old_playlists(output_dir)
        
        m3u_content = "#EXTM3U\n"
        for track in self.playlist:
            track_name = os.path.basename(track)
            try:
                audio = MP3(track)
                track_duration = int(audio.info.length)
                m3u_content += f"#EXTINF:{track_duration},{track_name}\n{track}\n"
            except Exception as e:
                print(f"Ошибка при получении информации о треке {track}: {e}")
                continue
        
        # Создаем папку для сохранения файла плейлиста (если нужно)
        if output_dir != '.':
            os.makedirs(output_dir, exist_ok=True)
        
        # Получаем следующее уникальное имя файла
        m3u_file_path = self.get_next_playlist_filename(output_dir)
        
        # Сохраняем плейлист в файл
        with open(m3u_file_path, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        
        print(f'Плейлист успешно сохранен как {os.path.basename(m3u_file_path)}!')
        return m3u_file_path
    
    def get_playlist_info(self):
        """Возвращает информацию о текущем плейлисте."""
        if not self.playlist:
            return "Плейлист пуст"
        
        total_duration = 0
        for track in self.playlist:
            try:
                audio = MP3(track)
                total_duration += int(audio.info.length)
            except:
                continue
        
        hours = total_duration // 3600
        minutes = (total_duration % 3600) // 60
        seconds = total_duration % 60
        
        return f"Треков: {len(self.playlist)}, Длительность: {hours:02d}:{minutes:02d}:{seconds:02d}"


if __name__ == '__main__':
    # Демонстрация работы класса
    generator = PlaylistGenerator()
    playlist = generator.create_playlist(3)  # 3 часа
    generator.save_playlist()
    print(f"Информация о плейлисте: {generator.get_playlist_info()}")
