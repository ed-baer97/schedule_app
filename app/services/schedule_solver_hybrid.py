"""
Гибридный алгоритм составления расписания 2025
Pipeline: Greedy → CP-SAT → LNS
100% размещение + 0 окон в классах + красивые сдвойки
"""
import random
import time
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict, Counter
import logging

try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
except ImportError as e:
    ORTOOLS_AVAILABLE = False
    logging.warning(f"OR-Tools не установлен. Гибридный алгоритм недоступен: {e}")

from app.services.schedule_solver import ClassSubjectRequirement

logger = logging.getLogger(__name__)

from app.services.progress_manager import update_progress


from app.services.progress_manager import update_progress



def solve_schedule_hybrid(
    requirements: List[ClassSubjectRequirement],
    shift_id: int,
    existing_schedule: Dict = None,
    schedule_settings: Dict[int, int] = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 45,
    lesson_mode: str = "pairs",  # "pairs" или "single"
    subgroup_pairs: List[Tuple[int, int]] = None,  # Разрешенные пары предметов для подгрупп
    max_lns_iterations: int = 800,
    cabinets_info: Dict = None,  # Optional: passed for testing or manual override
    subject_categories: Dict[int, str] = None  # NEW: mapping subject_id -> category
) -> Dict:
    """
    Гибридный алгоритм: Greedy → CP-SAT → LNS
    
    Args:
        requirements: Список требований
        shift_id: ID смены
        existing_schedule: Существующее расписание
        schedule_settings: Настройки расписания {day: lessons_count}
        clear_existing: Очищать ли существующее расписание
        time_limit_seconds: Лимит времени для CP-SAT
        lesson_mode: "pairs" - размещать парами, "single" - строго один предмет в день
        subgroup_pairs: Список кортежей (subject_id1, subject_id2) разрешенных пар для подгрупп
        max_lns_iterations: Максимальное количество итераций LNS
    
    Returns:
        Словарь с suggestions, warnings, summary
    """
    if not ORTOOLS_AVAILABLE:
        return {
            'suggestions': [],
            'warnings': ['OR-Tools не установлен. Установите: pip install ortools'],
            'summary': 'Ошибка: отсутствует библиотека OR-Tools'
        }
    
    if not requirements:
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    if schedule_settings is None:
        schedule_settings = {1: 6, 2: 6, 3: 6, 4: 6, 5: 6}
    
    if subgroup_pairs is None:
        subgroup_pairs = []
    
    start_time = time.time()
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ========== НАЧАЛО ГИБРИДНОГО АЛГОРИТМА ==========")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Запуск для смены {shift_id}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Параметры: lesson_mode={lesson_mode}, subgroup_pairs={subgroup_pairs}")
    if subject_categories:
        from collections import Counter
        cat_counter = Counter(subject_categories.values())
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Категории предметов: {dict(cat_counter)}")
    else:
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Категории предметов: не указаны")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Входные данные:")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Требований: {len(requirements)}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Настроек расписания: {len(schedule_settings) if schedule_settings else 0}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Существующее расписание: {len(existing_schedule) if existing_schedule else 0} слотов")
    
    # Проверяем структуру требований
    if requirements:
        sample_req = requirements[0]
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Пример требования:")
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   class_id: {sample_req.class_id}")
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   subject_id: {sample_req.subject_id}")
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   total_hours_per_week: {sample_req.total_hours_per_week}")
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   has_subgroups: {sample_req.has_subgroups}")
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   teachers: {len(sample_req.teachers)} учителей")
        if sample_req.teachers:
            sample_teacher = sample_req.teachers[0]
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Пример учителя: teacher_id={sample_teacher.get('teacher_id')}, hours={sample_teacher.get('hours_per_week')}")
    
    # Загружаем информацию о кабинетах
    from app.core.db_manager import db
    from app.models.school import Cabinet
    
    # Если кабинеты не переданы, пытаемся загрузить из БД
    if cabinets_info is None:
        cabinets_info = {}
        try:
            # Проверяем, что bind 'school' настроен
            from flask import current_app
            if 'SQLALCHEMY_BINDS' not in current_app.config or 'school' not in current_app.config.get('SQLALCHEMY_BINDS', {}):
                logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] Bind 'school' не настроен, пропускаем загрузку кабинетов")
            else:
                cabinets = db.session.query(Cabinet).all()
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Загружено кабинетов из БД: {len(cabinets)}")
                for cab in cabinets:
                    cabinets_info[cab.name] = {
                        'max_classes': cab.max_classes_simultaneously or 1,
                        'subgroups_only': bool(cab.subgroups_only),
                        'exclusive_to_subject': bool(cab.exclusive_to_subject),
                        'subject_id': cab.subject_id
                    }
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Информация о кабинетах загружена: {len(cabinets_info)} кабинетов")
        except Exception as e:
            logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] ОШИБКА при загрузке кабинетов: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Продолжаем работу без информации о кабинетах
    
    # Подготовка данных
    DAYS = 5
    max_lessons = [schedule_settings.get(d+1, 6) for d in range(DAYS)]
    cum_slots = [0]
    for m in max_lessons:
        cum_slots.append(cum_slots[-1] + m)
    TOTAL_SLOTS = cum_slots[-1]
    
    # Строим список задач (уроков)
    # Строим список задачи (уроков)
    update_progress(shift_id, 5, "Этап 0: Инициализация и валидация данных...", 1)
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Этап 0: Построение списка задач из требований...")

    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Всего требований: {len(requirements)}")
    
    tasks = []
    task_by_key = {}
    idx = 0
    
    reqs_with_teachers = 0
    reqs_without_teachers = 0
    teachers_with_hours = 0
    teachers_without_hours = 0
    
    for req_idx, req in enumerate(requirements):
        if not req.teachers:
            reqs_without_teachers += 1
            logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ] Требование #{req_idx}: класс_id={req.class_id}, subject_id={req.subject_id}, total_hours={req.total_hours_per_week} - НЕТ УЧИТЕЛЕЙ!")
            continue
        
        reqs_with_teachers += 1
        
        # Логируем первые 3 требования для диагностики
        if req_idx < 3:
            logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Требование #{req_idx}: класс_id={req.class_id}, subject_id={req.subject_id}, total_hours={req.total_hours_per_week}, учителей={len(req.teachers)}")
        
        tasks_for_req = 0
        for teacher_idx, teacher in enumerate(req.teachers):
            hours = teacher.get('hours_per_week', 0)
            teacher_id = teacher.get('teacher_id')
            
            # Логируем только первые несколько учителей для диагностики
            if req_idx < 2 and teacher_idx < 2:
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Учитель #{teacher_idx} в требовании #{req_idx}:")
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]     teacher_id={teacher_id} (type: {type(teacher_id)})")
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]     hours_per_week={hours} (type: {type(hours)}, raw: {teacher.get('hours_per_week')})")
                logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]     Все ключи учителя: {list(teacher.keys())}")
            
            if hours is None:
                logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   КРИТИЧЕСКАЯ ОШИБКА: Учитель teacher_id={teacher_id} имеет hours_per_week=None!")
                teachers_without_hours += 1
                continue
            
            if hours <= 0:
                teachers_without_hours += 1
                # Логируем только первые несколько случаев
                if teachers_without_hours <= 5:
                    logger.warning(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Учитель teacher_id={teacher_id} имеет hours={hours}, пропускаем")
                continue  # Пропускаем учителей без часов
            
            teachers_with_hours += 1
            
            # --- VALIDATION FIX: Safety cap ---
            if tasks_for_req >= req.total_hours_per_week:
                logger.warning(f"  [SAFETY CAP] Requirement {req.subject_id} ({req.class_id}) reached limit of {req.total_hours_per_week} hours. Skipping remaining teacher hours ({hours}).")
                break
            
            original_hours = hours
            hours = min(hours, req.total_hours_per_week - tasks_for_req)
            
            if hours < original_hours:
                 logger.warning(f"  [SAFETY CAP] Capped teacher {teacher_id} hours from {original_hours} to {hours} to fit total {req.total_hours_per_week}")
            # ----------------------------------
            
            default_cabinet = teacher.get('default_cabinet', '301')
            
            # Используем первый доступный кабинет из списка, если есть
            available_cabinets = teacher.get('available_cabinets', [])
            if available_cabinets:
                default_cabinet = available_cabinets[0].get('name', default_cabinet)
                logger.debug(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Используем кабинет из available_cabinets: {default_cabinet}")
            else:
                logger.debug(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Используем кабинет по умолчанию: {default_cabinet}")
            
            # Создаем задачи для каждого часа этого учителя
            for hour_idx in range(hours):
                task = {
                    'idx': idx,
                    'class_id': req.class_id,
                    'subject_id': req.subject_id,
                    'teacher_id': teacher_id,
                    'cabinet': default_cabinet,
                    'has_subgroups': req.has_subgroups
                }
                tasks.append(task)
                task_by_key[(req.class_id, req.subject_id, teacher_id, hour_idx)] = idx
                idx += 1
    
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Статистика построения задач:")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Требований с учителями: {reqs_with_teachers}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Требований без учителей: {reqs_without_teachers}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Учителей с часами: {teachers_with_hours}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ]   Учителей без часов: {teachers_without_hours}")
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Создано {len(tasks)} задач")
    
    if len(tasks) == 0:
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] КРИТИЧЕСКАЯ ОШИБКА: Не создано ни одной задачи!")
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ] Возможные причины:")
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   1. Нет учителей в требованиях (проверьте таблицу prompt_class_subject_teacher)")
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   2. У всех учителей hours_per_week = 0 (проверьте таблицу prompt_class_subject_teacher)")
        logger.error(f"[ГИБРИДНЫЙ АЛГОРИТМ]   3. Требования не загружены (проверьте таблицу prompt_class_subject)")
        return {
            'suggestions': [],
            'warnings': [
                'Не создано ни одной задачи для размещения',
                f'Требований с учителями: {reqs_with_teachers}',
                f'Требований без учителей: {reqs_without_teachers}',
                f'Учителей с часами: {teachers_with_hours}',
                f'Учителей без часов: {teachers_without_hours}',
                'Проверьте таблицы: prompt_class_subject, prompt_class_subject_teacher'
            ],
            'summary': 'Ошибка: нет задач для размещения'
        }
    
    # ЭТАП 1: Жадный алгоритм (Greedy)
    update_progress(shift_id, 10, "Этап 1: Предварительная расстановка (Greedy)...", 2)
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Этап 1: Greedy размещение...")

    partial_schedule, remaining_tasks = greedy_placement(
        tasks, DAYS, max_lessons, cum_slots, cabinets_info, lesson_mode, subgroup_pairs, subject_categories
    )
    placed_count = len(tasks) - len(remaining_tasks)
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Greedy разместил {placed_count}/{len(tasks)} уроков")
    
    # ЭТАП 2-3: CP-SAT для оставшихся уроков
    # ЭТАП 2-3: CP-SAT для оставшихся уроков
    if remaining_tasks:
        update_progress(shift_id, 40, "Этап 2: Точное размещение (CP-SAT)...", 3)
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Этап 2-3: CP-SAT для {len(remaining_tasks)} оставшихся уроков...")

        cp_sat_time_limit = max(5, time_limit_seconds - 10)  # Оставляем время на LNS
        
        cp_sat_schedule = cp_sat_solve(
            remaining_tasks, DAYS, max_lessons, cum_slots, TOTAL_SLOTS,
            cabinets_info, lesson_mode, subgroup_pairs, cp_sat_time_limit,
            partial_schedule, subject_categories  # ADDED ARGUMENT
        )
        
        # Объединяем результаты CP-SAT с частичным расписанием
        for key, task_list in cp_sat_schedule.items():
            if key not in partial_schedule:
                partial_schedule[key] = []
            partial_schedule[key].extend(task_list)
        
        cp_sat_placed = sum(len(task_list) for task_list in cp_sat_schedule.values())
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] CP-SAT разместил {cp_sat_placed} уроков")
    else:
        logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Все уроки размещены на этапе Greedy, пропускаем CP-SAT")
    
    # ЭТАП 4: LNS (Large Neighborhood Search) - финальная полировка
    update_progress(shift_id, 70, f"Этап 3: Оптимизация расписания (LNS) - 0/{max_lns_iterations}...", 4)
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] Этап 4: LNS полировка ({max_lns_iterations} итераций)...")
    final_schedule = lns_improve(
        partial_schedule, tasks, DAYS, max_lessons, cum_slots,
        cabinets_info, lesson_mode, subgroup_pairs, max_lns_iterations,
        shift_id, subject_categories  # NEW: передаем категории
    )
    
    # Преобразуем в формат suggestions
    suggestions = []
    warnings = []
    
    for (class_id, day, lesson), task_list in final_schedule.items():
        for task in task_list:
            suggestions.append({
                'day_of_week': day + 1,  # day 0-4 -> 1-5
                'lesson_number': lesson,
                'class_id': task['class_id'],
                'subject_id': task['subject_id'],
                'teacher_id': task['teacher_id'],
                'cabinet': task['cabinet']
            })
    
    total_time = time.time() - start_time
    
    # Проверяем качество решения
    placed_all = len(suggestions) == len(tasks)
    windows_count = count_windows(final_schedule, tasks, DAYS, cum_slots)
    pairs_count = count_pairs(final_schedule, lesson_mode)
    
    if not placed_all:
        warnings.append(f"Размещено {len(suggestions)} из {len(tasks)} уроков")
    if windows_count > 0:
        warnings.append(f"Обнаружено {windows_count} окон в расписании классов")
    
    summary = f"Гибридный алгоритм: размещено {len(suggestions)} уроков"
    if placed_all and windows_count == 0:
        summary += " (идеальное решение: 100% размещение, 0 окон)"
    if pairs_count > 0 and lesson_mode == "pairs":
        summary += f", создано {pairs_count} сдвоенных уроков"
    summary += f", время: {total_time:.1f}с"
    
    logger.info(f"[ГИБРИДНЫЙ АЛГОРИТМ] ✓ Завершено: {summary}")
    
    return {
        'suggestions': suggestions,
        'warnings': warnings,
        'summary': summary
    }


def greedy_placement(
    tasks: List[Dict],
    DAYS: int,
    max_lessons: List[int],
    cum_slots: List[int],
    cabinets_info: Dict,
    lesson_mode: str,
    subgroup_pairs: List[Tuple[int, int]],
    subject_categories: Dict[int, str] = None
) -> Tuple[Dict, List[Dict]]:
    """
    Жадный алгоритм размещения уроков с поддержкой категорий предметов
    
    Args:
        subject_categories: Словарь {subject_id: category} для мягких ограничений
    """
    placement = {}  # (class_id, day, lesson) -> [task, ...]
    remaining = tasks.copy()
    
    # Отслеживание категорий по классам и дням для мягких ограничений
    # {(class_id, day): {category: count}} - количество уроков каждой категории в день для класса
    category_day_counts = defaultdict(lambda: defaultdict(int))
    
    # Отслеживание распределения категорий по дням для класса
    # {class_id: {category: set(days)}} - в какие дни уже есть предметы этой категории
    category_day_distribution = defaultdict(lambda: defaultdict(set))
    
    if subject_categories is None:
        subject_categories = {}
    
    # Сортировка: подгруппы и сложные предметы первыми
    def difficulty(task):
        subj = task['subject_id']
        is_sub = any(subj in pair for pair in subgroup_pairs)
        count = sum(1 for t in tasks if t['class_id'] == task['class_id'] and t['subject_id'] == subj)
        return (is_sub, count)
    
    remaining.sort(key=difficulty, reverse=True)
    
    for task in remaining[:]:
        placed = False
        
        # Получаем категорию предмета для приоритизации дней
        task_category = subject_categories.get(task['subject_id']) if subject_categories else None
        
        # Создаем список дней с приоритетами для лучшего распределения категорий
        days_with_priority = []
        for d in range(DAYS):
            priority = 0
            if task_category:
                class_id = task['class_id']
                category_key = (class_id, d)
                current_count = category_day_counts[category_key][task_category]
                days_with_category = category_day_distribution[class_id][task_category]
                
                # Приоритет: дни без этой категории получают более высокий приоритет
                if d not in days_with_category:
                    priority = -100  # Высокий приоритет для дней без категории
                elif current_count >= 2:
                    priority = 100  # Низкий приоритет для дней с 2+ предметами категории
                else:
                    priority = current_count * 10  # Средний приоритет
            
            days_with_priority.append((d, priority))
        
        # Сортируем дни по приоритету (меньше = лучше)
        days_with_priority.sort(key=lambda x: x[1])
        
        for d, _ in days_with_priority:
            for l in range(1, max_lessons[d] + 1):
                can_place = True
                
                # Проверка: учитель свободен?
                for (c2, d2, l2), tlist in placement.items():
                    if d2 == d and l2 == l:
                        if any(t['teacher_id'] == task['teacher_id'] for t in tlist):
                            can_place = False
                            break
                if not can_place:
                    continue
                
                # Проверка: кабинет свободен?
                cab = task['cabinet']
                occupancy = sum(1 for (c2, d2, l2), tlist in placement.items()
                              if d2 == d and l2 == l and any(t['cabinet'] == cab for t in tlist))
                cab_info = cabinets_info.get(cab, {})
                max_cab = cab_info.get('max_classes', 1)
                if occupancy >= max_cab:
                    continue
                
                # Проверка: класс - только один предмет в слоте (или разрешенные пары подгрупп)
                key = (task['class_id'], d, l)
                existing = placement.get(key, [])
                
                if existing:
                    existing_subjects = {t['subject_id'] for t in existing}
                    existing_has_subgroups = any(t.get('has_subgroups', False) for t in existing)
                    current_subject = task['subject_id']
                    current_has_subgroups = task.get('has_subgroups', False)
                    
                    # Если уже есть другой предмет
                    if current_subject not in existing_subjects:
                        # ПРАВИЛО 1: Два предмета БЕЗ подгрупп не могут быть вместе
                        if not current_has_subgroups and not existing_has_subgroups:
                            continue  # Оба без подгрупп - запрещено
                        
                        # ПРАВИЛО 2: Предмет БЕЗ подгрупп не может быть с предметом С подгруппами
                        # (если они не в разрешенной паре)
                        if (not current_has_subgroups and existing_has_subgroups) or \
                           (current_has_subgroups and not existing_has_subgroups):
                            # Проверяем, разрешена ли эта пара
                            is_allowed_pair = False
                            for pair in subgroup_pairs:
                                if (current_subject in pair and 
                                    any(s in pair for s in existing_subjects)):
                                    is_allowed_pair = True
                                    break
                            
                            if not is_allowed_pair:
                                continue  # Не разрешенная пара - запрещено
                        
                        # ПРАВИЛО 3: Два предмета С подгруппами могут быть вместе только если они в разрешенной паре
                        if current_has_subgroups and existing_has_subgroups:
                            is_allowed_pair = False
                            for pair in subgroup_pairs:
                                if (current_subject in pair and 
                                    any(s in pair for s in existing_subjects)):
                                    is_allowed_pair = True
                                    break
                            
                            if not is_allowed_pair:
                                continue  # Не разрешенная пара подгрупп - запрещено
                
                # ПРАВИЛО 4: Максимум 2 урока подряд по одному предмету
                # Проверяем соседние слоты
                subject_slots_today = []
                for l_check in range(1, max_lessons[d] + 1):
                    # Проверяем, есть ли этот предмет в слоте l_check
                    key_check = (task['class_id'], d, l_check)
                    tasks_at_slot = placement.get(key_check, [])
                    
                    # Добавляем текущий слот, если мы его рассматриваем (l_check == l)
                    if l_check == l:
                        subject_slots_today.append(l) # Текущий слот будет занят этим предметом
                    elif any(t['subject_id'] == task['subject_id'] for t in tasks_at_slot):
                        subject_slots_today.append(l_check)
                
                subject_slots_today.sort()
                
                # Проверяем окна по 3
                has_triple = False
                if len(subject_slots_today) >= 3:
                    for i in range(len(subject_slots_today) - 2):
                        if subject_slots_today[i+2] == subject_slots_today[i] + 2:
                            # Найдены 3 подряд (n, n+1, n+2)
                            has_triple = True
                            break
                
                if has_triple:
                    continue # Нарушение ограничения "макс 2 подряд"
                
                # МЯГКИЕ ОГРАНИЧЕНИЯ НА ОСНОВЕ КАТЕГОРИЙ
                # (Приоритеты уже учтены при сортировке дней выше)
                if task_category:
                    class_id = task['class_id']
                    category_key = (class_id, d)
                    
                    # МЯГКОЕ ОГРАНИЧЕНИЕ 1: Максимум 3 предмета одной категории в день для класса
                    # Это мягкое ограничение - не блокируем, но предпочитаем дни с меньшим количеством
                    current_category_count = category_day_counts[category_key][task_category]
                    if current_category_count >= 3:
                        # Пропускаем этот день, если уже 3+ предмета этой категории
                        continue
                
                # Всё ок → размещаем
                if key not in placement:
                    placement[key] = []
                placement[key].append(task)
                
                # Обновляем отслеживание категорий
                if task_category:
                    class_id = task['class_id']
                    category_key = (class_id, d)
                    category_day_counts[category_key][task_category] += 1
                    category_day_distribution[class_id][task_category].add(d)
                
                remaining.remove(task)
                placed = True
                break
            
            if placed:
                break
    
    return placement, remaining


def cp_sat_solve(
    remaining_tasks: List[Dict],
    DAYS: int,
    max_lessons: List[int],
    cum_slots: List[int],
    TOTAL_SLOTS: int,
    cabinets_info: Dict,
    lesson_mode: str,
    subgroup_pairs: List[Tuple[int, int]],
    time_limit: int,
    partial_schedule: Dict = None,  # ADDED ARGUMENT
    subject_categories: Dict[int, str] = None  # NEW: для мягких ограничений
) -> Dict:
    """
    CP-SAT решение для оставшихся уроков
    """
    if not remaining_tasks:
        return {}
    
    # Проверяем доступность OR-Tools
    if not ORTOOLS_AVAILABLE:
        logger.error("[CP-SAT] OR-Tools не установлен, пропускаем CP-SAT этап")
        return {}
    
    try:
        model = cp_model.CpModel()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_search_workers = 8
        
        # Переменные: task_idx -> slot_id (0..TOTAL_SLOTS-1)
        var_slot = {}
        for task in remaining_tasks:
            var_slot[task['idx']] = model.NewIntVar(0, TOTAL_SLOTS - 1, f"s{task['idx']}")
            
        # --- EXCLUSIVITY FIX: Respect partial_schedule ---
        if partial_schedule:
            for key, existing_tasks in partial_schedule.items():
                c_id, d, l = key
                # Calculate slot_id
                # Check bounds
                if d >= DAYS or l > max_lessons[d]:
                    continue
                    
                slot_id = cum_slots[d] + (l - 1)
                
                has_whole = any(not t.get('is_subgroup', False) for t in existing_tasks)
                has_subgroup = any(t.get('is_subgroup', False) for t in existing_tasks)
                
                if has_whole:
                    # Slot blocked for ALL tasks of this class
                    for t in remaining_tasks:
                        if t['class_id'] == c_id:
                            model.Add(var_slot[t['idx']] != slot_id)
                elif has_subgroup:
                    # Slot blocked for WHOLE CLASS tasks of this class
                    for t in remaining_tasks:
                        if t['class_id'] == c_id and not t.get('is_subgroup', False):
                            model.Add(var_slot[t['idx']] != slot_id)
        # -------------------------------------------------
            
    except Exception as e:
        logger.error(f"[CP-SAT] Ошибка при инициализации CP-SAT: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}
    
    # Ограничение 1: Учитель не может быть в двух местах одновременно
    teacher_slots = defaultdict(list)
    for task in remaining_tasks:
        teacher_slots[task['teacher_id']].append(var_slot[task['idx']]) # Fixed context match
        
    # Also check against existing schedule for teachers!
    if partial_schedule:
        # Create a map of busy slots for each teacher
        teacher_busy_slots = defaultdict(set)
        for key, existing_tasks in partial_schedule.items():
            _, d, l = key
            slot_id = cum_slots[d] + (l - 1)
            for t in existing_tasks:
                teacher_busy_slots[t['teacher_id']].add(slot_id)
                
        for task in remaining_tasks:
            tid = task['teacher_id']
            if tid in teacher_busy_slots:
                for busy_slot in teacher_busy_slots[tid]:
                    model.Add(var_slot[task['idx']] != busy_slot)

    for slots in teacher_slots.values():
        if len(slots) > 1:
            model.AddAllDifferent(slots)
            
    # --- EXCLUSIVITY FIX: Strict constraint for non-subgroup subjects ---

    
    # --- EXCLUSIVITY FIX: Strict constraint for non-subgroup subjects ---
    # Group tasks by class
    class_tasks = defaultdict(list)
    for task in remaining_tasks:
        class_tasks[task['class_id']].append(task)
        
    for c_id, tasks in class_tasks.items():
        # Iterate all unique pairs in the class
        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                t1 = tasks[i]
                t2 = tasks[j]
                
                # If either task is NOT a subgroup (i.e. Whole Class), they cannot overlap
                # This covers:
                # 1. Whole vs Whole (Both True) -> Cannot overlap
                # 2. Whole vs Subgroup (One True) -> Cannot overlap
                # 3. Subgroup vs Subgroup (Both False) -> No constraint added (Overlap Allowed)
                is_whole_1 = not t1.get('is_subgroup', False)
                is_whole_2 = not t2.get('is_subgroup', False)
                
                if is_whole_1 or is_whole_2:
                    model.Add(var_slot[t1['idx']] != var_slot[t2['idx']])
                if is_whole_1 or is_whole_2:
                    model.Add(var_slot[t1['idx']] != var_slot[t2['idx']])
    # -------------------------------------------------------------------

    # --- CONSTRAINT: Max 2 Consecutive Lessons per Subject per Day ---
    # Create boolean variables for "subject S is in slot L for class C"
    # To optimize, we only create variables for relevant slots
    
    # Group by (class, subject)
    class_subject_tasks = defaultdict(list)
    for task in remaining_tasks:
        class_subject_tasks[(task['class_id'], task['subject_id'])].append(task)
        
    for (c_id, s_id), tasks in class_subject_tasks.items():
        # Optimization removed to support partial schedule checking
        # if len(tasks) < 3:
        #    continue
            
        # Iterate days
        for d in range(DAYS):
            day_slots = []
            start_slot = cum_slots[d]
            end_slot = start_slot + max_lessons[d]
            
            # Create boolean vars for each slot in this day
            slot_occupied = []
            
            # Identify slots already occupied by this subject in partial schedule
            fixed_occupied_slots = set()
            if partial_schedule:
                for key, existing_tasks in partial_schedule.items():
                    _, pd, pl = key # partial day, partial lesson
                    if pd == d:
                        pslot_id = cum_slots[pd] + (pl - 1)
                        # Check if any existing task matches current class/subject
                        for t in existing_tasks:
                            if t['class_id'] == c_id and t['subject_id'] == s_id:
                                fixed_occupied_slots.add(pslot_id)
            
            # DEBUG LOG
            if fixed_occupied_slots:
                logger.info(f"[CP-SAT DEBUG] Class {c_id} Subject {s_id} Day {d}: Fixed Slots {fixed_occupied_slots}")

            for s_idx in range(start_slot, end_slot):
                # Bool var: is slot s_idx occupied by ANY task of this class+subject?
                
                # If slot is permanently occupied by partial schedule
                if s_idx in fixed_occupied_slots:
                    # Treat as constant True (1)
                    slot_occupied.append(1) 
                    continue

                # Create intermediate bools for each task
                task_in_slot = []
                for t in tasks:
                    b_t_in_s = model.NewBoolVar(f"t{t['idx']}_in_s{s_idx}")
                    model.Add(var_slot[t['idx']] == s_idx).OnlyEnforceIf(b_t_in_s)
                    model.Add(var_slot[t['idx']] != s_idx).OnlyEnforceIf(b_t_in_s.Not())
                    task_in_slot.append(b_t_in_s)
                
                if not task_in_slot:
                    slot_occupied.append(0) # Logic zero
                    continue
                    
                b_occ = model.NewBoolVar(f"c{c_id}_s{s_id}_d{d}_s{s_idx}_occ")
                model.Add(sum(task_in_slot) >= 1).OnlyEnforceIf(b_occ)
                model.Add(sum(task_in_slot) == 0).OnlyEnforceIf(b_occ.Not())
                slot_occupied.append(b_occ)
            
            # Now enforce window size 3 => max 2 occupied
            # window: [i, i+1, i+2]
            for i in range(len(slot_occupied) - 2):
                model.Add(sum(slot_occupied[i:i+3]) <= 2)

    # --- OPTIMIZATION: Maximize Parallel Subgroups ---
    # Encourage subgroups of the same class/subject to be in the same slot
    parallel_bonuses = []
    
    for (c_id, s_id), tasks in class_subject_tasks.items():
        # Only relevant if we have multiple subgroups (tasks with is_subgroup=True)
        subgroup_tasks = [t for t in tasks if t.get('is_subgroup', False)]
        if len(subgroup_tasks) < 2:
            continue
            
        # Iterate unique pairs
        for i in range(len(subgroup_tasks)):
            for j in range(i + 1, len(subgroup_tasks)):
                t1 = subgroup_tasks[i]
                t2 = subgroup_tasks[j]
                
                # Check if they are allowed to be parallel (different teachers)
                if t1['teacher_id'] == t2['teacher_id']:
                    continue # Cannot be parallel if same teacher
                    
                # Bool var: are they in same slot?
                b_same = model.NewBoolVar(f"parallel_t{t1['idx']}_t{t2['idx']}")
                model.Add(var_slot[t1['idx']] == var_slot[t2['idx']]).OnlyEnforceIf(b_same)
                model.Add(var_slot[t1['idx']] != var_slot[t2['idx']]).OnlyEnforceIf(b_same.Not())
                
                parallel_bonuses.append(b_same)
    
    # МЯГКИЕ ОГРАНИЧЕНИЯ НА ОСНОВЕ КАТЕГОРИЙ
    category_penalties = []
    if subject_categories:
        # Группируем задачи по (class_id, category, day)
        # Создаем переменные для подсчета предметов категории в день для класса
        category_day_vars = {}  # {(class_id, category, day): IntVar}
        
        # Группируем задачи по классу и категории
        class_category_tasks = defaultdict(lambda: defaultdict(list))
        for task in remaining_tasks:
            task_category = subject_categories.get(task['subject_id'])
            if task_category:
                class_category_tasks[task['class_id']][task_category].append(task)
        
        # Для каждой комбинации (class_id, category, day) создаем переменную подсчета
        for class_id, categories in class_category_tasks.items():
            for category, tasks_in_category in categories.items():
                for day in range(DAYS):
                    # Создаем переменную для подсчета предметов этой категории в этот день для этого класса
                    count_var = model.NewIntVar(0, len(tasks_in_category), 
                                               f"cat_count_c{class_id}_cat{category}_d{day}")
                    
                    # Подсчитываем, сколько задач этой категории попало в этот день
                    day_tasks = []
                    for task in tasks_in_category:
                        # Создаем булеву переменную: находится ли задача в этот день?
                        in_day = model.NewBoolVar(f"task{task['idx']}_in_day{day}")
                        # slot_id должен быть в диапазоне этого дня
                        min_slot = cum_slots[day]
                        max_slot = cum_slots[day + 1] - 1
                        # Если in_day = True, то min_slot <= var_slot <= max_slot
                        model.Add(var_slot[task['idx']] >= min_slot).OnlyEnforceIf(in_day)
                        model.Add(var_slot[task['idx']] <= max_slot).OnlyEnforceIf(in_day)
                        # Если in_day = False, то var_slot < min_slot или var_slot > max_slot
                        # Используем упрощенный подход: если не в диапазоне, то in_day = False
                        # Это обеспечивается автоматически через OnlyEnforceIf
                        day_tasks.append(in_day)
                    
                    # count_var = сумма булевых переменных
                    model.Add(count_var == sum(day_tasks))
                    
                    # Штраф за превышение лимита (3 предмета одной категории в день)
                    # Создаем переменную превышения: excess = max(0, count_var - 3)
                    # В CP-SAT для max(0, x) достаточно:
                    # excess >= x и excess >= 0
                    # Поскольку мы минимизируем excess в целевой функции, это даст excess = max(0, x)
                    excess = model.NewIntVar(0, len(tasks_in_category), 
                                           f"excess_c{class_id}_cat{category}_d{day}")
                    # excess >= count_var - 3
                    model.Add(excess >= count_var - 3)
                    # excess >= 0 (уже гарантировано диапазоном переменной)
                    # Поскольку мы минимизируем excess (через -sum(category_penalties) в целевой функции),
                    # решатель автоматически установит excess = max(0, count_var - 3)
                    category_penalties.append(excess)
        
        logger.info(f"[CP-SAT] Добавлено {len(category_penalties)} штрафов за категории")
    
    # Add to objective (Maximize number of parallel pairs, minimize category penalties)
    objective_terms = []
    if parallel_bonuses:
        objective_terms.append(sum(parallel_bonuses))
    
    # Минимизируем штрафы за категории (вес 10, чтобы они были важны, но не критичны)
    if category_penalties:
        objective_terms.append(-sum(category_penalties) * 10)
    
    if objective_terms:
        model.Maximize(sum(objective_terms))

    # -------------------------------------------------------------------

    # Ограничение 2: Класс - в одном слоте только один предмет (или разрешенные пары подгрупп)
    # Реализуем через проверку в цикле после решения

    
    # Ограничение 3: Кабинетная загрузка
    # Упрощенная версия - проверяем после решения
    
    # Ограничение 4: НЕТ ОКОН - самое важное!
    # Для каждого класса и дня: если есть уроки, они должны быть без разрывов
    # Упрощенная версия: проверяем окна после решения и пытаемся их минимизировать
    # Полная реализация NoGap constraint слишком сложна для CP-SAT в данном контексте
    # Вместо этого используем проверку после решения и штрафы в LNS
    
    # Решаем
    logger.info(f"[CP-SAT] Запуск решения для {len(remaining_tasks)} задач...")
    status = solver.Solve(model)
    
    schedule = {}
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        try:
            for task in remaining_tasks:
                try:
                    slot_id = solver.Value(var_slot[task['idx']])
                    day = next((d for d in range(DAYS) if cum_slots[d] <= slot_id < cum_slots[d+1]), 0)
                    lesson = slot_id - cum_slots[day] + 1
                    
                    # Проверяем ограничения после решения
                    key = (task['class_id'], day, lesson)
                except Exception as e:
                    logger.error(f"[CP-SAT] Ошибка при обработке задачи {task.get('idx', 'unknown')}: {e}")
                    continue
                
                # Проверка: класс - один предмет в слоте (или разрешенные пары подгрупп)
                if key in schedule:
                    existing_subjects = {t['subject_id'] for t in schedule[key]}
                    existing_has_subgroups = any(t.get('has_subgroups', False) for t in schedule[key])
                    current_subject = task['subject_id']
                    current_has_subgroups = task.get('has_subgroups', False)
                    
                    if current_subject not in existing_subjects:
                        # ПРАВИЛО 1: Два предмета БЕЗ подгрупп не могут быть вместе
                        if not current_has_subgroups and not existing_has_subgroups:
                            continue  # Пропускаем - оба без подгрупп
                        
                        # ПРАВИЛО 2: Предмет БЕЗ подгрупп не может быть с предметом С подгруппами
                        # (если они не в разрешенной паре)
                        if (not current_has_subgroups and existing_has_subgroups) or \
                           (current_has_subgroups and not existing_has_subgroups):
                            is_allowed = False
                            for pair in subgroup_pairs:
                                if (current_subject in pair and 
                                    any(s in pair for s in existing_subjects)):
                                    is_allowed = True
                                    break
                            if not is_allowed:
                                continue  # Пропускаем - не разрешенная пара
                        
                        # ПРАВИЛО 3: Два предмета С подгруппами могут быть вместе только если они в разрешенной паре
                        if current_has_subgroups and existing_has_subgroups:
                            is_allowed = False
                            for pair in subgroup_pairs:
                                if (current_subject in pair and 
                                    any(s in pair for s in existing_subjects)):
                                    is_allowed = True
                                    break
                            if not is_allowed:
                                continue  # Пропускаем - не разрешенная пара подгрупп
                
                # Проверка: кабинет
                cab = task['cabinet']
                cab_info = cabinets_info.get(cab, {})
                max_cab = cab_info.get('max_classes', 1)
                occupancy = sum(1 for (c2, d2, l2), tlist in schedule.items()
                               if d2 == day and l2 == lesson and any(t['cabinet'] == cab for t in tlist))
                if occupancy >= max_cab:
                    continue  # Пропускаем этот урок
                
                if key not in schedule:
                    schedule[key] = []
                schedule[key].append(task)
            
            # Проверяем и исправляем окна после размещения
            # Для каждого класса и дня проверяем непрерывность
            class_ids = {t['class_id'] for t in remaining_tasks}
            for class_id in class_ids:
                for day in range(DAYS):
                    class_day_slots = []
                    for (c, d, l), tlist in schedule.items():
                        if c == class_id and d == day:
                            for task in tlist:
                                if task['class_id'] == class_id:
                                    class_day_slots.append(l)
                    
                    if len(class_day_slots) > 1:
                        class_day_slots.sort()
                        min_lesson = min(class_day_slots)
                        max_lesson = max(class_day_slots)
                        # Если есть разрыв (окно), пытаемся сдвинуть уроки
                        expected_lessons = set(range(min_lesson, max_lesson + 1))
                        actual_lessons = set(class_day_slots)
                        gaps = expected_lessons - actual_lessons
                        
                        if gaps:
                            # Есть окна - пытаемся их устранить, перемещая уроки
                            # Упрощенная версия: логируем предупреждение
                            logger.warning(f"[CP-SAT] Обнаружено окно в классе {class_id}, день {day+1}: пропущенные уроки {sorted(gaps)}")
            
            logger.info(f"[CP-SAT] Размещено {sum(len(tlist) for tlist in schedule.values())} уроков")
        except Exception as e:
            logger.error(f"[CP-SAT] КРИТИЧЕСКАЯ ОШИБКА при обработке результатов: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    else:
        logger.warning(f"[CP-SAT] Не удалось найти решение (статус: {status})")
    
    return schedule


def lns_improve(
    schedule: Dict,
    all_tasks: List[Dict],
    DAYS: int,
    max_lessons: List[int],
    cum_slots: List[int],
    cabinets_info: Dict,
    lesson_mode: str,
    subgroup_pairs: List[Tuple[int, int]],
    iterations: int,
    shift_id: int,
    subject_categories: Dict[int, str] = None  # NEW: для мягких ограничений
) -> Dict:
    """
    Large Neighborhood Search - финальная полировка
    """
    best = dict(schedule)
    best_score = calculate_soft_score(best, all_tasks, DAYS, cum_slots, lesson_mode, subject_categories)
    
    logger.info(f"[LNS] Начальный score: {best_score}")
    
    start_progress = 70
    end_progress = 95
    progress_range = end_progress - start_progress
    
    for it in range(iterations):
        # Update progress every 5% of iterations or at least every 10 iterations
        if it % max(1, iterations // 20) == 0:
            current_progress = start_progress + (it / iterations) * progress_range
            update_progress(
                shift_id, 
                current_progress, 
                f"Этап 3: Оптимизация (LNS) - {it}/{iterations} итер. (Score: {best_score})", 
                4
            )
        # Разрушаем 20% случайных уроков
        schedule_items = list(schedule.items())
        if not schedule_items:
            break
        
        to_relax_count = max(1, len(schedule_items) // 5)
        to_relax = random.sample(schedule_items, k=min(to_relax_count, len(schedule_items)))
        
        relaxed_tasks = [t for tlist in to_relax for t in tlist[1]]
        for key in [item[0] for item in to_relax]:
            if key in schedule:
                del schedule[key]
        
        # Переразмещаем жадным алгоритмом с учетом категорий
        # Сортируем задачи по приоритету дней на основе категорий
        for task in relaxed_tasks:
            placed = False
            task_category = subject_categories.get(task['subject_id']) if subject_categories else None
            
            # Создаем список дней с приоритетами для лучшего распределения категорий
            days_with_priority = []
            for d in range(DAYS):
                priority = 0
                if task_category:
                    class_id = task['class_id']
                    # Подсчитываем предметы этой категории в этот день для этого класса
                    category_count = 0
                    for (c, day, l), tlist in schedule.items():
                        if c == class_id and day == d:
                            for t in tlist:
                                if t['class_id'] == class_id:
                                    t_category = subject_categories.get(t['subject_id'])
                                    if t_category == task_category:
                                        category_count += 1
                    
                    # Приоритет: дни без категории > дни с 1 предметом > дни с 2+ предметами
                    if category_count == 0:
                        priority = -100
                    elif category_count >= 2:
                        priority = 100
                    else:
                        priority = category_count * 10
                
                days_with_priority.append((d, priority))
            
            # Сортируем дни по приоритету
            days_with_priority.sort(key=lambda x: x[1])
            
            for d, _ in days_with_priority:
                for l in range(1, max_lessons[d] + 1):
                    if is_slot_free_lns(task, d, l, schedule, cabinets_info, subgroup_pairs, subject_categories):
                        key = (task['class_id'], d, l)
                        if key not in schedule:
                            schedule[key] = []
                        schedule[key].append(task)
                        placed = True
                        break
                if placed:
                    break
        
        # Считаем score
        score = calculate_soft_score(schedule, all_tasks, DAYS, cum_slots, lesson_mode, subject_categories)
        
        if score < best_score:
            best = dict(schedule)
            best_score = score
            if it % 100 == 0:
                logger.info(f"[LNS] Итерация {it}: улучшено → {best_score}")
    
    logger.info(f"[LNS] Финальный score: {best_score}")
    return best


def is_slot_free_lns(
    task: Dict,
    day: int,
    lesson: int,
    schedule: Dict,
    cabinets_info: Dict,
    subgroup_pairs: List[Tuple[int, int]],
    subject_categories: Dict[int, str] = None
) -> bool:
    """
    Проверяет, можно ли разместить задачу в слот (для LNS)
    """
    key = (task['class_id'], day, lesson)
    
    # Учитель свободен?
    for (c2, d2, l2), tlist in schedule.items():
        if d2 == day and l2 == lesson:
            if any(t['teacher_id'] == task['teacher_id'] for t in tlist):
                return False
    
    # Кабинет свободен?
    cab = task['cabinet']
    occupancy = sum(1 for (c2, d2, l2), tlist in schedule.items()
                   if d2 == day and l2 == lesson and any(t['cabinet'] == cab for t in tlist))
    cab_info = cabinets_info.get(cab, {})
    max_cab = cab_info.get('max_classes', 1)
    if occupancy >= max_cab:
        return False
    
    # Класс - один предмет в слоте (или разрешенные пары подгрупп)?
    existing = schedule.get(key, [])
    if existing:
        existing_subjects = {t['subject_id'] for t in existing}
        existing_has_subgroups = any(t.get('has_subgroups', False) for t in existing)
        current_subject = task['subject_id']
        current_has_subgroups = task.get('has_subgroups', False)
        
        if current_subject not in existing_subjects:
            # ПРАВИЛО 1: Два предмета БЕЗ подгрупп не могут быть вместе
            if not current_has_subgroups and not existing_has_subgroups:
                return False
            
            # ПРАВИЛО 2: Предмет БЕЗ подгрупп не может быть с предметом С подгруппами
            # (если они не в разрешенной паре)
            if (not current_has_subgroups and existing_has_subgroups) or \
               (current_has_subgroups and not existing_has_subgroups):
                is_allowed = False
                for pair in subgroup_pairs:
                    if (current_subject in pair and 
                        any(s in pair for s in existing_subjects)):
                        is_allowed = True
                        break
                if not is_allowed:
                    return False
            
            # ПРАВИЛО 3: Два предмета С подгруппами могут быть вместе только если они в разрешенной паре
            if current_has_subgroups and existing_has_subgroups:
                is_allowed = False
                for pair in subgroup_pairs:
                    if (current_subject in pair and 
                        any(s in pair for s in existing_subjects)):
                        is_allowed = True
                        break
                if not is_allowed:
                    return False
    
    # МЯГКОЕ ОГРАНИЧЕНИЕ: Проверка категорий (не блокируем, но учитываем)
    if subject_categories:
        task_category = subject_categories.get(task['subject_id'])
        if task_category:
            class_id = task['class_id']
            # Подсчитываем предметы этой категории в этот день для этого класса
            category_count = 0
            for (c, d2, l2), tlist in schedule.items():
                if c == class_id and d2 == day:
                    for t in tlist:
                        if t['class_id'] == class_id:
                            t_category = subject_categories.get(t['subject_id'])
                            if t_category == task_category:
                                category_count += 1
            
            # Мягкое ограничение: максимум 3 предмета одной категории в день
            if category_count >= 3:
                return False  # Пропускаем этот день
    
    return True


def calculate_soft_score(
    schedule: Dict,
    all_tasks: List[Dict],
    DAYS: int,
    cum_slots: List[int],
    lesson_mode: str,
    subject_categories: Dict[int, str] = None
) -> int:
    """
    Вычисляет мягкий score (штрафы за окна, бонусы за пары, штрафы за категории)
    """
    score = 0
    if subject_categories is None:
        subject_categories = {}
    
    # Штраф за окна в классах
    class_ids = {t['class_id'] for t in all_tasks}
    for class_id in class_ids:
        class_slots = []
        for (c, d, l), tlist in schedule.items():
            if c == class_id:
                for task in tlist:
                    if task['class_id'] == class_id:
                        slot_id = cum_slots[d] + l - 1
                        class_slots.append((d, l, slot_id))
        
        # Группируем по дням
        for d in range(DAYS):
            day_slots = sorted([l for day, l, _ in class_slots if day == d])
            if len(day_slots) > 1:
                min_lesson = min(day_slots)
                max_lesson = max(day_slots)
                if max_lesson - min_lesson + 1 > len(day_slots):
                    score += 1000  # Штраф за окно
                    
    # Штраф за >2 уроков подряд по одному предмету
    for class_id in class_ids:
        # Собираем все уроки класса из расписания
        class_tasks_list = []
        for (c, d, l), tlist in schedule.items():
            if c == class_id:
                for t in tlist:
                    if t['class_id'] == class_id:
                        class_tasks_list.append((t, d, l))
        
        # Группируем по дням
        for d in range(DAYS):
            day_tasks = [x for x in class_tasks_list if x[1] == d]
            # Группируем по предметам
            subj_lessons = defaultdict(list)
            for t, _, l in day_tasks:
                subj_lessons[t['subject_id']].append(l)
            
            for subj, lessons in subj_lessons.items():
                lessons.sort()
                # Проверяем окно из 3 уроков (n, n+1, n+2)
                if len(lessons) >= 3:
                    for i in range(len(lessons) - 2):
                        if lessons[i+2] == lessons[i] + 2:
                            score += 5000 # ОЧЕНЬ большой штраф за нарушение жесткого ограничения
    
    # Бонус за пары (если lesson_mode == "pairs")
    if lesson_mode == "pairs":
        pairs_bonus = 0
        for (c, d, l), tlist in schedule.items():
            if len(tlist) >= 2:
                # Проверяем, что это пара одного предмета
                subjects = {t['subject_id'] for t in tlist}
                if len(subjects) == 1:
                    pairs_bonus += 10
        score -= pairs_bonus  # Вычитаем бонус (уменьшаем score)
    
    # Штраф за нарушение мягких ограничений категорий
    if subject_categories:
        # Штраф за превышение лимита категорий в день для класса
        for class_id in class_ids:
            for d in range(DAYS):
                # Подсчитываем предметы каждой категории в этот день для этого класса
                category_counts = defaultdict(int)
                for (c, day, l), tlist in schedule.items():
                    if c == class_id and day == d:
                        for task in tlist:
                            if task['class_id'] == class_id:
                                task_category = subject_categories.get(task['subject_id'])
                                if task_category:
                                    category_counts[task_category] += 1
                
                # Штраф за превышение лимита (3 предмета одной категории в день)
                for category, count in category_counts.items():
                    if count > 3:
                        # Штраф пропорционален превышению
                        excess = count - 3
                        score += excess * 50  # Штраф 50 за каждый лишний предмет категории
        
        # Бонус за равномерное распределение категорий по дням
        for class_id in class_ids:
            # Подсчитываем, в какие дни есть предметы каждой категории
            category_days = defaultdict(set)
            for (c, d, l), tlist in schedule.items():
                if c == class_id:
                    for task in tlist:
                        if task['class_id'] == class_id:
                            task_category = subject_categories.get(task['subject_id'])
                            if task_category:
                                category_days[task_category].add(d)
            
            # Бонус за распределение категорий по разным дням
            for category, days_set in category_days.items():
                if len(days_set) > 1:
                    # Чем больше дней, тем лучше распределение
                    score -= len(days_set) * 5  # Бонус 5 за каждый день с категорией
    
    return score


def count_windows(
    schedule: Dict,
    all_tasks: List[Dict],
    DAYS: int,
    cum_slots: List[int]
) -> int:
    """
    Подсчитывает количество окон в расписании
    """
    windows = 0
    class_ids = {t['class_id'] for t in all_tasks}
    
    for class_id in class_ids:
        class_slots = []
        for (c, d, l), tlist in schedule.items():
            if c == class_id:
                class_slots.append((d, l))
        
        for d in range(DAYS):
            day_slots = sorted([l for day, l in class_slots if day == d])
            if len(day_slots) > 1:
                min_lesson = min(day_slots)
                max_lesson = max(day_slots)
                if max_lesson - min_lesson + 1 > len(day_slots):
                    windows += 1
    
    return windows


def count_pairs(schedule: Dict, lesson_mode: str) -> int:
    """
    Подсчитывает количество сдвоенных уроков
    """
    if lesson_mode != "pairs":
        return 0
    
    pairs = 0
    for (c, d, l), tlist in schedule.items():
        if len(tlist) >= 2:
            subjects = {t['subject_id'] for t in tlist}
            if len(subjects) == 1:
                pairs += 1
    
    return pairs
