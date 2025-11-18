# app/ai_assistant.py

def handle_command_via_api(command_text):
    """
    Заглушка для обработки команды через внешний ИИ API.
    Возвращает структурированный словарь, как если бы его вернул реальный ИИ-сервис.
    """
    command_lower = command_text.lower().strip()

    # Пример команды: "найди замену для урока 100"
    if "найди замену" in command_lower and "урок" in command_lower:
        # Извлекаем ID урока (упрощённый парсинг)
        import re
        match = re.search(r"урок\s+(\d+)", command_lower)
        if match:
            lesson_id = int(match.group(1))
            # Имитируем ответ ИИ: нашли урок, нужно предложить замены
            # В реальности ИИ анализировал бы расписание и специализации
            # Предположим, у нас есть учителя с ID 101 и 102, которые могут вести предмет урока 100
            return {
                "action": "find_replacement",
                "details": {
                    "lesson_id": lesson_id,
                    # В реальности список пришёл бы из БД, здесь фиктивные ID
                    "possible_replacements": [
                        {"teacher_id": 101, "teacher_name": "Учитель Замены 1"},
                        {"teacher_id": 102, "teacher_name": "Учитель Замены 2"}
                    ]
                }
            }
        else:
            return {"action": "error", "details": {"error_message": "Не указан ID урока для поиска замены."}}

    # Пример команды: "перемести урок 100 в среду на 3 урок"
    elif "перемести урок" in command_lower:
        import re
        match = re.search(r"урок\s+(\d+)", command_lower)
        if match:
            lesson_id = int(match.group(1))
            # Имитируем, что ИИ сказал "переместить в среду (день 2), на 3 урок (номер 3)"
            # В реальности ИИ проверял бы доступность слотов
            return {
                "action": "move_lesson",
                "details": {
                    "lesson_id": lesson_id,
                    "day_of_week": 2, # Среда
                    "lesson_number": 3
                    # new_teacher_id и new_room_id могут быть указаны, если ИИ предлагает их
                }
            }
        else:
            return {"action": "error", "details": {"error_message": "Не указан ID урока для перемещения."}}

    # Пример команды: "найди слот для математики 5а в среду"
    elif "найди слот" in command_lower:
        # Имитируем, что ИИ нашёл свободные слоты
        # В реальности ИИ искал бы по БД
        return {
            "action": "suggest_slot",
            "details": {
                "slots": [
                    {"day": 2, "slot": 4, "teacher_id": 103, "room_id": 201}, # Ср, 4 урок
                    {"day": 2, "slot": 5, "teacher_id": 103, "room_id": 201}, # Ср, 5 урок
                ]
            }
        }

    # Если команда не распознана
    return {"action": "error", "details": {"error_message": f"Команда '{command_text}' не распознана или не поддерживается заглушкой."}}
