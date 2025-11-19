# app/models.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, Index
from enum import Enum # <-- Добавим импорт Enum

db = SQLAlchemy()

# --- Добавим Enum для типа изменения ---
class ChangeType(Enum): # <-- Новый класс
    SUBSTITUTION = "substitution" # Замена учителя
    MOVEMENT = "movement"        # Перенос урока (день/номер/кабинет)
    CANCELLATION = "cancellation" # Отмена урока

# Специализация учителя (какие предметы он может вести)
class TeacherSubject(db.Model):
    __tablename__ = 'teacher_subjects'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    __table_args__ = (UniqueConstraint('teacher_id', 'subject_id'),) # Один учитель не может дважды вести один и тот же предмет (в рамках своей специализации)

class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    # Связь с предметами, которые может вести учитель
    subjects = db.relationship('Subject', secondary='teacher_subjects', back_populates='teachers')
    # Связь с уроками, которые ведёт учитель
    lessons = db.relationship('Lesson', back_populates='teacher')
    # Связь с уроками, где учитель временно заменяет другого (для изменений)
    temporary_lessons = db.relationship('TemporaryChange', foreign_keys='TemporaryChange.new_teacher_id', back_populates='new_teacher')
    # Связь с уроками, где учитель является оригинальным (для изменений)
    original_lessons = db.relationship('TemporaryChange', foreign_keys='TemporaryChange.original_teacher_id', back_populates='original_teacher')
    # Связь с уроками, которые ведёт (для отслеживания основного расписания)
    lessons = db.relationship('Lesson', back_populates='teacher')
    # Связь с требованиями по количеству часов учителя (новая связь)
    teacher_requirements = db.relationship('TeacherSubjectRequirement', back_populates='teacher')

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    # Связь с учителями, ведущими этот предмет
    teachers = db.relationship('Teacher', secondary='teacher_subjects', back_populates='subjects')
    # Связь с требованиями по количеству уроков (класс-предмет)
    requirements = db.relationship('ClassSubjectRequirement', back_populates='subject')
    # Связь с уроками
    lessons = db.relationship('Lesson', back_populates='subject')

class Class(db.Model): # Обычный класс, например "5А"
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), nullable=False) # напр. "5А"
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'), nullable=False) # <-- НОВОЕ: поле для связи с Shift
    shift = db.relationship('Shift', back_populates='classes') # <-- НОВОЕ: связь с моделью Shift
    # Связь с подгруппами
    subgroups = db.relationship('SubGroup', back_populates='class_') # <-- Убедитесь, что 'subgroups' указано здесь
    # Связь с требованиями по количеству уроков (класс-предмет)
    requirements = db.relationship('ClassSubjectRequirement', back_populates='class_')
    # Связь с требованиями по количеству часов учителя (новая связь)
    teacher_requirements = db.relationship('TeacherSubjectRequirement', back_populates='class_')

class SubGroup(db.Model): # Подгруппа класса, например "5А-1" или "5А-2"
    __tablename__ = 'subgroups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(15), nullable=False) # напр. "5А-1", "5А-2" или просто "1", "2" внутри класса
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    class_ = db.relationship('Class', back_populates='subgroups') # <-- Убедитесь, что 'class_' указано здесь
    # Связь с уроками, которые посещает подгруппа
    lessons = db.relationship('Lesson', back_populates='subgroup')
    # Связь с требованиями по количеству часов учителя (новая связь)
    teacher_requirements = db.relationship('TeacherSubjectRequirement', back_populates='subgroup')

class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # напр. "22", "физика", "с\з"
    type = db.Column(db.String(100)) # напр. "обычный", "лаборатория", "спортзал", "кабинет информатики"
    # Связь с уроками
    lessons = db.relationship('Lesson', back_populates='room')
    # Связь с уроками, где комната временно изменена (для изменений)
    temporary_lessons = db.relationship('TemporaryChange', foreign_keys='TemporaryChange.new_room_id', back_populates='new_room')

class ClassSubjectRequirement(db.Model): # Требование: класс X должен иметь Y уроков предмета Z в неделю
    __tablename__ = 'class_subject_requirements'
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    weekly_hours = db.Column(db.Integer, nullable=False) # напр. 5 уроков математики в неделю для 5А
    class_ = db.relationship('Class', back_populates='requirements')
    subject = db.relationship('Subject', back_populates='requirements')

# --- ОБНОВЛЁННАЯ МОДЕЛЬ: Требование по количеству часов учителя ---
class TeacherSubjectRequirement(db.Model): # Требование: учитель X должен вести Y уроков предмета Z в классе W в неделю, для подгруппы V
    __tablename__ = 'teacher_subject_requirements'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    # !!! НОВОЕ поле !!!
    subgroup_id = db.Column(db.Integer, db.ForeignKey('subgroups.id'), nullable=False) # Привязка к подгруппе
    # !!! Ключевое изменение: часы теперь для (учитель, предмет, класс, подгруппа) !!!
    teacher_weekly_hours = db.Column(db.Integer, nullable=False) # напр. Учитель Иванов должен вести 3 урока математики в 5А-1 в неделю
    teacher = db.relationship('Teacher', back_populates='teacher_requirements')
    subject = db.relationship('Subject')
    class_ = db.relationship('Class', back_populates='teacher_requirements')
    subgroup = db.relationship('SubGroup') # Новая связь
    # Уникальность: один учитель не может дважды вести один и тот же предмет для одной и той же подгруппы класса
    __table_args__ = (UniqueConstraint('teacher_id', 'subject_id', 'class_id', 'subgroup_id'),)

# Урок (ячейка расписания)
class Lesson(db.Model):
    __tablename__ = 'lessons'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    # !!! Ключевое изменение: связь с подгруппой, а не с классом напрямую !!!
    subgroup_id = db.Column(db.Integer, db.ForeignKey('subgroups.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False) # 0=Пн, 1=Вт, ... 4=Пт
    lesson_number = db.Column(db.Integer, nullable=False) # 1, 2, 3, 4, 5, 6
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    subject = db.relationship('Subject', back_populates='lessons')
    teacher = db.relationship('Teacher', back_populates='lessons')
    subgroup = db.relationship('SubGroup', back_populates='lessons') # Подгруппа идёт на урок
    room = db.relationship('Room', back_populates='lessons')
    # Связь с временными изменениями (один урок может иметь несколько изменений на разные даты)
    temporary_changes = db.relationship('TemporaryChange', back_populates='original_lesson')
    # Ограничение: в один слот (день/урок) один учитель может быть только в одном кабинете
    # -> (teacher_id, day_of_week, lesson_number) должны быть уникальны
    # Ограничение: в один слот (день/урок) один кабинет может быть занят только одним уроком
    # -> (room_id, day_of_week, lesson_number) должны быть уникальны
    # Старое ограничение: в один слот (день/урок) одна подгруппа может быть только на одном уроке
    # -> (subgroup_id, day_of_week, lesson_number) должны быть уникальны
    # НОВОЕ: Разные подгруппы одного класса МОГУТ быть в одном слоте (если у них разные учителя/кабинеты)
    # -> (subgroup_id, day_of_week, lesson_number) больше НЕ уникальны в БД.
    # Проверки будут в логике приложения (services.py).
    # Эти ограничения лучше проверять в логике приложения при создании/изменении урока.
    # SQLAlchemy может помочь с уникальными индексами:
    __table_args__ = (
        Index('idx_lesson_time_teacher', 'day_of_week', 'lesson_number', 'teacher_id', unique=True),
        Index('idx_lesson_time_room', 'day_of_week', 'lesson_number', 'room_id', unique=True),
        # УДАЛЁН: Index('idx_lesson_time_subgroup', 'day_of_week', 'lesson_number', 'subgroup_id', unique=True),
    )

# (Опционально) Для отслеживания замен
class Replacement(db.Model):
    __tablename__ = 'replacements'
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False) # Урок, который заменяется
    original_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False) # Был
    replacement_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False) # На кого заменили
    date = db.Column(db.Date, nullable=False) # Дата, когда действует замена
    reason = db.Column(db.String(255)) # Причина (по желанию)
    lesson = db.relationship('Lesson')
    original_teacher = db.relationship('Teacher', foreign_keys=[original_teacher_id])
    replacement_teacher = db.relationship('Teacher', foreign_keys=[replacement_teacher_id])

# --- НОВАЯ МОДЕЛЬ: Временные изменения ---
class TemporaryChange(db.Model): # <-- Новая модель
    __tablename__ = 'temporary_changes'
    id = db.Column(db.Integer, primary_key=True)
    # Связь с *оригинальным* уроком в расписании
    original_lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    original_lesson = db.relationship('Lesson', foreign_keys=[original_lesson_id], back_populates='temporary_changes')

    # Дата, к которой применяется изменение
    date = db.Column(db.Date, nullable=False)

    # Тип изменения
    change_type = db.Column(db.Enum(ChangeType), nullable=False)

    # Поля для новых значений (не все будут заполнены, в зависимости от типа)
    # Для замены
    new_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    new_teacher = db.relationship('Teacher', foreign_keys=[new_teacher_id])
    # Для переноса
    new_day_of_week = db.Column(db.Integer) # 0-4
    new_lesson_number = db.Column(db.Integer) # 1-6
    new_room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    new_room = db.relationship('Room', foreign_keys=[new_room_id])
    # Причина/комментарий
    reason = db.Column(db.String(255))

    # Оригинальные значения (для отката или справки)
    original_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    original_teacher = db.relationship('Teacher', foreign_keys=[original_teacher_id])
    # original_day_of_week и original_lesson_number уже есть в original_lesson
    original_room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    original_room = db.relationship('Room', foreign_keys=[original_room_id])

    # Индекс для быстрого поиска изменений по дате и уроку
    __table_args__ = (
        Index('idx_temp_change_date_lesson', 'date', 'original_lesson_id'),
    )

# --- НОВАЯ МОДЕЛЬ: Shift ---
class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    classes = db.relationship('Class', back_populates='shift') # <-- Убедитесь, что 'classes' указано здесь

# --- Обновим связь в Lesson ---
Lesson.temporary_changes = db.relationship('TemporaryChange', back_populates='original_lesson')
