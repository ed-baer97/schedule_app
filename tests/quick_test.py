#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Быстрый тест миграции
"""
import sys
import os

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

print("=" * 60)
print("ТЕСТ МИГРАЦИИ БД")
print("=" * 60)

# Проверка импортов
print("\n1. Проверка импортов...")
try:
    from flask import Flask
    from config import Config
    from app.core.db_manager import init_system_db, system_db, school_db, create_school_database, school_db_context
    from app.models.system import School, User
    from app.models.school import (
        Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
        PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings
    )
    print("   ✅ Импорты успешны")
except Exception as e:
    print(f"   ❌ Ошибка импорта: {e}")
    sys.exit(1)

# Проверка существования старой БД
print("\n2. Проверка старой БД...")
old_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schedule.db')
if os.path.exists(old_db_path):
    size = os.path.getsize(old_db_path)
    print(f"   ✅ Старая БД найдена: {old_db_path} ({size} байт)")
else:
    print(f"   ⚠️ Старая БД не найдена: {old_db_path}")
    print("   Миграция не требуется или БД уже мигрирована")
    sys.exit(0)

# Проверка существования новой системной БД
print("\n3. Проверка новой структуры БД...")
project_root = os.path.dirname(os.path.dirname(__file__))
system_db_path = os.path.join(project_root, 'system.db')
databases_dir = os.path.join(project_root, 'databases')

if os.path.exists(system_db_path):
    print(f"   ⚠️ Системная БД уже существует: {system_db_path}")
    print("   Миграция может пропустить существующие данные")
else:
    print(f"   ✅ Системная БД будет создана: {system_db_path}")

if os.path.exists(databases_dir):
    db_files = [f for f in os.listdir(databases_dir) if f.endswith('.db')]
    if db_files:
        print(f"   ⚠️ Найдено {len(db_files)} БД школ в {databases_dir}")
    else:
        print(f"   ✅ Директория для БД школ готова: {databases_dir}")
else:
    print(f"   ✅ Директория для БД школ будет создана: {databases_dir}")

# Запуск миграции
print("\n4. Запуск миграции...")
print("   (Это может занять некоторое время)")
print("-" * 60)

try:
    from migrate_to_separate_databases import migrate_database
    migrate_database()
    print("-" * 60)
    print("\n✅ Миграция завершена!")
    print("\nСледующие шаги:")
    print("1. Проверьте созданные файлы БД")
    print("2. Запустите приложение: python app.py")
    print("3. Проверьте работоспособность")
    print("4. После проверки можно удалить старую БД (schedule.db)")
except Exception as e:
    print("-" * 60)
    print(f"\n❌ Ошибка при миграции: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

