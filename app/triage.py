"""Automatic ticket triage.

Two independent, explainable steps:

1. Category  - a TF-IDF + Logistic Regression text classifier. If the model is
               not confident enough, the ticket goes to the "general" queue and
               is flagged for a human to review instead of being mis-routed.
2. Priority  - transparent keyword rules (an outage beats a how-to question),
               with a floor of "high" for anything classified as security.
"""

import contextlib
import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline

from app.models import Priority
from app.sla import SLA_HOURS

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "ml" / "data" / "tickets.csv"
MODEL_PATH = ROOT / "ml" / "model.joblib"

CONFIDENCE_FLOOR = 0.45
FALLBACK_CATEGORY = "general"


@dataclass(frozen=True)
class TriageResult:
    category: str
    confidence: float
    needs_review: bool
    priority: str

    @property
    def sla_hours(self) -> int:
        return SLA_HOURS[self.priority]


# ---------- category model ----------
def load_dataset(path: Path = DATA_PATH) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            texts.append(row["text"])
            labels.append(row["category"])
    return texts, labels


def build_pipeline() -> Pipeline:
    return make_pipeline(
        TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True, stop_words="english"),
        LogisticRegression(max_iter=1000, C=5.0),
    )


def train_and_save() -> Pipeline:
    texts, labels = load_dataset()
    model = build_pipeline().fit(texts, labels)
    with contextlib.suppress(OSError):  # read-only filesystem: keep the model in memory only
        joblib.dump(model, MODEL_PATH)
    return model


@lru_cache(maxsize=1)
def get_model() -> Pipeline:
    """Load the saved model, or train one (takes well under a second) if it is missing/stale."""
    if MODEL_PATH.exists():
        try:
            return joblib.load(MODEL_PATH)
        except Exception:  # noqa: BLE001 - e.g. pickle from another scikit-learn version
            pass
    return train_and_save()


def known_categories() -> list[str]:
    return [*get_model().classes_, FALLBACK_CATEGORY]


def predict_category(text: str) -> tuple[str, float]:
    model = get_model()
    probabilities = model.predict_proba([text])[0]
    best = int(probabilities.argmax())
    return str(model.classes_[best]), float(probabilities[best])


# ---------- priority rules ----------
def _compile(*phrases: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.IGNORECASE)


_CRITICAL = _compile(
    "outage", "production down", "prod down", "production is down", "all users", "everyone",
    "entire office", "whole office", "company-wide", "data loss", "data breach", "breach",
    "ransomware", "sev1", "p1",
)
_HIGH = _compile(
    "urgent", "urgently", "asap", "immediately", "immediate", "blocked", "blocking", "blocker",
    "deadline", "client call", "client demo", "cannot work", "can't work", "unable to work",
    "escalate", "escalated",
)
_LOW = _compile(
    "no rush", "whenever possible", "when possible", "low priority", "not urgent", "how do i",
    "how to", "would like", "nice to have", "question", "request",
)


def infer_priority(text: str, category: str | None = None) -> str:
    if _CRITICAL.search(text):
        priority = Priority.critical
    elif _HIGH.search(text):
        priority = Priority.high
    elif _LOW.search(text):
        priority = Priority.low
    else:
        priority = Priority.medium
    if category == "security" and priority in (Priority.low, Priority.medium):
        priority = Priority.high
    return priority.value


# ---------- public entry point ----------
def triage(title: str, description: str = "") -> TriageResult:
    text = f"{title}. {description}".strip()
    category, confidence = predict_category(text)
    needs_review = confidence < CONFIDENCE_FLOOR
    if needs_review:
        category = FALLBACK_CATEGORY
    return TriageResult(
        category=category,
        confidence=round(confidence, 4),
        needs_review=needs_review,
        priority=infer_priority(text, category),
    )
