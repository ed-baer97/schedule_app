"""
Модуль для нормализации ID классов в смене
Первый класс смены получает class_id=1, второй class_id=2 и т.д.
"""

from typing import Dict, Tuple, List, Set


def create_class_id_mapping(assigned_class_ids: Set[int]) -> Tuple[Dict[int, int], Dict[int, int]]:
    """
    Создает маппинг между реальными class_id и нормализованными (начиная с 1)
    
    Args:
        assigned_class_ids: Множество реальных class_id классов, назначенных смене
    
    Returns:
        Tuple[normalized_to_real, real_to_normalized]:
        - normalized_to_real: {нормализованный_id: реальный_id}
        - real_to_normalized: {реальный_id: нормализованный_id}
    """
    sorted_class_ids = sorted(assigned_class_ids)
    
    normalized_to_real = {}
    real_to_normalized = {}
    
    for normalized_id, real_id in enumerate(sorted_class_ids, start=1):
        normalized_to_real[normalized_id] = real_id
        real_to_normalized[real_id] = normalized_id
    
    return normalized_to_real, real_to_normalized


def normalize_class_id(class_id: int, real_to_normalized: Dict[int, int]) -> int:
    """
    Преобразует реальный class_id в нормализованный
    
    Args:
        class_id: Реальный class_id
        real_to_normalized: Маппинг реальный_id -> нормализованный_id
    
    Returns:
        Нормализованный class_id (начиная с 1)
    """
    return real_to_normalized.get(class_id, class_id)


def denormalize_class_id(normalized_class_id: int, normalized_to_real: Dict[int, int]) -> int:
    """
    Преобразует нормализованный class_id обратно в реальный
    
    Args:
        normalized_class_id: Нормализованный class_id (начиная с 1)
        normalized_to_real: Маппинг нормализованный_id -> реальный_id
    
    Returns:
        Реальный class_id
    """
    return normalized_to_real.get(normalized_class_id, normalized_class_id)

