"""
Адаптер для гибридного алгоритма составления расписания
Гибридный пайплайн: Greedy → CP-SAT → LNS
"""
from typing import Dict
import logging

from app.core.db_manager import db, school_db_context
from app.services.schedule_solver_adapter import (
    load_requirements_from_db,
    get_schedule_settings,
    get_existing_schedule
)
from app.services.schedule_solver_hybrid import solve_schedule_hybrid

logger = logging.getLogger(__name__)


def generate_schedule_hybrid(
    shift_id: int,
    school_id: int = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 45,
    lesson_mode: str = "pairs",
    subgroup_pairs: list = None
) -> Dict:
    """
    Генерирует расписание используя гибридный алгоритм
    
    Pipeline:
    1. Greedy - предварительная расстановка 70-85% уроков
    2. CP-SAT - размещение оставшихся уроков с гарантией отсутствия окон
    3. LNS - финальная полировка и оптимизация
    
    Args:
        shift_id: ID смены
        school_id: ID школы
        clear_existing: Очищать ли существующее расписание перед генерацией
        time_limit_seconds: Лимит времени для CP-SAT (секунды)
        lesson_mode: "pairs" - размещать парами, "single" - строго один предмет в день
        subgroup_pairs: Список кортежей (subject_id1, subject_id2) разрешенных пар для подгрупп
    
    Returns:
        Словарь с suggestions, warnings, summary (совместимый с форматом AI)
    """
    # ВАЖНО: Если school_id не передан, но мы уже внутри school_db_context,
    # то контекст уже установлен и мы можем работать напрямую
    # Если school_id передан, создаем новый контекст
    if school_id:
        with school_db_context(school_id):
            return _generate_hybrid(shift_id, clear_existing, time_limit_seconds, lesson_mode, subgroup_pairs)
    else:
        # Если school_id не передан, предполагаем, что мы уже внутри school_db_context
        # Это происходит, когда функция вызывается из routes/schedule.py, где контекст уже установлен
        # Проверяем, что контекст действительно установлен
        from flask import current_app, has_app_context
        if has_app_context():
            binds = current_app.config.get('SQLALCHEMY_BINDS', {})
            if 'school' not in binds:
                # Пытаемся получить school_id из контекста Flask
                from flask import g, has_request_context
                if has_request_context() and hasattr(g, 'school_id') and g.school_id:
                    with school_db_context(g.school_id):
                        return _generate_hybrid(shift_id, clear_existing, time_limit_seconds, lesson_mode, subgroup_pairs)
                else:
                    raise RuntimeError(
                        "school_id не передан и bind 'school' не настроен. "
                        "Передайте school_id или убедитесь, что вы внутри school_db_context."
                    )
        
        return _generate_hybrid(shift_id, clear_existing, time_limit_seconds, lesson_mode, subgroup_pairs)


def _generate_hybrid(
    shift_id: int,
    clear_existing: bool,
    time_limit_seconds: int,
    lesson_mode: str,
    subgroup_pairs: list
) -> Dict:
    """
    Внутренняя функция генерации расписания
    
    ВАЖНО: Эта функция должна вызываться внутри school_db_context!
    """
    import time
    start_load = time.time()
    
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Этап 1: Загрузка данных из БД...")
    
    # Проверяем, что bind 'school' настроен
    from flask import current_app, has_app_context
    if not has_app_context():
        error_msg = "_generate_hybrid требует активный app context. Используйте school_db_context."
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: {error_msg}")
        raise RuntimeError(error_msg)
    
    binds = current_app.config.get('SQLALCHEMY_BINDS', {})
    if 'school' not in binds:
        error_msg = (
            f"Bind 'school' не настроен в SQLALCHEMY_BINDS. "
            f"Текущая конфигурация: {list(binds.keys())}. "
            f"Убедитесь, что вы вызываете эту функцию внутри school_db_context(school_id)."
        )
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: {error_msg}")
        raise RuntimeError(error_msg)
    
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Bind 'school' настроен: {binds.get('school', 'N/A')[:50]}...")
    
    # Проверяем доступность таблиц БД
    try:
        from app.core.db_manager import db
        from app.models.school import (
            PromptClassSubject, PromptClassSubjectTeacher, ScheduleSettings,
            PermanentSchedule, Shift, Cabinet, ShiftClass, Subject, ClassGroup,
            Teacher, CabinetTeacher, TeacherAssignment
        )
        
        # Проверяем существование смены
        shift_check = db.session.query(Shift).filter_by(id=shift_id).first()
        if not shift_check:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: Смена {shift_id} не найдена в БД")
            return {
                'suggestions': [],
                'warnings': [f'Смена {shift_id} не найдена в БД'],
                'summary': 'Ошибка: смена не найдена'
            }
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Смена найдена: {shift_check.name}")
        
        # Проверяем наличие классов в смене
        classes_count = db.session.query(ShiftClass).filter_by(shift_id=shift_id).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Классов в смене: {classes_count}")
        
        # Проверяем наличие предметов
        subjects_count = db.session.query(Subject).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Предметов в БД: {subjects_count}")
        
        # Проверяем наличие учителей
        teachers_count = db.session.query(Teacher).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Учителей в БД: {teachers_count}")
        
        # Проверяем наличие кабинетов
        cabinets_count = db.session.query(Cabinet).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Кабинетов в БД: {cabinets_count}")
        
        # Проверяем наличие требований
        requirements_count = db.session.query(PromptClassSubject).filter_by(shift_id=shift_id).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Требований (prompt_class_subject) для смены: {requirements_count}")
        
        # Проверяем наличие назначений учителей
        teacher_assignments_count = db.session.query(PromptClassSubjectTeacher).join(
            PromptClassSubject
        ).filter(PromptClassSubject.shift_id == shift_id).count()
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Назначений учителей (prompt_class_subject_teacher): {teacher_assignments_count}")
        
        if requirements_count == 0:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА: Нет требований в таблице prompt_class_subject для смены {shift_id}")
            return {
                'suggestions': [],
                'warnings': [
                    f'Нет требований в таблице prompt_class_subject для смены {shift_id}',
                    'Загрузите данные через загрузку файлов или создайте требования вручную'
                ],
                'summary': 'Ошибка: нет требований для составления расписания'
            }
        
        if teacher_assignments_count == 0:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА: Нет назначений учителей в таблице prompt_class_subject_teacher")
            return {
                'suggestions': [],
                'warnings': [
                    f'Нет назначений учителей в таблице prompt_class_subject_teacher для смены {shift_id}',
                    'Назначьте учителей для классов и предметов'
                ],
                'summary': 'Ошибка: нет назначений учителей'
            }
        
    except Exception as e:
        import traceback
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА при проверке БД: {e}")
        logger.error(traceback.format_exc())
        return {
            'suggestions': [],
            'warnings': [f'Ошибка при проверке БД: {str(e)}'],
            'summary': 'Ошибка доступа к БД'
        }
    
    # Загружаем требования из БД
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Загрузка требований для смены {shift_id}...")
    try:
        requirements = load_requirements_from_db(shift_id)
        load_time = time.time() - start_load
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Загружено {len(requirements)} требований за {load_time:.2f} секунд")
        
        # Детальная статистика по требованиям
        if requirements:
            total_teachers = sum(len(req.teachers) for req in requirements)
            total_hours = sum(req.total_hours_per_week for req in requirements)
            reqs_with_teachers = sum(1 for req in requirements if req.teachers)
            reqs_without_teachers = sum(1 for req in requirements if not req.teachers)
            
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Статистика требований:")
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Всего требований: {len(requirements)}")
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Требований с учителями: {reqs_with_teachers}")
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Требований без учителей: {reqs_without_teachers}")
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Всего учителей в требованиях: {total_teachers}")
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Всего часов в неделю: {total_hours}")
            
            if reqs_without_teachers > 0:
                logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] ВНИМАНИЕ: {reqs_without_teachers} требований без учителей!")
        else:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА: Не загружено ни одного требования!")
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] Проверьте таблицы:")
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   1. prompt_class_subject (для смены {shift_id})")
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   2. prompt_class_subject_teacher")
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   3. shift_classes (классы для смены {shift_id})")
    except Exception as e:
        import traceback
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА при загрузке требований: {e}")
        logger.error(traceback.format_exc())
        return {
            'suggestions': [],
            'warnings': [f'Ошибка при загрузке требований: {str(e)}'],
            'summary': 'Ошибка загрузки данных из БД'
        }
    
    if not requirements:
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: Нет требований для составления расписания")
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Загружаем настройки расписания
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Загрузка настроек расписания...")
    schedule_settings = get_schedule_settings(shift_id)
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Настройки загружены: {schedule_settings}")
    
    # Загружаем существующее расписание
    existing_schedule = get_existing_schedule(shift_id) if not clear_existing else {}
    if existing_schedule:
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Загружено существующее расписание: {len(existing_schedule)} слотов")
    
    # Преобразуем subgroup_pairs из списка списков в список кортежей
    subgroup_pairs_tuples = None
    if subgroup_pairs:
        try:
            subgroup_pairs_tuples = [tuple(pair) if isinstance(pair, (list, tuple)) else pair 
                                     for pair in subgroup_pairs]
        except Exception as e:
            logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] Ошибка при обработке subgroup_pairs: {e}")
            subgroup_pairs_tuples = []
    
    # Загружаем информацию о категориях предметов
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Загрузка категорий предметов...")
    subject_categories = {}
    try:
        subjects = db.session.query(Subject).all()
        for subject in subjects:
            if subject.category:
                subject_categories[subject.id] = subject.category
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Загружено категорий: {len(subject_categories)}")
        if subject_categories:
            from collections import Counter
            cat_counter = Counter(subject_categories.values())
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Распределение по категориям: {dict(cat_counter)}")
    except Exception as e:
        logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] Предупреждение при загрузке категорий: {e}")
        # Продолжаем без категорий - это не критично
    
    # КРИТИЧЕСКИ ВАЖНО: Закрываем сессию БД перед запуском длительного вычисления
    # Это предотвращает ошибку "database is locked", так как алгоритм работает только в памяти
    # и не требует постоянного соединения с БД. Если сессию не закрыть, транзакция может
    # висеть открытой 45+ секунд, блокируя другие операции (например, поллинг прогресса).
    db.session.remove()
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] БД сессия закрыта для освобождения ресурсов")
    
    start_hybrid = time.time()
    
    try:
        result = solve_schedule_hybrid(
            requirements=requirements,
            shift_id=shift_id,
            existing_schedule=existing_schedule,
            schedule_settings=schedule_settings,
            clear_existing=clear_existing,
            time_limit_seconds=time_limit_seconds,
            lesson_mode=lesson_mode,
            subgroup_pairs=subgroup_pairs_tuples,
            subject_categories=subject_categories  # NEW: Pass categories to solver
        )
        
        hybrid_time = time.time() - start_hybrid
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Алгоритм завершен за {hybrid_time:.2f} секунд")
        
        # Проверяем результат
        if not result:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: Алгоритм вернул None")
            return {
                'suggestions': [],
                'warnings': ['Алгоритм не вернул результат'],
                'summary': 'Внутренняя ошибка алгоритма'
            }
        
        suggestions_count = len(result.get('suggestions', []))
        warnings_count = len(result.get('warnings', []))
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Результат: {suggestions_count} предложений, {warnings_count} предупреждений")
        
        # Логируем предупреждения
        if result.get('warnings'):
            for warning in result['warnings']:
                logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] Предупреждение: {warning}")
        
        return result
        
    except ImportError as e:
        error_msg = f"Библиотека OR-Tools не установлена: {str(e)}"
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА: {error_msg}")
        return {
            'suggestions': [],
            'warnings': [error_msg, 'Установите библиотеку: pip install ortools'],
            'summary': 'Ошибка: отсутствует библиотека OR-Tools'
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        error_msg = f"Ошибка при выполнении гибридного алгоритма: {str(e)}"
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА:")
        logger.error(f"  Тип: {type(e).__name__}")
        logger.error(f"  Сообщение: {error_msg}")
        logger.error(f"  Трассировка:\n{error_trace}")
        return {
            'suggestions': [],
            'warnings': [error_msg],
            'summary': f'Ошибка выполнения алгоритма: {type(e).__name__}'
        }

