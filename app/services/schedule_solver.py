"""
Базовые классы данных для алгоритма составления расписания
"""
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass


@dataclass
class LessonSlot:
    """Слот для урока в расписании"""
    day_of_week: int  # 1=Понедельник, 7=Воскресенье
    lesson_number: int  # Номер урока (1, 2, 3, ...)
    
    def __hash__(self):
        return hash((self.day_of_week, self.lesson_number))
    
    def __eq__(self, other):
        if not isinstance(other, LessonSlot):
            return False
        return self.day_of_week == other.day_of_week and self.lesson_number == other.lesson_number


@dataclass
class ClassSubjectRequirement:
    """Требование для класса по предмету"""
    class_id: int
    subject_id: int
    total_hours_per_week: int
    has_subgroups: bool
    teachers: List[Dict]  # Список учителей с их данными
    class_name: str = ""  # Название класса для определения параллели
    subject_name: str = ""  # Название предмета для отображения в предупреждениях
    
    # Каждый teacher должен иметь: teacher_id, hours_per_week, available_cabinets (список с приоритетами)
    # Опционально: availability_grid - dict[teacher_id, set[(day, slot)]] - доступные слоты для учителя
    # Если не указано, учитель доступен во всех слотах


def extract_class_parallel(class_name: str) -> str:
    """
    Извлекает параллель из названия класса
    
    Примеры:
        "5А" -> "5"
        "10Б" -> "10"
        "11В" -> "11"
        "1А" -> "1"
    
    Args:
        class_name: Название класса (например, "5А", "10Б")
    
    Returns:
        Параллель (например, "5", "10") или пустая строка, если не удалось извлечь
    """
    if not class_name:
        return ""
    
    # Ищем первую последовательность цифр
    parallel = ""
    for char in class_name:
        if char.isdigit():
            parallel += char
        elif parallel:
            # Если уже нашли цифры и встретили не-цифру, останавливаемся
            break
    
    return parallel

