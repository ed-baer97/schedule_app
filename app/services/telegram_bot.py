"""
Утилита для работы с Telegram Bot API
"""
import requests
from flask import current_app
from datetime import datetime, date
from app.core.db_manager import db

DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

def send_telegram_message(telegram_id, message, parse_mode='HTML', school_id=None, bot_token=None):
    """
    Отправить сообщение в Telegram
    
    Args:
        telegram_id: ID пользователя Telegram (может быть числом или username с @)
        message: Текст сообщения
        parse_mode: Режим парсинга (HTML или Markdown)
        school_id: ID школы (опционально, для получения токена бота школы)
        bot_token: Токен бота напрямую (опционально, имеет приоритет над school_id)
    
    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        from flask import has_app_context
        if not has_app_context():
            print("Ошибка: нет контекста Flask приложения")
            return False
        
        # Определяем токен бота
        token = None
        
        # 1. Если передан bot_token напрямую, используем его
        if bot_token:
            token = bot_token
        # 2. Если передан school_id, пытаемся получить токен из БД школы
        elif school_id:
            from app.models.system import School
            school = School.query.get(school_id)
            if school and school.telegram_bot_token:
                token = school.telegram_bot_token
        
        # 3. Если токен не найден, используем общий токен из конфигурации
        if not token:
            token = current_app.config.get('TELEGRAM_BOT_TOKEN')
        
        if not token:
            print("TELEGRAM_BOT_TOKEN не настроен")
            return False
        
        api_url = current_app.config.get('TELEGRAM_API_URL', 'https://api.telegram.org/bot')
        url = f"{api_url}{token}/sendMessage"
        
        # Преобразуем telegram_id в правильный формат
        # Telegram API принимает числовой ID или строку (для username)
        if not telegram_id:
            print(f"Ошибка: telegram_id пустой")
            return False
        
        # Преобразуем telegram_id в правильный формат
        # Telegram API принимает:
        # - числовой ID (например: 123456789)
        # - username с @ (например: @username)
        # - username без @ (например: username) - Telegram API автоматически добавит @
        try:
            if isinstance(telegram_id, (int, float)):
                chat_id = int(telegram_id)
            elif isinstance(telegram_id, str):
                telegram_id_clean = telegram_id.strip()
                # Пытаемся преобразовать в число (обрабатываем и целые, и float в строковом формате)
                try:
                    # Сначала пытаемся преобразовать в float, затем в int
                    numeric_value = float(telegram_id_clean)
                    chat_id = int(numeric_value)
                except ValueError:
                    # Если не число, это username
                    # Telegram API требует username БЕЗ символа @
                    # Убираем @ если есть
                    if telegram_id_clean.startswith('@'):
                        chat_id = telegram_id_clean[1:]  # Убираем @
                    else:
                        chat_id = telegram_id_clean
                    print(f"📤 Отправка сообщения по username: {chat_id} (из {telegram_id})")
            else:
                chat_id = str(telegram_id)
        except (ValueError, TypeError) as e:
            print(f"Ошибка преобразования telegram_id '{telegram_id}': {e}")
            chat_id = str(telegram_id)
        
        print(f"📤 Попытка отправки сообщения chat_id: {chat_id} (тип: {type(chat_id).__name__})")
        
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': parse_mode
        }, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return True
            else:
                error_code = result.get('error_code', 'Unknown')
                error_desc = result.get('description', 'Unknown error')
                
                # Специальная обработка ошибок
                if error_code == 400:
                    if 'chat not found' in error_desc.lower():
                        print(f"⚠️ Telegram ID {chat_id}: Чат не найден. Учитель должен начать диалог с ботом (/start)")
                        print(f"   📝 Попросите учителя написать боту любое сообщение или /start")
                    elif 'user not found' in error_desc.lower() or 'username not found' in error_desc.lower():
                        print(f"⚠️ Telegram ID {chat_id}: Пользователь не найден. Проверьте правильность Telegram ID/username")
                        print(f"   📝 Убедитесь, что username существует и пользователь не заблокировал бота")
                    elif 'bad request' in error_desc.lower():
                        print(f"⚠️ Telegram ID {chat_id}: Неверный запрос - {error_desc}")
                        if '@' in str(chat_id):
                            print(f"   💡 Попробуйте использовать числовой ID вместо username")
                    else:
                        print(f"⚠️ Telegram ID {chat_id}: {error_desc}")
                elif error_code == 403:
                    print(f"⚠️ Telegram ID {chat_id}: Бот заблокирован пользователем")
                else:
                    print(f"⚠️ Telegram ID {chat_id}: Ошибка {error_code} - {error_desc}")
                
                return False
        else:
            print(f"⚠️ Ошибка отправки в Telegram: HTTP {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети при отправке в Telegram: {str(e)}")
        return False
    except Exception as e:
        print(f"Исключение при отправке в Telegram: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def format_schedule_for_teacher(teacher, shift_id=None, schedule_type='permanent', schedule_date=None):
    """
    Форматировать расписание учителя для отправки
    
    Args:
        teacher: Объект Teacher
        shift_id: ID смены (опционально, только для permanent)
        schedule_type: 'permanent' или 'temporary'
        schedule_date: Дата для временного расписания (обязательно для temporary)
    
    Returns:
        str: Отформатированное расписание
    """
    if schedule_type == 'permanent':
        return format_permanent_schedule(teacher, shift_id)
    else:
        # Для временного расписания нужна дата, а не shift_id
        if not schedule_date:
            schedule_date = date.today()
        return format_temporary_schedule(teacher, schedule_date)

def format_permanent_schedule(teacher, shift_id=None):
    """Форматировать постоянное расписание учителя"""
    from app.models.school import PermanentSchedule, Shift, ClassGroup, Subject
    
    if shift_id:
        schedule_items = db.session.query(PermanentSchedule).filter_by(
            teacher_id=teacher.id,
            shift_id=shift_id
        ).join(ClassGroup).join(Subject).order_by(
            PermanentSchedule.day_of_week,
            PermanentSchedule.lesson_number
        ).all()
    else:
        # Берем активную смену
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            return "❌ Нет активной смены"
        schedule_items = db.session.query(PermanentSchedule).filter_by(
            teacher_id=teacher.id,
            shift_id=active_shift.id
        ).join(ClassGroup).join(Subject).order_by(
            PermanentSchedule.day_of_week,
            PermanentSchedule.lesson_number
        ).all()
    
    if not schedule_items:
        return f"📅 <b>Расписание для {teacher.full_name}</b>\n\nРасписание пока не составлено."
    
    # Группируем по дням
    schedule_by_day = {}
    for item in schedule_items:
        day = item.day_of_week
        if day not in schedule_by_day:
            schedule_by_day[day] = []
        schedule_by_day[day].append(item)
    
    message = f"📅 <b>Расписание для {teacher.full_name}</b>\n\n"
    
    for day_num in sorted(schedule_by_day.keys()):
        day_name = DAYS[day_num - 1]
        message += f"<b>{day_name}:</b>\n"
        
        # Сортируем по номеру урока
        day_items = sorted(schedule_by_day[day_num], key=lambda x: x.lesson_number)
        
        for item in day_items:
            class_name = item.class_group.name
            subject_name = item.subject.name
            lesson_num = item.lesson_number
            cabinet = item.cabinet or "—"
            message += f"  {lesson_num}. {subject_name} - {class_name} (каб. {cabinet})\n"
        
        message += "\n"
    
    return message

def format_temporary_schedule(teacher, schedule_date=None):
    """Форматировать временное расписание учителя на дату
    
    Args:
        teacher: Объект Teacher
        schedule_date: Дата для временного расписания (если None, используется сегодняшняя дата)
    
    Returns:
        str или None: Отформатированное расписание или None, если нет расписания на эту дату
    """
    from app.models.school import TemporarySchedule, ClassGroup, Subject
    
    if not schedule_date:
        schedule_date = date.today()
    
    # Временное расписание не имеет поля shift_id, фильтруем только по дате и учителю
    schedule_items = db.session.query(TemporarySchedule).filter_by(
        teacher_id=teacher.id,
        date=schedule_date
    ).join(ClassGroup).join(Subject).order_by(
        TemporarySchedule.lesson_number
    ).all()
    
    if not schedule_items:
        return None  # Нет изменений на эту дату
    
    date_str = schedule_date.strftime('%d.%m.%Y')
    day_name = DAYS[schedule_date.weekday()] if schedule_date.weekday() < 7 else ''
    
    message = f"📢 <b>Изменения в расписании</b>\n\n"
    message += f"<b>Дата:</b> {date_str} ({day_name})\n"
    message += f"<b>Учитель:</b> {teacher.full_name}\n\n"
    message += "<b>Расписание на этот день:</b>\n"
    
    # Сортируем по номеру урока
    schedule_items = sorted(schedule_items, key=lambda x: x.lesson_number)
    
    for item in schedule_items:
        class_name = item.class_group.name
        subject_name = item.subject.name
        lesson_num = item.lesson_number
        cabinet = item.cabinet or "—"
        message += f"  {lesson_num}. {subject_name} - {class_name} (каб. {cabinet})\n"
    
    return message

def send_schedule_to_teacher(teacher, shift_id=None, school_id=None):
    """Отправить постоянное расписание учителю"""
    if not teacher or not teacher.telegram_id:
        return False
    
    # Получаем school_id из контекста, если не передан
    if not school_id:
        from flask import g, has_request_context
        if has_request_context():
            school_id = getattr(g, 'school_id', None)
        if not school_id:
            # Пытаемся получить из auth
            try:
                from app.core.auth import get_current_school_id
                school_id = get_current_school_id()
            except:
                pass
    
    try:
        message = format_permanent_schedule(teacher, shift_id)
        if not message:
            print(f"Не удалось сформировать сообщение для учителя {teacher.full_name}")
            return False
        return send_telegram_message(teacher.telegram_id, message, school_id=school_id)
    except Exception as e:
        print(f"Ошибка при отправке расписания учителю {teacher.full_name}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def send_temporary_changes_to_teacher(teacher, schedule_date, shift_id=None, school_id=None):
    """Отправить изменения из временного расписания учителю"""
    if not teacher.telegram_id:
        return False
    
    # Получаем school_id из контекста, если не передан
    if not school_id:
        from flask import g, has_request_context
        if has_request_context():
            school_id = getattr(g, 'school_id', None)
        if not school_id:
            # Пытаемся получить из auth
            try:
                from app.core.auth import get_current_school_id
                school_id = get_current_school_id()
            except:
                pass
    
    message = format_temporary_schedule(teacher, schedule_date)
    if message:
        return send_telegram_message(teacher.telegram_id, message, school_id=school_id)
    return False

def send_schedule_to_all_teachers(shift_id=None, school_id=None):
    """Отправить расписание всем учителям с уроками в постоянном расписании"""
    from app.models.school import Teacher, PermanentSchedule, Shift
    
    # Получаем school_id из контекста, если не передан
    if not school_id:
        from flask import g, has_request_context
        if has_request_context():
            school_id = getattr(g, 'school_id', None)
        if not school_id:
            # Пытаемся получить из auth
            try:
                from app.core.auth import get_current_school_id
                school_id = get_current_school_id()
            except:
                pass
    
    # Определяем смену
    if not shift_id:
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            return {'success': 0, 'failed': 0, 'errors': ['Нет активной смены']}
        shift_id = active_shift.id
    
    # Получаем учителей, у которых есть уроки в постоянном расписании для этой смены
    teachers_with_schedule = db.session.query(Teacher).join(
        PermanentSchedule, Teacher.id == PermanentSchedule.teacher_id
    ).filter(
        PermanentSchedule.shift_id == shift_id,
        Teacher.telegram_id.isnot(None)
    ).distinct().all()
    
    results = {'success': 0, 'failed': 0, 'errors': [], 'details': []}
    
    for teacher in teachers_with_schedule:
        if send_schedule_to_teacher(teacher, shift_id, school_id=school_id):
            results['success'] += 1
        else:
            results['failed'] += 1
            error_detail = f"{teacher.full_name}"
            if teacher.telegram_id:
                error_detail += f" (ID: {teacher.telegram_id})"
            else:
                error_detail += " (ID не указан)"
            results['errors'].append(error_detail)
            results['details'].append({
                'teacher': teacher.full_name,
                'telegram_id': teacher.telegram_id or 'не указан',
                'reason': 'Ошибка отправки'
            })
    
    return results

def send_temporary_changes_to_all_teachers(schedule_date, school_id=None):
    """Отправить изменения из временного расписания учителям, у которых есть уроки на эту дату
    
    Args:
        schedule_date: Дата для временного расписания
        school_id: ID школы (опционально, для получения токена бота школы)
    
    Returns:
        dict: Результаты отправки {'success': int, 'failed': int, 'no_changes': int, 'errors': list}
    """
    from app.models.school import Teacher, TemporarySchedule
    
    # Получаем school_id из контекста, если не передан
    if not school_id:
        from flask import g, has_request_context
        if has_request_context():
            school_id = getattr(g, 'school_id', None)
        if not school_id:
            # Пытаемся получить из auth
            try:
                from app.core.auth import get_current_school_id
                school_id = get_current_school_id()
            except:
                pass
    
    # Получаем учителей, у которых есть уроки во временном расписании на эту дату
    # Временное расписание не связано со сменой, поэтому shift_id не используется
    teachers_with_temporary = db.session.query(Teacher).join(
        TemporarySchedule, Teacher.id == TemporarySchedule.teacher_id
    ).filter(
        TemporarySchedule.date == schedule_date,
        Teacher.telegram_id.isnot(None)
    ).distinct().all()
    
    results = {'success': 0, 'failed': 0, 'no_changes': 0, 'errors': [], 'details': []}
    
    for teacher in teachers_with_temporary:
        # Временное расписание не связано со сменой, поэтому shift_id не используется
        message = format_temporary_schedule(teacher, schedule_date)
        if message:
            if send_telegram_message(teacher.telegram_id, message, school_id=school_id):
                results['success'] += 1
            else:
                results['failed'] += 1
                error_detail = f"{teacher.full_name}"
                if teacher.telegram_id:
                    error_detail += f" (ID: {teacher.telegram_id})"
                else:
                    error_detail += " (ID не указан)"
                results['errors'].append(error_detail)
                results['details'].append({
                    'teacher': teacher.full_name,
                    'telegram_id': teacher.telegram_id or 'не указан',
                    'reason': 'Ошибка отправки'
                })
        else:
            results['no_changes'] += 1
    
    return results

