"""Request and response schemas (Pydantic v2)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Priority, Role, Status


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth / users ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: int
    name: str
    email: EmailStr
    role: Role


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RoleUpdateIn(BaseModel):
    role: Role


# ---------- triage ----------
class TriageIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)


class TriageOut(BaseModel):
    category: str
    confidence: float
    needs_review: bool
    priority: Priority
    sla_hours: int


# ---------- tickets ----------
class TicketCreateIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=5000)


class TicketUpdateIn(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    category: str | None = Field(default=None, min_length=2, max_length=30)
    assignee_id: int | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(ORMModel):
    id: int
    body: str
    created_at: datetime
    author: UserOut


class EventOut(ORMModel):
    id: int
    field: str
    old_value: str | None
    new_value: str | None
    created_at: datetime
    actor: UserOut


class TicketOut(ORMModel):
    id: int
    title: str
    description: str
    category: str
    category_confidence: float
    needs_review: bool
    priority: Priority
    status: Status
    requester: UserOut
    assignee: UserOut | None
    created_at: datetime
    updated_at: datetime
    sla_due_at: datetime
    resolved_at: datetime | None
    sla_breached: bool


class TicketDetailOut(TicketOut):
    comments: list[CommentOut]
    events: list[EventOut]


class TicketPage(BaseModel):
    items: list[TicketOut]
    total: int
    limit: int
    offset: int


# ---------- analytics ----------
class SummaryOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_category: dict[str, int]
    unassigned_open: int
    needs_review: int
    open_breaches: int
    sla_compliance_pct: float | None
    avg_resolution_hours: float | None
