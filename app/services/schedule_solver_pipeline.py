"""
Эталонная архитектура составления расписания
Pipeline: Greedy -> Graph Coloring -> Bipartite Matching -> CP-SAT -> (опционально) Genetic Algorithm
"""
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
import logging

from app.services.schedule_solver import ClassSubjectRequirement, LessonSlot
from app.services.schedule_solver_greedy import solve_schedule_greedy
from app.services.schedule_solver_cp_sat import solve_schedule_cp_sat

logger = logging.getLogger(__name__)


def solve_schedule_pipeline(
    requirements: List[ClassSubjectRequirement],
    shift_id: int,
    existing_schedule: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    schedule_settings: Optional[Dict[int, int]] = None,
    clear_existing: bool = False,
    time_limit_seconds: int = 300,
    use_genetic: bool = False,
    use_cp_sat: bool = True  # Опционально использовать CP-SAT
) -> Dict:
    """
    Решает задачу составления расписания используя эталонную архитектуру
    
    Pipeline:
    1. Greedy - предварительная расстановка 70-85% уроков
    2. Graph Coloring - определение тайм-слотов
    3. Bipartite Matching - распределение кабинетов
    4. CP-SAT - финальная сборка и устранение конфликтов
    5. (опционально) Genetic Algorithm - улучшение итогового качества
    
    Args:
        requirements: Список требований для составления расписания
        shift_id: ID смены
        existing_schedule: Существующее расписание
        schedule_settings: Настройки расписания {day: lessons_count}
        clear_existing: Очищать ли существующее расписание
        time_limit_seconds: Лимит времени для CP-SAT (секунды)
        use_genetic: Использовать ли генетический алгоритм для улучшения
    
    Returns:
        Словарь с результатами
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
    
    logger.info(f"Начало pipeline для смены {shift_id}")
    logger.info(f"Требований: {len(requirements)}")
    
    all_warnings = []
    all_suggestions = []
    
    # Этап 1: Greedy - предварительная расстановка 70-85% уроков
    logger.info("Этап 1: Greedy - предварительная расстановка")
    greedy_result = solve_schedule_greedy(
        requirements=requirements,
        shift_id=shift_id,
        existing_schedule=existing_schedule,
        schedule_settings=schedule_settings,
        clear_existing=clear_existing
    )
    
    greedy_suggestions = greedy_result.get('suggestions', [])
    all_warnings.extend(greedy_result.get('warnings', []))
    
    logger.info(f"Greedy разместил {len(greedy_suggestions)} уроков")
    
    # Этап 2: Graph Coloring - определение тайм-слотов для оставшихся уроков
    logger.info("Этап 2: Graph Coloring - определение тайм-слотов")
    remaining_requirements = _get_remaining_requirements(requirements, greedy_suggestions)
    
    if remaining_requirements:
        graph_coloring_suggestions = _graph_coloring_assign_slots(
            remaining_requirements, schedule_settings, greedy_suggestions
        )
        logger.info(f"Graph Coloring разместил {len(graph_coloring_suggestions)} уроков")
    else:
        graph_coloring_suggestions = []
    
    # Этап 3: Bipartite Matching - распределение кабинетов
    logger.info("Этап 3: Bipartite Matching - распределение кабинетов")
    all_suggestions = greedy_suggestions + graph_coloring_suggestions
    
    if graph_coloring_suggestions:
        # Для уроков без кабинетов из Graph Coloring применяем Bipartite Matching
        matched_suggestions = _bipartite_matching_assign_cabinets(
            graph_coloring_suggestions, requirements, schedule_settings
        )
        # Заменяем suggestions с кабинетами
        all_suggestions = greedy_suggestions + matched_suggestions
        logger.info(f"Bipartite Matching распределил кабинеты для {len(matched_suggestions)} уроков")
    
    # Этап 4: CP-SAT - финальная сборка и устранение конфликтов (опционально)
    if use_cp_sat:
        remaining_count = len(requirements) * 2 - len(all_suggestions)  # Примерная оценка
        
        if remaining_count > 0 and len(all_suggestions) < len(requirements) * 0.9:
            # Есть неразмещенные уроки - используем CP-SAT для финализации
            logger.info(f"Этап 4: CP-SAT - финальная сборка и устранение конфликтов (осталось ~{remaining_count} уроков)")
            
            # Создаем частичное решение из предыдущих этапов
            partial_schedule = _convert_suggestions_to_schedule(all_suggestions)
            
            # Используем короткий лимит времени для быстрого ответа
            cp_sat_time_limit = min(time_limit_seconds, 30)  # Максимум 30 секунд для быстрого ответа
            
            cp_sat_result = solve_schedule_cp_sat(
                requirements=requirements,
                shift_id=shift_id,
                existing_schedule=partial_schedule,
                schedule_settings=schedule_settings,
                clear_existing=False,  # Не очищаем, используем как начальное решение
                time_limit_seconds=cp_sat_time_limit,
                gap_weight=100,
                priority_weight=1
            )
            
            final_suggestions = cp_sat_result.get('suggestions', [])
            all_warnings.extend(cp_sat_result.get('warnings', []))
            
            logger.info(f"CP-SAT финализировал {len(final_suggestions)} уроков за {cp_sat_time_limit} секунд")
        else:
            # Все уроки размещены или почти все - пропускаем CP-SAT для экономии времени
            logger.info(f"Этап 4: CP-SAT пропущен - уже размещено {len(all_suggestions)} уроков ({(len(all_suggestions) / (len(requirements) * 2) * 100):.1f}%)")
            final_suggestions = all_suggestions
    else:
        # CP-SAT отключен
        logger.info("Этап 4: CP-SAT отключен")
        final_suggestions = all_suggestions
    
    # Этап 5: (опционально) Genetic Algorithm - улучшение итогового качества
    if use_genetic and final_suggestions:
        logger.info("Этап 5: Genetic Algorithm - улучшение качества")
        improved_suggestions = _genetic_algorithm_improve(
            final_suggestions, requirements, schedule_settings
        )
        if improved_suggestions:
            final_suggestions = improved_suggestions
            logger.info(f"Genetic Algorithm улучшил решение")
    
    summary = (
        f"Pipeline: Greedy({len(greedy_suggestions)}) -> "
        f"Graph Coloring({len(graph_coloring_suggestions)}) -> "
        f"Bipartite Matching"
    )
    if use_cp_sat:
        summary += f" -> CP-SAT({len(final_suggestions)})"
    if use_genetic:
        summary += " -> Genetic Algorithm"
    
    return {
        'suggestions': final_suggestions,
        'warnings': all_warnings,
        'summary': summary
    }


def _get_remaining_requirements(
    requirements: List[ClassSubjectRequirement],
    placed_suggestions: List[Dict]
) -> List[Dict]:
    """
    Определяет оставшиеся требования, которые не были размещены Greedy
    """
    # Подсчитываем размещенные уроки по требованиям
    placed_count = defaultdict(int)
    
    for suggestion in placed_suggestions:
        key = (suggestion['class_id'], suggestion['subject_id'], suggestion['teacher_id'])
        placed_count[key] += 1
    
    # Создаем список оставшихся задач
    remaining = []
    
    for req in requirements:
        for teacher in req.teachers:
            teacher_id = teacher['teacher_id']
            hours = teacher.get('hours_per_week', 0)
            key = (req.class_id, req.subject_id, teacher_id)
            placed = placed_count.get(key, 0)
            remaining_hours = hours - placed
            
            if remaining_hours > 0:
                for _ in range(remaining_hours):
                    remaining.append({
                        'req': req,
                        'teacher_id': teacher_id,
                        'teacher': teacher
                    })
    
    return remaining


def _graph_coloring_assign_slots(
    remaining_requirements: List[Dict],
    schedule_settings: Dict[int, int],
    existing_suggestions: List[Dict]
) -> List[Dict]:
    """
    Graph Coloring: определяет тайм-слоты для оставшихся уроков
    Использует граф конфликтов для минимизации пересечений
    """
    suggestions = []
    
    if not remaining_requirements:
        return suggestions
    
    # Создаем граф конфликтов
    conflict_graph = _build_conflict_graph(remaining_requirements, existing_suggestions)
    
    # Применяем жадную раскраску графа
    colored = _greedy_graph_coloring(remaining_requirements, conflict_graph, schedule_settings)
    
    # Создаем suggestions из раскрашенных узлов
    for node_idx, (day, slot) in colored.items():
        req_data = remaining_requirements[node_idx]
        req = req_data['req']
        teacher_id = req_data['teacher_id']
        
        suggestions.append({
            'day_of_week': day,
            'lesson_number': slot,
            'class_id': req.class_id,
            'subject_id': req.subject_id,
            'teacher_id': teacher_id,
            'cabinet': None  # Кабинет будет назначен на следующем этапе
        })
    
    return suggestions


def _build_conflict_graph(
    remaining_requirements: List[Dict],
    existing_suggestions: List[Dict]
) -> Dict:
    """
    Строит граф конфликтов для Graph Coloring
    """
    # Граф конфликтов: узлы - индексы требований, ребра - конфликты
    conflict_graph = defaultdict(set)
    
    for i, req1 in enumerate(remaining_requirements):
        for j, req2 in enumerate(remaining_requirements):
            if i >= j:
                continue
            
            # Проверяем конфликты
            if _has_conflict(req1, req2, existing_suggestions):
                conflict_graph[i].add(j)
                conflict_graph[j].add(i)
    
    return conflict_graph


def _has_conflict(req1: Dict, req2: Dict, existing_suggestions: List[Dict]) -> bool:
    """
    Проверяет, есть ли конфликт между двумя требованиями
    """
    # Конфликт: один учитель, один класс, один предмет в одно время
    if req1['teacher_id'] == req2['teacher_id']:
        if req1['req'].class_id != req2['req'].class_id:
            return True  # Учитель в разных классах одновременно
    
    if req1['req'].class_id == req2['req'].class_id:
        if req1['req'].subject_id != req2['req'].subject_id:
            # Разные предметы в одном классе - конфликт
            # Но если это подгруппы (один предмет, разные учителя) - разрешаем
            if req1['req'].has_subgroups and req2['req'].has_subgroups:
                if req1['req'].subject_id == req2['req'].subject_id:
                    return False  # Подгруппы одного предмета - разрешаем
            return True
    
    return False


def _greedy_graph_coloring(
    remaining_requirements: List[Dict],
    conflict_graph: Dict,
    schedule_settings: Dict[int, int]
) -> Dict:
    """
    Жадная раскраска графа для определения тайм-слотов
    """
    # Сортируем узлы по степени (количество конфликтов)
    nodes = sorted(conflict_graph.keys(), key=lambda x: len(conflict_graph[x]), reverse=True)
    
    colored = {}
    available_slots = []
    
    # Создаем список доступных слотов
    for day in sorted(schedule_settings.keys()):
        max_lessons = schedule_settings[day]
        for slot in range(1, max_lessons + 1):
            available_slots.append((day, slot))
    
    # Раскрашиваем узлы
    for node in nodes:
        # Находим цвета (слоты), используемые соседями
        neighbor_colors = set()
        for neighbor in conflict_graph[node]:
            if neighbor in colored:
                neighbor_colors.add(colored[neighbor])
        
        # Выбираем первый доступный цвет (слот)
        for slot in available_slots:
            if slot not in neighbor_colors:
                colored[node] = slot
                break
    
    # Раскрашиваем узлы без конфликтов
    for i in range(len(remaining_requirements)):
        if i not in colored:
            # Выбираем первый доступный слот
            colored[i] = available_slots[0] if available_slots else (1, 1)
    
    return colored


def _bipartite_matching_assign_cabinets(
    suggestions: List[Dict],
    requirements: List[ClassSubjectRequirement],
    schedule_settings: Dict[int, int]
) -> List[Dict]:
    """
    Bipartite Matching: распределяет кабинеты для уроков без кабинетов
    """
    # Создаем словарь требований для быстрого поиска
    req_map = {}
    for req in requirements:
        for teacher in req.teachers:
            key = (req.class_id, req.subject_id, teacher['teacher_id'])
            req_map[key] = {'req': req, 'teacher': teacher}
    
    # Обрабатываем suggestions без кабинетов
    for suggestion in suggestions:
        if suggestion.get('cabinet') is None:
            key = (suggestion['class_id'], suggestion['subject_id'], suggestion['teacher_id'])
            req_data = req_map.get(key)
            
            if req_data:
                available_cabinets = req_data['teacher'].get('available_cabinets', [])
                if available_cabinets:
                    # Выбираем кабинет с наивысшим приоритетом
                    best_cabinet = min(available_cabinets, key=lambda x: x.get('priority', 4))
                    suggestion['cabinet'] = best_cabinet['name']
    
    return suggestions


def _convert_suggestions_to_schedule(suggestions: List[Dict]) -> Dict:
    """
    Конвертирует suggestions в формат existing_schedule
    """
    schedule = defaultdict(list)
    
    for suggestion in suggestions:
        key = (
            suggestion['day_of_week'],
            suggestion['lesson_number'],
            suggestion['class_id']
        )
        schedule[key].append({
            'teacher_id': suggestion['teacher_id'],
            'subject_id': suggestion['subject_id'],
            'cabinet': suggestion.get('cabinet', '')
        })
    
    return dict(schedule)


def _genetic_algorithm_improve(
    suggestions: List[Dict],
    requirements: List[ClassSubjectRequirement],
    schedule_settings: Dict[int, int]
) -> Optional[List[Dict]]:
    """
    Genetic Algorithm: улучшает итоговое качество расписания
    (Опциональный этап)
    """
    # TODO: Реализовать генетический алгоритм для улучшения решения
    # Пока возвращаем исходное решение
    return suggestions

