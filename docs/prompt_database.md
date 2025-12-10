# БД для промпта

## Описание

База данных для промпта хранит структуру: **Класс → Предмет → Учителя** и автоматически определяет наличие подгрупп.

## Структура данных

### Правила определения подгрупп:
- Если в данном классе и данном предмете **2+ учителя** → `has_subgroups = True` (предмет делится на подгруппы)
- Если только **1 учитель** → `has_subgroups = False` (подгрупп нет)

### Модели БД:

1. **PromptClassSubject** - основная таблица (класс, предмет, общие часы, есть ли подгруппы)
   - `class_id` - ID класса
   - `subject_id` - ID предмета
   - `shift_id` - ID смены
   - `total_hours_per_week` - общее количество часов в неделю
   - `has_subgroups` - есть ли подгруппы (True/False)

2. **PromptClassSubjectTeacher** - связь между классом-предметом и учителями
   - `prompt_class_subject_id` - ссылка на PromptClassSubject
   - `teacher_id` - ID учителя
   - `hours_per_week` - индивидуальная нагрузка учителя
   - `default_cabinet` - кабинет по умолчанию
   - `is_assigned_to_class` - закреплен ли учитель за классом

## Использование

### Инициализация БД промпта

```bash
# Для всех школ
python init_prompt_db.py

# Для конкретной школы
python init_prompt_db.py <school_id>

# Для конкретной школы и смены
python init_prompt_db.py <school_id> <shift_id>
```

### Программное использование

```python
from utils.prompt_db import build_prompt_database, get_prompt_structure, update_prompt_database

# Построить БД промпта на основе ClassLoad и TeacherAssignment
build_prompt_database(shift_id=1, school_id=1)

# Получить структуру данных для промпта
structure = get_prompt_structure(shift_id=1, school_id=1)
# Возвращает список словарей:
# [
#     {
#         'class_id': 1,
#         'class_name': '5А',
#         'subject_id': 1,
#         'subject_name': 'Математика',
#         'total_hours_per_week': 5,
#         'has_subgroups': False,
#         'teachers': [
#             {
#                 'teacher_id': 1,
#                 'teacher_name': 'Иванов И.И.',
#                 'hours_per_week': 5,
#                 'default_cabinet': '101',
#                 'is_assigned_to_class': False
#             }
#         ]
#     },
#     {
#         'class_id': 1,
#         'class_name': '5А',
#         'subject_id': 2,
#         'subject_name': 'Информатика',
#         'total_hours_per_week': 4,
#         'has_subgroups': True,  # 2 учителя
#         'teachers': [
#             {
#                 'teacher_id': 2,
#                 'teacher_name': 'Смолина А.А.',
#                 'hours_per_week': 2,
#                 'default_cabinet': '201',
#                 'is_assigned_to_class': False
#             },
#             {
#                 'teacher_id': 3,
#                 'teacher_name': 'Шахимова Б.Б.',
#                 'hours_per_week': 2,
#                 'default_cabinet': '202',
#                 'is_assigned_to_class': False
#             }
#         ]
#     }
# ]

# Обновить БД промпта (пересоздать на основе текущих данных)
update_prompt_database(shift_id=1, school_id=1)
```

## Автоматическое создание таблиц

Таблицы `prompt_class_subjects` и `prompt_class_subject_teachers` автоматически создаются при:
- Создании новой БД школы (`create_school_database`)
- Очистке БД школы (`clear_school_database`)

## Интеграция с API

Структура данных из БД промпта может использоваться вместо динамического формирования в `api.py`:

```python
from utils.prompt_db import get_prompt_structure

# Вместо формирования class_subject_structure вручную
class_subject_structure = get_prompt_structure(shift_id=shift_id, school_id=school_id)
context['class_subject_structure'] = class_subject_structure
```

## Обновление данных

БД промпта должна обновляться при:
- Изменении ClassLoad (нагрузка классов)
- Изменении TeacherAssignment (назначения учителей)
- Добавлении/удалении классов, предметов, учителей

Рекомендуется вызывать `build_prompt_database()` или `update_prompt_database()` после любых изменений в данных.

