"""Tenant isolation tests for knowledge-base endpoints."""
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
from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.main import app
from app.models import Client, User
from app.models.knowledge_base import KnowledgeBase


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


for table in Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, JSONB) and column.server_default is not None:
            column.server_default = None

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def env():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = Session()
    org_a, org_b = Client(name="Org A"), Client(name="Org B")
    db.add_all([org_a, org_b])
    db.flush()

    def make_user(email, org, role="admin"):
        user = User(
            email=email,
            hashed_password=hash_password("test-password"),
            first_name="Test",
            last_name="User",
            organization_name=org.name,
            phone_country_code="+91",
            phone_number="9876543210",
            role=role,
            client_id=org.id,
        )
        db.add(user)
        db.flush()
        return user

    user_a = make_user("kb-a@example.test", org_a)
    user_b = make_user("kb-b@example.test", org_b)
    superadmin = make_user("kb-super@example.test", org_a, "superadmin")
    kb_a = KnowledgeBase(client_id=org_a.id, name="Org A KB", status="active")
    db.add(kb_a)
    db.commit()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    def auth(user):
        return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}
    yield {
        "client": TestClient(app), "a": auth(user_a), "b": auth(user_b),
        "super": auth(superadmin), "org_a": org_a, "org_b": org_b, "kb_a": kb_a,
    }
    app.dependency_overrides.clear()
    db.close()


def test_knowledge_base_requires_authentication(env):
    assert env["client"].get("/api/v1/knowledge-bases").status_code in (401, 403)
    assert env["client"].post("/api/v1/knowledge-bases", json={"name": "No auth"}).status_code in (401, 403)


def test_admin_sees_only_own_knowledge_bases(env):
    response = env["client"].get("/api/v1/knowledge-bases", headers=env["b"])
    assert response.status_code == 200
    assert response.json()["total"] == 0
    foreign = env["client"].get(
        f"/api/v1/knowledge-bases/{env['kb_a'].id}", headers=env["b"]
    )
    assert foreign.status_code == 404


def test_admin_create_assigns_own_organization(env):
    response = env["client"].post(
        "/api/v1/knowledge-bases", headers=env["a"], json={"name": "New KB"}
    )
    assert response.status_code == 201
    assert response.json()["client_id"] == str(env["org_a"].id)


def test_admin_cannot_create_for_another_organization(env):
    response = env["client"].post(
        "/api/v1/knowledge-bases", headers=env["a"],
        json={"name": "Foreign KB", "client_id": str(env["org_b"].id)},
    )
    assert response.status_code == 403


def test_superadmin_must_choose_organization(env):
    response = env["client"].post(
        "/api/v1/knowledge-bases", headers=env["super"], json={"name": "No client"}
    )
    assert response.status_code == 400


def test_superadmin_can_create_for_selected_organization(env):
    response = env["client"].post(
        "/api/v1/knowledge-bases", headers=env["super"],
        json={"name": "Org B KB", "client_id": str(env["org_b"].id)},
    )
    assert response.status_code == 201
    assert response.json()["client_id"] == str(env["org_b"].id)
