"""
Адаптер для базового алгоритма составления расписания
"""
from typing import Dict
import logging

from app.core.db_manager import db, school_db_context
from app.services.schedule_solver_adapter import (
    load_requirements_from_db,
    get_schedule_settings,
    get_existing_schedule
)
from app.services.schedule_solver_basic import solve_schedule_basic

logger = logging.getLogger(__name__)


def generate_schedule_basic(
    shift_id: int,
    school_id: int = None,
    clear_existing: bool = False
) -> Dict:
    """
    Генерирует расписание используя базовый алгоритм
    
    Args:
        shift_id: ID смены
        school_id: ID школы
        clear_existing: Очищать ли существующее расписание перед генерацией
    
    Returns:
        Словарь с suggestions, warnings, summary (совместимый с форматом AI)
    """
    if school_id:
        with school_db_context(school_id):
            return _generate_basic(shift_id, clear_existing)
    else:
        return _generate_basic(shift_id, clear_existing)


def _generate_basic(shift_id: int, clear_existing: bool) -> Dict:
    """
    Внутренняя функция генерации расписания
    """
    import time
    start_load = time.time()
    
    logger.info(f"[BASIC АЛГОРИТМ] Этап 1: Загрузка данных из БД...")
    
    # Загружаем требования из БД
    logger.info(f"[BASIC АЛГОРИТМ] Загрузка требований для смены {shift_id}...")
    requirements = load_requirements_from_db(shift_id)
    
    load_time = time.time() - start_load
    logger.info(f"[BASIC АЛГОРИТМ] ✓ Загружено {len(requirements)} требований за {load_time:.2f} секунд")
    
    if not requirements:
        logger.error(f"[BASIC АЛГОРИТМ] ОШИБКА: Нет требований для составления расписания")
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Загружаем настройки расписания
    logger.info(f"[BASIC АЛГОРИТМ] Загрузка настроек расписания...")
    schedule_settings = get_schedule_settings(shift_id)
    logger.info(f"[BASIC АЛГОРИТМ] ✓ Настройки загружены: {schedule_settings}")
    
    # Загружаем существующее расписание
    existing_schedule = get_existing_schedule(shift_id) if not clear_existing else {}
    if existing_schedule:
        logger.info(f"[BASIC АЛГОРИТМ] Загружено существующее расписание: {len(existing_schedule)} слотов")
    
    # Вызываем алгоритм
    logger.info(f"[BASIC АЛГОРИТМ] Этап 2: Запуск базового алгоритма...")
    start_basic = time.time()
    result = solve_schedule_basic(
        requirements=requirements,
        shift_id=shift_id,
        existing_schedule=existing_schedule,
        schedule_settings=schedule_settings,
        clear_existing=clear_existing
    )
    
    basic_time = time.time() - start_basic
    logger.info(f"[BASIC АЛГОРИТМ] ✓ Алгоритм завершен за {basic_time:.2f} секунд")
    logger.info(f"[BASIC АЛГОРИТМ] Результат: {len(result.get('suggestions', []))} предложений, {len(result.get('warnings', []))} предупреждений")
    
    return result

