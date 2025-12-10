"""
Основные страницы админ-панели
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
import os
from app.core.db_manager import db, school_db_context, create_school_database, clear_school_database
from app.models.system import School
from app.models.school import Subject, ClassLoad, Shift, ScheduleSettings, PermanentSchedule, ClassGroup, Teacher
from app.services.excel_loader import load_class_load_excel, load_teacher_assignments_excel, load_teacher_contacts_excel
from app.core.auth import admin_required, get_current_school_id, current_user
from app.routes.utils import get_sorted_classes
from flask import current_app

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
@admin_required
def admin_index():
    """Главная страница админ-панели"""
    school_id = get_current_school_id()
    if not school_id:
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    # Получаем информацию о школе для отображения названия
    school = School.query.get(school_id)
    school_name = school.name if school else ''
    
    # Убеждаемся, что БД школы существует
    from app.core.db_manager import BASE_DIR
    db_path = os.path.join(BASE_DIR, 'databases', f'school_{school_id}.db')
    if not os.path.exists(db_path):
        try:
            create_school_database(school_id)
        except Exception as e:
            flash(f'Ошибка при создании БД школы: {str(e)}', 'danger')
            return redirect(url_for('logout'))
    
    try:
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
            try:
                subjects = db.session.query(Subject).join(ClassLoad).filter(
                    ClassLoad.shift_id == active_shift.id
                ).distinct().order_by(Subject.name).all()
            except Exception:
                subjects = db.session.query(Subject).order_by(Subject.name).all()
            
            return render_template('admin/index.html', subjects=subjects, current_user=current_user, school_name=school_name)
    except Exception as e:
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        import traceback
        traceback.print_exc()
        return redirect(url_for('logout'))


@admin_bp.route('/admin/upload', methods=['GET', 'POST'])
@admin_required
def upload_files():
    """Загрузка Excel файлов"""
    school_id = get_current_school_id()
    if not school_id:
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        if request.method == 'POST':
            shift_id = request.form.get('shift_id', type=int)
            shift = None
            if shift_id:
                shift = db.session.query(Shift).filter_by(id=shift_id).first()
                if not shift:
                    flash('Выбранная смена не найдена!', 'error')
                    shifts = db.session.query(Shift).order_by(Shift.id).all()
                    return render_template('admin/upload.html', shifts=shifts)
            
            if 'class_load' in request.files and request.files['class_load'].filename:
                f = request.files['class_load']
                path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'class_load.xlsx')
                f.save(path)
                
                # Если shift_id не указан, функция создаст смены автоматически из листов Excel
                created_shifts = load_class_load_excel(path, shift_id, school_id)
                
                if created_shifts:
                    # Были созданы новые смены
                    shifts_list = ', '.join([f'"{name}"' for name in created_shifts.keys()])
                    flash(f'Создано смен: {len(created_shifts)} ({shifts_list}). Нагрузка классов загружена успешно!', 'success')
                elif shift_id and shift:
                    flash(f'Нагрузка классов загружена успешно для смены "{shift.name}"!', 'success')
                else:
                    flash('Нагрузка классов загружена успешно!', 'success')

            if 'teacher_assign' in request.files and request.files['teacher_assign'].filename:
                f = request.files['teacher_assign']
                path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'teacher_assign.xlsx')
                f.save(path)
                if shift_id:
                    load_teacher_assignments_excel(path, shift_id, school_id)
                    flash(f'Назначения учителей загружены успешно для смены "{shift.name}"!', 'success')
                else:
                    flash('Для загрузки назначений учителей необходимо выбрать смену!', 'error')

            if 'teacher_contacts' in request.files and request.files['teacher_contacts'].filename:
                f = request.files['teacher_contacts']
                path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'teacher_contacts.xlsx')
                f.save(path)
                try:
                    updated, created = load_teacher_contacts_excel(path, shift_id, school_id)
                    flash(f'Контакты учителей загружены успешно! Обновлено: {updated}, создано: {created}', 'success')
                except Exception as e:
                    flash(f'Ошибка при загрузке контактов учителей: {str(e)}', 'error')

            return redirect(url_for('admin.admin_index'))
        
        shifts = db.session.query(Shift).order_by(Shift.id).all()
        if not shifts:
            default_shift = Shift(name='Первая смена', is_active=True)
            db.session.add(default_shift)
            db.session.commit()
            shifts = [default_shift]
        
        return render_template('admin/upload.html', shifts=shifts)


@admin_bp.route('/admin/clear')
@admin_required
def clear_db():
    """Очистить БД школы"""
    school_id = get_current_school_id()
    if not school_id:
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    if request.args.get('confirm') == 'yes':
        try:
            if clear_school_database(school_id):
                flash('База данных школы полностью очищена!', 'warning')
            else:
                flash('Ошибка при очистке базы данных', 'danger')
        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
    return redirect(url_for('admin.admin_index'))

