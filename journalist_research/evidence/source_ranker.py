
"""
Deep OSINT Agent (DOA)
Source Intelligence / Source Ranker

Purpose
-------
Evaluate investigative sources for research prioritization.

IMPORTANT
---------
Source quality != claim truth.

A high-quality source can still contain an error.
A low-quality source can still contain a useful lead.

The ranker therefore produces a source-quality assessment
for prioritization and corroboration. It does NOT establish
facts, guilt, liability, or identity.

Source hierarchy
----------------
VERY_HIGH
    Primary government, court, regulatory, official corporate
    or similarly authoritative records.

HIGH
    Established journalism, verified institutional sources,
    reputable databases with identifiable provenance.

MEDIUM
    Archived pages, specialist publications, identifiable
    secondary sources.

LOW
    Blogs, unattributed aggregators, weakly sourced pages.

VERY_LOW
    Anonymous posts, unverifiable claims, anonymous leaks.

UNKNOWN
    Insufficient source information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class SourceQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class SourceType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    COURT = "COURT"
    REGULATORY = "REGULATORY"
    CORPORATE_OFFICIAL = "CORPORATE_OFFICIAL"
    OFFICIAL_RECORD = "OFFICIAL_RECORD"
    ESTABLISHED_JOURNALISM = "ESTABLISHED_JOURNALISM"
    SPECIALIST_PUBLICATION = "SPECIALIST_PUBLICATION"
    ARCHIVED_WEBPAGE = "ARCHIVED_WEBPAGE"
    DATABASE = "DATABASE"
    BLOG = "BLOG"
    AGGREGATOR = "AGGREGATOR"
    FORUM = "FORUM"
    ANONYMOUS_POST = "ANONYMOUS_POST"
    ANONYMOUS_LEAK = "ANONYMOUS_LEAK"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    UNKNOWN = "UNKNOWN"


class ProvenanceQuality(str, Enum):
    UNKNOWN = "UNKNOWN"
    WEAK = "WEAK"
    PARTIAL = "PARTIAL"
    STRONG = "STRONG"
    VERIFIED = "VERIFIED"


class SourceStatus(str, Enum):
    UNASSESSED = "UNASSESSED"
    ASSESSED = "ASSESSED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class IndependenceLevel(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


# ============================================================
# SOURCE RECORD
# ============================================================

@dataclass
class SourceAssessment:
    """
    Structured assessment of a source.

    This record describes source quality and provenance only.
    It does not determine whether any claim from the source is true.
    """

    assessment_id: str

    source_id: str

    url: Optional[str]

    title: Optional[str]

    publisher: Optional[str]

    source_type: SourceType

    quality: SourceQuality

    quality_score: float

    provenance: ProvenanceQuality

    independence: IndependenceLevel

    status: SourceStatus = (
        SourceStatus.UNASSESSED
    )

    strengths: List[str] = field(
        default_factory=list
    )

    weaknesses: List[str] = field(
        default_factory=list
    )

    corroboration_required: bool = True

    fact_established: bool = False

    guilt_established: bool = False

    identity_established: bool = False

    notes: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# SOURCE METADATA
# ============================================================

@dataclass
class SourceRecord:
    """
    Minimal source metadata used by the ranker.
    """

    source_id: str

    url: Optional[str] = None

    title: Optional[str] = None

    publisher: Optional[str] = None

    source_type: SourceType = (
        SourceType.UNKNOWN
    )

    published_at: Optional[str] = None

    retrieved_at: Optional[str] = None

    author: Optional[str] = None

    provenance: ProvenanceQuality = (
        ProvenanceQuality.UNKNOWN
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# HELPERS
# ============================================================

def new_id(
    prefix: str = "SRC_ASSESS",
) -> str:

    return (
        f"{prefix}_{uuid4().hex}"
    )


QUALITY_SCORE = {
    SourceQuality.UNKNOWN: 0.0,
    SourceQuality.VERY_LOW: 0.15,
    SourceQuality.LOW: 0.30,
    SourceQuality.MEDIUM: 0.50,
    SourceQuality.HIGH: 0.75,
    SourceQuality.VERY_HIGH: 0.95,
}


SOURCE_TYPE_QUALITY = {
    SourceType.GOVERNMENT:
        SourceQuality.VERY_HIGH,

    SourceType.COURT:
        SourceQuality.VERY_HIGH,

    SourceType.REGULATORY:
        SourceQuality.VERY_HIGH,

    SourceType.CORPORATE_OFFICIAL:
        SourceQuality.VERY_HIGH,

    SourceType.OFFICIAL_RECORD:
        SourceQuality.VERY_HIGH,

    SourceType.ESTABLISHED_JOURNALISM:
        SourceQuality.HIGH,

    SourceType.DATABASE:
        SourceQuality.HIGH,

    SourceType.SPECIALIST_PUBLICATION:
        SourceQuality.MEDIUM,

    SourceType.ARCHIVED_WEBPAGE:
        SourceQuality.MEDIUM,

    SourceType.BLOG:
        SourceQuality.LOW,

    SourceType.AGGREGATOR:
        SourceQuality.LOW,

    SourceType.SOCIAL_MEDIA:
        SourceQuality.LOW,

    SourceType.FORUM:
        SourceQuality.VERY_LOW,

    SourceType.ANONYMOUS_POST:
        SourceQuality.VERY_LOW,

    SourceType.ANONYMOUS_LEAK:
        SourceQuality.VERY_LOW,

    SourceType.UNKNOWN:
        SourceQuality.UNKNOWN,
}


def quality_score(
    quality: SourceQuality,
) -> float:

    return QUALITY_SCORE[
        quality
    ]


# ============================================================
# VALIDATION
# ============================================================

def validate_source_record(
    source: SourceRecord,
) -> List[str]:

    errors = []

    if not source.source_id:
        errors.append(
            "source_id is required."
        )

    if not isinstance(
        source.source_type,
        SourceType,
    ):
        errors.append(
            "source_type must be SourceType."
        )

    if not isinstance(
        source.provenance,
        ProvenanceQuality,
    ):
        errors.append(
            "provenance must be ProvenanceQuality."
        )

    return errors


def validate_assessment(
    assessment: SourceAssessment,
) -> List[str]:

    errors = []

    if not assessment.assessment_id:
        errors.append(
            "assessment_id is required."
        )

    if not assessment.source_id:
        errors.append(
            "source_id is required."
        )

    if not (
        0.0
        <= assessment.quality_score
        <= 1.0
    ):
        errors.append(
            "quality_score must be between 0 and 1."
        )

    if assessment.fact_established:
        errors.append(
            "Source ranker cannot establish facts."
        )

    if assessment.guilt_established:
        errors.append(
            "Source ranker cannot establish guilt."
        )

    if assessment.identity_established:
        errors.append(
            "Source ranker cannot establish identity."
        )

    return errors


# ============================================================
# QUALITY DETERMINATION
# ============================================================

def determine_quality(
    source_type: SourceType,
    provenance: ProvenanceQuality,
) -> SourceQuality:

    base_quality = SOURCE_TYPE_QUALITY.get(
        source_type,
        SourceQuality.UNKNOWN,
    )

    # Strong/verified provenance can improve weak metadata,
    # but never turns an anonymous source into a primary source.
    if (
        provenance == ProvenanceQuality.VERIFIED
        and base_quality == SourceQuality.MEDIUM
    ):
        return SourceQuality.HIGH

    if (
        provenance == ProvenanceQuality.VERIFIED
        and base_quality == SourceQuality.LOW
    ):
        return SourceQuality.MEDIUM

    return base_quality


# ============================================================
# SOURCE ASSESSMENT
# ============================================================

def assess_source(
    source: SourceRecord,
    *,
    independence: IndependenceLevel = (
        IndependenceLevel.UNKNOWN
    ),
    notes: Optional[str] = None,
) -> SourceAssessment:

    errors = validate_source_record(
        source
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    quality = determine_quality(
        source.source_type,
        source.provenance,
    )

    score = quality_score(
        quality
    )

    strengths = []
    weaknesses = []

    if quality in (
        SourceQuality.VERY_HIGH,
        SourceQuality.HIGH,
    ):
        strengths.append(
            "Source category has relatively strong "
            "investigative provenance."
        )

    if source.provenance in (
        ProvenanceQuality.STRONG,
        ProvenanceQuality.VERIFIED,
    ):
        strengths.append(
            "Source provenance is documented."
        )

    if quality in (
        SourceQuality.LOW,
        SourceQuality.VERY_LOW,
        SourceQuality.UNKNOWN,
    ):
        weaknesses.append(
            "Source should not be treated as "
            "sufficient corroboration by itself."
        )

    if source.source_type in (
        SourceType.ANONYMOUS_POST,
        SourceType.ANONYMOUS_LEAK,
        SourceType.FORUM,
    ):
        weaknesses.append(
            "Source identity or provenance is limited."
        )

    assessment = SourceAssessment(
        assessment_id=new_id(),
        source_id=source.source_id,
        url=source.url,
        title=source.title,
        publisher=source.publisher,
        source_type=source.source_type,
        quality=quality,
        quality_score=score,
        provenance=source.provenance,
        independence=independence,
        status=SourceStatus.ASSESSED,
        strengths=strengths,
        weaknesses=weaknesses,
        corroboration_required=True,
        fact_established=False,
        guilt_established=False,
        identity_established=False,
        notes=notes,
        metadata={
            "source_quality_is_not_claim_truth": True,
            "requires_claim_level_evaluation": True,
            "automatic_fact_establishment": False,
        },
    )

    validation_errors = validate_assessment(
        assessment
    )

    if validation_errors:
        raise ValueError(
            "; ".join(validation_errors)
        )

    return assessment


# ============================================================
# SOURCE COMPARISON
# ============================================================

def compare_sources(
    first: SourceAssessment,
    second: SourceAssessment,
) -> Dict[str, Any]:

    if first.quality_score > second.quality_score:
        preferred = first.source_id

    elif second.quality_score > first.quality_score:
        preferred = second.source_id

    else:
        preferred = None

    return {
        "first_source_id": first.source_id,
        "second_source_id": second.source_id,
        "first_quality": first.quality.value,
        "second_quality": second.quality.value,
        "preferred_for_review": preferred,
        "truth_determined": False,
        "guilt_determined": False,
        "identity_determined": False,
        "reason": (
            "Quality ranking determines review priority, "
            "not claim truth."
        ),
    }


# ============================================================
# SOURCE PRIORITY
# ============================================================

def source_priority(
    assessment: SourceAssessment,
) -> int:

    """
    Lower number = higher research priority.
    """

    priority = {
        SourceQuality.VERY_HIGH: 1,
        SourceQuality.HIGH: 2,
        SourceQuality.MEDIUM: 3,
        SourceQuality.LOW: 4,
        SourceQuality.VERY_LOW: 5,
        SourceQuality.UNKNOWN: 6,
    }

    return priority[
        assessment.quality
    ]


def rank_sources(
    assessments: List[SourceAssessment],
) -> List[SourceAssessment]:

    return sorted(
        assessments,
        key=lambda item: (
            source_priority(item),
            -item.quality_score,
            item.source_id,
        ),
    )


# ============================================================
# SOURCE FILTERS
# ============================================================

def primary_source_candidates(
    assessments: List[SourceAssessment],
) -> List[SourceAssessment]:

    return [
        item
        for item in assessments
        if item.quality
        == SourceQuality.VERY_HIGH
    ]


def requires_corroboration(
    assessment: SourceAssessment,
) -> bool:

    return assessment.corroboration_required


# ============================================================
# SERIALIZATION
# ============================================================

def serialize_assessment(
    assessment: SourceAssessment,
) -> Dict[str, Any]:

    return {
        "assessment_id":
            assessment.assessment_id,

        "source_id":
            assessment.source_id,

        "url":
            assessment.url,

        "title":
            assessment.title,

        "publisher":
            assessment.publisher,

        "source_type":
            assessment.source_type.value,

        "quality":
            assessment.quality.value,

        "quality_score":
            assessment.quality_score,

        "provenance":
            assessment.provenance.value,

        "independence":
            assessment.independence.value,

        "status":
            assessment.status.value,

        "strengths":
            list(assessment.strengths),

        "weaknesses":
            list(assessment.weaknesses),

        "corroboration_required":
            assessment.corroboration_required,

        "fact_established":
            False,

        "guilt_established":
            False,

        "identity_established":
            False,

        "notes":
            assessment.notes,

        "metadata":
            dict(assessment.metadata),
    }


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "SourceQuality",
    "SourceType",
    "ProvenanceQuality",
    "SourceStatus",
    "IndependenceLevel",
    "SourceAssessment",
    "SourceRecord",
    "new_id",
    "quality_score",
    "validate_source_record",
    "validate_assessment",
    "determine_quality",
    "assess_source",
    "compare_sources",
    "source_priority",
    "rank_sources",
    "primary_source_candidates",
    "requires_corroboration",
    "serialize_assessment",
]
