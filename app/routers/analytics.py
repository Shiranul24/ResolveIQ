"""Service-desk health metrics for agents and admins."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db, utcnow
from app.deps import require_staff
from app.models import Status, Ticket, User
from app.schemas import SummaryOut

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

ACTIVE = (Status.open.value, Status.in_progress.value)


def _count_by(db: Session, column) -> dict[str, int]:
    return {key: count for key, count in db.execute(select(column, func.count(Ticket.id)).group_by(column))}


@router.get("/summary", response_model=SummaryOut)
def summary(_: User = Depends(require_staff), db: Session = Depends(get_db)) -> SummaryOut:
    now = utcnow()
    count = func.count(Ticket.id)

    open_breaches = db.scalar(select(count).where(Ticket.status.in_(ACTIVE), Ticket.sla_due_at < now)) or 0
    unassigned_open = db.scalar(select(count).where(Ticket.status.in_(ACTIVE), Ticket.assignee_id.is_(None))) or 0
    needs_review = db.scalar(select(count).where(Ticket.needs_review.is_(True))) or 0

    # Date arithmetic differs between SQLite and PostgreSQL, so resolution stats are computed
    # in Python from three timestamp columns of the resolved tickets only.
    resolved = db.execute(
        select(Ticket.created_at, Ticket.resolved_at, Ticket.sla_due_at).where(Ticket.resolved_at.is_not(None))
    ).all()
    compliance = avg_hours = None
    if resolved:
        within_sla = sum(1 for _, resolved_at, due in resolved if resolved_at <= due)
        total_hours = sum((resolved_at - created).total_seconds() for created, resolved_at, _ in resolved) / 3600
        compliance = round(100 * within_sla / len(resolved), 1)
        avg_hours = round(total_hours / len(resolved), 2)

    return SummaryOut(
        total=db.scalar(select(count)) or 0,
        by_status=_count_by(db, Ticket.status),
        by_priority=_count_by(db, Ticket.priority),
        by_category=_count_by(db, Ticket.category),
        unassigned_open=unassigned_open,
        needs_review=needs_review,
        open_breaches=open_breaches,
        sla_compliance_pct=compliance,
        avg_resolution_hours=avg_hours,
    )
