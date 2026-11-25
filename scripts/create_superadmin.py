"""
Create (or promote) a superadmin user.

Place this file at: scripts/create_superadmin.py

Usage (from project root):
    python -m scripts.create_superadmin
    python -m scripts.create_superadmin --email admin@example.com --first-name Super --last-name Admin

Password is prompted securely (not echoed) unless SUPERADMIN_PASSWORD env var is set.
If the email already exists, the user is promoted to superadmin (and client_id cleared)
only when --promote is passed.
"""
import argparse
import getpass
import os
import sys

import app.models  # noqa: F401  (registers all mappers so relationships resolve)
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.roles import UserRole
from app.models.user import User


def main() -> int:
    p = argparse.ArgumentParser(description="Create a superadmin user")
    p.add_argument("--email", default=os.getenv("SUPERADMIN_EMAIL"))
    p.add_argument("--first-name", default=os.getenv("SUPERADMIN_FIRST_NAME", "Super"))
    p.add_argument("--last-name", default=os.getenv("SUPERADMIN_LAST_NAME", "Admin"))
    p.add_argument("--phone-country-code", default="+91")
    p.add_argument("--phone-number", default="0000000000")
    p.add_argument("--promote", action="store_true",
                   help="If the email already exists, promote that user to superadmin")
    args = p.parse_args()

    email = (args.email or input("Email: ")).strip().lower()
    if not email:
        print("Email is required.")
        return 1

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()

        if existing:
            if not args.promote:
                print(f"User {email} already exists (role={existing.role}). "
                      f"Re-run with --promote to make them superadmin.")
                return 1
            existing.role = UserRole.SUPERADMIN.value
            existing.client_id = None
            existing.is_active = True
            db.commit()
            print(f"Promoted {email} to superadmin.")
            return 0

        password = os.getenv("SUPERADMIN_PASSWORD") or getpass.getpass("Password: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            return 1
        if not os.getenv("SUPERADMIN_PASSWORD") and password != getpass.getpass("Confirm password: "):
            print("Passwords do not match.")
            return 1

        user = User(
            email=email,
            hashed_password=hash_password(password),
            first_name=args.first_name,
            last_name=args.last_name,
            organization_name="Agni",
            phone_country_code=args.phone_country_code,
            phone_number=args.phone_number,
            role=UserRole.SUPERADMIN.value,
            is_active=True,
            client_id=None,  # superadmins aren't tied to an organization
        )
        db.add(user)
        db.commit()
        print(f"Superadmin created: {email}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Failed: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
