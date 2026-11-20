"""Authentication API tests using an isolated in-memory SQLite database."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.db.session import Base, get_db
from app.main import app
from app.models import Client, User


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


for table in Base.metadata.tables.values():
    for column in table.columns:
        if (
            column.server_default is not None
            and "::jsonb" in str(column.server_default.arg).lower()
        ):
            column.server_default = None


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def env():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = Session()
    client_org = Client(name="Authentication Test Org")
    db.add(client_org)
    db.flush()

    user = User(
        email="auth-test@example.com",
        hashed_password=hash_password("correct-password"),
        first_name="Test",
        last_name="User",
        organization_name="Authentication Test Org",
        phone_country_code="+91",
        phone_number="9876543210",
        role="admin",
        client_id=client_org.id,
        is_active=True,
    )

    inactive_user = User(
        email="inactive-test@example.com",
        hashed_password=hash_password("correct-password"),
        first_name="Inactive",
        last_name="User",
        organization_name="Authentication Test Org",
        phone_country_code="+91",
        phone_number="9876543211",
        role="user",
        client_id=client_org.id,
        is_active=False,
    )

    db.add_all([user, inactive_user])
    db.commit()
    db.refresh(user)
    db.refresh(inactive_user)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    try:
        with TestClient(app) as test_client:
            yield {
                "client": test_client,
                "user": user,
                "inactive_user": inactive_user,
                "db": db,
            }
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()
        Base.metadata.drop_all(engine)


def test_login_success(env):
    response = env["client"].post(
        "/api/v1/auth/login",
        json={
            "email": "auth-test@example.com",
            "password": "correct-password",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "auth-test@example.com"


def test_login_rejects_wrong_password(env):
    response = env["client"].post(
        "/api/v1/auth/login",
        json={
            "email": "auth-test@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401


def test_login_rejects_unknown_email(env):
    response = env["client"].post(
        "/api/v1/auth/login",
        json={
            "email": "unknown@example.com",
            "password": "correct-password",
        },
    )

    assert response.status_code == 401


def test_login_rejects_inactive_user(env):
    response = env["client"].post(
        "/api/v1/auth/login",
        json={
            "email": "inactive-test@example.com",
            "password": "correct-password",
        },
    )

    assert response.status_code == 403


def test_me_requires_authentication(env):
    response = env["client"].get("/api/v1/auth/me")

    assert response.status_code in (401, 403)


def test_me_returns_authenticated_user(env):
    token = create_access_token(
        str(env["user"].id),
        env["user"].role,
    )

    response = env["client"].get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "auth-test@example.com"


def test_me_rejects_refresh_token(env):
    token = create_refresh_token(
        str(env["user"].id),
        env["user"].role,
    )

    response = env["client"].get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_me_rejects_inactive_user(env):
    token = create_access_token(
        str(env["inactive_user"].id),
        env["inactive_user"].role,
    )

    response = env["client"].get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_refresh_success(env):
    token = create_refresh_token(
        str(env["user"].id),
        env["user"].role,
    )

    response = env["client"].post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "auth-test@example.com"


def test_refresh_rejects_access_token(env):
    token = create_access_token(
        str(env["user"].id),
        env["user"].role,
    )

    response = env["client"].post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token},
    )

    assert response.status_code == 401


def test_refresh_rejects_invalid_token(env):
    response = env["client"].post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )

    assert response.status_code == 401


def test_refresh_rejects_inactive_user(env):
    token = create_refresh_token(
        str(env["inactive_user"].id),
        env["inactive_user"].role,
    )

    response = env["client"].post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token},
    )

    assert response.status_code == 401


def test_register_creates_user_and_organization(env):
    response = env["client"].post(
        "/api/v1/auth/register",
        json={
            "first_name": "New",
            "last_name": "Account",
            "email": "new-account@example.com",
            "phone_country_code": "+91",
            "phone_number": "9876543212",
            "password": "registration-password",
            "organization_name": "New Test Organization",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-account@example.com"
    assert body["role"] == "admin"
    assert body["client_id"] is not None

    db = Session()
    try:
        saved_user = (
            db.query(User)
            .filter(User.email == "new-account@example.com")
            .first()
        )
        assert saved_user is not None
        saved_client = db.get(Client, saved_user.client_id)
        assert saved_client is not None
        assert saved_client.name == "New Test Organization"
    finally:
        db.close()


def test_register_rejects_duplicate_email(env):
    response = env["client"].post(
        "/api/v1/auth/register",
        json={
            "first_name": "Duplicate",
            "last_name": "User",
            "email": "auth-test@example.com",
            "phone_country_code": "+91",
            "phone_number": "9876543213",
            "password": "registration-password",
            "organization_name": "Duplicate Organization",
        },
    )

    assert response.status_code == 400


def test_admin_dashboard_allows_admin(env):
    token = create_access_token(
        str(env["user"].id),
        "admin",
    )

    response = env["client"].get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_admin_dashboard_allows_superadmin(env):
    db = env["db"]
    superadmin = User(
        email="superadmin@example.com",
        hashed_password=hash_password("correct-password"),
        first_name="Super",
        last_name="Admin",
        organization_name="Platform",
        phone_country_code="+91",
        phone_number="9876543214",
        role="superadmin",
        client_id=None,
        is_active=True,
    )
    db.add(superadmin)
    db.commit()
    db.refresh(superadmin)

    token = create_access_token(str(superadmin.id), superadmin.role)

    response = env["client"].get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "superadmin"


def test_admin_dashboard_rejects_regular_user(env):
    token = create_access_token(
        str(env["inactive_user"].id),
        "user",
    )

    # Use an active regular user to test role authorization.
    db = env["db"]
    regular_user = User(
        email="regular-user@example.com",
        hashed_password=hash_password("correct-password"),
        first_name="Regular",
        last_name="User",
        organization_name="Authentication Test Org",
        phone_country_code="+91",
        phone_number="9876543215",
        role="user",
        client_id=env["user"].client_id,
        is_active=True,
    )
    db.add(regular_user)
    db.commit()
    db.refresh(regular_user)

    token = create_access_token(str(regular_user.id), regular_user.role)

    response = env["client"].get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_admin_dashboard_requires_authentication(env):
    response = env["client"].get("/api/v1/admin/dashboard")

    assert response.status_code == 401
