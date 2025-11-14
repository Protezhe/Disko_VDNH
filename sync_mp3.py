#!/usr/bin/env python3
"""
Скрипт синхронизации треков из локальной папки mp3 на удаленный сервер через SSH.
Удаляет файлы на сервере, которых нет локально, и загружает новые файлы.
"""

import os
import sys
import paramiko
from pathlib import Path
from typing import Set, Dict
import stat


class MP3Sync:
    def __init__(self, host: str, username: str, password: str, local_dir: str, remote_dir: str):
        self.host = host
        self.username = username
        self.password = password
        self.local_dir = Path(local_dir)
        self.remote_dir = remote_dir
        self.ssh_client = None
        self.sftp_client = None

    def connect(self):
        """Подключение к серверу по SSH"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print(f"Подключение к {self.username}@{self.host}...")
            self.ssh_client.connect(
                hostname=self.host,
                username=self.username,
                password=self.password,
                timeout=10
            )
            self.sftp_client = self.ssh_client.open_sftp()
            print("Подключение установлено")
            return True
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            return False

    def disconnect(self):
        """Закрытие соединения"""
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
        print("Соединение закрыто")

    def get_local_files(self) -> Dict[str, Path]:
        """Получить словарь всех локальных файлов с их относительными путями"""
        local_files = {}
        if not self.local_dir.exists():
            print(f"Локальная директория {self.local_dir} не существует")
            return local_files

        for root, dirs, files in os.walk(self.local_dir):
            for file in files:
                if file.endswith('.mp3'):
                    full_path = Path(root) / file
                    rel_path = full_path.relative_to(self.local_dir)
                    local_files[str(rel_path).replace('\\', '/')] = full_path

        return local_files

    def _expand_remote_path(self, path: str) -> str:
        """Раскрыть ~ в удаленном пути до абсолютного пути"""
        if path.startswith('~'):
            stdin, stdout, stderr = self.ssh_client.exec_command('echo $HOME')
            home_dir = stdout.read().decode().strip()
            return path.replace('~', home_dir)
        return path

    def get_remote_files(self) -> Set[str]:
        """Получить множество всех удаленных файлов с их относительными путями"""
        remote_files = set()
        # Раскрываем ~ до абсолютного пути
        expanded_remote_dir = self._expand_remote_path(self.remote_dir)
        remote_mp3_path = f"{expanded_remote_dir}/mp3"

        def walk_remote_dir(sftp, remote_path, base_path=""):
            try:
                items = sftp.listdir_attr(remote_path)
                for item in items:
                    item_path = f"{remote_path}/{item.filename}"
                    rel_path = f"{base_path}/{item.filename}" if base_path else item.filename

                    if stat.S_ISDIR(item.st_mode):
                        walk_remote_dir(sftp, item_path, rel_path)
                    elif item.filename.endswith('.mp3'):
                        # Нормализуем путь: убираем двойные слеши
                        normalized = rel_path.replace('\\', '/').replace('//', '/')
                        remote_files.add(normalized)
            except Exception as e:
                print(f"Ошибка при обходе {remote_path}: {e}")

        try:
            # Проверяем существование директории mp3 на сервере
            try:
                self.sftp_client.stat(remote_mp3_path)
            except FileNotFoundError:
                print(f"Создание директории {remote_mp3_path} на сервере...")
                self._create_remote_dir(remote_mp3_path)

            walk_remote_dir(self.sftp_client, remote_mp3_path)
        except Exception as e:
            print(f"Ошибка при получении списка удаленных файлов: {e}")

        return remote_files

    def _create_remote_dir(self, remote_path: str):
        """Рекурсивно создать директорию на сервере"""
        parts = remote_path.strip('/').split('/')
        current_path = ''
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            try:
                self.sftp_client.stat(current_path)
            except FileNotFoundError:
                try:
                    self.sftp_client.mkdir(current_path)
                except Exception as e:
                    print(f"Не удалось создать директорию {current_path}: {e}")

    def upload_file(self, local_path: Path, remote_rel_path: str):
        """Загрузить файл на сервер"""
        expanded_remote_dir = self._expand_remote_path(self.remote_dir)
        remote_full_path = f"{expanded_remote_dir}/mp3/{remote_rel_path}"
        remote_dir = '/'.join(remote_full_path.split('/')[:-1])

        # Создаем директории если нужно
        self._create_remote_dir(remote_dir)

        try:
            print(f"Загрузка: {remote_rel_path}")
            self.sftp_client.put(str(local_path), remote_full_path)
            return True
        except Exception as e:
            print(f"Ошибка при загрузке {remote_rel_path}: {e}")
            return False

    def delete_remote_file(self, remote_rel_path: str):
        """Удалить файл на сервере"""
        expanded_remote_dir = self._expand_remote_path(self.remote_dir)
        remote_full_path = f"{expanded_remote_dir}/mp3/{remote_rel_path}"
        try:
            print(f"Удаление: {remote_rel_path}")
            self.sftp_client.remove(remote_full_path)
            return True
        except Exception as e:
            print(f"Ошибка при удалении {remote_rel_path}: {e}")
            return False

    def sync(self):
        """Выполнить синхронизацию"""
        if not self.connect():
            return False

        try:
            print("\nПолучение списка локальных файлов...")
            local_files = self.get_local_files()
            print(f"Найдено локальных файлов: {len(local_files)}")

            print("\nПолучение списка удаленных файлов...")
            remote_files = self.get_remote_files()
            print(f"Найдено удаленных файлов: {len(remote_files)}")

            # Файлы для загрузки (есть локально, но нет на сервере или изменились)
            files_to_upload = set()
            expanded_remote_dir = self._expand_remote_path(self.remote_dir)
            
            for rel_path, local_path in local_files.items():
                if rel_path not in remote_files:
                    files_to_upload.add((rel_path, local_path))
                    print(f"  Новый файл: {rel_path}")
                else:
                    # Проверяем размер файла для определения изменений
                    try:
                        remote_full_path = f"{expanded_remote_dir}/mp3/{rel_path}"
                        remote_stat = self.sftp_client.stat(remote_full_path)
                        local_size = local_path.stat().st_size
                        if local_size != remote_stat.st_size:
                            files_to_upload.add((rel_path, local_path))
                            print(f"  Изменен размер: {rel_path} (локально: {local_size}, удаленно: {remote_stat.st_size})")
                    except Exception as e:
                        files_to_upload.add((rel_path, local_path))
                        print(f"  Ошибка проверки: {rel_path} - {e}")

            print(f"Файлов для загрузки: {len(files_to_upload)}")

            # Загружаем файлы
            if files_to_upload:
                print("\n--- Загрузка файлов ---")
                for rel_path, local_path in sorted(files_to_upload):
                    self.upload_file(local_path, rel_path)

            print("\n=== Синхронизация завершена ===")
            print(f"Загружено: {len(files_to_upload)} файлов")

            return True

        except Exception as e:
            print(f"Ошибка при синхронизации: {e}")
            return False
        finally:
            self.disconnect()


def main():
    # Параметры подключения из ssh.txt
    HOST = "10.8.0.9"
    USERNAME = "orangepi"
    PASSWORD = "|-]yMQp9.k|rtByx"
    REMOTE_DIR = "~/disco_server"

    # Локальная директория относительно скрипта
    script_dir = Path(__file__).parent
    LOCAL_DIR = script_dir / "mp3_normalized"

    if not LOCAL_DIR.exists():
        print(f"Ошибка: локальная директория {LOCAL_DIR} не существует")
        sys.exit(1)

    sync = MP3Sync(HOST, USERNAME, PASSWORD, str(LOCAL_DIR), REMOTE_DIR)
    success = sync.sync()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

