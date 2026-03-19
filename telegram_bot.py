#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
УСТАРЕЛ: Этот модуль оставлен для обратной совместимости.
Используйте vk_bot.py вместо этого.

Бот переведен на ВКонтакте. Этот файл перенаправляет импорты.
"""

from vk_bot import DiscoVKBot, get_exe_dir

# Для обратной совместимости
TelegramNotifier = DiscoVKBot
DiscoTelegramBot = DiscoVKBot


def main():
    """Перенаправляем на новый модуль"""
    print("ВНИМАНИЕ: telegram_bot.py устарел!")
    print("Используйте vk_bot.py для запуска бота\n")

    from vk_bot import main as new_main
    new_main()


if __name__ == '__main__':
    main()
