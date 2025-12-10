# app/services/prompt_db.py
"""
Утилита для работы с БД промпта
Создает и обновляет структуру: Класс -> Предмет -> Учителя
Определяет подгруппы: если в классе по предмету 2+ учителя, то has_subgroups = True
"""
from app.core.db_manager import db, switch_school_db
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
    # Переключаемся на БД школы, если указана
    # Если school_id=None, предполагаем, что мы уже в правильном контексте (school_db_context)
    if school_id:
        from flask import has_app_context
        if has_app_context():
            switch_school_db(school_id)
    
    # Создаем таблицы, если их нет (checkfirst=True создаст только если не существуют)
    try:
        from flask import current_app
        engine = db.get_engine(current_app, bind='school')
        
        # Создаем таблицы с checkfirst=True (создаст только если не существуют)
        PromptClassSubject.__table__.create(engine, checkfirst=True)
        PromptClassSubjectTeacher.__table__.create(engine, checkfirst=True)
        print(f"✅ Таблицы БД промпта проверены/созданы")
    except Exception as e:
        print(f"⚠️ Ошибка при создании таблиц: {e}")
        import traceback
        traceback.print_exc()
    
    # Очищаем старые данные для этой смены
    try:
        PromptClassSubjectTeacher.query.filter(
            PromptClassSubjectTeacher.prompt_class_subject_id.in_(
                db.session.query(PromptClassSubject.id).filter_by(shift_id=shift_id)
            )
        ).delete(synchronize_session=False)
        
        PromptClassSubject.query.filter_by(shift_id=shift_id).delete()
        db.session.commit()
    except Exception as e:
        # Если таблиц нет, просто продолжаем (они уже созданы выше)
        print(f"⚠️ Ошибка при очистке старых данных: {e}")
        db.session.rollback()
    
    # Получаем все ClassLoad для этой смены
    class_loads = db.session.query(ClassLoad).filter_by(shift_id=shift_id).all()
    
    for class_load in class_loads:
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
        
        # Создаем или обновляем PromptClassSubject
        prompt_class_subject = PromptClassSubject(
            shift_id=shift_id,
            class_id=class_load.class_id,
            subject_id=class_load.subject_id,
            total_hours_per_week=class_load.hours_per_week,
            has_subgroups=has_subgroups
        )
        db.session.add(prompt_class_subject)
        db.session.flush()
        
        # Добавляем учителей
        for assignment in teacher_assignments:
            # Проверяем, закреплен ли учитель за классом
            # (это можно определить из teacher_classes таблицы или других источников)
            is_assigned_to_class = False
            # TODO: Добавить логику определения is_assigned_to_class если нужно
            
            prompt_teacher = PromptClassSubjectTeacher(
                prompt_class_subject_id=prompt_class_subject.id,
                teacher_id=assignment.teacher_id,
                hours_per_week=assignment.hours_per_week or 0,
                default_cabinet=assignment.default_cabinet or '',
                is_assigned_to_class=is_assigned_to_class
            )
            db.session.add(prompt_teacher)
    
    try:
        db.session.commit()
        print(f"✅ БД для промпта построена для смены {shift_id}")
        if school_id:
            print(f"   Школа: {school_id}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении БД промпта: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        raise  # Пробрасываем ошибку дальше


def get_prompt_structure(shift_id, school_id=None, use_ids_only=False):
    """
    Получает структуру данных для промпта в формате, используемом в api.py
    
    Args:
        shift_id: ID смены
        school_id: ID школы (опционально)
        use_ids_only: Если True, возвращает только ID без имен (для оптимизации объема токенов)
    
    Returns:
        list: Список словарей с структурой:
        [
            {
                'class_id': int,
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
    """
    # Переключаемся на БД школы, если указана
    # Если school_id=None, предполагаем, что мы уже в правильном контексте (school_db_context)
    if school_id:
        from flask import has_app_context
        if has_app_context():
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
    
    # Получаем все PromptClassSubject для этой смены
    try:
        prompt_class_subjects = db.session.query(PromptClassSubject).filter_by(
            shift_id=shift_id
        ).all()
    except Exception as e:
        print(f"⚠️ Ошибка при запросе PromptClassSubject: {e}")
        import traceback
        traceback.print_exc()
        return []  # Возвращаем пустой список при ошибке
    
    result = []
    
    for pcs in prompt_class_subjects:
        # Получаем класс и предмет
        class_group = db.session.query(ClassGroup).filter_by(id=pcs.class_id).first()
        subject = db.session.query(Subject).filter_by(id=pcs.subject_id).first()
        
        if not class_group or not subject:
            continue
        
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
            'class_id': class_group.id,
            'subject_id': subject.id,
            'total_hours_per_week': pcs.total_hours_per_week,
            'has_subgroups': pcs.has_subgroups,
            'teachers': teachers
        }
        if not use_ids_only:
            item['class_name'] = class_group.name
            item['subject_name'] = subject.name
        
        result.append(item)
    
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

