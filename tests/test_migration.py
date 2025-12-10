"""
Тестовый скрипт для проверки миграции
"""
import sys
import os

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    print("Импортируем модули...")
    from migrate_to_separate_databases import migrate_database
    print("✅ Импорт успешен")
    
    print("\nЗапускаем миграцию...")
    migrate_database()
    print("\n✅ Миграция завершена")
    
except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

