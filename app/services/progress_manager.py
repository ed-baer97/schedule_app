import threading

# Global dictionary to store progress
# Key: shift_id (or some unique task identifier)
# Value: dict with 'percent', 'stage', 'step'
_progress_lock = threading.Lock()
GENERATION_PROGRESS = {}

def update_progress(shift_id, percent, stage, step=1):
    """Update progress for a given shift generation task"""
    with _progress_lock:
        GENERATION_PROGRESS[shift_id] = {
            'percent': percent,
            'stage': stage,
            'step': step
        }

def get_progress(shift_id):
    """Get current progress for a shift"""
    with _progress_lock:
        return GENERATION_PROGRESS.get(shift_id, {'percent': 0, 'stage': 'Инициализация...', 'step': 0})

def clear_progress(shift_id):
    """Clear progress data (e.g. on completion)"""
    with _progress_lock:
        if shift_id in GENERATION_PROGRESS:
            del GENERATION_PROGRESS[shift_id]
