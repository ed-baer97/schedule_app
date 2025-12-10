"""Проверка импортов перед миграцией"""
import sys
import os

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    print("Проверяем импорты...")
    from flask import Flask
    from config import Config
    from app.core.db_manager import init_system_db, system_db, school_db, create_school_database, school_db_context
    from app.models.system import School, User
    from app.models.school import (
        Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
        PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings
    )
    print("✅ Все импорты успешны!")
    
    # Проверяем, что старая БД существует
    project_root = os.path.dirname(os.path.dirname(__file__))
    old_db_path = os.path.join(project_root, 'schedule.db')
    if os.path.exists(old_db_path):
        print(f"✅ Старая БД найдена: {old_db_path}")
    else:
        print(f"⚠️ Старая БД не найдена: {old_db_path}")
    
except Exception as e:
    print(f"❌ Ошибка импорта: {e}")
    import traceback
    traceback.print_exc()

