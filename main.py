import telebot
from telebot import types
import sqlite3
import atexit
import pytz
import datetime
import re
import schedule
import time
from telebot.types import BotCommand, Message
from telegram.error import TelegramError
import threading
import transliterate

timezone = pytz.timezone('Europe/Kiev')

conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    birthday TEXT,
    username TEXT
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week TEXT,
    lesson_number INTEGER,
    subject TEXT,
    start_time TEXT,
    end_time TEXT,
    command TEXT,
    reminded INTEGER DEFAULT 0
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    homework TEXT,
    photo_ids TEXT
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS important_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT,
    end_date TEXT,
    event_text TEXT
)
''')
conn.commit()


bot = telebot.TeleBot('7430719579:AAEbBWVSgmrjdm0JXY9FruhTVXqxlELYjhM')  #7539784956:AAHSTLqowwWwkLX_wA2rJ_tdosUDzo02Np0 Основа:7430719579:AAEbBWVSgmrjdm0JXY9FruhTVXqxlELYjhM

commands = [
    BotCommand("start", "Начать или продолжить общение"),
    BotCommand("help", "Показать список доступных команд"),
    BotCommand("get_info", "Получить информацию о себе"),
    BotCommand("register", "Повторная регистрация"),
    BotCommand("homework", "Записать домашнее задание"),
    BotCommand("clear_chat", "Полная очистка чата")
]

admin_commands = [
    BotCommand("monday", "Заполнить расписание на понедельник"),
    BotCommand("tuesday", "Заполнить расписание на вторник"),
    BotCommand("wednesday", "Заполнить расписание на среду"),
    BotCommand("thursday", "Заполнить расписание на четверг"),
    BotCommand("friday", "Заполнить расписание на пятницу"),
    BotCommand("add_event", "Создать важное событие"),
    BotCommand("delete_event", "Удалить важное событие"),
    BotCommand("list_events", "Список важных событий"),
    BotCommand("clear_db", "Полная очистка базы данных"),
    BotCommand("list_users", "Получить список пользователей"),
    BotCommand("edit_lesson", "Изменить урок по дню и номеру урока"),
    BotCommand("delete_last_lesson", "Удалить последний урок на день"),
    BotCommand("add_lesson", "Добавить новый урок в конец дня")
]


admin_ids = [1341134928, 616194710, 5626868283] 

def get_help_message(user_id):
    help_message = "Доступные команды для всех пользователей:\n"
    for command in commands:
        help_message += f"/{command.command} - {command.description}\n"
    
    if user_id in admin_ids:
        help_message += "\n🔒 Команды для администраторов:\n"
        for command in admin_commands:
            help_message += f"/{command.command} - {command.description}\n"
    
    return help_message

schedule_sent_today = False
user_data = {}

def is_admin(user_id):
    return user_id in admin_ids

@bot.message_handler(commands=['list_users'])
def list_users(message):
    if message.from_user.id in admin_ids:
        cursor.execute("SELECT user_id, name, birthday, username FROM users")
        users = cursor.fetchall()

        if users:
            response = "Список пользователей:\n\n"
            for user in users:
                user_id, name, birthday, username = user
                response += f"ID: {user_id}\n"
                response += f"Имя: {name}\n"
                response += f"Дата рождения: {birthday}\n"
                response += f"Username: @{username if username else 'не указан'}\n"
                response += "-" * 20 + "\n"
        else:
            response = "В базе данных нет пользователей."

        bot.send_message(message.chat.id, response)
    else:
        bot.send_message(message.chat.id, "У тебя нет прав для использования этой команды.")

@bot.message_handler(commands=['clear_db'])
def clear_database(message):
    if message.from_user.id in admin_ids:
        try:
            cursor.execute('DELETE FROM users')
            cursor.execute('DELETE FROM schedule')
            cursor.execute('DELETE FROM homework')
            cursor.execute('DELETE FROM important_events')
            conn.commit()

            bot.send_message(message.chat.id, "Все таблицы успешно очищены.")
        except Exception as e:
            bot.send_message(message.chat.id, f"Произошла ошибка при очистке базы данных: {e}")
    else:
        bot.send_message(message.chat.id, "У тебя нет прав для использования этой команды.")


def show_schedule_buttons(chatid, text):
    markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True)
    itembtn1 = types.KeyboardButton('Понедельник')
    itembtn2 = types.KeyboardButton('Вторник')
    itembtn3 = types.KeyboardButton('Среда')
    itembtn4 = types.KeyboardButton('Четверг')
    itembtn5 = types.KeyboardButton('Пятница')
    markup.add(itembtn1, itembtn2, itembtn3, itembtn4, itembtn5)
    
    bot.send_message(chatid, text, reply_markup=markup)

def add_schedule_day(day, message):
    if message.from_user.id not in admin_ids:
        bot.send_message(message.chat.id, "У тебя нет прав для выполнения этой команды.")
        return
    
    cursor.execute('DELETE FROM schedule WHERE day_of_week = ?', (day,))
    conn.commit()

    bot.send_message(message.chat.id, f"Ты заполняешь расписание на {day}. Введи название предмета или напиши 'стоп' для завершения.")
    bot.register_next_step_handler(message, lambda msg: ask_lesson_info(day, 1, msg))

def ask_lesson_info(day, lesson_number, message):
    if message.text.lower() == 'стоп':
        bot.send_message(message.chat.id, f"Заполнение расписания на {day} завершено.")
        return
    
    subject = message.text
    
    cursor.execute('SELECT subject FROM homework WHERE subject=?', (subject,))
    existing_subject = cursor.fetchone()

    if not existing_subject:
        cursor.execute('INSERT INTO homework (subject, homework) VALUES (?, ?)', (subject, 'Домашнее задание еще не задано'))
        conn.commit()
    
    bot.send_message(message.chat.id, f"Введи время начала урока {lesson_number} !!!(в формате ЧЧ:ММ)!!!:")
    bot.register_next_step_handler(message, lambda msg: ask_start_time(day, lesson_number, subject, msg))

def ask_start_time(day, lesson_number, subject, message):
    start_time = message.text
    bot.send_message(message.chat.id, f"Введи время окончания урока {lesson_number} !!!(в формате ЧЧ:ММ)!!!:")
    bot.register_next_step_handler(message, lambda msg: ask_end_time(day, lesson_number, subject, start_time, msg))

def ask_end_time(day, lesson_number, subject, start_time, message):
    end_time = message.text

    command = generate_command(subject)
    cursor.execute('''
        INSERT INTO schedule (day_of_week, lesson_number, subject, start_time, end_time, command)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (day, lesson_number, subject, start_time, end_time, command))
    conn.commit()

    bot.send_message(message.chat.id, f"Урок {lesson_number} ({subject}) добавлен в расписание на {day}.")
    bot.send_message(message.chat.id, "Введи следующий предмет или напиши 'стоп' для завершения.")
    bot.register_next_step_handler(message, lambda msg: ask_lesson_info(day, lesson_number + 1, msg))

@bot.message_handler(commands=['monday'])
def handle_monday(message):
    add_schedule_day('Monday', message)

@bot.message_handler(commands=['tuesday'])
def handle_tuesday(message):
    add_schedule_day('Tuesday', message)

@bot.message_handler(commands=['wednesday'])
def handle_wednesday(message):
    add_schedule_day('Wednesday', message)

@bot.message_handler(commands=['thursday'])
def handle_thursday(message):
    add_schedule_day('Thursday', message)

@bot.message_handler(commands=['friday'])
def handle_friday(message):
    add_schedule_day('Friday', message)

def ask_name(message):
    user_name = message.text
    user_id = message.from_user.id

    if re.match(r'^[^a-zA-Zа-яА-Я]', user_name):  
        bot.send_message(user_id, "Имя не должно начинаться с специальных символов или цифр. Пожалуйста, введи корректное имя:")
        bot.register_next_step_handler(message, ask_name)
        return

    cursor.execute('INSERT INTO users (user_id, name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET name=?', (user_id, user_name, user_name))
    conn.commit()
    
    bot.send_message(user_id, f"Приятно познакомиться, {user_name} 😉")
    bot.send_message(user_id, "Теперь скажи, когда у тебя день рождения? (в формате ДД.ММ.ГГГГ)")
    bot.register_next_step_handler_by_chat_id(user_id, ask_birthday)

def ask_birthday(message):
    user_birthday = message.text
    user_id = message.from_user.id
    
    date_pattern = r"^\d{2}\.\d{2}\.\d{4}$"

    if re.match(date_pattern, user_birthday):
        try:
            day, month, year = map(int, user_birthday.split('.'))
            date_valid = datetime.datetime(year, month, day)

            cursor.execute('UPDATE users SET birthday=? WHERE user_id=?', (user_birthday, user_id))
            conn.commit()

            show_schedule_buttons(user_id, "Отлично, запомнил!")
            bot.send_message(user_id, "На этом все, если захочешь изменить свои данные используй команду /register")
            bot.send_message(user_id, "Все доступные команды можешь посмотреть по команде /help")

        
        except ValueError:
            bot.send_message(user_id, "Некорректная дата. Пожалуйста, укажи правильную дату рождения в формате ДД.ММ.ГГГГ:")
            bot.register_next_step_handler(message, ask_birthday)
    
    else:
        bot.send_message(user_id, "Некорректный формат. Пожалуйста, укажи дату рождения в формате ДД.ММ.ГГГГ:")
        bot.register_next_step_handler(message, ask_birthday)

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    cursor.execute('SELECT name, birthday FROM users WHERE user_id=?', (user_id,))
    user = cursor.fetchone()

    if is_admin(user_id):
        full_commands = commands + admin_commands
    else:
        full_commands = commands

    bot.set_my_commands(full_commands, scope=types.BotCommandScopeChat(message.chat.id))
    if user:
        name, birthday = user
        
        if not name:
            show_schedule_buttons(user_id, "Для начала, как мне тебя называть?")
            bot.register_next_step_handler(message, ask_name)
        elif not birthday:
            bot.send_message(user_id, f"Привет, {name}! Я еще не знаю, когда у тебя день рождения.")
            bot.send_message(user_id, "Пожалуйста, укажи дату рождения в формате ДД.ММ.ГГГГ:")
            bot.register_next_step_handler_by_chat_id(user_id, ask_birthday)
        else:
            bot.send_message(user_id, f"С возвращением, {name}! Рад снова тебя видеть! 😊")
            show_schedule_buttons(user_id, "Чем могу быть полезен?")
    else:
        bot.send_message(user_id, "Привет! Я Beneki!👋")
        bot.send_message(user_id, "Что-то я тебя не припоминаю 🤔")
        bot.send_message(user_id, "Не беда, сейчас исправим")
        bot.send_message(user_id, "Для начала, как мне тебя называть?")
        bot.register_next_step_handler(message, ask_name)

    cursor.execute('INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username=?', (user_id, username, username))
    conn.commit()

@bot.message_handler(commands=['get_info'])
def get_user_info(message):
    user_id = message.from_user.id
    
    cursor.execute('SELECT name, birthday, username FROM users WHERE user_id=?', (user_id,))
    user = cursor.fetchone()
    
    if user:
        name, birthday, username = user
        response = f"Вот информация о тебе:\nИмя: {name or 'не указано'}\nДень рождения: {birthday or 'не указан'}\nНикнейм: @{username or 'не указан'}"
    else:
        response = "Я не нашел твоих данных. Попробуй зарегистрироваться снова с помощью команды /start."

    bot.send_message(user_id, response)

@bot.message_handler(commands=['register'])
def reregister(message):
    bot.send_message(message.chat.id, "Давай обновим твою информацию.")
    bot.send_message(message.chat.id, "Как мне тебя называть?")
    bot.register_next_step_handler(message, ask_name)


def add_important_event(start_date, end_date, event_text):
    cursor.execute('''
    INSERT INTO important_events (start_date, end_date, event_text)
    VALUES (?, ?, ?)
    ''', (start_date, end_date, event_text))
    conn.commit()

def delete_important_event(event_id):
    cursor.execute('''
    DELETE FROM important_events WHERE id=?
    ''', (event_id,))
    conn.commit()

def get_important_events():
    now = datetime.datetime.now(timezone).strftime('%Y-%m-%d')
    cursor.execute('SELECT * FROM important_events WHERE end_date >= ?', (now,))
    events = cursor.fetchall()
    return events

def remove_expired_events():
    now = datetime.datetime.now(timezone).strftime('%Y-%m-%d')
    cursor.execute('DELETE FROM important_events WHERE end_date < ?', (now,))
    conn.commit()

def send_important_events(user_id):
    events = get_important_events()
    if not events:
        return
    
    response = "📢 <b>Важные события:</b>\n\n"
    for event in events:
        response += f"🔹 {event[3]}\n"
    
    bot.send_message(user_id, response, parse_mode="HTML")

@bot.message_handler(commands=['help'])
def send_help(message: Message):
    user_id = message.from_user.id
    help_message = get_help_message(user_id)
    bot.send_message(message.chat.id, help_message)

schedule.every().day.at("00:05").do(remove_expired_events)

@bot.message_handler(func=lambda message: message.text in ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'])
def show_day_schedule(message):
    user_id = message.from_user.id
    days_translation = {
        'Понедельник': 'Monday',
        'Вторник': 'Tuesday',
        'Среда': 'Wednesday',
        'Четверг': 'Thursday',
        'Пятница': 'Friday'
    }
    
    day = days_translation[message.text]
    
    cursor.execute('SELECT lesson_number, subject, start_time, end_time, command FROM schedule WHERE day_of_week=? ORDER BY lesson_number', (day,))
    lessons = cursor.fetchall()
    
    if lessons:
        response = f"📅 <b>Расписание на {message.text}:</b>\n\n"
        for lesson_number, subject, start_time, end_time, command in lessons:
            response += f"🔹 <b>{lesson_number}</b>. <b>{subject}</b> {start_time} - {end_time}\n "
            response += f"   🔸 <i>Домашнее задание:</i> \n   {command}\n\n"
        bot.send_message(message.chat.id, response, parse_mode="HTML")
        send_important_events(user_id)
    else:
        bot.send_message(message.chat.id, f"🔹 На {message.text} пока нет расписания")
        send_important_events(user_id)


def check_schedule():
    now = datetime.datetime.now(timezone)  # Текущее время с временной зоной
    current_time = now.strftime("%H:%M")
    current_day = now.strftime("%A")

    local_cursor = conn.cursor()

    local_cursor.execute('SELECT id, lesson_number, start_time, end_time, subject, reminded FROM schedule WHERE day_of_week=?', (current_day,))
    lessons = local_cursor.fetchall()

    for lesson_id, lesson_number, start_time, end_time, subject, reminded in lessons:
        # Преобразуем start_time и end_time в datetime с временной зоной
        lesson_time = datetime.datetime.strptime(start_time, "%H:%M").replace(tzinfo=timezone)
        end_time_dt = datetime.datetime.strptime(end_time, "%H:%M").replace(tzinfo=timezone)

        # Задаем время для текущего дня
        lesson_time = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
        end_time_dt = now.replace(hour=end_time_dt.hour, minute=end_time_dt.minute, second=0, microsecond=0)

        if 0 <= (lesson_time - now).total_seconds() <= 300 and reminded == 0:
            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    bot.send_message(user_id, f"🟠Скоро начнется {subject}! Время начала {start_time}.")
                except TelegramError:
                    # Игнорируем пользователей, которые заблокировали бота
                    pass

            local_cursor.execute('UPDATE schedule SET reminded=1 WHERE id=?', (lesson_id,))
            conn.commit()

        if now >= lesson_time and now <= lesson_time + datetime.timedelta(minutes=1) and reminded == 1:
            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    bot.send_message(user_id, f"🔴Урок {subject} начался!")
                except TelegramError:
                    # Игнорируем пользователей, которые заблокировали бота
                    pass

            local_cursor.execute('UPDATE schedule SET reminded=2 WHERE id=?', (lesson_id,))
            conn.commit()

        if now >= end_time_dt and reminded == 2:
            local_cursor.execute('SELECT lesson_number, start_time, subject FROM schedule WHERE day_of_week=? AND lesson_number=?', (current_day, lesson_number + 1))
            next_lesson = local_cursor.fetchone()

            if next_lesson:
                next_lesson_number, next_start_time, next_subject = next_lesson

                # Преобразуем время следующего урока к datetime с временной зоной
                next_start_time_dt = datetime.datetime.strptime(next_start_time, "%H:%M").replace(tzinfo=timezone)

                # Проверка на случай, если следующий урок на следующий день
                if next_start_time_dt < end_time_dt:
                    next_start_time_dt += datetime.timedelta(days=1)

                # Подсчет перемены с использованием total_seconds
                break_duration = int((next_start_time_dt - end_time_dt).total_seconds() // 60)

                message = f"🟢Урок №{lesson_number} закончился!. Следующий урок ({next_subject}) начнется в {next_start_time}."
            else:
                message = f"🟢Урок №{lesson_number} закончился! Это был последний урок на сегодня."

            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    bot.send_message(user_id, message)
                except TelegramError:
                    # Игнорируем пользователей, которые заблокировали бота
                    pass

            local_cursor.execute('UPDATE schedule SET reminded=0 WHERE id=?', (lesson_id,))
            conn.commit()

schedule.every().second.do(check_schedule)

admin_id = 1341134928

@bot.message_handler(commands=['homework'])
def handle_homework(message):
    bot.send_message(message.chat.id, "Введи название урока:")
    bot.register_next_step_handler(message, get_homework)

def get_homework(message):
    subject = message.text

    cursor.execute('SELECT id, homework FROM homework WHERE subject=?', (subject,))
    lesson = cursor.fetchone()

    if lesson:
        lesson_id, existing_homework = lesson
        bot.send_message(message.chat.id, f"Введи текст домашнего задания для {subject}:")
        bot.register_next_step_handler(message, lambda msg: collect_homework_data(lesson_id, subject, msg))
    else:
        bot.send_message(message.chat.id, "Урок с таким названием не найден.")

def collect_homework_data(lesson_id, subject, message):
    user_id = message.from_user.id
    user_name = message.from_user.username
    homework = message.text  # Берем текст домашнего задания точно так, как его ввел пользователь

    bot.send_message(message.chat.id, "Отправь фото. Когда закончишь, напиши 'стоп' (если фото нет то просто напиши стоп)")
    bot.register_next_step_handler(message, lambda msg: collect_photos(lesson_id, subject, user_id, user_name, homework, [], msg))

def collect_photos(lesson_id, subject, user_id, user_name, homework, photo_ids, message):
    if message.text and message.text.lower() == 'стоп':
        # Отправляем домашнее задание админу на проверку
        send_homework_to_admin( subject, user_id, user_name, homework, photo_ids)
        bot.send_message(message.chat.id, "Домашнее задание отправлено на проверку.")
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        photo_ids.append(file_id)
        bot.send_message(message.chat.id, "Фото получено. Отправь еще одно или напиши 'стоп' для завершения.")

    bot.register_next_step_handler(message, lambda msg: collect_photos(lesson_id, subject, user_id, user_name, homework, photo_ids, msg))


def send_homework_to_admin(subject, user_id, user_name, homework_text, photo_ids):
    # Проверяем, если фото есть, объединяем их в строку
    photo_ids_str = ','.join(photo_ids) if photo_ids else None

    # Проверяем, существует ли уже запись для этого предмета
    cursor.execute('SELECT id FROM homework WHERE subject=?', (subject,))
    lesson = cursor.fetchone()

    if lesson:
        # Если запись существует, не обновляем сразу, а сохраняем данные для возможного обновления после одобрения
        lesson_id = lesson[0]
    else:
        # Если записи нет, добавляем новую
        cursor.execute('INSERT INTO homework (subject, homework, photo_ids) VALUES (?, ?, ?)', 
                       (subject, homework_text, photo_ids_str))
        lesson_id = cursor.lastrowid
        conn.commit()

    # Формируем сообщение для отправки админу
    homework_message = f"Новое домашнее задание\nПредмет: {subject}\nОтправитель: @{user_name} (ID: {user_id})\n\nТекст задания:\n{homework_text}"

    bot.send_message(admin_id, homework_message)

    # Отправляем фото админу, если они были добавлены
    if photo_ids:
        for file_id in photo_ids:
            bot.send_photo(admin_id, file_id)

    # Отправляем кнопки для одобрения/отклонения
    markup = types.InlineKeyboardMarkup()
    approve_button = types.InlineKeyboardButton("✅", callback_data=f"approve_{lesson_id}_{user_id}_{homework_text}_{photo_ids_str}")
    reject_button = types.InlineKeyboardButton("❌", callback_data=f"reject_{lesson_id}_{user_id}")
    markup.add(approve_button, reject_button)

    bot.send_message(admin_id, "Выберите действие:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve') or call.data.startswith('reject'))
def handle_admin_decision(call):
    if call.data.startswith('approve'):
        # Админ одобрил задание
        _, lesson_id, user_id, homework_text, photo_ids_str = call.data.split('_')
        approve_homework(lesson_id, int(user_id), homework_text, photo_ids_str, call.message)

    elif call.data.startswith('reject'):
        # Админ отклонил задание
        _, lesson_id, user_id = call.data.split('_')
        bot.send_message(call.message.chat.id, "Укажите причину отклонения:")
        bot.register_next_step_handler(call.message, lambda msg: reject_homework(lesson_id, int(user_id), msg, call.message))

def approve_homework(lesson_id, user_id, homework_text, photo_ids_str, admin_message):
    # Обновляем запись с новым домашним заданием, если она существует
    cursor.execute('UPDATE homework SET homework=?, photo_ids=? WHERE id=?', 
                   (homework_text, photo_ids_str, lesson_id))
    conn.commit()

    # Уведомляем пользователя об одобрении
    bot.send_message(admin_id, "✅Ты одобрил дз!")
    bot.send_message(user_id, "✅Твое домашнее задание одобрено")

def reject_homework(lesson_id, user_id, message, admin_message):
    reason = message.text

    # Уведомляем пользователя об отклонении и причине
    bot.send_message(user_id, f"❌Твое домашнее задание отклонено. \nПричина: {reason}")
    bot.send_message(admin_id, "❌Ты отклонил дз!")

@bot.message_handler(commands=['delete_homework'])
def handle_delete_homework(message):
    # Проверка, является ли пользователь администратором (например, по user_id)
    if message.from_user.id == admin_id:
        bot.send_message(message.chat.id, "Укажите ID домашнего задания для удаления:")
        bot.register_next_step_handler(message, delete_homework)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")

def delete_homework(message):
    try:
        # Получаем ID домашнего задания от пользователя
        homework_id = int(message.text)

        # Проверяем, существует ли домашнее задание с данным ID
        cursor.execute('SELECT * FROM homework WHERE id=?', (homework_id,))
        homework_data = cursor.fetchone()

        if homework_data:
            # Удаляем запись с указанным ID
            cursor.execute('DELETE FROM homework WHERE id=?', (homework_id,))
            conn.commit()

            bot.send_message(message.chat.id, f"Домашнее задание с ID {homework_id} успешно удалено.")
        else:
            bot.send_message(message.chat.id, "Запись с таким ID не найдена.")
    
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат ID. Введите числовое значение.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")
        
def reset_reminders():
    now = datetime.datetime.now(timezone)
    current_day = now.strftime("%A")
    
    if current_day == "Monday":
        local_cursor = conn.cursor()
        local_cursor.execute('UPDATE schedule SET reminded=0')
        conn.commit()
schedule.every().monday.at("00:01").do(reset_reminders)

def check_end_of_day():
    global schedule_sent_today 

    now = datetime.datetime.now(timezone)
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    days_translation = {
        'Monday': 'Понедельник',
        'Tuesday': 'Вторник',
        'Wednesday': 'Среда',
        'Thursday': 'Четверг',
        'Friday': 'Пятница',
        'Saturday': 'Суббота',
        'Sunday': 'Воскресенье'
    }
    
    if schedule_sent_today:
        return False  

    conn = sqlite3.connect('users.db')  
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT end_time FROM schedule WHERE day_of_week=? ORDER BY lesson_number DESC LIMIT 1', (current_day,))
        last_lesson = cursor.fetchone()

        if last_lesson:
            last_end_time = last_lesson[0]
            if current_time >= last_end_time: 
                next_day_eng = (now + datetime.timedelta(days=1)).strftime("%A")
                next_day_rus = days_translation[next_day_eng]

                cursor.execute('SELECT lesson_number, subject, start_time, end_time, command FROM schedule WHERE day_of_week=? ORDER BY lesson_number', (next_day_eng,))
                lessons_tomorrow = cursor.fetchall()
                
                cursor.execute('SELECT user_id FROM users')
                users = cursor.fetchall()

                for user_id, in users:
                    try:
                        if lessons_tomorrow:
                            response = f"📅 <b>Расписание на завтра ({next_day_rus}):</b>\n\n"
                            for lesson_number, subject, start_time, end_time, command in lessons_tomorrow:
                                response += f"🔹 <b>{lesson_number}</b>. <b>{subject}</b> {start_time} - {end_time}\n"
                                response += f"   🔸 <i>Домашнее задание:</i> \n   {command}\n\n"
                            
                            bot.send_message(user_id, response, parse_mode="HTML")
                            send_important_events(user_id)
                        else:
                            bot.send_message(user_id, "🔹 Поздравляю, завтра у тебя нет уроков!")
                            send_important_events(user_id)
                    
                    except TelegramError:
                        pass

                schedule_sent_today = True
                return True
    finally:
        cursor.close()
        conn.close()

    return False
def reset_schedule_flag():
    global schedule_sent_today
    schedule_sent_today = False

schedule.every().day.at("00:01").do(reset_schedule_flag)

schedule.every().minute.do(check_end_of_day)

def generate_command(subject_name):
    subject_name = subject_name.lower().replace(' ', '_') 
    subject_name = subject_name.replace('/', '_').replace('.', '_')  
    subject_name = transliterate.translit(subject_name, reversed=True)  
    command = f"/h_{subject_name}"
    return command


@bot.message_handler(func=lambda message: message.text.startswith('/h_'))
def handle_homework_command(message):
    command = message.text

    cursor.execute('SELECT subject FROM schedule WHERE command=?', (command,))
    subject_data = cursor.fetchone()

    if subject_data:
        subject = subject_data[0]

        cursor.execute('SELECT homework, photo_ids FROM homework WHERE subject=?', (subject,))
        homework_data = cursor.fetchone()

        if homework_data:
            homework, photo_ids = homework_data
            if photo_ids:
                photo_ids_list = photo_ids.split(',')
                media_group = []
                for photo_id in photo_ids_list:
                    media_group.append(types.InputMediaPhoto(photo_id, caption=homework if len(media_group) == 0 else ''))

                media_messages = bot.send_media_group(message.chat.id, media_group)
                media_message_ids = [media.message_id for media in media_messages]

                markup = types.InlineKeyboardMarkup()
                collapse_button = types.InlineKeyboardButton(
                    "Свернуть", 
                    callback_data=f'collapse_{message.message_id}_{",".join(map(str, media_message_ids))}'
                )
                markup.add(collapse_button)

                bot.send_message(message.chat.id, "Нажми что-бы свернуть", reply_markup=markup)
            else:
                markup = types.InlineKeyboardMarkup()
                collapse_button = types.InlineKeyboardButton(
                    "Свернуть", 
                    callback_data=f'collapse_{message.message_id}_{message.message_id}'
                )
                markup.add(collapse_button)
                bot.send_message(message.chat.id, homework, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, f"Домашнее задание для предмета {subject} не найдено.")
    else:
        bot.send_message(message.chat.id, f"Команда {command} не распознана. Возможно возникла ошибка при генерации команды.")


@bot.callback_query_handler(func=lambda call: call.data.startswith('collapse_'))
def handle_collapse_callback(call):

    data_parts = call.data.split('_')
    user_message_id = int(data_parts[1])
    message_ids = data_parts[2].split(',')

    try:
        bot.delete_message(call.message.chat.id, user_message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message to delete not found" not in str(e):
            raise

    for message_id in message_ids:
        try:
            bot.delete_message(call.message.chat.id, int(message_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message to delete not found" not in str(e):
                raise

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message to delete not found" not in str(e):
            raise
@bot.message_handler(commands=['add_event'])
def start_add_event(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    bot.send_message(message.chat.id, "Введи дату начала уведомлений (в формате ДД.ММ):")
    bot.register_next_step_handler(message, process_start_date)

def process_start_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        start_date_input = message.text.strip()
        start_date = datetime.strptime(start_date_input + f".{datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id] = {'start_date': start_date}
        bot.send_message(message.chat.id, "Введи дату окончания уведомлений (в формате ДД.ММ):")
        bot.register_next_step_handler(message, process_end_date)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_start_date)

def process_start_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        start_date_input = message.text.strip()
        start_date = datetime.datetime.strptime(start_date_input + f".{datetime.datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id] = {'start_date': start_date}
        bot.send_message(message.chat.id, "Введи дату окончания уведомлений (в формате ДД.ММ):")
        bot.register_next_step_handler(message, process_end_date)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_start_date)

def process_end_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        end_date_input = message.text.strip()
        end_date = datetime.datetime.strptime(end_date_input + f".{datetime.datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id]['end_date'] = end_date
        bot.send_message(message.chat.id, "Введи текст события:")
        bot.register_next_step_handler(message, process_event_text)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_end_date)


def process_event_text(message):
    if not is_admin(message.from_user.id):
        return

    try:
        event_text = message.text.strip()
        user_id = message.from_user.id
        
        start_date = user_data[user_id]['start_date']
        end_date = user_data[user_id]['end_date']

        add_important_event(start_date, end_date, event_text)
        
        bot.send_message(message.chat.id, "Событие успешно добавлено.")
        
        del user_data[user_id]
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")
        if user_id in user_data:
            del user_data[user_id]

@bot.message_handler(commands=['delete_event'])
def delete_event_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    try:
        event_id = int(message.text.split(' ')[1])
        delete_important_event(event_id)
        bot.reply_to(message, f"Событие с ID {event_id} удалено.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@bot.message_handler(commands=['list_events'])
def list_events_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    cursor.execute('SELECT id, start_date, end_date, event_text FROM important_events')
    events = cursor.fetchall()

    if events:
        response = "📅 <b>Важные события:</b>\n\n"
        for event in events:
            event_id, start_date, end_date, event_text = event
            response += f"🔹 <b>ID:</b> {event_id}\n   <b>Событие:</b> {event_text}\n   <b>С {start_date} по {end_date}</b>\n\n"
        bot.send_message(message.chat.id, response, parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "Нет запланированных событий.")

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)


scheduler_thread = threading.Thread(target=run_scheduler)
scheduler_thread.start()


@bot.message_handler(commands=['clear_chat'])
def clear_chat(message):
    chat_id = message.chat.id
    message_id = message.message_id

    markup = types.InlineKeyboardMarkup()
    yes_button = types.InlineKeyboardButton("✅Да, точно", callback_data="confirm_clear")
    no_button = types.InlineKeyboardButton("❌Нет, отменить", callback_data="cancel_clear")
    markup.add(yes_button, no_button)

    warning_message = bot.send_message(chat_id, 
        "Ты точно хочешь полностью очистить чат? Восстановить информацию будет невозможно.",
        reply_markup=markup
    )

    bot.clear_chat_context = {'message_id': message_id, 'warning_message_id': warning_message.message_id}

@bot.callback_query_handler(func=lambda call: call.data in ['confirm_clear', 'cancel_clear'])
def handle_clear_confirmation(call):
    chat_id = call.message.chat.id

    if call.data == 'confirm_clear':
        perform_clear_chat(chat_id, call.message)
    else:
        clear_chat_context = bot.clear_chat_context
        try:
            bot.delete_message(chat_id, clear_chat_context['warning_message_id'])
        except Exception:
            pass 

        try:
            bot.delete_message(chat_id, clear_chat_context['message_id'])
        except Exception:
            pass  

        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass  

def perform_clear_chat(chat_id, warning_message):
    deleted_messages = 0
    message_id = warning_message.message_id
    max_failures = 101
    failure_count = 0

    notification = bot.send_message(chat_id, "Очищаю чат, пожалуйста подожди, это может занять некоторое время...")

    while message_id > 0:
        try:
            if message_id != notification.message_id:
                bot.delete_message(chat_id, message_id)
                deleted_messages += 1
                failure_count = 0  
        except Exception:
            failure_count += 1
            if failure_count >= max_failures:
                break  
        message_id -= 1

    try:
        bot.delete_message(chat_id, notification.message_id)
    except Exception:
        pass  

    bot.send_message(chat_id, f"Чат очищен. Удалено сообщений: {deleted_messages}, напиши /start что-бы возобновить работу с ботом")
    bot.send_message(chat_id, f"Если некоторые сообщения все еще остались попробуй перезапустить команду")

days_mapping = {
    'Понедельник': 'Monday',
    'Вторник': 'Tuesday',
    'Среда': 'Wednesday',
    'Четверг': 'Thursday',
    'Пятница': 'Friday'
}

@bot.message_handler(commands=['edit_lesson'])
def edit_lesson(message: Message):
    if is_admin(message.from_user.id):
        # Создаем клавиатуру с днями недели на русском
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"edit_day_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_day_'))
def select_day(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]  # Получаем день недели на русском
    day_of_week_eng = days_mapping[day_of_week_rus]  # Преобразуем в английский
    bot.send_message(call.message.chat.id, f"Вы выбрали {day_of_week_rus}. Введите номер урока:")
    bot.register_next_step_handler(call.message, process_edit_lesson, day_of_week_eng)

def process_edit_lesson(message: Message, day_of_week):
    try:
        lesson_number = message.text
        bot.send_message(message.chat.id, "Введите предмет, время начала и конца (Пример: Физра 15:30 16:00):")
        bot.register_next_step_handler(message, finalize_edit_lesson, day_of_week, lesson_number)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

def finalize_edit_lesson(message: Message, day_of_week, lesson_number):
    try:
        data = message.text.split()
        if len(data) == 3:
            subject, start_time, end_time = data
            # Генерируем команду для ссылки на домашнее задание
            homework_link = generate_command(subject)
            
            cursor.execute('''
                UPDATE schedule
                SET subject = ?, start_time = ?, end_time = ?, command = ?
                WHERE day_of_week = ? AND lesson_number = ?
            ''', (subject, start_time, end_time, homework_link, day_of_week, lesson_number))
            conn.commit()
            bot.send_message(message.chat.id, f"Урок {lesson_number} на {day_of_week} изменён.")
        else:
            bot.send_message(message.chat.id, "Неправильный формат. Попробуйте снова.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

# 2. Удаление последнего урока на определённый день
@bot.message_handler(commands=['delete_last_lesson'])
def delete_last_lesson(message: Message):
    if is_admin(message.from_user.id):
        # Создаем клавиатуру с днями недели на русском
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"delete_last_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели для удаления последнего урока:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_last_'))
def process_delete_last_lesson(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]  # Получаем день недели на русском
    day_of_week_eng = days_mapping.get(day_of_week_rus)  # Преобразуем в английский
    if day_of_week_eng:
        try:
            cursor.execute('''
                SELECT MAX(lesson_number) FROM schedule WHERE day_of_week = ?
            ''', (day_of_week_eng,))
            last_lesson_number = cursor.fetchone()[0]
            if last_lesson_number:
                cursor.execute('''
                    DELETE FROM schedule WHERE day_of_week = ? AND lesson_number = ?
                ''', (day_of_week_eng, last_lesson_number))
                conn.commit()
                bot.send_message(call.message.chat.id, f"Последний урок номер {last_lesson_number} на {day_of_week_rus} удалён.")
            else:
                bot.send_message(call.message.chat.id, "Нет уроков на этот день.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"Ошибка: {str(e)}")
    else:
        bot.send_message(call.message.chat.id, "Неправильный день недели.")

# 3. Добавление нового урока в конец определённого дня
@bot.message_handler(commands=['add_lesson'])
def add_lesson(message: Message):
    if is_admin(message.from_user.id):
        # Создаем клавиатуру с днями недели на русском
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"add_lesson_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели для добавления нового урока:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.message_handler(commands=['add_lesson'])
def add_lesson(message: Message):
    if is_admin(message.from_user.id):
        # Создаем клавиатуру с днями недели на русском
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"add_lesson_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели для добавления нового урока:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_lesson_'))
def process_add_lesson(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]  # Получаем день недели на русском
    day_of_week_eng = days_mapping.get(day_of_week_rus)  # Преобразуем в английский
    if day_of_week_eng:
        bot.send_message(call.message.chat.id, "Введи предмет, время начала и конца (Пример: Физра 15:30 16:00):")
        bot.register_next_step_handler(call.message, finalize_add_lesson, day_of_week_eng)
    else:
        bot.send_message(call.message.chat.id, "Неправильный день недели.")

def finalize_add_lesson(message: Message, day_of_week):
    try:
        data = message.text.split()
        if len(data) == 3:
            subject, start_time, end_time = data
            
            # Генерируем ссылку на домашнее задание
            command = generate_command(subject)
            
            cursor.execute('''
                SELECT MAX(lesson_number) FROM schedule WHERE day_of_week = ?
            ''', (day_of_week,))
            last_lesson_number = cursor.fetchone()[0] or 0
            new_lesson_number = last_lesson_number + 1
            
            # Вставляем новый урок в базу данных с сгенерированной ссылкой
            cursor.execute('''
                INSERT INTO schedule (day_of_week, lesson_number, subject, start_time, end_time, command)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (day_of_week, new_lesson_number, subject, start_time, end_time, command))
            conn.commit()
            
            bot.send_message(message.chat.id, f"Новый урок добавлен в {day_of_week}: {subject} ({start_time} - {end_time})")
        else:
            bot.send_message(message.chat.id, "Неправильный формат. Попробуйте снова.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

def check_birthdays():
    today = datetime.now().strftime('%d-%m')  # Текущая дата в формате день-месяц
    cursor.execute("SELECT user_id, name FROM users WHERE birthday LIKE ?", (f'%{today}%',))
    users = cursor.fetchall()
    
    for user in users:
        user_id, name = user
        message = f'🎉 Поздравляю с Днем Рождения, {name}! 🎂 Желаю всего наилучшего! 🎉'
        bot.send_message(user_id, message)

# Планирование задачи на 8:20
schedule.every().day.at("08:20").do(check_birthdays)

def close_connection():
    conn.close()

atexit.register(close_connection)

bot.polling()