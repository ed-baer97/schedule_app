"""
WSGI entry point for Gunicorn
Explicitly loads app.py to avoid conflict with app/ package directory
"""
import sys
import os
import importlib.util

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure BASE_DIR is in Python path
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Path to app.py file
app_py_file = os.path.join(BASE_DIR, 'app.py')

if not os.path.exists(app_py_file):
    raise FileNotFoundError(f"app.py not found at {app_py_file}")

# Load app.py explicitly as a module to avoid conflict with app/ directory
spec = importlib.util.spec_from_file_location("app_main_module", app_py_file)

if spec is None:
    raise ImportError(f"Failed to create spec for {app_py_file}")

if spec.loader is None:
    raise ImportError(f"Failed to get loader for {app_py_file}")

# Create and execute the module
app_main = importlib.util.module_from_spec(spec)
sys.modules['app_main_module'] = app_main  # Register in sys.modules

# Execute the module - this will run all code in app.py including blueprint registration
spec.loader.exec_module(app_main)

# Get the Flask app instance
if not hasattr(app_main, 'app'):
    raise AttributeError("app.py does not contain 'app' variable")

app = app_main.app

# Make sure app is a Flask instance
if app is None:
    raise ValueError("app is None")

# Export for Gunicorn
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

