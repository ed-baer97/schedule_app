# create_project_fixed.py  ← сохрани под этим именем и запусти
import os

structure = {
    "schedule_app": {
        "utils": {
            "__init__.py": "",
            "excel_loader.py": '''import pandas as pd
from models import db, Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment

def load_class_load_excel(filepath):
    df = pd.read_excel(filepath)

    # Поддержка двух форматов
    if 'Класс' in df.columns and any('Unnamed' in str(col) for col in df.columns[1:]):
        # Горизонтальный формат
        df = df.set_index('Класс').stack().reset_index()
        df.columns = ['class_name', 'subject_name', 'hours_per_week']
    else:
        # Вертикальный формат
        df = df.rename(columns={
            'Класс': 'class_name',
            'Предмет': 'subject_name',
            'Часов в неделю': 'hours_per_week',
            'Количество_часов_в_неделю': 'hours_per_week'
        })[['class_name', 'subject_name', 'hours_per_week']]

    for _, row in df.iterrows():
        class_name = str(row['class_name']).strip()
        subject_name = str(row['subject_name']).strip()
        hours = int(row['hours_per_week'])

        cls = ClassGroup.query.filter_by(name=class_name).first()
        if not cls:
            cls = ClassGroup(name=class_name)
            db.session.add(cls)

        subj = Subject.query.filter_by(name=subject_name).first()
        if not subj:
            subj = Subject(name=subject_name)
            db.session.add(subj)

        db.session.flush()

        load = ClassLoad.query.filter_by(class_id=cls.id, subject_id=subj.id).first()
        if load:
            load.hours_per_week = hours
        else:
            db.session.add(ClassLoad(class_id=cls.id, subject_id=subj.id, hours_per_week=hours))

    db.session.commit()

def load_teacher_assignments_excel(filepath):
    df = pd.read_excel(filepath)
    cols = ['Учитель', 'Предмет', 'Класс', 'Кабинет', 'Количество_часов_в_неделю']
    if not all(c in df.columns for c in cols):
        df.columns = cols

    for _, row in df.iterrows():
        teacher_name = str(row['Учитель']).strip()
        subject_name = str(row['Предмет']).strip()
        class_name = str(row['Класс']).strip()
        cabinet = str(row['Кабинет']) if pd.notna(row['Кабинет']) else ""
        hours = int(row['Количество_часов_в_неделю'])

        teacher = Teacher.query.filter_by(full_name=teacher_name).first()
        if not teacher:
            short = ".".join([n[0]+"." for n in teacher_name.split()[:2]])
            teacher = Teacher(full_name=teacher_name, short_name=short)
            db.session.add(teacher)

        subj = Subject.query.filter_by(name=subject_name).first()
        if not subj:
            subj = Subject(name=subject_name)
            db.session.add(subj)

        cls = ClassGroup.query.filter_by(name=class_name).first()
        if not cls:
            cls = ClassGroup(name=class_name)
            db.session.add(cls)

        db.session.flush()

        assignment = TeacherAssignment.query.filter_by(
            teacher_id=teacher.id, subject_id=subj.id, class_id=cls.id
        ).first()

        if assignment:
            assignment.hours_per_week = hours
            assignment.default_cabinet = cabinet
        else:
            db.session.add(TeacherAssignment(
                teacher_id=teacher.id, subject_id=subj.id, class_id=cls.id,
                hours_per_week=hours, default_cabinet=cabinet
            ))

    db.session.commit()
'''
        },
        "templates": {
            "admin": {
                "base.html": '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Админка расписания</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { padding: 20px; background:#f8f9fa; }</style>
</head>
<body>
    <div class="container-fluid">
        <h1 class="mb-4 text-primary">Админ-панель расписания</h1>
        <div class="btn-group mb-4">
            <a href="/admin" class="btn btn-outline-primary">Главная</a>
            <a href="/admin/upload" class="btn btn-success">Загрузить Excel</a>
            <a href="/admin/clear?confirm=yes" class="btn btn-danger" onclick="return confirm('УДАЛИТЬ ВСЮ БАЗУ?')">Очистить базу</a>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ 'danger' if category=='error' else category }} alert-dismissible fade show">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>''',
                "index.html": '''{% extends "admin/base.html" %}
{% block content %}
<div class="row">
    <div class="col-md-3">
        <h3>Предметы</h3>
        <div class="list-group">
            {% for s in subjects %}
                <a href="/admin/matrix/{{ s.name }}" class="list-group-item list-group-item-action">{{ s.name }}</a>
            {% else %}
                <p class="text-muted">Нет предметов.<br>Загрузите Excel-файлы.</p>
            {% endfor %}
        </div>
    </div>
    <div class="col-md-9">
        <h3>Добро пожаловать!</h3>
        <p>Выберите предмет слева → увидите матрицу «Класс ↔ Учитель ↔ Часы»</p>
    </div>
</div>
{% endblock %}''',
                "subject_matrix.html": '''{% extends "admin/base.html" %}
{% block content %}
<h2 class="mb-4">{{ subject.name }}</h2>
<table class="table table-bordered table-hover align-middle">
    <thead class="table-primary">
        <tr>
            <th rowspan="2" class="align-middle">Класс</th>
            <th colspan="{{ teachers|length }}" class="text-center">Учителя (часы в неделю)</th>
            <th rowspan="2" class="align-middle text-center">Должно</th>
            <th rowspan="2" class="align-middle text-center">Назначено</th>
            <th rowspan="2" class="align-middle text-center">Разница</th>
        </tr>
        <tr>
            {% for t in teachers %}
                <th class="text-center">{{ t.full_name }}</th>
            {% endfor %}
        </tr>
    </thead>
    <tbody>
        {% for row in matrix %}
        <tr {% if row.diff < 0 %}class="table-danger"
            {% elif row.diff == 0 %}class="table-success"
            {% else %}class="table-warning"{% endif %}>
            <td><strong>{{ row.class.name }}</strong></td>
            {% for t in teachers %}
                <td class="text-center">{{ row['teacher_' + t.id|string] }}</td>
            {% endfor %}
            <td class="text-center fw-bold">{{ row.required }}</td>
            <td class="text-center fw-bold">{{ row.assigned }}</td>
            <td class="text-center fw-bold">{{ row.diff }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}''',
                "upload.html": '''{% extends "admin/base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header"><h4>Загрузка данных из Excel</h4></div>
            <div class="card-body">
                <form method="post" enctype="multipart/form-data">
                    <div class="mb-4">
                        <label class="form-label fw-bold">1. Нагрузка классов (сколько часов каждого предмета)</label>
                        <input type="file" name="class_load" class="form-control" accept=".xlsx,.xls" required>
                    </div>
                    <div class="mb-4">
                        <label class="form-label fw-bold">2. Назначения учителей (кто ведёт что)</label>
                        <input type="file" name="teacher_assign" class="form-control" accept=".xlsx,.xls" required>
                    </div>
                    <button type="submit" class="btn btn-primary btn-lg">Загрузить оба файла</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}'''
            },
            "public": {
                "index.html": '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Расписание школы</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container text-center py-5">
        <h1 class="display-4">Расписание школы</h1>
        <p class="lead">Публичный просмотр расписания в разработке</p>
        <a href="/admin" class="btn btn-warning btn-lg">Вход в админ-панель</a>
    </div>
</body>
</html>'''
            }
        },
        "requirements.txt": '''Flask==3.0.3
Flask-SQLAlchemy==3.1.1
pandas==2.2.2
openpyxl==3.1.5
''',
        "config.py": '''import os
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'schedule.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    SECRET_KEY = 'change-me-in-production'
''',
        "models.py": '''from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), unique=True, nullable=False)
    short_name = db.Column(db.String(30))

class ClassGroup(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), unique=True, nullable=False)

class ClassLoad(db.Model):
    __tablename__ = 'class_load'
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint('class_id', 'subject_id', name='uix_class_subject'),)

class TeacherAssignment(db.Model):
    __tablename__ = 'teacher_assignments'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, default=0)
    default_cabinet = db.Column(db.String(10))
    __table_args__ = (db.UniqueConstraint('teacher_id', 'subject_id', 'class_id'),)
''',
        "app.py": '''from flask import Flask, render_template, request, flash, redirect, url_for
import os
from config import Config
from models import db, Subject, ClassGroup, Teacher, ClassLoad, TeacherAssignment
from utils.excel_loader import load_class_load_excel, load_teacher_assignments_excel

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.before_first_request
def create_tables():
    db.create_all()

@app.route('/')
def public_index():
    return render_template('public/index.html')

@app.route('/admin')
def admin_index():
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('admin/index.html', subjects=subjects)

@app.route('/admin/matrix/<subject_name>')
def subject_matrix(subject_name):
    subject = Subject.query.filter_by(name=subject_name).first_or_404()
    classes = ClassGroup.query.order_by(ClassGroup.name).all()
    teachers = Teacher.query.order_by(Teacher.full_name).all()

    matrix = []
    for cls in classes:
        row = {'class': cls}
        load = ClassLoad.query.filter_by(class_id=cls.id, subject_id=subject.id).first()
        row['required'] = load.hours_per_week if load else 0

        assigned = 0
        for t in teachers:
            ass = TeacherAssignment.query.filter_by(teacher_id=t.id, subject_id=subject.id, class_id=cls.id).first()
            hours = ass.hours_per_week if ass else 0
            row[f'teacher_{t.id}'] = hours
            assigned += hours
        row['assigned'] = assigned
        row['diff'] = row['required'] - assigned
        matrix.append(row)

    return render_template('admin/subject_matrix.html',
                           subject=subject, matrix=matrix, teachers=teachers)

@app.route('/admin/upload', methods=['GET', 'POST'])
def upload_files():
    if request.method == 'POST':
        if 'class_load' in request.files and request.files['class_load'].filename:
            f = request.files['class_load']
            path = os.path.join(app.config['UPLOAD_FOLDER'], 'class_load.xlsx')
            f.save(path)
            load_class_load_excel(path)
            flash('Нагрузка классов загружена', 'success')

        if 'teacher_assign' in request.files and request.files['teacher_assign'].filename:
            f = request.files['teacher_assign']
            path = os.path.join(app.config['UPLOAD_FOLDER'], 'teacher_assign.xlsx')
            f.save(path)
            load_teacher_assignments_excel(path)
            flash('Назначения учителей загружены', 'success')

        return redirect(url_for('admin_index'))
    return render_template('admin/upload.html')

@app.route('/admin/clear')
def clear_db():
    if request.args.get('confirm') == 'yes':
        db.drop_all()
        db.create_all()
        flash('База полностью очищена!', 'warning')
    return redirect(url_for('admin_index'))

if __name__ == '__main__':
    app.run(debug=True)
'''
    }
}

def create_structure(base_path, struct):
    for name, content in struct.items():
        path = os.path.join(base_path, name)
        if isinstance(content, dict):
            os.makedirs(path, exist_ok=True)
            create_structure(path, content)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content.lstrip())
            print(f"Создан: {path}")

if __name__ == '__main__':
    project_dir = "schedule_app"
    os.makedirs(project_dir, exist_ok=True)
    create_structure(project_dir, structure)
    print("\nВСЁ ГОТОВО!")
    print(f"Папка проекта: {os.path.abspath(project_dir)}")
    print("\nТеперь выполните:")
    print("   cd schedule_app")
    print("   pip install -r requirements.txt")
    print("   python app.py")
    print("\nОткройте в браузере: http://127.0.0.1:5000/admin")