# init_prompt_db.py
"""
Скрипт для инициализации БД промпта
Создает структуру: Класс -> Предмет -> Учителя
Определяет подгруппы на основе количества учителей
"""
import sys
from flask import Flask
from config import Config
from app.core.db_manager import init_system_db, db, switch_school_db
from app.models.system import School
from app.models.school import PromptClassSubject, PromptClassSubjectTeacher
from utils.prompt_db import build_prompt_database

# Создаем Flask app для работы с БД
app = Flask(__name__)
app.config.from_object(Config)
init_system_db(app)

def init_prompt_db_for_all_schools():
    """Инициализирует БД промпта для всех школ"""
    with app.app_context():
        schools = db.session.query(School).all()
    
        if not schools:
            print("❌ Нет школ в системе. Сначала создайте школу.")
            return
        
        for school in schools:
            print(f"\n📚 Обработка школы: {school.name} (ID: {school.id})")
            switch_school_db(school.id)
            
            # Получаем все смены
            from app.models.school import Shift
            shifts = db.session.query(Shift).all()
            
            if not shifts:
                print(f"   ⚠️ Нет смен в школе {school.name}")
                continue
            
            for shift in shifts:
                print(f"   🔄 Обработка смены: {shift.name} (ID: {shift.id})")
                try:
                    build_prompt_database(shift.id, school.id)
                    print(f"   ✅ БД промпта создана для смены {shift.name}")
                except Exception as e:
                    print(f"   ❌ Ошибка при создании БД промпта для смены {shift.name}: {e}")
                    import traceback
                    traceback.print_exc()
        
        print("\n✅ Инициализация БД промпта завершена!")


def init_prompt_db_for_school(school_id, shift_id=None):
    """Инициализирует БД промпта для конкретной школы и смены"""
    with app.app_context():
        school = db.session.query(School).filter_by(id=school_id).first()
        if not school:
            print(f"❌ Школа с ID {school_id} не найдена")
            return
        
        print(f"📚 Обработка школы: {school.name} (ID: {school.id})")
        switch_school_db(school.id)
    
        from app.models.school import Shift
        
        if shift_id:
            # Обрабатываем конкретную смену
            shift = db.session.query(Shift).filter_by(id=shift_id).first()
            if not shift:
                print(f"❌ Смена с ID {shift_id} не найдена")
                return
            
            print(f"   🔄 Обработка смены: {shift.name} (ID: {shift.id})")
            try:
                build_prompt_database(shift.id, school.id)
                print(f"   ✅ БД промпта создана для смены {shift.name}")
            except Exception as e:
                print(f"   ❌ Ошибка при создании БД промпта для смены {shift.name}: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Обрабатываем все смены
            shifts = db.session.query(Shift).all()
            
            if not shifts:
                print(f"   ⚠️ Нет смен в школе {school.name}")
                return
            
            for shift in shifts:
                print(f"   🔄 Обработка смены: {shift.name} (ID: {shift.id})")
                try:
                    build_prompt_database(shift.id, school.id)
                    print(f"   ✅ БД промпта создана для смены {shift.name}")
                except Exception as e:
                    print(f"   ❌ Ошибка при создании БД промпта для смены {shift.name}: {e}")
                    import traceback
                    traceback.print_exc()
        
        print("\n✅ Инициализация БД промпта завершена!")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if len(sys.argv) == 2:
            # Только school_id
            school_id = int(sys.argv[1])
            init_prompt_db_for_school(school_id)
        elif len(sys.argv) == 3:
            # school_id и shift_id
            school_id = int(sys.argv[1])
            shift_id = int(sys.argv[2])
            init_prompt_db_for_school(school_id, shift_id)
        else:
            print("Использование:")
            print("  python init_prompt_db.py                    # Для всех школ")
            print("  python init_prompt_db.py <school_id>         # Для конкретной школы")
            print("  python init_prompt_db.py <school_id> <shift_id>  # Для конкретной школы и смены")
    else:
        # Инициализируем для всех школ
        init_prompt_db_for_all_schools()

