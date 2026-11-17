from datetime import UTC, datetime, timedelta

import jwt

from app.security import ALGORITHM
from tests.conftest import PASSWORD


def test_first_user_is_admin_and_later_users_are_employees(client, admin, employee):
    assert client.get("/api/auth/me", headers=admin["headers"]).json()["role"] == "admin"
    assert client.get("/api/auth/me", headers=employee["headers"]).json()["role"] == "employee"


def test_register_rejects_duplicate_email_case_insensitively(client, admin):
    response = client.post(
        "/api/auth/register", json={"name": "Dup", "email": "ADMIN@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


def test_register_validates_input(client):
    weak = client.post("/api/auth/register", json={"name": "A B", "email": "a@example.com", "password": "short"})
    bad_email = client.post("/api/auth/register", json={"name": "A B", "email": "nope", "password": PASSWORD})
    assert weak.status_code == 422
    assert bad_email.status_code == 422


def test_password_is_never_returned_or_stored_in_plain_text(client, admin):
    from app.database import SessionLocal
    from app.models import User

    assert "password" not in client.get("/api/auth/me", headers=admin["headers"]).text
    with SessionLocal() as db:
        stored = db.get(User, admin["id"]).password_hash
    assert stored != PASSWORD and stored.startswith("$2")


def test_login_fails_with_same_error_for_wrong_password_and_unknown_user(client, admin):
    wrong = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_routes_need_a_valid_token(client, admin):
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/tickets", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_expired_and_forged_tokens_are_rejected(client, admin):
    past = datetime.now(UTC) - timedelta(minutes=5)
    expired = jwt.encode(
        {"sub": str(admin["id"]), "exp": past}, "test-secret-key-that-is-long-enough-for-hs256", algorithm=ALGORITHM
    )
    forged = jwt.encode(
        {"sub": str(admin["id"]), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "some-other-secret-key-that-is-also-long-enough",
        algorithm=ALGORITHM,
    )
    for token in (expired, forged):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_only_admin_can_list_users_and_change_roles(client, admin, agent, employee):
    assert client.get("/api/users", headers=admin["headers"]).status_code == 200
    assert client.get("/api/users", headers=agent["headers"]).status_code == 403
    promote_self = client.patch(
        f"/api/users/{employee['id']}/role", json={"role": "admin"}, headers=employee["headers"]
    )
    assert promote_self.status_code == 403


def test_role_change_applies_to_existing_tokens_immediately(client, admin, agent):
    assert client.get("/api/analytics/summary", headers=agent["headers"]).status_code == 200
    client.patch(f"/api/users/{agent['id']}/role", json={"role": "employee"}, headers=admin["headers"])
    assert client.get("/api/analytics/summary", headers=agent["headers"]).status_code == 403


def test_admin_cannot_demote_themselves(client, admin):
    response = client.patch(f"/api/users/{admin['id']}/role", json={"role": "agent"}, headers=admin["headers"])
    assert response.status_code == 400
