"""Create an admin (or superadmin) user, or reset the password of an existing one.

Run from the project root (the folder that contains `app/` and `.env`):

    python -m scripts.create_admin --email admin@ravanai.com
    python -m scripts.create_admin --email admin@ravanai.com --password "Admin@123"
    python -m scripts.create_admin --email boss@ravanai.com --role superadmin
    python -m scripts.create_admin --email admin@ravanai.com --client-id <organization id>
    python -m scripts.create_admin --list-clients

--client-id attaches the admin to an EXISTING organization (so they see its agents,
calls and dashboard). Without it, a new admin gets a new, empty organization.

If the email already exists, its password is reset, the account is re-activated
and (when --role is given) the role is updated. Nothing else is touched.
"""
import argparse
import getpass
import sys
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.agent import Agent
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User

MIN_PASSWORD_LENGTH = 8


def upsert_admin(
    db: Session,
    email: str,
    password: str,
    *,
    first_name: str = "Admin",
    last_name: str = "User",
    organization: str = "Agni",
    role: str = UserRole.ADMIN.value,
    client_id: uuid.UUID | None = None,
) -> tuple[User, bool]:
    """Returns (user, created). Safe to run more than once."""
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("email is not valid")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if role not in (UserRole.ADMIN.value, UserRole.SUPERADMIN.value):
        raise ValueError("role must be 'admin' or 'superadmin'")

    if client_id is not None:
        if role != UserRole.ADMIN.value:
            raise ValueError("--client-id only applies to role 'admin'")
        if db.get(Client, client_id) is None:
            raise ValueError(f"no organization with id {client_id} (use --list-clients)")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user:
        user.email = email
        user.hashed_password = hash_password(password)
        user.is_active = True
        user.role = role
        if client_id is not None:
            user.client_id = client_id
        elif role == UserRole.ADMIN.value and user.client_id is None:
            client = Client(name=organization, email=email)
            db.add(client)
            db.flush()
            user.client_id = client.id
        db.commit()
        return user, False

    if client_id is None and role == UserRole.ADMIN.value:  # a superadmin has no organization
        client = Client(name=organization, email=email)
        db.add(client)
        db.flush()
        client_id = client.id

    user = User(
        email=email,
        hashed_password=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        organization_name=organization,
        phone_country_code="",
        phone_number="",
        role=role,
        is_active=True,
        client_id=client_id,
    )
    db.add(user)
    db.commit()
    return user, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email")
    parser.add_argument("--list-clients", action="store_true", help="show organizations and how many agents each has")
    parser.add_argument("--client-id", type=uuid.UUID, help="attach the admin to this existing organization")
    parser.add_argument("--password", help="omit to be asked (recommended: it stays out of your shell history)")
    parser.add_argument("--first-name", default="Admin")
    parser.add_argument("--last-name", default="User")
    parser.add_argument("--org", default="Agni", help="organization name for a new admin")
    parser.add_argument("--role", choices=["admin", "superadmin"], default="admin")
    args = parser.parse_args()

    from app.db.session import SessionLocal  # imported late so --help works without a database

    if args.list_clients:
        with SessionLocal() as db:
            for c in db.query(Client).order_by(Client.created_at).all():
                agents = db.query(Agent).filter(Agent.client_id == c.id).count()
                print(f"{c.id}  {c.name}  agents={agents}")
        return 0

    if not args.email:
        parser.error("--email is required")
    password = args.password or getpass.getpass("New password: ")

    with SessionLocal() as db:
        try:
            user, created = upsert_admin(
                db, args.email, password,
                first_name=args.first_name, last_name=args.last_name,
                organization=args.org, role=args.role, client_id=args.client_id,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        agents = db.query(Agent).filter(Agent.client_id == user.client_id).count() if user.client_id else 0
        print(f"organization: {user.client_id}  (agents visible to this user: {agents})")
    print(f"{'Created' if created else 'Updated'} {user.role}: {user.email}")
    print("You can now log in with POST /api/v1/auth/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())