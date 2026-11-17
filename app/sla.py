"""SLA policy: how long the desk has to resolve a ticket of each priority."""

from datetime import datetime, timedelta

SLA_HOURS: dict[str, int] = {"critical": 4, "high": 8, "medium": 24, "low": 72}


def due_at(priority: str, opened_at: datetime) -> datetime:
    return opened_at + timedelta(hours=SLA_HOURS[priority])
