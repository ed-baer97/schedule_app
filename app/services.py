# app/services.py
from .models import db, Lesson, Teacher, Room, SubGroup, ClassSubjectRequirement, TeacherSubjectRequirement, Class, Subject # Добавлены Class, Subject

def check_teacher_conflict(teacher_id, day, lesson_number, exclude_lesson_id=None):
    """
    Проверяет, занят ли учитель в указанный день и время.
    Возвращает True, если конфликт есть.
    """
    query = db.session.query(Lesson).filter(
        Lesson.teacher_id == teacher_id,
        Lesson.day_of_week == day,
        Lesson.lesson_number == lesson_number
    )
    if exclude_lesson_id:
        query = query.filter(Lesson.id != exclude_lesson_id)
    return db.session.query(query.exists()).scalar()

def check_room_conflict(room_id, day, lesson_number, exclude_lesson_id=None):
    """
    Проверяет, занят ли кабинет в указанный день и время.
    Возвращает True, если конфликт есть.
    """
    query = db.session.query(Lesson).filter(
        Lesson.room_id == room_id,
        Lesson.day_of_week == day,
        Lesson.lesson_number == lesson_number
    )
    if exclude_lesson_id:
        query = query.filter(Lesson.id != exclude_lesson_id)
    return db.session.query(query.exists()).scalar()

def check_subgroup_conflict(subgroup_id, day, lesson_number, exclude_lesson_id=None):
    """
    Проверяет, занята ли подгруппа в указанный день и время.
    Возвращает True, если конфликт есть.
    """
    query = db.session.query(Lesson).filter(
        Lesson.subgroup_id == subgroup_id,
        Lesson.day_of_week == day,
        Lesson.lesson_number == lesson_number
    )
    if exclude_lesson_id:
        query = query.filter(Lesson.id != exclude_lesson_id)
    return db.session.query(query.exists()).scalar()

def check_class_subject_limit(class_id, subject_id, new_lesson_data=None, exclude_lesson_id=None):
    """
    Проверяет, не превышено ли количество уроков предмета в классе в неделю.
    Теперь проверяет ограничение для ПОДГРУППЫ на основе TeacherSubjectRequirement.
    new_lesson_data словарь с day_of_week, lesson_number, subgroup_id, room_id, teacher_id для нового/обновляемого урока.
                     Если None, проверяется только существующие уроки.
    exclude_lesson_id: ID урока, который нужно исключить из проверки (например, при обновлении).
    Возвращает (is_valid, [список ошибок]).
    """
    errors = []

    # Проверяем, переданы ли необходимые данные
    if new_lesson_data: # <-- ИСПРАВЛЕНО: было new_lesson_
        subgroup_id_to_check = new_lesson_data.get('subgroup_id')
        if not subgroup_id_to_check:
             return False, ["Невозможно проверить лимит: не указана подгруппа в новых данных урока."]
    elif exclude_lesson_id:
        # Если new_lesson_data нет, но exclude_lesson_id есть, получаем subgroup_id из существующего урока
        lesson_to_exclude = Lesson.query.get(exclude_lesson_id)
        if lesson_to_exclude:
            subgroup_id_to_check = lesson_to_exclude.subgroup_id
        else:
            return False, [f"Невозможно проверить лимит: урок с ID {exclude_lesson_id} не найден."]
    else:
        # Если нет ни new_lesson_data, ни exclude_lesson_id, проверить нечего
        return True, []

    # Находим требование по учителю, предмету, классу и ПОДГРУППЕ
    # Это определяет, сколько часов *должно быть* для этой подгруппы
    # ВАЖНО: Теперь это значение определяется логикой загрузки данных (см. app.py)
    requirement_for_subgroup = TeacherSubjectRequirement.query.filter_by(
        subject_id=subject_id,
        class_id=class_id,
        subgroup_id=subgroup_id_to_check
    ).first()

    if not requirement_for_subgroup:
        # Если для конкретной подгруппы нет требования (например, если подгруппа создана, но нагрузка не указана),
        # можно считать лимит равным 0 или использовать логику по умолчанию.
        # В текущей логике загрузки подразумевается, что если подгруппа есть, то и требование есть.
        # Но на всякий случай:
        # Для простоты, если нет требования для подгруппы, считаем лимит = 0.
        # Или можно использовать ClassSubjectRequirement, если это более подходящая логика.
        # В данном случае, будем считать, что если подгруппа существует в уроке, то и требование для неё должно быть.
        # Добавим предупреждение.
        print(f"Предупреждение: Не найдено TeacherSubjectRequirement для подгруппы {subgroup_id_to_check}, предмета {subject_id}, класса {class_id}.")
        # Пока оставим как было, но в идеале нужно убедиться, что требование всегда создаётся.
        # Попробуем использовать ClassSubjectRequirement как запасной вариант.
        class_requirement = ClassSubjectRequirement.query.filter_by(
            class_id=class_id, subject_id=subject_id
        ).first()
        if class_requirement:
             required_hours_for_subgroup = class_requirement.weekly_hours
        else:
             required_hours_for_subgroup = 0
    else:
        required_hours_for_subgroup = requirement_for_subgroup.teacher_weekly_hours


    # Считаем *уже созданные* уроки ТОЛЬКО для ЭТОЙ ПОДГРУППЫ по ЭТОМУ ПРЕДМЕТУ
    existing_lessons_query = db.session.query(Lesson).filter(
        Lesson.subject_id == subject_id,
        Lesson.subgroup_id == subgroup_id_to_check
    )

    if exclude_lesson_id:
        existing_lessons_query = existing_lessons_query.filter(Lesson.id != exclude_lesson_id)

    existing_lessons_count = existing_lessons_query.count()

    # Учитываем новый урок, если он передан и относится к той же подгруппе
    total_count_after_add = existing_lessons_count
    if new_lesson_data and new_lesson_data.get('subgroup_id') == subgroup_id_to_check:
        # Проверим, что new_lesson_data содержит все необходимые поля (повтор)
        if not all(k in new_lesson_data for k in ['day_of_week', 'lesson_number', 'subgroup_id', 'room_id', 'teacher_id']):
            return False, ["Недостаточно данных для проверки лимита часов."]

        # Считаем, что один урок в слоте = 1 час
        total_count_after_add += 1

    # Сравниваем *фактически созданные уроки* для ПОДГРУППЫ с *требуемым количеством часов для ПОДГРУППЫ*
    if total_count_after_add > required_hours_for_subgroup:
        # Получаем имена класса, подгруппы, предмета для сообщения
        class_obj = Class.query.get(class_id)
        subgroup_obj = SubGroup.query.get(subgroup_id_to_check)
        subject_obj = Subject.query.get(subject_id) # <-- ИСПОЛЬЗУЕТСЯ Subject
        class_name = class_obj.name if class_obj else 'N/A'
        subgroup_name = subgroup_obj.name if subgroup_obj else 'N/A'
        subject_name = subject_obj.name if subject_obj else 'N/A'
        errors.append(f"Превышен лимит уроков предмета '{subject_name}' для подгруппы '{subgroup_name}' класса '{class_name}' в неделю. Требуется: {required_hours_for_subgroup}, текущий/плановый счётчик: {total_count_after_add}.")

    return len(errors) == 0, errors


def validate_lesson(lesson_data, existing_lesson_id=None):
    """
    Проверяет, можно ли создать или изменить урок, не нарушая ограничений.
    lesson_data dict с ключами: subject_id, teacher_id, subgroup_id, room_id, day_of_week, lesson_number
    existing_lesson_id: ID урока, если происходит обновление (чтобы исключить его из проверки).
    Возвращает (is_valid, [список ошибок]).
    """
    errors = []

    # Получаем class_id из подгруппы
    subgroup = SubGroup.query.get(lesson_data['subgroup_id'])
    if not subgroup:
         errors.append(f"Подгруппа с ID {lesson_data['subgroup_id']} не найдена.")
         return False, errors

    class_id = subgroup.class_id # class_id, к которому принадлежит подгруппа

    # 1. Проверка на конфликт учителя
    if check_teacher_conflict(lesson_data['teacher_id'], lesson_data['day_of_week'], lesson_data['lesson_number'], exclude_lesson_id=existing_lesson_id):
        errors.append(f"Учитель ID {lesson_data['teacher_id']} уже занят в этот слот (день {lesson_data['day_of_week']}, урок {lesson_data['lesson_number']}).")

    # 2. Проверка на конфликт кабинета
    if check_room_conflict(lesson_data['room_id'], lesson_data['day_of_week'], lesson_data['lesson_number'], exclude_lesson_id=existing_lesson_id):
        errors.append(f"Кабинет ID {lesson_data['room_id']} уже занят в этот слот (день {lesson_data['day_of_week']}, урок {lesson_data['lesson_number']}).")

    # 3. Проверка на конфликт подгруппы (одна подгруппа не может быть в двух местах)
    if check_subgroup_conflict(lesson_data['subgroup_id'], lesson_data['day_of_week'], lesson_data['lesson_number'], exclude_lesson_id=existing_lesson_id):
        errors.append(f"Подгруппа ID {lesson_data['subgroup_id']} уже занята в этот слот (день {lesson_data['day_of_week']}, урок {lesson_data['lesson_number']}).")

    # 4. Проверка лимита часов для ПОДГРУППЫ-предмета
    # Передаём class_id, subject_id, и новое lesson_data. exclude_lesson_id используется для исключения при подсчёте.
    is_limit_valid, limit_errors = check_class_subject_limit(
        class_id, lesson_data['subject_id'], new_lesson_data=lesson_data, exclude_lesson_id=existing_lesson_id
    )
    if not is_limit_valid:
        errors.extend(limit_errors)

    return len(errors) == 0, errors

def get_subjects_for_class(class_id):
    """
    Возвращает список предметов, которые должны преподаваться в классе (с ненулевым количеством часов).
    """
    requirements = ClassSubjectRequirement.query.filter(
        ClassSubjectRequirement.class_id == class_id,
        ClassSubjectRequirement.weekly_hours > 0
    ).all()
    subject_ids = [req.subject_id for req in requirements]
    subjects = Subject.query.filter(Subject.id.in_(subject_ids)).all()
    return subjects

def get_teachers_for_class(class_id):
    """
    Возвращает список учителей, которые преподают в данном классе (имеют нагрузку).
    """
    # Получаем все TeacherSubjectRequirement для этого класса
    requirements = TeacherSubjectRequirement.query.filter_by(
        class_id=class_id
    ).all()
    teacher_ids = list(set([req.teacher_id for req in requirements])) # Убираем дубликаты
    teachers = Teacher.query.filter(Teacher.id.in_(teacher_ids)).all()
    return teachers

# --- НОВАЯ ФУНКЦИЯ ---
def get_teachers_for_class_and_subject(class_id, subject_id):
    """
    Возвращает список учителей, которые преподают определённый предмет в определённом классе.
    """
    print(f"DEBUG: Ищем учителей для class_id={class_id}, subject_id={subject_id}") # Отладочный вывод
    # Получаем все TeacherSubjectRequirement для этого класса и предмета
    requirements = TeacherSubjectRequirement.query.filter_by(
        class_id=class_id,
        subject_id=subject_id
    ).all()
    print(f"DEBUG: Найдено требований: {len(requirements)}") # Отладочный вывод
    for req in requirements:
        print(f"DEBUG: req.teacher_id={req.teacher_id}, req.subgroup_id={req.subgroup_id}") # Отладочный вывод
    teacher_ids = [req.teacher_id for req in requirements]
    # Убираем дубликаты, если вдруг есть несколько записей для одной подгруппы
    unique_teacher_ids = list(set(teacher_ids))
    print(f"DEBUG: Уникальные teacher_ids: {unique_teacher_ids}") # Отладочный вывод
    teachers = Teacher.query.filter(Teacher.id.in_(unique_teacher_ids)).all()
    print(f"DEBUG: Возвращаем учителей: {[t.name for t in teachers]}") # Отладочный вывод
    return teachers

# Пример функции для добавления урока с проверкой
def add_lesson(lesson_data):
    is_valid, errors = validate_lesson(lesson_data)
    if is_valid:
        new_lesson = Lesson(
            subject_id=lesson_data['subject_id'],
            teacher_id=lesson_data['teacher_id'],
            subgroup_id=lesson_data['subgroup_id'],
            day_of_week=lesson_data['day_of_week'],
            lesson_number=lesson_data['lesson_number'],
            room_id=lesson_data['room_id']
        )
        db.session.add(new_lesson)
        db.session.commit()
        return True, "Урок успешно добавлен"
    else:
        return False, errors

# Пример функции для изменения урока с проверкой
def update_lesson(lesson_id, lesson_data):
    lesson_to_update = Lesson.query.get(lesson_id)
    if not lesson_to_update:
        return False, f"Урок с ID {lesson_id} не найден."

    is_valid, errors = validate_lesson(lesson_data, existing_lesson_id=lesson_id)
    if is_valid:
        lesson_to_update.subject_id = lesson_data['subject_id']
        lesson_to_update.teacher_id = lesson_data['teacher_id']
        lesson_to_update.subgroup_id = lesson_data['subgroup_id']
        lesson_to_update.day_of_week = lesson_data['day_of_week']
        lesson_to_update.lesson_number = lesson_data['lesson_number']
        lesson_to_update.room_id = lesson_data['room_id']
        db.session.commit()
        return True, "Урок успешно обновлён"
    else:
        return False, errors

# Пример функции для удаления урока
def remove_lesson(lesson_id):
    lesson_to_remove = Lesson.query.get(lesson_id)
    if not lesson_to_remove:
        return False, f"Урок с ID {lesson_id} не найден."
    db.session.delete(lesson_to_remove)
    db.session.commit()
    return True, "Урок успешно удалён"