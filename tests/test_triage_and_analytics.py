from datetime import timedelta

import pytest

from app import triage
from app.database import SessionLocal
from app.models import Ticket


# ---------- category model ----------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Office Wi-Fi shows no internet access on my machine", "network"),
        ("My docking station is not detected when plugged in", "hardware"),
        ("Microsoft Teams crashes on startup after the update", "software"),
        ("My password has expired and I cannot sign in", "access"),
        ("Nightly ETL job failed with a deadlock error", "database"),
        ("Got a phishing email with a suspicious attachment", "security"),
    ],
)
def test_classifier_routes_typical_tickets(text, expected):
    result = triage.triage(text)
    assert result.category == expected
    assert result.needs_review is False


def test_out_of_domain_ticket_falls_back_to_human_review():
    result = triage.triage("Parking slot allocation", "Whom should I contact about the basement parking slot?")
    assert result.category == triage.FALLBACK_CATEGORY
    assert result.needs_review is True
    assert result.confidence < triage.CONFIDENCE_FLOOR


# ---------- priority rules ----------
@pytest.mark.parametrize(
    ("text", "category", "expected"),
    [
        ("Production is down for all users", None, "critical"),
        ("Need this urgently, it is blocking my work", None, "high"),
        ("How do I set up a mail signature? No rush", None, "low"),
        ("Excel freezes when opening large files", None, "medium"),
        ("Strange popup on my machine", "security", "high"),  # security is never below high
        ("Possible data breach on the finance server", "security", "critical"),
        ("The countdown widget looks odd", None, "medium"),  # 'down' inside a word must not match
    ],
)
def test_priority_rules(text, category, expected):
    assert triage.infer_priority(text, category) == expected


# ---------- analytics ----------
def test_summary_is_staff_only(client, employee, agent):
    assert client.get("/api/analytics/summary", headers=employee["headers"]).status_code == 403
    assert client.get("/api/analytics/summary", headers=agent["headers"]).status_code == 200


def test_summary_on_empty_desk(client, agent):
    summary = client.get("/api/analytics/summary", headers=agent["headers"]).json()
    assert summary["total"] == 0
    assert summary["sla_compliance_pct"] is None and summary["avg_resolution_hours"] is None


def test_summary_counts_breaches_compliance_and_resolution_time(client, agent, make_ticket):
    fast = make_ticket("VPN keeps disconnecting", "The VPN drops every few minutes.")  # medium, 24h
    slow = make_ticket("Laptop not powering on", "My laptop is not powering on.")  # medium, 24h
    overdue = make_ticket("Outlook crashes on startup", "Outlook crashes on startup every time.")
    make_ticket("Parking slot allocation", "Whom should I contact about the basement parking slot?")

    for ticket in (fast, slow):
        for status in ("in_progress", "resolved"):
            client.patch(f"/api/tickets/{ticket['id']}", json={"status": status}, headers=agent["headers"])

    with SessionLocal() as db:
        # fast: resolved in 2h (within SLA); slow: resolved in 30h (late); overdue: open for 48h.
        for ticket_id, age, took in ((fast["id"], 40, 2), (slow["id"], 40, 30), (overdue["id"], 48, None)):
            ticket = db.get(Ticket, ticket_id)
            ticket.created_at -= timedelta(hours=age)
            ticket.sla_due_at = ticket.created_at + timedelta(hours=24)
            if took is not None:
                ticket.resolved_at = ticket.created_at + timedelta(hours=took)
        db.commit()

    summary = client.get("/api/analytics/summary", headers=agent["headers"]).json()
    assert summary["total"] == 4
    assert summary["by_status"] == {"open": 2, "resolved": 2}
    assert summary["by_category"] == {"network": 1, "hardware": 1, "software": 1, "general": 1}
    assert summary["open_breaches"] == 1
    assert summary["unassigned_open"] == 2
    assert summary["needs_review"] == 1
    assert summary["sla_compliance_pct"] == 50.0
    assert summary["avg_resolution_hours"] == 16.0


# ---------- ops ----------
def test_health_check_and_dashboard_are_served(client):
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "ResolveIQ" in page.text
