from datetime import timedelta

from app.database import SessionLocal, utcnow
from app.models import Ticket


def _patch(client, ticket_id, user, **changes):
    return client.patch(f"/api/tickets/{ticket_id}", json=changes, headers=user["headers"])


def _backdate(ticket_id: int, hours: int) -> None:
    """Pretend the ticket was opened `hours` ago (keeps the SLA window the same length)."""
    with SessionLocal() as db:
        ticket = db.get(Ticket, ticket_id)
        shift = timedelta(hours=hours)
        ticket.created_at -= shift
        ticket.sla_due_at -= shift
        db.commit()


# ---------- creation + auto-triage ----------
def test_create_ticket_is_auto_triaged_with_sla(client, employee, make_ticket):
    ticket = make_ticket("VPN keeps disconnecting", "The VPN drops every few minutes when I work from home.")
    assert ticket["status"] == "open"
    assert ticket["category"] == "network"
    assert ticket["priority"] == "medium"
    assert ticket["requester"]["id"] == employee["id"]
    assert ticket["assignee"] is None
    assert ticket["sla_breached"] is False
    assert ticket["sla_due_at"] > ticket["created_at"]


def test_create_ticket_validates_input(client, employee):
    response = client.post("/api/tickets", json={"title": "x", "description": ""}, headers=employee["headers"])
    assert response.status_code == 422


def test_triage_preview_does_not_create_a_ticket(client, employee):
    body = {"title": "Production database outage", "description": "PostgreSQL is rejecting new connections."}
    preview = client.post("/api/triage/preview", json=body, headers=employee["headers"]).json()
    assert preview["category"] == "database"
    assert preview["priority"] == "critical"
    assert preview["sla_hours"] == 4
    assert client.get("/api/tickets", headers=employee["headers"]).json()["total"] == 0


# ---------- visibility ----------
def test_employees_only_see_their_own_tickets(client, employee, other_employee, agent, make_ticket):
    ticket = make_ticket()
    assert client.get("/api/tickets", headers=other_employee["headers"]).json()["total"] == 0
    assert client.get(f"/api/tickets/{ticket['id']}", headers=other_employee["headers"]).status_code == 404
    assert _patch(client, ticket["id"], other_employee, status="closed").status_code == 404
    comment = client.post(
        f"/api/tickets/{ticket['id']}/comments", json={"body": "hi"}, headers=other_employee["headers"]
    )
    assert comment.status_code == 404
    assert client.get("/api/tickets", headers=agent["headers"]).json()["total"] == 1


def test_missing_ticket_returns_404(client, agent):
    assert client.get("/api/tickets/999", headers=agent["headers"]).status_code == 404


# ---------- filtering, search, pagination ----------
def test_list_filters_search_and_pagination(client, employee, agent, make_ticket):
    make_ticket("VPN keeps disconnecting", "The VPN drops every few minutes.")
    make_ticket("Laptop not powering on", "My laptop is not powering on since morning.")
    make_ticket("Production database outage", "PostgreSQL production database is rejecting new connections.")
    headers = agent["headers"]

    def listing(**params):
        return client.get("/api/tickets", params=params, headers=headers).json()

    assert listing()["total"] == 3
    assert [t["title"] for t in listing(category="hardware")["items"]] == ["Laptop not powering on"]
    assert listing(priority="critical")["total"] == 1
    assert listing(q="laptop")["total"] == 1
    assert listing(status="resolved")["total"] == 0

    page = listing(limit=2, offset=0)
    assert len(page["items"]) == 2 and page["total"] == 3
    assert page["items"][0]["title"] == "Production database outage"  # newest first
    assert len(listing(limit=2, offset=2)["items"]) == 1
    assert client.get("/api/tickets", params={"limit": 500}, headers=headers).status_code == 422


def test_mine_filter_shows_only_tickets_assigned_to_me(client, agent, admin, make_ticket):
    first, _second = make_ticket(), make_ticket("Laptop not powering on", "It is not powering on.")
    _patch(client, first["id"], agent, status="in_progress")
    mine = client.get("/api/tickets", params={"mine": True}, headers=agent["headers"]).json()
    assert [t["id"] for t in mine["items"]] == [first["id"]]
    assert client.get("/api/tickets", params={"mine": True}, headers=admin["headers"]).json()["total"] == 0


# ---------- workflow / state machine ----------
def test_full_lifecycle_records_an_audit_trail(client, employee, agent, make_ticket):
    ticket_id = make_ticket()["id"]

    started = _patch(client, ticket_id, agent, status="in_progress").json()
    assert started["status"] == "in_progress"
    assert started["assignee"]["id"] == agent["id"]  # starting work claims the ticket

    resolved = _patch(client, ticket_id, agent, status="resolved").json()
    assert resolved["resolved_at"] is not None

    closed = _patch(client, ticket_id, employee, status="closed")  # requester accepts the fix
    assert closed.status_code == 200

    detail = client.get(f"/api/tickets/{ticket_id}", headers=employee["headers"]).json()
    trail = [(e["field"], e["old_value"], e["new_value"]) for e in detail["events"]]
    assert trail == [
        ("status", "open", "in_progress"),
        ("assignee_id", None, str(agent["id"])),
        ("status", "in_progress", "resolved"),
        ("status", "resolved", "closed"),
    ]
    assert detail["events"][-1]["actor"]["id"] == employee["id"]


def test_invalid_transitions_are_rejected(client, agent, make_ticket):
    ticket_id = make_ticket()["id"]
    assert _patch(client, ticket_id, agent, status="resolved").status_code == 409  # must be started first
    _patch(client, ticket_id, agent, status="closed")
    assert _patch(client, ticket_id, agent, status="open").status_code == 409  # closed is terminal
    assert _patch(client, ticket_id, agent, status="banana").status_code == 422


def test_requester_can_reopen_but_cannot_resolve(client, employee, agent, make_ticket):
    ticket_id = make_ticket()["id"]
    assert _patch(client, ticket_id, employee, status="in_progress").status_code == 403
    _patch(client, ticket_id, agent, status="in_progress")
    assert _patch(client, ticket_id, employee, status="resolved").status_code == 403
    _patch(client, ticket_id, agent, status="resolved")

    reopened = _patch(client, ticket_id, employee, status="in_progress")
    assert reopened.status_code == 200
    assert reopened.json()["resolved_at"] is None


def test_employees_cannot_change_priority_category_or_assignee(client, employee, make_ticket):
    ticket_id = make_ticket()["id"]
    assert _patch(client, ticket_id, employee, priority="critical").status_code == 403
    assert _patch(client, ticket_id, employee, category="security").status_code == 403
    assert _patch(client, ticket_id, employee, assignee_id=employee["id"]).status_code == 403


def test_empty_update_is_rejected(client, agent, make_ticket):
    assert _patch(client, make_ticket()["id"], agent).status_code == 400


# ---------- staff edits ----------
def test_priority_change_recomputes_sla_deadline(client, agent, make_ticket):
    ticket = make_ticket()
    updated = _patch(client, ticket["id"], agent, priority="critical").json()
    assert updated["priority"] == "critical"
    assert updated["sla_due_at"] < ticket["sla_due_at"]  # 4h window instead of 24h


def test_tickets_can_only_be_assigned_to_staff(client, admin, agent, employee, make_ticket):
    ticket_id = make_ticket()["id"]
    assert _patch(client, ticket_id, admin, assignee_id=employee["id"]).status_code == 400
    assert _patch(client, ticket_id, admin, assignee_id=9999).status_code == 400
    assigned = _patch(client, ticket_id, admin, assignee_id=agent["id"])
    assert assigned.json()["assignee"]["id"] == agent["id"]
    unassigned = _patch(client, ticket_id, admin, assignee_id=None)
    assert unassigned.json()["assignee"] is None


def test_category_override_clears_review_flag_and_validates(client, agent, make_ticket):
    ticket = make_ticket("Parking slot allocation", "Whom should I contact about the basement parking slot?")
    assert ticket["needs_review"] is True and ticket["category"] == "general"
    assert _patch(client, ticket["id"], agent, category="made-up").status_code == 400
    fixed = _patch(client, ticket["id"], agent, category="access").json()
    assert fixed["category"] == "access" and fixed["needs_review"] is False


# ---------- SLA ----------
def test_overdue_ticket_is_flagged_and_filterable(client, agent, make_ticket):
    late = make_ticket()
    on_time = make_ticket("Laptop not powering on", "It is not powering on.")
    _backdate(late["id"], hours=30)  # medium priority => 24h SLA

    assert client.get(f"/api/tickets/{late['id']}", headers=agent["headers"]).json()["sla_breached"] is True
    breached = client.get("/api/tickets", params={"breached": True}, headers=agent["headers"]).json()
    healthy = client.get("/api/tickets", params={"breached": False}, headers=agent["headers"]).json()
    assert [t["id"] for t in breached["items"]] == [late["id"]]
    assert [t["id"] for t in healthy["items"]] == [on_time["id"]]


def test_ticket_resolved_within_sla_stays_compliant_forever(client, agent, make_ticket):
    ticket_id = make_ticket()["id"]
    _patch(client, ticket_id, agent, status="in_progress")
    _patch(client, ticket_id, agent, status="resolved")
    with SessionLocal() as db:  # long after the deadline has passed...
        ticket = db.get(Ticket, ticket_id)
        ticket.created_at -= timedelta(days=10)
        ticket.resolved_at = ticket.created_at + timedelta(hours=1)
        ticket.sla_due_at = ticket.created_at + timedelta(hours=24)
        db.commit()
    assert ticket.sla_due_at < utcnow()
    assert client.get(f"/api/tickets/{ticket_id}", headers=agent["headers"]).json()["sla_breached"] is False


# ---------- comments ----------
def test_comments_thread_and_closed_tickets_are_locked(client, employee, agent, make_ticket):
    ticket_id = make_ticket()["id"]
    url = f"/api/tickets/{ticket_id}/comments"
    assert client.post(url, json={"body": "Any update?"}, headers=employee["headers"]).status_code == 201
    assert client.post(url, json={"body": "Looking into it."}, headers=agent["headers"]).status_code == 201
    assert client.post(url, json={"body": ""}, headers=agent["headers"]).status_code == 422

    comments = client.get(f"/api/tickets/{ticket_id}", headers=employee["headers"]).json()["comments"]
    assert [(c["author"]["name"], c["body"]) for c in comments] == [
        ("Employee", "Any update?"),
        ("Agent", "Looking into it."),
    ]

    _patch(client, ticket_id, employee, status="closed")
    assert client.post(url, json={"body": "too late"}, headers=employee["headers"]).status_code == 409
