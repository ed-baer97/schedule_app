"""
Работа с расписанием (постоянное и временное)
"""
from flask import Blueprint, render_template, request, jsonify
from datetime import datetime
from collections import defaultdict
import logging
from app.core.db_manager import db, school_db_context
from app.models.school import (
    Subject, ClassGroup, Teacher, PermanentSchedule, TemporarySchedule,
    Shift, ScheduleSettings
)
from app.core.auth import admin_required, get_current_school_id
from app.routes.utils import get_sorted_classes
from app.services.progress_manager import get_progress

from app.services.progress_manager import get_progress


logger = logging.getLogger(__name__)

schedule_bp = Blueprint('schedule', __name__)


@schedule_bp.route('/admin/schedule')
@admin_required
def schedule():
    """Страница расписания"""
    school_id = get_current_school_id()
    if not school_id:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    with school_db_context(school_id):
        classes = get_sorted_classes()
        subjects = db.session.query(Subject).order_by(Subject.name).all()
        teachers = db.session.query(Teacher).order_by(Teacher.full_name).all()
        
        shifts = db.session.query(Shift).order_by(Shift.id).all()
        if not shifts:
            default_shift = Shift(name='Первая смена', is_active=True)
            db.session.add(default_shift)
            db.session.commit()
            shifts = [default_shift]
        
        active_shift = db.session.query(Shift).filter_by(is_active=True).first()
        if not active_shift:
            active_shift = shifts[0]
            active_shift.is_active = True
            db.session.commit()
        
        active_shift_id = active_shift.id
        
        settings = {}
        schedule_settings = db.session.query(ScheduleSettings).filter_by(shift_id=active_shift_id).all()
        for setting in schedule_settings:
            settings[setting.day_of_week] = setting.lessons_count
        
        if not settings:
            for day in range(1, 8):
                setting = ScheduleSettings(shift_id=active_shift_id, day_of_week=day, lessons_count=6)
                db.session.add(setting)
                settings[day] = 6
            db.session.commit()
        
        permanent_schedule = db.session.query(PermanentSchedule).filter_by(shift_id=active_shift_id).join(
            ClassGroup).join(Subject).join(Teacher).order_by(
            PermanentSchedule.day_of_week,
            PermanentSchedule.lesson_number,
            ClassGroup.name
        ).all()
        
        schedule_data = []
        # Группируем по ячейкам для отладки подгрупп
        cells_with_multiple_lessons = defaultdict(list)
        
        for item in permanent_schedule:
            schedule_data.append({
                'id': item.id,
                'day_of_week': item.day_of_week,
                'lesson_number': item.lesson_number,
                'class_id': item.class_id,
                'subject_name': item.subject.name,
                'teacher_name': item.teacher.full_name,
                'cabinet': item.cabinet or ''
            })
            
            # Отладка: собираем уроки по ячейкам
            cell_key = (item.class_id, item.day_of_week, item.lesson_number, item.subject_id)
            cells_with_multiple_lessons[cell_key].append({
                'teacher_name': item.teacher.full_name,
                'teacher_id': item.teacher_id,
                'cabinet': item.cabinet or ''
            })
        
        # Логируем ячейки с несколькими уроками (подгруппы)
        logger.info("=" * 80)
        logger.info("ПРОВЕРКА ПОДГРУПП В БД")
        logger.info("=" * 80)
        subgroups_found = 0
        for (class_id, day, lesson, subject_id), lessons in cells_with_multiple_lessons.items():
            if len(lessons) > 1:
                subgroups_found += 1
                class_group = next((c for c in classes if c.id == class_id), None)
                subject = next((s for s in subjects if s.id == subject_id), None)
                class_name = class_group.name if class_group else f"Class {class_id}"
                subject_name = subject.name if subject else f"Subject {subject_id}"
                logger.info(f"✓ ПОДГРУППЫ в БД: Класс '{class_name}', Предмет '{subject_name}', День {day}, Урок {lesson}")
                for lesson_info in lessons:
                    logger.info(f"   - Учитель: {lesson_info['teacher_name']} (ID: {lesson_info['teacher_id']}), Кабинет: {lesson_info['cabinet']}")
        
        if subgroups_found == 0:
            logger.warning("⚠️ В БД не найдено подгрупп (ячеек с несколькими уроками одного предмета)")
        else:
            logger.info(f"✓ Найдено подгрупп в БД: {subgroups_found}")
        logger.info("=" * 80)
        
        classes_list = [{'id': cls.id, 'name': cls.name} for cls in classes]
        teachers_list = [{'id': t.id, 'full_name': t.full_name} for t in teachers] if teachers else []
        subjects_list = [{'id': s.id, 'name': s.name} for s in subjects] if subjects else []
        
        return render_template('admin/schedule.html',
                             classes=classes,
                             subjects=subjects,
                             teachers=teachers,
                             teachers_list=teachers_list,
                             subjects_list=subjects_list,
                             shifts=shifts,
                             active_shift_id=active_shift_id,
                             schedule_data=schedule_data,
                             lessons_count=settings,
                             classes_list=classes_list)


@schedule_bp.route('/admin/schedule/generate', methods=['POST'])
@admin_required
def generate_schedule():
    """Генерация расписания с использованием фильтров"""
    import time
    start_time = time.time()
    
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    shift_id = data.get('shift_id')
    filter_settings = data.get('filter_settings', {})
    algorithm = data.get('algorithm', 'pipeline')  # По умолчанию pipeline
    
    logger.info("=" * 80)
    logger.info(f"НАЧАЛО ГЕНЕРАЦИИ РАСПИСАНИЯ")
    logger.info(f"Смена ID: {shift_id}, Алгоритм: {algorithm}")
    logger.info(f"Настройки фильтра: {filter_settings}")
    logger.info("=" * 80)
    
    if not shift_id:
        return jsonify({'success': False, 'error': 'ID смены не указан'}), 400
    
    try:
        with school_db_context(school_id):
            # Проверяем существование смены
            logger.info(f"[1/5] Проверка смены ID={shift_id}...")
            shift = db.session.query(Shift).filter_by(id=shift_id).first()
            if not shift:
                logger.error(f"[1/5] ОШИБКА: Смена {shift_id} не найдена")
                return jsonify({'success': False, 'error': 'Смена не найдена'}), 404
            logger.info(f"[1/5] ✓ Смена найдена: {shift.name}")
            
            # Выбираем генератор в зависимости от выбранного алгоритма
            logger.info(f"[2/5] Запуск алгоритма генерации: {algorithm}...")
            
            # Получаем настройки фильтров
            lesson_mode = filter_settings.get('lessonMode', 'pairs')
            subgroup_pairs = filter_settings.get('subgroupPairs', [])
            
            if algorithm == 'pipeline' or algorithm == 'hybrid':
                from app.services.schedule_solver_hybrid_adapter import generate_schedule_hybrid
                logger.info(f"[2/5] Гибридный алгоритм: Greedy → CP-SAT → LNS")
                logger.info(f"[2/5] Параметры: lesson_mode={lesson_mode}, subgroup_pairs={len(subgroup_pairs)} пар")
                # Не передаем school_id, так как мы уже внутри school_db_context
                # Функция будет использовать существующий контекст
                result = generate_schedule_hybrid(
                    shift_id=shift_id,
                    school_id=school_id,  # Передаем явно для гарантии контекста
                    clear_existing=True,
                    time_limit_seconds=45,
                    lesson_mode=lesson_mode,
                    subgroup_pairs=subgroup_pairs
                )
            elif algorithm == 'greedy':
                from app.services.schedule_solver_greedy_adapter import generate_schedule_greedy
                logger.info(f"[2/5] Greedy: быстрый жадный алгоритм")
                result = generate_schedule_greedy(
                    shift_id=shift_id,
                    school_id=school_id,
                    clear_existing=True
                )
            elif algorithm == 'cp_sat':
                from app.services.schedule_solver_cp_sat_adapter import generate_schedule_cp_sat
                logger.info(f"[2/5] CP-SAT: time_limit=300с, точный алгоритм оптимизации")
                result = generate_schedule_cp_sat(
                    shift_id=shift_id,
                    school_id=school_id,
                    clear_existing=True,
                    time_limit_seconds=300
                )
            elif algorithm == 'basic':
                from app.services.schedule_solver_basic_adapter import generate_schedule_basic
                logger.info(f"[2/5] Basic: простой базовый алгоритм")
                result = generate_schedule_basic(
                    shift_id=shift_id,
                    school_id=school_id,
                    clear_existing=True
                )
            elif algorithm == 'genetic':
                from app.services.schedule_solver_genetic_adapter import generate_schedule_genetic
                logger.info(f"[2/5] Генетический алгоритм: population_size=400, generations=2000")
                result = generate_schedule_genetic(
                    shift_id=shift_id,
                    school_id=school_id,
                    clear_existing=True,
                    population_size=400,
                    generations=2000
                )
            else:
                logger.error(f"[2/5] ОШИБКА: Неизвестный алгоритм: {algorithm}")
                return jsonify({'success': False, 'error': f'Неизвестный алгоритм: {algorithm}'}), 400
            
            algorithm_time = time.time() - start_time
            logger.info(f"[2/5] ✓ Алгоритм завершен за {algorithm_time:.2f} секунд")
            
            # Проверяем наличие результата
            if not result:
                logger.error(f"[2/5] ОШИБКА: Алгоритм вернул None")
                return jsonify({
                    'success': False,
                    'error': 'Алгоритм не вернул результат',
                    'warnings': [],
                    'summary': 'Внутренняя ошибка алгоритма'
                }), 500
            
            suggestions_count = len(result.get('suggestions', []))
            warnings_count = len(result.get('warnings', []))
            logger.info(f"[2/5] Результат: {suggestions_count} предложений, {warnings_count} предупреждений")
            
            # Логируем предупреждения, если есть
            if result.get('warnings'):
                logger.warning(f"[2/5] Предупреждения алгоритма:")
                for warning in result['warnings']:
                    logger.warning(f"  - {warning}")
            
            # Проверяем результат
            logger.info(f"[3/5] Обработка результатов генерации...")
            if suggestions_count > 0:
                # Очищаем существующее расписание
                logger.info(f"[3/5] Очистка существующего расписания для смены {shift_id}...")
                deleted_count = db.session.query(PermanentSchedule).filter_by(shift_id=shift_id).count()
                db.session.query(PermanentSchedule).filter_by(shift_id=shift_id).delete()
                db.session.commit()
                logger.info(f"[3/5] ✓ Удалено {deleted_count} старых записей")
                
                # Применяем предложения к расписанию
                logger.info(f"[4/5] Сохранение {len(result['suggestions'])} уроков в БД...")
                applied_count = 0
                failed_count = 0
                skipped_duplicates = 0
                
                # Используем set для отслеживания уникальных комбинаций
                seen_entries = set()
                
                for idx, suggestion in enumerate(result['suggestions']):
                    try:
                        # Формируем ключ для проверки уникальности
                        entry_key = (
                            shift_id,
                            suggestion.get('day_of_week'),
                            suggestion.get('lesson_number'),
                            suggestion.get('class_id'),
                            suggestion.get('teacher_id'),
                            suggestion.get('cabinet', '')
                        )
                        
                        # Проверяем на дубликаты
                        if entry_key in seen_entries:
                            skipped_duplicates += 1
                            if skipped_duplicates <= 5:
                                logger.warning(f"[4/5] Пропущен дубликат: day={suggestion.get('day_of_week')}, lesson={suggestion.get('lesson_number')}, class={suggestion.get('class_id')}, teacher={suggestion.get('teacher_id')}, cabinet={suggestion.get('cabinet')}")
                            continue
                        
                        # Проверка существования в БД удалена для оптимизации производительности
                        # Мы полагаемся на seen_entries и предварительную очистку БД
                        # Это предотвращает ошибку "database is locked" из-за autoflush
                        
                        seen_entries.add(entry_key)
                        
                        schedule_entry = PermanentSchedule(
                            shift_id=shift_id,
                            class_id=suggestion.get('class_id'),
                            subject_id=suggestion.get('subject_id'),
                            teacher_id=suggestion.get('teacher_id'),
                            day_of_week=suggestion.get('day_of_week'),
                            lesson_number=suggestion.get('lesson_number'),
                            cabinet=suggestion.get('cabinet', '')
                        )
                        db.session.add(schedule_entry)
                        applied_count += 1
                        
                        # Логируем каждые 50 уроков
                        if (idx + 1) % 50 == 0:
                            logger.info(f"[4/5] Сохранено {idx + 1}/{len(result['suggestions'])} уроков...")
                    except Exception as e:
                        logger.error(f"[4/5] Ошибка при добавлении урока {idx+1}: {e}")
                        failed_count += 1
                        continue
                
                if skipped_duplicates > 0:
                    logger.warning(f"[4/5] Пропущено дубликатов: {skipped_duplicates}")
                
                db.session.commit()
                logger.info(f"[4/5] ✓ Сохранено {applied_count} уроков, ошибок: {failed_count}, пропущено дубликатов: {skipped_duplicates}")
                
                total_time = time.time() - start_time
                logger.info(f"[5/5] ✓ ГЕНЕРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
                logger.info(f"[5/5] Всего времени: {total_time:.2f} секунд")
                logger.info(f"[5/5] Размещено уроков: {applied_count}")
                if skipped_duplicates > 0:
                    logger.warning(f"[5/5] Пропущено дубликатов: {skipped_duplicates}")
                if result.get('warnings'):
                    logger.warning(f"[5/5] Предупреждения: {len(result['warnings'])}")
                    for warning in result['warnings']:
                        logger.warning(f"  - {warning}")
                logger.info("=" * 80)
                
                warnings_list = result.get('warnings', [])
                if skipped_duplicates > 0:
                    warnings_list.append(f'Пропущено {skipped_duplicates} дублирующих записей')
                
                return jsonify({
                    'success': True,
                    'message': f'Расписание успешно сгенерировано. Размещено уроков: {applied_count}',
                    'warnings': warnings_list,
                    'summary': result.get('summary', '')
                })
            else:
                error_msg = 'Не удалось сгенерировать расписание'
                if result.get('warnings'):
                    error_msg += f". Причины: {', '.join(result['warnings'][:3])}"
                
                logger.error(f"[3/5] ОШИБКА: {error_msg}")
                logger.error(f"[3/5] Summary: {result.get('summary', 'Нет предложений для размещения')}")
                
                return jsonify({
                    'success': False,
                    'error': error_msg,
                    'warnings': result.get('warnings', []),
                    'summary': result.get('summary', 'Нет предложений для размещения')
                }), 400
                
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error("=" * 80)
        logger.error(f"[КРИТИЧЕСКАЯ ОШИБКА] Ошибка при генерации расписания")
        logger.error(f"Тип ошибки: {type(e).__name__}")
        logger.error(f"Сообщение: {str(e)}")
        logger.error(f"Трассировка:")
        logger.error(error_trace)
        logger.error("=" * 80)
        
        # Формируем детальное сообщение об ошибке
        error_message = str(e)
        if len(error_message) > 500:
            error_message = error_message[:500] + "..."
        
        return jsonify({
            'success': False,
            'error': f'Ошибка при генерации расписания: {error_message}',
            'error_type': type(e).__name__,
            'warnings': [f'Тип ошибки: {type(e).__name__}']
        }), 500


# Остальные функции расписания будут добавлены позже
# Это включает:
# - get_teachers_for_subject
# - schedule_data
# - add_permanent_schedule
# - delete_permanent_schedule
# - clear_permanent_schedule
# - add_temporary_schedule
# - delete_temporary_schedule
# - temporary_schedule_latest_date
# - temporary_schedule_data
# - export_schedule_excel
# - copy_permanent_to_temporary
# - add_shift
# - save_schedule_settings

@schedule_bp.route('/admin/schedule/progress/<int:shift_id>')
@admin_required
def get_generation_progress(shift_id):
    """Возвращает текущий прогресс генерации для указанной смены"""
    progress = get_progress(shift_id)
    return jsonify(progress)


