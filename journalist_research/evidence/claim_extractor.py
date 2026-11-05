
"""
Deep OSINT Agent (DOA)
Claim Extraction Contract

Purpose:
    Convert document text into structured investigative claims.

Critical rule:
    Extracting a claim does NOT establish the claim as true.

Pipeline:

    Document
        ↓
    Candidate Claim
        ↓
    Claim Record
        ↓
    Source / Evidence linkage
        ↓
    Corroboration
        ↓
    Contradiction
        ↓
    Confidence

The extractor is intentionally conservative.
It does not:
    - declare guilt
    - identify suspects
    - convert allegations into facts
    - infer causation
    - infer identity from association
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from journalist_research.models import (
    ClaimStatus,
    CorroborationStatus,
    Claim,
)


# ============================================================
# CONSTANTS
# ============================================================

CLAIM_ID_PREFIX = "CLAIM"

DEFAULT_STATUS = ClaimStatus.UNKNOWN

DEFAULT_CORROBORATION = CorroborationStatus.NONE

FACT_ASSERTION_PATTERNS = [
    r"\bis\b",
    r"\bwas\b",
    r"\bare\b",
    r"\bwere\b",
    r"\bhas\b",
    r"\bhad\b",
    r"\bowns?\b",
    r"\bowned\b",
    r"\bserves?\b",
    r"\bserved\b",
    r"\bappointed\b",
    r"\bfounded\b",
    r"\bregistered\b",
    r"\bsued\b",
    r"\barrested\b",
    r"\bcharged\b",
    r"\bconvicted\b",
    r"\bacquitted\b",
    r"\breported\b",
    r"\bsaid\b",
    r"\bclaimed\b",
    r"\balleged\b",
]

ALLEGATION_MARKERS = [
    "alleged",
    "allegedly",
    "claims",
    "claimed",
    "accused",
    "accusation",
    "reportedly",
    "according to",
    "suspected",
    "sources said",
]

UNCERTAINTY_MARKERS = [
    "may",
    "might",
    "could",
    "appears",
    "appeared",
    "possibly",
    "potentially",
    "believed",
    "unconfirmed",
    "unclear",
    "unknown",
    "could not be verified",
    "not independently verified",
]

NEGATION_MARKERS = [
    "not",
    "never",
    "no",
    "without",
    "denied",
    "denies",
    "rejects",
    "rejected",
    "disputed",
    "disputes",
]


# ============================================================
# HELPERS
# ============================================================

def new_claim_id() -> str:
    return f"{CLAIM_ID_PREFIX}_{uuid4().hex}"


def normalize_text(
    text: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        (text or "").strip(),
    )


def split_sentences(
    text: str,
) -> List[str]:

    value = normalize_text(text)

    if not value:
        return []

    parts = re.split(
        r"(?<=[.!?])\s+",
        value,
    )

    return [
        part.strip()
        for part in parts
        if part.strip()
    ]


def contains_any(
    text: str,
    markers: List[str],
) -> bool:

    lowered = text.lower()

    return any(
        marker.lower() in lowered
        for marker in markers
    )


def classify_sentence(
    sentence: str,
) -> str:

    lowered = sentence.lower()

    if contains_any(
        lowered,
        ALLEGATION_MARKERS,
    ):
        return "ALLEGATION"

    if contains_any(
        lowered,
        UNCERTAINTY_MARKERS,
    ):
        return "UNCERTAIN"

    if contains_any(
        lowered,
        NEGATION_MARKERS,
    ):
        return "NEGATED"

    if any(
        re.search(
            pattern,
            lowered,
        )
        for pattern in FACT_ASSERTION_PATTERNS
    ):
        return "ASSERTION"

    return "OBSERVATION"


def extract_dates(
    text: str,
) -> List[str]:

    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
        r"\b(?:19|20)\d{2}\b",
    ]

    found: List[str] = []

    for pattern in patterns:
        found.extend(
            re.findall(
                pattern,
                text,
            )
        )

    return list(
        dict.fromkeys(found)
    )


def extract_quoted_phrases(
    text: str,
) -> List[str]:

    phrases = re.findall(
        r'"([^"]+)"|'
        r"'([^']+)'",
        text,
    )

    result = []

    for first, second in phrases:
        value = (
            first
            if first
            else second
        )

        value = value.strip()

        if value:
            result.append(value)

    return list(
        dict.fromkeys(result)
    )


def detect_subject_candidates(
    sentence: str,
) -> List[str]:
    """
    Conservative entity candidate extraction.

    These are candidates only.
    They are NOT resolved entities.
    """

    candidates = []

    candidates.extend(
        extract_quoted_phrases(
            sentence
        )
    )

    # Conservative capitalized phrase.
    matches = re.findall(
        r"\b[A-Z][A-Za-z0-9&.-]*"
        r"(?:\s+[A-Z][A-Za-z0-9&.-]*){0,5}",
        sentence,
    )

    for match in matches:
        cleaned = match.strip(
            " ,.;:()[]{}"
        )

        if len(cleaned) >= 2:
            candidates.append(
                cleaned
            )

    # Deduplicate while preserving order.
    return list(
        dict.fromkeys(
            candidates
        )
    )


def confidence_for_extraction(
    classification: str,
) -> Optional[float]:
    """
    Extraction confidence is NOT truth confidence.

    It indicates how confidently the system classified the
    sentence as a candidate claim.
    """

    values = {
        "ASSERTION": 0.90,
        "ALLEGATION": 0.92,
        "UNCERTAIN": 0.88,
        "NEGATED": 0.90,
        "OBSERVATION": 0.70,
    }

    return values.get(
        classification
    )


# ============================================================
# EXTRACTED CLAIM
# ============================================================

@dataclass
class ExtractedClaim:
    """
    Intermediate claim candidate.

    This is intentionally separate from a verified Claim.
    """

    claim_id: str

    text: str

    source_id: str

    document_id: str

    sentence_index: int

    classification: str

    dates: List[str] = field(
        default_factory=list
    )

    subject_candidates: List[str] = field(
        default_factory=list
    )

    extraction_confidence: Optional[float] = None

    status: ClaimStatus = DEFAULT_STATUS

    corroboration: CorroborationStatus = (
        DEFAULT_CORROBORATION
    )

    fact_established: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_extracted_claim(
    claim: ExtractedClaim,
) -> List[str]:

    errors: List[str] = []

    if not claim.claim_id:
        errors.append(
            "claim_id is required."
        )

    if not claim.text:
        errors.append(
            "claim text is required."
        )

    if not claim.source_id:
        errors.append(
            "source_id is required."
        )

    if not claim.document_id:
        errors.append(
            "document_id is required."
        )

    if claim.sentence_index < 0:
        errors.append(
            "sentence_index cannot be negative."
        )

    if claim.classification not in {
        "ASSERTION",
        "ALLEGATION",
        "UNCERTAIN",
        "NEGATED",
        "OBSERVATION",
    }:
        errors.append(
            "Invalid claim classification."
        )

    if claim.extraction_confidence is not None:
        if not (
            0.0
            <= claim.extraction_confidence
            <= 1.0
        ):
            errors.append(
                "Extraction confidence must be 0..1."
            )

    if claim.fact_established:
        errors.append(
            "Claim extraction cannot establish fact."
        )

    return errors


# ============================================================
# EXTRACTION ENGINE
# ============================================================

def extract_claims(
    text: str,
    source_id: str,
    document_id: str,
    *,
    min_length: int = 20,
) -> List[ExtractedClaim]:

    sentences = split_sentences(
        text
    )

    claims: List[ExtractedClaim] = []

    for index, sentence in enumerate(
        sentences
    ):

        if len(sentence) < min_length:
            continue

        classification = classify_sentence(
            sentence
        )

        claim = ExtractedClaim(
            claim_id=new_claim_id(),
            text=sentence,
            source_id=source_id,
            document_id=document_id,
            sentence_index=index,
            classification=classification,
            dates=extract_dates(
                sentence
            ),
            subject_candidates=detect_subject_candidates(
                sentence
            ),
            extraction_confidence=confidence_for_extraction(
                classification
            ),
            status=ClaimStatus.UNKNOWN,
            corroboration=(
                DEFAULT_CORROBORATION
            ),
            fact_established=False,
            metadata={
                "extraction_method":
                    "sentence_candidate_extraction",
                "truth_verified":
                    False,
                "human_verified":
                    False,
            },
        )

        errors = validate_extracted_claim(
            claim
        )

        if errors:
            raise ValueError(
                "; ".join(errors)
            )

        claims.append(
            claim
        )

    return claims


# ============================================================
# CONVERSION TO CORE MODEL CLAIM
# ============================================================

def to_core_claim(
    extracted: ExtractedClaim,
) -> Claim:

    """
    Convert an extracted candidate into the actual DOA Claim model.

    IMPORTANT:
        Extraction does not establish truth.
        The resulting Claim remains UNKNOWN.
    """

    errors = validate_extracted_claim(
        extracted
    )

    if errors:
        raise ValueError(
            "; ".join(errors)
        )

    return Claim(
        text=extracted.text,
        status=ClaimStatus.UNKNOWN,
        source_ids=[extracted.source_id],
        evidence_ids=[],
        entity_ids=[],
        confidence=None,
        corroboration=CorroborationStatus.NONE,
        contradiction_ids=[],
        metadata={
            **extracted.metadata,
            "classification":
                extracted.classification,
            "dates":
                extracted.dates,
            "subject_candidates":
                extracted.subject_candidates,
            "extraction_confidence":
                extracted.extraction_confidence,
            "fact_established":
                False,
        },
    )


# ============================================================
# BATCH EXTRACTION
# ============================================================

def extract_document_claims(
    document: Any,
) -> List[ExtractedClaim]:

    return extract_claims(
        text=getattr(
            document,
            "content",
            "",
        ),
        source_id=getattr(
            document,
            "source_id",
            "",
        ),
        document_id=getattr(
            document,
            "document_id",
            "",
        ),
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "ExtractedClaim",
    "extract_claims",
    "extract_document_claims",
    "to_core_claim",
    "validate_extracted_claim",
    "classify_sentence",
    "extract_dates",
    "detect_subject_candidates",
]
