#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утилиты для очистки служебных файлов
"""

import os


def cleanup_macos_service_files(music_folder='mp3', verbose=True):
    """
    Удаляет служебные файлы macOS из папки с музыкой.

    Удаляет:
    - Файлы, начинающиеся с ._ (AppleDouble encoded files)
    - Файлы .DS_Store (настройки Finder)
    - Файлы Thumbs.db (эскизы Windows, на всякий случай)

    Args:
        music_folder (str): Путь к папке с музыкой
        verbose (bool): Выводить ли подробную информацию

    Returns:
        dict: Статистика удаления {'removed_count': int, 'freed_bytes': int, 'errors': list}
    """
    stats = {
        'removed_count': 0,
        'freed_bytes': 0,
        'errors': []
    }

    if not os.path.exists(music_folder):
        if verbose:
            print(f"⚠️ Папка {music_folder} не найдена, пропускаем очистку")
        return stats

    # Список паттернов для удаления
    service_file_patterns = [
        lambda name: name.startswith('._'),  # AppleDouble
        lambda name: name == '.DS_Store',     # macOS Finder
        lambda name: name == 'Thumbs.db',     # Windows thumbnails
        lambda name: name == 'desktop.ini'    # Windows folder settings
    ]

    try:
        # Рекурсивно обходим все папки
        for root, dirs, files in os.walk(music_folder):
            for filename in files:
                # Проверяем, соответствует ли файл паттернам служебных файлов
                is_service_file = any(pattern(filename) for pattern in service_file_patterns)

                if is_service_file:
                    filepath = os.path.join(root, filename)
                    try:
                        # Получаем размер перед удалением
                        file_size = os.path.getsize(filepath)

                        # Удаляем файл
                        os.remove(filepath)

                        # Обновляем статистику
                        stats['removed_count'] += 1
                        stats['freed_bytes'] += file_size

                        if verbose:
                            # Относительный путь для читаемости
                            rel_path = os.path.relpath(filepath, music_folder)
                            size_kb = file_size / 1024
                            print(f"  🗑️ Удален: {rel_path} ({size_kb:.1f} KB)")

                    except Exception as e:
                        error_msg = f"Ошибка удаления {filepath}: {e}"
                        stats['errors'].append(error_msg)
                        if verbose:
                            print(f"  ❌ {error_msg}")

        # Итоговая статистика
        if verbose:
            if stats['removed_count'] > 0:
                freed_mb = stats['freed_bytes'] / (1024 * 1024)
                print(f"\n✅ Очистка завершена:")
                print(f"   Удалено файлов: {stats['removed_count']}")
                print(f"   Освобождено места: {freed_mb:.2f} MB")
                if stats['errors']:
                    print(f"   Ошибок: {len(stats['errors'])}")
            else:
                print("✅ Служебные файлы не найдены - всё чисто!")

    except Exception as e:
        error_msg = f"Ошибка при обходе папок: {e}"
        stats['errors'].append(error_msg)
        if verbose:
            print(f"❌ {error_msg}")

    return stats


def cleanup_on_startup(music_folder='mp3'):
    """
    Очистка служебных файлов при запуске сервера.
    Выводит краткую информацию.

    Args:
        music_folder (str): Путь к папке с музыкой
    """
    print("\n" + "=" * 60)
    print("🧹 Очистка служебных файлов macOS/Windows...")
    print("=" * 60)

    stats = cleanup_macos_service_files(music_folder, verbose=True)

    print("=" * 60 + "\n")

    return stats


if __name__ == '__main__':
    # Тестирование
    import sys

    # Кодировка для Windows консоли
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass

    # Запускаем очистку
    cleanup_on_startup()
