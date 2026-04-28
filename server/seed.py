"""Initial setup: create admin user and seed data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import User
from auth import hash_password


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        if User.query.first():
            print('Already seeded.')
            return

        admin = User(
            username='admin',
            password_hash=hash_password('admin'),
            role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        print('Created admin user (admin/admin)')


if __name__ == '__main__':
    seed()
