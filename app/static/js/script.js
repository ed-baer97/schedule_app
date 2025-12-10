// Функции для работы с модальными окнами

// Модальное окно для ячейки расписания
function openCellModal(lessonData, classId, dayIndex, lessonSlot) {
    // Заполняем данные в модальном окне
    document.getElementById('cellModal').style.display = 'block';
    
    // Обновляем информацию о ячейке
    const className = classesList.find(cls => cls.id == classId)?.name || 'Неизвестный класс';
    const dayName = getDayNameFull(dayIndex);
    
    document.getElementById('cell-class-name').textContent = className;
    document.getElementById('cell-day-name').textContent = dayName;
    document.getElementById('cell-lesson-slot').textContent = lessonSlot;
    
    // Очищаем предыдущий список уроков в ячейке
    const lessonsList = document.getElementById('cell-lessons-list');
    lessonsList.innerHTML = '';
    
    // Добавляем уроки в список (если есть уроки в этой ячейке)
    if (lessonData && lessonData.length > 0) {
        lessonData.forEach(lesson => {
            const lessonDiv = document.createElement('div');
            lessonDiv.className = 'cell-lesson-item';
            lessonDiv.innerHTML = `
                <div class="lesson-info">
                    <span class="subject">${lesson.subject_name}</span>
                    <span class="teacher">${lesson.teacher_name}</span>
                    <span class="room">${lesson.room_name}</span>
                    <span class="subgroup">${lesson.subgroup_name || 'Все'}</span>
                </div>
                <div class="lesson-actions">
                    <button onclick="openLessonModal(${lesson.id})" class="edit-lesson-btn">Редактировать</button>
                    <button onclick="deleteLesson(${lesson.id})" class="delete-lesson-btn">Удалить</button>
                </div>
            `;
            lessonsList.appendChild(lessonDiv);
        });
    } else {
        lessonsList.innerHTML = '<p>В этой ячейке нет уроков</p>';
    }
}

// Модальное окно для конкретного урока
function openLessonModal(lessonId) {
    // Находим урок по ID
    const allLessons = [...scheduleData, ...temporaryChangesData.map(change => ({
        ...change,
        is_temporary: true
    }))];
    
    const lesson = allLessons.find(l => l.id == lessonId);
    if (!lesson) return;
    
    // Заполняем форму редактирования
    document.getElementById('lessonModal').style.display = 'block';
    document.getElementById('edit-lesson-id').value = lesson.id;
    document.getElementById('edit-subject').value = lesson.subject_id || '';
    document.getElementById('edit-teacher').value = lesson.teacher_id || '';
    document.getElementById('edit-subgroup').value = lesson.subgroup_id || '';
    document.getElementById('edit-room').value = lesson.room_id || '';
    
    // Если это временные изменения, показываем дополнительные поля
    if (lesson.is_temporary) {
        document.getElementById('lesson-date').value = lesson.date || '';
        document.getElementById('temp-change-type').value = lesson.change_type || '';
        document.getElementById('temp-change-reason').value = lesson.reason || '';
    }
}

// Закрытие модальных окон
function closeModals() {
    document.getElementById('cellModal').style.display = 'none';
    document.getElementById('lessonModal').style.display = 'none';
}

// Редактирование урока
async function editLesson(event) {
    event.preventDefault();
    
    const lessonId = document.getElementById('edit-lesson-id').value;
    const subjectId = document.getElementById('edit-subject').value;
    const teacherId = document.getElementById('edit-teacher').value;
    const subgroupId = document.getElementById('edit-subgroup').value;
    const roomId = document.getElementById('edit-room').value;
    
    try {
        const response = await fetch(`/api/lessons/${lessonId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                subject_id: parseInt(subjectId),
                teacher_id: parseInt(teacherId),
                subgroup_id: parseInt(subgroupId) || null,
                room_id: parseInt(roomId)
            })
        });
        
        if (response.ok) {
            addChatMessage('Урок успешно отредактирован', 'bot');
            closeModals();
            // Перезагружаем расписание
            if (selectedDate && currentShift) {
                loadScheduleDataForDate(selectedDate, currentShift);
            } else if (currentShift) {
                loadScheduleData(currentShift);
            }
        } else {
            const errorData = await response.json();
            addChatMessage(`Ошибка редактирования: ${errorData.message || 'Неизвестная ошибка'}`, 'bot');
        }
    } catch (error) {
        addChatMessage(`Ошибка редактирования: ${error.message}`, 'bot');
    }
}

// Удаление урока
async function deleteLesson(lessonId) {
    if (!confirm('Вы уверены, что хотите удалить этот урок?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/lessons/${lessonId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            addChatMessage('Урок успешно удален', 'bot');
            closeModals();
            // Перезагружаем расписание
            if (selectedDate && currentShift) {
                loadScheduleDataForDate(selectedDate, currentShift);
            } else if (currentShift) {
                loadScheduleData(currentShift);
            }
        } else {
            const errorData = await response.json();
            addChatMessage(`Ошибка удаления: ${errorData.message || 'Неизвестная ошибка'}`, 'bot');
        }
    } catch (error) {
        addChatMessage(`Ошибка удаления: ${error.message}`, 'bot');
    }
}

// Добавление подгруппы
async function addSubgroup() {
    const className = prompt('Введите название новой подгруппы:');
    if (!className) return;
    
    try {
        const response = await fetch('/api/subgroups', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: className
            })
        });
        
        if (response.ok) {
            addChatMessage('Подгруппа успешно добавлена', 'bot');
            // Перезагружаем список подгрупп
            const subgroupsResponse = await fetch('/api/subgroups');
            subgroupsList = await subgroupsResponse.json();
        } else {
            const errorData = await response.json();
            addChatMessage(`Ошибка добавления подгруппы: ${errorData.message || 'Неизвестная ошибка'}`, 'bot');
        }
    } catch (error) {
        addChatMessage(`Ошибка добавления подгруппы: ${error.message}`, 'bot');
    }
}

// Изменение учителя
async function changeTeacher(lessonId) {
    const newTeacherId = prompt('Введите ID нового учителя:');
    if (!newTeacherId) return;
    
    try {
        const response = await fetch(`/api/lessons/${lessonId}/teacher`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                teacher_id: parseInt(newTeacherId)
            })
        });
        
        if (response.ok) {
            addChatMessage('Учитель успешно изменен', 'bot');
            closeModals();
            // Перезагружаем расписание
            if (selectedDate && currentShift) {
                loadScheduleDataForDate(selectedDate, currentShift);
            } else if (currentShift) {
                loadScheduleData(currentShift);
            }
        } else {
            const errorData = await response.json();
            addChatMessage(`Ошибка изменения учителя: ${errorData.message || 'Неизвестная ошибка'}`, 'bot');
        }
    } catch (error) {
        addChatMessage(`Ошибка изменения учителя: ${error.message}`, 'bot');
    }
}

// Изменение предмета
async function changeSubject(lessonId) {
    const newSubjectId = prompt('Введите ID нового предмета:');
    if (!newSubjectId) return;
    
    try {
        const response = await fetch(`/api/lessons/${lessonId}/subject`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                subject_id: parseInt(newSubjectId)
            })
        });
        
        if (response.ok) {
            addChatMessage('Предмет успешно изменен', 'bot');
            closeModals();
            // Перезагружаем расписание
            if (selectedDate && currentShift) {
                loadScheduleDataForDate(selectedDate, currentShift);
            } else if (currentShift) {
                loadScheduleData(currentShift);
            }
        } else {
            const errorData = await response.json();
            addChatMessage(`Ошибка изменения предмета: ${errorData.message || 'Неизвестная ошибка'}`, 'bot');
        }
    } catch (error) {
        addChatMessage(`Ошибка изменения предмета: ${error.message}`, 'bot');
    }
}

// Добавляем обработчики событий для модальных окон
document.addEventListener('DOMContentLoaded', function() {
    // Закрытие модальных окон при клике вне их области
    window.onclick = function(event) {
        const cellModal = document.getElementById('cellModal');
        const lessonModal = document.getElementById('lessonModal');
        
        if (event.target === cellModal) {
            cellModal.style.display = 'none';
        }
        if (event.target === lessonModal) {
            lessonModal.style.display = 'none';
        }
    };
    
    // Закрытие модальных окон по клавише Escape
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeModals();
        }
    });
    
    // Привязываем обработчики к формам
    const lessonForm = document.getElementById('lesson-form');
    if (lessonForm) {
        lessonForm.addEventListener('submit', editLesson);
    }
});