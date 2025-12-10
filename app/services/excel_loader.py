# app/services/excel_loader.py
import pandas as pd
import re
from app.core.db_manager import db
from app.models.school import Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment, Cabinet, CabinetTeacher


def load_class_load_excel(filepath, shift_id=None, school_id=None):
    """
    Загружает файл 'Часы_Класс_Предмет'
    Формат: каждый лист = одна смена, строки = классы, столбцы = предметы, ячейки = количество часов
    Если shift_id не указан, создает смены автоматически на основе названий листов
    """
    from app.models.school import Shift, ScheduleSettings
    
    # Читаем все листы из файла
    excel_file = pd.ExcelFile(filepath)
    sheet_names = excel_file.sheet_names
    
    created_shifts = {}
    
    # Если shift_id не указан, создаем смены для каждого листа
    if not shift_id:
        for sheet_name in sheet_names:
            # Создаем или находим смену с названием листа
            shift = db.session.query(Shift).filter_by(name=sheet_name).first()
            if not shift:
                shift = Shift(name=sheet_name, is_active=False)
                db.session.add(shift)
                db.session.flush()
                
                # Создаем настройки по умолчанию для смены
                for day in range(1, 8):
                    setting = ScheduleSettings(shift_id=shift.id, day_of_week=day, lessons_count=6)
                    db.session.add(setting)
                db.session.flush()
                
                created_shifts[sheet_name] = shift.id
            else:
                created_shifts[sheet_name] = shift.id
        
        db.session.commit()
    
    # Обрабатываем каждый лист
    for sheet_name in sheet_names:
        # Определяем shift_id для этого листа
        current_shift_id = shift_id
        if not current_shift_id:
            current_shift_id = created_shifts.get(sheet_name)
            if not current_shift_id:
                continue
        
        # Читаем лист
        df = pd.read_excel(filepath, sheet_name=sheet_name)
        
        # Убираем полностью пустые строки и столбцы
        df = df.dropna(how='all').dropna(axis=1, how='all')
        
        if df.empty:
            continue
        
        # Определяем столбец с классами (первый столбец или столбец с названием "Класс")
        class_col = None
        original_columns = list(df.columns)
        for col in original_columns:
            col_lower = str(col).strip().lower()
            if any(word in col_lower for word in ['класс', 'class']):
                class_col = col
                break
        
        # Если есть столбец с названием "Класс" - используем его как индекс
        if class_col:
            df_indexed = df.set_index(class_col)
        # Иначе первый столбец - это классы
        else:
            df_indexed = df.set_index(df.columns[0])
        
        # Убираем строки с пустым индексом (класс)
        df_indexed = df_indexed[df_indexed.index.notna()]
        df_indexed.index = df_indexed.index.astype(str).str.strip()
        
        # Получаем список предметов (столбцов) после установки индекса
        subject_columns = [col for col in df_indexed.columns if not pd.isna(col) and str(col).strip().lower() not in ['nan', '']]
        
        # Проходим по всем строкам (классам) и столбцам (предметам)
        for class_name in df_indexed.index:
            if not class_name or str(class_name).lower() == 'nan':
                continue
            
            # Создаем или находим класс
            cls = db.session.query(ClassGroup).filter_by(name=str(class_name)).first()
            if not cls:
                cls = ClassGroup(name=str(class_name))
                db.session.add(cls)
            db.session.flush()
            
            # Проходим по всем столбцам (предметам)
            for subject_name in subject_columns:
                subject_name_clean = str(subject_name).strip()
                
                if not subject_name_clean or subject_name_clean.lower() in ['nan', '']:
                    continue
                
                # Получаем количество часов из ячейки с обработкой ошибок
                try:
                    # Проверяем, что и класс, и предмет существуют в DataFrame
                    if class_name not in df_indexed.index:
                        continue
                    if subject_name not in df_indexed.columns:
                        continue
                    
                    cell_value = df_indexed.loc[class_name, subject_name]
                except (KeyError, IndexError, TypeError) as e:
                    # Пропускаем, если не удалось получить значение
                    continue
                
                if pd.isna(cell_value):
                    continue
                
                # Преобразуем в число
                try:
                    hours = int(float(cell_value))
                except (ValueError, TypeError):
                    continue
                
                if hours <= 0:
                    continue
                
                # Создаем или находим предмет
                subj = db.session.query(Subject).filter_by(name=subject_name_clean).first()
                if not subj:
                    subj = Subject(name=subject_name_clean)
                    db.session.add(subj)
                db.session.flush()
                
                # Нагрузка (общая для всех смен, shift_id = None)
                # Проверяем существующую нагрузку без привязки к смене
                load = db.session.query(ClassLoad).filter_by(shift_id=None, class_id=cls.id, subject_id=subj.id).first()
                if load:
                    load.hours_per_week = hours
                else:
                    # Если нет общей нагрузки, проверяем, есть ли для конкретной смены (для обратной совместимости)
                    load = db.session.query(ClassLoad).filter_by(shift_id=current_shift_id, class_id=cls.id, subject_id=subj.id).first()
                    if load:
                        # Обновляем существующую, убирая привязку к смене
                        load.shift_id = None
                        load.hours_per_week = hours
                    else:
                        # Создаем новую нагрузку без привязки к смене
                        db.session.add(ClassLoad(shift_id=None, class_id=cls.id, subject_id=subj.id, hours_per_week=hours))
        
        db.session.commit()
    
    return created_shifts if not shift_id else None


def parse_teacher_names(cell_value):
    """
    Парсит строку с именами учителей из ячейки Excel
    Может содержать несколько учителей, разделенных запятой, точкой с запятой, или новой строкой
    """
    if pd.isna(cell_value):
        return []
    
    text = str(cell_value).strip()
    if not text or text.lower() in ['nan', 'none', '']:
        return []
    
    # Разделяем по различным разделителям
    # Сначала по переносу строки, потом по точке с запятой, потом по запятой
    teachers = re.split(r'[\n\r;,]', text)
    
    # Очищаем и фильтруем
    result = []
    for teacher in teachers:
        teacher = teacher.strip()
        if teacher and teacher.lower() not in ['nan', 'none', '']:
            result.append(teacher)
    
    return result


def load_teacher_assignments_excel(filepath, shift_id=None, school_id=None):
    """
    Загружает файл 'Учителя_Предмет'
    Формат: столбцы = предметы, в ячейках = учителя, которые преподают этот предмет
    ВАЖНО: Учителя добавляются к предмету БЕЗ автоматического назначения на классы.
    Классы нужно назначать вручную через интерфейс админ-панели.
    """
    df = pd.read_excel(filepath)

    # Убираем полностью пустые строки и столбцы
    df = df.dropna(how='all').dropna(axis=1, how='all')

    # Определяем структуру: столбцы = предметы, строки могут быть любыми (или одна строка)
    # Если есть столбец с "Класс", убираем его - нам он не нужен
    
    # Ищем столбец с классами и удаляем его, если есть
    class_col = None
    for col in df.columns:
        col_lower = str(col).strip().lower()
        if any(word in col_lower for word in ['класс', 'class']):
            class_col = col
            break
    
    if class_col:
        df = df.drop(columns=[class_col])
    
    # Если первый столбец выглядит как "Класс", тоже удаляем
    if df.columns[0] and any(word in str(df.columns[0]).strip().lower() for word in ['класс', 'class']):
        df = df.drop(columns=[df.columns[0]])

    if not shift_id:
        return

    # Проходим по всем столбцам (предметам)
    for subject_name in df.columns:
        if pd.isna(subject_name) or str(subject_name).strip().lower() in ['nan', '']:
            continue

        subject_name = str(subject_name).strip()
        
        # Создаем или находим предмет
        subj = db.session.query(Subject).filter_by(name=subject_name).first()
        if not subj:
            subj = Subject(name=subject_name)
            db.session.add(subj)
        db.session.flush()

        # Собираем всех учителей для этого предмета из всех строк
        all_teachers = []
        for idx in df.index:
            try:
                # Проверяем, что столбец существует
                if subject_name not in df.columns:
                    continue
                cell_value = df.loc[idx, subject_name]
            except (KeyError, IndexError, TypeError):
                continue
            teacher_names = parse_teacher_names(cell_value)
            all_teachers.extend(teacher_names)
        
        # Убираем дубликаты
        all_teachers = list(set(all_teachers))

        if not all_teachers:
            continue

        # Находим все классы, где есть этот предмет в данной смене
        class_loads = db.session.query(ClassLoad).filter_by(shift_id=shift_id, subject_id=subj.id).all()
        
        # Для каждого учителя создаем или находим его
        for teacher_name in all_teachers:
            if not teacher_name or str(teacher_name).strip().lower() in ['nan', '']:
                continue

            teacher_name = str(teacher_name).strip()

            # Создаем или находим учителя
            teacher = db.session.query(Teacher).filter_by(full_name=teacher_name).first()
            if not teacher:
                # Генерируем короткое имя
                parts = teacher_name.split()
                if len(parts) >= 2:
                    short = parts[0][0] + "." + parts[1][0] + "."
                else:
                    short = parts[0][:2] + "."
                teacher = Teacher(full_name=teacher_name, short_name=short)
                db.session.add(teacher)
            db.session.flush()

            # ВАЖНО: НЕ создаем автоматически назначения на классы
            # Учитель будет добавлен к предмету, но БЕЗ классов
            # Классы нужно назначать вручную через интерфейс админ-панели
            
            # Проверяем, есть ли уже хотя бы одно назначение этого учителя на этот предмет
            # Если есть - значит учитель уже добавлен к предмету, пропускаем
            existing_assignment = db.session.query(TeacherAssignment).filter_by(
                shift_id=shift_id,
                teacher_id=teacher.id,
                subject_id=subj.id
            ).first()
            
            # Если назначений нет, создаем минимальную запись для первого класса (если есть классы)
            # Это нужно только для того, чтобы учитель отображался в списке учителей предмета
            # В интерфейсе будет показано, что классы не назначены, и админ должен проставить галочки вручную
            if not existing_assignment:
                if class_loads:
                    # Создаем назначение только для первого класса (как маркер, что учитель добавлен к предмету)
                    # Это позволит учителю отображаться в списке, но в интерфейсе будет показано, что классы не назначены
                    # Админ должен вручную проставить галочки для нужных классов
                    first_class_id = class_loads[0].class_id
                    db.session.add(TeacherAssignment(
                        shift_id=shift_id,
                        teacher_id=teacher.id,
                        subject_id=subj.id,
                        class_id=first_class_id,
                        hours_per_week=0,
                        default_cabinet=None
                    ))
                else:
                    # Если классов нет, создаем временную запись с первым доступным классом из всех классов
                    # или просто пропускаем - учитель будет добавлен вручную позже
                    # Но лучше создать запись, чтобы учитель отображался
                    first_class = db.session.query(ClassGroup).first()
                    if first_class:
                        db.session.add(TeacherAssignment(
                            shift_id=shift_id,
                            teacher_id=teacher.id,
                            subject_id=subj.id,
                            class_id=first_class.id,
                            hours_per_week=0,
                            default_cabinet=None
                        ))

    db.session.commit()


def load_teacher_contacts_excel(filepath, shift_id=None, school_id=None):
    """
    Загружает файл 'Учителя_Контакты'
    Формат: столбцы с именами учителей, телефонами и Telegram ID
    Обновляет поля phone и telegram_id для существующих учителей
    """
    df = pd.read_excel(filepath)
    
    # Убираем полностью пустые строки и столбцы
    df = df.dropna(how='all').dropna(axis=1, how='all')
    
    # Ищем столбцы с именами, телефонами и Telegram ID
    name_col = None
    phone_col = None
    telegram_id_col = None
    
    for col in df.columns:
        col_lower = str(col).strip().lower()
        # Ищем столбец с именем учителя
        if name_col is None and any(word in col_lower for word in ['учитель', 'имя', 'фио', 'teacher', 'name', 'full_name']):
            name_col = col
        # Ищем столбец с телефоном
        if phone_col is None and any(word in col_lower for word in ['телефон', 'phone', 'tel', 'номер']):
            phone_col = col
        # Ищем столбец с Telegram ID
        if telegram_id_col is None and any(word in col_lower for word in ['telegram', 'telegram_id', 'id', 'tg_id', 'tg']):
            telegram_id_col = col
    
    # Если не нашли столбцы по названиям, используем первые столбцы
    if name_col is None and len(df.columns) > 0:
        name_col = df.columns[0]
    if phone_col is None and len(df.columns) > 1:
        phone_col = df.columns[1]
    if telegram_id_col is None and len(df.columns) > 2:
        telegram_id_col = df.columns[2]
    
    if not name_col:
        raise ValueError("Не удалось найти столбец с именами учителей")
    
    updated_count = 0
    created_count = 0
    
    # Проходим по всем строкам
    for idx in df.index:
        # Получаем имя учителя
        teacher_name = df.loc[idx, name_col]
        if pd.isna(teacher_name) or str(teacher_name).strip().lower() in ['nan', '']:
            continue
        
        teacher_name = str(teacher_name).strip()
        
        # Получаем телефон, если есть столбец
        phone = None
        if phone_col:
            phone_value = df.loc[idx, phone_col]
            if not pd.isna(phone_value):
                phone = str(phone_value).strip()
                if phone.lower() in ['nan', 'none', '']:
                    phone = None
        
        # Получаем Telegram ID, если есть столбец
        telegram_id = None
        if telegram_id_col:
            telegram_id_value = df.loc[idx, telegram_id_col]
            if not pd.isna(telegram_id_value):
                telegram_id = str(telegram_id_value).strip()
                if telegram_id.lower() in ['nan', 'none', '']:
                    telegram_id = None
        
        # Ищем учителя по имени
        teacher = db.session.query(Teacher).filter_by(full_name=teacher_name).first()
        
        if teacher:
            # Обновляем существующего учителя
            updated = False
            if phone and teacher.phone != phone:
                teacher.phone = phone
                updated = True
            if telegram_id and teacher.telegram_id != telegram_id:
                teacher.telegram_id = telegram_id
                updated = True
            if updated:
                updated_count += 1
        else:
            # Создаем нового учителя, если его нет
            # Генерируем короткое имя
            parts = teacher_name.split()
            if len(parts) >= 2:
                short = parts[0][0] + "." + parts[1][0] + "."
            else:
                short = parts[0][:2] + "."
            
            teacher = Teacher(
                full_name=teacher_name,
                short_name=short,
                phone=phone,
                telegram_id=telegram_id
            )
            db.session.add(teacher)
            created_count += 1
    
    db.session.commit()
    return updated_count, created_count


def load_cabinets_excel(filepath, school_id=None):
    """
    Загружает файл 'Учителя_Кабинет'
    Формат: столбцы: №, Кабинет, Учителя (список учителей через запятую)
    Создает кабинеты и связывает их с учителями
    Автоматически привязывает кабинеты к предметам на основе учителей
    ВАЖНО: Использует существующих учителей из БД, не создает дубли
    """
    df = pd.read_excel(filepath)
    
    # Убираем полностью пустые строки и столбцы
    df = df.dropna(how='all').dropna(axis=1, how='all')
    
    # Ищем столбцы
    cabinet_col = None
    teachers_col = None
    subject_col = None  # Опциональный столбец с предметом
    
    for col in df.columns:
        col_lower = str(col).strip().lower()
        if cabinet_col is None and any(word in col_lower for word in ['кабинет', 'cabinet', 'номер']):
            cabinet_col = col
        if teachers_col is None and any(word in col_lower for word in ['учителя', 'учитель', 'teacher', 'teachers']):
            teachers_col = col
        if subject_col is None and any(word in col_lower for word in ['предмет', 'subject']):
            subject_col = col
    
    # Если не нашли по названиям, используем стандартные
    if cabinet_col is None:
        # Ищем столбец "Кабинет"
        for col in df.columns:
            if 'кабинет' in str(col).lower():
                cabinet_col = col
                break
        if cabinet_col is None and len(df.columns) >= 2:
            cabinet_col = df.columns[1]  # Второй столбец обычно кабинет
    
    if teachers_col is None:
        # Ищем столбец "Учителя"
        for col in df.columns:
            if 'учител' in str(col).lower():
                teachers_col = col
                break
        if teachers_col is None and len(df.columns) >= 3:
            teachers_col = df.columns[2]  # Третий столбец обычно учителя
    
    if not cabinet_col or not teachers_col:
        raise ValueError("Не удалось найти столбцы 'Кабинет' и 'Учителя' в файле")
    
    print(f"   Используются столбцы: Кабинет='{cabinet_col}', Учителя='{teachers_col}'")
    if subject_col:
        print(f"   Найден столбец с предметом: '{subject_col}'")
    
    created_cabinets = 0
    created_links = 0
    skipped_teachers = 0
    
    # Проходим по всем строкам
    for idx in df.index:
        # Получаем название кабинета
        cabinet_name = df.loc[idx, cabinet_col]
        if pd.isna(cabinet_name) or str(cabinet_name).strip().lower() in ['nan', '']:
            continue
        
        cabinet_name = str(cabinet_name).strip()
        
        # Получаем предмет, если есть столбец
        subject_id = None
        if subject_col:
            subject_name = df.loc[idx, subject_col]
            if not pd.isna(subject_name) and str(subject_name).strip().lower() not in ['nan', '']:
                subject = db.session.query(Subject).filter_by(name=str(subject_name).strip()).first()
                if subject:
                    subject_id = subject.id
        
        # Получаем список учителей
        teachers_value = df.loc[idx, teachers_col]
        if pd.isna(teachers_value) or str(teachers_value).strip().lower() in ['nan', '']:
            # Кабинет без учителей - создаем его пустым
            cabinet = db.session.query(Cabinet).filter_by(
                name=cabinet_name,
                subject_id=subject_id
            ).first()
            if not cabinet:
                cabinet = Cabinet(name=cabinet_name, subject_id=subject_id)
                db.session.add(cabinet)
                created_cabinets += 1
            continue
        
        # Парсим список учителей (могут быть через запятую, точку с запятой и т.д.)
        teachers_str = str(teachers_value).strip()
        teacher_names = parse_teacher_names(teachers_str)
        
        if not teacher_names:
            # Кабинет без учителей - создаем его пустым
            cabinet = db.session.query(Cabinet).filter_by(
                name=cabinet_name,
                subject_id=subject_id
            ).first()
            if not cabinet:
                cabinet = Cabinet(name=cabinet_name, subject_id=subject_id)
                db.session.add(cabinet)
                created_cabinets += 1
            continue
        
        # Если предмет не указан в файле, определяем его по учителям
        if not subject_id:
            # Находим предметы этих учителей из назначений
            teacher_ids = []
            for teacher_name in teacher_names:
                teacher = db.session.query(Teacher).filter_by(full_name=teacher_name).first()
                if teacher:
                    teacher_ids.append(teacher.id)
            
            if teacher_ids:
                # Ищем назначения этих учителей с указанным кабинетом
                assignments = db.session.query(TeacherAssignment).filter(
                    TeacherAssignment.teacher_id.in_(teacher_ids),
                    TeacherAssignment.default_cabinet == cabinet_name
                ).all()
                
                # Группируем по предметам
                subject_counts = {}
                for assignment in assignments:
                    subj_id = assignment.subject_id
                    if subj_id not in subject_counts:
                        subject_counts[subj_id] = 0
                    subject_counts[subj_id] += 1
                
                # Привязываем к предмету с наибольшим количеством назначений
                if subject_counts:
                    subject_id = max(subject_counts, key=subject_counts.get)
        
        # Создаем или находим кабинет
        cabinet = db.session.query(Cabinet).filter_by(
            name=cabinet_name,
            subject_id=subject_id
        ).first()
        if not cabinet:
            cabinet = Cabinet(name=cabinet_name, subject_id=subject_id)
            db.session.add(cabinet)
            db.session.flush()  # Нужно для получения ID
            created_cabinets += 1
        
        # Связываем учителей с кабинетом
        for teacher_name in teacher_names:
            # Ищем учителя в БД (используем существующих, не создаем дубли)
            teacher = db.session.query(Teacher).filter_by(full_name=teacher_name).first()
            
            if not teacher:
                # Учитель не найден - пропускаем (не создаем дубли)
                skipped_teachers += 1
                print(f"   ⚠️ Учитель '{teacher_name}' не найден в БД, пропущен")
                continue
            
            # Проверяем, нет ли уже такой связи
            existing_link = db.session.query(CabinetTeacher).filter_by(
                cabinet_id=cabinet.id,
                teacher_id=teacher.id
            ).first()
            
            if not existing_link:
                # Создаем связь
                cabinet_teacher = CabinetTeacher(
                    cabinet_id=cabinet.id,
                    teacher_id=teacher.id
                )
                db.session.add(cabinet_teacher)
                created_links += 1
    
    db.session.commit()
    
    print(f"   ✅ Создано кабинетов: {created_cabinets}")
    print(f"   ✅ Создано связей учитель-кабинет: {created_links}")
    if skipped_teachers > 0:
        print(f"   ⚠️ Пропущено учителей (не найдены в БД): {skipped_teachers}")
    
    return created_cabinets, created_links, skipped_teachers

