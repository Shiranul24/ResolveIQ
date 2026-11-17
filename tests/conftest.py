"""Test setup: an isolated in-memory database that is rebuilt for every test."""

import os

# Must be set before the app is imported, because the engine is created at import time.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests only
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def _signup(client: TestClient, name: str, email: str) -> dict:
    response = client.post("/api/auth/register", json={"name": name, "email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"id": response.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def admin(client):
    """The first registered account is bootstrapped as admin."""
    return _signup(client, "Admin", "admin@example.com")


@pytest.fixture
def agent(client, admin):
    user = _signup(client, "Agent", "agent@example.com")
    response = client.patch(f"/api/users/{user['id']}/role", json={"role": "agent"}, headers=admin["headers"])
    assert response.status_code == 200, response.text
    return user


@pytest.fixture
def employee(client, admin):
    return _signup(client, "Employee", "employee@example.com")


@pytest.fixture
def other_employee(client, admin):
    return _signup(client, "Other", "other@example.com")


@pytest.fixture
def make_ticket(client, employee):
    def _make(title="VPN keeps disconnecting", description="The VPN drops every few minutes.", headers=None):
        response = client.post(
            "/api/tickets",
            json={"title": title, "description": description},
            headers=headers or employee["headers"],
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make
