# utils/prompt_db.py
"""
Утилита для работы с БД промпта
Создает и обновляет структуру: Класс -> Предмет -> Учителя
Определяет подгруппы: если в классе по предмету 2+ учителя, то has_subgroups = True
"""
from app.core.db_manager import db
from app.models.school import (
    ClassLoad, TeacherAssignment, PromptClassSubject, PromptClassSubjectTeacher,
    ClassGroup, Subject, Teacher, Shift
)


def build_prompt_database(shift_id, school_id=None):
    """
    Строит БД для промпта на основе ClassLoad и TeacherAssignment
    
    Структура данных для промпта:
    - Класс
    - В классе предмет
    - Количество часов этого предмета в этом классе (total_hours_per_week)
    - Список учителей, которые ведут этот предмет в этом классе
    - Если в данном классе и данном предмете 2+ учителя → has_subgroups = True (подгруппы)
    - Если в данном классе и данном предмете 1 учитель → has_subgroups = False (подгрупп нет)
    
    Важно: Подгруппы определяются для КАЖДОЙ пары (класс, предмет) отдельно.
    Два учителя могут вести один предмет, но в разных классах - в этих классах подгрупп нет.
    Подгруппы есть только там, где два учителя ведут один предмет в ОДНОМ классе.
    
    Args:
        shift_id: ID смены
        school_id: ID школы (опционально, для контекста БД)
    """
    # ВАЖНО: Эта функция должна вызываться внутри school_db_context!
    # Если school_id указан, убеждаемся что контекст установлен
    from flask import has_app_context, g, has_request_context
    if school_id and has_app_context():
        # Устанавливаем school_id в контекст Flask, если его там нет
        if has_request_context():
            if not hasattr(g, 'school_id') or g.school_id != school_id:
                from app.core.db_manager import switch_school_db
                switch_school_db(school_id)
                # Убеждаемся что school_id установлен в контексте
                g.school_id = school_id
        else:
            # Нет request context, но есть app context - устанавливаем bind напрямую
            from flask import current_app
            from app.core.db_manager import get_school_db_uri
            if 'SQLALCHEMY_BINDS' not in current_app.config:
                current_app.config['SQLALCHEMY_BINDS'] = {}
            current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(school_id)
    
    # Создаем таблицы, если их нет (checkfirst=True создаст только если не существуют)
    try:
        from flask import current_app
        # Убеждаемся что bind 'school' установлен в конфигурации
        if 'SQLALCHEMY_BINDS' not in current_app.config:
            current_app.config['SQLALCHEMY_BINDS'] = {}
        if 'school' not in current_app.config['SQLALCHEMY_BINDS']:
            # Если bind не установлен, но есть school_id, устанавливаем его
            if school_id:
                from app.core.db_manager import get_school_db_uri
                current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(school_id)
            elif has_app_context() and hasattr(g, 'school_id'):
                from app.core.db_manager import get_school_db_uri
                current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(g.school_id)
        
        engine = db.get_engine(current_app, bind='school')
        
        # Создаем таблицы с checkfirst=True (создаст только если не существуют)
        PromptClassSubject.__table__.create(engine, checkfirst=True)
        PromptClassSubjectTeacher.__table__.create(engine, checkfirst=True)
        print(f"✅ Таблицы БД промпта проверены/созданы")
    except Exception as e:
        print(f"⚠️ Ошибка при создании таблиц: {e}")
        import traceback
        traceback.print_exc()
    
    # Не очищаем старые данные, так как мы обновляем существующие записи
    # Это позволяет избежать блокировок БД и конфликтов UNIQUE constraint
    # Если запись больше не нужна, она просто не будет обновлена, что не критично
    
    # Получаем классы, назначенные этой смене (через ShiftClass)
    from app.models.school import ShiftClass
    
    # Создаем таблицу, если её нет
    try:
        from flask import current_app, g
        # Убеждаемся что bind 'school' установлен
        if 'SQLALCHEMY_BINDS' not in current_app.config:
            current_app.config['SQLALCHEMY_BINDS'] = {}
        if 'school' not in current_app.config['SQLALCHEMY_BINDS']:
            if school_id:
                from app.core.db_manager import get_school_db_uri
                current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(school_id)
            elif has_app_context() and hasattr(g, 'school_id'):
                from app.core.db_manager import get_school_db_uri
                current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(g.school_id)
        
        engine = db.get_engine(current_app, bind='school')
        ShiftClass.__table__.create(engine, checkfirst=True)
    except Exception as e:
        print(f"⚠️ Ошибка при создании таблицы shift_classes: {e}")
        # Продолжаем работу, используя обратную совместимость
    
    try:
        assigned_class_ids = set(
            sc.class_id for sc in db.session.query(ShiftClass).filter_by(shift_id=shift_id).all()
        )
        if assigned_class_ids:
            print(f"✅ Найдено {len(assigned_class_ids)} классов, назначенных смене {shift_id}")
        else:
            print(f"ℹ️ Для смены {shift_id} нет явно назначенных классов в ShiftClass")
    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ Ошибка при запросе shift_classes: {error_msg}")
        # Если ошибка связана с bind, это критично - не используем обратную совместимость
        if 'bind' in error_msg.lower() or 'sqlalchemy_binds' in error_msg.lower():
            print(f"❌ Критическая ошибка: bind 'school' не настроен. Убедитесь, что функция вызывается внутри school_db_context.")
            import traceback
            traceback.print_exc()
            raise  # Пробрасываем ошибку дальше
        import traceback
        traceback.print_exc()
        assigned_class_ids = set()
    
    # Если нет явно назначенных классов, используем все классы из ClassLoad (обратная совместимость)
    if not assigned_class_ids:
        print(f"ℹ️ Для смены {shift_id} нет явно назначенных классов, используем все классы из ClassLoad")
        assigned_class_ids = set(
            cl.class_id for cl in db.session.query(ClassLoad).filter_by(shift_id=shift_id).distinct(ClassLoad.class_id).all()
        )
    
    if not assigned_class_ids:
        print(f"⚠️ Для смены {shift_id} не найдено классов")
        return
    
    print(f"📊 Для смены {shift_id} найдено {len(assigned_class_ids)} классов")
    
    # Получаем все ClassLoad для этой смены, но только для назначенных классов
    # Используем no_autoflush, чтобы избежать блокировок при запросах во время накопления изменений
    with db.session.no_autoflush:
        class_loads = db.session.query(ClassLoad).filter_by(shift_id=shift_id).filter(
            ClassLoad.class_id.in_(assigned_class_ids)
        ).all()
    
    for class_load in class_loads:
        # Используем no_autoflush для всех запросов во время накопления изменений
        with db.session.no_autoflush:
            # Получаем все TeacherAssignment для этого класса и предмета
            teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                shift_id=shift_id,
                class_id=class_load.class_id,
                subject_id=class_load.subject_id
            ).all()
            
            if not teacher_assignments:
                # Если нет учителей, пропускаем
                continue
            
            # Определяем, есть ли подгруппы (2+ учителя)
            has_subgroups = len(teacher_assignments) >= 2
            
            # Проверяем, существует ли уже запись для этой комбинации
            prompt_class_subject = db.session.query(PromptClassSubject).filter_by(
                shift_id=shift_id,
                class_id=class_load.class_id,
                subject_id=class_load.subject_id
            ).first()
        
        if prompt_class_subject:
            # Обновляем существующую запись
            prompt_class_subject.total_hours_per_week = class_load.hours_per_week
            prompt_class_subject.has_subgroups = has_subgroups
            # Получаем существующих учителей для этой записи
            # Используем no_autoflush, чтобы избежать блокировок
            with db.session.no_autoflush:
                existing_teachers = db.session.query(PromptClassSubjectTeacher).filter_by(
                    prompt_class_subject_id=prompt_class_subject.id
                ).all()
        else:
            # Создаем новую запись
            prompt_class_subject = PromptClassSubject(
                shift_id=shift_id,
                class_id=class_load.class_id,
                subject_id=class_load.subject_id,
                total_hours_per_week=class_load.hours_per_week,
                has_subgroups=has_subgroups
            )
            db.session.add(prompt_class_subject)
            # Для новой записи учителей еще нет
            existing_teachers = []
        
        # Создаем словарь существующих учителей для быстрого поиска
        existing_teachers_dict = {t.teacher_id: t for t in existing_teachers}
        
        # Добавляем или обновляем учителей
        for assignment in teacher_assignments:
            existing_teacher = existing_teachers_dict.get(assignment.teacher_id)
            
            if existing_teacher:
                # Обновляем существующую запись
                existing_teacher.hours_per_week = assignment.hours_per_week or 0
                existing_teacher.default_cabinet = assignment.default_cabinet or ''
                # is_assigned_to_class остается без изменений
            else:
                # Создаем новую запись только если её еще нет
                is_assigned_to_class = False
                # TODO: Добавить логику определения is_assigned_to_class если нужно
                
                # Используем relationship для установки связи
                # SQLAlchemy автоматически установит правильный ID при commit
                prompt_teacher = PromptClassSubjectTeacher(
                    teacher_id=assignment.teacher_id,
                    hours_per_week=assignment.hours_per_week or 0,
                    default_cabinet=assignment.default_cabinet or '',
                    is_assigned_to_class=is_assigned_to_class
                )
                # Используем relationship для установки связи с классом-предметом
                # Это работает даже если prompt_class_subject.id еще None
                prompt_class_subject.teachers.append(prompt_teacher)
                # Добавляем в словарь, чтобы избежать дубликатов в этой транзакции
                existing_teachers_dict[assignment.teacher_id] = prompt_teacher
        
        # Не удаляем старых учителей, чтобы избежать блокировок БД
        # Лишние записи не будут использоваться, но это не критично
    
    # Сохраняем все изменения одним commit с обработкой блокировок
    max_retries = 3
    retry_delay = 0.1  # 100ms
    
    for attempt in range(max_retries):
        try:
            db.session.commit()
            print(f"✅ БД для промпта построена для смены {shift_id}")
            if school_id:
                print(f"   Школа: {school_id}")
            break  # Успешно закоммитили, выходим из цикла
        except Exception as e:
            error_str = str(e).lower()
            if 'locked' in error_str and attempt < max_retries - 1:
                # БД заблокирована, пробуем еще раз
                print(f"⚠️ БД заблокирована, попытка {attempt + 1}/{max_retries}, повтор через {retry_delay}s...")
                db.session.rollback()
                import time
                time.sleep(retry_delay)
                retry_delay *= 2  # Увеличиваем задержку для следующей попытки
            else:
                # Другая ошибка или последняя попытка
                print(f"❌ Ошибка при сохранении БД промпта: {e}")
                import traceback
                traceback.print_exc()
                db.session.rollback()
                raise  # Пробрасываем ошибку дальше


def get_prompt_structure(shift_id, school_id=None, use_ids_only=False, normalize_class_ids=True):
    """
    Получает структуру данных для промпта в формате, используемом в api.py
    
    Args:
        shift_id: ID смены
        school_id: ID школы (опционально)
        use_ids_only: Если True, возвращает только ID без имен (для оптимизации объема токенов)
        normalize_class_ids: Если True, нормализует class_id (первый класс = 1, второй = 2 и т.д.)
    
    Returns:
        tuple: (list, dict) где:
        - list: Список словарей с структурой:
        [
            {
                'class_id': int (нормализованный, если normalize_class_ids=True),
                'class_name': str (только если use_ids_only=False),
                'subject_id': int,
                'subject_name': str (только если use_ids_only=False),
                'total_hours_per_week': int,
                'has_subgroups': bool,
                'teachers': [
                    {
                        'teacher_id': int,
                        'teacher_name': str (только если use_ids_only=False),
                        'hours_per_week': int,
                        'default_cabinet': str,
                        'is_assigned_to_class': bool
                    }
                ]
            }
        ]
        - dict: Маппинг нормализованных ID в реальные:
        {
            'normalized_to_real': {нормализованный_id: реальный_id},
            'real_to_normalized': {реальный_id: нормализованный_id}
        }
    """
    # Переключаемся на БД школы, если указана
    # Если school_id=None, предполагаем, что мы уже в правильном контексте (school_db_context)
    if school_id:
        from flask import has_app_context
        if has_app_context():
            from app.core.db_manager import switch_school_db
            switch_school_db(school_id)
    
    # Создаем таблицы, если их нет (на случай, если они еще не созданы)
    try:
        from flask import current_app
        engine = db.get_engine(current_app, bind='school')
        PromptClassSubject.__table__.create(engine, checkfirst=True)
        PromptClassSubjectTeacher.__table__.create(engine, checkfirst=True)
    except Exception as e:
        print(f"⚠️ Ошибка при проверке таблиц в get_prompt_structure: {e}")
        import traceback
        traceback.print_exc()
    
    # Получаем классы, назначенные этой смене, для нормализации ID
    from app.models.school import ShiftClass
    assigned_class_ids = set()
    try:
        assigned_class_ids = set(
            sc.class_id for sc in db.session.query(ShiftClass).filter_by(shift_id=shift_id).all()
        )
    except Exception:
        pass
    
    # Если нет явно назначенных классов, используем все из PromptClassSubject
    if not assigned_class_ids:
        try:
            assigned_class_ids = set(
                pcs.class_id for pcs in db.session.query(PromptClassSubject).filter_by(shift_id=shift_id).distinct(PromptClassSubject.class_id).all()
            )
        except Exception:
            pass
    
    # Создаем маппинг нормализованных ID
    class_id_mapping = {'normalized_to_real': {}, 'real_to_normalized': {}}
    if normalize_class_ids and assigned_class_ids:
        from utils.id_normalizer import create_class_id_mapping
        normalized_to_real, real_to_normalized = create_class_id_mapping(assigned_class_ids)
        class_id_mapping = {
            'normalized_to_real': normalized_to_real,
            'real_to_normalized': real_to_normalized
        }
        print(f"📊 Нормализация class_id: {len(assigned_class_ids)} классов, первый класс = 1")
    
    # Получаем все PromptClassSubject для этой смены
    try:
        prompt_class_subjects = db.session.query(PromptClassSubject).filter_by(
            shift_id=shift_id
        ).all()
    except Exception as e:
        print(f"⚠️ Ошибка при запросе PromptClassSubject: {e}")
        import traceback
        traceback.print_exc()
        return ([], class_id_mapping) if normalize_class_ids else []
    
    result = []
    
    for pcs in prompt_class_subjects:
        # Получаем класс и предмет
        class_group = db.session.query(ClassGroup).filter_by(id=pcs.class_id).first()
        subject = db.session.query(Subject).filter_by(id=pcs.subject_id).first()
        
        if not class_group or not subject:
            continue
        
        # Нормализуем class_id, если нужно
        normalized_class_id = pcs.class_id
        if normalize_class_ids and class_id_mapping.get('real_to_normalized'):
            normalized_class_id = class_id_mapping['real_to_normalized'].get(pcs.class_id, pcs.class_id)
        
        # Получаем учителей
        teachers = []
        for pcs_teacher in pcs.teachers:
            teacher_data = {
                'teacher_id': pcs_teacher.teacher_id,
                'hours_per_week': pcs_teacher.hours_per_week,
                'default_cabinet': pcs_teacher.default_cabinet or '',
                'is_assigned_to_class': pcs_teacher.is_assigned_to_class
            }
            if not use_ids_only:
                teacher = db.session.query(Teacher).filter_by(id=pcs_teacher.teacher_id).first()
                if teacher:
                    teacher_data['teacher_name'] = teacher.full_name
            teachers.append(teacher_data)
        
        item = {
            'class_id': normalized_class_id,  # Используем нормализованный ID
            'subject_id': subject.id,
            'total_hours_per_week': pcs.total_hours_per_week,
            'has_subgroups': pcs.has_subgroups,
            'teachers': teachers
        }
        if not use_ids_only:
            item['class_name'] = class_group.name
            item['subject_name'] = subject.name
        
        result.append(item)
    
    if normalize_class_ids:
        return result, class_id_mapping
    else:
        return result


def update_prompt_database(shift_id, school_id=None):
    """
    Обновляет БД для промпта (пересоздает на основе текущих данных)
    """
    build_prompt_database(shift_id, school_id)


def get_class_subject_info(class_id, subject_id, shift_id, school_id=None):
    """
    Получает информацию о классе и предмете для промпта
    
    Returns:
        dict: Информация о классе и предмете с учителями
    """
    # Переключаемся на БД школы, если указана
    if school_id:
        from app.core.db_manager import switch_school_db
        switch_school_db(school_id)
    
    pcs = db.session.query(PromptClassSubject).filter_by(
        shift_id=shift_id,
        class_id=class_id,
        subject_id=subject_id
    ).first()
    
    if not pcs:
        return None
    
    class_group = db.session.query(ClassGroup).filter_by(id=class_id).first()
    subject = db.session.query(Subject).filter_by(id=subject_id).first()
    
    teachers = []
    for pcs_teacher in pcs.teachers:
        teacher = db.session.query(Teacher).filter_by(id=pcs_teacher.teacher_id).first()
        if teacher:
            teachers.append({
                'teacher_id': teacher.id,
                'teacher_name': teacher.full_name,
                'hours_per_week': pcs_teacher.hours_per_week,
                'default_cabinet': pcs_teacher.default_cabinet or '',
                'is_assigned_to_class': pcs_teacher.is_assigned_to_class
            })
    
    return {
        'class_id': class_group.id,
        'class_name': class_group.name,
        'subject_id': subject.id,
        'subject_name': subject.name,
        'total_hours_per_week': pcs.total_hours_per_week,
        'has_subgroups': pcs.has_subgroups,
        'teachers': teachers
    }

