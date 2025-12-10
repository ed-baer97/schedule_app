"""
Скрипт для миграции существующих баз данных школ
Добавляет колонку category в таблицу subjects
"""
import sys
import os

# Добавляем путь к проекту в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Импортируем app напрямую из app.py, обходя пакет app
import importlib.util
spec = importlib.util.spec_from_file_location("app_main", os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"))
app_module = importlib.util.module_from_spec(spec)
# Важно: добавляем в sys.modules, чтобы относительные импорты внутри app.py работали
sys.modules["app_main"] = app_module
spec.loader.exec_module(app_module)
app = app_module.app

from app.core.db_manager import migrate_school_database, db
from app.models.system import School

def migrate_all_schools():
    """Мигрировать все существующие базы данных школ"""
    with app.app_context():
        # Получаем все школы из главной БД
        schools = School.query.all()
        
        print(f"Найдено школ: {len(schools)}")
        
        for school in schools:
            print(f"\n{'='*50}")
            print(f"Миграция школы: {school.name} (ID: {school.id})")
            print(f"{'='*50}")
            
            try:
                # Запускаем миграцию для этой школы
                migrate_school_database(school.id)
                print(f"✅ Миграция успешно выполнена для школы {school.name}")
            except Exception as e:
                print(f"❌ Ошибка при миграции школы {school.name}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'='*50}")
        print("Миграция завершена!")
        print(f"{'='*50}")

if __name__ == '__main__':
    migrate_all_schools()
