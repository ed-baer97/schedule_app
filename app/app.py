# app/app.py
from flask import Flask, request, jsonify, render_template # Добавлен render_template
from .models import db, Teacher, Subject, Class, SubGroup, Room, Lesson, ClassSubjectRequirement, TeacherSubjectRequirement, TeacherSubject, Replacement, Shift # Добавлен Replacement
# app/app.py
# ... (другие импорты) ...
from .services import add_lesson, update_lesson, remove_lesson, validate_lesson, check_teacher_conflict, check_room_conflict, check_subgroup_conflict, get_subjects_for_class, get_teachers_for_class, get_teachers_for_class_and_subject # Добавлены get_subjects_for_class, get_teachers_for_class, get_teachers_for_class_and_subject
# ... (остальные импорты и код)...
from .ai_assistant import handle_command_via_api # Импортируем заглушку
import os
# --- НОВОЕ: Импорты для загрузки файлов ---
from werkzeug.utils import secure_filename
import pandas as pd
import tempfile # Для временного хранения файлов

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ---
def get_day_name(day_index):
    """Вспомогательная функция для преобразования индекса дня в строку."""
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт']
    return days[day_index] if 0 <= day_index < len(days) else 'N/A'

def get_day_name_full(day_index):
    """Вспомогательная функция для получения полного названия дня недели."""
    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА']
    return days[day_index] if 0 <= day_index < len(days) else 'N/A'


def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///schedule.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # --- НОВОЕ: Настройки для загрузки файлов ---
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = tempfile.gettempdir() # Используем временную директорию ОС
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    db.init_app(app)

    with app.app_context():
        db.create_all() # Создаём таблицы при запуске

        # --- Добавим создание базовых смен при запуске, если их нет ---
        if Shift.query.count() == 0:
            print("Создание базовых смен...")
            shift_1 = Shift(id=1, name="1 смена")
            shift_2 = Shift(id=2, name="2 смена")
            shift_3 = Shift(id=3, name="3 смена") # Добавляем 3-ю смену
            db.session.add(shift_1)
            db.session.add(shift_2)
            db.session.add(shift_3)
            db.session.commit()
            print("Базовые смены созданы.")

        # --- УБРАЛИ БЛОК С ТЕСТОВЫМИ ДАННЫМИ (или оставьте, если нужно) ---
        # add_test_data = False
        # if add_test_data and Teacher.query.count() == 0:
        #     print("Добавление тестовых данных...")
        #     # ... (код добавления тестовых данных) ...
        #     print("Тестовые данные добавлены.")


    @app.route('/')
    def main_index(): # <-- Изменили имя функции на main_index
        return render_template('index.html') # Главная страница

    # --- НОВЫЙ маршрут для загрузки данных ---
    @app.route('/upload_data', methods=['POST'])
    def upload_data():
        if 'file_hours' not in request.files or 'file_teachers' not in request.files:
            return jsonify({"error": "Файлы не найдены в запросе"}), 400

        file_hours = request.files['file_hours']
        file_teachers = request.files['file_teachers']

        if file_hours.filename == '' or file_teachers.filename == '':
            return jsonify({"error": "Имя файла пустое"}), 400

        # Проверка типа файла (опционально, но рекомендуется)
        if not (file_hours.filename.endswith('.xlsx') or file_hours.filename.endswith('.xls')):
             return jsonify({"error": "Файл часов должен быть .xlsx или .xls"}), 400
        if not (file_teachers.filename.endswith('.xlsx') or file_teachers.filename.endswith('.xls')):
             return jsonify({"error": "Файл нагрузки должен быть .xlsx или .xls"}), 400

        try:
            # --- Сохраняем файлы во временные файлы ---
            # Используем tempfile.NamedTemporaryFile для автоматической очистки
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_hours.filename)[1]) as temp_file_hours:
                file_hours.save(temp_file_hours.name)
                temp_filename_hours = temp_file_hours.name

            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_teachers.filename)[1]) as temp_file_teachers:
                file_teachers.save(temp_file_teachers.name)
                temp_filename_teachers = temp_file_teachers.name

            # --- Вызываем парсер ---
            result_message = parse_and_load_data(temp_filename_hours, temp_filename_teachers)

            # --- Удаляем временные файлы ---
            os.unlink(temp_filename_hours)
            os.unlink(temp_filename_teachers)

            return jsonify({"message": result_message})

        except Exception as e:
            # Убедитесь, что временные файлы удаляются даже при ошибке
            if 'temp_filename_hours' in locals():
                try:
                    os.unlink(temp_filename_hours)
                except:
                    pass
            if 'temp_filename_teachers' in locals():
                try:
                    os.unlink(temp_filename_teachers)
                except:
                    pass
            print(f"Ошибка при загрузке данных: {e}") # Логирование ошибки
            return jsonify({"error": f"Ошибка обработки файла: {str(e)}"}), 500


    # --- НОВЫЙ маршрут для экспорта расписания в Excel (список) ---
    @app.route('/export_schedule', methods=['GET'])
    def export_schedule():
        import io
        from flask import send_file
        import xlsxwriter

        shift_filter = request.args.get('shift', type=int)
        # Начинаем с JOIN, чтобы получить доступ к смене класса через подгруппу
        query = db.session.query(Lesson).join(SubGroup).join(Class).join(Shift)
        if shift_filter:
            query = query.filter(Shift.id == shift_filter)

        lessons = query.all()

        # Создаём буфер в памяти для файла Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet()

        # Заголовки
        worksheet.write(0, 0, 'День недели')
        worksheet.write(0, 1, 'Номер урока')
        worksheet.write(0, 2, 'Класс')
        worksheet.write(0, 3, 'Подгруппа')
        worksheet.write(0, 4, 'Предмет')
        worksheet.write(0, 5, 'Учитель')
        worksheet.write(0, 6, 'Кабинет')

        # Словари для быстрого поиска имён по ID
        teachers_dict = {t.id: t.name for t in Teacher.query.all()}
        subjects_dict = {s.id: s.name for s in Subject.query.all()}
        rooms_dict = {r.id: r.name for r in Room.query.all()}
        # --- ИСПРАВЛЕНО: subgroups_dict содержит объекты SubGroup ---
        subgroups_dict = {sg.id: sg for sg in SubGroup.query.all()} # sg - объект модели SubGroup
        classes_dict = {c.id: c.name for c in Class.query.all()}

        row = 1
        for lesson in lessons:
            worksheet.write(row, 0, get_day_name(lesson.day_of_week)) # Используем глобальную функцию
            worksheet.write(row, 1, lesson.lesson_number)
            # Получаем имя класса через подгруппу
            # subgroups_dict[lesson.subgroup_id] теперь возвращает объект SubGroup
            subgroup_obj = subgroups_dict.get(lesson.subgroup_id)
            if subgroup_obj:
                class_name = classes_dict.get(subgroup_obj.class_id, 'N/A') # Получаем class_id у объекта подгруппы
                subgroup_name = subgroup_obj.name # Получаем имя подгруппы у объекта подгруппы
            else:
                class_name = 'N/A'
                subgroup_name = 'N/A'
            worksheet.write(row, 2, class_name)
            worksheet.write(row, 3, subgroup_name) # Записываем имя подгруппы
            worksheet.write(row, 4, subjects_dict.get(lesson.subject_id, 'N/A'))
            worksheet.write(row, 5, teachers_dict.get(lesson.teacher_id, 'N/A'))
            worksheet.write(row, 6, rooms_dict.get(lesson.room_id, 'N/A'))
            row += 1

        workbook.close()
        output.seek(0)

        filename = f"schedule_shift_{shift_filter if shift_filter else 'all'}.xlsx"
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )


    # --- НОВЫЙ маршрут для форматированного экспорта расписания в Excel ---
    @app.route('/export_schedule_formatted', methods=['GET'])
    def export_schedule_formatted():
        import io
        from flask import send_file
        import xlsxwriter

        shift_filter = request.args.get('shift', type=int)
        if not shift_filter:
            return jsonify({"error": "Не указана смена для экспорта."}), 400

        # Загружаем уроки для выбранной смены
        query = db.session.query(Lesson).join(SubGroup).join(Class).join(Shift).filter(Shift.id == shift_filter)
        lessons = query.all()

        # Загружаем справочники
        teachers_dict = {t.id: t.name for t in Teacher.query.all()}
        subjects_dict = {s.id: s.name for s in Subject.query.all()}
        rooms_dict = {r.id: r.name for r in Room.query.all()}
        subgroups_dict = {sg.id: sg for sg in SubGroup.query.all()} # Ключ - ID, Значение - объект SubGroup
        classes_dict = {c.id: c.name for c in Class.query.all()}

        # Группируем уроки: day_of_week -> lesson_number -> class_name -> lesson_data
        schedule_grid = {}
        class_names = set() # Множество для уникальных имён классов
        max_lesson_number = 0 # Для определения максимального количества уроков в день

        for lesson in lessons:
            subgroup = subgroups_dict.get(lesson.subgroup_id)
            if not subgroup:
                continue # Пропускаем уроки с несуществующей подгруппой
            class_name = classes_dict.get(subgroup.class_id)
            if not class_name:
                continue # Пропускаем уроки с несуществующим классом

            day = lesson.day_of_week
            lesson_num = lesson.lesson_number

            if day not in schedule_grid:
                schedule_grid[day] = {}
            if lesson_num not in schedule_grid[day]:
                schedule_grid[day][lesson_num] = {}
            # Для упрощения, если в одном слоте для класса есть несколько подгрупп (например, разные учителя),
            # мы просто добавим их в одну ячейку, разделяя символом новой строки.
            # В реальности может потребоваться более сложная логика.
            lesson_key = class_name
            lesson_info = {
                'subject': subjects_dict.get(lesson.subject_id, 'N/A'),
                'room': rooms_dict.get(lesson.room_id, 'N/A'),
                'teacher': teachers_dict.get(lesson.teacher_id, 'N/A')
            }
            if lesson_key in schedule_grid[day][lesson_num]:
                # Если уже есть урок для этого класса в этом слоте, добавляем к существующему
                existing_info = schedule_grid[day][lesson_num][lesson_key]
                existing_info['subject'] += f"\n{lesson_info['subject']}"
                existing_info['room'] += f"\n{lesson_info['room']}"
                existing_info['teacher'] += f"\n{lesson_info['teacher']}"
            else:
                schedule_grid[day][lesson_num][lesson_key] = lesson_info

            class_names.add(class_name)
            if lesson_num > max_lesson_number:
                max_lesson_number = lesson_num

        sorted_class_names = sorted(list(class_names)) # Сортируем имена классов для стабильности

        # Создаём буфер в памяти для файла Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet()

        # --- Форматирование ---
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#D3D3D3', # Светло-серый фон
            'border': 1
        })
        day_header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#E6E6FA', # Светло-голубой фон для дней
            'border': 1,
            'rotation': 90 # Поворот текста на 90 градусов
        })
        class_header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#F0F8FF', # Светло-синий фон для заголовков классов
            'border': 1
        })
        lesson_info_format = workbook.add_format({
            'align': 'left',
            'valign': 'top',
            'text_wrap': True, # Перенос текста
            'border': 1
        })

        # --- Заполнение таблицы ---
        current_row = 0
        current_col = 0

        # Ячейка для "Расписание уроков" (может быть объединена)
        worksheet.merge_range(current_row, current_col, current_row, 1 + len(sorted_class_names), f'Расписание уроков - Смена {shift_filter}', header_format)
        current_row += 1

        # Заголовки классов (вторая строка)
        worksheet.write(current_row, 0, 'День/Урок', header_format)
        worksheet.write(current_row, 1, '', header_format) # Пустая ячейка под "Урок"
        col_idx = 2
        for class_name in sorted_class_names:
            worksheet.write(current_row, col_idx, class_name, class_header_format)
            col_idx += 1
        current_row += 1

        # Дни недели: ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА']

        for day_index in range(5): # Предполагаем 5 дней
            if day_index not in schedule_grid:
                # Пропускаем день, если нет уроков
                continue

            day_name = get_day_name_full(day_index) # Используем вспомогательную функцию
            # Записываем день недели в первый столбец, объединяя ячейки для всех уроков этого дня
            lesson_count_for_day = len(schedule_grid[day_index])
            start_row_for_day = current_row
            end_row_for_day = current_row + lesson_count_for_day - 1
            worksheet.merge_range(start_row_for_day, 0, end_row_for_day, 0, day_name, day_header_format)

            # Проходим по урокам в этом дне (от 1 до max_lesson_number)
            for lesson_num in range(1, max_lesson_number + 1):
                if lesson_num not in schedule_grid[day_index]:
                    # Пропускаем номер урока, если нет уроков
                    continue

                # Записываем номер урока во второй столбец
                worksheet.write(current_row, 1, lesson_num, header_format)

                # Проходим по классам
                col_idx = 2
                for class_name in sorted_class_names:
                    lesson_info = schedule_grid[day_index][lesson_num].get(class_name)
                    cell_content = ""
                    if lesson_info:
                        cell_content = f"{lesson_info['subject']}\n{lesson_info['room']}\n{lesson_info['teacher']}"
                    worksheet.write(current_row, col_idx, cell_content, lesson_info_format)
                    col_idx += 1

                current_row += 1 # Переходим к следующей строке для следующего урока

        workbook.close()
        output.seek(0)

        filename = f"schedule_shift_{shift_filter}_formatted.xlsx"
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )


    # --- НОВЫЙ маршрут для очистки ячеек (уроков) для выбранной смены ---
    @app.route('/clear_schedule', methods=['POST'])
    def clear_schedule():
        data = request.get_json()
        shift_id = data.get('shift_id')

        if shift_id is None:
            return jsonify({"error": "ID смены не указан"}), 400

        # Начинаем с JOIN, чтобы получить доступ к смене класса через подгруппу
        query = db.session.query(Lesson).join(SubGroup).join(Class).join(Shift).filter(Shift.id == shift_id)
        lessons_to_delete = query.all()

        deleted_count = 0
        for lesson in lessons_to_delete:
            db.session.delete(lesson)
            deleted_count += 1

        db.session.commit()
        return jsonify({"message": f"Успешно удалено {deleted_count} уроков для смены {shift_id}."})

    # --- НОВЫЙ маршрут для очистки всей базы данных ---
    @app.route('/clear_database', methods=['POST'])
    def clear_database():
        try:
            # Важно: порядок удаления важен из-за внешних ключей
            # Удаляем сначала дочерние таблицы
            Lesson.query.delete()
            ClassSubjectRequirement.query.delete()
            TeacherSubjectRequirement.query.delete()
            TeacherSubject.query.delete()
            Replacement.query.delete() # Теперь Replacement определён и импортирован
            SubGroup.query.delete()
            Room.query.delete()
            Class.query.delete()
            Subject.query.delete()
            Teacher.query.delete()
            # Потом родительскую таблицу Shift
            Shift.query.delete()

            db.session.commit()
            return jsonify({"message": "База данных успешно очищена."})
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при очистке базы данных: {e}")
            return jsonify({"error": f"Ошибка при очистке базы данных: {str(e)}"}), 500

    @app.route('/api/class_subjects/<int:class_id>', methods=['GET'])
    def get_class_subjects(class_id):
        subjects = get_subjects_for_class(class_id)
        return jsonify([{"id": s.id, "name": s.name} for s in subjects])

    @app.route('/api/class_teachers/<int:class_id>', methods=['GET'])
    def get_class_teachers(class_id):
        teachers = get_teachers_for_class(class_id)
        return jsonify([{"id": t.id, "name": t.name} for t in teachers])

    # --- НОВЫЙ маршрут ---
    @app.route('/api/class_teachers_for_subject/<int:class_id>/<int:subject_id>', methods=['GET'])
    def get_class_teachers_for_subject(class_id, subject_id):
        print(f"DEBUG: Вызван маршрут для class_id={class_id}, subject_id={subject_id}") # Отладочный вывод
        teachers = get_teachers_for_class_and_subject(class_id, subject_id)
        return jsonify([{"id": t.id, "name": t.name} for t in teachers])


    # --- API для получения списка смен (ОБНОВЛЁН) ---
    @app.route('/api/shifts', methods=['GET'])
    def get_shifts():
        # Загружаем список смен из БД
        shifts = Shift.query.all()
        return jsonify([{"id": s.id, "name": s.name} for s in shifts])

    # --- API для получения требований класс-предмет (для JS) ---
    @app.route('/api/class_subject_requirements', methods=['GET'])
    def get_class_subject_requirements():
        requirements = ClassSubjectRequirement.query.all()
        return jsonify([{
            "id": req.id,
            "class_id": req.class_id,
            "subject_id": req.subject_id,
            "weekly_hours": req.weekly_hours
        } for req in requirements])

    # --- API для ИИ-помощника ---
    @app.route('/api/ai_command', methods=['POST'])
    def ai_command():
        data = request.get_json()
        command_text = data.get('command', '')
        if not command_text:
            return jsonify({"error": "Команда не указана"}), 400

        # 1. Вызвать ИИ-помощник (через заглушку)
        ai_result = handle_command_via_api(command_text)

        # 2. Проверить результат ИИ
        if ai_result.get("action") == "error":
            return jsonify(ai_result), 400

        # 3. Выполнить действие на основе результата ИИ
        action = ai_result.get("action")
        details = ai_result.get("details", {})

        if action == "find_replacement":
            # Пример: ИИ нашёл урок и оригинального учителя, нужно найти замену
            lesson_id = details.get("lesson_id")
            possible_replacements = details.get("possible_replacements", [])

            if not lesson_id:
                return jsonify({"action": "error", "details": {"error_message": "ID урока не указан для поиска замены."}}), 400

            # В случае заглушки, возможные замены уже в `possible_replacements`
            # В реальном приложении, эту логику нужно перенести в services.py
            # и вызывать её из app.py, передав ID урока и получая реальные данные из БД.
            # Для заглушки, просто возвращаем то, что сгенерировала заглушка
            return jsonify({
                "action": "found_replacements",
                "lesson_id": lesson_id,
                # original_teacher_name неизвестен в заглушке, можно получить из БД
                "possible_replacements": possible_replacements
            })

        elif action == "suggest_slot":
            # Пример: ИИ хочет предложить слот
            suggested_slots = details.get("slots", [])
            # Возвращаем предложенные слоты
            return jsonify({"action": "suggested_slots", "details": {"slots": suggested_slots}})

        elif action == "move_lesson":
            # Пример: ИИ хочет переместить урок
            lesson_id = details.get("lesson_id")
            new_day = details.get("day_of_week")
            new_slot = details.get("lesson_number")

            if not all(v is not None for v in [lesson_id, new_day, new_slot]):
                 return jsonify({"action": "error", "details": {"error_message": "Недостаточно данных для перемещения урока."}}), 400

            lesson_to_update = Lesson.query.get(lesson_id)
            if not lesson_to_update:
                return jsonify({"action": "error", "details": {"error_message": f"Урок с ID {lesson_id} не найден."}}), 404

            # Подготовим данные для обновления
            update_data = {
                'subject_id': lesson_to_update.subject_id,
                'teacher_id': lesson_to_update.teacher_id, # Пока не меняем
                'subgroup_id': lesson_to_update.subgroup_id,
                'day_of_week': new_day,
                'lesson_number': new_slot,
                'room_id': lesson_to_update.room_id, # Пока не меняем
            }

            # Проверим ограничения
            is_valid, errors = validate_lesson(update_data, existing_lesson_id=lesson_id)
            if not is_valid:
                return jsonify({"action": "error", "details": {"error_message": f"Невозможно переместить урок: {'; '.join(errors)}"}}), 400

            # Выполним обновление
            success, message = update_lesson(lesson_id, update_data)
            if success:
                return jsonify({"action": "lesson_moved", "details": {"message": message, "lesson_id": lesson_id}})
            else:
                return jsonify({"action": "error", "details": {"error_message": message}}), 500

        # ... другие действия ...

        else:
            # Неизвестное действие от ИИ
            return jsonify({"action": "error", "details": {"error_message": f"Неизвестное действие от ИИ: {action}"}}), 400


    # --- API для справочников (для JS) ---
    @app.route('/api/teachers', methods=['GET'])
    def get_teachers():
        teachers = Teacher.query.all()
        return jsonify([{"id": t.id, "name": t.name} for t in teachers])

    @app.route('/api/subjects', methods=['GET'])
    def get_subjects():
        subjects = Subject.query.all()
        return jsonify([{"id": s.id, "name": s.name} for s in subjects])

    # --- Обновлённый маршрут для получения классов (с фильтрацией по смене) ---
    @app.route('/api/classes', methods=['GET'])
    def get_classes():
        shift_filter = request.args.get('shift', type=int) # Получаем параметр shift из URL
        query = Class.query
        if shift_filter:
            query = query.join(Shift).filter(Shift.id == shift_filter)
        classes = query.all()
        return jsonify([{"id": c.id, "name": c.name, "shift_id": c.shift_id, "shift_name": c.shift.name if c.shift else "N/A"} for c in classes])

    @app.route('/api/subgroups', methods=['GET'])
    def get_subgroups():
        subgroups = SubGroup.query.all()
        return jsonify([{"id": sg.id, "name": sg.name, "class_id": sg.class_id} for sg in subgroups])

    @app.route('/api/rooms', methods=['GET'])
    def get_rooms():
        rooms = Room.query.all()
        return jsonify([{"id": r.id, "name": r.name} for r in rooms])


    # --- Обновлённый маршрут для получения уроков (с фильтрацией по смене класса) ---
    @app.route('/api/lessons', methods=['GET'])
    def get_lessons():
        shift_filter = request.args.get('shift', type=int) # Получаем параметр shift из URL
        # Начинаем с JOIN, чтобы получить доступ к смене класса через подгруппу
        query = db.session.query(Lesson).join(SubGroup).join(Class).join(Shift) # <-- Добавлен JOIN с Shift
        if shift_filter:
            # query = query.filter(Class.shift == shift_filter) # <-- СТАРОЕ
            query = query.filter(Shift.id == shift_filter) # <-- НОВОЕ: фильтр по ID смены через JOIN

        lessons = query.all()
        return jsonify([{
            "id": l.id,
            "subject_id": l.subject_id,
            "teacher_id": l.teacher_id,
            "subgroup_id": l.subgroup_id,
            "day_of_week": l.day_of_week,
            "lesson_number": l.lesson_number,
            "room_id": l.room_id
            # Возвращаем ID, чтобы JS мог их сопоставить с именами из справочников
        } for l in lessons])

    @app.route('/api/lessons', methods=['POST'])
    def create_lesson():
        data = request.get_json()
        success, message = add_lesson(data)
        if success:
            return jsonify({"message": message}), 201
        else:
            return jsonify({"error": message}), 400

    @app.route('/api/lessons/<int:lesson_id>', methods=['PUT'])
    def modify_lesson(lesson_id):
        data = request.get_json()
        success, message = update_lesson(lesson_id, data)
        if success:
            return jsonify({"message": message}), 200
        else:
            return jsonify({"error": message}), 400

    @app.route('/api/lessons/<int:lesson_id>', methods=['DELETE'])
    def delete_lesson(lesson_id):
        success, message = remove_lesson(lesson_id)
        if success:
            return jsonify({"message": message}), 200
        else:
            return jsonify({"error": message}), 400

    # ... (ваш существующий код до return app) ...

    # --- API для админ-панели (Учителя и Специализации) ---
    @app.route('/api/admin/teachers', methods=['GET'])
    def get_admin_teachers():
        teachers = Teacher.query.all()
        return jsonify([{"id": t.id, "name": t.name} for t in teachers])

    @app.route('/api/admin/teachers', methods=['POST'])
    def create_teacher():
        data = request.get_json()
        name = data.get('name')
        if not name:
            return jsonify({"error": "Имя учителя не указано"}), 400

        existing_teacher = Teacher.query.filter_by(name=name).first()
        if existing_teacher:
            return jsonify({"error": f"Учитель с именем '{name}' уже существует."}), 400

        new_teacher = Teacher(name=name)
        db.session.add(new_teacher)
        db.session.commit()
        return jsonify({"message": f"Учитель '{name}' успешно добавлен.", "id": new_teacher.id}), 201

    @app.route('/api/admin/teachers/<int:teacher_id>', methods=['DELETE'])
    def delete_teacher(teacher_id):
        teacher = Teacher.query.get_or_404(teacher_id)

        # Удаляем все специализации учителя перед удалением учителя
        TeacherSubject.query.filter_by(teacher_id=teacher_id).delete()

        db.session.delete(teacher)
        db.session.commit()
        return jsonify({"message": f"Учитель '{teacher.name}' и его специализации успешно удалены."})

    @app.route('/api/admin/teacher_subjects', methods=['GET'])
    def get_admin_teacher_subjects():
        teacher_subjects = TeacherSubject.query.all()
        return jsonify([{
            "id": ts.id,
            "teacher_id": ts.teacher_id,
            "subject_id": ts.subject_id
        } for ts in teacher_subjects])

    @app.route('/api/admin/teacher_subjects', methods=['POST'])
    def create_teacher_subject():
        data = request.get_json()
        teacher_id = data.get('teacher_id')
        subject_id = data.get('subject_id')

        if not teacher_id or not subject_id:
            return jsonify({"error": "ID учителя и ID предмета не указаны"}), 400

        # Проверим, существует ли учитель и предмет
        teacher = Teacher.query.get(teacher_id)
        subject = Subject.query.get(subject_id)
        if not teacher or not subject:
            return jsonify({"error": "Учитель или предмет не найдены."}), 404

        # Проверим, не существует ли уже такая специализация
        existing = TeacherSubject.query.filter_by(teacher_id=teacher_id, subject_id=subject_id).first()
        if existing:
            return jsonify({"error": f"Специализация учителя '{teacher.name}' по предмету '{subject.name}' уже существует."}), 400

        new_ts = TeacherSubject(teacher_id=teacher_id, subject_id=subject_id)
        db.session.add(new_ts)
        db.session.commit()
        return jsonify({"message": f"Специализация учителя '{teacher.name}' по предмету '{subject.name}' успешно добавлена.", "id": new_ts.id}), 201

    @app.route('/api/admin/teacher_subjects/<int:ts_id>', methods=['DELETE'])
    def delete_teacher_subject(ts_id):
        ts = TeacherSubject.query.get_or_404(ts_id)

        db.session.delete(ts)
        db.session.commit()
        # Найдем имена для сообщения
        teacher_name = Teacher.query.get(ts.teacher_id).name
        subject_name = Subject.query.get(ts.subject_id).name
        return jsonify({"message": f"Специализация учителя '{teacher_name}' по предмету '{subject_name}' успешно удалена."})


    # --- Маршрут для интерфейса расписания ---
    @app.route('/schedule') # Можно оставить как / или изменить на /schedule
    def schedule_interface(): # <-- Изменили имя функции на schedule_interface
        return render_template('schedule.html') # Основной интерфейс расписания

    # --- Маршрут для админ-панели ---
    @app.route('/admin')
    def admin_panel():
        return render_template('admin_panel.html') # Админ-панель

    # ... (остальные маршруты) ...

    return app

# ... (предыдущий код app.py до parse_and_load_data) ...

# --- НОВАЯ функция для парсинга и загрузки данных ---
def parse_and_load_data(filepath_hours, filepath_teachers):
    """
    Парсит два Excel-файла и загружает данные в БД.
    filepath_hours: путь к файлу с часами (Класс-Предмет)
    filepath_teachers: путь к файлу с нагрузкой (Учитель-Предмет-Класс-Кабинет)
    """
    import pandas as pd

    # --- ШАГ 1: Загрузка и обработка файла часов (Класс-Предмет) ---
    df_hours = pd.read_excel(filepath_hours, index_col=0) # Индекс - классы, столбцы - предметы

    # --- ШАГ 2: Загрузка и обработка файла нагрузки (Учитель-Предмет-Класс-Кабинет) ---
    df_teachers = pd.read_excel(filepath_teachers)

    # Загрузим учителей, классы, предметы, кабинеты, подгруппы, чтобы получить ID или создать новые
    teachers_dict = {t.name: t for t in Teacher.query.all()}
    classes_dict = {c.name: c for c in Class.query.all()}
    subjects_dict = {s.name: s for s in Subject.query.all()}
    rooms_dict = {r.name: r for r in Room.query.all()}
    subgroups_dict = {sg.name: sg for sg in SubGroup.query.all()} # Ключ: "5А-1", Значение: объект SubGroup
    # Загрузим смены
    shifts_dict = {s.id: s for s in Shift.query.all()} # Ключ: ID, Значение: объект Shift

    # --- ШАГ 3: Создание/Обновление классов, предметов, учителей, кабинетов ---
    # Классы
    for class_name in df_hours.index:
        if class_name not in classes_dict:
            # default_shift_id = 2 # Или получите из файла, если он там есть
            # default_shift_obj = Shift.query.get(default_shift_id)
            # if not default_shift_obj:
            #     print(f"Смена с ID {default_shift_id} не найдена. Создаём...")
            #     default_shift_obj = Shift(id=default_shift_id, name=f"{default_shift_id} смена")
            #     db.session.add(default_shift_obj)
            #     db.session.flush() # Получаем ID, если он был None
            # Пока что, если смена всегда 2, можно явно указать:
            # Для гибкости, можно добавить колонку 'Смена' в Excel файл.
            # Временно используем смену с ID 2, если она существует, иначе 1.
            default_shift_id = 2
            default_shift_obj = shifts_dict.get(default_shift_id)
            if not default_shift_obj:
                default_shift_id = 1
                default_shift_obj = shifts_dict.get(default_shift_id)
            # new_class = Class(name=class_name, shift=2) # <-- СТАРОЕ
            new_class = Class(name=class_name, shift_id=default_shift_obj.id) # <-- НОВОЕ: используем shift_id
            db.session.add(new_class)
            db.session.flush() # Получаем ID
            classes_dict[class_name] = new_class

    # Предметы
    for subject_name in df_hours.columns:
        if subject_name not in subjects_dict:
            new_subject = Subject(name=subject_name)
            db.session.add(new_subject)
            db.session.flush()
            subjects_dict[subject_name] = new_subject

    # Учителя из df_teachers
    for _, row in df_teachers.iterrows():
        teacher_name = row['Учитель']
        if teacher_name not in teachers_dict:
            new_teacher = Teacher(name=teacher_name)
            db.session.add(new_teacher)
            db.session.flush()
            teachers_dict[teacher_name] = new_teacher

    # Кабинеты из df_teachers
    for _, row in df_teachers.iterrows():
        room_name = row['Кабинет']
        if room_name not in rooms_dict:
            new_room = Room(name=room_name)
            db.session.add(new_room)
            db.session.flush()
            rooms_dict[room_name] = new_room

    # --- АНАЛИЗ ФАЙЛА НАГРУЗКИ ДЛЯ ОПРЕДЕЛЕНИЯ ПОДГРУПП И ЧАСОВ ---
    # Группируем df_teachers по Классу и Предмету, чтобы посчитать уникальных учителей
    grouped_by_class_subject = df_teachers.groupby(['Класс', 'Предмет']).agg({
        'Учитель': 'nunique', # Количество уникальных учителей
        'Кабинет': 'nunique'  # Количество уникальных кабинетов (доп. индикатор)
    }).reset_index()

    # Словарь для хранения информации о подгруппах: {class_name: {subject_name: [subgroup_names]}}
    subgroups_for_class_subject = {}
    # Словарь для хранения часов из ClassSubjectRequirement: {class_name: {subject_name: total_hours}}
    hours_from_requirements = {}

    # Заполняем hours_from_requirements
    for class_name in df_hours.index:
        class_obj = classes_dict[class_name]
        hours_from_requirements[class_name] = {}
        for subject_name in df_hours.columns:
            hours_per_week = df_hours.loc[class_name, subject_name]
            if pd.isna(hours_per_week) or hours_per_week == 0:
                continue
            subject_obj = subjects_dict[subject_name]
            hours_from_requirements[class_name][subject_name] = int(hours_per_week)

    for _, row in grouped_by_class_subject.iterrows():
        class_name = row['Класс']
        subject_name = row['Предмет']
        num_unique_teachers = row['Учитель']
        # num_unique_rooms = row['Кабинет'] # Пока не используем, но может пригодиться

        # Определяем, нужны ли подгруппы
        needs_subgroups = num_unique_teachers > 1

        if needs_subgroups:
            # Нужно создать num_unique_teachers подгрупп
            # Найдем соответствующие строки в df_teachers для этого класса и предмета
            class_subject_rows = df_teachers[
                (df_teachers['Класс'] == class_name) & (df_teachers['Предмет'] == subject_name)
            ]
            num_subgroups_needed = len(class_subject_rows) # Должно совпадать с num_unique_teachers
            subgroup_names = [f"{class_name}-{i+1}" for i in range(num_subgroups_needed)]

            # Сохраняем имена подгрупп
            if class_name not in subgroups_for_class_subject:
                subgroups_for_class_subject[class_name] = {}
            subgroups_for_class_subject[class_name][subject_name] = subgroup_names
        else:
            # Подгруппы не нужны. Создадим или используем одну подгруппу "класс-1".
            # Или можно использовать сам класс, но в нашей системе урок привязан к подгруппе.
            # Для единообразия, всегда будем создавать хотя бы одну подгруппу.
            # Имя подгруппы для "всего класса" может быть, например, "{class_name}-0" или "{class_name}-1".
            # Выберем "{class_name}-1" для простоты.
            subgroup_name = f"{class_name}-1"
            if class_name not in subgroups_for_class_subject:
                subgroups_for_class_subject[class_name] = {}
            subgroups_for_class_subject[class_name][subject_name] = [subgroup_name]


    # --- ШАГ 4: Создание подгрупп на основе анализа ---
    # Теперь, когда у нас есть subgroups_for_class_subject, создадим подгруппы
    for class_name, subjects_data in subgroups_for_class_subject.items():
        class_obj = classes_dict[class_name]
        for subject_name, subgroup_names_list in subjects_data.items():
            for sg_name in subgroup_names_list:
                if sg_name not in subgroups_dict:
                    new_sg = SubGroup(name=sg_name, class_id=class_obj.id)
                    db.session.add(new_sg)
                    db.session.flush()
                    subgroups_dict[sg_name] = new_sg # Добавляем в словарь

    # --- ШАГ 5: Обработка часов из df_hours (ClassSubjectRequirement) ---
    for class_name in df_hours.index:
        class_obj = classes_dict[class_name]
        for subject_name in df_hours.columns:
            hours_per_week = df_hours.loc[class_name, subject_name]
            if pd.isna(hours_per_week) or hours_per_week == 0:
                continue

            subject_obj = subjects_dict[subject_name]

            existing_req = ClassSubjectRequirement.query.filter_by(
                class_id=class_obj.id, subject_id=subject_obj.id
            ).first()

            if existing_req:
                existing_req.weekly_hours = int(hours_per_week)
            else:
                new_req = ClassSubjectRequirement(
                    class_id=class_obj.id,
                    subject_id=subject_obj.id,
                    weekly_hours=int(hours_per_week)
                )
                db.session.add(new_req)

    # --- ШАГ 6: Обработка нагрузки из df_teachers (TeacherSubject, TeacherSubjectRequirement) ---
    # Сгруппируем df_teachers, чтобы суммировать часы учителя для (учитель, предмет, класс)
    # ВАЖНО: Теперь используем часы из ClassSubjectRequirement для каждой подгруппы
    grouped_teachers = df_teachers.groupby(['Учитель', 'Предмет', 'Класс']).agg({'Количество_часов_в_неделю': 'sum'}).reset_index()

    for _, row in grouped_teachers.iterrows():
        teacher_name = row['Учитель']
        subject_name = row['Предмет']
        class_name = row['Класс']
        # teacher_total_hours_from_file = int(row['Количество_часов_в_неделю']) # БОЛЬШЕ НЕ ИСПОЛЬЗУЕМ

        teacher_obj = teachers_dict[teacher_name]
        subject_obj = subjects_dict[subject_name]
        class_obj = classes_dict[class_name]

        # --- ОПРЕДЕЛЕНИЕ ПОДГРУППЫ ---
        # Найдем возможные подгруппы для этого (класс, предмет)
        possible_subgroup_names = subgroups_for_class_subject.get(class_name, {}).get(subject_name, [])
        # Найдем строку в df_teachers для определения, какой должна быть подгруппа
        teacher_class_subject_rows = df_teachers[
            (df_teachers['Учитель'] == teacher_name) &
            (df_teachers['Предмет'] == subject_name) &
            (df_teachers['Класс'] == class_name)
        ]

        if len(teacher_class_subject_rows) == 0:
             print(f"Предупреждение: Нет строки в df_teachers для ({teacher_name}, {subject_name}, {class_name})")
             continue

        # Получаем часы из ClassSubjectRequirement для этого (класс, предмет)
        class_subject_hours = hours_from_requirements.get(class_name, {}).get(subject_name, 0)

        # Если для (class, subject) несколько учителей, подгруппы определяются по порядку или уникальному значению (например, кабинету)
        # Используем индекс строки в отфильтрованном фрейме как индекс подгруппы
        for _, specific_row in teacher_class_subject_rows.iterrows():
             # Найдем индекс текущей строки среди всех строк для этого класса и предмета
             relevant_rows_indices = df_teachers[
                 (df_teachers['Класс'] == class_name) & (df_teachers['Предмет'] == subject_name)
             ].index.tolist()
             # Индекс в отфильтрованном фрейме (0, 1, 2...)
             # Индекс в основном фрейме (его индекс в relevant_rows_indices)
             current_row_index_in_main_df = specific_row.name
             subgroup_index_in_list = relevant_rows_indices.index(current_row_index_in_main_df)
             # Выберем имя подгруппы по индексу
             if subgroup_index_in_list < len(possible_subgroup_names):
                 assigned_subgroup_name = possible_subgroup_names[subgroup_index_in_list]
                 assigned_subgroup_obj = subgroups_dict[assigned_subgroup_name]
             else:
                 print(f"Ошибка: Не удалось сопоставить подгруппу для ({teacher_name}, {subject_name}, {class_name})")
                 continue # Пропускаем, если не получилось сопоставить


             # --- Создание TeacherSubject (специализация) ---
             existing_ts = TeacherSubject.query.filter_by(
                 teacher_id=teacher_obj.id, subject_id=subject_obj.id
             ).first()
             if not existing_ts:
                 new_ts = TeacherSubject(teacher_id=teacher_obj.id, subject_id=subject_obj.id)
                 db.session.add(new_ts)

             # --- Создание TeacherSubjectRequirement ---
             # ИСПОЛЬЗУЕМ class_subject_hours вместо teacher_total_hours_from_file
             existing_tsr = TeacherSubjectRequirement.query.filter_by(
                 teacher_id=teacher_obj.id, subject_id=subject_obj.id, class_id=class_obj.id, subgroup_id=assigned_subgroup_obj.id # Добавляем привязку к подгруппе
             ).first()

             if existing_tsr:
                 existing_tsr.teacher_weekly_hours = class_subject_hours # НОВОЕ: часы из ClassSubjectRequirement
             else:
                 new_tsr = TeacherSubjectRequirement(
                     teacher_id=teacher_obj.id,
                     subject_id=subject_obj.id,
                     class_id=class_obj.id,
                     subgroup_id=assigned_subgroup_obj.id, # Привязываем к конкретной подгруппе
                     teacher_weekly_hours=class_subject_hours # НОВОЕ: часы из ClassSubjectRequirement
                 )
                 db.session.add(new_tsr)

    db.session.commit() # Зафиксируем все изменения

    return "Данные успешно загружены из файлов часов и нагрузки."

# ... (остальной код app.py) ...

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)