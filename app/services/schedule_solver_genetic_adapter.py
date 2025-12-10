"""
Адаптер для генетического алгоритма составления расписания
"""
from typing import Dict
import logging

from app.core.db_manager import db, school_db_context
from app.services.schedule_solver_adapter import (
    load_requirements_from_db,
    get_schedule_settings,
    get_existing_schedule
)
from app.services.schedule_solver_genetic import solve_schedule_genetic

logger = logging.getLogger(__name__)


def generate_schedule_genetic(
    shift_id: int,
    school_id: int = None,
    clear_existing: bool = False,
    population_size: int = 400,
    generations: int = 2000
) -> Dict:
    """
    Генерирует расписание используя генетический алгоритм
    
    Args:
        shift_id: ID смены
        school_id: ID школы
        clear_existing: Очищать ли существующее расписание перед генерацией
        population_size: Размер популяции для генетического алгоритма
        generations: Количество поколений
    
    Returns:
        Словарь с suggestions, warnings, summary (совместимый с форматом AI)
    """
    if school_id:
        with school_db_context(school_id):
            return _generate_genetic(shift_id, clear_existing, population_size, generations)
    else:
        return _generate_genetic(shift_id, clear_existing, population_size, generations)


def _generate_genetic(
    shift_id: int,
    clear_existing: bool,
    population_size: int,
    generations: int
) -> Dict:
    """
    Внутренняя функция генерации расписания
    """
    import time
    start_load = time.time()
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 1: Загрузка данных из БД...")
    
    # Загружаем требования из БД
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Загрузка требований для смены {shift_id}...")
    requirements = load_requirements_from_db(shift_id)
    
    load_time = time.time() - start_load
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Загружено {len(requirements)} требований за {load_time:.2f} секунд")
    
    if not requirements:
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: Нет требований для составления расписания")
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Загружаем настройки расписания
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Загрузка настроек расписания...")
    schedule_settings = get_schedule_settings(shift_id)
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Настройки загружены: {schedule_settings}")
    
    # Загружаем существующее расписание (не используется в генетическом алгоритме, но для совместимости)
    existing_schedule = get_existing_schedule(shift_id) if not clear_existing else {}
    if existing_schedule:
        logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Загружено существующее расписание: {len(existing_schedule)} слотов")
    
    # Вызываем генетический алгоритм
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 2: Запуск генетического алгоритма...")
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Параметры: популяция={population_size}, поколений={generations}")
    start_genetic = time.time()
    
    try:
        result = solve_schedule_genetic(
            requirements=requirements,
            shift_id=shift_id,
            existing_schedule=existing_schedule,
            schedule_settings=schedule_settings,
            clear_existing=clear_existing,
            population_size=population_size,
            generations=generations
        )
        
        genetic_time = time.time() - start_genetic
        logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Алгоритм завершен за {genetic_time:.2f} секунд")
        
        # Проверяем результат
        if not result:
            logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: Алгоритм вернул None")
            return {
                'suggestions': [],
                'warnings': ['Алгоритм не вернул результат'],
                'summary': 'Внутренняя ошибка алгоритма'
            }
        
        suggestions_count = len(result.get('suggestions', []))
        warnings_count = len(result.get('warnings', []))
        logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Результат: {suggestions_count} предложений, {warnings_count} предупреждений")
        
        # Логируем предупреждения
        if result.get('warnings'):
            for warning in result['warnings']:
                logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Предупреждение: {warning}")
        
        return result
        
    except ImportError as e:
        error_msg = f"Библиотека DEAP не установлена: {str(e)}"
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: {error_msg}")
        return {
            'suggestions': [],
            'warnings': [error_msg, 'Установите библиотеку: pip install deap'],
            'summary': 'Ошибка: отсутствует библиотека DEAP'
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        error_msg = f"Ошибка при выполнении генетического алгоритма: {str(e)}"
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА:")
        logger.error(f"  Тип: {type(e).__name__}")
        logger.error(f"  Сообщение: {error_msg}")
        logger.error(f"  Трассировка:\n{error_trace}")
        return {
            'suggestions': [],
            'warnings': [error_msg],
            'summary': f'Ошибка выполнения алгоритма: {type(e).__name__}'
        }

