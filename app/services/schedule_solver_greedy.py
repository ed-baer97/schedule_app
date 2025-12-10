"""
Жадный алгоритм составления расписания
Быстрый алгоритм, который размещает уроки по приоритетам
"""
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
import logging
import random

from app.services.schedule_solver import ClassSubjectRequirement, LessonSlot

logger = logging.getLogger(__name__)


def solve_schedule_greedy(
    requirements: List[ClassSubjectRequirement],
    shift_id: int,
    existing_schedule: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    schedule_settings: Optional[Dict[int, int]] = None,
    clear_existing: bool = False
) -> Dict:
    """
    Решает задачу составления расписания используя жадный алгоритм
    
    Args:
        requirements: Список требований для составления расписания
        shift_id: ID смены
        existing_schedule: Существующее расписание
        schedule_settings: Настройки расписания {day: lessons_count}
        clear_existing: Очищать ли существующее расписание
    
    Returns:
        Словарь с результатами:
        {
            'suggestions': [список предложений],
            'warnings': [список предупреждений],
            'summary': 'текстовая сводка'
        }
    """
    if not requirements:
        return {
            'suggestions': [],
            'warnings': ['Нет требований для составления расписания'],
            'summary': 'Нет данных для составления расписания'
        }
    
    # Подготовка данных
    if schedule_settings is None:
        schedule_settings = {day: 6 for day in range(1, 8)}
    
    if existing_schedule is None:
        existing_schedule = {}
    
    logger.info(f"Начало жадного алгоритма для смены {shift_id}")
    logger.info(f"Требований: {len(requirements)}")
    
    # Создаем структуры для отслеживания размещенных уроков
    placed_lessons = []  # Список размещенных уроков
    teacher_schedule = defaultdict(set)  # {(teacher_id, day, slot): set()}
    class_schedule = defaultdict(set)  # {(class_id, day, slot): set()}
    cabinet_schedule = defaultdict(lambda: defaultdict(set))  # {cabinet: {(day, slot): set(class_ids)}}
    subject_day_count = defaultdict(int)  # {(class_id, subject_id, day): count}
    
    # Создаем список задач для размещения
    tasks = []
    for req_idx, req in enumerate(requirements):
        for teacher_idx, teacher in enumerate(req.teachers):
            teacher_id = teacher['teacher_id']
            hours = teacher.get('hours_per_week', 0)
            available_cabinets = teacher.get('available_cabinets', [])
            
            for _ in range(hours):
                tasks.append({
                    'req_idx': req_idx,
                    'req': req,
                    'teacher_idx': teacher_idx,
                    'teacher_id': teacher_id,
                    'available_cabinets': available_cabinets,
                    'priority': _calculate_priority(req, teacher, available_cabinets)
                })
    
    # Сортируем задачи по приоритету (высший приоритет первым)
    tasks.sort(key=lambda x: x['priority'], reverse=True)
    
    # Размещаем задачи жадным алгоритмом
    warnings = []
    placed_count = 0
    
    for task in tasks:
        req = task['req']
        teacher_id = task['teacher_id']
        class_id = req.class_id
        subject_id = req.subject_id
        available_cabinets = task['available_cabinets']
        
        # Пытаемся найти подходящий слот
        placed = False
        
        # Перебираем дни и слоты
        for day in sorted(schedule_settings.keys()):
            # Проверяем ограничение: не более 2 уроков одного предмета в день
            if subject_day_count[(class_id, subject_id, day)] >= 2:
                continue
            
            max_lessons = schedule_settings[day]
            
            for slot in range(1, max_lessons + 1):
                # Проверяем конфликты
                if not _can_place_lesson(
                    teacher_id, class_id, subject_id, day, slot,
                    teacher_schedule, class_schedule, cabinet_schedule,
                    req.has_subgroups, available_cabinets, cabinet_schedule
                ):
                    continue
                
                # Выбираем лучший кабинет
                cabinet = _select_best_cabinet(
                    available_cabinets, day, slot, class_id,
                    cabinet_schedule, req.has_subgroups
                )
                
                if not cabinet:
                    continue
                
                # Размещаем урок
                placed_lessons.append({
                    'day_of_week': day,
                    'lesson_number': slot,
                    'class_id': class_id,
                    'subject_id': subject_id,
                    'teacher_id': teacher_id,
                    'cabinet': cabinet
                })
                
                # Обновляем структуры отслеживания
                teacher_schedule[(teacher_id, day, slot)].add((class_id, subject_id))
                class_schedule[(class_id, day, slot)].add((subject_id, teacher_id))
                cabinet_schedule[cabinet][(day, slot)].add(class_id)
                subject_day_count[(class_id, subject_id, day)] += 1
                
                placed = True
                placed_count += 1
                break
            
            if placed:
                break
        
        if not placed:
            warnings.append(
                f"Не удалось разместить урок: класс {req.class_name}, предмет {req.subject_name}, "
                f"учитель ID {teacher_id}"
            )
    
    logger.info(f"Жадный алгоритм завершен: размещено {placed_count} из {len(tasks)} уроков")
    
    summary = f"Жадный алгоритм: обработано {len(requirements)} требований, размещено {placed_count} уроков"
    
    return {
        'suggestions': placed_lessons,
        'warnings': warnings,
        'summary': summary
    }


def _calculate_priority(req: ClassSubjectRequirement, teacher: Dict, available_cabinets: List[Dict]) -> float:
    """
    Вычисляет приоритет задачи для размещения
    
    Приоритет выше для:
    - Подгрупп (нужно размещать вместе)
    - Учителей с меньшим количеством доступных кабинетов
    - Предметов с большей нагрузкой
    """
    priority = 0.0
    
    # Подгруппы имеют высокий приоритет
    if req.has_subgroups:
        priority += 1000
    
    # Меньше доступных кабинетов = выше приоритет
    if available_cabinets:
        priority += 100.0 / len(available_cabinets)
    
    # Больше нагрузка = выше приоритет
    priority += req.total_hours_per_week * 10
    
    # Добавляем случайность для разнообразия
    priority += random.random() * 0.1
    
    return priority


def _can_place_lesson(
    teacher_id: int,
    class_id: int,
    subject_id: int,
    day: int,
    slot: int,
    teacher_schedule: Dict,
    class_schedule: Dict,
    cabinet_schedule: Dict,
    has_subgroups: bool,
    available_cabinets: List[Dict],
    cabinet_info: Dict
) -> bool:
    """
    Проверяет, можно ли разместить урок в указанном слоте
    """
    # Проверка 1: Учитель не может быть в двух местах одновременно
    # (исключение: подгруппы в одном классе)
    teacher_conflicts = teacher_schedule.get((teacher_id, day, slot), set())
    if teacher_conflicts:
        # Проверяем, не является ли это подгруппой
        if not has_subgroups:
            return False
        # Для подгрупп: проверяем, что учитель не в другом классе
        for (c_id, s_id) in teacher_conflicts:
            if c_id != class_id:
                return False
    
    # Проверка 2: Класс не может быть в двух местах одновременно
    # (исключение: подгруппы - один предмет, несколько учителей)
    class_conflicts = class_schedule.get((class_id, day, slot), set())
    if class_conflicts:
        # Проверяем, не является ли это подгруппой
        for (s_id, t_id) in class_conflicts:
            if s_id != subject_id:
                # Разные предметы в одном классе - запрещаем
                return False
            # Один предмет, разные учителя - это подгруппы, разрешаем
    
    return True


def _select_best_cabinet(
    available_cabinets: List[Dict],
    day: int,
    slot: int,
    class_id: int,
    cabinet_schedule: Dict,
    has_subgroups: bool
) -> Optional[str]:
    """
    Выбирает лучший доступный кабинет для урока
    """
    if not available_cabinets:
        return None
    
    # Сортируем кабинеты по приоритету
    sorted_cabinets = sorted(available_cabinets, key=lambda x: x.get('priority', 4))
    
    for cab in sorted_cabinets:
        cab_name = cab['name']
        max_capacity = cab.get('max_classes_simultaneously', 1)
        
        # Проверяем вместимость кабинета
        classes_in_slot = cabinet_schedule.get(cab_name, {}).get((day, slot), set())
        
        if len(classes_in_slot) >= max_capacity:
            # Кабинет заполнен
            if class_id not in classes_in_slot:
                continue
        
        # Кабинет доступен
        return cab_name
    
    return None

