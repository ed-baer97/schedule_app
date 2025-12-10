
import sys
import os
import importlib.util
from flask import Flask, session
from flask_login import login_user

# Add project root to path
sys.path.insert(0, os.path.abspath('.'))

def reproduce():
    # Import app.py explicitly
    spec = importlib.util.spec_from_file_location("main_app", "app.py")
    main_app = importlib.util.module_from_spec(spec)
    sys.modules["main_app"] = main_app
    spec.loader.exec_module(main_app)
    app = main_app.app
    db = main_app.db
    User = main_app.User
    School = main_app.School
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost'

    with app.app_context():
        # Create tables
        db.create_all()
        
        # Create school and user
        if not School.query.get(1):
            school = School(name="Test School")
            db.session.add(school)
            db.session.commit()
            
        if not User.query.filter_by(username='admin').first():
            user = User(username='admin', full_name='Admin', role='admin', school_id=1)
            user.set_password('password')
            db.session.add(user)
            db.session.commit()
        
        user = User.query.filter_by(username='admin').first()

        # Login and fetch
        with app.test_client() as client:
            # Login
            client.post('/login', data={'username': 'admin', 'password': 'password'})
            
            # Fetch
            response = client.get('/admin/subjects?subject=Английский язык', follow_redirects=True)
            
            if response.status_code != 200:
                print(f"Failed to fetch page: {response.status_code}")
                return

            html = response.get_data(as_text=True)
            
            print(f"Rendered HTML size: {len(html)} chars")
            print(f"Rendered HTML lines: {len(html.splitlines())}")

            with open('rendered_subjects.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("Saved to rendered_subjects.html")

            # Check for self-reference
            if 'subjects?subject' in html:
                print("FOUND 'subjects?subject' in HTML!")
            else:
                print("Not found 'subjects?subject' in HTML.")

if __name__ == "__main__":
    reproduce()
