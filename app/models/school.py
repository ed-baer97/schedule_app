"""
Модели для школ - хранятся в отдельных БД для каждой школы
Используют общий db из app.core.db_manager с bind 'school' для динамического переключения БД
"""
from datetime import datetime, date
from sqlalchemy import ForeignKey, UniqueConstraint, Table, Column, Integer
from app.core.db_manager import db

# Константы для категорий предметов
SUBJECT_CATEGORY_LANGUAGES = 'languages'
SUBJECT_CATEGORY_HUMANITIES = 'humanities'
SUBJECT_CATEGORY_NATURAL_MATH = 'natural_math'

SUBJECT_CATEGORIES = {
    SUBJECT_CATEGORY_LANGUAGES: 'Языки',
    SUBJECT_CATEGORY_HUMANITIES: 'Гуманитарные предметы',
    SUBJECT_CATEGORY_NATURAL_MATH: 'Естественно-математические предметы'
}

# Все модели используют db с __bind_key__ = 'school' для динамического переключения БД
class Subject(db.Model):
    __tablename__ = 'subjects'
    __bind_key__ = 'school'  # Используем bind для переключения БД
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=True)  # Категория предмета: languages, humanities, natural_math
    __table_args__ = (UniqueConstraint('name', name='uix_subject_name'),)

class Teacher(db.Model):
    __tablename__ = 'teachers'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(30))
    phone = db.Column(db.String(20))
    telegram_id = db.Column(db.String(50), nullable=True)
    
    # НЕ создаем relationship для classes - используем прямые запросы к промежуточной таблице
    # Это более надежно и не вызывает проблем с инициализацией FK
    # Для доступа к классам используйте _get_teacher_classes_table() и прямые запросы

class ClassGroup(db.Model):
    __tablename__ = 'classes'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False)
    __table_args__ = (UniqueConstraint('name', name='uix_class_name'),)

class Shift(db.Model):
    __tablename__ = 'shifts'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class ShiftClass(db.Model):
    """Связь классов со сменами - явное назначение класса смене"""
    __tablename__ = 'shift_classes'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    __table_args__ = (UniqueConstraint('shift_id', 'class_id', name='uix_shift_class'),)
    
    shift = db.relationship('Shift', backref='shift_classes')
    class_group = db.relationship('ClassGroup', backref='shift_classes')

class ClassLoad(db.Model):
    __tablename__ = 'class_load'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=True)  # Нагрузка общая для всех смен
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, nullable=False)
    __table_args__ = (UniqueConstraint('class_id', 'subject_id', name='uix_class_subject'),)  # Убрали shift_id из уникального ключа
    
    shift = db.relationship('Shift', backref='class_loads')
    class_group = db.relationship('ClassGroup', backref='class_loads')
    subject = db.relationship('Subject', backref='class_loads')

class TeacherAssignment(db.Model):
    __tablename__ = 'teacher_assignments'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    teacher_id = db.Column(db.Integer, ForeignKey('teachers.id'), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id'), nullable=False)
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, default=0)
    default_cabinet = db.Column(db.String(10))
    __table_args__ = (UniqueConstraint('shift_id', 'teacher_id', 'subject_id', 'class_id'),)
    
    shift = db.relationship('Shift', backref='teacher_assignments')
    teacher = db.relationship('Teacher', backref='teacher_assignments')
    subject = db.relationship('Subject', backref='teacher_assignments')
    class_group = db.relationship('ClassGroup', backref='teacher_assignments')

class PermanentSchedule(db.Model):
    __tablename__ = 'permanent_schedule'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 1=Понедельник, 7=Воскресенье
    lesson_number = db.Column(db.Integer, nullable=False)
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, ForeignKey('teachers.id'), nullable=False)
    cabinet = db.Column(db.String(10), nullable=False)
    __table_args__ = (UniqueConstraint('shift_id', 'day_of_week', 'lesson_number', 'class_id', 'teacher_id', 'cabinet', name='uix_permanent_schedule'),)
    
    shift = db.relationship('Shift', backref='permanent_schedules')
    class_group = db.relationship('ClassGroup', backref='permanent_schedules')
    subject = db.relationship('Subject', backref='permanent_schedules')
    teacher = db.relationship('Teacher', backref='permanent_schedules')

class TemporarySchedule(db.Model):
    __tablename__ = 'temporary_schedule'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    lesson_number = db.Column(db.Integer, nullable=False)
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, ForeignKey('teachers.id'), nullable=False)
    cabinet = db.Column(db.String(10))
    __table_args__ = (UniqueConstraint('date', 'lesson_number', 'class_id', 'cabinet', name='uix_temporary_schedule'),)
    
    class_group = db.relationship('ClassGroup', backref='temporary_schedules')
    subject = db.relationship('Subject', backref='temporary_schedules')
    teacher = db.relationship('Teacher', backref='temporary_schedules')

class ScheduleSettings(db.Model):
    __tablename__ = 'schedule_settings'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)
    lessons_count = db.Column(db.Integer, nullable=False, default=6)
    __table_args__ = (UniqueConstraint('shift_id', 'day_of_week', name='uix_shift_day'),)
    
    shift = db.relationship('Shift', backref='settings')

class PromptClassSubject(db.Model):
    """
    Модель для структуры промпта: Класс -> Предмет
    Хранит информацию о предмете в классе и определяет, есть ли подгруппы
    """
    __tablename__ = 'prompt_class_subjects'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    class_id = db.Column(db.Integer, ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id'), nullable=False)
    total_hours_per_week = db.Column(db.Integer, nullable=False)  # Общее количество часов в неделю
    has_subgroups = db.Column(db.Boolean, default=False)  # True если 2+ учителя, False если 1 учитель
    __table_args__ = (UniqueConstraint('shift_id', 'class_id', 'subject_id', name='uix_prompt_class_subject'),)
    
    shift = db.relationship('Shift', backref='prompt_class_subjects')
    class_group = db.relationship('ClassGroup', backref='prompt_class_subjects')
    subject = db.relationship('Subject', backref='prompt_class_subjects')
    teachers = db.relationship('PromptClassSubjectTeacher', backref='class_subject', cascade='all, delete-orphan')

class PromptClassSubjectTeacher(db.Model):
    """
    Модель для связи: Класс -> Предмет -> Учитель
    Хранит информацию о том, какой учитель ведет предмет в классе и его индивидуальную нагрузку
    """
    __tablename__ = 'prompt_class_subject_teachers'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    prompt_class_subject_id = db.Column(db.Integer, ForeignKey('prompt_class_subjects.id', ondelete='CASCADE'), nullable=False)
    teacher_id = db.Column(db.Integer, ForeignKey('teachers.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, nullable=False)  # Индивидуальная нагрузка учителя
    default_cabinet = db.Column(db.String(10))  # Кабинет по умолчанию
    is_assigned_to_class = db.Column(db.Boolean, default=False)  # Закреплен ли учитель за классом
    __table_args__ = (UniqueConstraint('prompt_class_subject_id', 'teacher_id', name='uix_prompt_class_subject_teacher'),)
    
    teacher = db.relationship('Teacher', backref='prompt_class_subject_teachers')

class AIConversation(db.Model):
    """
    Модель для хранения истории диалога с ИИ при составлении расписания
    Позволяет администратору обсуждать детали с ИИ перед генерацией
    """
    __tablename__ = 'ai_conversations'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, ForeignKey('shifts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True)  # Активна ли сессия диалога
    
    shift = db.relationship('Shift', backref='ai_conversations')
    messages = db.relationship('AIConversationMessage', backref='conversation', cascade='all, delete-orphan', order_by='AIConversationMessage.created_at')

class AIConversationMessage(db.Model):
    """
    Модель для хранения сообщений в диалоге с ИИ
    """
    __tablename__ = 'ai_conversation_messages'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, ForeignKey('ai_conversations.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'user' или 'assistant'
    content = db.Column(db.Text, nullable=False)  # Текст сообщения
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# Промежуточная таблица для связи many-to-many между Teacher и ClassGroup
# КРИТИЧЕСКИ ВАЖНО: НЕ определяем таблицу здесь, чтобы избежать проверки FK при инициализации мапперов
# Таблица будет определена динамически при создании БД школы
def _get_teacher_classes_table():
    """Создает промежуточную таблицу для связи учителей и классов"""
    # Используем строковые имена для ForeignKey, чтобы отложить проверку
    # use_alter=True позволяет создать FK позже через ALTER TABLE
    # Это критически важно для избежания ошибок при инициализации
    return Table(
        'teacher_classes',
        db.Model.metadata,
        Column('teacher_id', Integer, ForeignKey('teachers.id', ondelete='CASCADE', use_alter=True, name='fk_teacher_classes_teacher'), primary_key=True),
        Column('class_id', Integer, ForeignKey('classes.id', ondelete='CASCADE', use_alter=True, name='fk_teacher_classes_class'), primary_key=True),
        UniqueConstraint('teacher_id', 'class_id', name='uix_teacher_class'),
        extend_existing=True
    )

# Глобальная переменная для хранения таблицы (будет создана при необходимости)
teacher_classes = None

class SubjectCabinet(db.Model):
    """
    Модель для связи предметов и кабинетов
    Каждый предмет может иметь несколько кабинетов
    """
    __tablename__ = 'subject_cabinets'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    cabinet_name = db.Column(db.String(10), nullable=False)
    __table_args__ = (UniqueConstraint('subject_id', 'cabinet_name', name='uix_subject_cabinet'),)
    
    subject = db.relationship('Subject', backref='cabinets')


class Cabinet(db.Model):
    """
    Модель для хранения списка кабинетов
    Каждый кабинет привязан к предмету
    """
    __tablename__ = 'cabinets'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False)
    subject_id = db.Column(db.Integer, ForeignKey('subjects.id', ondelete='CASCADE'), nullable=True)  # Временно nullable для миграции
    subgroups_only = db.Column(db.Integer, default=0, nullable=False)  # 0 = False, 1 = True (SQLite использует INTEGER для булевых значений)
    exclusive_to_subject = db.Column(db.Integer, default=0, nullable=False)  # 0 = False, 1 = True (SQLite использует INTEGER для булевых значений)
    max_classes_simultaneously = db.Column(db.Integer, default=1, nullable=False)  # Максимальное количество классов, которые могут быть одновременно в кабинете
    __table_args__ = (UniqueConstraint('name', 'subject_id', name='uix_cabinet_name_subject'),)
    
    subject = db.relationship('Subject', backref='cabinet_list')  # Изменено имя backref, чтобы избежать конфликта с SubjectCabinet
    teachers = db.relationship('CabinetTeacher', back_populates='cabinet', cascade='all, delete-orphan')


class CabinetTeacher(db.Model):
    """
    Модель для связи кабинетов и учителей
    Каждый кабинет может использоваться несколькими учителями
    """
    __tablename__ = 'cabinet_teachers'
    __bind_key__ = 'school'
    id = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, ForeignKey('cabinets.id', ondelete='CASCADE'), nullable=False)
    teacher_id = db.Column(db.Integer, ForeignKey('teachers.id', ondelete='CASCADE'), nullable=False)
    __table_args__ = (UniqueConstraint('cabinet_id', 'teacher_id', name='uix_cabinet_teacher'),)
    
    cabinet = db.relationship('Cabinet', back_populates='teachers')
    teacher = db.relationship('Teacher', backref='cabinets')

# НЕ создаем relationship динамически - это вызывает проблемы с инициализацией
# Вместо этого используем прямые запросы к промежуточной таблице
# Это более надежно и не вызывает проблем с FK
def _init_teacher_classes_relationship():
    """
    Заглушка для обратной совместимости.
    Relationship не создается динамически - используются прямые запросы к таблице.
    Также удаляем любые некорректные relationships, которые могли быть созданы ранее.
    """
    # Удаляем любые некорректные relationships, которые могли быть созданы ранее
    try:
        if hasattr(Teacher, 'classes'):
            # Удаляем некорректный relationship, если он существует
            if hasattr(Teacher.__mapper__, 'relationships'):
                if 'classes' in Teacher.__mapper__.relationships:
                    del Teacher.__mapper__.relationships['classes']
            # Удаляем атрибут из класса
            if hasattr(Teacher, 'classes'):
                delattr(Teacher, 'classes')
    except Exception:
        # Игнорируем ошибки при удалении - это не критично
        pass

