"""
Вспомогательные функции для маршрутов
"""
import re
from app.core.db_manager import db
from app.models.school import ClassGroup, AIConversation, AIConversationMessage


def get_class_group(class_name):
    """
    Определяет группу класса: 'primary' (1-4, начальная школа) или 'secondary' (5-11, старшая школа)
    
    Args:
        class_name: Название класса (например, "1А", "5Б", "11В")
    
    Returns:
        str: 'primary' для 1-4 классов, 'secondary' для 5-11 классов, None если не удалось определить
    """
    if not class_name:
        return None
    
    # Извлекаем число из названия класса (например, "1А" -> 1, "11В" -> 11)
    match = re.match(r'^(\d+)', str(class_name).strip())
    if match:
        class_number = int(match.group(1))
        if 1 <= class_number <= 4:
            return 'primary'
        elif 5 <= class_number <= 11:
            return 'secondary'
    
    return None


def sort_classes_key(class_name):
    """
    Функция для правильной сортировки классов по названию.
    Сортирует по числовой части (1, 2, ..., 9, 10, 11), а затем по буквенной части.
    
    Args:
        class_name: Название класса (например, "1А", "10Б", "11В")
    
    Returns:
        tuple: (число, буква) для сортировки
    """
    if not class_name:
        return (999, '')  # Классы без названия в конец
    
    class_name_str = str(class_name).strip()
    
    # Извлекаем число и букву из названия класса
    match = re.match(r'^(\d+)([А-Яа-яA-Za-z]*)', class_name_str)
    if match:
        number = int(match.group(1))
        letter = match.group(2).upper() if match.group(2) else ''
        return (number, letter)
    
    # Если не удалось распарсить, возвращаем как есть (в конец)
    return (999, class_name_str)


def get_sorted_classes(query=None):
    """
    Получает классы из БД и сортирует их правильно (10-11 после 9).
    
    Args:
        query: SQLAlchemy query объект (опционально). Если не указан, получает все классы.
    
    Returns:
        list: Отсортированный список классов
    """
    if query is None:
        classes = db.session.query(ClassGroup).all()
    else:
        classes = query.all()
    
    # Сортируем классы по правильному ключу
    return sorted(classes, key=lambda cls: sort_classes_key(cls.name))


def ensure_ai_tables_exist():
    """Проверяет и создает таблицы для диалога с ИИ, если их нет"""
    try:
        from flask import current_app
        from sqlalchemy import inspect
        
        engine = db.get_engine(current_app, bind='school')
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        if 'ai_conversations' not in existing_tables:
            print("🔄 Создание таблиц для диалога с ИИ...")
            AIConversation.__table__.create(engine, checkfirst=True)
            AIConversationMessage.__table__.create(engine, checkfirst=True)
            print("✅ Таблицы для диалога с ИИ созданы")
    except Exception as e:
        print(f"⚠️ Ошибка при проверке/создании таблиц: {e}")
        import traceback
        traceback.print_exc()

