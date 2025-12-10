"""
Модуль авторизации для работы с Flask-Login
"""
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask import redirect, url_for, flash
from functools import wraps
from app.models.system import User
from app.core.db_manager import db

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Загрузка пользователя для Flask-Login"""
    try:
        return db.session.get(User, int(user_id))
    except Exception as e:
        # Игнорируем ошибки при инициализации мапперов (например, при проверке FK промежуточной таблицы)
        # Это может произойти при первом обращении к пользователю, если мапперы еще не полностью инициализированы
        print(f"Предупреждение при загрузке пользователя: {e}")
        # Пытаемся загрузить пользователя напрямую через запрос
        try:
            return User.query.get(int(user_id))
        except:
            return None

def super_admin_required(f):
    """Декоратор для проверки прав супер-админа"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_super_admin():
            flash('Доступ запрещен. Требуются права супер-администратора.', 'danger')
            return redirect(url_for('admin_index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Декоратор для проверки прав админа (админ школы или супер-админ)"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not (current_user.is_admin() or current_user.is_super_admin()):
            flash('Доступ запрещен. Требуются права администратора.', 'danger')
            return redirect(url_for('admin_index'))
        
        # Проверяем активность школы для админов (не для супер-админов)
        if current_user.is_admin() and current_user.school_id:
            from app.models.system import School
            school = School.query.get(current_user.school_id)
            if school and not school.is_actually_active():
                flash('Доступ к школе ограничен. Срок активации истек или школа деактивирована. Обратитесь к супер-администратору.', 'warning')
                return redirect(url_for('logout'))
        
        return f(*args, **kwargs)
    return decorated_function

def get_current_school_id():
    """Получить school_id текущего пользователя"""
    if current_user.is_authenticated:
        if current_user.is_super_admin():
            # Супер-админ может выбрать школу через параметр
            return None  # Будет передаваться через параметры
        elif current_user.is_admin():
            return current_user.school_id
    return None

# Экспортируем login_user и logout_user для удобства
__all__ = [
    'login_manager', 'login_required', 'super_admin_required', 
    'admin_required', 'get_current_school_id', 'login_user', 
    'logout_user', 'current_user'
]

