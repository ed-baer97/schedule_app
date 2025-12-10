import os
# BASE_DIR указывает на корень проекта (на уровень выше app/)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

class Config:
    # SQLALCHEMY_DATABASE_URI больше не используется напрямую
    # БД управляется через db_manager.py (system.db и databases/school_*.db)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    SECRET_KEY = 'change-me-in-production'
    
    # Telegram Bot API настройки
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8266665318:AAH9vyLlel7UoAWT4iyRBqWCIbnpLkEnvcM')  # Токен бота из @BotFather
    TELEGRAM_API_URL = 'https://api.telegram.org/bot'
    
    # AI API настройки (Qwen, DeepSeek, OpenAI или Yandex GPT)
    # Приоритет: Qwen > DeepSeek > OpenAI > Yandex GPT
    # Можно установить здесь напрямую или через переменные окружения
    
    # Qwen (Alibaba Cloud - рекомендуется, есть бесплатный период)
    # Используется DASHSCOPE_API_KEY (официальное название ключа для DashScope)
    QWEN_API_KEY = os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('QWEN_API_KEY') or os.environ.get('AI_API_KEY', '') or 'sk-bc439a49a48144c28b4de473f9c07b7b'
    # Модели Qwen:
    # - qwen-plus: Хороший баланс качества и скорости - РЕКОМЕНДУЕТСЯ для общих задач
    # - qwen3-max: Лучшая для сложных задач (составление расписания, анализ данных)
    # - qwen-max: Предыдущая версия (также хороша)
    # - qwen-turbo: Быстрая, но менее мощная (для простых задач)
    # - qwen3-coder-plus: Специализированная модель для работы с кодом - РЕКОМЕНДУЕТСЯ для улучшения алгоритмов
    QWEN_MODEL = os.environ.get('QWEN_MODEL', 'qwen-plus')  # Рекомендуется qwen-plus для составления расписания
    QWEN_CODER_MODEL = os.environ.get('QWEN_CODER_MODEL', 'qwen3-coder-plus')  # Модель для работы с кодом
    
    # DeepSeek (альтернатива - есть бесплатный период)
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('AI_API_KEY', '') or 'sk-e9520bedb6464f4d8e16c64c50be286e'
    DEEPSEEK_MODEL = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
    
    # OpenAI (альтернатива)
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
    
    # Yandex GPT (альтернатива)
    YANDEX_GPT_API_KEY = os.environ.get('YANDEX_GPT_API_KEY', '')
    YANDEX_GPT_FOLDER_ID = os.environ.get('YANDEX_GPT_FOLDER_ID', '')
    YANDEX_GPT_MODEL = os.environ.get('YANDEX_GPT_MODEL', 'yandexgpt-lite')

