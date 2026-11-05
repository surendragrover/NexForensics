"""
Canonical evidence status ladder for DOA.

Every module (confidence, matrix, synthesis, report) must express its
final verdict through this vocabulary.  Legacy module-specific labels
are mapped via to_canonical().  Nothing here establishes fact, identity,
guilt or non-existence; these are evidence states, not truth values.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional


class EvidenceStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"                      # primary official record only
    STRONGLY_CORROBORATED = "STRONGLY_CORROBORATED"  # >=2 independent lineages, adequate quality
    REPORTED = "REPORTED"                            # >=1 lineage of adequate quality
    UNVERIFIED = "UNVERIFIED"                        # only weak / self-reported support
    DISPUTED = "DISPUTED"                            # material contradiction exists
    NOT_ESTABLISHED = "NOT_ESTABLISHED"              # searched, relevant sources, no support
    NOT_AVAILABLE = "NOT_AVAILABLE"                  # source blocked / unavailable
    NOT_ASSESSED = "NOT_ASSESSED"                    # not searched / not evaluated


class SourceTier(str, Enum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"   # court order, regulator order, MCA filing, bank record
    HIGH = "HIGH"                           # established newsroom original reporting
    MEDIUM = "MEDIUM"                       # secondary reporting, trade press
    LOW = "LOW"                             # blogs, forums, aggregators
    SELF_REPORTED = "SELF_REPORTED"         # subject's own statement / own website
    NOT_EVIDENCE = "NOT_EVIDENCE"           # AI-generated, unverifiable paste, leaked creds


TIER_WEIGHT = {
    SourceTier.PRIMARY_OFFICIAL: 1.0,
    SourceTier.HIGH: 0.8,
    SourceTier.MEDIUM: 0.6,
    SourceTier.LOW: 0.3,
    SourceTier.SELF_REPORTED: 0.25,
    SourceTier.NOT_EVIDENCE: 0.0,
}

ADEQUATE = {SourceTier.PRIMARY_OFFICIAL, SourceTier.HIGH, SourceTier.MEDIUM}

LEGACY_MAP = {
    # confidence_engine.ConfidenceLevel
    "CONFIRMED": EvidenceStatus.STRONGLY_CORROBORATED,
    "HIGH": EvidenceStatus.STRONGLY_CORROBORATED,
    "MODERATE": EvidenceStatus.REPORTED,
    "LOW": EvidenceStatus.UNVERIFIED,
    "VERY_LOW": EvidenceStatus.UNVERIFIED,
    # synthesis / dossier / report states
    "CORROBORATED": EvidenceStatus.STRONGLY_CORROBORATED,
    "DEVELOPING": EvidenceStatus.REPORTED,
    "CONTESTED": EvidenceStatus.DISPUTED,
    "CONTRADICTED": EvidenceStatus.DISPUTED,
    "INSUFFICIENT_EVIDENCE": EvidenceStatus.UNVERIFIED,
    "REVIEW_REQUIRED": EvidenceStatus.DISPUTED,
    # negative finding
    "FOUND": EvidenceStatus.REPORTED,
    "NOT_FOUND": EvidenceStatus.NOT_ESTABLISHED,
    "PARTIAL": EvidenceStatus.UNVERIFIED,
    "INCONCLUSIVE": EvidenceStatus.UNVERIFIED,
    "NOT_ASSESSED": EvidenceStatus.NOT_ASSESSED,
}

# Phrase each status may be rendered with.  (English, Hindi)
LANGUAGE = {
    EvidenceStatus.ESTABLISHED: ("Official records show", "आधिकारिक रिकॉर्ड दर्शाते हैं"),
    EvidenceStatus.STRONGLY_CORROBORATED: ("Multiple independent sources report", "कई स्वतंत्र स्रोत बताते हैं"),
    EvidenceStatus.REPORTED: ("It has been reported that", "रिपोर्ट किया गया है कि"),
    EvidenceStatus.UNVERIFIED: ("Unverified claim:", "अप्रमाणित दावा:"),
    EvidenceStatus.DISPUTED: ("Sources conflict on whether", "स्रोतों में इस पर विरोधाभास है कि"),
    EvidenceStatus.NOT_ESTABLISHED: ("Not found in the sources searched:", "खोजे गए स्रोतों में नहीं मिला:"),
    EvidenceStatus.NOT_AVAILABLE: ("Could not be checked (source unavailable):", "जाँच नहीं हो सकी (स्रोत उपलब्ध नहीं):"),
    EvidenceStatus.NOT_ASSESSED: ("Not assessed:", "आकलन नहीं हुआ:"),
}


def to_canonical(value) -> EvidenceStatus:
    raw = getattr(value, "value", value)
    raw = str(raw or "").upper()
    if raw in EvidenceStatus.__members__:
        return EvidenceStatus(raw)
    return LEGACY_MAP.get(raw, EvidenceStatus.NOT_ASSESSED)


def tier_of(value) -> SourceTier:
    raw = str(getattr(value, "value", value) or "").upper()
    return SourceTier(raw) if raw in SourceTier.__members__ else SourceTier.LOW


def determine_status(
    *,
    assessed: bool,
    independent_lineages: int,
    best_tier: Optional[SourceTier],
    adequate_lineages: int = 0,
    material_contradiction: bool = False,
    unavailable: bool = False,
) -> EvidenceStatus:
    """Single rule used by every module.  Quality ceiling: weak sources never exceed UNVERIFIED."""
    if unavailable:
        return EvidenceStatus.NOT_AVAILABLE
    if not assessed:
        return EvidenceStatus.NOT_ASSESSED
    if material_contradiction:
        return EvidenceStatus.DISPUTED
    if independent_lineages <= 0 or best_tier is None:
        return EvidenceStatus.NOT_ESTABLISHED
    if best_tier == SourceTier.PRIMARY_OFFICIAL:
        return EvidenceStatus.ESTABLISHED
    if adequate_lineages >= 2:
        return EvidenceStatus.STRONGLY_CORROBORATED
    if adequate_lineages >= 1:
        return EvidenceStatus.REPORTED
    return EvidenceStatus.UNVERIFIED


def phrase(status: EvidenceStatus, lang: str = "en") -> str:
    en, hi = LANGUAGE[to_canonical(status)]
    return hi if lang == "hi" else en
