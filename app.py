# app.py
from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session, g
import os
import logging
from config import Config
from datetime import datetime, date

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Импорты для новой системы БД
from app.core.db_manager import init_system_db, db, school_db_context, create_school_database, clear_school_database, delete_school_database, switch_school_db, get_school_db_uri
# Для обратной совместимости
system_db = db
school_db = db
from app.models.system import School, User
# Импортируем модели школ
# Промежуточная таблица teacher_classes использует use_alter=True для отложенной проверки FK
from app.models.school import (
    Subject, ClassGroup, Teacher, ClassLoad, TeacherAssignment,
    PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings
)

from app.services.excel_loader import load_class_load_excel, load_teacher_assignments_excel
from app.services.telegram_bot import send_schedule_to_all_teachers, send_temporary_changes_to_all_teachers, send_schedule_to_teacher
from app.core.auth import login_manager, login_required, super_admin_required, admin_required, get_current_school_id, login_user, logout_user, current_user

# Импортируем Blueprint с API маршрутами
from api import api_bp

app = Flask(__name__)
app.config.from_object(Config)

# Инициализация новой системы БД
init_system_db(app)

# Отключаем автоматическую проверку внешних ключей при инициализации мапперов
# Это необходимо для промежуточной таблицы teacher_classes, которая находится в другой БД
# Используем use_alter=True в определении таблицы, что должно решить проблему

# Автоматическая миграция: добавление полей если их нет
def ensure_school_columns():
    """Проверяет и добавляет столбцы если их нет"""
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('schools')]
            
            if 'telegram_bot_token' not in columns:
                print("Добавляю поле telegram_bot_token в таблицу schools...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE schools ADD COLUMN telegram_bot_token VARCHAR(255)"))
                    conn.commit()
                print("✅ Поле telegram_bot_token успешно добавлено")
            
            if 'ai_api_key' not in columns:
                print("Добавляю поле ai_api_key в таблицу schools...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE schools ADD COLUMN ai_api_key VARCHAR(255)"))
                    conn.commit()
                print("✅ Поле ai_api_key успешно добавлено")
            
            if 'ai_model' not in columns:
                print("Добавляю поле ai_model в таблицу schools...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE schools ADD COLUMN ai_model VARCHAR(100)"))
                    conn.commit()
                print("✅ Поле ai_model успешно добавлено")
        except Exception as e:
            print(f"⚠️ Предупреждение при проверке столбцов schools: {e}")

def ensure_activation_columns():
    """
    Автоматическая миграция: добавляет поля activation_expires_at и activated_at в таблицу schools,
    если они отсутствуют
    """
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('schools')]
            
            if 'activation_expires_at' not in columns:
                print("Добавляю поле activation_expires_at в таблицу schools...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE schools ADD COLUMN activation_expires_at DATETIME"))
                    conn.commit()
                print("✅ Поле activation_expires_at успешно добавлено")
            
            if 'activated_at' not in columns:
                print("Добавляю поле activated_at в таблицу schools...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE schools ADD COLUMN activated_at DATETIME"))
                    conn.commit()
                print("✅ Поле activated_at успешно добавлено")
        except Exception as e:
            print(f"⚠️ Предупреждение при проверке столбцов активации: {e}")

def ensure_teacher_classes_table():
    """
    Автоматическая миграция: создает таблицу teacher_classes для связи учителей и классов,
    если она отсутствует в существующих БД школ
    """
    with app.app_context():
        try:
            from app.models.system import School
            from sqlalchemy import text, inspect
            from app.core.db_manager import get_school_db_uri, school_db_context
            
            schools = School.query.all()
            for school in schools:
                try:
                    with school_db_context(school.id):
                        inspector = inspect(db.engine)
                        tables = inspector.get_table_names()
                        
                        if 'teacher_classes' not in tables:
                            print(f"Добавляю таблицу teacher_classes в БД школы {school.id} ({school.name})...")
                            with db.engine.connect() as conn:
                                conn.execute(text("""
                                    CREATE TABLE IF NOT EXISTS teacher_classes (
                                        teacher_id INTEGER NOT NULL,
                                        class_id INTEGER NOT NULL,
                                        PRIMARY KEY (teacher_id, class_id),
                                        FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                                        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                                        UNIQUE (teacher_id, class_id)
                                    )
                                """))
                                conn.commit()
                            print(f"✅ Таблица teacher_classes успешно добавлена в БД школы {school.id}")
                        
                        # НЕ инициализируем relationship - используем прямые запросы к промежуточной таблице
                        # Это более надежно и не вызывает проблем с инициализацией FK
                except Exception as e:
                    # Выводим предупреждение только для реальных ошибок, не связанных с FK
                    if 'Foreign key' not in str(e) and 'NoReferencedTableError' not in str(type(e).__name__):
                        print(f"⚠️ Предупреждение при проверке таблицы teacher_classes для школы {school.id}: {e}")
        except Exception as e:
            print(f"⚠️ Предупреждение при проверке таблицы teacher_classes: {e}")

# Выполняем миграции после инициализации БД
ensure_school_columns()
ensure_activation_columns()
ensure_teacher_classes_table()

# Регистрируем Blueprint с API маршрутами
app.register_blueprint(api_bp)

# Регистрируем Blueprint для настроек Telegram
from app.routes.ai_settings import telegram_settings_bp
app.register_blueprint(telegram_settings_bp)

# Регистрируем Blueprint для расписания
from app.routes.schedule import schedule_bp
app.register_blueprint(schedule_bp)

# login_manager должен быть инициализирован после init_system_db
login_manager.init_app(app)

# Создаём папку для загрузок
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# === ИНИЦИАЛИЗАЦИЯ БД ===
@app.route('/init-db')  # можно вызвать один раз вручную
def init_db():
    with app.app_context():
        # Создаем системную БД
        db.create_all()
        
        # Создаем первого супер-админа, если его нет
        super_admin = User.query.filter_by(role='super_admin').first()
        if not super_admin:
            super_admin = User(
                username='admin',
                full_name='Супер-Администратор',
                role='super_admin',
                school_id=None,
                is_active=True
            )
            super_admin.set_password('admin123')
            db.session.add(super_admin)
            db.session.commit()
            return """
            <h1>✅ Системная база данных создана!</h1>
            <h2>Создан супер-администратор:</h2>
            <p><strong>Логин:</strong> admin</p>
            <p><strong>Пароль:</strong> admin123</p>
            <p>⚠️ <strong>ВАЖНО:</strong> Измените пароль после первого входа!</p>
            <hr>
            <p><a href="/login">Перейти к странице входа</a></p>
            """
        
        return """
        <h1>✅ Системная база данных создана!</h1>
        <p>Супер-администратор уже существует.</p>
        <p><a href="/login">Перейти к странице входа</a></p>
        """

# Автоматическое создание таблиц системной БД при первом запросе
@app.before_request
def before_request_func():
    # Инициализируем системную БД (только системные модели, без моделей школ)
    if not hasattr(app, 'system_db_initialized'):
        with app.app_context():
            # Создаем только системные таблицы (School, User)
            # Не создаем таблицы школ, так как они создаются отдельно для каждой школы
            from app.models.system import School, User
            try:
                # Создаем таблицы только для системных моделей (без bind_key)
                School.__table__.create(db.engine, checkfirst=True)
                User.__table__.create(db.engine, checkfirst=True)
            except Exception as e:
                # Игнорируем ошибки при создании таблиц (они могут уже существовать)
                print(f"Предупреждение при создании системных таблиц: {e}")
        app.system_db_initialized = True
    
    # Переключаемся на БД школы для текущего пользователя (только для админов школ)
    # Супер-админы используют school_db_context в каждом маршруте отдельно
    school_id = get_current_school_id()
    if school_id:
        # Убеждаемся, что БД школы существует и инициализирована
        db_path = os.path.join(os.path.dirname(__file__), 'databases', f'school_{school_id}.db')
        if not os.path.exists(db_path):
            # Создаем БД школы, если её нет
            try:
                create_school_database(school_id)
            except Exception as e:
                print(f"Ошибка при создании БД школы {school_id}: {e}")
        
        # Переключаемся на БД школы
        # Это делается здесь для базового переключения,
        # но в маршрутах всё равно нужно использовать school_db_context
        # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что bind 'school' настроен
        switch_school_db(school_id)
        
        # Дополнительная проверка: если bind 'school' все еще не настроен, настраиваем его
        from flask import current_app
        if 'SQLALCHEMY_BINDS' not in current_app.config:
            current_app.config['SQLALCHEMY_BINDS'] = {}
        if 'school' not in current_app.config['SQLALCHEMY_BINDS']:
            current_app.config['SQLALCHEMY_BINDS']['school'] = get_school_db_uri(school_id)
# =====================================

@app.route('/')
def public_index():
    return render_template('public/index.html')

# ==================== АВТОРИЗАЦИЯ ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('Введите логин и пароль', 'danger')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(username=username, is_active=True).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash(f'Добро пожаловать, {user.full_name}!', 'success')
            
            # Перенаправление в зависимости от роли
            if user.is_super_admin():
                return redirect(url_for('super_admin_dashboard'))
            else:
                return redirect(url_for('api.admin_index'))
        else:
            flash('Неверный логин или пароль', 'danger')
    
    return render_template('auth/login.html')

@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# ==================== СУПЕР-АДМИН ====================

@app.route('/super-admin')
@super_admin_required
def super_admin_dashboard():
    """Панель супер-администратора со статистикой"""
    # Системные данные
    # Показываем все школы, включая неактивные (для управления активацией)
    schools = School.query.order_by(School.created_at.desc()).all()
    
    # Общая статистика (только системные данные)
    # Показываем статистику только по активным школам
    stats = {
        'total_schools': School.query.filter_by(is_active=True).count(),
        'total_admins': User.query.filter_by(role='admin', is_active=True).count(),
        'total_teachers': 0,
        'total_classes': 0,
        'total_subjects': 0,
        'total_shifts': 0,
        'total_permanent_schedules': 0,
        'total_temporary_schedules': 0,
        'teachers_with_telegram': 0,
        'schools_stats': []
    }
    
    # Собираем статистику по каждой школе
    for school in schools:
        try:
            with school_db_context(school.id):
                school_stats = {
                    'school_id': school.id,
                    'school_name': school.name,
                    'teachers': db.session.query(Teacher).count(),
                    'classes': db.session.query(ClassGroup).count(),
                    'subjects': db.session.query(Subject).count(),
                    'shifts': db.session.query(Shift).count(),
                    'permanent_schedules': db.session.query(PermanentSchedule).count(),
                    'temporary_schedules': db.session.query(TemporarySchedule).count(),
                    'teachers_with_telegram': db.session.query(Teacher).filter(Teacher.telegram_id.isnot(None)).count()
                }
                stats['schools_stats'].append(school_stats)
                
                # Суммируем общую статистику
                stats['total_teachers'] += school_stats['teachers']
                stats['total_classes'] += school_stats['classes']
                stats['total_subjects'] += school_stats['subjects']
                stats['total_shifts'] += school_stats['shifts']
                stats['total_permanent_schedules'] += school_stats['permanent_schedules']
                stats['total_temporary_schedules'] += school_stats['temporary_schedules']
                stats['teachers_with_telegram'] += school_stats['teachers_with_telegram']
        except Exception as e:
            # Если БД школы не существует, пропускаем
            print(f"Ошибка при получении статистики для школы {school.id}: {e}")
            continue
    
    # Расширенная статистика по каждой школе (обновляем существующие записи)
    for i, school in enumerate(schools):
        # Получаем всех админов школы с подробной информацией (системная БД)
        school_admins = User.query.filter_by(school_id=school.id, role='admin', is_active=True).all()
        
        # Получаем статистику из БД школы
        try:
            with school_db_context(school.id):
                school_shifts = db.session.query(Shift).all()
                shift_ids = [s.id for s in school_shifts]
                
                total_permanent = db.session.query(PermanentSchedule).filter(PermanentSchedule.shift_id.in_(shift_ids)).count() if shift_ids else 0
                total_temporary = db.session.query(TemporarySchedule).count()
                
                school_teachers = db.session.query(Teacher).all()
                teachers_with_telegram = len([t for t in school_teachers if t.telegram_id])
                
                school_classes = db.session.query(ClassGroup).all()
                class_ids = [c.id for c in school_classes]
                total_class_loads = db.session.query(ClassLoad).filter(ClassLoad.class_id.in_(shift_ids)).count() if class_ids and shift_ids else 0
                
                school_subjects_count = db.session.query(Subject).count()
                avg_teachers_per_class = round(len(school_teachers) / len(school_classes), 1) if school_classes else 0
                avg_subjects_per_class = round(school_subjects_count / len(school_classes), 1) if school_classes and school_subjects_count > 0 else 0
                
                # Обновляем или создаем статистику школы
                if i < len(stats['schools_stats']):
                    stats['schools_stats'][i].update({
                        'school': school,
                        'school_data': {
                            'id': school.id,
                            'name': school.name,
                            'created_at': school.created_at.isoformat() if school.created_at else None
                        },
                        'teachers': len(school_teachers),
                        'classes': len(school_classes),
                        'subjects': school_subjects_count,
                        'shifts': len(school_shifts),
                        'admins': len(school_admins),
                        'admin_list': [{'id': a.id, 'username': a.username, 'full_name': a.full_name, 'created_at': a.created_at.isoformat() if a.created_at else None} for a in school_admins],
                        'permanent_schedules': total_permanent,
                        'temporary_schedules': total_temporary,
                        'teachers_with_telegram': teachers_with_telegram,
                        'total_class_loads': total_class_loads,
                        'avg_teachers_per_class': avg_teachers_per_class,
                        'avg_subjects_per_class': avg_subjects_per_class
                    })
                else:
                    school_stats = {
                        'school': school,
                        'school_data': {
                            'id': school.id,
                            'name': school.name,
                            'created_at': school.created_at.isoformat() if school.created_at else None
                        },
                        'teachers': len(school_teachers),
                        'classes': len(school_classes),
                        'subjects': school_subjects_count,
                        'shifts': len(school_shifts),
                        'admins': len(school_admins),
                        'admin_list': [{'id': a.id, 'username': a.username, 'full_name': a.full_name, 'created_at': a.created_at.isoformat() if a.created_at else None} for a in school_admins],
                        'permanent_schedules': total_permanent,
                        'temporary_schedules': total_temporary,
                        'teachers_with_telegram': teachers_with_telegram,
                        'total_class_loads': total_class_loads,
                        'avg_teachers_per_class': avg_teachers_per_class,
                        'avg_subjects_per_class': avg_subjects_per_class
                    }
                    stats['schools_stats'].append(school_stats)
        except Exception as e:
            print(f"Ошибка при получении статистики для школы {school.id}: {e}")
            # Добавляем базовую статистику без данных из БД школы
            if i >= len(stats['schools_stats']):
                stats['schools_stats'].append({
                    'school': school,
                    'school_data': {
                        'id': school.id,
                        'name': school.name,
                        'created_at': school.created_at.isoformat() if school.created_at else None
                    },
                    'teachers': 0,
                    'classes': 0,
                    'subjects': 0,
                    'shifts': 0,
                    'admins': len(school_admins),
                    'admin_list': [{'id': a.id, 'username': a.username, 'full_name': a.full_name, 'created_at': a.created_at.isoformat() if a.created_at else None} for a in school_admins],
                    'permanent_schedules': 0,
                    'temporary_schedules': 0,
                    'teachers_with_telegram': 0,
                    'total_class_loads': 0,
                    'avg_teachers_per_class': 0,
                    'avg_subjects_per_class': 0
                })
    
    # Подготовка данных для JavaScript (сериализуем объекты для JSON)
    schools_stats_for_js = []
    for stat in stats['schools_stats']:
        js_stat = {
            'school': {
                'id': stat['school'].id,
                'name': stat['school'].name,
                'created_at': stat['school'].created_at.isoformat() if stat['school'].created_at else None
            },
            'teachers': stat['teachers'],
            'classes': stat['classes'],
            'subjects': stat['subjects'],
            'shifts': stat['shifts'],
            'admins': stat['admins'],
            'admin_list': stat['admin_list'],
            'permanent_schedules': stat['permanent_schedules'],
            'temporary_schedules': stat['temporary_schedules'],
            'teachers_with_telegram': stat['teachers_with_telegram'],
            'total_class_loads': stat['total_class_loads'],
            'avg_teachers_per_class': stat['avg_teachers_per_class'],
            'avg_subjects_per_class': stat['avg_subjects_per_class']
        }
        schools_stats_for_js.append(js_stat)
    
    return render_template('super_admin/dashboard.html', stats=stats, schools=schools, schools_stats_for_js=schools_stats_for_js)

@app.route('/super-admin/schools/create', methods=['POST'])
@super_admin_required
def create_school():
    """Создать новую школу"""
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'success': False, 'error': 'Название школы обязательно'}), 400
    
    try:
        # Создаем школу в системной БД
        school = School(name=name, is_active=True)
        db.session.add(school)
        db.session.commit()
        
        # Создаем БД для новой школы (внутри функции используется school_db_context)
        create_school_database(school.id)
        
        # Создаем первую смену для школы
        # school_db_context гарантирует правильную регистрацию и переключение БД
        with school_db_context(school.id):
            # Убеждаемся, что БД правильно переключена
            first_shift = Shift(name='Первая смена', is_active=True)
            db.session.add(first_shift)
            db.session.commit()
        
        return jsonify({'success': True, 'school_id': school.id, 'school_name': school.name})
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        print(f"Ошибка при создании школы: {error_trace}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/admins/create', methods=['POST'])
@super_admin_required
def create_school_admin(school_id):
    """Создать администратора для школы"""
    school = School.query.get_or_404(school_id)
    data = request.get_json()
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    full_name = data.get('full_name', '').strip()
    
    if not username or not password or not full_name:
        return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400
    
    # Проверяем, не существует ли пользователь с таким username
    existing = User.query.filter_by(username=username).first()
    if existing:
        return jsonify({'success': False, 'error': 'Пользователь с таким логином уже существует'}), 400
    
    try:
        admin = User(
            username=username,
            full_name=full_name,
            role='admin',
            school_id=school.id,
            is_active=True
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return jsonify({'success': True, 'admin_id': admin.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/admins/<int:admin_id>/delete', methods=['POST'])
@super_admin_required
def delete_school_admin(school_id, admin_id):
    """Полностью удалить администратора школы"""
    school = School.query.get_or_404(school_id)
    admin = User.query.filter_by(id=admin_id, school_id=school.id, role='admin').first()
    
    if not admin:
        return jsonify({'success': False, 'error': 'Администратор не найден'}), 404
    
    try:
        # Полностью удаляем администратора из БД
        db.session.delete(admin)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Администратор успешно удален'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/clear', methods=['POST'])
@super_admin_required
def clear_school_data(school_id):
    """Очистить все данные школы (очистить БД школы)"""
    school = School.query.get_or_404(school_id)
    data = request.get_json()
    confirm_text = data.get('confirm', '').strip() if data else ''
    
    # Проверка подтверждения
    if confirm_text != school.name:
        return jsonify({'success': False, 'error': f'Для подтверждения введите название школы: {school.name}'}), 400
    
    try:
        # Используем новую функцию очистки БД школы
        if clear_school_database(school_id):
            # Деактивируем администраторов (не удаляем, чтобы была история)
            User.query.filter_by(school_id=school.id, role='admin').update({'is_active': False})
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Все данные школы "{school.name}" успешно удалены'
            })
        else:
            return jsonify({'success': False, 'error': 'Ошибка при очистке БД школы'}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/telegram-token', methods=['POST'])
@super_admin_required
def update_school_telegram_token(school_id):
    """Обновить токен Telegram бота для школы"""
    school = School.query.get_or_404(school_id)
    data = request.get_json()
    
    telegram_token = data.get('telegram_token', '').strip() if data else ''
    
    # Если токен пустой, удаляем его (будет использоваться общий токен)
    if not telegram_token:
        school.telegram_bot_token = None
        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Токен Telegram бота удален (будет использоваться общий)',
            'bot_info': None
        })
    
    # Проверяем формат токена (должен быть вида "123456:ABC-DEF...")
    if ':' not in telegram_token or len(telegram_token) < 20:
        return jsonify({'success': False, 'error': 'Неверный формат токена Telegram бота'}), 400
    
    # Проверяем токен через Telegram API
    try:
        import requests
        from flask import current_app
        api_url = current_app.config.get('TELEGRAM_API_URL', 'https://api.telegram.org/bot')
        test_url = f"{api_url}{telegram_token}/getMe"
        response = requests.get(test_url, timeout=5)
        
        if response.status_code != 200:
                return jsonify({
                    'success': False, 
                'error': f'Неверный токен. Telegram API вернул ошибку: {response.status_code}'
                }), 400
            
        result = response.json()
        if not result.get('ok'):
            error_desc = result.get('description', 'Неизвестная ошибка')
            return jsonify({
                'success': False, 
                'error': f'Неверный токен: {error_desc}'
            }), 400
            
        # Токен валидный, сохраняем информацию о боте
        bot_info = result.get('result', {})
        bot_username = bot_info.get('username', '')
        bot_first_name = bot_info.get('first_name', '')
        
        school.telegram_bot_token = telegram_token
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Токен Telegram бота успешно обновлен и проверен',
            'bot_info': {
                'username': bot_username,
                'first_name': bot_first_name,
                'id': bot_info.get('id')
            }
        })
    except requests.exceptions.RequestException as e:
                return jsonify({
                    'success': False, 
            'error': f'Ошибка при проверке токена: {str(e)}'
        }), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/telegram-token/check', methods=['GET'])
@super_admin_required
def check_school_telegram_token(school_id):
    """Проверить текущий токен Telegram бота школы и получить информацию о боте"""
    school = School.query.get_or_404(school_id)
    
    if not school.telegram_bot_token:
        return jsonify({
            'success': False,
            'has_token': False,
            'message': 'Токен не настроен'
        })
    
    try:
        import requests
        from flask import current_app
        api_url = current_app.config.get('TELEGRAM_API_URL', 'https://api.telegram.org/bot')
        test_url = f"{api_url}{school.telegram_bot_token}/getMe"
        response = requests.get(test_url, timeout=5)
        
        if response.status_code != 200:
                return jsonify({
                    'success': False, 
                'has_token': True,
                'error': f'Токен недействителен. Telegram API вернул ошибку: {response.status_code}'
            })
        
        result = response.json()
        if not result.get('ok'):
                    return jsonify({
                        'success': False, 
                'has_token': True,
                'error': result.get('description', 'Неизвестная ошибка')
            })
        
        bot_info = result.get('result', {})
        return jsonify({
            'success': True,
            'has_token': True,
            'bot_info': {
                'username': bot_info.get('username', ''),
                'first_name': bot_info.get('first_name', ''),
                'id': bot_info.get('id')
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'has_token': True,
            'error': str(e)
        })

@app.route('/super-admin/schools/<int:school_id>/activate', methods=['POST'])
@super_admin_required
def activate_school(school_id):
    """Активировать школу с таймером (на указанное количество месяцев/дней)"""
    school = School.query.get_or_404(school_id)
    data = request.get_json()
    
    # Получаем параметры активации
    months = data.get('months', 0) if data else 0
    days = data.get('days', 0) if data else 0
    
    if months < 0 or days < 0:
        return jsonify({'success': False, 'error': 'Количество месяцев и дней должно быть неотрицательным'}), 400
    
    if months == 0 and days == 0:
        # Бессрочная активация
        school.is_active = True
        school.activation_expires_at = None
        school.activated_at = datetime.utcnow()
    else:
        # Активация с таймером
        from datetime import timedelta
        total_days = (months * 30) + days  # Приблизительно 30 дней в месяце
        school.is_active = True
        school.activation_expires_at = datetime.utcnow() + timedelta(days=total_days)
        school.activated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        expires_text = "бессрочно" if school.activation_expires_at is None else school.activation_expires_at.strftime("%d.%m.%Y")
        return jsonify({
            'success': True,
            'message': f'Школа "{school.name}" активирована до {expires_text}',
            'activation_status': school.get_activation_status()
            })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/deactivate', methods=['POST'])
@super_admin_required
def deactivate_school(school_id):
    """Деактивировать школу"""
    school = School.query.get_or_404(school_id)
    
    try:
        school.is_active = False
        # Не сбрасываем activation_expires_at, чтобы сохранить историю
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Школа "{school.name}" деактивирована',
            'activation_status': school.get_activation_status()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/super-admin/schools/<int:school_id>/delete', methods=['POST'])
@super_admin_required
def delete_school(school_id):
    """Полностью удалить школу, её БД и всех админов"""
    school = School.query.get_or_404(school_id)
    data = request.get_json()
    confirm_text = data.get('confirm', '').strip() if data else ''
    
    # Проверка подтверждения
    if confirm_text != school.name:
        return jsonify({'success': False, 'error': f'Для подтверждения введите название школы: {school.name}'}), 400
    
    try:
        school_name = school.name
        
        # 1. Удаляем всех админов школы
        admins = User.query.filter_by(school_id=school.id, role='admin').all()
        for admin in admins:
            db.session.delete(admin)
        db.session.flush()
        
        # 2. Удаляем БД школы (файл БД)
        if not delete_school_database(school_id):
            # Если БД не существует - это не критично, продолжаем
            print(f"Предупреждение: БД школы {school_id} не найдена или уже удалена")
        
        # 3. Удаляем школу из системной БД
        db.session.delete(school)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Школа "{school_name}" и все её данные успешно удалены'
        })
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== АДМИН ПАНЕЛЬ ====================
# Все маршруты админ-панели перенесены в api.py (Blueprint)

# ВРЕМЕННЫЙ РОУТ ДЛЯ ПРОВЕРКИ СТРУКТУРЫ EXCEL ФАЙЛОВ (удалить после проверки)
@app.route('/admin/test-excel-structure')
def test_excel_structure():
    """Временный роут для проверки структуры Excel файлов"""
    import pandas as pd
    
    file1_info = {}
    file2_info = {}
    
    try:
        # Проверяем файл 1
        df1 = pd.read_excel('Часы_Класс_Предмет.xlsx')
        file1_info = {
            'success': True,
            'columns': list(df1.columns),
            'rows': df1.shape[0],
            'cols': df1.shape[1],
            'first_rows': df1.head(15).to_dict('records')
        }
    except Exception as e:
        file1_info = {'success': False, 'error': str(e)}
    
    try:
        # Проверяем файл 2
        df2 = pd.read_excel('Учителя_Предмет.xlsx')
        file2_info = {
            'success': True,
            'columns': list(df2.columns),
            'rows': df2.shape[0],
            'cols': df2.shape[1],
            'first_rows': df2.head(15).to_dict('records'),
            'sample_cells': {}
        }
        # Показываем несколько примеров ячеек
        if df2.shape[0] > 0 and df2.shape[1] > 1:
            for i in range(min(3, df2.shape[0])):
                for j in range(min(5, df2.shape[1])):
                    cell_val = df2.iloc[i, j]
                    if pd.notna(cell_val):
                        file2_info['sample_cells'][f'[{i},{j}]'] = str(cell_val)[:100]
    except Exception as e:
        file2_info = {'success': False, 'error': str(e)}
    
    return render_template('admin/test_excel.html', 
                         file1=file1_info, 
                         file2=file2_info)

if __name__ == '__main__':
    import sys
    app.run(debug=True)