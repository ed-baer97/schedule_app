"""
Адаптер для эталонной архитектуры составления расписания
"""
from typing import Dict
import logging

from app.core.db_manager import db, school_db_context
from app.services.schedule_solver_adapter import (
    load_requirements_from_db,
    get_schedule_settings,
    get_existing_schedule
)
from app.services.schedule_solver_pipeline import solve_schedule_pipeline

logger = logging.getLogger(__name__)


def generate_schedule_pipeline(
    shift_id: int,
    school_id: int = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 300,
    use_genetic: bool = False,
    use_cp_sat: bool = True  # По умолчанию включен, но можно отключить для скорости
) -> Dict:
    """
    Генерирует расписание используя эталонную архитектуру
    
    Pipeline:
    1. Greedy - предварительная расстановка 70-85% уроков
    2. Graph Coloring - определение тайм-слотов
    3. Bipartite Matching - распределение кабинетов
    4. CP-SAT - финальная сборка и устранение конфликтов
    5. (опционально) Genetic Algorithm - улучшение итогового качества
    
    Args:
        shift_id: ID смены
        school_id: ID школы
        clear_existing: Очищать ли существующее расписание перед генерацией
        time_limit_seconds: Лимит времени для CP-SAT (секунды)
        use_genetic: Использовать ли генетический алгоритм
    
    Returns:
        Словарь с suggestions, warnings, summary (совместимый с форматом AI)
    """
    if school_id:
        with school_db_context(school_id):
            return _generate_pipeline(shift_id, clear_existing, time_limit_seconds, use_genetic, use_cp_sat)
    else:
        return _generate_pipeline(shift_id, clear_existing, time_limit_seconds, use_genetic, use_cp_sat)


def _generate_pipeline(
    shift_id: int,
    clear_existing: bool,
    time_limit_seconds: int,
    use_genetic: bool,
    use_cp_sat: bool
) -> Dict:
    """
    Внутренняя функция генерации расписания
    """
    import time
    start_load = time.time()
    
    logger.info(f"[PIPELINE АЛГОРИТМ] Этап 1: Загрузка данных из БД...")
    
    # Загружаем требования из БД
    logger.info(f"[PIPELINE АЛГОРИТМ] Загрузка требований для смены {shift_id}...")
    requirements = load_requirements_from_db(shift_id)
    
    load_time = time.time() - start_load
    logger.info(f"[PIPELINE АЛГОРИТМ] ✓ Загружено {len(requirements)} требований за {load_time:.2f} секунд")
    
    if not requirements:
        logger.error(f"[PIPELINE АЛГОРИТМ] ОШИБКА: Нет требований для составления расписания")
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Загружаем настройки расписания
    logger.info(f"[PIPELINE АЛГОРИТМ] Загрузка настроек расписания...")
    schedule_settings = get_schedule_settings(shift_id)
    logger.info(f"[PIPELINE АЛГОРИТМ] ✓ Настройки загружены: {schedule_settings}")
    
    # Загружаем существующее расписание
    existing_schedule = get_existing_schedule(shift_id) if not clear_existing else {}
    if existing_schedule:
        logger.info(f"[PIPELINE АЛГОРИТМ] Загружено существующее расписание: {len(existing_schedule)} слотов")
    
    # Вызываем pipeline
    logger.info(f"[PIPELINE АЛГОРИТМ] Этап 2: Запуск Pipeline алгоритма...")
    logger.info(f"[PIPELINE АЛГОРИТМ] Параметры: time_limit={time_limit_seconds}с, use_genetic={use_genetic}, use_cp_sat={use_cp_sat}")
    start_pipeline = time.time()
    result = solve_schedule_pipeline(
        requirements=requirements,
        shift_id=shift_id,
        existing_schedule=existing_schedule,
        schedule_settings=schedule_settings,
        clear_existing=clear_existing,
        time_limit_seconds=time_limit_seconds,
        use_genetic=use_genetic,
        use_cp_sat=use_cp_sat
    )
    
    pipeline_time = time.time() - start_pipeline
    logger.info(f"[PIPELINE АЛГОРИТМ] ✓ Pipeline завершен за {pipeline_time:.2f} секунд")
    logger.info(f"[PIPELINE АЛГОРИТМ] Результат: {len(result.get('suggestions', []))} предложений, {len(result.get('warnings', []))} предупреждений")
    
    return result

