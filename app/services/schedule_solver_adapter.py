"""
Адаптер для преобразования данных из БД в формат для алгоритма составления расписания
"""
from typing import List, Dict, Set, Tuple
from collections import defaultdict
import logging

from app.core.db_manager import db
from app.models.school import (
    PromptClassSubject, PromptClassSubjectTeacher, ScheduleSettings,
    PermanentSchedule, Shift, Cabinet, ShiftClass, Subject, ClassGroup,
    Teacher, CabinetTeacher, TeacherAssignment, ClassLoad
)
from app.services.schedule_solver import ClassSubjectRequirement, LessonSlot

logger = logging.getLogger(__name__)


def get_available_cabinets_for_teacher(
    teacher_id: int,
    subject_id: int,
    default_cabinet: str = '',
    has_subgroups: bool = False
) -> List[Dict]:
    """
    Получает список доступных кабинетов для учителя с приоритетами
    
    Приоритеты:
    1. Кабинет, закрепленный за учителем через CabinetTeacher
    2. Кабинет по умолчанию из TeacherAssignment.default_cabinet
    3. Кабинет, привязанный к предмету
    4. Любой свободный кабинет
    
    Args:
        teacher_id: ID учителя
        subject_id: ID предмета
        default_cabinet: Кабинет по умолчанию
        has_subgroups: Есть ли подгруппы (для проверки subgroups_only)
    
    Returns:
        Список словарей с информацией о кабинетах:
        [{'name': '101', 'priority': 1, 'cabinet_id': 1}, ...]
    """
    cabinets = []
    
    # Приоритет 1: Кабинет, закрепленный за учителем
    cabinet_teachers = db.session.query(CabinetTeacher).filter_by(
        teacher_id=teacher_id
    ).all()
    
    for ct in cabinet_teachers:
        cabinet = db.session.query(Cabinet).filter_by(id=ct.cabinet_id).first()
        if cabinet:
            # Проверяем ограничения кабинета
            if cabinet.subgroups_only and not has_subgroups:
                continue
            if cabinet.exclusive_to_subject and cabinet.subject_id != subject_id:
                continue
            
            cabinets.append({
                'name': cabinet.name,
                'priority': 1,
                'cabinet_id': cabinet.id,
                'max_classes_simultaneously': cabinet.max_classes_simultaneously or 1,
                'subgroups_only': bool(cabinet.subgroups_only),
                'exclusive_to_subject': bool(cabinet.exclusive_to_subject),
                'subject_id': cabinet.subject_id
            })
    
    # Приоритет 2: Кабинет по умолчанию из TeacherAssignment
    if default_cabinet:
        cabinet = db.session.query(Cabinet).filter_by(name=default_cabinet).first()
        if cabinet:
            # Проверяем, не добавлен ли уже
            if not any(c['name'] == default_cabinet for c in cabinets):
                # Проверяем ограничения
                if not (cabinet.subgroups_only and not has_subgroups):
                    if not (cabinet.exclusive_to_subject and cabinet.subject_id != subject_id):
                        cabinets.append({
                            'name': cabinet.name,
                            'priority': 2,
                            'cabinet_id': cabinet.id,
                            'max_classes_simultaneously': cabinet.max_classes_simultaneously or 1,
                            'subgroups_only': bool(cabinet.subgroups_only),
                            'exclusive_to_subject': bool(cabinet.exclusive_to_subject),
                            'subject_id': cabinet.subject_id
                        })
    
    # Приоритет 3: Кабинет, привязанный к предмету
    subject_cabinets = db.session.query(Cabinet).filter_by(
        subject_id=subject_id
    ).all()
    
    for cabinet in subject_cabinets:
        # Проверяем, не добавлен ли уже
        if not any(c['name'] == cabinet.name for c in cabinets):
            # Проверяем ограничения
            if not (cabinet.subgroups_only and not has_subgroups):
                cabinets.append({
                    'name': cabinet.name,
                    'priority': 3,
                    'cabinet_id': cabinet.id,
                    'max_classes_simultaneously': cabinet.max_classes_simultaneously or 1,
                    'subgroups_only': bool(cabinet.subgroups_only),
                    'exclusive_to_subject': bool(cabinet.exclusive_to_subject),
                    'subject_id': cabinet.subject_id
                })
    
    # Приоритет 4: Любой свободный кабинет (без ограничений)
    all_cabinets = db.session.query(Cabinet).all()
    for cabinet in all_cabinets:
        # Пропускаем кабинеты с ограничениями
        if cabinet.subgroups_only and not has_subgroups:
            continue
        if cabinet.exclusive_to_subject and cabinet.subject_id != subject_id:
            continue
        
        # Проверяем, не добавлен ли уже
        if not any(c['name'] == cabinet.name for c in cabinets):
            cabinets.append({
                'name': cabinet.name,
                'priority': 4,
                'cabinet_id': cabinet.id,
                'max_classes_simultaneously': cabinet.max_classes_simultaneously or 1,
                'subgroups_only': bool(cabinet.subgroups_only),
                'exclusive_to_subject': bool(cabinet.exclusive_to_subject),
                'subject_id': cabinet.subject_id
            })
    
    # Сортируем по приоритету
    cabinets.sort(key=lambda x: x['priority'])
    
    return cabinets


def load_requirements_from_db(shift_id: int) -> List[ClassSubjectRequirement]:
    """
    Загружает требования для составления расписания из БД
    
    ВАЖНО: Эта функция должна вызываться внутри school_db_context!
    
    Args:
        shift_id: ID смены
    
    Returns:
        Список требований ClassSubjectRequirement
    """
    # Проверяем, что bind 'school' настроен
    from flask import current_app, has_app_context
    if not has_app_context():
        raise RuntimeError("load_requirements_from_db требует активный app context. Используйте school_db_context.")
    
    binds = current_app.config.get('SQLALCHEMY_BINDS', {})
    if 'school' not in binds:
        error_msg = (
            f"Bind 'school' не настроен в SQLALCHEMY_BINDS. "
            f"Текущая конфигурация: {list(binds.keys())}. "
            f"Убедитесь, что вы вызываете эту функцию внутри school_db_context(school_id)."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    requirements = []
    
    try:
        # Получаем все класс-предмет пары для смены
        class_subjects = db.session.query(PromptClassSubject).filter_by(
            shift_id=shift_id
        ).all()
    except Exception as e:
        error_msg = f"Ошибка при загрузке prompt_class_subjects: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        raise RuntimeError(error_msg) from e
    
    logger.info(f"Найдено class_subjects (prompt_class_subjects) для смены {shift_id}: {len(class_subjects)}")
    
    # Проверяем альтернативный источник - TeacherAssignment
    try:
        teacher_assignments_count = db.session.query(TeacherAssignment).filter_by(
            shift_id=shift_id
        ).count()
        logger.info(f"Найдено teacher_assignments для смены {shift_id}: {teacher_assignments_count}")
    except Exception as e:
        logger.error(f"Ошибка при проверке teacher_assignments: {str(e)}")
        teacher_assignments_count = 0
    
    # Если нет данных в prompt_class_subjects, используем teacher_assignments
    if len(class_subjects) == 0 and teacher_assignments_count > 0:
        logger.info(f"Нет данных в prompt_class_subjects, используем teacher_assignments как основной источник")
        return _load_requirements_from_teacher_assignments(shift_id)
    
    for cs_idx, cs in enumerate(class_subjects):
        logger.debug(f"Обработка class_subject #{cs_idx}: id={cs.id}, class_id={cs.class_id}, subject_id={cs.subject_id}, total_hours={cs.total_hours_per_week}")
        # Получаем учителей для этого класса и предмета
        teachers_data = db.session.query(PromptClassSubjectTeacher).filter_by(
            prompt_class_subject_id=cs.id
        ).all()
        
        logger.debug(f"Загрузка требования: class_id={cs.class_id}, subject_id={cs.subject_id}, prompt_class_subject_id={cs.id}")
        logger.debug(f"Найдено учителей в prompt_class_subject_teachers: {len(teachers_data)}")
        
        # Если нет учителей в prompt_class_subject_teachers, пробуем загрузить из teacher_assignments
        use_teacher_assignments = len(teachers_data) == 0
        if use_teacher_assignments:
            logger.info(f"Нет учителей в prompt_class_subject_teachers для class_id={cs.class_id}, subject_id={cs.subject_id}")
            logger.info(f"Пробуем загрузить из teacher_assignments...")
            
            teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                shift_id=shift_id,
                class_id=cs.class_id,
                subject_id=cs.subject_id
            ).all()
            
            if teacher_assignments:
                logger.info(f"Найдено {len(teacher_assignments)} назначений в teacher_assignments")
                teachers_data = teacher_assignments
            else:
                logger.warning(f"Нет данных и в teacher_assignments, пропускаем это требование")
                continue
        
        teachers = []
        for t_idx, t in enumerate(teachers_data):
            if use_teacher_assignments:
                # Данные из TeacherAssignment
                teacher_id = t.teacher_id
                hours = t.hours_per_week or 0
                default_cabinet_raw = t.default_cabinet or ''
                is_assigned = False
            else:
                # Данные из PromptClassSubjectTeacher
                teacher_id = t.teacher_id
                hours = t.hours_per_week or 0
                default_cabinet_raw = t.default_cabinet or ''
                is_assigned = t.is_assigned_to_class or False
            
            logger.debug(f"Обработка учителя #{t_idx} из БД:")
            logger.debug(f"  teacher_id: {teacher_id} (type: {type(teacher_id)})")
            logger.debug(f"  hours_per_week: {hours} (type: {type(hours)})")
            logger.debug(f"  default_cabinet: {default_cabinet_raw}")
            logger.debug(f"  Источник: {'teacher_assignments' if use_teacher_assignments else 'prompt_class_subject_teachers'}")
            
            # Проверяем, что hours_per_week не None и не 0
            if hours is None:
                logger.error(f"  ОШИБКА: hours_per_week = None для teacher_id={teacher_id}")
                hours = 0
            elif hours == 0:
                # Логируем только первые несколько случаев
                if t_idx < 3:
                    logger.warning(f"  ПРЕДУПРЕЖДЕНИЕ: hours_per_week = 0 для teacher_id={teacher_id}")
            
            if teacher_id is None:
                logger.error(f"  ОШИБКА: teacher_id = None, пропускаем")
                continue
            
            # Если hours = 0, пытаемся взять из ClassLoad (как на странице "Нагрузка учителей")
            if hours == 0:
                class_load = db.session.query(ClassLoad).filter_by(
                    shift_id=shift_id,
                    class_id=cs.class_id,
                    subject_id=cs.subject_id
                ).first()
                if class_load:
                    hours = class_load.hours_per_week
                    logger.info(f"teacher_id={teacher_id}, class_id={cs.class_id}, subject_id={cs.subject_id}: hours из ClassLoad = {hours}")
            

            # Пропускаем учителей с hours = 0 или None
            if hours is None or hours <= 0:
                continue
            
            # --- VALIDATION FIX: Cap teacher hours to class subject total ---
            if hours > cs.total_hours_per_week:
                logger.warning(f"  [VALIDATION] Teacher {teacher_id} hours ({hours}) > Subject total ({cs.total_hours_per_week}). Capping at {cs.total_hours_per_week}.")
                hours = cs.total_hours_per_week
            # -------------------------------------------------------------
            
            # Получаем список доступных кабинетов с приоритетами
            available_cabinets = get_available_cabinets_for_teacher(
                teacher_id, 
                cs.subject_id, 
                default_cabinet_raw,
                cs.has_subgroups
            )
            
            default_cabinet = available_cabinets[0]['name'] if available_cabinets else (default_cabinet_raw or '-')
            
            teacher_data = {
                'teacher_id': teacher_id,
                'hours_per_week': hours,
                'default_cabinet': default_cabinet,
                'available_cabinets': available_cabinets,
                'is_assigned_to_class': is_assigned
            }
            
            teachers.append(teacher_data)
            logger.debug(f"Добавлен учитель: {teacher_data}")
        
        if not teachers:
            logger.warning(f"Требование class_id={cs.class_id}, subject_id={cs.subject_id}: нет учителей с hours_per_week > 0")
            continue
            
        # --- VALIDATION FIX: Cap sum of hours for subgroups ---
        # Note: Ideally we want to check parallel groups, but strict single teacher cap is safer for now.
        # This fix is primarily for single teacher overuse. 

        
        # Логируем статистику для первых нескольких требований
        if cs_idx < 3:
            total_hours_teachers = sum(t['hours_per_week'] for t in teachers)
            logger.info(f"Требование #{cs_idx}: class_id={cs.class_id}, subject_id={cs.subject_id}")
            logger.info(f"  Учителей с часами: {len(teachers)}")
            logger.info(f"  Сумма часов учителей: {total_hours_teachers}")
            logger.info(f"  total_hours_per_week из БД: {cs.total_hours_per_week}")
        
        # Получаем название класса
        class_group = db.session.query(ClassGroup).filter_by(id=cs.class_id).first()
        class_name = class_group.name if class_group else ""
        
        # Получаем название предмета
        subject = db.session.query(Subject).filter_by(id=cs.subject_id).first()
        subject_name = subject.name if subject else ""
        
        # Определяем has_subgroups: либо из БД, либо автоматически по количеству учителей
        if len(teachers) >= 2:
            has_subgroups = True
        elif cs.has_subgroups is True:
            has_subgroups = True
        else:
            has_subgroups = False
        
        # Создаем требование
        req = ClassSubjectRequirement(
            class_id=cs.class_id,
            subject_id=cs.subject_id,
            total_hours_per_week=cs.total_hours_per_week,
            has_subgroups=has_subgroups,
            teachers=teachers,  # ВСЕ учителя в одном требовании
            class_name=class_name,
            subject_name=subject_name
        )
        requirements.append(req)
    
    logger.info(f"Загружено {len(requirements)} требований для смены {shift_id}")
    
    return requirements


def _load_requirements_from_teacher_assignments(shift_id: int) -> List[ClassSubjectRequirement]:
    """
    Загружает требования из таблицы teacher_assignments (резервный метод)
    
    Используется, если prompt_class_subjects пуста, но есть данные в teacher_assignments
    
    ВАЖНО: Эта функция должна вызываться внутри school_db_context!
    
    Args:
        shift_id: ID смены
    
    Returns:
        Список требований ClassSubjectRequirement
    """
    from collections import defaultdict
    
    # Проверяем, что bind 'school' настроен
    from flask import current_app, has_app_context
    if not has_app_context():
        raise RuntimeError("_load_requirements_from_teacher_assignments требует активный app context. Используйте school_db_context.")
    
    binds = current_app.config.get('SQLALCHEMY_BINDS', {})
    if 'school' not in binds:
        error_msg = (
            f"Bind 'school' не настроен в SQLALCHEMY_BINDS. "
            f"Текущая конфигурация: {list(binds.keys())}. "
            f"Убедитесь, что вы вызываете эту функцию внутри school_db_context(school_id)."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Загрузка из teacher_assignments для смены {shift_id}")
    
    requirements = []
    
    try:
        # Получаем все назначения учителей для смены
        teacher_assignments = db.session.query(TeacherAssignment).filter_by(
            shift_id=shift_id
        ).all()
    except Exception as e:
        error_msg = f"Ошибка при загрузке teacher_assignments: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        raise RuntimeError(error_msg) from e
    
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Найдено {len(teacher_assignments)} назначений учителей")
    
    if not teacher_assignments:
        logger.warning(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Нет назначений учителей в teacher_assignments")
        return []
    
    # Группируем по классу и предмету
    class_subject_groups = defaultdict(lambda: {
        'class_id': None,
        'subject_id': None,
        'total_hours': 0,
        'teachers': []
    })
    
    teachers_with_hours_count = 0
    teachers_without_hours_count = 0
    
    # Проверяем первые несколько записей для диагностики
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Проверка первых 5 записей teacher_assignments:")
    for i, ta in enumerate(teacher_assignments[:5]):
        logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА]   Запись #{i}: teacher_id={ta.teacher_id}, class_id={ta.class_id}, subject_id={ta.subject_id}, hours_per_week={ta.hours_per_week} (type: {type(ta.hours_per_week)})")
    
    for ta in teacher_assignments:
        key = (ta.class_id, ta.subject_id)
        if class_subject_groups[key]['class_id'] is None:
            class_subject_groups[key]['class_id'] = ta.class_id
            class_subject_groups[key]['subject_id'] = ta.subject_id
        
        # Получаем total_hours из class_load
        class_load = db.session.query(ClassLoad).filter_by(
            shift_id=shift_id,
            class_id=ta.class_id,
            subject_id=ta.subject_id
        ).first()
        
        if class_load:
            class_subject_groups[key]['total_hours'] = class_load.hours_per_week
        
        # Получаем hours_per_week - если 0, берем из ClassLoad (как на странице "Нагрузка учителей")
        hours = ta.hours_per_week or 0
        if hours == 0:
            if class_load:
                hours = class_load.hours_per_week
                logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] teacher_id={ta.teacher_id}, class_id={ta.class_id}, subject_id={ta.subject_id}: hours из ClassLoad = {hours}")
        
        # Пропускаем учителей с hours = 0 или None
        if hours is None or hours <= 0:
            teachers_without_hours_count += 1
            if teachers_without_hours_count <= 5:
                logger.warning(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Пропускаем teacher_id={ta.teacher_id}, hours={hours}")
            continue
        
        teachers_with_hours_count += 1
        
        # Получаем доступные кабинеты
        available_cabinets = get_available_cabinets_for_teacher(
            ta.teacher_id,
            ta.subject_id,
            ta.default_cabinet or '',
            False  # Определим has_subgroups позже
        )
        
        default_cabinet = available_cabinets[0]['name'] if available_cabinets else (ta.default_cabinet or '-')
        
        class_subject_groups[key]['teachers'].append({
            'teacher_id': ta.teacher_id,
            'hours_per_week': hours,  # Используем hours (может быть из ClassLoad)
            'default_cabinet': default_cabinet,
            'available_cabinets': available_cabinets,
            'is_assigned_to_class': False
        })
    
    # Создаем требования
    for (class_id, subject_id), group_data in class_subject_groups.items():
        if not group_data['teachers']:
            continue
        
        # Определяем has_subgroups (если 2+ учителя)
        has_subgroups = len(group_data['teachers']) >= 2
        
        # Получаем названия
        class_group = db.session.query(ClassGroup).filter_by(id=class_id).first()
        class_name = class_group.name if class_group else ""
        
        subject = db.session.query(Subject).filter_by(id=subject_id).first()
        subject_name = subject.name if subject else ""
        
        # Используем total_hours из class_load или сумму часов учителей
        total_hours = group_data['total_hours']
        if total_hours == 0:
            total_hours = sum(t['hours_per_week'] for t in group_data['teachers'])
            logger.warning(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] class_id={class_id}, subject_id={subject_id}: total_hours не найден в class_load, используем сумму: {total_hours}")
        
        req = ClassSubjectRequirement(
            class_id=class_id,
            subject_id=subject_id,
            total_hours_per_week=total_hours,
            has_subgroups=has_subgroups,
            teachers=group_data['teachers'],
            class_name=class_name,
            subject_name=subject_name
        )
        requirements.append(req)
        
        logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Создано требование: class_id={class_id}, subject_id={subject_id}, total_hours={total_hours}, учителей={len(group_data['teachers'])}")
    
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Статистика:")
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА]   Всего teacher_assignments: {len(teacher_assignments)}")
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА]   Учителей с hours > 0: {teachers_with_hours_count}")
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА]   Учителей с hours = 0 или None: {teachers_without_hours_count}")
    logger.info(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА]   Загружено требований: {len(requirements)}")
    
    if teachers_with_hours_count == 0:
        logger.error(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] КРИТИЧЕСКАЯ ОШИБКА: Все учителя имеют hours_per_week = 0 или None!")
        logger.error(f"[АЛЬТЕРНАТИВНАЯ ЗАГРУЗКА] Проверьте данные в таблице teacher_assignments для смены {shift_id}")
    
    return requirements


def get_schedule_settings(shift_id: int) -> Dict[int, int]:
    """
    Получает настройки расписания для смены
    
    Args:
        shift_id: ID смены
    
    Returns:
        Словарь {day_of_week: lessons_count}
    """
    settings = db.session.query(ScheduleSettings).filter_by(
        shift_id=shift_id
    ).all()
    
    result = {}
    for s in settings:
        result[s.day_of_week] = s.lessons_count
    
    # Если для какого-то дня нет настроек, используем значение по умолчанию (6 уроков)
    for day in range(1, 8):  # Понедельник - Воскресенье
        if day not in result:
            result[day] = 6
    
    return result


def get_existing_schedule(shift_id: int) -> Dict[Tuple[int, int, int], List[Dict]]:
    """
    Получает существующее расписание для смены
    
    Args:
        shift_id: ID смены
    
    Returns:
        Словарь {(day_of_week, lesson_number, class_id): [уроки]}
        Каждый урок: {teacher_id, subject_id, cabinet}
    """
    existing = db.session.query(PermanentSchedule).filter_by(
        shift_id=shift_id
    ).all()
    
    result = defaultdict(list)
    for entry in existing:
        key = (entry.day_of_week, entry.lesson_number, entry.class_id)
        result[key].append({
            'teacher_id': entry.teacher_id,
            'subject_id': entry.subject_id,
            'cabinet': entry.cabinet
        })
    
    return dict(result)


def _build_requirements(shift_id: int) -> List[ClassSubjectRequirement]:
    """
    Строит список требований для алгоритма (используется для ИИ улучшения)
    
    Args:
        shift_id: ID смены
    
    Returns:
        Список требований ClassSubjectRequirement
    """
    return load_requirements_from_db(shift_id)


def _get_settings(shift_id: int) -> Tuple[List[int], int]:
    """
    Получает настройки расписания (используется для ИИ улучшения)
    
    Args:
        shift_id: ID смены
    
    Returns:
        Кортеж (study_days, max_lessons_per_day)
        study_days: список дней недели (1-7)
        max_lessons_per_day: максимальное количество уроков в день
    """
    settings = get_schedule_settings(shift_id)
    study_days = list(settings.keys())
    max_lessons_per_day = max(settings.values()) if settings else 6
    
    return study_days, max_lessons_per_day


def _get_existing(shift_id: int) -> List[LessonSlot]:
    """
    Получает существующие слоты расписания (используется для ИИ улучшения)
    
    Args:
        shift_id: ID смены
    
    Returns:
        Список LessonSlot с существующими уроками
    """
    from app.services.schedule_solver import LessonSlot
    
    existing = get_existing_schedule(shift_id)
    slots = []
    
    for (day, lesson, class_id), lessons in existing.items():
        for lesson_data in lessons:
            slot = LessonSlot(day_of_week=day, lesson_number=lesson)
            if slot not in slots:
                slots.append(slot)
    
    return slots

