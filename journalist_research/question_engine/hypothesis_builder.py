"""
Deep OSINT Agent (DOA)
Hypothesis Builder

Converts parsed investigative questions into testable hypotheses.

Core rule:
    Hypothesis != Finding
    Hypothesis != Fact
    Hypothesis != Accusation

Every hypothesis starts with confidence=None and status=UNKNOWN.
The engine explicitly defines both supporting evidence and
counter-evidence that should be sought.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from journalist_research.models import (
    ClaimStatus,
    Hypothesis,
)
from journalist_research.question_engine.question_parser import (
    ParsedQuestion,
    parse_question,
)


# ============================================================
# HYPOTHESIS TEMPLATES
# ============================================================

HYPOTHESIS_TEMPLATES: Dict[str, List[Dict[str, object]]] = {

    "IDENTITY": [
        {
            "statement": (
                "The identified target may correspond to a "
                "specific real-world identity that can be independently corroborated."
            ),
            "evidence": [
                "Government or regulatory records",
                "Court records",
                "Corporate records",
                "Multiple independent reputable sources",
                "Consistent identifiers across dated sources",
            ],
            "counter": [
                "Conflicting identity information",
                "Different person with same/similar name",
                "Inconsistent dates or locations",
                "Independent sources identifying another person",
            ],
        }
    ],

    "RELATIONSHIP": [
        {
            "statement": (
                "A publicly documented relationship may exist between "
                "the identified entities."
            ),
            "evidence": [
                "Corporate filings",
                "Court records",
                "Official records",
                "Direct statements from reliable sources",
                "Multiple independent sources",
            ],
            "counter": [
                "No primary-source evidence",
                "Relationship claim appears only in secondary sources",
                "Sources contradict the claimed relationship",
                "Relationship is based only on geographic or social proximity",
            ],
        }
    ],

    "CORPORATE": [
        {
            "statement": (
                "The target may have a documented corporate connection "
                "through ownership, directorship, shareholding, or another "
                "official corporate role."
            ),
            "evidence": [
                "Company registry records",
                "Annual filings",
                "Regulatory filings",
                "Official corporate documents",
                "Historical corporate records",
            ],
            "counter": [
                "No official corporate record",
                "Different person with similar name",
                "Corporate record predates or postdates the claimed relationship",
                "Official records contradict the claim",
            ],
        }
    ],

    "FINANCIAL": [
        {
            "statement": (
                "There may be publicly documented financial or corporate "
                "financial activity relevant to the investigation."
            ),
            "evidence": [
                "Official financial filings",
                "Court records",
                "Regulatory records",
                "Corporate disclosures",
                "Documented transactions from lawful public sources",
            ],
            "counter": [
                "No primary financial evidence",
                "Claim originates only from unverified reporting",
                "Records contradict the alleged activity",
                "Financial terminology without transaction evidence",
            ],
        }
    ],

    "LEGAL": [
        {
            "statement": (
                "The target may have a documented legal proceeding or "
                "court record relevant to the investigation."
            ),
            "evidence": [
                "Court docket",
                "Judgment",
                "Order",
                "Official case record",
                "Authenticated legal document",
            ],
            "counter": [
                "No official case record found",
                "Different person with same name",
                "Case status contradicts the reported claim",
                "Secondary report cannot be independently corroborated",
            ],
        }
    ],

    "REGULATORY": [
        {
            "statement": (
                "A regulator or government authority may have taken a "
                "documented action involving the target."
            ),
            "evidence": [
                "Official regulatory notice",
                "Enforcement order",
                "Penalty order",
                "Government investigation record",
                "Regulatory database",
            ],
            "counter": [
                "No official regulatory record",
                "Notice concerns a different entity",
                "Action was withdrawn or overturned",
                "Secondary reporting conflicts with official records",
            ],
        }
    ],

    "DIGITAL_FOOTPRINT": [
        {
            "statement": (
                "A publicly accessible digital footprint may be "
                "attributable to the identified target."
            ),
            "evidence": [
                "Official website",
                "Verified public profile",
                "Domain registration history where lawfully available",
                "Archived website",
                "Multiple consistent digital identifiers",
            ],
            "counter": [
                "Identity cannot be reliably attributed",
                "Conflicting ownership information",
                "Digital profile belongs to another person/entity",
                "Evidence is only an unverified online claim",
            ],
        }
    ],

    "HISTORICAL": [
        {
            "statement": (
                "Historical records may establish how the target's "
                "identity, organization, role, or digital presence changed over time."
            ),
            "evidence": [
                "Archived webpages",
                "Dated corporate filings",
                "Historical court records",
                "Historical government records",
                "Contemporaneous reputable reporting",
            ],
            "counter": [
                "Archive provenance is unclear",
                "Dates cannot be independently established",
                "Historical records conflict",
                "Material appears to have been altered or republished",
            ],
        }
    ],

    "NETWORK": [
        {
            "statement": (
                "The target may have publicly documented relationships "
                "with specific people or organizations."
            ),
            "evidence": [
                "Corporate records",
                "Court documents",
                "Official organizational records",
                "Multiple independent sources",
                "Direct documented association",
            ],
            "counter": [
                "Association exists only in one source",
                "Association is inferred from proximity",
                "Sources contradict the relationship",
                "No evidence establishes the nature of the relationship",
            ],
        }
    ],

    "LOCATION": [
        {
            "statement": (
                "A publicly documented location or registered address "
                "may be associated with the target."
            ),
            "evidence": [
                "Corporate registry",
                "Government records",
                "Official filings",
                "Authenticated public documents",
            ],
            "counter": [
                "Address belongs to another entity",
                "Address is outdated",
                "Only an unverified source reports the location",
                "No reliable attribution",
            ],
        }
    ],

    "ADVERSE_MEDIA": [
        {
            "statement": (
                "Reputable sources may contain adverse reporting or "
                "allegations relevant to the target that require verification."
            ),
            "evidence": [
                "Reputable contemporaneous reporting",
                "Primary documents cited by the reporting",
                "Court or regulatory records",
                "Independent corroboration",
            ],
            "counter": [
                "No primary evidence",
                "Claim appears only in low-reliability sources",
                "Target or official records contradict the allegation",
                "Reporting is based on an unverified claim",
            ],
        }
    ],
}


# ============================================================
# RESULT MODEL
# ============================================================

@dataclass
class HypothesisSet:
    hypotheses: List[Hypothesis] = field(default_factory=list)

    source_question: str = ""

    categories_used: List[str] = field(default_factory=list)

    methodology_notes: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, object] = field(default_factory=dict)


# ============================================================
# HYPOTHESIS CREATION
# ============================================================

def _make_hypothesis(
    statement: str,
    evidence: List[str],
    counter_evidence: List[str],
    priority: int,
) -> Hypothesis:

    hypothesis = Hypothesis(
        statement=statement,
        priority=priority,
        confidence=None,
        status=ClaimStatus.UNKNOWN,
        required_evidence=list(evidence),
        metadata={
            "supporting_evidence_targets": list(evidence),
            "counter_evidence_targets": list(counter_evidence),
            "assessment_status": "NOT_ASSESSED",
            "fact_established": False,
        },
    )

    return hypothesis


def build_hypotheses(
    parsed: ParsedQuestion,
) -> HypothesisSet:

    hypotheses: List[Hypothesis] = []

    priority = 1

    for category in parsed.categories:

        templates = HYPOTHESIS_TEMPLATES.get(
            category,
            [],
        )

        for template in templates:

            hypothesis = _make_hypothesis(
                statement=str(template["statement"]),
                evidence=list(template["evidence"]),
                counter_evidence=list(template["counter"]),
                priority=priority,
            )

            hypotheses.append(hypothesis)

            priority += 1

    notes = [
        "Hypotheses are investigative propositions, not findings.",
        "No hypothesis receives an initial confidence score.",
        "Supporting evidence and counter-evidence must both be investigated.",
        "Association alone must not establish wrongdoing.",
        "Identity must be independently resolved before attributing claims.",
        "Absence of evidence must not automatically be interpreted as innocence.",
        "Low-quality sources must not be promoted to established facts.",
    ]

    return HypothesisSet(
        hypotheses=hypotheses,
        source_question=parsed.original_text,
        categories_used=list(parsed.categories),
        methodology_notes=notes,
        metadata={
            "builder_version": "DOA-HB-1.0",
            "assessment_performed": False,
            "fact_establishment": False,
        },
    )


def build_from_question(
    question: str,
) -> HypothesisSet:

    parsed = parse_question(question)

    return build_hypotheses(parsed)


# ============================================================
# VALIDATION
# ============================================================

def validate_hypothesis_set(
    hypothesis_set: HypothesisSet,
) -> List[str]:

    errors: List[str] = []

    for index, hypothesis in enumerate(
        hypothesis_set.hypotheses,
        start=1,
    ):

        if not hypothesis.statement.strip():
            errors.append(
                f"Hypothesis {index}: empty statement."
            )

        if hypothesis.confidence is not None:
            errors.append(
                f"Hypothesis {index}: confidence must remain "
                f"None until assessment."
            )

        if hypothesis.status != ClaimStatus.UNKNOWN:
            errors.append(
                f"Hypothesis {index}: initial status must be UNKNOWN."
            )

        counter = hypothesis.metadata.get(
            "counter_evidence_targets"
        )

        if not counter:
            errors.append(
                f"Hypothesis {index}: counter-evidence missing."
            )

    return errors


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "HypothesisSet",
    "build_hypotheses",
    "build_from_question",
    "validate_hypothesis_set",
]
