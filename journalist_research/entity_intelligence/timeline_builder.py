
"""
Deep OSINT Agent (DOA)
Timeline Builder

Purpose
-------
Build a provenance-preserving chronological timeline from
claims linked to entities.

Core rule:

    DATE EXTRACTION != DATE TRUTH

The timeline records what the available claims/documents say.
It does not silently decide which conflicting date is correct.

Design principles
-----------------
1. Preserve every source-backed event.
2. Preserve conflicting dates.
3. Never invent a missing date.
4. Never infer an exact date from vague language.
5. Separate event date from source publication date.
6. Preserve source provenance.
7. Allow multiple claims to describe the same event.
8. Entity linkage does not establish claim truth.
9. Timeline ordering must tolerate unknown dates.
10. Contradictions remain visible instead of being overwritten.

Temporal relations:

    BEFORE
    AFTER
    SAME_TIME
    SAME_PERIOD
    UNKNOWN
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import re


# ============================================================
# ENUMS
# ============================================================

class TemporalPrecision(str, Enum):
    EXACT_DATE = "EXACT_DATE"
    YEAR = "YEAR"
    MONTH = "MONTH"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


class TemporalRelation(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    SAME_TIME = "SAME_TIME"
    SAME_PERIOD = "SAME_PERIOD"
    UNKNOWN = "UNKNOWN"


class TimelineEventStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    ESTABLISHED = "ESTABLISHED"
    UNKNOWN = "UNKNOWN"


# ============================================================
# DATE RECORD
# ============================================================

@dataclass
class TemporalValue:
    """
    Structured temporal value.

    start/end are optional because many investigative claims
    contain only a year, month, or no usable date at all.
    """

    raw_text: str

    start: Optional[date] = None

    end: Optional[date] = None

    precision: TemporalPrecision = (
        TemporalPrecision.UNKNOWN
    )

    inferred: bool = False

    inference_reason: Optional[str] = None


# ============================================================
# TIMELINE EVENT
# ============================================================

@dataclass
class TimelineEvent:
    """
    A source-backed event representation.

    This is a timeline record, not a declaration that the event
    actually occurred.
    """

    event_id: str

    entity_ids: List[str]

    claim_ids: List[str]

    source_ids: List[str]

    description: str

    temporal_values: List[TemporalValue] = field(
        default_factory=list
    )

    event_date: Optional[date] = None

    event_end_date: Optional[date] = None

    temporal_precision: TemporalPrecision = (
        TemporalPrecision.UNKNOWN
    )

    status: TimelineEventStatus = (
        TimelineEventStatus.UNVERIFIED
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_established: bool = False


# ============================================================
# TEMPORAL RELATION
# ============================================================

@dataclass
class TemporalEdge:
    """
    Relationship between two timeline events.

    The edge describes temporal ordering only.
    """

    source_event_id: str

    target_event_id: str

    relation: TemporalRelation

    reason: str = ""

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# TIMELINE
# ============================================================

@dataclass
class InvestigationTimeline:
    """
    Complete timeline with events, temporal edges and explicit
    conflicts.
    """

    timeline_id: str

    entity_ids: List[str]

    events: List[TimelineEvent] = field(
        default_factory=list
    )

    temporal_edges: List[TemporalEdge] = field(
        default_factory=list
    )

    conflicting_events: List[Tuple[str, str]] = field(
        default_factory=list
    )

    unresolved_temporal_questions: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# HELPERS
# ============================================================

def new_id(prefix: str) -> str:
    from uuid import uuid4

    return (
        f"{prefix}_{uuid4().hex}"
    )


def validate_temporal_value(
    value: TemporalValue,
) -> List[str]:

    errors = []

    if not value.raw_text:
        errors.append(
            "raw_text is required."
        )

    if (
        value.precision
        == TemporalPrecision.EXACT_DATE
        and value.start is None
    ):
        errors.append(
            "EXACT_DATE requires start."
        )

    if (
        value.start
        and value.end
        and value.end < value.start
    ):
        errors.append(
            "Temporal end cannot precede start."
        )

    if value.inferred and not value.inference_reason:
        errors.append(
            "Inferred temporal values require inference_reason."
        )

    return errors


def validate_event(
    event: TimelineEvent,
) -> List[str]:

    errors = []

    if not event.event_id:
        errors.append(
            "event_id is required."
        )

    if not event.description:
        errors.append(
            "description is required."
        )

    if event.fact_established:
        errors.append(
            "Timeline builder cannot establish facts."
        )

    for temporal_value in event.temporal_values:
        errors.extend(
            validate_temporal_value(
                temporal_value
            )
        )

    return errors


def validate_timeline(
    timeline: InvestigationTimeline,
) -> List[str]:

    errors = []

    if not timeline.timeline_id:
        errors.append(
            "timeline_id is required."
        )

    for event in timeline.events:
        errors.extend(
            validate_event(event)
        )

    return errors


# ============================================================
# DATE PARSING
# ============================================================

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_temporal_expression(
    raw_text: str,
) -> TemporalValue:

    raw = (
        raw_text or ""
    ).strip()

    if not raw:
        return TemporalValue(
            raw_text="",
            precision=TemporalPrecision.UNKNOWN,
        )

    # --------------------------------------------------------
    # ISO exact date
    # --------------------------------------------------------

    match = re.fullmatch(
        r"(20\d{2})-(\d{2})-(\d{2})",
        raw,
    )

    if match:

        value = date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )

        return TemporalValue(
            raw_text=raw,
            start=value,
            end=value,
            precision=TemporalPrecision.EXACT_DATE,
        )

    # --------------------------------------------------------
    # DD/MM/YYYY or DD-MM-YYYY
    # --------------------------------------------------------

    match = re.fullmatch(
        r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})",
        raw,
    )

    if match:

        value = date(
            int(match.group(3)),
            int(match.group(2)),
            int(match.group(1)),
        )

        return TemporalValue(
            raw_text=raw,
            start=value,
            end=value,
            precision=TemporalPrecision.EXACT_DATE,
        )

    # --------------------------------------------------------
    # Month YYYY
    # --------------------------------------------------------

    match = re.fullmatch(
        r"([A-Za-z]+)\s+(20\d{2})",
        raw,
    )

    if match:

        month_name = match.group(1).lower()

        if month_name in MONTHS:

            year = int(match.group(2))
            month = MONTHS[month_name]

            first = date(
                year,
                month,
                1,
            )

            if month == 12:
                next_month = date(
                    year + 1,
                    1,
                    1,
                )
            else:
                next_month = date(
                    year,
                    month + 1,
                    1,
                )

            last = (
                next_month
                - __import__(
                    "datetime"
                ).timedelta(days=1)
            )

            return TemporalValue(
                raw_text=raw,
                start=first,
                end=last,
                precision=TemporalPrecision.MONTH,
            )

    # --------------------------------------------------------
    # Year
    # --------------------------------------------------------

    match = re.fullmatch(
        r"(19\d{2}|20\d{2})",
        raw,
    )

    if match:

        year = int(
            match.group(1)
        )

        return TemporalValue(
            raw_text=raw,
            start=date(
                year,
                1,
                1,
            ),
            end=date(
                year,
                12,
                31,
            ),
            precision=TemporalPrecision.YEAR,
        )

    # --------------------------------------------------------
    # Unknown
    # --------------------------------------------------------

    return TemporalValue(
        raw_text=raw,
        precision=TemporalPrecision.UNKNOWN,
    )


# ============================================================
# CLAIM → EVENT
# ============================================================

def build_event_from_claim(
    claim_id: str,
    description: str,
    entity_ids: Optional[List[str]] = None,
    source_ids: Optional[List[str]] = None,
    temporal_expressions: Optional[List[str]] = None,
    status: TimelineEventStatus = (
        TimelineEventStatus.UNVERIFIED
    ),
) -> TimelineEvent:

    entity_ids = (
        list(entity_ids)
        if entity_ids
        else []
    )

    source_ids = (
        list(source_ids)
        if source_ids
        else []
    )

    temporal_values = []

    for expression in (
        temporal_expressions or []
    ):

        temporal_values.append(
            parse_temporal_expression(
                expression
            )
        )

    event_date = None
    event_end_date = None
    precision = (
        TemporalPrecision.UNKNOWN
    )

    # Only exact dates are promoted to event_date.
    exact_values = [
        value
        for value in temporal_values
        if value.start
        and value.precision
        in {
            TemporalPrecision.EXACT_DATE,
            TemporalPrecision.MONTH,
            TemporalPrecision.YEAR,
        }
    ]

    if exact_values:

        first = exact_values[0]

        event_date = first.start
        event_end_date = first.end
        precision = first.precision

    event = TimelineEvent(
        event_id=new_id("EVENT"),
        entity_ids=entity_ids,
        claim_ids=[claim_id],
        source_ids=source_ids,
        description=description,
        temporal_values=temporal_values,
        event_date=event_date,
        event_end_date=event_end_date,
        temporal_precision=precision,
        status=status,
        metadata={
            "date_source": "claim",
            "date_inferred": False,
            "claim_truth_is_independent": True,
        },
        fact_established=False,
    )

    errors = validate_event(
        event
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return event


# ============================================================
# DATE OVERLAP
# ============================================================

def temporal_relation(
    left: TimelineEvent,
    right: TimelineEvent,
) -> TemporalRelation:

    if (
        left.event_date is None
        or right.event_date is None
    ):
        return TemporalRelation.UNKNOWN

    left_start = left.event_date
    left_end = (
        left.event_end_date
        or left.event_date
    )

    right_start = right.event_date
    right_end = (
        right.event_end_date
        or right.event_date
    )

    if left_end < right_start:
        return TemporalRelation.BEFORE

    if right_end < left_start:
        return TemporalRelation.AFTER

    if (
        left_start == right_start
        and left_end == right_end
    ):
        return TemporalRelation.SAME_TIME

    return TemporalRelation.SAME_PERIOD


# ============================================================
# TEMPORAL GRAPH
# ============================================================

def build_temporal_edges(
    events: List[TimelineEvent],
) -> List[TemporalEdge]:

    edges = []

    for index, left in enumerate(events):

        for right in events[index + 1:]:

            relation = temporal_relation(
                left,
                right,
            )

            if (
                relation
                == TemporalRelation.UNKNOWN
            ):
                continue

            edges.append(
                TemporalEdge(
                    source_event_id=left.event_id,
                    target_event_id=right.event_id,
                    relation=relation,
                    reason=(
                        "Derived from source-backed "
                        "temporal values."
                    ),
                    metadata={
                        "inference_used": False,
                    },
                )
            )

    return edges


# ============================================================
# CONFLICT DETECTION
# ============================================================

def detect_temporal_conflicts(
    events: List[TimelineEvent],
) -> List[Tuple[str, str]]:

    conflicts = []

    # Same claim represented with incompatible exact dates.
    for index, left in enumerate(events):

        for right in events[index + 1:]:

            if not (
                set(left.claim_ids)
                & set(right.claim_ids)
            ):
                continue

            if (
                left.event_date is None
                or right.event_date is None
            ):
                continue

            left_exact = (
                left.temporal_precision
                == TemporalPrecision.EXACT_DATE
            )

            right_exact = (
                right.temporal_precision
                == TemporalPrecision.EXACT_DATE
            )

            if (
                left_exact
                and right_exact
                and left.event_date
                != right.event_date
            ):

                conflicts.append(
                    (
                        left.event_id,
                        right.event_id,
                    )
                )

    return conflicts


# ============================================================
# TIMELINE BUILD
# ============================================================

def build_timeline(
    entity_ids: List[str],
    events: List[TimelineEvent],
) -> InvestigationTimeline:

    timeline = InvestigationTimeline(
        timeline_id=new_id("TIMELINE"),
        entity_ids=list(
            dict.fromkeys(
                entity_ids
            )
        ),
        events=list(events),
        temporal_edges=build_temporal_edges(
            events
        ),
        conflicting_events=detect_temporal_conflicts(
            events
        ),
        unresolved_temporal_questions=[],
        metadata={
            "fact_established": False,
            "date_inference": False,
            "provenance_preserved": True,
        },
    )

    for event in events:

        if event.event_date is None:

            timeline.unresolved_temporal_questions.append(
                f"Event {event.event_id} has no resolvable date."
            )

    errors = validate_timeline(
        timeline
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return timeline


# ============================================================
# SORTING
# ============================================================

def sort_events_chronologically(
    events: List[TimelineEvent],
) -> List[TimelineEvent]:

    dated = [
        event
        for event in events
        if event.event_date is not None
    ]

    undated = [
        event
        for event in events
        if event.event_date is None
    ]

    dated.sort(
        key=lambda event: (
            event.event_date,
            event.event_end_date
            or event.event_date,
        )
    )

    # Unknown-date events remain at the end.
    return dated + undated


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "TemporalPrecision",
    "TemporalRelation",
    "TimelineEventStatus",
    "TemporalValue",
    "TimelineEvent",
    "TemporalEdge",
    "InvestigationTimeline",
    "parse_temporal_expression",
    "build_event_from_claim",
    "temporal_relation",
    "build_temporal_edges",
    "detect_temporal_conflicts",
    "build_timeline",
    "sort_events_chronologically",
    "validate_temporal_value",
    "validate_event",
    "validate_timeline",
]
