
import os
from getpass import getpass

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.extensions import db
from app.models.role import Role
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider
from app.security.password_utils import hash_password


@click.command("seed-admin")
@with_appcontext
def seed_admin():
    """Create the initial administrator account."""

    email = click.prompt("Admin email").strip().lower()
    username = click.prompt("Admin username").strip()
    password = getpass("Admin password: ")

    if not email or not username or len(password) < 8:
        raise click.ClickException(
            "Valid email, username, and password (8+ characters) required"
        )

    role = db.session.scalar(
        select(Role).where(
            Role.code == "ADMIN",
            Role.is_active.is_(True),
            Role.is_deleted.is_(False)
        )
    )

    if role is None:
        raise click.ClickException("ADMIN role not found")

    existing = db.session.scalar(
        select(User).where(
            User.email == email,
            User.is_deleted.is_(False)
        )
    )

    if existing:
        click.echo("Account already exists. No changes made.")
        return

    try:
        admin = User(
            username=username,
            email=email,
            password=hash_password(password),
            role_id=role.id,
            status="ACTIVE"
        )

        db.session.add(admin)
        db.session.flush()

        db.session.add(
            UserAuthProvider(
                user_id=admin.id,
                provider="LOCAL",
                provider_user_id=str(admin.id)
            )
        )

        db.session.commit()
        click.echo("Admin account created successfully!")

    except Exception:
        db.session.rollback()
        raise
