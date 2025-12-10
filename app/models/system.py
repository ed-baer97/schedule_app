"""
Системные модели - хранятся в системной БД (system.db)
Включают: School, User
"""
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import ForeignKey
from app.core.db_manager import db

class School(db.Model):
    """Модель школы"""
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    # Telegram Bot Token для школы (если None, используется общий токен из config)
    telegram_bot_token = db.Column(db.String(255), nullable=True)
    # AI API настройки для школы (если None, используются общие настройки из config)
    ai_api_key = db.Column(db.String(255), nullable=True)  # API ключ для AI модели
    ai_model = db.Column(db.String(100), nullable=True)  # Выбранная AI модель (qwen, deepseek, openai, mistral, etc.)
    # Управление активацией с таймером
    activation_expires_at = db.Column(db.DateTime, nullable=True)  # Дата истечения активации
    activated_at = db.Column(db.DateTime, nullable=True)  # Дата последней активации
    
    # Связи (только для системной БД)
    users = db.relationship('User', backref='school', lazy=True, cascade='all, delete-orphan')
    
    def is_actually_active(self):
        """Проверяет, активна ли школа с учетом таймера"""
        if not self.is_active:
            return False
        if self.activation_expires_at is None:
            # Если таймер не установлен, школа активна бессрочно (если is_active=True)
            return True
        # Проверяем, не истек ли срок активации
        from datetime import datetime
        return datetime.utcnow() < self.activation_expires_at
    
    def get_activation_status(self):
        """Возвращает статус активации для отображения"""
        if not self.is_active:
            return {'status': 'inactive', 'text': 'Деактивирована', 'color': 'danger'}
        if self.activation_expires_at is None:
            return {'status': 'active_unlimited', 'text': 'Активна (бессрочно)', 'color': 'success'}
        from datetime import datetime
        if datetime.utcnow() >= self.activation_expires_at:
            return {'status': 'expired', 'text': 'Срок истек', 'color': 'danger'}
        # Вычисляем оставшиеся дни
        remaining = (self.activation_expires_at - datetime.utcnow()).days
        if remaining <= 7:
            return {'status': 'expiring_soon', 'text': f'Истекает через {remaining} дн.', 'color': 'warning'}
        return {'status': 'active', 'text': f'Активна до {self.activation_expires_at.strftime("%d.%m.%Y")}', 'color': 'success'}
    
    def __repr__(self):
        return f'<School {self.name}>'

class User(UserMixin, db.Model):
    """Модель пользователя (администраторы)"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'super_admin' или 'admin'
    school_id = db.Column(db.Integer, ForeignKey('schools.id'), nullable=True)  # NULL для super_admin
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        """Установить пароль"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Проверить пароль"""
        return check_password_hash(self.password_hash, password)
    
    def is_super_admin(self):
        """Проверить, является ли пользователь супер-админом"""
        return self.role == 'super_admin'
    
    def is_admin(self):
        """Проверить, является ли пользователь админом школы"""
        return self.role == 'admin'
    
    def __repr__(self):
        return f'<User {self.username}>'

