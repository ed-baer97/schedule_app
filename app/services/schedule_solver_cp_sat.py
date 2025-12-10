"""
CP-SAT алгоритм составления расписания с использованием Google OR-Tools
Математическая модель: X[class][subject][teacher][time][room] ∈ {0,1}

Ограничения:
1. Для каждого урока суммарно один слот: sum(time, room) X[...] = 1
2. Учитель в одном тайм-слоте: sum(class, room) X[teacher][time] ≤ 1
3. Класс в одном тайм-слоте: sum(subject, room) X[class][time] ≤ 1
4. Комната вместимость: sum(class, subject) X[room][time] ≤ capacity(room)
5. В ячейку можно поставить X[subgroup1], X[subgroup2], ... если они относятся к одному классу
"""
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
import logging

from ortools.sat.python import cp_model

from app.services.schedule_solver import ClassSubjectRequirement, LessonSlot

logger = logging.getLogger(__name__)


def solve_schedule_cp_sat(
    requirements: List[ClassSubjectRequirement],
    shift_id: int,
    existing_schedule: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    schedule_settings: Optional[Dict[int, int]] = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 300,
    gap_weight: int = 100,
    priority_weight: int = 1
) -> Dict:
    """
    Решает задачу составления расписания используя CP-SAT solver
    
    Args:
        requirements: Список требований для составления расписания
        shift_id: ID смены
        existing_schedule: Существующее расписание
        schedule_settings: Настройки расписания {day: lessons_count}
        clear_existing: Очищать ли существующее расписание
        time_limit_seconds: Лимит времени для решения (секунды)
        gap_weight: Вес штрафа за окно
        priority_weight: Вес штрафа за использование кабинета с низким приоритетом
    
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
    
    # Создаем модель CP-SAT
    model = cp_model.CpModel()
    
    # Собираем информацию о кабинетах из требований
    cabinet_info = _extract_cabinet_info(requirements)
    
    # Создаем переменные решения X[class][subject][teacher][time][room]
    variables = _create_variables(model, requirements, schedule_settings, cabinet_info)
    
    # Добавляем ограничения согласно математической модели
    _add_constraints(
        model, requirements, variables, schedule_settings, 
        cabinet_info, existing_schedule, clear_existing
    )
    
    # Добавляем целевую функцию (минимизация штрафов)
    _add_objective(model, variables, requirements, gap_weight, priority_weight)
    
    # Решаем
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 4  # Параллельный поиск
    solver.parameters.log_search_progress = True  # Логирование прогресса
    
    import time
    start_solve = time.time()
    
    logger.info(f"Начало решения CP-SAT для смены {shift_id}")
    logger.info(f"Требований: {len(requirements)}, Переменных: {len(variables['lesson_vars'])}")
    logger.info(f"Лимит времени: {time_limit_seconds} секунд")
    
    status = solver.Solve(model)
    
    solve_time = time.time() - start_solve
    logger.info(f"Решение CP-SAT заняло {solve_time:.2f} секунд")
    
    suggestions = []
    warnings = []
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # Извлекаем решение
        suggestions = _extract_solution(solver, variables, requirements, schedule_settings)
        
        logger.info(f"Решение найдено: {len(suggestions)} уроков размещено")
        
        if status == cp_model.FEASIBLE:
            warnings.append("Найдено допустимое решение (не обязательно оптимальное)")
    else:
        logger.warning(f"Решение не найдено. Статус: {status}")
        warnings.append("Не удалось найти решение. Проверьте ограничения и данные.")
    
    summary = f"CP-SAT алгоритм: обработано {len(requirements)} требований, размещено {len(suggestions)} уроков"
    
    return {
        'suggestions': suggestions,
        'warnings': warnings,
        'summary': summary
    }


def _extract_cabinet_info(requirements: List[ClassSubjectRequirement]) -> Dict[str, Dict]:
    """
    Извлекает информацию о кабинетах из требований
    
    Returns:
        Словарь {cabinet_name: {subgroups_only, exclusive_to_subject, subject_id, max_classes_simultaneously, priority}}
    """
    cabinet_info = {}
    
    for req in requirements:
        for teacher in req.teachers:
            for cab in teacher.get('available_cabinets', []):
                cab_name = cab['name']
                if cab_name not in cabinet_info:
                    cabinet_info[cab_name] = {
                        'subgroups_only': cab.get('subgroups_only', False),
                        'exclusive_to_subject': cab.get('exclusive_to_subject', False),
                        'subject_id': cab.get('subject_id'),
                        'max_classes_simultaneously': cab.get('max_classes_simultaneously', 1),
                        'priority': cab.get('priority', 4)
                    }
    
    return cabinet_info


def _create_variables(
    model: cp_model.CpModel,
    requirements: List[ClassSubjectRequirement],
    schedule_settings: Dict[int, int],
    cabinet_info: Dict[str, Dict]
) -> Dict:
    """
    Создает переменные решения X[class][subject][teacher][time][room] ∈ {0,1}
    
    Returns:
        Словарь с переменными:
        {
            'lesson_vars': {(class_id, subject_id, teacher_id, day, slot, cabinet): BoolVar},
            'requirements_map': {(class_id, subject_id, teacher_id): req} - для обратного поиска
        }
    """
    lesson_vars = {}
    requirements_map = {}
    
    for req_idx, req in enumerate(requirements):
        class_id = req.class_id
        subject_id = req.subject_id
        
        # Для каждого учителя в требовании
        for teacher_idx, teacher in enumerate(req.teachers):
            teacher_id = teacher['teacher_id']
            available_cabinets = teacher.get('available_cabinets', [])
            
            # Сохраняем маппинг для обратного поиска
            requirements_map[(class_id, subject_id, teacher_id)] = req
            
            # Для каждого дня недели
            for day in schedule_settings.keys():
                max_lessons = schedule_settings[day]
                
                # Для каждого слота урока
                for slot in range(1, max_lessons + 1):
                    # Для каждого доступного кабинета
                    for cab in available_cabinets:
                        cab_name = cab['name']
                        
                        # Проверяем ограничения кабинета
                        cab_info = cabinet_info.get(cab_name, {})
                        
                        # Если кабинет только для подгрупп, а это не подгруппа - пропускаем
                        if cab_info.get('subgroups_only', False) and not req.has_subgroups:
                            continue
                        
                        # Если кабинет эксклюзивный для предмета, проверяем
                        if cab_info.get('exclusive_to_subject', False):
                            if cab_info.get('subject_id') != req.subject_id:
                                continue
                        
                        # Создаем переменную X[class][subject][teacher][time][room]
                        var_name = f"X_c{class_id}_s{subject_id}_t{teacher_id}_d{day}_sl{slot}_r{cab_name}"
                        lesson_vars[(class_id, subject_id, teacher_id, day, slot, cab_name)] = model.NewBoolVar(var_name)
    
    return {
        'lesson_vars': lesson_vars,
        'requirements_map': requirements_map
    }


def _add_constraints(
    model: cp_model.CpModel,
    requirements: List[ClassSubjectRequirement],
    variables: Dict,
    schedule_settings: Dict[int, int],
    cabinet_info: Dict[str, Dict],
    existing_schedule: Dict[Tuple[int, int, int], List[Dict]],
    clear_existing: bool
):
    """
    Добавляет все ограничения согласно математической модели
    """
    lesson_vars = variables['lesson_vars']
    requirements_map = variables['requirements_map']
    
    # 1. Для каждого урока суммарно один слот: sum(time, room) X[...] = 1
    _add_lesson_slot_constraints(model, requirements, lesson_vars, requirements_map, schedule_settings)
    
    # 2. Учитель в одном тайм-слоте: sum(class, room) X[teacher][time] ≤ 1
    _add_teacher_time_constraints(model, lesson_vars, schedule_settings, requirements_map)
    
    # 3. Класс в одном тайм-слоте: sum(subject, room) X[class][time] ≤ 1
    _add_class_time_constraints(model, lesson_vars, schedule_settings)
    
    # 4. Комната вместимость: sum(class, subject) X[room][time] ≤ capacity(room)
    _add_room_capacity_constraints(model, lesson_vars, cabinet_info, schedule_settings)
    
    # 5. Не более 2 уроков одного предмета в день для класса
    _add_max_lessons_per_day_constraints(model, requirements, lesson_vars, requirements_map, schedule_settings)
    
    # 6. Ограничение: существующее расписание (если не очищаем)
    if not clear_existing:
        _add_existing_schedule_constraints(model, requirements, lesson_vars, existing_schedule, schedule_settings)


def _add_lesson_slot_constraints(
    model: cp_model.CpModel,
    requirements: List[ClassSubjectRequirement],
    lesson_vars: Dict,
    requirements_map: Dict,
    schedule_settings: Dict[int, int]
):
    """
    Ограничение 1: Для каждого урока суммарно один слот
    sum(time, room) X[class][subject][teacher][time][room] = hours_per_week
    """
    # Группируем переменные по (class, subject, teacher)
    lesson_groups = defaultdict(list)
    
    for (class_id, subject_id, teacher_id, day, slot, cab), var in lesson_vars.items():
        lesson_groups[(class_id, subject_id, teacher_id)].append(var)
    
    # Для каждой группы (class, subject, teacher) находим требование
    for (class_id, subject_id, teacher_id), vars_list in lesson_groups.items():
        req = requirements_map.get((class_id, subject_id, teacher_id))
        if not req:
                continue
            
        # Находим нагрузку этого учителя для этого класса и предмета
        teacher_hours = 0
        for teacher in req.teachers:
            if teacher['teacher_id'] == teacher_id:
                teacher_hours = teacher.get('hours_per_week', 0)
                break
        
        # Сумма всех размещений должна равняться нагрузке учителя
        if vars_list and teacher_hours > 0:
            model.Add(sum(vars_list) == teacher_hours)


def _add_teacher_time_constraints(
    model: cp_model.CpModel,
    lesson_vars: Dict,
    schedule_settings: Dict[int, int],
    requirements_map: Dict
):
    """
    Ограничение 2: Учитель в одном тайм-слоте
    sum(class, room) X[teacher][time] ≤ 1
    
    Исключение: подгруппы - несколько учителей одного предмета в одном классе одновременно
    """
    # Группируем переменные по (teacher_id, day, slot)
    teacher_time_vars = defaultdict(list)
    
    for (class_id, subject_id, teacher_id, day, slot, cab), var in lesson_vars.items():
        teacher_time_vars[(teacher_id, day, slot)].append(var)
    
    # Для каждого учителя и тайм-слота: максимум одна переменная может быть True
    # Но для подгрупп (один класс, один предмет) разрешаем несколько учителей одновременно
    for (teacher_id, day, slot), vars_list in teacher_time_vars.items():
        if len(vars_list) > 1:
            # Группируем по (class_id, subject_id) для проверки подгрупп
            class_subject_groups = defaultdict(list)
            for (c_id, s_id, t_id, d, sl, cab), var in lesson_vars.items():
                if t_id == teacher_id and d == day and sl == slot:
                    class_subject_groups[(c_id, s_id)].append(var)
            
            # Если есть несколько переменных для одного (class, subject) - это подгруппы
            # Проверяем, действительно ли это подгруппы
            for (class_id, subject_id), group_vars in class_subject_groups.items():
                req = requirements_map.get((class_id, subject_id, teacher_id))
                if req and req.has_subgroups:
                    # Это подгруппы - разрешаем все переменные для этого (class, subject)
                    # Но учитель не может быть в разных классах одновременно
                    pass
            
            # Учитель не может быть в разных классах одновременно
            if len(class_subject_groups) > 1:
                # Учитель в разных классах - запрещаем
                model.Add(sum(vars_list) <= 1)
            elif len(class_subject_groups) == 1:
                # Все переменные для одного (class, subject)
                # Если это подгруппы - разрешаем все, иначе только одну
                (class_id, subject_id), group_vars = next(iter(class_subject_groups.items()))
                req = requirements_map.get((class_id, subject_id, teacher_id))
                if not (req and req.has_subgroups):
                    # Не подгруппы - только одна переменная
                    model.Add(sum(group_vars) <= 1)


def _add_class_time_constraints(
    model: cp_model.CpModel,
    lesson_vars: Dict,
    schedule_settings: Dict[int, int]
):
    """
    Ограничение 3: Класс в одном тайм-слоте
    sum(subject, room) X[class][time] ≤ 1
    
    Исключение: подгруппы - несколько предметов с подгруппами в одном классе одновременно
    """
    # Группируем переменные по (class_id, day, slot)
    class_time_vars = defaultdict(list)
    
    for (class_id, subject_id, teacher_id, day, slot, cab), var in lesson_vars.items():
        class_time_vars[(class_id, day, slot)].append(var)
    
    # Для каждого класса и тайм-слота: максимум одна переменная может быть True
    # Но для подгрупп (один предмет, несколько учителей) разрешаем несколько переменных
    for (class_id, day, slot), vars_list in class_time_vars.items():
        if len(vars_list) > 1:
            # Группируем по subject_id для проверки подгрупп
            subject_groups = defaultdict(list)
            for (c_id, s_id, t_id, d, sl, cab), var in lesson_vars.items():
                if c_id == class_id and d == day and sl == slot:
                    subject_groups[s_id].append(var)
            
            # Если есть несколько переменных для одного subject - это подгруппы, разрешаем
            # Но разные предметы в одном классе в одно время - запрещаем
            if len(subject_groups) > 1:
                # Разные предметы в одном классе - запрещаем
                model.Add(sum(vars_list) <= 1)
            else:
                # Все переменные для одного subject - это подгруппы, разрешаем все
                pass


def _add_room_capacity_constraints(
    model: cp_model.CpModel,
    lesson_vars: Dict,
    cabinet_info: Dict[str, Dict],
    schedule_settings: Dict[int, int]
):
    """
    Ограничение 4: Комната вместимость
    sum(class, subject) X[room][time] ≤ capacity(room)
    """
    # Группируем переменные по (cabinet, day, slot)
    room_time_vars = defaultdict(list)
    
    for (class_id, subject_id, teacher_id, day, slot, cab), var in lesson_vars.items():
        room_time_vars[(cab, day, slot)].append(var)
    
    # Для каждого кабинета и тайм-слота: считаем уникальные классы
    for (cab, day, slot), vars_list in room_time_vars.items():
        cab_info = cabinet_info.get(cab, {})
        max_capacity = cab_info.get('max_classes_simultaneously', 1)
        
        # Создаем индикаторы для каждого класса
        class_indicators = {}
        classes_in_slot = set()
        
        for (class_id, subject_id, teacher_id, d, s, c), var in lesson_vars.items():
            if c == cab and d == day and s == slot:
                if class_id not in classes_in_slot:
                    classes_in_slot.add(class_id)
                    class_indicator = model.NewBoolVar(f"class_{class_id}_cab_{cab}_d{day}_s{slot}")
                    class_indicators[class_id] = class_indicator
                    
                    # Связываем индикатор с переменными этого класса
                    class_vars = [v for (c_id, s_id, t_id, d, s, c_name), v in lesson_vars.items()
                                if c_name == cab and d == day and s == slot and c_id == class_id]
                    
                    if class_vars:
                        # Если хотя бы одна переменная True, индикатор = 1
                        model.Add(sum(class_vars) >= class_indicator)
                        model.Add(sum(class_vars) <= len(class_vars) * class_indicator)
        
        # Не более max_capacity классов одновременно
        if class_indicators:
            indicators_list = list(class_indicators.values())
            model.Add(sum(indicators_list) <= max_capacity)


def _add_max_lessons_per_day_constraints(
    model: cp_model.CpModel,
    requirements: List[ClassSubjectRequirement],
    lesson_vars: Dict,
    requirements_map: Dict,
    schedule_settings: Dict[int, int]
):
    """
    Ограничение: не более 2 уроков одного предмета в день для класса
    """
    # Группируем переменные по (class_id, subject_id, day)
    class_subject_day_vars = defaultdict(list)
    
    for (class_id, subject_id, teacher_id, day, slot, cab), var in lesson_vars.items():
        class_subject_day_vars[(class_id, subject_id, day)].append(var)
    
    # Для каждого (class, subject, day): создаем индикаторы слотов
    for (class_id, subject_id, day), vars_list in class_subject_day_vars.items():
        # Группируем по слотам
        slot_indicators = {}
        slots_in_day = set()
        
        for (c_id, s_id, t_id, d, s, cab), var in lesson_vars.items():
            if c_id == class_id and s_id == subject_id and d == day:
                if s not in slots_in_day:
                    slots_in_day.add(s)
                    slot_indicator = model.NewBoolVar(f"slot_c{class_id}_s{subject_id}_d{day}_sl{s}")
                    slot_indicators[s] = slot_indicator
                    
                    # Связываем индикатор с переменными этого слота
                    slot_vars = [v for (c_id2, s_id2, t_id2, d2, s2, cab2), v in lesson_vars.items()
                               if c_id2 == class_id and s_id2 == subject_id and d2 == day and s2 == s]
                    
                    if slot_vars:
                        # Если хотя бы одна переменная True, индикатор = 1
                        model.Add(sum(slot_vars) >= slot_indicator)
                        model.Add(sum(slot_vars) <= len(slot_vars) * slot_indicator)
        
        # Не более 2 уроков в день
        if slot_indicators:
            indicators_list = list(slot_indicators.values())
            model.Add(sum(indicators_list) <= 2)


def _add_existing_schedule_constraints(
    model: cp_model.CpModel,
    requirements: List[ClassSubjectRequirement],
    lesson_vars: Dict,
    existing_schedule: Dict[Tuple[int, int, int], List[Dict]],
    schedule_settings: Dict[int, int]
):
    """Ограничение: существующее расписание должно быть сохранено"""
    # TODO: Реализовать при необходимости
    pass


def _add_objective(
    model: cp_model.CpModel,
    variables: Dict,
    requirements: List[ClassSubjectRequirement],
    gap_weight: int,
    priority_weight: int
):
    """
    Добавляет целевую функцию: минимизация штрафов за окна и низкие приоритеты кабинетов
    """
    # TODO: Реализовать минимизацию окон и приоритетов
    pass


def _extract_solution(
    solver: cp_model.CpSolver,
    variables: Dict,
    requirements: List[ClassSubjectRequirement],
    schedule_settings: Dict[int, int]
) -> List[Dict]:
    """
    Извлекает решение из solver
    """
    suggestions = []
    lesson_vars = variables['lesson_vars']
    
    for (class_id, subject_id, teacher_id, day, slot, cab_name), var in lesson_vars.items():
        if solver.Value(var):
            suggestions.append({
                'day_of_week': day,
                'lesson_number': slot,
                'class_id': class_id,
                'subject_id': subject_id,
                    'teacher_id': teacher_id,
                'cabinet': cab_name
            })
    
    return suggestions
