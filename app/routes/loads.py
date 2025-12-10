"""
Нагрузка классов и учителей
"""
from flask import Blueprint, render_template, request, jsonify
from app.core.db_manager import db, school_db_context
from app.models.school import ClassGroup, Subject, ClassLoad, Teacher, TeacherAssignment, Shift
from app.core.auth import admin_required, get_current_school_id, current_user
from app.routes.utils import get_class_group, get_sorted_classes

loads_bp = Blueprint('loads', __name__)


@loads_bp.route('/admin/classes')
@admin_required
def classes_page():
    """Страница для просмотра классов с предметами, учителями и часами"""
    school_id = get_current_school_id()
    if not school_id:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            shifts = db.session.query(Shift).all()
            if shifts:
                active_shift = shifts[0]
            else:
                active_shift = Shift(name='Первая смена', is_active=True)
                db.session.add(active_shift)
                db.session.commit()
        
        classes = get_sorted_classes()
        classes_data = []
        
        for cls in classes:
            # Нагрузка общая для всех смен (shift_id = None)
            class_loads = db.session.query(ClassLoad).filter_by(
                shift_id=None,
                class_id=cls.id
            ).all()
            
            # Если нет нагрузки с shift_id=None, получаем все (для обратной совместимости)
            if not class_loads:
                all_loads = db.session.query(ClassLoad).filter_by(class_id=cls.id).all()
                # Берем только уникальные комбинации (class_id, subject_id)
                seen = set()
                for cl in all_loads:
                    key = (cl.class_id, cl.subject_id)
                    if key not in seen:
                        class_loads.append(cl)
                        seen.add(key)
            
            for class_load in class_loads:
                subject = db.session.query(Subject).filter_by(id=class_load.subject_id).first()
                if not subject:
                    continue
                
                # Сначала пытаемся получить назначения для активной смены
                teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                    shift_id=active_shift.id,
                    class_id=cls.id,
                    subject_id=class_load.subject_id
                ).all()
                
                # Если нет назначений для активной смены, получаем для любой смены
                if not teacher_assignments:
                    teacher_assignments = db.session.query(TeacherAssignment).filter_by(
                        class_id=cls.id,
                        subject_id=class_load.subject_id
                    ).all()
                    # Если есть несколько назначений для разных смен, приоритет отдаем активной смене
                    # Но если их нет для активной смены, берем все
                
                teachers = []
                for assignment in teacher_assignments:
                    teacher = db.session.query(Teacher).filter_by(id=assignment.teacher_id).first()
                    if teacher:
                        teachers.append({
                            'teacher_id': teacher.id,
                            'teacher_name': teacher.full_name,
                            'hours_per_week': assignment.hours_per_week or 0,
                            'default_cabinet': assignment.default_cabinet or ''
                        })
                
                classes_data.append({
                    'class_id': cls.id,
                    'class_name': cls.name,
                    'subject_id': subject.id,
                    'subject_name': subject.name,
                    'total_hours_per_week': class_load.hours_per_week,
                    'has_subgroups': len(teachers) >= 2,
                    'teachers': teachers
                })
        
        classes_dict = {}
        for item in classes_data:
            class_name = item['class_name']
            if class_name not in classes_dict:
                classes_dict[class_name] = {
                    'class_id': item['class_id'],
                    'class_name': class_name,
                    'subjects': []
                }
            
            classes_dict[class_name]['subjects'].append({
                'subject_id': item['subject_id'],
                'subject_name': item['subject_name'],
                'total_hours_per_week': item['total_hours_per_week'],
                'has_subgroups': item['has_subgroups'],
                'teachers': item['teachers']
            })
        
        classes_list = sorted(classes_dict.values(), key=lambda x: x['class_name'])
        for cls_data in classes_list:
            cls_data['subjects'].sort(key=lambda x: x['subject_name'])
        
        primary_classes = []
        secondary_classes = []
        
        for cls_data in classes_list:
            group = get_class_group(cls_data['class_name'])
            if group == 'primary':
                primary_classes.append(cls_data)
            elif group == 'secondary':
                secondary_classes.append(cls_data)
            else:
                secondary_classes.append(cls_data)
        
        return render_template('admin/classes.html',
                             classes_list=classes_list,
                             primary_classes=primary_classes,
                             secondary_classes=secondary_classes,
                             active_shift=active_shift,
                             current_user=current_user)


# Остальные функции для нагрузки будут добавлены позже:
# - class_loads_page
# - auto_fill_class_loads
# - update_class_load
# - teacher_workload_page

