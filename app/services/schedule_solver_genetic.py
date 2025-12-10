"""
Генетический алгоритм для составления расписания
Версия от 08.12.2025 - работает идеально на школах до 40 классов
"""
import random
from collections import defaultdict
from typing import List, Dict, Tuple
import logging

try:
    from deap import base, creator, tools, algorithms
    DEAP_AVAILABLE = True
except ImportError:
    DEAP_AVAILABLE = False
    logging.warning("DEAP не установлен. Генетический алгоритм недоступен.")

from app.services.schedule_solver import ClassSubjectRequirement

logger = logging.getLogger(__name__)


def solve_schedule_genetic(
    requirements: List[ClassSubjectRequirement],
    shift_id: int,
    existing_schedule: Dict = None,
    schedule_settings: Dict[int, int] = None,
    clear_existing: bool = False,
    population_size: int = 400,
    generations: int = 2000
) -> Dict:
    """
    Решает задачу составления расписания используя генетический алгоритм
    
    Args:
        requirements: Список требований к расписанию
        shift_id: ID смены
        existing_schedule: Существующее расписание (не используется)
        schedule_settings: Настройки расписания (количество уроков по дням)
        clear_existing: Очищать ли существующее расписание
        population_size: Размер популяции
        generations: Количество поколений
    
    Returns:
        Словарь с suggestions, warnings, summary
    """
    # Проверяем доступность DEAP
    if not DEAP_AVAILABLE:
        logger.error("[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: Библиотека DEAP не установлена")
        return {
            'suggestions': [],
            'warnings': ['Библиотека DEAP не установлена. Установите: pip install deap'],
            'summary': 'Ошибка: отсутствует библиотека DEAP'
        }
    """
    Генерирует расписание используя генетический алгоритм
    
    Args:
        requirements: Список требований ClassSubjectRequirement
        shift_id: ID смены
        existing_schedule: Существующее расписание (не используется в генетическом алгоритме)
        schedule_settings: Настройки расписания {day_of_week: lessons_count}
        clear_existing: Очищать ли существующее расписание (не используется)
        population_size: Размер популяции
        generations: Количество поколений
    
    Returns:
        Словарь с suggestions, warnings, summary
    """
    if not DEAP_AVAILABLE:
        return {
            'suggestions': [],
            'warnings': ['DEAP не установлен. Установите: pip install deap'],
            'summary': 'Генетический алгоритм недоступен'
        }
    
    if not requirements:
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Настройки расписания
    if not schedule_settings:
        schedule_settings = {1: 6, 2: 6, 3: 6, 4: 6, 5: 6}
    
    # Загружаем информацию о кабинетах из БД
    from app.core.db_manager import db
    from app.models.school import Cabinet
    cabinets_info = {}
    try:
        cabinets = db.session.query(Cabinet).all()
        for cab in cabinets:
            cabinets_info[cab.name] = {
                'max_classes': cab.max_classes_simultaneously or 1,
                'subgroups_only': bool(cab.subgroups_only),
                'exclusive_to_subject': bool(cab.exclusive_to_subject),
                'subject_id': cab.subject_id
            }
    except Exception as e:
        logger.warning(f"Не удалось загрузить информацию о кабинетах: {e}")
    
    # Строим список задач (уроков)
    tasks = []
    task_index = {}
    idx = 0
    
    for req in requirements:
        for teacher in req.teachers:
            hours = teacher.get('hours_per_week', 0)
            default_cabinet = teacher.get('default_cabinet', '301')
            
            # Используем первый доступный кабинет из списка, если есть
            available_cabinets = teacher.get('available_cabinets', [])
            if available_cabinets:
                default_cabinet = available_cabinets[0].get('name', default_cabinet)
            
            for _ in range(hours):
                task = {
                    'idx': idx,
                    'class_id': req.class_id,
                    'subject_id': req.subject_id,
                    'teacher_id': teacher['teacher_id'],
                    'cabinet': default_cabinet,
                    'required_hours': req.total_hours_per_week,
                    'has_subgroups': req.has_subgroups
                }
                tasks.append(task)
                task_index[(req.class_id, req.subject_id, teacher['teacher_id'])] = idx
                idx += 1
    
    N_TASKS = len(tasks)
    DAYS = 5  # Понедельник - Пятница
    SLOTS_PER_DAY = max(schedule_settings.values()) if schedule_settings else 7
    SLOTS_PER_WEEK = DAYS * SLOTS_PER_DAY
    
    if N_TASKS == 0:
        return {
            'suggestions': [],
            'warnings': ['Нет уроков для размещения'],
            'summary': 'Нет задач для размещения'
        }
    
    logger.info(f"Генетический алгоритм: {N_TASKS} задач, {SLOTS_PER_WEEK} слотов в неделю")
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 2.2: Инициализация DEAP...")
    
    # Настройка DEAP
    if not hasattr(creator, "FitnessMin"):
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMin)
    
    toolbox = base.Toolbox()
    toolbox.register("slot", random.randint, 0, SLOTS_PER_WEEK - 1)
    toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.slot, N_TASKS)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    
    # Вычисляем кумулятивные слоты для дней
    day_slots = [0] + [schedule_settings.get(d, 6) for d in range(1, DAYS + 1)]
    cumulative_slots = [sum(day_slots[:d]) for d in range(DAYS + 1)]
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ DEAP инициализирован")
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Кумулятивные слоты: {cumulative_slots}")
    
    # Функция оценки
    def evaluate(individual):
        penalty = 0
        teacher_busy = defaultdict(set)
        class_slot_subject = defaultdict(set)  # (class, slot) → set(subject_id)
        cabinet_occupancy = defaultdict(int)
        class_daily_count = defaultdict(int)
        
        for i, slot in enumerate(individual):
            if i >= len(tasks):
                continue
            
            # Проверяем валидность слота
            if slot < 0 or slot >= SLOTS_PER_WEEK:
                penalty += 100_000  # Штраф за невалидный слот
                continue
                
            t = tasks[i]
            c_id = t["class_id"]
            
            # Определяем день и номер урока
            day = next((d for d in range(DAYS) if cumulative_slots[d] <= slot < cumulative_slots[d+1]), None)
            if day is None:
                penalty += 100_000  # Штраф за невалидный день
                continue
            
            lesson_num = slot - cumulative_slots[day] + 1
            
            # Жёсткие ограничения
            
            # Учитель не может быть в двух классах одновременно
            if slot in teacher_busy[t["teacher_id"]]:
                penalty += 100_000
            teacher_busy[t["teacher_id"]].add(slot)
            
            # В одном слоте для класса могут быть только уроки с одинаковым предметом (подгруппы)
            # Проверяем, есть ли уже другие предметы в этом слоте
            existing_subjects = class_slot_subject[(c_id, slot)]
            if len(existing_subjects) > 0:
                # Если в слоте уже есть предметы
                if t["subject_id"] not in existing_subjects:
                    # Разные предметы в одном слоте - нарушение
                    penalty += 100_000
                # Если тот же предмет - это подгруппа, разрешено
            else:
                # Слот пустой, добавляем предмет
                class_slot_subject[(c_id, slot)].add(t["subject_id"])
            
            # Проверка кабинетов
            cabinet_name = t["cabinet"]
            cabinet_occupancy[(cabinet_name, slot)] += 1
            
            # Получаем информацию о кабинете
            cab_info = cabinets_info.get(cabinet_name, {'max_classes': 1, 'subgroups_only': False, 'exclusive_to_subject': False, 'subject_id': None})
            max_classes = cab_info['max_classes']
            
            # Проверяем превышение лимита классов в кабинете
            if cabinet_occupancy[(cabinet_name, slot)] > max_classes:
                penalty += 50_000
            
            # Проверяем exclusive_to_subject
            if cab_info['exclusive_to_subject'] and cab_info['subject_id'] != t["subject_id"]:
                penalty += 50_000
            
            # Проверяем subgroups_only
            if cab_info['subgroups_only']:
                # Проверяем, что это подгруппа (несколько уроков одного предмета в слоте)
                same_subject_count = sum(1 for j, t2 in enumerate(tasks) 
                                        if j < len(individual) and 
                                        t2["class_id"] == c_id and 
                                        t2["subject_id"] == t["subject_id"] and
                                        individual[j] == slot)
                if same_subject_count < 2:
                    penalty += 50_000  # Кабинет только для подгрупп, а это не подгруппа
            
            # Максимум уроков в день для класса
            class_daily_count[(c_id, day)] += 1
            max_lessons = schedule_settings.get(day + 1, 6)
            if class_daily_count[(c_id, day)] > max_lessons:
                penalty += 80_000
        
        # ОКНА НЕТ - САМЫЙ ВАЖНЫЙ ШТРАФ
        class_ids = set(t["class_id"] for t in tasks)
        for class_id in class_ids:
            used = sorted([individual[i] for i, t in enumerate(tasks) 
                          if i < len(individual) and t["class_id"] == class_id])
            
            for d in range(DAYS):
                day_start = cumulative_slots[d]
                day_end = cumulative_slots[d+1]
                day_slots_used = [s for s in used if day_start <= s < day_end]
                
                if len(day_slots_used) > 1:
                    min_lesson = min(day_slots_used) - day_start + 1
                    max_lesson = max(day_slots_used) - day_start + 1
                    if max_lesson - min_lesson + 1 > len(day_slots_used):
                        penalty += 1_000_000  # ОКНО!!!
        
        return (penalty,)
    
    # Функция ремонта (синхронизация подгрупп)
    def repair(individual):
        """
        Принудительно синхронизирует подгруппы - все уроки одного предмета в одном классе
        должны быть в одном слоте
        """
        processed = set()
        
        # Группируем задачи по (class_id, subject_id)
        groups = defaultdict(list)
        for i, task in enumerate(tasks):
            if i < len(individual):
                key = (task["class_id"], task["subject_id"])
                groups[key].append(i)
        
        # Для каждой группы подгрупп синхронизируем слоты
        for key, indices in groups.items():
            if len(indices) > 1:  # Это подгруппа (несколько учителей)
                # Используем слот первого урока в группе
                target_slot = individual[indices[0]]
                for idx in indices[1:]:
                    if idx < len(individual):
                        individual[idx] = target_slot
                        processed.add(idx)
        
        return individual
    
    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxUniform, indpb=0.5)
    toolbox.register("mutate", tools.mutUniformInt, low=0, up=SLOTS_PER_WEEK-1, indpb=0.4)
    toolbox.register("select", tools.selTournament, tournsize=5)
    
    # Запуск алгоритма
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 2.3: Запуск эволюции...")
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Параметры эволюции: популяция={population_size}, поколений={generations}")
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Вероятности: скрещивание=0.85, мутация=0.95")
    
    import time
    evolution_start = time.time()
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Создание начальной популяции...")
    pop = toolbox.population(n=population_size)
    hof = tools.HallOfFame(1)
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Популяция создана, начинаем эволюцию...")
    
    for gen in range(1, generations + 1):
        # Скрещивание и мутация
        offspring = algorithms.varAnd(pop, toolbox, cxpb=0.85, mutpb=0.95)
        
        # Ремонт и оценка
        evaluated_count = 0
        for ind in offspring:
            repair(ind)
            ind.fitness.values = evaluate(ind)
            evaluated_count += 1
        
        # Отбор
        pop[:] = toolbox.select(offspring, k=len(pop))
        hof.update(pop)
        
        best = hof[0]
        best_penalty = best.fitness.values[0]
        
        # Логирование прогресса
        if gen % 200 == 0 or best_penalty == 0:
            elapsed = time.time() - evolution_start
            avg_time_per_gen = elapsed / gen
            remaining_gens = generations - gen
            estimated_remaining = avg_time_per_gen * remaining_gens
            
            logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Поколение {gen:4d}/{generations} → штраф = {best_penalty:8d}")
            logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ]   Время: {elapsed:.1f}с, оценка осталось: {estimated_remaining:.1f}с")
        
        if best_penalty == 0:
            elapsed = time.time() - evolution_start
            logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ ИДЕАЛЬНОЕ РАСПИСАНИЕ НАЙДЕНО на поколении {gen}!")
            logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Время эволюции: {elapsed:.2f} секунд")
            break
    
    # Проверяем, что есть лучшее решение
    if not hof or len(hof) == 0:
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: Не найдено ни одного решения")
        return {
            'suggestions': [],
            'warnings': ['Не удалось найти решение за отведенное время'],
            'summary': 'Генетический алгоритм не смог найти решение'
        }
    
    best_individual = hof[0]
    
    # Проверяем, что у решения есть fitness
    if not hasattr(best_individual, 'fitness') or not best_individual.fitness.valid:
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: У лучшего решения нет валидного fitness")
        return {
            'suggestions': [],
            'warnings': ['Ошибка при оценке решения'],
            'summary': 'Генетический алгоритм: ошибка оценки решения'
        }
    
    best_penalty = best_individual.fitness.values[0]
    total_evolution_time = time.time() - evolution_start
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Эволюция завершена")
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Лучшее решение: штраф = {best_penalty}, время = {total_evolution_time:.2f}с")
    
    # Проверяем длину решения
    if len(best_individual) != N_TASKS:
        logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ВНИМАНИЕ: Длина решения ({len(best_individual)}) не совпадает с количеством задач ({N_TASKS})")
    
    # Преобразуем решение в suggestions
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 2.4: Преобразование решения в формат suggestions...")
    
    suggestions = []
    warnings = []
    
    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    for i, slot in enumerate(best_individual):
        if i >= len(tasks):
            logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Индекс {i} выходит за пределы списка задач (всего задач: {len(tasks)})")
            continue
        
        try:
            task = tasks[i]
            
            # Проверяем валидность слота
            if slot < 0 or slot >= SLOTS_PER_WEEK:
                logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Невалидный слот {slot} для задачи {i}, пропускаем")
                continue
            
            # Определяем день и номер урока
            day_idx = next((d for d in range(DAYS) if cumulative_slots[d] <= slot < cumulative_slots[d+1]), None)
            if day_idx is None:
                logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Не удалось определить день для слота {slot}, пропускаем")
                continue
            
            lesson_num = slot - cumulative_slots[day_idx] + 1
            
            # Проверяем валидность данных задачи
            if not all(key in task for key in ['class_id', 'subject_id', 'teacher_id', 'cabinet']):
                logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Задача {i} содержит неполные данные, пропускаем")
                continue
            
            suggestions.append({
                'day_of_week': day_idx + 1,
                'lesson_number': lesson_num,
                'class_id': task['class_id'],
                'subject_id': task['subject_id'],
                'teacher_id': task['teacher_id'],
                'cabinet': task['cabinet']
            })
        except Exception as e:
            logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Ошибка при обработке задачи {i}: {e}")
            continue
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Создано {len(suggestions)} предложений из {N_TASKS} задач")
    
    # Проверяем, что созданы предложения
    if len(suggestions) == 0:
        error_msg = f"Не удалось создать ни одного предложения из {N_TASKS} задач"
        logger.error(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ОШИБКА: {error_msg}")
        warnings.append(error_msg)
        warnings.append(f"Лучший штраф: {best_penalty}")
        return {
            'suggestions': [],
            'warnings': warnings,
            'summary': f'Генетический алгоритм: не удалось разместить уроки (штраф: {best_penalty})'
        }
    
    if best_penalty > 0:
        warnings.append(f"Расписание сгенерировано с штрафом {best_penalty}. Возможны нарушения ограничений.")
        logger.warning(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ВНИМАНИЕ: Решение имеет штраф {best_penalty}")
    else:
        logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] ✓ Идеальное решение без нарушений!")
    
    summary = f"Генетический алгоритм: размещено {len(suggestions)} из {N_TASKS} уроков"
    if best_penalty == 0:
        summary += " (идеальное решение)"
    else:
        summary += f" (штраф: {best_penalty})"
    
    logger.info(f"[ГЕНЕТИЧЕСКИЙ АЛГОРИТМ] Этап 2.5: Завершение. Итог: {summary}")
    
    return {
        'suggestions': suggestions,
        'warnings': warnings,
        'summary': summary
    }

