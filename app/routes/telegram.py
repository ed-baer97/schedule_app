"""
Telegram функции для отправки расписания
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from app.core.db_manager import school_db_context
from app.core.auth import admin_required, get_current_school_id
from app.services.telegram_bot import send_schedule_to_all_teachers, send_temporary_changes_to_all_teachers

telegram_bp = Blueprint('telegram', __name__)


@telegram_bp.route('/admin/telegram/send-schedule', methods=['POST'])
@admin_required
def send_schedule_telegram():
    """Отправить расписание всем учителям через Telegram"""
    data = request.get_json()
    shift_id = data.get('shift_id') if data else None
    if shift_id:
        try:
            shift_id = int(shift_id)
        except (ValueError, TypeError):
            shift_id = None
    
    try:
        school_id = get_current_school_id()
        if not school_id:
            return jsonify({'success': False, 'error': 'Не удалось определить школу'}), 400
        
        with school_db_context(school_id):
            results = send_schedule_to_all_teachers(shift_id, school_id=school_id)
        
        if 'errors' in results and isinstance(results['errors'], list) and results['errors']:
            error_msg = results['errors'][0] if isinstance(results['errors'][0], str) else 'Ошибка при отправке'
        else:
            error_msg = None
        
        return jsonify({
            'success': True,
            'sent': results.get('success', 0),
            'failed': results.get('failed', 0),
            'errors': results.get('errors', []),
            'message': f"Отправлено: {results.get('success', 0)}, Ошибок: {results.get('failed', 0)}"
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Ошибка отправки: {error_msg}'}), 500


@telegram_bp.route('/admin/telegram/send-temporary', methods=['POST'])
@admin_required
def send_temporary_telegram():
    """Отправить временное расписание через Telegram"""
    school_id = get_current_school_id()
    if not school_id:
        return jsonify({'success': False, 'error': 'Школа не найдена'}), 400
    
    data = request.get_json()
    date_str = data.get('date')
    
    if not date_str:
        return jsonify({'success': False, 'error': 'Date parameter is required'}), 400
    
    try:
        schedule_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        school_id = get_current_school_id()
        if not school_id:
            return jsonify({'success': False, 'error': 'Не удалось определить школу'}), 400
        
        with school_db_context(school_id):
            results = send_temporary_changes_to_all_teachers(schedule_date, school_id=school_id)
        return jsonify({
            'success': True,
            'sent': results['success'],
            'failed': results['failed'],
            'no_changes': results['no_changes'],
            'errors': results['errors']
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        return jsonify({'success': False, 'error': error_msg}), 500

