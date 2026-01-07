"""
CRUD операции для учителей
"""
from flask import Blueprint, render_template, request, jsonify
from app.core.db_manager import db, school_db_context
from app.models.school import Teacher, TeacherAssignment, PermanentSchedule, TemporarySchedule, ClassGroup, ShiftClass
from app.core.auth import admin_required, get_current_school_id
from app.routes.utils import get_sorted_classes

teachers_bp = Blueprint('teachers', __name__)


@teachers_bp.route('/admin/teachers')
@admin_required
def teachers_list():
    """Список учителей"""
    school_id = get_current_school_id()
    if not school_id:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        teachers = db.session.query(Teacher).order_by(Teacher.full_name).all()
        classes = get_sorted_classes()
        # Загружаем связи учителей с классами
        for teacher in teachers:
            # Получаем классы учителя через промежуточную таблицу
            from app.models.school import _get_teacher_classes_table
            teacher_classes_table = _get_teacher_classes_table()
            class_ids = db.session.query(teacher_classes_table.c.class_id).filter(
                teacher_classes_table.c.teacher_id == teacher.id
            ).all()
            teacher.classes_list = [row[0] for row in class_ids]
        return render_template('admin/teachers.html', teachers=teachers, classes=classes)


@teachers_bp.route('/admin/teachers/create', methods=['POST'])
@admin_required
def create_teacher():
    """Создать учителя"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    full_name = data.get('full_name', '').strip()
    phone = data.get('phone')
    phone = phone.strip() if phone else None
    telegram_id = data.get('telegram_id')
    telegram_id = telegram_id.strip() if telegram_id else None

    if not full_name:
        return jsonify({'success': False, 'error': 'Полное имя обязательно'}), 400

    try:
        with school_db_context(school_id):
            existing = db.session.query(Teacher).filter_by(full_name=full_name).first()
            if existing:
                return jsonify({'success': False, 'error': 'Учитель с таким именем уже существует'}), 400

            name_parts = full_name.split()
            if len(name_parts) >= 2:
                short_name = ".".join([n[0] + "." for n in name_parts[:2]])
            else:
                short_name = full_name[:30]

            teacher = Teacher(
                full_name=full_name,
                short_name=short_name,
                phone=phone,
                telegram_id=telegram_id
            )
            db.session.add(teacher)
            db.session.commit()

            return jsonify({'success': True, 'teacher_id': teacher.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@teachers_bp.route('/admin/teachers/update/<int:teacher_id>', methods=['POST'])
@admin_required
def update_teacher(teacher_id):
    """Обновить учителя"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    full_name = data.get('full_name', '').strip()
    phone = data.get('phone')
    phone = phone.strip() if phone else None

    if not full_name:
        return jsonify({'success': False, 'error': 'Полное имя обязательно'}), 400

    try:
        with school_db_context(school_id):
            teacher = db.session.query(Teacher).filter_by(id=teacher_id).first_or_404()
            
            existing = db.session.query(Teacher).filter_by(full_name=full_name).first()
            if existing and existing.id != teacher_id:
                return jsonify({'success': False, 'error': 'Учитель с таким именем уже существует'}), 400

            teacher.full_name = full_name
            teacher.phone = phone
            telegram_id = data.get('telegram_id')
            teacher.telegram_id = telegram_id.strip() if telegram_id else None
            
            name_parts = full_name.split()
            if len(name_parts) >= 2:
                teacher.short_name = ".".join([n[0] + "." for n in name_parts[:2]])
            else:
                teacher.short_name = full_name[:30]
            
            db.session.commit()
            return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@teachers_bp.route('/admin/teachers/delete/<int:teacher_id>', methods=['POST'])
@admin_required
def delete_teacher(teacher_id):
    """Удалить учителя"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    try:
        with school_db_context(school_id):
            teacher = db.session.query(Teacher).filter_by(id=teacher_id).first_or_404()
            
            # Удаляем связи с классами (автоматически через CASCADE, но лучше явно)
            from app.models.school import _get_teacher_classes_table
            teacher_classes = _get_teacher_classes_table()
            db.session.execute(teacher_classes.delete().where(teacher_classes.c.teacher_id == teacher_id))
            
            db.session.query(TeacherAssignment).filter_by(teacher_id=teacher_id).delete()
            db.session.query(PermanentSchedule).filter_by(teacher_id=teacher_id).delete()
            db.session.query(TemporarySchedule).filter_by(teacher_id=teacher_id).delete()
            
            db.session.delete(teacher)
            db.session.commit()
            
            return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@teachers_bp.route('/admin/teachers/<int:teacher_id>/classes', methods=['GET', 'POST'])
@admin_required
def manage_teacher_classes(teacher_id):
    """Управление классами учителя
    
    Если передан subject_id и shift_id, работает с TeacherAssignment для конкретного предмета.
    Иначе работает с общей таблицей teacher_classes.
    """
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    with school_db_context(school_id):
        teacher = db.session.query(Teacher).filter_by(id=teacher_id).first_or_404()
        
        # Проверяем, передан ли subject_id и shift_id (для работы с конкретным предметом)
        subject_id = request.args.get('subject_id', type=int) if request.method == 'GET' else request.get_json().get('subject_id')
        shift_id = request.args.get('shift_id', type=int) if request.method == 'GET' else request.get_json().get('shift_id')
        
        # Логирование для отладки
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[manage_teacher_classes] teacher_id={teacher_id}, subject_id={subject_id}, shift_id={shift_id}, method={request.method}")
        
        if request.method == 'GET':
            # Получить список классов учителя
            # Проверяем, что subject_id и shift_id не None и не 0
            logger.info(f"[manage_teacher_classes] Параметры: subject_id={subject_id} (type={type(subject_id)}), shift_id={shift_id} (type={type(shift_id)})")
            if subject_id is not None and shift_id is not None and subject_id != 0 and shift_id != 0:
                logger.info(f"[manage_teacher_classes] Работаем с TeacherAssignment для конкретного предмета")
                # Работаем с TeacherAssignment для конкретного предмета
                # Сначала пытаемся получить для активной смены
                teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                    teacher_id=teacher_id,
                    subject_id=subject_id,
                    shift_id=shift_id
                ).all()
                logger.info(f"[manage_teacher_classes] Найдено TeacherAssignment для teacher_id={teacher_id}, subject_id={subject_id}, shift_id={shift_id}: {len(teacher_assignments)}")
                if teacher_assignments:
                    for ta in teacher_assignments:
                        logger.info(f"[manage_teacher_classes] TeacherAssignment: class_id={ta.class_id}, hours_per_week={ta.hours_per_week} (type={type(ta.hours_per_week)})")
                
                # Если нет назначений для активной смены, получаем для любой смены
                if not teacher_assignments:
                    teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                        teacher_id=teacher_id,
                        subject_id=subject_id
                    ).all()
                    logger.info(f"[manage_teacher_classes] Всего TeacherAssignment для teacher_id={teacher_id}, subject_id={subject_id}: {len(teacher_assignments)}")
                    if teacher_assignments:
                        shift_ids_found = list(set([ta.shift_id for ta in teacher_assignments if hasattr(ta, 'shift_id') and ta.shift_id]))
                        logger.info(f"[manage_teacher_classes] Найдены записи для других смен: shift_ids={shift_ids_found}")

                # Если у учителя только одно назначение с hours_per_week = 0,
                # считаем, что классы еще не назначены (это "пустая" запись при добавлении учителя)
                # В этом случае не показываем классы и не ставим галочки
                if len(teacher_assignments) == 1:
                    first_assignment = teacher_assignments[0]
                    hours = getattr(first_assignment, "hours_per_week", None)
                    # Преобразуем в int для надежности
                    try:
                        hours_int = int(hours) if hours is not None else None
                    except (ValueError, TypeError):
                        hours_int = None
                    
                    if hours_int == 0:
                        logger.info(f"[manage_teacher_classes] Обнаружена только одна временная запись с 0 часами (class_id={first_assignment.class_id}, hours={hours}, hours_int={hours_int}) — считаем, что классы не назначены")
                        teacher_assignments = []
                        teacher_classes = []  # Явно устанавливаем пустой список
                        logger.info(f"[manage_teacher_classes] teacher_classes установлен в пустой список: {teacher_classes}, type: {type(teacher_classes)}, len: {len(teacher_classes) if teacher_classes else 0}")
                    else:
                        # Если hours != 0, обрабатываем нормально
                        class_ids_list = [ta.class_id for ta in teacher_assignments if ta.class_id]
                        logger.info(f"[manage_teacher_classes] class_ids_list: {class_ids_list}")
                        classes = db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids_list)).all() if class_ids_list else []
                        teacher_classes = [{'id': c.id, 'name': c.name} for c in classes]
                        logger.info(f"[manage_teacher_classes] teacher_classes: {teacher_classes}")
                else:
                    # Если назначений больше одного или нет вообще, обрабатываем нормально
                    class_ids_list = [ta.class_id for ta in teacher_assignments if ta.class_id]
                    logger.info(f"[manage_teacher_classes] class_ids_list: {class_ids_list}")
                    classes = db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids_list)).all() if class_ids_list else []
                    teacher_classes = [{'id': c.id, 'name': c.name} for c in classes]
                    logger.info(f"[manage_teacher_classes] teacher_classes: {teacher_classes}")
            else:
                # Работаем с общей таблицей teacher_classes
                from app.models.school import _get_teacher_classes_table
                teacher_classes_table = _get_teacher_classes_table()
                class_ids = db.session.query(teacher_classes_table.c.class_id).filter(
                    teacher_classes_table.c.teacher_id == teacher_id
                ).all()
                class_ids_list = [row[0] for row in class_ids]
                classes = db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids_list)).all()
                teacher_classes = [{'id': c.id, 'name': c.name} for c in classes]
            
            # Получаем все классы для предмета из ClassLoad (общая нагрузка, shift_id = None)
            if subject_id:
                # Получаем классы, для которых есть ClassLoad для этого предмета
                class_loads = db.session.query(ClassLoad).filter_by(
                    subject_id=subject_id,
                    shift_id=None
                ).all()
                
                # Если нет ClassLoad с shift_id=None, получаем все (для обратной совместимости)
                if not class_loads:
                    class_loads = db.session.query(ClassLoad).filter_by(
                        subject_id=subject_id
                    ).all()
                    # Берем только уникальные комбинации (class_id, subject_id)
                    seen = set()
                    unique_loads = []
                    for cl in class_loads:
                        key = (cl.class_id, cl.subject_id)
                        if key not in seen:
                            unique_loads.append(cl)
                            seen.add(key)
                    class_loads = unique_loads
                
                class_ids_from_load = [cl.class_id for cl in class_loads]
                if class_ids_from_load:
                    classes_query = db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids_from_load))
                    all_classes = [{'id': c.id, 'name': c.name} for c in get_sorted_classes(classes_query)]
                else:
                    # Если нет ClassLoad для предмета, возвращаем все классы
                    all_classes = [{'id': c.id, 'name': c.name} for c in get_sorted_classes()]
            else:
                # Если subject_id не указан, возвращаем все классы
                all_classes = [{'id': c.id, 'name': c.name} for c in get_sorted_classes()]
            
            # Логируем финальный результат для отладки
            logger.info(f"[manage_teacher_classes] ФИНАЛЬНЫЙ РЕЗУЛЬТАТ: teacher_classes={teacher_classes}, количество={len(teacher_classes) if teacher_classes else 0}")
            
            return jsonify({
                'success': True,
                'teacher_classes': teacher_classes,
                'all_classes': all_classes
            })
        
        elif request.method == 'POST':
            # Обновить список классов учителя
            data = request.get_json()
            class_ids = data.get('class_ids', [])
            subject_id = data.get('subject_id')
            shift_id = data.get('shift_id')
            
            try:
                if subject_id and shift_id:
                    # Работаем с TeacherAssignment для конкретного предмета
                    # Получаем активную смену, если shift_id не передан или равен 0
                    if not shift_id or shift_id == 0:
                        from app.models.school import Shift
                        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
                        if not active_shift:
                            return jsonify({'success': False, 'error': 'Активная смена не найдена'}), 400
                        shift_id = active_shift.id
                    
                    # Удаляем ВСЕ старые TeacherAssignment для этого учителя, предмета и смены
                    deleted_count = db.session.query(TeacherAssignment).filter_by(
                        teacher_id=teacher_id,
                        subject_id=subject_id,
                        shift_id=shift_id
                    ).delete()
                    
                    # Добавляем новые TeacherAssignment для выбранных классов
                    # Если class_ids пустой, создаем одно назначение с hours_per_week=0 как маркер,
                    # что учитель добавлен к предмету, но классы еще не назначены
                    if class_ids:
                        from app.models.school import ClassLoad
                        for class_id in class_ids:
                            # Проверяем, есть ли ClassLoad для этого класса и предмета (общая нагрузка, shift_id = None)
                            class_load = db.session.query(ClassLoad).filter_by(
                                class_id=class_id,
                                subject_id=subject_id,
                                shift_id=None
                            ).first()
                            
                            # Если нет ClassLoad с shift_id=None, проверяем любую (для обратной совместимости)
                            if not class_load:
                                class_load = db.session.query(ClassLoad).filter_by(
                                    class_id=class_id,
                                    subject_id=subject_id
                                ).first()
                            
                            if class_load:
                                # Проверяем, нет ли уже такого назначения
                                existing = db.session.query(TeacherAssignment).filter_by(
                                    teacher_id=teacher_id,
                                    subject_id=subject_id,
                                    class_id=class_id,
                                    shift_id=shift_id
                                ).first()
                                
                                if not existing:
                                    # Создаем новое назначение с 0 часами (часы можно будет установить позже)
                                    assignment = TeacherAssignment(
                                        teacher_id=teacher_id,
                                        subject_id=subject_id,
                                        class_id=class_id,
                                        shift_id=shift_id,
                                        hours_per_week=0,
                                        default_cabinet=None
                                    )
                                    db.session.add(assignment)
                    else:
                        # Если class_ids пустой, создаем одно назначение с hours_per_week=0
                        # Это маркер того, что учитель добавлен к предмету, но классы еще не назначены
                        # Получаем первый класс для этого предмета (любой, нужен только для создания записи)
                        from app.models.school import ClassLoad
                        first_class_load = db.session.query(ClassLoad).filter_by(
                            subject_id=subject_id,
                            shift_id=None
                        ).first()
                        
                        # Если нет ClassLoad с shift_id=None, получаем любую
                        if not first_class_load:
                            first_class_load = db.session.query(ClassLoad).filter_by(
                                subject_id=subject_id
                            ).first()
                        
                        # Если все еще нет, получаем первый класс вообще
                        if not first_class_load:
                            first_class = db.session.query(ClassGroup).first()
                        else:
                            first_class = db.session.query(ClassGroup).filter_by(id=first_class_load.class_id).first()
                        
                        if first_class:
                            # Проверяем, нет ли уже такого назначения
                            existing = db.session.query(TeacherAssignment).filter_by(
                                teacher_id=teacher_id,
                                subject_id=subject_id,
                                class_id=first_class.id,
                                shift_id=shift_id
                            ).first()
                            
                            if not existing:
                                # Создаем маркерное назначение с hours_per_week=0
                                assignment = TeacherAssignment(
                                    teacher_id=teacher_id,
                                    subject_id=subject_id,
                                    class_id=first_class.id,
                                    shift_id=shift_id,
                                    hours_per_week=0,
                                    default_cabinet=None
                                )
                                db.session.add(assignment)
                else:
                    # Работаем с общей таблицей teacher_classes
                    from app.models.school import _get_teacher_classes_table
                    teacher_classes_table = _get_teacher_classes_table()
                    db.session.execute(
                        teacher_classes_table.delete().where(
                            teacher_classes_table.c.teacher_id == teacher_id
                        )
                    )
                    
                    # Добавляем новые связи
                    if class_ids:
                        for class_id in class_ids:
                            db.session.execute(
                                teacher_classes_table.insert().values(
                                    teacher_id=teacher_id,
                                    class_id=class_id
                                )
                            )
                
                db.session.commit()
                return jsonify({'success': True, 'message': 'Классы учителя обновлены'})
            except Exception as e:
                db.session.rollback()
                import traceback
                traceback.print_exc()
                return jsonify({'success': False, 'error': str(e)}), 500

