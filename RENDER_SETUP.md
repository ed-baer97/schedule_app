# Настройка Python версии на Render

## Проблема

Render может автоматически выбрать Python 3.13+, что может вызвать проблемы с некоторыми пакетами (numpy, pandas).

## Решение

**В настройках сервиса на Render:**

1. Зайдите в ваш сервис на Render
2. Откройте раздел **"Settings"**
3. Найдите секцию **"Environment"**
4. Найдите поле **"Python Version"** или **"PYTHON_VERSION"**
5. Установите значение: **`3.11.0`**
6. Сохраните изменения
7. Перезапустите деплой

## Альтернативный способ

Если в настройках нет поля "Python Version", добавьте переменную окружения:

- **Key**: `PYTHON_VERSION`
- **Value**: `3.11.0`

## Проверка

После перезапуска деплоя в логах должно быть:
```
==> Installing Python version 3.11.0...
==> Using Python version 3.11.0 via environment variable PYTHON_VERSION
```

Вместо:
```
==> Installing Python version 3.13.4...
==> Using Python version 3.13.4 (default)
```

## Правильный формат деплоя

Деплой должен выглядеть так:
```
==> Downloading cache...
==> Cloning from https://github.com/...
==> Installing Python version 3.11.0...
==> Using Python version 3.11.0 via environment variable PYTHON_VERSION
==> Running build command 'pip install --upgrade pip && pip install -r requirements.txt'...
```

## Почему Python 3.11?

- Python 3.11 имеет лучшую совместимость с numpy, pandas
- Меньше проблем с компиляцией пакетов
- Более стабильная работа на Render

