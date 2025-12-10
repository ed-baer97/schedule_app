"""
Модуль для преобразования матрицы расписания от AI в записи PermanentSchedule
"""
from typing import Dict, List, Tuple, Any
from app.models.school import PermanentSchedule


def convert_matrix_to_schedule(
    schedule_matrix: Dict[str, List[List[Any]]],
    shift_id: int,
    id_mappings: Dict[str, Dict[int, str]] = None
) -> List[Dict]:
    """
    Преобразует матрицу расписания от AI в список записей для PermanentSchedule
    
    Args:
        schedule_matrix: Матрица от AI в формате {class_id: [[subject_id, teacher_id, day, lesson, cabinet], ...]}
        shift_id: ID смены
        id_mappings: Справочники для преобразования ID в имена (опционально)
    
    Returns:
        Список словарей с данными для создания PermanentSchedule:
        [
            {
                'shift_id': int,
                'day_of_week': int,
                'lesson_number': int,
                'class_id': int,
                'subject_id': int,
                'teacher_id': int,
                'cabinet': str,
                'class_name': str (если id_mappings предоставлен),
                'subject_name': str (если id_mappings предоставлен),
                'teacher_name': str (если id_mappings предоставлен)
            },
            ...
        ]
    """
    suggestions = []
    
    for class_id_str, lessons_list in schedule_matrix.items():
        try:
            class_id = int(class_id_str)
        except (ValueError, TypeError):
            print(f"⚠️ Неверный class_id: {class_id_str}, пропускаем")
            continue
        
        for lesson_tuple in lessons_list:
            try:
                # Проверяем формат кортежа
                if not isinstance(lesson_tuple, (list, tuple)) or len(lesson_tuple) < 4:
                    print(f"⚠️ Неверный формат кортежа урока: {lesson_tuple}, пропускаем")
                    continue
                
                subject_id = int(lesson_tuple[0])
                teacher_id = int(lesson_tuple[1])
                day_of_week = int(lesson_tuple[2])
                lesson_number = int(lesson_tuple[3])
                cabinet = str(lesson_tuple[4]) if len(lesson_tuple) > 4 else ""
                
                # Создаем запись
                suggestion = {
                    'shift_id': shift_id,
                    'day_of_week': day_of_week,
                    'lesson_number': lesson_number,
                    'class_id': class_id,
                    'subject_id': subject_id,
                    'teacher_id': teacher_id,
                    'cabinet': cabinet
                }
                
                # Добавляем имена, если есть справочники
                if id_mappings:
                    if class_id in id_mappings.get('classes', {}):
                        suggestion['class_name'] = id_mappings['classes'][class_id]
                    if subject_id in id_mappings.get('subjects', {}):
                        suggestion['subject_name'] = id_mappings['subjects'][subject_id]
                    if teacher_id in id_mappings.get('teachers', {}):
                        suggestion['teacher_name'] = id_mappings['teachers'][teacher_id]
                
                suggestions.append(suggestion)
                
            except (ValueError, TypeError, IndexError) as e:
                print(f"⚠️ Ошибка при обработке кортежа урока {lesson_tuple}: {e}, пропускаем")
                continue
    
    return suggestions


def prepare_lessons_data_for_ai(class_subject_structure: List[Dict]) -> List[Tuple[int, int, int]]:
    """
    Подготавливает данные в формате списка кортежей (class_id, subject_id, teacher_id)
    для отправки в AI
    
    Args:
        class_subject_structure: Структура классов-предметов из БД промпта
    
    Returns:
        Список кортежей [(class_id, subject_id, teacher_id), ...]
    """
    lessons = []
    
    for item in class_subject_structure:
        class_id = item.get('class_id')
        subject_id = item.get('subject_id')
        teachers = item.get('teachers', [])
        total_hours = item.get('total_hours_per_week', 0)
        
        if not class_id or not subject_id or not teachers:
            continue
        
        # Добавляем кортеж для каждого учителя
        # Если это подгруппы, будет несколько кортежей с одним class_id и subject_id
        for teacher in teachers:
            teacher_id = teacher.get('teacher_id')
            if teacher_id:
                # Добавляем кортеж столько раз, сколько часов у этого учителя
                hours = teacher.get('hours_per_week', 0)
                for _ in range(hours):
                    lessons.append((class_id, subject_id, teacher_id))
    
    return lessons

