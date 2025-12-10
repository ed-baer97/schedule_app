"""
Пример использования ScheduleSolver для составления расписания
"""
from app.services.schedule_solver import (
    ScheduleSolver, ClassSubjectRequirement, LessonSlot
)

# Пример 1: Простое расписание для одного класса
requirements = [
    ClassSubjectRequirement(
        class_id=1,
        subject_id=1,  # Математика
        total_hours_per_week=5,
        has_subgroups=False,
        teachers=[{'teacher_id': 1, 'default_cabinet': '101', 'hours_per_week': 5}]
    ),
    ClassSubjectRequirement(
        class_id=1,
        subject_id=2,  # Русский язык
        total_hours_per_week=4,
        has_subgroups=False,
        teachers=[{'teacher_id': 2, 'default_cabinet': '102', 'hours_per_week': 4}]
    ),
]

# Создаем solver
solver = ScheduleSolver(
    class_subject_requirements=requirements,
    study_days=[1, 2, 3, 4, 5],  # Понедельник-пятница
    max_lessons_per_day={1: 6, 2: 6, 3: 6, 4: 6, 5: 6}  # 6 уроков в день
)

# Решаем
success, schedule, warnings = solver.solve()

if success:
    print(f"✅ Расписание успешно создано! Всего уроков: {len(schedule)}")
    for lesson in schedule:
        print(f"  День {lesson.day_of_week}, Урок {lesson.lesson_number}: "
              f"Класс {lesson.class_id}, Предмет {lesson.subject_id}, "
              f"Учитель {lesson.teacher_id}, Кабинет {lesson.cabinet}")
else:
    print(f"⚠️ Не удалось разместить все уроки")
    for warning in warnings:
        print(f"  {warning}")

# Пример 2: Расписание с подгруппами
requirements_with_subgroups = [
    ClassSubjectRequirement(
        class_id=1,
        subject_id=3,  # Информатика
        total_hours_per_week=2,
        has_subgroups=True,  # Есть подгруппы!
        teachers=[
            {'teacher_id': 3, 'default_cabinet': '201', 'hours_per_week': 1},
            {'teacher_id': 4, 'default_cabinet': '202', 'hours_per_week': 1}
        ]
    ),
]

solver2 = ScheduleSolver(
    class_subject_requirements=requirements_with_subgroups,
    study_days=[1, 2, 3, 4, 5],
    max_lessons_per_day={1: 6, 2: 6, 3: 6, 4: 6, 5: 6}
)

success2, schedule2, warnings2 = solver2.solve()

if success2:
    print(f"\n✅ Расписание с подгруппами создано!")
    # Подгруппы должны быть в одно время
    for lesson in schedule2:
        print(f"  День {lesson.day_of_week}, Урок {lesson.lesson_number}: "
              f"Учитель {lesson.teacher_id}, Кабинет {lesson.cabinet}")

