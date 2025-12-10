# Будет создан позже
"""
Модели данных приложения
"""
from .models.system import School, User
from .models.school import (
    Subject, ClassGroup, Teacher, ClassLoad, TeacherAssignment,
    PermanentSchedule, TemporarySchedule, Shift, ScheduleSettings,
    PromptClassSubject, PromptClassSubjectTeacher, SubjectCabinet,
    Cabinet, CabinetTeacher, AIConversation, AIConversationMessage
)

__all__ = [
    'School', 'User',
    'Subject', 'ClassGroup', 'Teacher', 'ClassLoad', 'TeacherAssignment',
    'PermanentSchedule', 'TemporarySchedule', 'Shift', 'ScheduleSettings',
    'PromptClassSubject', 'PromptClassSubjectTeacher', 'SubjectCabinet',
    'Cabinet', 'CabinetTeacher', 'AIConversation', 'AIConversationMessage'
]

