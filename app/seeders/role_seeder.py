
from sqlalchemy import select

from app.extensions import db
from app.models.role import Role


def seed_roles():
    default_roles = [
        {"name": "Admin", "code": "ADMIN"},
        {"name": "User", "code": "USER"},
    ]

    for role_data in default_roles:
        existing = db.session.scalar(
            select(Role).where(
                Role.code == role_data["code"]
            )
        )

        if existing is None:
            role = Role(
                name=role_data["name"],
                code=role_data["code"],
                is_active=True,
            )
            db.session.add(role)
            print(f"Created role: {role_data['code']}")
        else:
            print(f"Role already exists: {role_data['code']}")

    db.session.commit()

    print("Role seeding completed successfully!")
    