"""Load demo users and tickets:  python -m app.seed

Creates one account per role (password for all three: Demo@12345) and a
spread of tickets in different states so the dashboard has something to show.
"""

from datetime import timedelta

from sqlalchemy import select

from app import triage
from app.database import Base, SessionLocal, engine, utcnow
from app.models import Role, Status, Ticket, User
from app.security import hash_password
from app.sla import due_at

DEMO_PASSWORD = "Demo@12345"
USERS = [
    ("Asha Admin", "admin@resolveiq.dev", Role.admin),
    ("Arjun Agent", "agent@resolveiq.dev", Role.agent),
    ("Esha Employee", "employee@resolveiq.dev", Role.employee),
]
# (title, description, status, hours since it was opened)
TICKETS = [
    ("VPN keeps disconnecting", "The VPN drops every few minutes when I work from home.", Status.open, 2),
    (
        "Production database outage",
        "PostgreSQL production database is rejecting new connections for all users.",
        Status.in_progress,
        6,
    ),
    (
        "Laptop not powering on",
        "My laptop is not powering on after the weekend. Need a replacement urgently.",
        Status.in_progress,
        3,
    ),
    (
        "Phishing email from fake HR",
        "Received a suspicious attachment from an external sender pretending to be HR.",
        Status.resolved,
        5,
    ),
    ("Request access to Jira project", "Would like Jira project access for my new team, no rush.", Status.resolved, 30),
    ("Outlook crashes on startup", "Outlook crashes on startup since the latest Windows update.", Status.closed, 50),
    (
        "Nightly ETL job failed",
        "The nightly ETL job failed with a deadlock error and reports are stale.",
        Status.open,
        30,
    ),
    ("Password reset", "My password expired and I cannot sign in to SSO.", Status.closed, 20),
    (
        "Printer prints blank pages",
        "The 2nd floor printer prints blank pages, whenever possible please check.",
        Status.open,
        1,
    ),
    ("Parking slot allocation", "Whom should I contact about the basement parking slot?", Status.open, 4),
]


def run() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            print("Database already has data - nothing to do.")
            return

        password_hash = hash_password(DEMO_PASSWORD)
        admin, agent, employee = (
            User(name=name, email=email, role=role.value, password_hash=password_hash) for name, email, role in USERS
        )
        db.add_all([admin, agent, employee])
        db.flush()

        now = utcnow()
        for title, description, status, age_hours in TICKETS:
            result = triage.triage(title, description)
            opened = now - timedelta(hours=age_hours)
            is_active_work = status != Status.open
            is_done = status in (Status.resolved, Status.closed)
            db.add(
                Ticket(
                    title=title,
                    description=description,
                    category=result.category,
                    category_confidence=result.confidence,
                    needs_review=result.needs_review,
                    priority=result.priority,
                    status=status.value,
                    requester_id=employee.id,
                    assignee_id=agent.id if is_active_work else None,
                    created_at=opened,
                    updated_at=now,
                    sla_due_at=due_at(result.priority, opened),
                    resolved_at=opened + timedelta(hours=age_hours * 0.6) if is_done else None,
                )
            )
        db.commit()
        print(f"Seeded {len(USERS)} users and {len(TICKETS)} tickets. Password for all demo users: {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
