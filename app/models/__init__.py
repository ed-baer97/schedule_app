"""
Модели приложения
"""
from app.models.school import (
    Subject, Teacher, ClassGroup, ClassLoad, TeacherAssignment,
    PermanentSchedule, TemporarySchedule, Shift, ShiftClass, ScheduleSettings,
    PromptClassSubject, PromptClassSubjectTeacher,
    AIConversation, AIConversationMessage, SubjectCabinet, Cabinet, CabinetTeacher,
    _get_teacher_classes_table, _init_teacher_classes_relationship
)
from app.models.system import School, User

__all__ = [
    # School models
    'Subject', 'Teacher', 'ClassGroup', 'ClassLoad', 'TeacherAssignment',
    'PermanentSchedule', 'TemporarySchedule', 'Shift', 'ShiftClass', 'ScheduleSettings',
    'PromptClassSubject', 'PromptClassSubjectTeacher',
    'AIConversation', 'AIConversationMessage', 'SubjectCabinet', 'Cabinet', 'CabinetTeacher',
    '_get_teacher_classes_table', '_init_teacher_classes_relationship',
    # System models
    'School', 'User'
]
