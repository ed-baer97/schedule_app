"""
Скрипт инициализации системы с нуля
Создает системную БД, супер-администратора и опционально первую школу
"""
import os
import sys

# Добавляем путь к проекту
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from flask import Flask
from config import Config
from app.core.db_manager import init_system_db, db, create_school_database, school_db_context
# Для обратной совместимости
system_db = db
school_db = db
from app.models.system import School, User

def init_system(create_first_school=False):
    """Инициализировать систему с нуля"""
    
    print("=" * 60)
    print("ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ")
    print("=" * 60)
    
    # Создаем Flask приложение
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Инициализируем систему БД
    init_system_db(app)
    
    with app.app_context():
        # 1. Создаем системную БД
        print("\n1. Создание системной БД...")
        db.create_all()
        print("   ✅ Системная БД создана")
        
        # 2. Создаем супер-администратора
        print("\n2. Создание супер-администратора...")
        super_admin = User.query.filter_by(role='super_admin').first()
        if super_admin:
            print(f"   ⚠️  Супер-администратор уже существует: {super_admin.username}")
        else:
            super_admin = User(
                username='admin',
                full_name='Супер-Администратор',
                role='super_admin',
                school_id=None,
                is_active=True
            )
            super_admin.set_password('admin123')
            db.session.add(super_admin)
            db.session.commit()
            print("   ✅ Создан супер-администратор:")
            print(f"      Логин: admin")
            print(f"      Пароль: admin123")
            print("      ⚠️  ВАЖНО: Измените пароль после первого входа!")
        
        # 3. Опционально создаем первую школу
        if create_first_school:
            print("\n3. Создание первой школы...")
            first_school = School.query.filter_by(name='Первая школа').first()
            if first_school:
                print(f"   ⚠️  Школа уже существует: {first_school.name} (ID: {first_school.id})")
            else:
                first_school = School(
                    name='Первая школа',
                    is_active=True
                )
                db.session.add(first_school)
                db.session.commit()
                
                # Создаем БД для школы
                create_school_database(first_school.id)
                print(f"   ✅ Создана школа: {first_school.name} (ID: {first_school.id})")
                print(f"   ✅ Создана БД школы: databases/school_{first_school.id}.db")
                
                # Создаем первую смену для школы
                with school_db_context(first_school.id):
                    from app.models.school import Shift
                    first_shift = Shift(name='Первая смена', is_active=True)
                    db.session.add(first_shift)
                    db.session.commit()
                    print(f"   ✅ Создана первая смена: {first_shift.name}")
                
                # Создаем администратора для школы
                school_admin = User(
                    username='school_admin',
                    full_name='Администратор школы',
                    role='admin',
                    school_id=first_school.id,
                    is_active=True
                )
                school_admin.set_password('admin123')
                db.session.add(school_admin)
                db.session.commit()
                print("   ✅ Создан администратор школы:")
                print(f"      Логин: school_admin")
                print(f"      Пароль: admin123")
                print(f"      Школа: {first_school.name}")
        
        print("\n" + "=" * 60)
        print("✅ ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА!")
        print("=" * 60)
        print("\n📝 Следующие шаги:")
        print("   1. Запустите приложение: python app.py")
        print("   2. Откройте в браузере: http://localhost:5000/login")
        if create_first_school:
            print("   3. Войдите как:")
            print("      - Супер-админ: admin / admin123")
            print("      - Админ школы: school_admin / admin123")
        else:
            print("   3. Войдите как супер-администратор: admin / admin123")
            print("   4. Создайте школу через панель супер-администратора")
        print("   5. ⚠️  ВАЖНО: Измените пароли после первого входа!")
        print("\n" + "=" * 60)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Инициализация системы с нуля')
    parser.add_argument(
        '--create-school',
        action='store_true',
        help='Создать первую школу и администратора для неё'
    )
    
    args = parser.parse_args()
    
    try:
        init_system(create_first_school=args.create_school)
    except Exception as e:
        print(f"\n❌ Ошибка при инициализации: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

