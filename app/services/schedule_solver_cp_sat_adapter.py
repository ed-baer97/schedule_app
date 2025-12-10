"""
Адаптер для CP-SAT алгоритма составления расписания
"""
from typing import Dict
import logging

from app.core.db_manager import db, school_db_context
from app.services.schedule_solver_adapter import (
    load_requirements_from_db,
    get_schedule_settings,
    get_existing_schedule
)
from app.services.schedule_solver_cp_sat import solve_schedule_cp_sat

logger = logging.getLogger(__name__)


def generate_schedule_cp_sat(
    shift_id: int,
    school_id: int = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 300,
    gap_weight: int = 100,
    priority_weight: int = 1
) -> Dict:
    """
    Генерирует расписание используя CP-SAT алгоритм
    
    Args:
        shift_id: ID смены
        school_id: ID школы
        clear_existing: Очищать ли существующее расписание перед генерацией
        time_limit_seconds: Лимит времени для решения (секунды)
        gap_weight: Вес штрафа за окно
        priority_weight: Вес штрафа за использование кабинета с низким приоритетом
    
    Returns:
        Словарь с suggestions, warnings, summary (совместимый с форматом AI)
    """
    if school_id:
        with school_db_context(school_id):
            return _generate_cp_sat(shift_id, clear_existing, time_limit_seconds, gap_weight, priority_weight)
    else:
        return _generate_cp_sat(shift_id, clear_existing, time_limit_seconds, gap_weight, priority_weight)


def _generate_cp_sat(
    shift_id: int, 
    clear_existing: bool,
    time_limit_seconds: int,
    gap_weight: int,
    priority_weight: int
) -> Dict:
    """
    Внутренняя функция генерации расписания
    """
    import time
    start_load = time.time()
    
    logger.info(f"[CP-SAT АЛГОРИТМ] Этап 1: Загрузка данных из БД...")
    
    # Загружаем требования из БД (локально, без нейросети)
    logger.info(f"[CP-SAT АЛГОРИТМ] Загрузка требований для смены {shift_id}...")
    requirements = load_requirements_from_db(shift_id)
    
    load_time = time.time() - start_load
    logger.info(f"[CP-SAT АЛГОРИТМ] ✓ Загружено {len(requirements)} требований за {load_time:.2f} секунд")
    
    if not requirements:
        logger.error(f"[CP-SAT АЛГОРИТМ] ОШИБКА: Нет требований для составления расписания")
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Загружаем настройки расписания
    logger.info(f"[CP-SAT АЛГОРИТМ] Загрузка настроек расписания...")
    schedule_settings = get_schedule_settings(shift_id)
    logger.info(f"[CP-SAT АЛГОРИТМ] ✓ Настройки загружены: {schedule_settings}")
    
    # Загружаем существующее расписание
    existing_schedule = get_existing_schedule(shift_id) if not clear_existing else {}
    if existing_schedule:
        logger.info(f"[CP-SAT АЛГОРИТМ] Загружено существующее расписание: {len(existing_schedule)} слотов")
    
    # Вызываем CP-SAT алгоритм
    logger.info(f"[CP-SAT АЛГОРИТМ] Этап 2: Запуск CP-SAT алгоритма...")
    logger.info(f"[CP-SAT АЛГОРИТМ] Параметры: time_limit={time_limit_seconds}с, gap_weight={gap_weight}, priority_weight={priority_weight}")
    start_cp_sat = time.time()
    result = solve_schedule_cp_sat(
        requirements=requirements,
        shift_id=shift_id,
        existing_schedule=existing_schedule,
        schedule_settings=schedule_settings,
        clear_existing=clear_existing,
        time_limit_seconds=time_limit_seconds,
        gap_weight=gap_weight,
        priority_weight=priority_weight
    )
    
    cp_sat_time = time.time() - start_cp_sat
    logger.info(f"[CP-SAT АЛГОРИТМ] ✓ Алгоритм завершен за {cp_sat_time:.2f} секунд")
    logger.info(f"[CP-SAT АЛГОРИТМ] Результат: {len(result.get('suggestions', []))} предложений, {len(result.get('warnings', []))} предупреждений")
    
    return result

