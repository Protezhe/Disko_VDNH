#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для управления еженедельной сменой конфигураций.
Переключает config.txt между config_zhenya.txt и config_ruslan.txt каждую неделю.
"""

import os
import sys
import json
import shutil
from datetime import datetime, timedelta


def get_exe_dir():
    """Получает директорию где находится exe файл"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


class ConfigManager:
    """Класс для управления еженедельной сменой конфигураций."""

    def __init__(self, config_dir=None, state_file=None):
        """
        Инициализация менеджера конфигураций.

        Args:
            config_dir (str): Директория с конфигурационными файлами
            state_file (str): Путь к файлу состояния
        """
        self.config_dir = config_dir if config_dir else get_exe_dir()
        self.state_file = state_file if state_file else os.path.join(self.config_dir, 'scheduler_config.json')

        # Пути к конфигурационным файлам
        self.config_main = os.path.join(self.config_dir, 'config.txt')
        self.config_zhenya = os.path.join(self.config_dir, 'config_zhenya.txt')
        self.config_ruslan = os.path.join(self.config_dir, 'config_ruslan.txt')

        # Загружаем состояние
        self.state = self.load_state()

    def load_state(self):
        """
        Загружает состояние из файла.

        Returns:
            dict: Словарь с состоянием (текущий конфиг и дата последней смены)
        """
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Извлекаем только нужные поля
                    return {
                        'current_config': config.get('current_config', 'zhenya'),
                        'last_switch_date': config.get('last_switch_date', datetime.now().strftime('%Y-%m-%d')),
                        'last_switch_week': config.get('last_switch_week', datetime.now().isocalendar()[1])
                    }
            else:
                # Инициализация состояния по умолчанию
                return {
                    'current_config': 'zhenya',
                    'last_switch_date': datetime.now().strftime('%Y-%m-%d'),
                    'last_switch_week': datetime.now().isocalendar()[1]
                }
        except Exception as e:
            print(f'Ошибка загрузки состояния: {e}')
            return {
                'current_config': 'zhenya',
                'last_switch_date': datetime.now().strftime('%Y-%m-%d'),
                'last_switch_week': datetime.now().isocalendar()[1]
            }

    def save_state(self):
        """Сохраняет текущее состояние в файл."""
        try:
            # Читаем весь конфиг
            with open(self.state_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Обновляем только поля состояния
            config['current_config'] = self.state['current_config']
            config['last_switch_date'] = self.state['last_switch_date']
            config['last_switch_week'] = self.state['last_switch_week']

            # Сохраняем весь конфиг обратно
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print(f'Состояние сохранено: {self.state}')
        except Exception as e:
            print(f'Ошибка сохранения состояния: {e}')

    def get_current_week_number(self):
        """
        Получает номер текущей недели года.

        Returns:
            int: Номер недели (1-53)
        """
        return datetime.now().isocalendar()[1]

    def should_switch_config(self):
        """
        Проверяет, нужно ли переключить конфигурацию.
        Переключение происходит каждую неделю.

        Returns:
            bool: True если нужно переключить
        """
        current_week = self.get_current_week_number()
        last_switch_week = self.state.get('last_switch_week', current_week)

        # Если номер недели изменился, нужно переключить
        return current_week != last_switch_week

    def switch_config(self):
        """
        Переключает конфигурацию на следующую по очереди.

        Returns:
            bool: True если переключение выполнено успешно
        """
        try:
            current_config = self.state.get('current_config', 'zhenya')

            # Определяем следующую конфигурацию
            if current_config == 'zhenya':
                next_config = 'ruslan'
                source_file = self.config_ruslan
            else:
                next_config = 'zhenya'
                source_file = self.config_zhenya

            # Проверяем что исходный файл существует
            if not os.path.exists(source_file):
                print(f'Ошибка: файл {source_file} не найден')
                return False

            # Создаем резервную копию текущего config.txt
            if os.path.exists(self.config_main):
                backup_file = self.config_main + '.backup'
                shutil.copy2(self.config_main, backup_file)

            # Копируем новую конфигурацию
            shutil.copy2(source_file, self.config_main)

            # Обновляем состояние
            self.state['current_config'] = next_config
            self.state['last_switch_date'] = datetime.now().strftime('%Y-%m-%d')
            self.state['last_switch_week'] = self.get_current_week_number()
            self.save_state()

            print(f'✅ Конфигурация переключена на: {next_config}')
            print(f'   Файл: config_{next_config}.txt -> config.txt')

            return True

        except Exception as e:
            print(f'❌ Ошибка при переключении конфигурации: {e}')
            return False

    def check_and_switch(self):
        """
        Проверяет необходимость переключения и выполняет его при необходимости.

        Returns:
            dict: Информация о выполненном действии
        """
        if self.should_switch_config():
            print('🔄 Обнаружена новая неделя, переключаю конфигурацию...')
            success = self.switch_config()
            return {
                'switched': success,
                'current_config': self.state.get('current_config'),
                'message': 'Конфигурация переключена' if success else 'Ошибка переключения'
            }
        else:
            return {
                'switched': False,
                'current_config': self.state.get('current_config'),
                'message': 'Переключение не требуется'
            }

    def force_switch(self):
        """
        Принудительно переключает конфигурацию (для тестирования или ручного управления).

        Returns:
            bool: True если переключение выполнено успешно
        """
        print('🔄 Принудительное переключение конфигурации...')
        success = self.switch_config()
        return success

    def get_status(self):
        """
        Получает текущий статус конфигурации.

        Returns:
            dict: Информация о текущем состоянии
        """
        current_week = self.get_current_week_number()
        current_config = self.state.get('current_config', 'unknown')
        last_switch_date = self.state.get('last_switch_date', 'неизвестно')
        last_switch_week = self.state.get('last_switch_week', 'неизвестно')

        return {
            'current_config': current_config,
            'current_week': current_week,
            'last_switch_date': last_switch_date,
            'last_switch_week': last_switch_week,
            'should_switch': self.should_switch_config()
        }

    def set_config(self, config_name):
        """
        Устанавливает конкретную конфигурацию.

        Args:
            config_name (str): Имя конфигурации ('zhenya' или 'ruslan')

        Returns:
            bool: True если установка выполнена успешно
        """
        try:
            if config_name not in ['zhenya', 'ruslan']:
                print(f'❌ Неверное имя конфигурации: {config_name}')
                return False

            # Определяем исходный файл
            if config_name == 'zhenya':
                source_file = self.config_zhenya
            else:
                source_file = self.config_ruslan

            # Проверяем что исходный файл существует
            if not os.path.exists(source_file):
                print(f'Ошибка: файл {source_file} не найден')
                return False

            # Создаем резервную копию текущего config.txt
            if os.path.exists(self.config_main):
                backup_file = self.config_main + '.backup'
                shutil.copy2(self.config_main, backup_file)

            # Копируем новую конфигурацию
            shutil.copy2(source_file, self.config_main)

            # Обновляем состояние
            self.state['current_config'] = config_name
            self.state['last_switch_date'] = datetime.now().strftime('%Y-%m-%d')
            self.state['last_switch_week'] = self.get_current_week_number()
            self.save_state()

            print(f'✅ Установлена конфигурация: {config_name}')

            return True

        except Exception as e:
            print(f'❌ Ошибка при установке конфигурации: {e}')
            return False


def main():
    """Тестовая функция"""
    print("=== Менеджер конфигураций ===")

    manager = ConfigManager()

    # Меню для тестирования
    while True:
        print("\n--- Меню ---")
        print("1. Показать статус")
        print("2. Проверить и переключить (если нужно)")
        print("3. Принудительно переключить")
        print("4. Установить config_zhenya")
        print("5. Установить config_ruslan")
        print("0. Выход")

        choice = input("\nВыберите действие: ").strip()

        if choice == '1':
            status = manager.get_status()
            print(f"\nТекущий статус:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        elif choice == '2':
            result = manager.check_and_switch()
            print(f"\nРезультат: {result}")
        elif choice == '3':
            manager.force_switch()
        elif choice == '4':
            manager.set_config('zhenya')
        elif choice == '5':
            manager.set_config('ruslan')
        elif choice == '0':
            print("Выход...")
            break
        else:
            print("❌ Неверный выбор")


if __name__ == '__main__':
    main()
