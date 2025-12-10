"""
Роуты для настроек Telegram бота в админ-панели
"""
from flask import Blueprint, request, jsonify, render_template, current_app
import requests
from app.core.db_manager import db
from app.core.auth import admin_required, get_current_school_id
from app.models.system import School

telegram_settings_bp = Blueprint('telegram_settings', __name__)


@telegram_settings_bp.route('/admin/api-settings')
@admin_required
def api_settings_page():
    """Страница настроек Telegram бота"""
    school_id = get_current_school_id()
    if not school_id:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    school = db.session.query(School).filter_by(id=school_id).first()
    if not school:
        from flask import flash, redirect, url_for
        flash('Ошибка: школа не найдена', 'danger')
        return redirect(url_for('logout'))
    
    return render_template('admin/api_settings.html', school=school)


@telegram_settings_bp.route('/admin/api-settings/save', methods=['POST'])
@admin_required
def save_api_settings():
    """Сохранить настройки Telegram"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    telegram_token = data.get('telegram_token', '').strip()
    
    school = db.session.query(School).filter_by(id=school_id).first()
    if not school:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 404
    
    try:
        # Сохраняем настройки Telegram
        if not telegram_token:
            school.telegram_bot_token = None
        else:
            # Проверяем формат токена
            if ':' not in telegram_token or len(telegram_token) < 20:
                return jsonify({'success': False, 'error': 'Неверный формат токена Telegram. Токен должен быть в формате: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz'}), 400
            school.telegram_bot_token = telegram_token
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Настройки Telegram успешно сохранены'
        })
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@telegram_settings_bp.route('/admin/api-settings/test-telegram', methods=['POST'])
@admin_required
def test_telegram_token():
    """Тестировать токен Telegram"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    telegram_token = data.get('telegram_token', '').strip()
    
    if not telegram_token:
        return jsonify({'success': False, 'error': 'Токен Telegram не указан'}), 400
    
    # Проверяем формат токена
    if ':' not in telegram_token or len(telegram_token) < 20:
        return jsonify({
            'success': False,
            'error': 'Неверный формат токена. Токен должен быть в формате: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz'
        }), 400
    
    try:
        # Проверяем токен через Telegram API
        api_url = current_app.config.get('TELEGRAM_API_URL', 'https://api.telegram.org/bot')
        test_url = f"{api_url}{telegram_token}/getMe"
        
        response = requests.get(test_url, timeout=10)
        
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Неверный токен. Telegram API вернул ошибку: {response.status_code}'
            }), 400
        
        result = response.json()
        if not result.get('ok'):
            error_desc = result.get('description', 'Неизвестная ошибка')
            return jsonify({
                'success': False,
                'error': f'Неверный токен: {error_desc}'
            }), 400
        
        # Токен валидный, возвращаем информацию о боте
        bot_info = result.get('result', {})
        return jsonify({
            'success': True,
            'message': f'Токен валиден! Бот: @{bot_info.get("username", "неизвестно")} ({bot_info.get("first_name", "")})',
            'bot_info': {
                'username': bot_info.get('username', ''),
                'first_name': bot_info.get('first_name', ''),
                'id': bot_info.get('id')
            }
        })
    except requests.exceptions.RequestException as e:
        return jsonify({
            'success': False,
            'error': f'Ошибка при проверке токена: {str(e)}'
        }), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Ошибка при тестировании: {str(e)}'
        }), 500

