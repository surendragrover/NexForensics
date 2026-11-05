"""
Deep OSINT Agent (DOA)
Question Parser

Converts a journalist's natural-language investigative question into
a structured research specification.

Important:
- The parser does NOT establish facts.
- It does NOT identify suspects.
- It does NOT infer guilt.
- It produces investigation dimensions and research questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from journalist_research.models import (
    Question,
    Entity,
    EntityType,
)


# ============================================================
# QUESTION CATEGORIES
# ============================================================

QUESTION_CATEGORIES = {
    "IDENTITY": [
        "who is",
        "who exactly",
        "identity",
        "real identity",
        "alias",
        "aka",
        "कौन है",
        "पहचान",
        "वास्तविक पहचान",
        "असली नाम",
    ],
    "RELATIONSHIP": [
        "relationship",
        "connected",
        "connection",
        "linked",
        "associated",
        "relation",
        "संबंध",
        "रिश्ता",
        "जुड़ा",
        "जुड़े",
        "कनेक्शन",
        "संबंधित",
    ],
    "CORPORATE": [
        "company",
        "companies",
        "director",
        "shareholder",
        "owner",
        "ownership",
        "corporate",
        "कंपनी",
        "कंपनियां",
        "निदेशक",
        "शेयरहोल्डर",
        "मालिक",
        "स्वामित्व",
    ],
    "FINANCIAL": [
        "money",
        "payment",
        "transaction",
        "bank",
        "account",
        "fund",
        "financial",
        "finance",
        "wealth",
        "पैसा",
        "भुगतान",
        "लेनदेन",
        "बैंक",
        "खाता",
        "वित्त",
        "धन",
    ],
    "LEGAL": [
        "court",
        "case",
        "lawsuit",
        "litigation",
        "fir",
        "charges",
        "convicted",
        "legal",
        "अदालत",
        "मामला",
        "मुकदमा",
        "एफआईआर",
        "आरोप",
        "कानूनी",
    ],
    "REGULATORY": [
        "regulator",
        "regulatory",
        "notice",
        "penalty",
        "fine",
        "investigation",
        "sanction",
        "नियामक",
        "नियामकीय",
        "नोटिस",
        "जुर्माना",
        "प्रतिबंध",
        "जांच",
    ],
    "DIGITAL_FOOTPRINT": [
        "website",
        "domain",
        "online",
        "social media",
        "digital footprint",
        "internet",
        "वेबसाइट",
        "डोमेन",
        "ऑनलाइन",
        "सोशल मीडिया",
        "डिजिटल",
        "इंटरनेट",
    ],
    "HISTORICAL": [
        "history",
        "historical",
        "past",
        "previous",
        "earlier",
        "archive",
        "इतिहास",
        "पुराना",
        "पुराने",
        "पहले",
        "अतीत",
        "अभिलेख",
    ],
    "NETWORK": [
        "network",
        "associates",
        "partners",
        "contacts",
        "connections",
        "नेटवर्क",
        "सहयोगी",
        "साझेदार",
        "संपर्क",
        "कनेक्शन",
    ],
    "LOCATION": [
        "address",
        "location",
        "located",
        "residence",
        "office",
        "where",
        "पता",
        "स्थान",
        "कहां",
        "कहाँ",
        "निवास",
        "दफ्तर",
        "कार्यालय",
    ],
    "ADVERSE_MEDIA": [
        "scandal",
        "controversy",
        "allegation",
        "accusation",
        "fraud",
        "corruption",
        "crime",
        "scam",
        "घोटाला",
        "विवाद",
        "आरोप",
        "धोखाधड़ी",
        "भ्रष्टाचार",
        "अपराध",
    ],
}


# ============================================================
# INVESTIGATION DIMENSIONS
# ============================================================

DIMENSION_MAP = {
    "IDENTITY": [
        "legal name",
        "aliases",
        "identity corroboration",
        "identity disambiguation",
    ],
    "RELATIONSHIP": [
        "relationship records",
        "corporate links",
        "professional links",
        "publicly documented associations",
    ],
    "CORPORATE": [
        "company registrations",
        "directorships",
        "ownership",
        "shareholding",
        "registered addresses",
    ],
    "FINANCIAL": [
        "public financial records",
        "corporate financial signals",
        "regulatory financial actions",
        "documented transactions",
    ],
    "LEGAL": [
        "court records",
        "litigation history",
        "case records",
        "documented legal proceedings",
    ],
    "REGULATORY": [
        "regulatory actions",
        "notices",
        "penalties",
        "sanctions",
        "official investigations",
    ],
    "DIGITAL_FOOTPRINT": [
        "official websites",
        "domains",
        "public social profiles",
        "historical web presence",
    ],
    "HISTORICAL": [
        "archived websites",
        "historical records",
        "previous names",
        "timeline reconstruction",
    ],
    "NETWORK": [
        "known associates",
        "business partners",
        "organizational relationships",
        "relationship graph",
    ],
    "LOCATION": [
        "publicly documented addresses",
        "registered locations",
        "office locations",
    ],
    "ADVERSE_MEDIA": [
        "reputable media coverage",
        "documented allegations",
        "corroborated adverse reporting",
        "counter-evidence",
    ],
}


# ============================================================
# RESULT MODEL
# ============================================================

@dataclass
class ParsedQuestion:
    original_text: str

    normalized_text: str

    categories: List[str] = field(default_factory=list)

    dimensions: List[str] = field(default_factory=list)

    entities: List[Entity] = field(default_factory=list)

    sub_questions: List[Question] = field(default_factory=list)

    ambiguity_flags: List[str] = field(default_factory=list)

    investigative_constraints: List[str] = field(default_factory=list)

    metadata: Dict[str, object] = field(default_factory=dict)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


# ============================================================
# CATEGORY DETECTION
# ============================================================

def detect_categories(text: str) -> List[str]:
    lowered = text.lower()

    detected = []

    for category, keywords in QUESTION_CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                detected.append(category)
                break

    return detected


# ============================================================
# ENTITY EXTRACTION
# ============================================================

def extract_quoted_entities(text: str) -> List[Entity]:
    """
    Extract explicitly quoted names/entities.

    Example:
        क्या "Rajesh Kumar" का "ABC Ltd" से संबंध है?
    """

    entities: List[Entity] = []

    patterns = [
        r'"([^"]+)"',
        r"'([^']+)'",
        r"“([^”]+)”",
        r"‘([^’]+)’",
    ]

    seen = set()

    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = match.strip()

            if not value:
                continue

            key = value.casefold()

            if key in seen:
                continue

            seen.add(key)

            entities.append(
                Entity(
                    name=value,
                    entity_type=EntityType.UNKNOWN,
                    confidence=None,
                    verified=False,
                )
            )

    return entities


def extract_capitalized_entities(text: str) -> List[Entity]:
    """
    Conservative extraction of Latin-script proper-name candidates.

    This is deliberately NOT treated as identity resolution.
    """

    entities: List[Entity] = []

    pattern = r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){1,5}\b"

    seen = set()

    for match in re.findall(pattern, text):
        value = match.strip()

        if len(value) < 3:
            continue

        key = value.casefold()

        if key in seen:
            continue

        seen.add(key)

        entities.append(
            Entity(
                name=value,
                entity_type=EntityType.UNKNOWN,
                confidence=None,
                verified=False,
            )
        )

    return entities


def extract_entities(text: str) -> List[Entity]:
    entities = extract_quoted_entities(text)

    existing = {
        entity.name.casefold()
        for entity in entities
    }

    for entity in extract_capitalized_entities(text):
        if entity.name.casefold() not in existing:
            entities.append(entity)
            existing.add(entity.name.casefold())

    return entities


# ============================================================
# SUB-QUESTION GENERATION
# ============================================================

def build_sub_questions(
    categories: List[str],
    entities: List[Entity],
) -> List[Question]:

    questions: List[Question] = []

    entity_names = [
        entity.name
        for entity in entities
    ]

    target = (
        ", ".join(entity_names)
        if entity_names
        else "the identified target"
    )

    templates = {
        "IDENTITY": [
            f"What independently verifiable identity records exist for {target}?",
            f"Are any aliases or alternate names for {target} independently corroborated?",
        ],
        "RELATIONSHIP": [
            f"What publicly documented relationships involving {target} can be independently corroborated?",
            f"Are the claimed relationships supported by primary or independent sources?",
        ],
        "CORPORATE": [
            f"What companies or corporate records are associated with {target}?",
            f"Are directorship, ownership or shareholding claims independently documented?",
        ],
        "FINANCIAL": [
            f"What public financial or corporate records are relevant to {target}?",
            f"Are any financial claims independently corroborated?",
        ],
        "LEGAL": [
            f"What court or legal records involving {target} can be verified?",
            f"What is the documented procedural status of each identified case?",
        ],
        "REGULATORY": [
            f"What regulatory actions or official notices involving {target} can be verified?",
        ],
        "DIGITAL_FOOTPRINT": [
            f"What publicly accessible digital footprint can be attributed to {target}?",
            f"Can the attribution be independently corroborated?",
        ],
        "HISTORICAL": [
            f"What historical records or archived web evidence exist for {target}?",
            f"Can changes over time be established from dated sources?",
        ],
        "NETWORK": [
            f"Which publicly documented people or organizations are connected to {target}?",
            f"Which relationships have independent corroboration?",
        ],
        "LOCATION": [
            f"What publicly documented locations or registered addresses are associated with {target}?",
        ],
        "ADVERSE_MEDIA": [
            f"What reputable-source allegations or adverse reporting involving {target} exist?",
            f"What supporting evidence and counter-evidence exist for those claims?",
        ],
    }

    priority = 1

    for category in categories:
        for text in templates.get(category, []):
            questions.append(
                Question(
                    text=text,
                    priority=priority,
                    category=category,
                    generated_from="DOA_QUESTION_PARSER",
                )
            )

        priority += 1

    return questions


# ============================================================
# CONSTRAINTS
# ============================================================

def build_constraints(categories: List[str]) -> List[str]:
    constraints = [
        "Do not treat search results as established facts.",
        "Require source provenance for every substantive claim.",
        "Separate allegations from verified findings.",
        "Preserve contradictory evidence.",
        "Do not infer guilt from association alone.",
        "Do not resolve identity from geographic overlap alone.",
    ]

    if "ADVERSE_MEDIA" in categories:
        constraints.append(
            "Adverse claims require source-quality assessment and corroboration."
        )

    if "IDENTITY" in categories:
        constraints.append(
            "Identity matches require disambiguation and wrong-person rejection."
        )

    if "FINANCIAL" in categories:
        constraints.append(
            "Financial language alone must not be treated as financial evidence."
        )

    return constraints


# ============================================================
# MAIN PARSER
# ============================================================

def parse_question(text: str) -> ParsedQuestion:

    if not isinstance(text, str):
        raise TypeError("Question must be a string.")

    normalized = normalize_text(text)

    if not normalized:
        raise ValueError("Question cannot be empty.")

    categories = detect_categories(normalized)

    if not categories:
        categories = ["IDENTITY"]

    dimensions: List[str] = []

    for category in categories:
        for dimension in DIMENSION_MAP.get(category, []):
            if dimension not in dimensions:
                dimensions.append(dimension)

    entities = extract_entities(normalized)

    sub_questions = build_sub_questions(
        categories,
        entities,
    )

    ambiguity_flags = []

    if not entities:
        ambiguity_flags.append(
            "No explicit target entity was extracted."
        )

    if len(entities) > 1:
        ambiguity_flags.append(
            "Multiple entity candidates detected; identity resolution is required."
        )

    return ParsedQuestion(
        original_text=text,
        normalized_text=normalized,
        categories=categories,
        dimensions=dimensions,
        entities=entities,
        sub_questions=sub_questions,
        ambiguity_flags=ambiguity_flags,
        investigative_constraints=build_constraints(categories),
        metadata={
            "parser_version": "DOA-QP-1.0",
            "fact_establishment": False,
            "identity_resolution_performed": False,
        },
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "ParsedQuestion",
    "parse_question",
    "detect_categories",
    "extract_entities",
    "build_sub_questions",
]
