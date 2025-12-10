"""
Скрипт для сброса БД школы и перезагрузки данных с правильной привязкой кабинетов к предметам
"""
import os
import sys
from app import app
from app.core.db_manager import db, school_db_context, clear_school_database
from app.models.school import (
    Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
    Cabinet, CabinetTeacher, Shift
)
from app.services.excel_loader import (
    load_class_load_excel, load_teacher_assignments_excel,
    load_teacher_contacts_excel, load_cabinets_excel
)


def reset_and_reload_school_data(school_id, excel_files_dir=None):
    """
    Сбрасывает БД школы и перезагружает данные из Excel файлов
    с правильной привязкой кабинетов к предметам и учителей к кабинетам
    
    Args:
        school_id: ID школы
        excel_files_dir: Директория с Excel файлами (по умолчанию корень проекта)
    """
    if excel_files_dir is None:
        excel_files_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"\n{'='*60}")
    print(f"Сброс и перезагрузка данных для школы ID: {school_id}")
    print(f"{'='*60}\n")
    
    with app.app_context():
        with school_db_context(school_id):
            # Шаг 1: Очистка БД
            print("📋 Шаг 1: Очистка базы данных...")
            try:
                clear_school_database(school_id)
                print("   ✅ База данных очищена\n")
            except Exception as e:
                print(f"   ⚠️ Предупреждение при очистке: {e}\n")
            
            # Шаг 2: Загрузка классов и предметов (Часы_Класс_Предмет.xlsx)
            print("📋 Шаг 2: Загрузка классов и предметов...")
            class_load_file = os.path.join(excel_files_dir, "Часы_Класс_Предмет.xlsx")
            if os.path.exists(class_load_file):
                try:
                    load_class_load_excel(class_load_file)
                    print("   ✅ Классы и предметы загружены\n")
                except Exception as e:
                    print(f"   ❌ Ошибка при загрузке: {e}\n")
            else:
                print(f"   ⚠️ Файл не найден: {class_load_file}\n")
            
            # Шаг 3: Загрузка учителей и их назначений (Учителя_Предмет.xlsx)
            print("📋 Шаг 3: Загрузка учителей и назначений...")
            teacher_assign_file = os.path.join(excel_files_dir, "Учителя_Предмет.xlsx")
            if os.path.exists(teacher_assign_file):
                try:
                    # Получаем первую смену для загрузки
                    shift = db.session.query(Shift).first()
                    if shift:
                        load_teacher_assignments_excel(teacher_assign_file, shift_id=shift.id)
                        print("   ✅ Учителя и назначения загружены\n")
                    else:
                        print("   ⚠️ Нет смен в БД, создайте смену сначала\n")
                except Exception as e:
                    print(f"   ❌ Ошибка при загрузке: {e}\n")
            else:
                print(f"   ⚠️ Файл не найден: {teacher_assign_file}\n")
            
            # Шаг 4: Загрузка контактов учителей (Учителя_Контакты.xlsx)
            print("📋 Шаг 4: Загрузка контактов учителей...")
            teacher_contacts_file = os.path.join(excel_files_dir, "Учителя_Контакты.xlsx")
            if os.path.exists(teacher_contacts_file):
                try:
                    shift = db.session.query(Shift).first()
                    updated, created = load_teacher_contacts_excel(teacher_contacts_file, shift_id=shift.id if shift else None)
                    print(f"   ✅ Обновлено: {updated}, Создано: {created}\n")
                except Exception as e:
                    print(f"   ❌ Ошибка при загрузке: {e}\n")
            else:
                print(f"   ⚠️ Файл не найден: {teacher_contacts_file}\n")
            
            # Шаг 5: Привязка кабинетов к предметам на основе TeacherAssignment
            print("📋 Шаг 5: Привязка кабинетов к предметам...")
            try:
                # Получаем все назначения учителей с кабинетами
                assignments = db.session.query(TeacherAssignment).filter(
                    TeacherAssignment.default_cabinet.isnot(None),
                    TeacherAssignment.default_cabinet != ''
                ).all()
                
                # Словарь для группировки: предмет -> множество кабинетов
                subject_cabinets = {}
                
                for assignment in assignments:
                    subject_id = assignment.subject_id
                    cabinet_name = assignment.default_cabinet.strip()
                    
                    if subject_id not in subject_cabinets:
                        subject_cabinets[subject_id] = set()
                    subject_cabinets[subject_id].add(cabinet_name)
                
                # Создаем кабинеты и привязываем их к предметам
                created_cabinets = 0
                for subject_id, cabinet_names in subject_cabinets.items():
                    subject = db.session.query(Subject).filter_by(id=subject_id).first()
                    if not subject:
                        continue
                    
                    for cabinet_name in cabinet_names:
                        # Проверяем, существует ли уже такой кабинет для этого предмета
                        existing = db.session.query(Cabinet).filter_by(
                            name=cabinet_name,
                            subject_id=subject_id
                        ).first()
                        
                        if not existing:
                            cabinet = Cabinet(name=cabinet_name, subject_id=subject_id)
                            db.session.add(cabinet)
                            created_cabinets += 1
                
                db.session.commit()
                print(f"   ✅ Создано кабинетов: {created_cabinets}\n")
            except Exception as e:
                print(f"   ❌ Ошибка при привязке кабинетов: {e}\n")
                db.session.rollback()
            
            # Шаг 6: Загрузка кабинетов и учителей из файла (Учителя_Кабинет.xlsx)
            # Этот файл может содержать дополнительную информацию о кабинетах
            print("📋 Шаг 6: Загрузка кабинетов и учителей из файла...")
            cabinets_file = os.path.join(excel_files_dir, "Учителя_Кабинет.xlsx")
            if os.path.exists(cabinets_file):
                try:
                    # Сначала создаем кабинеты без предметов из файла
                    # Потом попытаемся привязать их к предметам на основе учителей
                    load_cabinets_excel(cabinets_file)
                    
                    # Теперь привязываем кабинеты без предметов к предметам
                    # на основе того, какие учителя в них работают
                    cabinets_without_subject = db.session.query(Cabinet).filter_by(
                        subject_id=None
                    ).all()
                    
                    linked_count = 0
                    for cabinet in cabinets_without_subject:
                        # Получаем учителей этого кабинета
                        cabinet_teachers = db.session.query(CabinetTeacher).filter_by(
                            cabinet_id=cabinet.id
                        ).all()
                        
                        if not cabinet_teachers:
                            continue
                        
                        # Находим предметы этих учителей
                        teacher_ids = [ct.teacher_id for ct in cabinet_teachers]
                        assignments = db.session.query(TeacherAssignment).filter(
                            TeacherAssignment.teacher_id.in_(teacher_ids),
                            TeacherAssignment.default_cabinet == cabinet.name
                        ).all()
                        
                        # Группируем по предметам
                        subject_counts = {}
                        for assignment in assignments:
                            subject_id = assignment.subject_id
                            if subject_id not in subject_counts:
                                subject_counts[subject_id] = 0
                            subject_counts[subject_id] += 1
                        
                        # Привязываем к предмету с наибольшим количеством назначений
                        if subject_counts:
                            most_common_subject_id = max(subject_counts, key=subject_counts.get)
                            cabinet.subject_id = most_common_subject_id
                            linked_count += 1
                    
                    db.session.commit()
                    print(f"   ✅ Привязано кабинетов к предметам: {linked_count}\n")
                except Exception as e:
                    print(f"   ❌ Ошибка при загрузке кабинетов: {e}\n")
                    db.session.rollback()
            else:
                print(f"   ⚠️ Файл не найден: {cabinets_file}\n")
            
            # Шаг 7: Финальная проверка и статистика
            print("📋 Шаг 7: Статистика...")
            subjects_count = db.session.query(Subject).count()
            teachers_count = db.session.query(Teacher).count()
            classes_count = db.session.query(ClassGroup).count()
            cabinets_count = db.session.query(Cabinet).count()
            cabinets_with_subject = db.session.query(Cabinet).filter(
                Cabinet.subject_id.isnot(None)
            ).count()
            cabinets_without_subject = db.session.query(Cabinet).filter_by(
                subject_id=None
            ).count()
            
            print(f"   📊 Предметов: {subjects_count}")
            print(f"   📊 Учителей: {teachers_count}")
            print(f"   📊 Классов: {classes_count}")
            print(f"   📊 Кабинетов всего: {cabinets_count}")
            print(f"   📊 Кабинетов с предметом: {cabinets_with_subject}")
            print(f"   📊 Кабинетов без предмета: {cabinets_without_subject}")
            
            if cabinets_without_subject > 0:
                print(f"\n   ⚠️ Внимание: {cabinets_without_subject} кабинетов не привязаны к предметам.")
                print(f"   Привяжите их вручную через интерфейс админ-панели.\n")
            
            print(f"\n{'='*60}")
            print("✅ Перезагрузка данных завершена!")
            print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python reset_and_reload_data.py <school_id> [excel_files_dir]")
        print("\nПример:")
        print("  python reset_and_reload_data.py 1")
        print("  python reset_and_reload_data.py 1 C:/path/to/excel/files")
        sys.exit(1)
    
    school_id = int(sys.argv[1])
    excel_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    reset_and_reload_school_data(school_id, excel_dir)

