"""
Управление кабинетами и учителями
"""
from flask import Blueprint, render_template, request, jsonify
from app.core.db_manager import db, school_db_context
from app.models.school import Teacher, Cabinet, CabinetTeacher, Subject
from app.core.auth import admin_required, get_current_school_id, current_user
from sqlalchemy import distinct

cabinets_bp = Blueprint('cabinets', __name__)


@cabinets_bp.route('/admin/cabinets')
@admin_required
def cabinets_page():
    """Страница управления кабинетами и учителями"""
    school_id = get_current_school_id()
    if not school_id:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        # Убеждаемся, что таблицы существуют и выполняем миграции
        try:
            from sqlalchemy import inspect
            from flask import current_app
            from app.core.db_manager import migrate_school_database
            engine = db.get_engine(current_app, bind='school')
            
            # Выполняем миграции (добавит subject_id, если его нет)
            migrate_school_database(school_id, engine)
            
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            if 'cabinets' not in tables:
                Cabinet.__table__.create(engine, checkfirst=True)
            if 'cabinet_teachers' not in tables:
                CabinetTeacher.__table__.create(engine, checkfirst=True)
        except Exception as e:
            print(f"Предупреждение при проверке таблиц кабинетов: {e}")
        
        # Получаем все кабинеты из таблицы Cabinet
        cabinets = db.session.query(Cabinet).order_by(Cabinet.name).all()
        
        # Также собираем кабинеты из других источников для синхронизации
        all_cabinets_from_schedule = set()
        
        # Из постоянного расписания
        from app.models.school import PermanentSchedule
        permanent_cabinets = db.session.query(distinct(PermanentSchedule.cabinet)).filter(
            PermanentSchedule.cabinet.isnot(None),
            PermanentSchedule.cabinet != ''
        ).all()
        for row in permanent_cabinets:
            if row[0]:
                all_cabinets_from_schedule.add(row[0])
        
        # Из временного расписания
        from app.models.school import TemporarySchedule
        temporary_cabinets = db.session.query(distinct(TemporarySchedule.cabinet)).filter(
            TemporarySchedule.cabinet.isnot(None),
            TemporarySchedule.cabinet != ''
        ).all()
        for row in temporary_cabinets:
            if row[0]:
                all_cabinets_from_schedule.add(row[0])
        
        # Из назначений учителей (default_cabinet)
        from app.models.school import TeacherAssignment
        assignment_cabinets = db.session.query(distinct(TeacherAssignment.default_cabinet)).filter(
            TeacherAssignment.default_cabinet.isnot(None),
            TeacherAssignment.default_cabinet != ''
        ).all()
        for row in assignment_cabinets:
            if row[0]:
                all_cabinets_from_schedule.add(row[0])
        
        # Добавляем кабинеты из расписания, которых нет в таблице Cabinet
        existing_cabinet_names = {c.name for c in cabinets}
        for cab_name in all_cabinets_from_schedule:
            if cab_name not in existing_cabinet_names:
                new_cabinet = Cabinet(name=cab_name)
                db.session.add(new_cabinet)
        
        if all_cabinets_from_schedule:
            db.session.commit()
            # Перезагружаем список
            cabinets = db.session.query(Cabinet).order_by(Cabinet.name).all()
        
        # Получаем всех учителей
        teachers = db.session.query(Teacher).order_by(Teacher.full_name).all()
        
        # Получаем все предметы
        subjects = db.session.query(Subject).order_by(Subject.name).all()
        
        # Группируем кабинеты по предметам
        subjects_with_cabinets = []
        cabinets_without_subject = []
        
        for subject in subjects:
            # Получаем кабинеты для этого предмета
            subject_cabinets = db.session.query(Cabinet).filter_by(
                subject_id=subject.id
            ).order_by(Cabinet.name).all()
            
            cabinets_data = []
            for cabinet in subject_cabinets:
                # Получаем учителей для этого кабинета
                cabinet_teachers = db.session.query(CabinetTeacher).filter_by(
                    cabinet_id=cabinet.id
                ).all()
                
                teachers_list = [ct.teacher for ct in cabinet_teachers]
                
                cabinets_data.append({
                    'cabinet_id': cabinet.id,
                    'cabinet_name': cabinet.name,
                    'teachers': teachers_list,
                    'subgroups_only': cabinet.subgroups_only,
                    'exclusive_to_subject': cabinet.exclusive_to_subject
                })
            
            if cabinets_data:
                subjects_with_cabinets.append({
                    'subject_id': subject.id,
                    'subject_name': subject.name,
                    'cabinets': cabinets_data
                })
        
        # Кабинеты без предмета (для обратной совместимости)
        cabinets_no_subject = db.session.query(Cabinet).filter_by(
            subject_id=None
        ).order_by(Cabinet.name).all()
        
        for cabinet in cabinets_no_subject:
            cabinet_teachers = db.session.query(CabinetTeacher).filter_by(
                cabinet_id=cabinet.id
            ).all()
            
            teachers_list = [ct.teacher for ct in cabinet_teachers]
            
            cabinets_without_subject.append({
                'cabinet_id': cabinet.id,
                'cabinet_name': cabinet.name,
                'teachers': teachers_list,
                'subgroups_only': cabinet.subgroups_only,
                'exclusive_to_subject': cabinet.exclusive_to_subject,
                'max_classes_simultaneously': cabinet.max_classes_simultaneously or 1
            })
        
        return render_template('admin/cabinets.html', 
                             subjects_with_cabinets=subjects_with_cabinets,
                             cabinets_without_subject=cabinets_without_subject,
                             all_teachers=teachers,
                             all_subjects=subjects,
                             current_user=current_user)


@cabinets_bp.route('/admin/cabinets/add', methods=['POST'])
@admin_required
def add_cabinet():
    """Добавить новый кабинет"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_name = data.get('cabinet_name', '').strip()
    subject_id = data.get('subject_id')
    subgroups_only = data.get('subgroups_only', False)
    exclusive_to_subject = data.get('exclusive_to_subject', False)
    max_classes_simultaneously = data.get('max_classes_simultaneously', 1)
    
    if not cabinet_name:
        return jsonify({'success': False, 'error': 'Не указан кабинет'}), 400
    
    if not subject_id:
        return jsonify({'success': False, 'error': 'Не указан предмет'}), 400
    
    with school_db_context(school_id):
        # Проверяем, существует ли предмет
        subject = db.session.query(Subject).filter_by(id=subject_id).first()
        if not subject:
            return jsonify({'success': False, 'error': 'Предмет не найден'}), 404
        
        # Проверяем, существует ли уже такой кабинет для этого предмета
        existing = db.session.query(Cabinet).filter_by(
            name=cabinet_name,
            subject_id=subject_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Этот кабинет уже существует для данного предмета'}), 400
        
        # Валидация max_classes_simultaneously
        try:
            max_classes = int(max_classes_simultaneously)
            if max_classes < 1:
                max_classes = 1
            elif max_classes > 10:  # Ограничение на разумное количество
                max_classes = 10
        except (ValueError, TypeError):
            max_classes = 1
        
        # Создаем новый кабинет
        new_cabinet = Cabinet(
            name=cabinet_name, 
            subject_id=subject_id,
            subgroups_only=bool(subgroups_only),
            exclusive_to_subject=bool(exclusive_to_subject),
            max_classes_simultaneously=max_classes
        )
        db.session.add(new_cabinet)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Кабинет "{cabinet_name}" создан для предмета "{subject.name}". Добавьте учителей.',
            'cabinet_id': new_cabinet.id,
            'cabinet_name': cabinet_name,
            'subject_id': subject_id,
            'subject_name': subject.name,
            'subgroups_only': new_cabinet.subgroups_only,
            'exclusive_to_subject': new_cabinet.exclusive_to_subject
        })


@cabinets_bp.route('/admin/cabinets/add-teacher', methods=['POST'])
@admin_required
def add_teacher_to_cabinet():
    """Добавить учителя к кабинету"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    teacher_id = data.get('teacher_id')
    
    if not cabinet_id or not teacher_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет или учитель'}), 400
    
    with school_db_context(school_id):
        cabinet = db.session.query(Cabinet).filter_by(id=cabinet_id).first()
        if not cabinet:
            return jsonify({'success': False, 'error': 'Кабинет не найден'}), 404
        
        teacher = db.session.query(Teacher).filter_by(id=teacher_id).first()
        if not teacher:
            return jsonify({'success': False, 'error': 'Учитель не найден'}), 404
        
        existing = db.session.query(CabinetTeacher).filter_by(
            cabinet_id=cabinet_id,
            teacher_id=teacher_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Этот учитель уже добавлен к кабинету'}), 400
        
        cabinet_teacher = CabinetTeacher(
            cabinet_id=cabinet_id,
            teacher_id=teacher_id
        )
        db.session.add(cabinet_teacher)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Учитель "{teacher.full_name}" добавлен к кабинету "{cabinet.name}"',
            'teacher': {
                'id': teacher.id,
                'name': teacher.full_name
            }
        })


@cabinets_bp.route('/admin/cabinets/remove-teacher', methods=['POST'])
@admin_required
def remove_teacher_from_cabinet():
    """Удалить учителя из кабинета"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    teacher_id = data.get('teacher_id')
    
    if not cabinet_id or not teacher_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет или учитель'}), 400
    
    with school_db_context(school_id):
        cabinet_teacher = db.session.query(CabinetTeacher).filter_by(
            cabinet_id=cabinet_id,
            teacher_id=teacher_id
        ).first()
        
        if not cabinet_teacher:
            return jsonify({'success': False, 'error': 'Связь не найдена'}), 404
        
        teacher_name = cabinet_teacher.teacher.full_name
        cabinet_name = cabinet_teacher.cabinet.name
        db.session.delete(cabinet_teacher)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Учитель "{teacher_name}" удален из кабинета "{cabinet_name}"'
        })


@cabinets_bp.route('/admin/cabinets/delete', methods=['POST'])
@admin_required
def delete_cabinet():
    """Удалить кабинет"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    
    if not cabinet_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет'}), 400
    
    with school_db_context(school_id):
        cabinet = db.session.query(Cabinet).filter_by(id=cabinet_id).first()
        
        if not cabinet:
            return jsonify({'success': False, 'error': 'Кабинет не найден'}), 404
        
        cabinet_name = cabinet.name
        
        # Проверяем, используется ли кабинет в расписании
        from app.models.school import PermanentSchedule, TemporarySchedule, TeacherAssignment
        
        # Проверяем постоянное расписание
        permanent_usage = db.session.query(PermanentSchedule).filter_by(
            cabinet=cabinet_name
        ).first()
        
        # Проверяем временное расписание
        temporary_usage = db.session.query(TemporarySchedule).filter_by(
            cabinet=cabinet_name
        ).first()
        
        # Проверяем назначения учителей
        assignment_usage = db.session.query(TeacherAssignment).filter_by(
            default_cabinet=cabinet_name
        ).first()
        
        if permanent_usage or temporary_usage or assignment_usage:
            return jsonify({
                'success': False,
                'error': f'Кабинет "{cabinet_name}" используется в расписании. Сначала удалите все связанные записи.'
            }), 400
        
        # Удаляем кабинет (связи с учителями удалятся автоматически благодаря cascade)
        db.session.delete(cabinet)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Кабинет "{cabinet_name}" успешно удален'
        })


@cabinets_bp.route('/admin/cabinets/update-subgroups-only', methods=['POST'])
@admin_required
def update_subgroups_only():
    """Обновить флаг subgroups_only для кабинета"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    subgroups_only = data.get('subgroups_only', False)
    
    if not cabinet_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет'}), 400
    
    with school_db_context(school_id):
        cabinet = db.session.query(Cabinet).filter_by(id=cabinet_id).first()
        
        if not cabinet:
            return jsonify({'success': False, 'error': 'Кабинет не найден'}), 404
        
        cabinet.subgroups_only = bool(subgroups_only)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Настройка кабинета "{cabinet.name}" обновлена',
            'subgroups_only': cabinet.subgroups_only
        })


@cabinets_bp.route('/admin/cabinets/update-max-classes', methods=['POST'])
@admin_required
def update_max_classes_simultaneously():
    """Обновить максимальное количество классов одновременно в кабинете"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    max_classes = data.get('max_classes_simultaneously')
    
    if not cabinet_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет'}), 400
    
    # Валидация
    try:
        max_classes = int(max_classes)
        if max_classes < 1:
            max_classes = 1
        elif max_classes > 10:  # Ограничение на разумное количество
            max_classes = 10
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Неверное значение количества классов'}), 400
    
    with school_db_context(school_id):
        cabinet = db.session.query(Cabinet).filter_by(id=cabinet_id).first()
        
        if not cabinet:
            return jsonify({'success': False, 'error': 'Кабинет не найден'}), 404
        
        cabinet.max_classes_simultaneously = max_classes
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Максимальное количество классов для кабинета "{cabinet.name}" обновлено',
            'max_classes_simultaneously': cabinet.max_classes_simultaneously
        })


@cabinets_bp.route('/admin/cabinets/update-exclusive-to-subject', methods=['POST'])
@admin_required
def update_exclusive_to_subject():
    """Обновить флаг exclusive_to_subject для кабинета"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    cabinet_id = data.get('cabinet_id')
    exclusive_to_subject = data.get('exclusive_to_subject', False)
    
    if not cabinet_id:
        return jsonify({'success': False, 'error': 'Не указан кабинет'}), 400
    
    with school_db_context(school_id):
        cabinet = db.session.query(Cabinet).filter_by(id=cabinet_id).first()
        
        if not cabinet:
            return jsonify({'success': False, 'error': 'Кабинет не найден'}), 404
        
        cabinet.exclusive_to_subject = bool(exclusive_to_subject)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Настройка кабинета "{cabinet.name}" обновлена',
            'exclusive_to_subject': cabinet.exclusive_to_subject
        })


@cabinets_bp.route('/admin/cabinets/delete-all', methods=['POST'])
@admin_required
def delete_all_cabinets():
    """Удалить все кабинеты"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    force = data.get('force', False) if data else False
    
    with school_db_context(school_id):
        # Получаем все кабинеты
        all_cabinets = db.session.query(Cabinet).all()
        
        if not all_cabinets:
            return jsonify({
                'success': True,
                'message': 'Нет кабинетов для удаления',
                'deleted_count': 0
            })
        
        # Проверяем использование кабинетов в расписании
        from app.models.school import PermanentSchedule, TemporarySchedule, TeacherAssignment
        
        used_cabinets = set()
        errors = []
        
        for cabinet in all_cabinets:
            cabinet_name = cabinet.name
            
            # Проверяем постоянное расписание
            permanent_usage = db.session.query(PermanentSchedule).filter_by(
                cabinet=cabinet_name
            ).first()
            
            # Проверяем временное расписание
            temporary_usage = db.session.query(TemporarySchedule).filter_by(
                cabinet=cabinet_name
            ).first()
            
            # Проверяем назначения учителей
            assignment_usage = db.session.query(TeacherAssignment).filter_by(
                default_cabinet=cabinet_name
            ).first()
            
            if permanent_usage or temporary_usage or assignment_usage:
                used_cabinets.add(cabinet_name)
                if not force:
                    errors.append(f'Кабинет "{cabinet_name}" используется в расписании')
        
        # Если есть используемые кабинеты и не принудительное удаление
        if used_cabinets and not force:
            return jsonify({
                'success': False,
                'error': f'Невозможно удалить кабинеты: {len(used_cabinets)} кабинетов используются в расписании',
                'used_cabinets': list(used_cabinets),
                'errors': errors[:10]  # Первые 10 ошибок
            }), 400
        
        # Удаляем все кабинеты
        deleted_count = 0
        deleted_names = []
        
        for cabinet in all_cabinets:
            # Если принудительное удаление, пропускаем проверку
            # Иначе проверяем еще раз (на случай, если что-то изменилось)
            if not force:
                cabinet_name = cabinet.name
                permanent_usage = db.session.query(PermanentSchedule).filter_by(
                    cabinet=cabinet_name
                ).first()
                temporary_usage = db.session.query(TemporarySchedule).filter_by(
                    cabinet=cabinet_name
                ).first()
                assignment_usage = db.session.query(TeacherAssignment).filter_by(
                    default_cabinet=cabinet_name
                ).first()
                
                if permanent_usage or temporary_usage or assignment_usage:
                    continue  # Пропускаем используемые кабинеты
            
            deleted_names.append(cabinet.name)
            db.session.delete(cabinet)
            deleted_count += 1
        
        db.session.commit()
        
        if deleted_count == 0:
            return jsonify({
                'success': False,
                'error': 'Не удалось удалить кабинеты: все они используются в расписании'
            }), 400
        
        message = f'Успешно удалено кабинетов: {deleted_count}'
        if len(used_cabinets) > 0 and force:
            message += f' (пропущено используемых: {len(used_cabinets)})'
        
        return jsonify({
            'success': True,
            'message': message,
            'deleted_count': deleted_count,
            'deleted_cabinets': deleted_names,
            'skipped_count': len(used_cabinets) if used_cabinets else 0
        })