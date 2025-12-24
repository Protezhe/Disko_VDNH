#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
УСТАРЕЛ: Этот модуль оставлен для обратной совместимости.
Используйте telegram_bot_commands.py вместо этого.

Телеграм-бот для отправки уведомлений о дискотеке теперь объединен
с интерактивными командами в telegram_bot_commands.py.

Этот файл теперь просто перенаправляет импорты на новый модуль.
"""

# Импортируем все из нового объединенного модуля
from telegram_bot_commands import DiscoTelegramBot, get_exe_dir

# Для обратной совместимости - старое имя класса указывает на новый
TelegramNotifier = DiscoTelegramBot


def main():
    """Тестовая функция - перенаправляем на новый модуль"""
    print("⚠️ ВНИМАНИЕ: telegram_bot.py устарел!")
    print("Используйте telegram_bot_commands.py для запуска бота\n")

    from telegram_bot_commands import main as new_main
    new_main()


if __name__ == '__main__':
    main()
