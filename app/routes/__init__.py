"""
Регистрация всех маршрутов приложения
"""
from flask import Blueprint

# Создаем главный Blueprint для API маршрутов
api_bp = Blueprint('api', __name__)

# Импортируем и регистрируем все подмодули
from . import admin, teachers, subjects, schedule, telegram, cabinets, loads

# Регистрируем blueprint'ы
# ВАЖНО: Этот api_bp используется только если импортируется из app.routes
# В app.py импортируется api_bp из api.py, поэтому регистрация должна быть там
api_bp.register_blueprint(admin.admin_bp)
api_bp.register_blueprint(teachers.teachers_bp)
api_bp.register_blueprint(subjects.subjects_bp)
api_bp.register_blueprint(schedule.schedule_bp)
api_bp.register_blueprint(telegram.telegram_bp)
api_bp.register_blueprint(cabinets.cabinets_bp)
api_bp.register_blueprint(loads.loads_bp)

# Экспортируем главный blueprint
__all__ = ['api_bp']
