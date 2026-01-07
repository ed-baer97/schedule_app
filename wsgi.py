"""
WSGI entry point for Gunicorn
Imports the Flask app from app.py
All blueprints are registered in app.py
"""
# Import the Flask app - this will execute all blueprint registrations
# We use a workaround to avoid conflict with app/ package directory
import sys
import os

# Ensure we're importing from the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import app.py module explicitly by loading it as a file
# This avoids the conflict with app/ package directory
import importlib.util
spec = importlib.util.spec_from_file_location("app_main", os.path.join(current_dir, "app.py"))
app_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_main)

# Get the Flask app instance (all blueprints are already registered)
app = app_main.app

if __name__ == "__main__":
    app.run()

