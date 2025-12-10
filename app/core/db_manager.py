"""
Менеджер баз данных для разделения системной БД и БД школ
РАДИКАЛЬНОЕ РЕШЕНИЕ: Используем ОДИН экземпляр SQLAlchemy для обеих БД
"""
import os
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from sqlalchemy import create_engine
from contextlib import contextmanager
from functools import wraps
from flask import g, has_request_context, current_app, has_app_context

# ОДИН экземпляр SQLAlchemy для всех БД
# Системные модели используют основную БД (без bind)
# Модели школ используют bind 'school' (динамически переключается)

class DynamicSession(Session):
    """
    Кастомная сессия, которая правильно обрабатывает динамические binds
    """
    def get_bind(self, mapper=None, clause=None, **kwargs):
        """
        Переопределяем get_bind для правильной обработки динамических binds
        Flask-SQLAlchemy вызывает этот метод через session для получения правильного engine
        """
        from flask import current_app, g
        
        # Определяем bind из mapper, если не указан явно
        bind = None
        if mapper is not None:
            # Получаем bind_key из mapper
            bind_key = getattr(mapper.class_, '__bind_key__', None)
            if bind_key:
                bind = bind_key
        
        # Если указан bind 'school', используем его из конфигурации
        if bind == 'school':
            # КРИТИЧЕСКИ ВАЖНО: Проверяем, есть ли school_id в контексте Flask (g)
            # Если есть, используем его для получения правильного URI
            school_id = None
            if has_request_context() and hasattr(g, 'school_id'):
                school_id = g.school_id
            
            binds = current_app.config.get('SQLALCHEMY_BINDS', {})
            
            # Если bind не найден в конфигурации, но есть school_id в контексте,
            # устанавливаем bind динамически
            if 'school' not in binds:
                if school_id is not None:
                    # Устанавливаем bind динамически из school_id
                    db_uri = get_school_db_uri(school_id)
                    if 'SQLALCHEMY_BINDS' not in current_app.config:
                        current_app.config['SQLALCHEMY_BINDS'] = {}
                    current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
                    binds = current_app.config.get('SQLALCHEMY_BINDS', {})
                else:
                    raise RuntimeError(
                        f"Bind 'school' отсутствует в SQLALCHEMY_BINDS и school_id не найден в контексте. "
                        f"Текущая конфигурация: {binds}. "
                        f"Убедитесь, что вы используете school_db_context."
                    )
            
            # Получаем engine через наш кастомный SQLAlchemy экземпляр
            # Используем get_engine из db, который правильно обработает динамический bind
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                sqlalchemy_ext = current_app.extensions['sqlalchemy']
                # Проверяем кэш engines
                if hasattr(sqlalchemy_ext, 'engines') and 'school' in sqlalchemy_ext.engines:
                    return sqlalchemy_ext.engines['school']
                if hasattr(sqlalchemy_ext, '_engines') and 'school' in sqlalchemy_ext._engines:
                    return sqlalchemy_ext._engines['school']
                
                # Если engine не найден в кэше, создаем его через db.get_engine
                # Это вызовет наш кастомный get_engine метод
                engine = sqlalchemy_ext.get_engine(current_app, bind='school')
                return engine
        
        # Для остальных случаев используем стандартное поведение
        return super().get_bind(mapper=mapper, clause=clause, **kwargs)

class DynamicSQLAlchemy(SQLAlchemy):
    """
    Кастомный SQLAlchemy, который правильно обрабатывает динамические binds
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Кэш для engines bind 'school' (ключ - URI БД)
        self._school_engines = {}
    
    def _make_engine_cache(self, app):
        """
        Переопределяем создание кэша engines, чтобы он всегда включал 'school' bind
        если он доступен через контекст
        """
        cache = super()._make_engine_cache(app)
        
        # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что 'school' bind всегда в конфигурации
        # даже если он не был установлен заранее
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, 'school_id') and g.school_id is not None:
            if 'SQLALCHEMY_BINDS' not in app.config:
                app.config['SQLALCHEMY_BINDS'] = {}
            if 'school' not in app.config['SQLALCHEMY_BINDS']:
                db_uri = get_school_db_uri(g.school_id)
                app.config['SQLALCHEMY_BINDS']['school'] = db_uri
        
        return cache
    
    def make_session(self, options):
        """
        Создаем кастомную сессию с правильной обработкой binds
        """
        # Используем наш кастомный класс сессии
        # Flask-SQLAlchemy передает options как словарь
        return DynamicSession(self, **options)
    
    def get_engine(self, app=None, bind=None):
        """
        Переопределяем get_engine для правильной обработки динамических binds
        Это критически важно - Flask-SQLAlchemy проверяет binds здесь
        """
        from flask import current_app
        
        # Используем current_app, если app не указан
        if app is None:
            app = current_app
        
        # Если указан bind 'school', обрабатываем его напрямую
        if bind == 'school':
            binds = app.config.get('SQLALCHEMY_BINDS', {})
            if 'school' not in binds:
                raise RuntimeError(
                    f"Bind 'school' отсутствует в SQLALCHEMY_BINDS. "
                    f"Текущая конфигурация: {binds}"
                )
            
            db_uri = binds['school']
            
            # Проверяем, есть ли engine в кэше для этого URI
            if db_uri in self._school_engines:
                return self._school_engines[db_uri]
            
            # Создаем новый engine для этого URI
            from sqlalchemy import create_engine
            engine = create_engine(db_uri, echo=False)
            self._school_engines[db_uri] = engine
            return engine
        
        # Для остальных случаев используем стандартное поведение
        return super().get_engine(app=app, bind=bind)
    
    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        """
        Переопределяем get_bind для правильной обработки динамических binds
        Flask-SQLAlchemy вызывает этот метод для получения правильного engine
        """
        from flask import current_app, g
        
        # Определяем bind из mapper или clause, если не указан явно
        if bind is None:
            if mapper is not None:
                # Получаем bind_key из mapper
                bind_key = getattr(mapper.class_, '__bind_key__', None)
                if bind_key:
                    bind = bind_key
            elif clause is not None:
                # Пытаемся определить bind из clause (таблицы)
                if hasattr(clause, 'table'):
                    bind_key = getattr(clause.table, 'bind_key', None)
                    if bind_key:
                        bind = bind_key
        
        # Если указан bind 'school', используем его из конфигурации
        if bind == 'school':
            # КРИТИЧЕСКИ ВАЖНО: Проверяем, есть ли school_id в контексте Flask (g)
            # Если есть, используем его для получения правильного URI
            school_id = None
            if has_request_context() and hasattr(g, 'school_id'):
                school_id = g.school_id
            
            binds = current_app.config.get('SQLALCHEMY_BINDS', {})
            
            # Если bind не найден в конфигурации, но есть school_id в контексте,
            # устанавливаем bind динамически
            if 'school' not in binds:
                if school_id is not None:
                    # Устанавливаем bind динамически из school_id
                    db_uri = get_school_db_uri(school_id)
                    if 'SQLALCHEMY_BINDS' not in current_app.config:
                        current_app.config['SQLALCHEMY_BINDS'] = {}
                    current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
                    binds = current_app.config.get('SQLALCHEMY_BINDS', {})
                else:
                    raise RuntimeError(
                        f"Bind 'school' отсутствует в SQLALCHEMY_BINDS и school_id не найден в контексте. "
                        f"Текущая конфигурация: {binds}. "
                        f"Убедитесь, что вы используете school_db_context."
                    )
            
            db_uri = binds['school']
            
            # Проверяем, есть ли engine в кэше для этого URI
            if db_uri in self._school_engines:
                return self._school_engines[db_uri]
            
            # Создаем новый engine для этого URI
            from sqlalchemy import create_engine
            engine = create_engine(db_uri, echo=False)
            self._school_engines[db_uri] = engine
            return engine
        
        # Для остальных случаев используем стандартное поведение
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)
    
    def clear_school_engine_cache(self, db_uri=None):
        """
        Очистить кэш engines для bind 'school'
        Если указан db_uri, очищает только для этого URI, иначе очищает весь кэш
        """
        if db_uri:
            if db_uri and db_uri in self._school_engines:
                # Закрываем соединение перед удалением
                try:
                    self._school_engines[db_uri].dispose()
                    del self._school_engines[db_uri]
                except KeyError:
                    # Ключ уже был удален - это нормально
                    pass
            # Если ключа нет в кэше, это нормально - просто игнорируем
        else:
            # Очищаем весь кэш
            for engine in self._school_engines.values():
                engine.dispose()
            self._school_engines.clear()

db = DynamicSQLAlchemy()

# Для обратной совместимости (постепенно заменим на db)
system_db = db
school_db = db

# BASE_DIR указывает на корень проекта (на уровень выше app/core/)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def get_system_db_path():
    """Получить путь к системной БД"""
    return os.path.join(BASE_DIR, 'system.db')

def get_school_db_path(school_id):
    """Получить путь к БД школы"""
    return os.path.join(BASE_DIR, 'databases', f'school_{school_id}.db')

def get_system_db_uri():
    """Получить URI системной БД"""
    return f"sqlite:///{get_system_db_path()}"

def get_school_db_uri(school_id):
    """Получить URI БД школы"""
    return f"sqlite:///{get_school_db_path(school_id)}"

def init_system_db(app):
    """Инициализировать БД (один экземпляр для всех БД)"""
    # Настраиваем конфигурацию
    app.config['SQLALCHEMY_DATABASE_URI'] = get_system_db_uri()
    
    # КРИТИЧЕСКИ ВАЖНО: Всегда инициализируем SQLALCHEMY_BINDS
    if 'SQLALCHEMY_BINDS' not in app.config:
        app.config['SQLALCHEMY_BINDS'] = {}
    
    # Устанавливаем начальное значение для bind 'school' (будет переключаться динамически)
    # Используем временный URI - он будет переключен при первом использовании school_db_context
    # НЕ создаем файл school_0.db - используем только в памяти URI
    temp_db_path = os.path.join(BASE_DIR, 'databases', 'temp_school.db')
    app.config['SQLALCHEMY_BINDS']['school'] = f"sqlite:///{temp_db_path}"
    
    # Инициализируем ОДИН экземпляр SQLAlchemy
    # Он будет работать и с основной БД, и с bind 'school'
    try:
        db.init_app(app)
    except RuntimeError as e:
        error_msg = str(e).lower()
        # Если уже зарегистрирован, это нормально
        if 'already been registered' not in error_msg and 'already been initialized' not in error_msg:
            raise
    
    # Создаем директорию для БД школ
    databases_dir = os.path.join(BASE_DIR, 'databases')
    os.makedirs(databases_dir, exist_ok=True)
    
    # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что bind 'school' всегда в конфигурации
    # Это гарантирует, что Flask-SQLAlchemy всегда найдет bind для моделей с __bind_key__ = 'school'
    if 'school' not in app.config.get('SQLALCHEMY_BINDS', {}):
        temp_db_path = os.path.join(BASE_DIR, 'databases', 'temp_school.db')
        app.config['SQLALCHEMY_BINDS']['school'] = f"sqlite:///{temp_db_path}"
    
    # КРИТИЧЕСКИ ВАЖНО: Monkey patch для _clause_to_engine, чтобы он проверял g.school_id
    # перед проверкой наличия bind в конфигурации
    try:
        from flask_sqlalchemy.session import _clause_to_engine as original_clause_to_engine
        from flask import g, has_request_context
        import inspect
        
        # Получаем сигнатуру оригинальной функции для совместимости
        sig = inspect.signature(original_clause_to_engine)
        
        def patched_clause_to_engine(*args, **kwargs):
            """
            Патч для _clause_to_engine, который проверяет g.school_id перед проверкой bind
            Использует *args, **kwargs для совместимости с разными версиями Flask-SQLAlchemy
            
            ВАЖНО: Flask-SQLAlchemy вызывает эту функцию как _clause_to_engine(table, engines)
            где table = mapper.local_table
            """
            # Определяем параметры из args/kwargs
            # Flask-SQLAlchemy обычно вызывает: _clause_to_engine(table, engines) или _clause_to_engine(table, engines, app)
            table = args[0] if len(args) > 0 else kwargs.get('table')
            engines = args[1] if len(args) > 1 else kwargs.get('engines')
            app = args[2] if len(args) > 2 else kwargs.get('app', None)
            
            # Если table не определен, пробуем получить из kwargs
            if table is None:
                table = kwargs.get('table')
            if engines is None:
                engines = kwargs.get('engines')
            if app is None:
                app = kwargs.get('app', None)
            
            # Получаем bind_key из таблицы
            bind_key = None
            if table is not None:
                # Пробуем получить bind_key из таблицы
                bind_key = getattr(table, 'bind_key', None)
                
                # Если bind_key не найден, пробуем определить по имени таблицы
                # Это быстрый способ для таблиц моделей школ
                if not bind_key:
                    table_name = getattr(table, 'name', None)
                    if table_name:
                        # Таблицы для моделей школ обычно имеют определенные имена
                        school_table_names = [
                            'ai_conversations', 'ai_conversation_messages',
                            'subjects', 'teachers', 'classes', 'class_load', 
                            'teacher_assignments', 'permanent_schedule', 'temporary_schedule',
                            'shifts', 'schedule_settings', 'prompt_class_subjects',
                            'prompt_class_subject_teachers', 'teacher_classes',
                            'cabinets', 'cabinet_teachers', 'subject_cabinets'
                        ]
                        if table_name in school_table_names or any(table_name.startswith(prefix) for prefix in ['ai_', 'prompt_']):
                            # Это таблица модели школы, устанавливаем bind_key = 'school'
                            bind_key = 'school'
                
                # Если bind_key не найден в таблице, пробуем получить из mapper через table
                if not bind_key:
                    # table может иметь атрибут mapper или мы можем получить mapper через metadata
                    try:
                        # Пробуем получить mapper из table, если он есть
                        if hasattr(table, 'mapper') and table.mapper is not None:
                            mapper = table.mapper
                            if hasattr(mapper, 'class_'):
                                bind_key = getattr(mapper.class_, '__bind_key__', None)
                    except (AttributeError, TypeError):
                        pass
                    
                    # Если все еще не нашли, пробуем через metadata таблицы
                    if not bind_key and hasattr(table, 'metadata'):
                        # Ищем модель в metadata, которая использует эту таблицу
                        try:
                            # Пробуем получить все mappers из metadata
                            if hasattr(table.metadata, '_mappers'):
                                for mapper_obj in table.metadata._mappers.values():
                                    if hasattr(mapper_obj, 'class_') and hasattr(mapper_obj, 'local_table'):
                                        if mapper_obj.local_table is table:
                                            bind_key = getattr(mapper_obj.class_, '__bind_key__', None)
                                            if bind_key:
                                                break
                            
                            # Если не нашли через _mappers, пробуем через registry
                            if not bind_key:
                                # Пробуем найти модель через глобальный db объект
                                try:
                                    # Используем глобальный db, который уже импортирован в этом модуле
                                    if hasattr(db, 'Model') and hasattr(db.Model, 'registry'):
                                        for mapper_obj in db.Model.registry._mappers.values():
                                            if hasattr(mapper_obj, 'class_') and hasattr(mapper_obj, 'local_table'):
                                                if mapper_obj.local_table is table:
                                                    bind_key = getattr(mapper_obj.class_, '__bind_key__', None)
                                                    if bind_key:
                                                        break
                                except (AttributeError, TypeError):
                                    pass
                        except (AttributeError, TypeError):
                            pass
            
            # Если это bind 'school', проверяем g.school_id и устанавливаем bind динамически
            if bind_key == 'school':
                if app is None:
                    from flask import current_app
                    app = current_app
                
                # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что SQLALCHEMY_BINDS существует
                if 'SQLALCHEMY_BINDS' not in app.config:
                    app.config['SQLALCHEMY_BINDS'] = {}
                
                # Проверяем, есть ли school_id в контексте
                school_id = None
                if has_request_context() and hasattr(g, 'school_id'):
                    school_id = g.school_id
                
                # Если school_id найден, устанавливаем bind динамически
                if school_id is not None:
                    if 'school' not in app.config['SQLALCHEMY_BINDS']:
                        db_uri = get_school_db_uri(school_id)
                        app.config['SQLALCHEMY_BINDS']['school'] = db_uri
                
                # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что bind есть в конфигурации перед вызовом оригинального метода
                # Даже если school_id не найден, устанавливаем временный bind, чтобы избежать ошибки
                if 'school' not in app.config['SQLALCHEMY_BINDS']:
                    # Если school_id не найден, используем временный bind
                    if school_id is not None:
                        db_uri = get_school_db_uri(school_id)
                        app.config['SQLALCHEMY_BINDS']['school'] = db_uri
                    else:
                        # Устанавливаем временный bind
                        temp_db_path = os.path.join(BASE_DIR, 'databases', 'temp_school.db')
                        app.config['SQLALCHEMY_BINDS']['school'] = f"sqlite:///{temp_db_path}"
                
                # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что engine есть в словаре engines
                # Оригинальная функция проверяет наличие ключа 'school' в словаре engines
                if engines is not None and isinstance(engines, dict):
                    if 'school' not in engines:
                        # Создаем engine и добавляем его в словарь engines
                        db_uri = app.config['SQLALCHEMY_BINDS']['school']
                        from sqlalchemy import create_engine
                        engine = create_engine(db_uri, echo=False)
                        engines['school'] = engine
            
            # Вызываем оригинальный метод с теми же аргументами
            try:
                return original_clause_to_engine(*args, **kwargs)
            except Exception as e:
                # Если оригинальная функция выбрасывает ошибку о том, что bind 'school' не найден,
                # устанавливаем его динамически и пробуем снова
                error_msg = str(e).lower()
                is_school_bind = False
                
                # Проверяем, является ли это bind 'school'
                if bind_key == 'school':
                    is_school_bind = True
                elif 'bind key' in error_msg and 'school' in error_msg:
                    # Если bind_key не определен, но ошибка говорит о bind 'school',
                    # проверяем имя таблицы
                    if table is not None:
                        table_name = getattr(table, 'name', None)
                        if table_name:
                            school_table_names = [
                                'ai_conversations', 'ai_conversation_messages',
                                'subjects', 'teachers', 'classes', 'class_load', 
                                'teacher_assignments', 'permanent_schedule', 'temporary_schedule',
                                'shifts', 'schedule_settings', 'prompt_class_subjects',
                                'prompt_class_subject_teachers', 'teacher_classes'
                            ]
                            if table_name in school_table_names or any(table_name.startswith(prefix) for prefix in ['ai_', 'prompt_']):
                                is_school_bind = True
                                bind_key = 'school'  # Устанавливаем для дальнейшего использования
                
                if 'bind key' in error_msg and 'school' in error_msg and is_school_bind:
                    if app is None:
                        from flask import current_app
                        app = current_app
                    
                    # Убеждаемся, что bind установлен
                    if 'SQLALCHEMY_BINDS' not in app.config:
                        app.config['SQLALCHEMY_BINDS'] = {}
                    
                    school_id = None
                    if has_request_context() and hasattr(g, 'school_id'):
                        school_id = g.school_id
                    
                    if school_id is not None:
                        db_uri = get_school_db_uri(school_id)
                        app.config['SQLALCHEMY_BINDS']['school'] = db_uri
                    else:
                        temp_db_path = os.path.join(BASE_DIR, 'databases', 'temp_school.db')
                        app.config['SQLALCHEMY_BINDS']['school'] = f"sqlite:///{temp_db_path}"
                    
                    # Убеждаемся, что engine есть в словаре engines
                    if engines is not None and isinstance(engines, dict):
                        if 'school' not in engines:
                            db_uri = app.config['SQLALCHEMY_BINDS']['school']
                            from sqlalchemy import create_engine
                            engine = create_engine(db_uri, echo=False)
                            engines['school'] = engine
                    
                    # Пробуем снова
                    return original_clause_to_engine(*args, **kwargs)
                else:
                    # Если это другая ошибка, пробрасываем её дальше
                    raise
        
        # Применяем monkey patch
        import flask_sqlalchemy.session
        flask_sqlalchemy.session._clause_to_engine = patched_clause_to_engine
    except (ImportError, AttributeError, TypeError) as e:
        # Если не удалось применить патч, это не критично - будем полагаться на другие методы
        print(f"⚠️ Не удалось применить monkey patch для _clause_to_engine: {e}")

def ensure_school_db_registered(app):
    """Устаревшая функция - больше не нужна, но оставлена для совместимости"""
    # Теперь используем один экземпляр db, регистрация не нужна
    # Просто обновляем конфигурацию bind
    pass

def switch_school_db(school_id):
    """
    Переключить bind 'school' на БД конкретной школы
    Просто обновляем конфигурацию - Flask-SQLAlchemy автоматически использует новый URI
    """
    if school_id is None:
        return False
    
    db_uri = get_school_db_uri(school_id)
    
    # Обновляем конфигурацию приложения
    from flask import has_app_context, current_app
    
    if has_app_context() or has_request_context():
        # КРИТИЧЕСКИ ВАЖНО: Всегда убеждаемся, что SQLALCHEMY_BINDS существует
        if 'SQLALCHEMY_BINDS' not in current_app.config:
            current_app.config['SQLALCHEMY_BINDS'] = {}
        
        # Сохраняем старый URI для очистки кэша
        old_uri = current_app.config.get('SQLALCHEMY_BINDS', {}).get('school')
        
        # Устанавливаем bind 'school' (всегда обновляем, даже если уже существует)
        current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
        
        # КРИТИЧЕСКИ ВАЖНО: Очищаем кэш engines для bind 'school' через наш кастомный метод
        if hasattr(db, 'clear_school_engine_cache'):
            # Очищаем кэш для старого URI (если был)
            if old_uri:
                db.clear_school_engine_cache(old_uri)
            # Очищаем кэш для нового URI, чтобы создать новый engine
            db.clear_school_engine_cache(db_uri)
        
        # Также очищаем стандартные кэши Flask-SQLAlchemy (на всякий случай)
        if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
            sqlalchemy_ext = current_app.extensions['sqlalchemy']
            # Очищаем все возможные кэши engines
            for attr_name in ['engines', '_engines', '_bind_registry', '_make_engine_cache']:
                if hasattr(sqlalchemy_ext, attr_name):
                    engines_dict = getattr(sqlalchemy_ext, attr_name)
                    if isinstance(engines_dict, dict) and 'school' in engines_dict:
                        del engines_dict['school']
    
    return True

def create_school_database(school_id):
    """
    Создать БД для школы и инициализировать все таблицы
    Требует активный app context
    """
    from app.models.school import (
        Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
        PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings,
        PromptClassSubject, PromptClassSubjectTeacher
    )
    
    # Создаем директорию, если её нет
    db_path = get_school_db_path(school_id)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Используем прямой create_engine для создания таблиц
    # Это более надежно для динамических БД
    db_uri = get_school_db_uri(school_id)
    engine = create_engine(db_uri, echo=False)
    
    # Создаем все таблицы используя metadata напрямую
    # Фильтруем только модели с __bind_key__ = 'school'
    from app.models.school import (
        Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
        PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings,
        PromptClassSubject, PromptClassSubjectTeacher,
        AIConversation, AIConversationMessage,
        SubjectCabinet,
        _get_teacher_classes_table
    )
    
    # Сначала создаем основные таблицы
    from app.models.school import Cabinet, CabinetTeacher
    db.Model.metadata.create_all(engine, tables=[
        Subject.__table__,
        Teacher.__table__,
        ClassGroup.__table__,
        ClassLoad.__table__,
        TeacherAssignment.__table__,
        PermanentSchedule.__table__,
        TemporarySchedule.__table__,
        Shift.__table__,
        ScheduleSettings.__table__,
        PromptClassSubject.__table__,
        PromptClassSubjectTeacher.__table__,
        AIConversation.__table__,
        AIConversationMessage.__table__,
        SubjectCabinet.__table__,
        Cabinet.__table__,
        CabinetTeacher.__table__
    ])
    
    # Затем создаем промежуточную таблицу (после создания основных таблиц)
    # Используем прямое SQL для создания таблицы, чтобы избежать проверки FK при создании через SQLAlchemy
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'teacher_classes' not in tables:
            # Создаем таблицу напрямую через SQL, чтобы избежать проверки FK
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE teacher_classes (
                        teacher_id INTEGER NOT NULL,
                        class_id INTEGER NOT NULL,
                        PRIMARY KEY (teacher_id, class_id),
                        FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                        FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                        UNIQUE (teacher_id, class_id)
                    )
                """))
                conn.commit()
    except Exception as e:
        # Если не удалось создать через SQL, пробуем через SQLAlchemy
        # Предупреждение о FK - это нормально с use_alter=True
        try:
            teacher_classes_table = _get_teacher_classes_table()
            teacher_classes_table.info = getattr(teacher_classes_table, 'info', {})
            teacher_classes_table.info['bind_key'] = 'school'
            teacher_classes_table.create(engine, checkfirst=True)
        except Exception:
            # Игнорируем ошибки FK - они ожидаемы с use_alter=True
            pass
    
    # НЕ инициализируем relationship - используем прямые запросы к промежуточной таблице
    # Это более надежно и не вызывает проблем с инициализацией FK
    
    # Выполняем миграции для существующих БД (добавит недостающие колонки)
    migrate_school_database(school_id, engine)
    
    return True

def migrate_school_database(school_id, engine=None):
    """
    Выполняет миграции для БД школы
    Добавляет недостающие колонки и таблицы
    """
    if engine is None:
        db_uri = get_school_db_uri(school_id)
        engine = create_engine(db_uri, echo=False)
    
    from sqlalchemy import text, inspect
    from app.models.school import Cabinet, CabinetTeacher
    inspector = inspect(engine)
    
    try:
        # Проверяем наличие таблиц кабинетов
        tables = inspector.get_table_names()
        
        # Создаем таблицы, если их нет
        if 'cabinets' not in tables:
            Cabinet.__table__.create(engine, checkfirst=True)
        if 'cabinet_teachers' not in tables:
            CabinetTeacher.__table__.create(engine, checkfirst=True)
        
        # Проверяем наличие колонок в таблице cabinets
        if 'cabinets' in tables:
            columns = [col['name'] for col in inspector.get_columns('cabinets')]
            
            # Добавляем колонку subject_id, если её нет
            if 'subject_id' not in columns:
                print(f"   Миграция: Добавление колонки subject_id в таблицу cabinets для школы {school_id}...")
                with engine.connect() as conn:
                    # Добавляем колонку subject_id (nullable для обратной совместимости)
                    conn.execute(text("ALTER TABLE cabinets ADD COLUMN subject_id INTEGER"))
                    # Добавляем уникальный индекс
                    try:
                        conn.execute(text("""
                            CREATE UNIQUE INDEX IF NOT EXISTS uix_cabinet_name_subject 
                            ON cabinets(name, subject_id)
                        """))
                    except Exception:
                        # Индекс может уже существовать или быть проблемой с NULL значениями
                        pass
                    conn.commit()
                print(f"   ✅ Колонка subject_id добавлена в таблицу cabinets")
            
            # Добавляем колонку subgroups_only, если её нет
            if 'subgroups_only' not in columns:
                print(f"   Миграция: Добавление колонки subgroups_only в таблицу cabinets для школы {school_id}...")
                with engine.connect() as conn:
                    # SQLite использует INTEGER для булевых значений (0 = False, 1 = True)
                    # Добавляем колонку с значением по умолчанию 0 (False)
                    conn.execute(text("ALTER TABLE cabinets ADD COLUMN subgroups_only INTEGER DEFAULT 0"))
                    # Устанавливаем значение 0 для всех существующих записей (на случай, если DEFAULT не сработал)
                    conn.execute(text("UPDATE cabinets SET subgroups_only = 0 WHERE subgroups_only IS NULL"))
                    conn.commit()
                print(f"   ✅ Колонка subgroups_only добавлена в таблицу cabinets")
            
            # Добавляем колонку exclusive_to_subject, если её нет
            if 'exclusive_to_subject' not in columns:
                print(f"   Миграция: Добавление колонки exclusive_to_subject в таблицу cabinets для школы {school_id}...")
                with engine.connect() as conn:
                    # SQLite использует INTEGER для булевых значений (0 = False, 1 = True)
                    # Добавляем колонку с значением по умолчанию 0 (False)
                    conn.execute(text("ALTER TABLE cabinets ADD COLUMN exclusive_to_subject INTEGER DEFAULT 0"))
                    # Устанавливаем значение 0 для всех существующих записей (на случай, если DEFAULT не сработал)
                    conn.execute(text("UPDATE cabinets SET exclusive_to_subject = 0 WHERE exclusive_to_subject IS NULL"))
                    conn.commit()
                print(f"   ✅ Колонка exclusive_to_subject добавлена в таблицу cabinets")
            
            # Добавляем колонку max_classes_simultaneously, если её нет
            if 'max_classes_simultaneously' not in columns:
                print(f"   Миграция: Добавление колонки max_classes_simultaneously в таблицу cabinets для школы {school_id}...")
                with engine.connect() as conn:
                    # Добавляем колонку с значением по умолчанию 1
                    conn.execute(text("ALTER TABLE cabinets ADD COLUMN max_classes_simultaneously INTEGER DEFAULT 1 NOT NULL"))
                    # Устанавливаем значение 1 для всех существующих записей
                    conn.execute(text("UPDATE cabinets SET max_classes_simultaneously = 1 WHERE max_classes_simultaneously IS NULL"))
                    conn.commit()
                print(f"   ✅ Колонка max_classes_simultaneously добавлена в таблицу cabinets")
        
        # Проверяем наличие колонок в таблице subjects
        if 'subjects' in tables:
            columns = [col['name'] for col in inspector.get_columns('subjects')]
            
            # Добавляем колонку category, если её нет
            if 'category' not in columns:
                print(f"   Миграция: Добавление колонки category в таблицу subjects для школы {school_id}...")
                with engine.connect() as conn:
                    # Добавляем колонку category (nullable для обратной совместимости)
                    # Существующие предметы будут иметь NULL в этом поле
                    conn.execute(text("ALTER TABLE subjects ADD COLUMN category TEXT"))
                    conn.commit()
                print(f"   ✅ Колонка category добавлена в таблицу subjects")
    except Exception as e:
        print(f"   ⚠️ Предупреждение при миграции БД школы {school_id}: {e}")
        import traceback
        traceback.print_exc()

def delete_school_database(school_id):
    """
    Удалить БД школы
    """
    db_path = get_school_db_path(school_id)
    
    # Удаляем файл БД
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            return True
        except Exception as e:
            print(f"Ошибка при удалении БД школы {school_id}: {e}")
            return False
    
    return True

def clear_school_database(school_id):
    """
    Очистить все данные из БД школы (удалить все таблицы и создать заново)
    """
    from app.models.school import (
        Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
        PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings,
        PromptClassSubject, PromptClassSubjectTeacher
    )
    
    try:
        # Используем прямой create_engine для очистки таблиц
        db_uri = get_school_db_uri(school_id)
        engine = create_engine(db_uri, echo=False)
        
        # Фильтруем только модели с __bind_key__ = 'school'
        from app.models.school import (
            Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
            PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings,
            PromptClassSubject, PromptClassSubjectTeacher,
            SubjectCabinet
        )
        tables = [
            Subject.__table__,
            Teacher.__table__,
            ClassGroup.__table__,
            ClassLoad.__table__,
            TeacherAssignment.__table__,
            PermanentSchedule.__table__,
            TemporarySchedule.__table__,
            Shift.__table__,
            ScheduleSettings.__table__,
            PromptClassSubject.__table__,
            PromptClassSubjectTeacher.__table__,
            SubjectCabinet.__table__
        ]
        
        # Удаляем все таблицы
        db.Model.metadata.drop_all(engine, tables=tables)
        
        # Создаем заново
        db.Model.metadata.create_all(engine, tables=tables)
        
        return True
    except Exception as e:
        print(f"Ошибка при очистке БД школы {school_id}: {e}")
        import traceback
        traceback.print_exc()
        return False

@contextmanager
def school_db_context(school_id):
    """
    Контекстный менеджер для работы с БД школы
    Переключает bind 'school' на нужную БД и гарантирует, что он настроен
    """
    if school_id is None:
        raise ValueError("school_id не может быть None")
    
    # Убеждаемся, что есть app context
    from flask import has_app_context, current_app
    if not has_app_context():
        raise RuntimeError("school_db_context требует активный app context")
    
    # Сохраняем school_id в g для доступа в функциях (если есть request context)
    old_school_id = None
    if has_request_context():
        old_school_id = getattr(g, 'school_id', None)
        g.school_id = school_id
    
    # Сохраняем старый URI для восстановления
    old_uri = current_app.config.get('SQLALCHEMY_BINDS', {}).get('school')
    
    # КРИТИЧЕСКИ ВАЖНО: Убеждаемся, что SQLALCHEMY_BINDS существует и содержит 'school'
    if 'SQLALCHEMY_BINDS' not in current_app.config:
        current_app.config['SQLALCHEMY_BINDS'] = {}
    
    # Переключаемся на БД школы (это обновит SQLALCHEMY_BINDS['school'])
    switch_school_db(school_id)
    
    # Дополнительная проверка: убеждаемся, что bind 'school' точно настроен
    db_uri = get_school_db_uri(school_id)
    if 'school' not in current_app.config.get('SQLALCHEMY_BINDS', {}):
        current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
    else:
        # Обновляем URI даже если bind уже существует
        current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
    
    # КРИТИЧЕСКИ ВАЖНО: Принудительно очищаем все кэши engines после обновления конфигурации
    # Flask-SQLAlchemy кэширует engines, и нужно их очистить, чтобы использовался новый URI
    if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
        sqlalchemy_ext = current_app.extensions['sqlalchemy']
        # Очищаем все возможные кэши
        for attr_name in ['engines', '_engines', '_bind_registry']:
            if hasattr(sqlalchemy_ext, attr_name):
                engines_dict = getattr(sqlalchemy_ext, attr_name)
                if isinstance(engines_dict, dict) and 'school' in engines_dict:
                    del engines_dict['school']
    
    # КРИТИЧЕСКИ ВАЖНО: Проверяем, что bind точно настроен перед yield
    # Это гарантирует, что все запросы внутри контекста будут использовать правильный bind
    final_binds = current_app.config.get('SQLALCHEMY_BINDS', {})
    if 'school' not in final_binds or final_binds['school'] != db_uri:
        # Если bind не настроен правильно, устанавливаем его принудительно
        current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
        # Очищаем кэши еще раз
        if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
            sqlalchemy_ext = current_app.extensions['sqlalchemy']
            for attr_name in ['engines', '_engines', '_bind_registry']:
                if hasattr(sqlalchemy_ext, attr_name):
                    engines_dict = getattr(sqlalchemy_ext, attr_name)
                    if isinstance(engines_dict, dict) and 'school' in engines_dict:
                        del engines_dict['school']
        # Создаем engine заново
        try:
            engine = db.get_engine(current_app, bind='school')
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                sqlalchemy_ext = current_app.extensions['sqlalchemy']
                if not hasattr(sqlalchemy_ext, 'engines'):
                    sqlalchemy_ext.engines = {}
                sqlalchemy_ext.engines['school'] = engine
                if not hasattr(sqlalchemy_ext, '_engines'):
                    sqlalchemy_ext._engines = {}
                sqlalchemy_ext._engines['school'] = engine
        except Exception as e:
            raise RuntimeError(
                f"Не удалось создать engine для bind 'school' перед yield. "
                f"Ошибка: {e}\n"
                f"SQLALCHEMY_BINDS: {final_binds}\n"
                f"Ожидаемый URI: {db_uri}"
            )
    
    # КРИТИЧЕСКИ ВАЖНО: Предварительно создаем engine для bind 'school'
    # Это гарантирует, что Flask-SQLAlchemy найдет engine при первом использовании
    # Используем наш кастомный get_engine, который правильно обработает динамический bind
    try:
        # Вызываем get_engine для создания и кэширования engine
        # Это заставит наш кастомный метод создать engine и сохранить его в кэше
        engine = db.get_engine(current_app, bind='school')
        
        # КРИТИЧЕСКИ ВАЖНО: Регистрируем engine в кэше Flask-SQLAlchemy
        # Это необходимо, чтобы Flask-SQLAlchemy мог найти engine через свой внутренний механизм
        if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
            sqlalchemy_ext = current_app.extensions['sqlalchemy']
            # Регистрируем engine в стандартных кэшах Flask-SQLAlchemy
            if not hasattr(sqlalchemy_ext, 'engines'):
                sqlalchemy_ext.engines = {}
            sqlalchemy_ext.engines['school'] = engine
            
            if not hasattr(sqlalchemy_ext, '_engines'):
                sqlalchemy_ext._engines = {}
            sqlalchemy_ext._engines['school'] = engine
        
        # Теперь engine создан и зарегистрирован, Flask-SQLAlchemy сможет его найти
    except Exception as e:
        # Если не удалось создать engine, выводим ошибку
        binds_config = current_app.config.get('SQLALCHEMY_BINDS', {})
        raise RuntimeError(
            f"Не удалось создать engine для bind 'school' в school_db_context.\n"
            f"Ошибка: {e}\n"
            f"SQLALCHEMY_BINDS: {binds_config}\n"
            f"Ожидаемый URI: {db_uri}"
        )
    
    # НЕ инициализируем связь Teacher.classes - используем прямые запросы к промежуточной таблице
    # Это позволяет избежать проблем с проверкой внешних ключей при инициализации
    # Убеждаемся, что таблица teacher_classes существует в БД
    try:
        from sqlalchemy import inspect
        from app.models.school import _get_teacher_classes_table
        
        # Проверяем, что таблица существует в БД
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'teacher_classes' not in tables:
            # Таблица не существует, создаем её через SQL, чтобы избежать проверки FK
            try:
                from sqlalchemy import text
                with engine.connect() as conn:
                    conn.execute(text("""
                        CREATE TABLE teacher_classes (
                            teacher_id INTEGER NOT NULL,
                            class_id INTEGER NOT NULL,
                            PRIMARY KEY (teacher_id, class_id),
                            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
                            UNIQUE (teacher_id, class_id)
                        )
                    """))
                    conn.commit()
            except Exception as sql_error:
                # Если не удалось создать через SQL, пробуем через SQLAlchemy
                # Предупреждение о FK - это нормально, игнорируем
                try:
                    from app.models.school import _get_teacher_classes_table
                    teacher_classes_table = _get_teacher_classes_table()
                    teacher_classes_table.info = getattr(teacher_classes_table, 'info', {})
                    teacher_classes_table.info['bind_key'] = 'school'
                    teacher_classes_table.create(engine, checkfirst=True)
                except Exception:
                    # Игнорируем ошибки FK - они ожидаемы с use_alter=True
                    pass
    except Exception as e:
        # Если создание таблицы не удалось, это не критично
        # Не выводим предупреждение, так как это ожидаемое поведение с use_alter=True
        pass
    
    # КРИТИЧЕСКИ ВАЖНО: Проверяем, что bind точно настроен перед yield
    # Это гарантирует, что все запросы внутри контекста будут использовать правильный bind
    final_binds = current_app.config.get('SQLALCHEMY_BINDS', {})
    if 'school' not in final_binds or final_binds['school'] != db_uri:
        # Если bind не настроен правильно, устанавливаем его принудительно
        current_app.config['SQLALCHEMY_BINDS']['school'] = db_uri
        # Очищаем кэши еще раз
        if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
            sqlalchemy_ext = current_app.extensions['sqlalchemy']
            for attr_name in ['engines', '_engines', '_bind_registry']:
                if hasattr(sqlalchemy_ext, attr_name):
                    engines_dict = getattr(sqlalchemy_ext, attr_name)
                    if isinstance(engines_dict, dict) and 'school' in engines_dict:
                        del engines_dict['school']
        # Создаем engine заново
        try:
            engine = db.get_engine(current_app, bind='school')
            if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                sqlalchemy_ext = current_app.extensions['sqlalchemy']
                if not hasattr(sqlalchemy_ext, 'engines'):
                    sqlalchemy_ext.engines = {}
                sqlalchemy_ext.engines['school'] = engine
                if not hasattr(sqlalchemy_ext, '_engines'):
                    sqlalchemy_ext._engines = {}
                sqlalchemy_ext._engines['school'] = engine
        except Exception as e:
            raise RuntimeError(
                f"Не удалось создать engine для bind 'school' перед yield. "
                f"Ошибка: {e}\n"
                f"SQLALCHEMY_BINDS: {final_binds}\n"
                f"Ожидаемый URI: {db_uri}"
            )
    
    try:
        yield db  # Возвращаем общий экземпляр db
    finally:
        # Восстанавливаем school_id и URI при выходе
        if has_request_context():
            if old_school_id:
                g.school_id = old_school_id
                switch_school_db(old_school_id)
            else:
                g.school_id = None
                # Восстанавливаем старый URI или устанавливаем дефолтный
                if old_uri:
                    current_app.config['SQLALCHEMY_BINDS']['school'] = old_uri
                    # Очищаем кэш
                    if hasattr(current_app, 'extensions') and 'sqlalchemy' in current_app.extensions:
                        sqlalchemy_ext = current_app.extensions['sqlalchemy']
                        if hasattr(sqlalchemy_ext, 'engines') and 'school' in sqlalchemy_ext.engines:
                            del sqlalchemy_ext.engines['school']
                        if hasattr(sqlalchemy_ext, '_engines') and 'school' in sqlalchemy_ext._engines:
                            del sqlalchemy_ext._engines['school']

def with_school_db(f):
    """
    Декоратор для автоматического переключения на БД школы
    Требует, чтобы school_id был доступен (через get_current_school_id)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from app.core.auth import get_current_school_id
        
        school_id = get_current_school_id()
        if school_id is None:
            # Если нет school_id, возможно это супер-админ или системная функция
            # В этом случае используем системную БД
            return f(*args, **kwargs)
        
        # Убеждаемся, что БД школы существует
        db_path = get_school_db_path(school_id)
        if not os.path.exists(db_path):
            create_school_database(school_id)
        
        with school_db_context(school_id):
            return f(*args, **kwargs)
    
    return decorated_function

def get_current_school_db():
    """
    Получить текущую БД школы из контекста Flask (g)
    """
    if has_request_context() and hasattr(g, 'school_id'):
        switch_school_db(g.school_id)
        return school_db
    return None

def get_school_db_session(school_id):
    """
    Получить session для БД школы
    Используйте эту функцию вместо прямого доступа к db.session
    """
    from flask import current_app, has_app_context
    
    if not has_app_context():
        raise RuntimeError("get_school_db_session требует активный app context")
    
    # Переключаемся на БД школы
    switch_school_db(school_id)
    
    # Возвращаем session из общего экземпляра db
    # Flask-SQLAlchemy автоматически использует правильный bind для моделей с __bind_key__ = 'school'
    return db.session

