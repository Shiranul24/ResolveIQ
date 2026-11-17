"""Ticket lifecycle: create (with auto-triage), search, update, comment."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import triage as triage_service
from app.database import get_db, utcnow
from app.deps import get_current_user
from app.models import Comment, Priority, Status, Ticket, TicketEvent, User
from app.schemas import (
    CommentIn,
    CommentOut,
    TicketCreateIn,
    TicketDetailOut,
    TicketOut,
    TicketPage,
    TicketUpdateIn,
    TriageIn,
    TriageOut,
)
from app.sla import due_at

router = APIRouter(prefix="/api", tags=["tickets"])

# Allowed status moves. "closed" is terminal.
TRANSITIONS: dict[str, set[str]] = {
    Status.open: {Status.in_progress, Status.closed},
    Status.in_progress: {Status.resolved, Status.open},
    Status.resolved: {Status.closed, Status.in_progress},
    Status.closed: set(),
}
# The subset a requester may perform on their own ticket: withdraw it, accept the fix, or reopen.
REQUESTER_TRANSITIONS = {
    (Status.open, Status.closed),
    (Status.resolved, Status.closed),
    (Status.resolved, Status.in_progress),
}


def _get_visible_ticket(ticket_id: int, user: User, db: Session) -> Ticket:
    """Employees can only see their own tickets; a hidden ticket looks like a missing one."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (not user.is_staff and ticket.requester_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return ticket


def _record(db: Session, ticket: Ticket, actor: User, field: str, old: object, new: object) -> None:
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            actor_id=actor.id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )
    )


@router.post("/triage/preview", response_model=TriageOut)
def preview_triage(body: TriageIn, _: User = Depends(get_current_user)) -> TriageOut:
    """Show how a ticket would be routed, without creating it."""
    result = triage_service.triage(body.title, body.description)
    return TriageOut(
        category=result.category,
        confidence=result.confidence,
        needs_review=result.needs_review,
        priority=Priority(result.priority),
        sla_hours=result.sla_hours,
    )


@router.post("/tickets", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    body: TicketCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    result = triage_service.triage(body.title, body.description)
    now = utcnow()
    ticket = Ticket(
        title=body.title.strip(),
        description=body.description.strip(),
        category=result.category,
        category_confidence=result.confidence,
        needs_review=result.needs_review,
        priority=result.priority,
        status=Status.open.value,
        requester_id=user.id,
        created_at=now,
        updated_at=now,
        sla_due_at=due_at(result.priority, now),
    )
    db.add(ticket)
    db.commit()
    return ticket


@router.get("/tickets", response_model=TicketPage)
def list_tickets(
    status_: Status | None = Query(default=None, alias="status"),
    priority: Priority | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, min_length=2, max_length=100, description="Search title/description"),
    mine: bool = Query(default=False, description="Staff: only tickets assigned to me"),
    breached: bool | None = Query(default=None, description="Filter by SLA breach state"),
    needs_review: bool | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketPage:
    conditions = []
    if not user.is_staff:
        conditions.append(Ticket.requester_id == user.id)
    elif mine:
        conditions.append(Ticket.assignee_id == user.id)
    if status_:
        conditions.append(Ticket.status == status_.value)
    if priority:
        conditions.append(Ticket.priority == priority.value)
    if category:
        conditions.append(Ticket.category == category.lower())
    if needs_review is not None:
        conditions.append(Ticket.needs_review == needs_review)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Ticket.title.ilike(pattern), Ticket.description.ilike(pattern)))
    if breached is not None:
        is_late = func.coalesce(Ticket.resolved_at, utcnow()) > Ticket.sla_due_at
        conditions.append(is_late if breached else ~is_late)

    total = db.scalar(select(func.count(Ticket.id)).where(*conditions)) or 0
    newest_first = (Ticket.created_at.desc(), Ticket.id.desc())
    items = db.scalars(select(Ticket).where(*conditions).order_by(*newest_first).limit(limit).offset(offset)).all()
    return TicketPage(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/tickets/{ticket_id}", response_model=TicketDetailOut)
def get_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Ticket:
    return _get_visible_ticket(ticket_id, user, db)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(
    ticket_id: int,
    body: TicketUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Ticket:
    ticket = _get_visible_ticket(ticket_id, user, db)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No changes supplied")

    if not user.is_staff and set(changes) - {"status"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only agents can change priority, category or assignee")

    # --- assignee ---
    if "assignee_id" in changes and changes["assignee_id"] != ticket.assignee_id:
        new_assignee_id = changes["assignee_id"]
        if new_assignee_id is not None:
            assignee = db.get(User, new_assignee_id)
            if assignee is None or not assignee.is_staff:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tickets can only be assigned to an agent or admin")
        _record(db, ticket, user, "assignee_id", ticket.assignee_id, new_assignee_id)
        ticket.assignee_id = new_assignee_id

    # --- priority (re-computes the SLA deadline from when the ticket was opened) ---
    if body.priority is not None and body.priority.value != ticket.priority:
        _record(db, ticket, user, "priority", ticket.priority, body.priority.value)
        ticket.priority = body.priority.value
        ticket.sla_due_at = due_at(ticket.priority, ticket.created_at)

    # --- category (a human correction clears the review flag) ---
    if body.category is not None:
        category = body.category.lower()
        if category not in triage_service.known_categories():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown category '{category}'")
        if category != ticket.category:
            _record(db, ticket, user, "category", ticket.category, category)
            ticket.category = category
        ticket.needs_review = False

    # --- status (validated against the state machine) ---
    if body.status is not None and body.status.value != ticket.status:
        old, new = Status(ticket.status), body.status
        if new not in TRANSITIONS[old]:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot move a ticket from '{old.value}' to '{new.value}'")
        if not user.is_staff and (old, new) not in REQUESTER_TRANSITIONS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only agents can make this status change")

        _record(db, ticket, user, "status", old.value, new.value)
        ticket.status = new.value
        if new == Status.resolved:
            ticket.resolved_at = utcnow()
        elif old == Status.resolved and new == Status.in_progress:
            ticket.resolved_at = None  # reopened: the SLA clock is running again
        if new == Status.in_progress and ticket.assignee_id is None and user.is_staff:
            _record(db, ticket, user, "assignee_id", None, user.id)
            ticket.assignee_id = user.id  # whoever starts the work owns the ticket

    ticket.updated_at = utcnow()
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    ticket_id: int,
    body: CommentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Comment:
    ticket = _get_visible_ticket(ticket_id, user, db)
    if ticket.status == Status.closed.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Closed tickets cannot receive new comments")
    comment = Comment(ticket_id=ticket.id, author_id=user.id, body=body.body.strip())
    db.add(comment)
    ticket.updated_at = utcnow()
    db.commit()
    return comment
