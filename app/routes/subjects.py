"""
Работа с предметами и матрицей предметов
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from app.core.db_manager import db, school_db_context
from app.models.school import (
    Subject, ClassGroup, Teacher, ClassLoad, TeacherAssignment, Shift,
    SUBJECT_CATEGORIES, SUBJECT_CATEGORY_LANGUAGES, 
    SUBJECT_CATEGORY_HUMANITIES, SUBJECT_CATEGORY_NATURAL_MATH
)
from app.core.auth import admin_required, get_current_school_id, current_user
from app.routes.utils import get_class_group, get_sorted_classes

subjects_bp = Blueprint('subjects', __name__)


@subjects_bp.route('/admin/subjects')
@admin_required
def subjects_page():
    """Страница со списком предметов"""
    school_id = get_current_school_id()
    if not school_id:
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        # Получаем активную смену
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            shifts = db.session.query(Shift).all()
            if shifts:
                active_shift = shifts[0]
                active_shift.is_active = True
                db.session.commit()
            else:
                active_shift = Shift(name='Первая смена', is_active=True)
                db.session.add(active_shift)
                db.session.commit()
        
        # Получаем предметы
        # Сначала пытаемся получить предметы из ClassLoad с shift_id=None
        try:
            subjects = db.session.query(Subject).join(ClassLoad).filter(
                ClassLoad.shift_id.is_(None)
            ).distinct().order_by(Subject.name).all()
            
            # Если нет предметов с shift_id=None, получаем из всех ClassLoad (для обратной совместимости)
            if not subjects:
                subjects = db.session.query(Subject).join(ClassLoad).distinct().order_by(Subject.name).all()
        except Exception:
            # Если возникла ошибка, получаем все предметы
            subjects = db.session.query(Subject).order_by(Subject.name).all()
        
        # Дополнительная проверка на случай, если список все еще пустой
        if not subjects:
            subjects = db.session.query(Subject).order_by(Subject.name).all()
        
        # Группируем предметы по классам (начальная 1-4 и старшая 5-11)
        primary_subjects = set()
        secondary_subjects = set()
        
        all_classes = db.session.query(ClassGroup).all()
        for cls in all_classes:
            group = get_class_group(cls.name)
            # Нагрузка общая для всех смен (shift_id = NULL)
            class_loads = db.session.query(ClassLoad).filter_by(
                shift_id=None,
                class_id=cls.id
            ).all()
            
            # Если нет нагрузки с shift_id=None, получаем все (для обратной совместимости)
            if not class_loads:
                class_loads = db.session.query(ClassLoad).filter_by(class_id=cls.id).all()
                # Берем только уникальные комбинации (class_id, subject_id)
                seen = set()
                unique_loads = []
                for cl in class_loads:
                    key = (cl.class_id, cl.subject_id)
                    if key not in seen:
                        unique_loads.append(cl)
                        seen.add(key)
                class_loads = unique_loads
            
            for class_load in class_loads:
                subject_id = class_load.subject_id
                if group == 'primary':
                    primary_subjects.add(subject_id)
                elif group == 'secondary':
                    secondary_subjects.add(subject_id)
        
        primary_subjects_list = [s for s in subjects if s.id in primary_subjects]
        secondary_subjects_list = [s for s in subjects if s.id in secondary_subjects]
        common_subjects = [s for s in subjects if s.id in primary_subjects and s.id in secondary_subjects]
        
        # Группируем предметы по категориям
        subjects_by_category = {
            SUBJECT_CATEGORY_LANGUAGES: [],
            SUBJECT_CATEGORY_HUMANITIES: [],
            SUBJECT_CATEGORY_NATURAL_MATH: [],
            'uncategorized': []
        }
        
        for subject in subjects:
            if subject.category and subject.category in subjects_by_category:
                subjects_by_category[subject.category].append(subject)
            else:
                subjects_by_category['uncategorized'].append(subject)
        
        # Если выбран предмет, загружаем данные для матрицы
        selected_subject = None
        teachers_with_classes = []
        teachers = []
        all_teachers = []
        subject_name = request.args.get('subject')
        
        if subject_name:
            selected_subject = db.session.query(Subject).filter_by(name=subject_name).first()
            if selected_subject:
                # Сначала пытаемся получить учителей для активной смены
                teachers = db.session.query(Teacher).join(TeacherAssignment).filter(
                    TeacherAssignment.subject_id == selected_subject.id,
                    TeacherAssignment.shift_id == active_shift.id
                ).distinct().order_by(Teacher.full_name).all()
                
                # Если учителей нет для активной смены, получаем для любой смены
                if not teachers:
                    teachers = db.session.query(Teacher).join(TeacherAssignment).filter(
                        TeacherAssignment.subject_id == selected_subject.id
                    ).distinct().order_by(Teacher.full_name).all()
                
                from app.models.school import CabinetTeacher, Cabinet, PromptClassSubject, PromptClassSubjectTeacher
                teachers_with_classes = []
                for teacher in teachers:
                    # Получаем все назначения учителя для этого предмета (для любой смены)
                    # Это гарантирует, что мы получим все классы, даже если они для разных смен
                    teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                        teacher_id=teacher.id,
                        subject_id=selected_subject.id
                    ).all()
                    
                    # Если есть назначения, приоритет отдаем активной смене
                    if teacher_assignments:
                        # Проверяем, есть ли назначения для активной смены
                        active_shift_assignments = [ta for ta in teacher_assignments if hasattr(ta, 'shift_id') and ta.shift_id == active_shift.id]
                        if active_shift_assignments:
                            teacher_assignments = active_shift_assignments
                        # Если нет для активной смены, берем все назначения (для любой смены)
                    
                    # Получаем ID классов из назначений, фильтруя None и дубликаты
                    class_ids = []
                    for ta in teacher_assignments:
                        if hasattr(ta, 'class_id') and ta.class_id is not None:
                            class_id = int(ta.class_id)
                            if class_id not in class_ids:
                                class_ids.append(class_id)
                    
                    # Получаем классы
                    if class_ids:
                        try:
                            classes_query = db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids))
                            classes = get_sorted_classes(classes_query)
                            # Дополнительная проверка: если запрос вернул пустой список, но class_ids не пустой,
                            # возможно классы были удалены из БД
                            if not classes and class_ids:
                                print(f"⚠️ Предупреждение: классы с ID {class_ids} не найдены в БД для учителя {teacher.id}")
                        except Exception as e:
                            print(f"❌ Ошибка при получении классов для учителя {teacher.id}: {e}")
                            import traceback
                            traceback.print_exc()
                            classes = []
                    else:
                        classes = []
                        # Если нет class_ids, но есть teacher_assignments, это странно
                        if teacher_assignments:
                            print(f"⚠️ Предупреждение: у учителя {teacher.id} есть {len(teacher_assignments)} назначений, но нет class_id")
                    
                    # Получаем кабинеты учителя для этого предмета
                    # 1. Из TeacherAssignment (default_cabinet)
                    cabinets_from_assignments = set()
                    for ta in teacher_assignments:
                        if ta.default_cabinet and ta.default_cabinet.strip() and ta.default_cabinet.strip() != '-':
                            cabinets_from_assignments.add(ta.default_cabinet.strip())
                    
                    # 2. Из CabinetTeacher (связь учителя с кабинетом)
                    cabinet_teachers = db.session.query(CabinetTeacher).filter_by(teacher_id=teacher.id).all()
                    cabinets_from_relation = []
                    for ct in cabinet_teachers:
                        cabinet = db.session.query(Cabinet).filter_by(id=ct.cabinet_id).first()
                        if cabinet:
                            cabinets_from_relation.append(cabinet.name)
                    
                    # Объединяем кабинеты
                    all_cabinets = list(cabinets_from_assignments) + cabinets_from_relation
                    unique_cabinets = list(set(all_cabinets))
                    
                    # Проверка временной записи
                    is_temporary = False
                    if len(teacher_assignments) == 1 and teacher_assignments[0].hours_per_week == 0:
                        # Нагрузка общая для всех смен (shift_id = NULL)
                        class_loads = db.session.query(ClassLoad).filter_by(
                            shift_id=None,
                            subject_id=selected_subject.id
                        ).order_by(ClassLoad.class_id).all()
                        
                        # Если нет нагрузки с shift_id=None, получаем все (для обратной совместимости)
                        if not class_loads:
                            all_loads = db.session.query(ClassLoad).filter_by(
                                subject_id=selected_subject.id
                            ).order_by(ClassLoad.class_id).all()
                            # Берем только уникальные комбинации (class_id, subject_id)
                            seen = set()
                            for cl in all_loads:
                                key = (cl.class_id, cl.subject_id)
                                if key not in seen:
                                    class_loads.append(cl)
                                    seen.add(key)
                        
                        if class_loads and len(class_loads) > 1:
                            first_class_id = class_loads[0].class_id
                            if teacher_assignments[0].class_id == first_class_id:
                                is_temporary = True
                    
                    if is_temporary:
                        classes = []
                    
                    teachers_with_classes.append({
                        'teacher': teacher,
                        'classes': classes,
                        'cabinets': unique_cabinets
                    })
                
                # Получаем информацию о подгруппах для каждого класса и предмета
                subject_subgroups_info = {}  # {(class_id, subject_id): has_subgroups}
                if selected_subject:
                    prompt_class_subjects = db.session.query(PromptClassSubject).filter_by(
                        shift_id=active_shift.id,
                        subject_id=selected_subject.id
                    ).all()
                    
                    for pcs in prompt_class_subjects:
                        # Определяем has_subgroups: либо из БД, либо автоматически по количеству учителей
                        if pcs.has_subgroups is True:
                            has_subgroups = True
                        elif pcs.has_subgroups is False:
                            has_subgroups = False
                        else:
                            # Автоматическое определение: если учителей 2 или больше, значит есть подгруппы
                            teachers_count = db.session.query(PromptClassSubjectTeacher).filter_by(
                                prompt_class_subject_id=pcs.id
                            ).count()
                            has_subgroups = teachers_count >= 2
                        
                        subject_subgroups_info[(pcs.class_id, pcs.subject_id)] = has_subgroups
                else:
                    subject_subgroups_info = {}
                
                if teachers:
                    all_teachers = db.session.query(Teacher).filter(
                        ~Teacher.id.in_([t.id for t in teachers])
                    ).order_by(Teacher.full_name).all()
                else:
                    all_teachers = db.session.query(Teacher).order_by(Teacher.full_name).all()
        
        return render_template('admin/subjects.html', 
                             subjects=subjects,
                             primary_subjects=primary_subjects_list,
                             secondary_subjects=secondary_subjects_list,
                             common_subjects=common_subjects,
                             subjects_by_category=subjects_by_category,
                             subject_categories=SUBJECT_CATEGORIES,
                             current_user=current_user,
                             active_shift=active_shift,
                             selected_subject=selected_subject,
                             teachers_with_classes=teachers_with_classes,
                             teachers=teachers,
                             all_teachers=all_teachers,
                             shift_id=active_shift.id if active_shift else None,
                             subject_subgroups_info=subject_subgroups_info if subject_name else {})


@subjects_bp.route('/admin/matrix/<subject_name>')
@admin_required
def subject_matrix(subject_name):
    """Матрица предметов"""
    school_id = get_current_school_id()
    if not school_id:
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        subject = db.session.query(Subject).filter_by(name=subject_name).first_or_404()
        
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            return redirect(url_for('admin.admin_index'))
        
        teachers = db.session.query(Teacher).join(TeacherAssignment).filter(
            TeacherAssignment.subject_id == subject.id,
            TeacherAssignment.shift_id == active_shift.id
        ).distinct().order_by(Teacher.full_name).all()
        
        teachers_with_classes = []
        for teacher in teachers:
            teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                teacher_id=teacher.id,
                subject_id=subject.id,
                shift_id=active_shift.id
            ).all()
            
            class_ids = list(set([ta.class_id for ta in teacher_assignments]))
            classes = get_sorted_classes(db.session.query(ClassGroup).filter(ClassGroup.id.in_(class_ids))) if class_ids else []
            
            teachers_with_classes.append({
                'teacher': teacher,
                'classes': classes
            })
        
        if teachers:
            all_teachers = db.session.query(Teacher).filter(
                ~Teacher.id.in_([t.id for t in teachers])
            ).order_by(Teacher.full_name).all()
        else:
            all_teachers = db.session.query(Teacher).order_by(Teacher.full_name).all()

        return render_template('admin/subject_matrix.html',
                               subject=subject, 
                               teachers_with_classes=teachers_with_classes, 
                               teachers=teachers, 
                               all_teachers=all_teachers, 
                               shift_id=active_shift.id)


@subjects_bp.route('/admin/update_hours', methods=['POST'])
@admin_required
def update_hours():
    """Обновить количество часов для учителя по предмету"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    teacher_id = data.get('teacher_id')
    class_id = data.get('class_id')
    subject_id = data.get('subject_id')
    hours = data.get('hours', 0)
    
    with school_db_context(school_id):
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            return jsonify({'success': False, 'error': 'Нет активной смены'}), 400
        
        shift_id = active_shift.id

        assignment = db.session.query(TeacherAssignment).filter_by(
            shift_id=shift_id,
            teacher_id=teacher_id, 
            subject_id=subject_id, 
            class_id=class_id
        ).first()

        if assignment:
            assignment.hours_per_week = hours
        else:
            assignment = TeacherAssignment(
                shift_id=shift_id,
                teacher_id=teacher_id,
                subject_id=subject_id,
                class_id=class_id,
                hours_per_week=hours
            )
            db.session.add(assignment)

        db.session.commit()

        assigned = sum(
            ta.hours_per_week for ta in db.session.query(TeacherAssignment).filter_by(
                shift_id=shift_id,
                subject_id=subject_id, 
                class_id=class_id
            ).all()
        )

        # Нагрузка общая для всех смен (shift_id = None)
        load = db.session.query(ClassLoad).filter_by(shift_id=None, class_id=class_id, subject_id=subject_id).first()
        # Если нет нагрузки с shift_id=None, получаем любую (для обратной совместимости)
        if not load:
            load = db.session.query(ClassLoad).filter_by(class_id=class_id, subject_id=subject_id).first()
        required = load.hours_per_week if load else 0
        diff = required - assigned

        return jsonify({'assigned': assigned, 'diff': diff})


@subjects_bp.route('/admin/add_teacher_to_subject', methods=['POST'])
@admin_required
def add_teacher_to_subject():
    """Добавить учителя к предмету"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    teacher_id = data.get('teacher_id')
    subject_id = data.get('subject_id')
    
    with school_db_context(school_id):
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            return jsonify({'success': False, 'error': 'Нет активной смены'}), 400
        
        shift_id = active_shift.id

        # Получаем классы, для которых есть ClassLoad (общая нагрузка, shift_id = None)
        classes = db.session.query(ClassGroup).join(ClassLoad).filter(
            ClassLoad.subject_id == subject_id,
            ClassLoad.shift_id.is_(None)
        ).all()
        
        # Если нет классов с ClassLoad shift_id=None, получаем все классы с ClassLoad для этого предмета (для обратной совместимости)
        if not classes:
            classes = db.session.query(ClassGroup).join(ClassLoad).filter(
                ClassLoad.subject_id == subject_id
            ).distinct().all()
        
        # Если все еще нет классов, получаем все классы
        if not classes:
            classes = db.session.query(ClassGroup).all()

        # Добавляем учителя к классам
        if classes:
            for cls in classes:
                existing = db.session.query(TeacherAssignment).filter_by(
                    shift_id=shift_id,
                    teacher_id=teacher_id, 
                    subject_id=subject_id, 
                    class_id=cls.id
                ).first()
                if not existing:
                    assignment = TeacherAssignment(
                        shift_id=shift_id,
                        teacher_id=teacher_id,
                        subject_id=subject_id,
                        class_id=cls.id,
                        hours_per_week=0
                    )
                    db.session.add(assignment)
        else:
            # Если вообще нет классов в базе, создаем TeacherAssignment без класса
            # Но это может быть проблемой, если class_id обязателен
            # В этом случае просто возвращаем ошибку
            return jsonify({'success': False, 'error': 'Нет классов в базе данных'}), 400

        db.session.commit()
        return jsonify({'success': True})


@subjects_bp.route('/admin/api/active_shift', methods=['GET'])
@admin_required
def get_active_shift():
    """Получить ID активной смены"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    with school_db_context(school_id):
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            # Пытаемся найти или создать активную смену
            shifts = db.session.query(Shift).all()
            if shifts:
                active_shift = shifts[0]
                active_shift.is_active = True
                db.session.commit()
            else:
                active_shift = Shift(name='Первая смена', is_active=True)
                db.session.add(active_shift)
                db.session.commit()
        
        return jsonify({
            'success': True,
            'shift_id': active_shift.id,
            'shift_name': active_shift.name
        })


@subjects_bp.route('/admin/remove_teacher_from_subject', methods=['POST'])
@admin_required
def remove_teacher_from_subject():
    """Удалить учителя из предмета"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    teacher_id = data.get('teacher_id')
    subject_id = data.get('subject_id')
    shift_id = data.get('shift_id')
    
    # Логирование для отладки
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[remove_teacher_from_subject] teacher_id={teacher_id}, subject_id={subject_id}, shift_id={shift_id}")
    
    with school_db_context(school_id):
        # Используем переданный shift_id, если он есть, иначе берем активную смену
        if not shift_id:
            active_shift = db.session.query(Shift).filter_by(is_active=True).first()
            if not active_shift:
                logger.warning(f"[remove_teacher_from_subject] Активная смена не найдена")
                return jsonify({'success': False, 'error': 'Нет активной смены'}), 400
            shift_id = active_shift.id
            logger.info(f"[remove_teacher_from_subject] Используется активная смена: shift_id={shift_id}")
        else:
            # Проверяем, что смена существует
            shift = db.session.query(Shift).filter_by(id=shift_id).first()
            if not shift:
                logger.warning(f"[remove_teacher_from_subject] Смена не найдена: shift_id={shift_id}")
                return jsonify({'success': False, 'error': 'Смена не найдена'}), 400

        try:
            assignments = db.session.query(TeacherAssignment).filter_by(
                shift_id=shift_id,
                teacher_id=teacher_id,
                subject_id=subject_id
            ).all()
            
            deleted_count = len(assignments)
            logger.info(f"[remove_teacher_from_subject] Найдено назначений для удаления: {deleted_count}")
            
            for assignment in assignments:
                db.session.delete(assignment)
            
            db.session.commit()
            logger.info(f"[remove_teacher_from_subject] Успешно удалено назначений: {deleted_count}")
            
            return jsonify({
                'success': True, 
                'message': f'Учитель удален из предмета (удалено назначений: {deleted_count})'
            })
        except Exception as e:
            db.session.rollback()
            import traceback
            logger.error(f"[remove_teacher_from_subject] Ошибка: {str(e)}")
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500


@subjects_bp.route('/admin/subjects/<int:subject_id>/update_category', methods=['POST'])
@admin_required
def update_subject_category(subject_id):
    """Обновить категорию предмета"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    category = data.get('category')
    
    # Валидация категории
    valid_categories = [SUBJECT_CATEGORY_LANGUAGES, SUBJECT_CATEGORY_HUMANITIES, 
                       SUBJECT_CATEGORY_NATURAL_MATH, None, '']
    if category not in valid_categories:
        return jsonify({'success': False, 'error': 'Недопустимая категория'}), 400
    
    # Преобразуем пустую строку в None
    if category == '':
        category = None
    
    with school_db_context(school_id):
        subject = db.session.query(Subject).filter_by(id=subject_id).first()
        if not subject:
            return jsonify({'success': False, 'error': 'Предмет не найден'}), 404
        
        try:
            subject.category = category
            db.session.commit()
            
            category_name = SUBJECT_CATEGORIES.get(category, 'Без категории') if category else 'Без категории'
            return jsonify({
                'success': True, 
                'message': f'Категория обновлена: {category_name}',
                'category': category,
                'category_name': category_name
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
