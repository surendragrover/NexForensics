"""
Deep OSINT Agent (DOA)
Search Plan Generator v1.1

Converts parsed questions and hypotheses into executable research tasks.

Important:
    Hypothesis text is NOT itself a search query.

Pipeline:
    Hypothesis
        ↓
    Research Objective
        ↓
    Query Templates
        ↓
    Search Tasks

Every investigative proposition receives:
    - supporting-evidence searches
    - counter-evidence searches

This module does NOT perform web searches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from journalist_research.models import (
    Hypothesis,
    SearchTask,
    SourceType,
)
from journalist_research.question_engine.hypothesis_builder import (
    HypothesisSet,
)


# ============================================================
# SEARCH STRATEGIES
# ============================================================

SEARCH_STRATEGIES: Dict[str, Dict[str, object]] = {

    "IDENTITY": {
        "supporting": [
            (
                "Identity verification",
                [
                    '"{target}" official identity',
                    '"{target}" government record',
                    '"{target}" court record',
                ],
                [
                    SourceType.GOVERNMENT,
                    SourceType.REGULATORY,
                    SourceType.COURT,
                ],
            ),
            (
                "Identity corroboration",
                [
                    '"{target}" biography',
                    '"{target}" profile',
                    '"{target}" "{target2}"',
                ],
                [
                    SourceType.JOURNALISM,
                    SourceType.CORPORATE,
                    SourceType.PUBLIC_DATABASE,
                ],
            ),
        ],
        "counter": [
            (
                "Wrong-person rejection",
                [
                    '"{target}" same name',
                    '"{target}" different person',
                    '"{target}" conflicting identity',
                ],
                [
                    SourceType.GOVERNMENT,
                    SourceType.COURT,
                    SourceType.JOURNALISM,
                ],
            ),
        ],
    },

    "RELATIONSHIP": {
        "supporting": [
            (
                "Relationship verification",
                [
                    '"{target}" relationship',
                    '"{target}" associated with "{target2}"',
                    '"{target}" connected to "{target2}"',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.GOVERNMENT,
                    SourceType.COURT,
                ],
            ),
            (
                "Independent corroboration",
                [
                    '"{target}" "{target2}"',
                    '"{target}" partner "{target2}"',
                    '"{target}" associate "{target2}"',
                ],
                [
                    SourceType.JOURNALISM,
                    SourceType.CORPORATE,
                ],
            ),
        ],
        "counter": [
            (
                "Relationship challenge",
                [
                    '"{target}" "{target2}" no relationship',
                    '"{target}" "{target2}" denied',
                    '"{target}" "{target2}" conflicting',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.GOVERNMENT,
                    SourceType.JOURNALISM,
                ],
            ),
        ],
    },

    "CORPORATE": {
        "supporting": [
            (
                "Corporate registry",
                [
                    '"{target}" company',
                    '"{target}" director',
                    '"{target}" corporate filing',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.GOVERNMENT,
                    SourceType.REGULATORY,
                ],
            ),
            (
                "Ownership and directorship",
                [
                    '"{target}" shareholder',
                    '"{target}" ownership',
                    '"{target}" director company',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.REGULATORY,
                ],
            ),
        ],
        "counter": [
            (
                "Corporate contradiction",
                [
                    '"{target}" ownership dispute',
                    '"{target}" director dispute',
                    '"{target}" company record discrepancy',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.REGULATORY,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
    },

    "FINANCIAL": {
        "supporting": [
            (
                "Financial records",
                [
                    '"{target}" financial filing',
                    '"{target}" annual report',
                    '"{target}" financial records',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.REGULATORY,
                    SourceType.GOVERNMENT,
                ],
            ),
            (
                "Financial enforcement",
                [
                    '"{target}" financial penalty',
                    '"{target}" financial investigation',
                    '"{target}" regulatory action',
                ],
                [
                    SourceType.REGULATORY,
                    SourceType.COURT,
                ],
            ),
        ],
        "counter": [
            (
                "Financial claim challenge",
                [
                    '"{target}" financial claim disputed',
                    '"{target}" transaction claim denied',
                    '"{target}" financial records contradiction',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.REGULATORY,
                    SourceType.COURT,
                ],
            ),
        ],
    },

    "LEGAL": {
        "supporting": [
            (
                "Court record search",
                [
                    '"{target}" court case',
                    '"{target}" court order',
                    '"{target}" judgment',
                ],
                [
                    SourceType.COURT,
                ],
            ),
            (
                "Legal reporting corroboration",
                [
                    '"{target}" lawsuit',
                    '"{target}" litigation',
                    '"{target}" court proceedings',
                ],
                [
                    SourceType.JOURNALISM,
                ],
            ),
        ],
        "counter": [
            (
                "Legal status verification",
                [
                    '"{target}" case dismissed',
                    '"{target}" acquitted',
                    '"{target}" case withdrawn',
                    '"{target}" legal status',
                ],
                [
                    SourceType.COURT,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
    },

    "REGULATORY": {
        "supporting": [
            (
                "Regulatory record search",
                [
                    '"{target}" regulatory notice',
                    '"{target}" enforcement action',
                    '"{target}" regulatory penalty',
                ],
                [
                    SourceType.REGULATORY,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
        "counter": [
            (
                "Regulatory status challenge",
                [
                    '"{target}" regulatory action withdrawn',
                    '"{target}" penalty overturned',
                    '"{target}" regulatory notice cancelled',
                ],
                [
                    SourceType.REGULATORY,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
    },

    "DIGITAL_FOOTPRINT": {
        "supporting": [
            (
                "Official web presence",
                [
                    '"{target}" official website',
                    '"{target}" official',
                    '"{target}" website',
                    '"{target}" domain',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.PUBLIC_DATABASE,
                    SourceType.SOCIAL_MEDIA,
                ],
            ),
            (
                "Historical digital footprint",
                [
                    '"{target}" archive',
                    '"{target}" historical website',
                    '"{target}" previous website',
                    '"{target}" domain history',
                ],
                [
                    SourceType.ARCHIVED_WEB,
                    SourceType.PUBLIC_DATABASE,
                ],
            ),
        ],
        "counter": [
            (
                "Digital attribution challenge",
                [
                    '"{target}" different company',
                    '"{target}" different person',
                    '"{target}" domain ownership dispute',
                    '"{target}" website ownership dispute',
                ],
                [
                    SourceType.ARCHIVED_WEB,
                    SourceType.CORPORATE,
                    SourceType.PUBLIC_DATABASE,
                ],
            ),
        ],
    },

    "HISTORICAL": {
        "supporting": [
            (
                "Historical records",
                [
                    '"{target}" historical records',
                    '"{target}" history',
                    '"{target}" archive',
                    '"{target}" previous name',
                ],
                [
                    SourceType.ARCHIVED_WEB,
                    SourceType.CORPORATE,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
        "counter": [
            (
                "Historical consistency check",
                [
                    '"{target}" conflicting history',
                    '"{target}" conflicting dates',
                    '"{target}" previous name disputed',
                    '"{target}" ownership history dispute',
                ],
                [
                    SourceType.ARCHIVED_WEB,
                    SourceType.CORPORATE,
                    SourceType.JOURNALISM,
                ],
            ),
        ],
    },

    "NETWORK": {
        "supporting": [
            (
                "Relationship network",
                [
                    '"{target}" associates',
                    '"{target}" partners',
                    '"{target}" business connections',
                    '"{target}" network',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.GOVERNMENT,
                    SourceType.COURT,
                ],
            ),
            (
                "Network corroboration",
                [
                    '"{target}" associated with',
                    '"{target}" partner',
                    '"{target}" business relationship',
                ],
                [
                    SourceType.JOURNALISM,
                ],
            ),
        ],
        "counter": [
            (
                "Association challenge",
                [
                    '"{target}" association denied',
                    '"{target}" no connection',
                    '"{target}" relationship disputed',
                ],
                [
                    SourceType.CORPORATE,
                    SourceType.COURT,
                    SourceType.JOURNALISM,
                ],
            ),
        ],
    },

    "LOCATION": {
        "supporting": [
            (
                "Public location records",
                [
                    '"{target}" registered address',
                    '"{target}" office address',
                    '"{target}" location',
                ],
                [
                    SourceType.GOVERNMENT,
                    SourceType.CORPORATE,
                    SourceType.REGULATORY,
                ],
            ),
        ],
        "counter": [
            (
                "Location attribution challenge",
                [
                    '"{target}" address changed',
                    '"{target}" address disputed',
                    '"{target}" different address',
                ],
                [
                    SourceType.GOVERNMENT,
                    SourceType.CORPORATE,
                ],
            ),
        ],
    },

    "ADVERSE_MEDIA": {
        "supporting": [
            (
                "Adverse-media research",
                [
                    '"{target}" allegation',
                    '"{target}" controversy',
                    '"{target}" investigation',
                    '"{target}" fraud',
                ],
                [
                    SourceType.JOURNALISM,
                ],
            ),
            (
                "Primary-source corroboration",
                [
                    '"{target}" court allegation',
                    '"{target}" regulatory investigation',
                    '"{target}" government investigation',
                ],
                [
                    SourceType.COURT,
                    SourceType.GOVERNMENT,
                    SourceType.REGULATORY,
                ],
            ),
        ],
        "counter": [
            (
                "Adverse-claim challenge",
                [
                    '"{target}" allegation denied',
                    '"{target}" allegation retracted',
                    '"{target}" correction',
                    '"{target}" contrary evidence',
                ],
                [
                    SourceType.JOURNALISM,
                    SourceType.COURT,
                    SourceType.GOVERNMENT,
                ],
            ),
        ],
    },
}


# ============================================================
# RESULT MODEL
# ============================================================

@dataclass
class SearchPlan:
    investigation_question: str

    tasks: List[SearchTask] = field(
        default_factory=list
    )

    categories: List[str] = field(
        default_factory=list
    )

    target_entities: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, object] = field(
        default_factory=dict
    )


# ============================================================
# ENTITY / TARGET EXTRACTION
# ============================================================

def extract_targets_from_question(
    question: str,
) -> List[str]:
    """
    Extract explicitly quoted targets.

    This intentionally remains conservative.
    Full identity resolution happens later.
    """

    patterns = [
        r'"([^"]+)"',
        r"'([^']+)'",
        r"“([^”]+)”",
        r"‘([^’]+)’",
    ]

    targets: List[str] = []
    seen = set()

    for pattern in patterns:
        for match in re.findall(pattern, question):
            value = match.strip()

            if not value:
                continue

            key = value.casefold()

            if key not in seen:
                targets.append(value)
                seen.add(key)

    return targets


def build_query(
    template: str,
    targets: List[str],
) -> str:

    target = targets[0] if targets else "target"

    target2 = (
        targets[1]
        if len(targets) > 1
        else target
    )

    return template.format(
        target=target,
        target2=target2,
    )


# ============================================================
# TASK CREATION
# ============================================================

def create_tasks_for_category(
    category: str,
    hypothesis: Hypothesis,
    targets: List[str],
) -> List[SearchTask]:

    strategy = SEARCH_STRATEGIES.get(category)

    if not strategy:
        return []

    tasks: List[SearchTask] = []

    # --------------------------------------------------------
    # SUPPORTING
    # --------------------------------------------------------

    for (
        strategy_name,
        query_templates,
        source_types,
    ) in strategy.get("supporting", []):

        for query_template in query_templates:

            query = build_query(
                query_template,
                targets,
            )

            task = SearchTask(
                query=query,
                purpose=(
                    f"SUPPORTING_EVIDENCE: "
                    f"{hypothesis.statement}"
                ),
                category=category,
                priority=hypothesis.priority,
                source_types=list(source_types),
                metadata={
                    "direction": "SUPPORTING",
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "strategy": strategy_name,
                    "query_template": query_template,
                    "fact_establishment": False,
                },
            )

            tasks.append(task)

    # --------------------------------------------------------
    # COUNTER
    # --------------------------------------------------------

    for (
        strategy_name,
        query_templates,
        source_types,
    ) in strategy.get("counter", []):

        for query_template in query_templates:

            query = build_query(
                query_template,
                targets,
            )

            task = SearchTask(
                query=query,
                purpose=(
                    f"COUNTER_EVIDENCE: "
                    f"{hypothesis.statement}"
                ),
                category=category,
                priority=hypothesis.priority,
                source_types=list(source_types),
                metadata={
                    "direction": "COUNTER",
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "strategy": strategy_name,
                    "query_template": query_template,
                    "fact_establishment": False,
                },
            )

            tasks.append(task)

    return tasks


# ============================================================
# CATEGORY MATCHING
# ============================================================

def _hypothesis_matches_category(
    hypothesis: Hypothesis,
    category: str,
) -> bool:

    category_terms = {
        "IDENTITY": [
            "identity",
            "aliases",
            "alternate names",
        ],
        "RELATIONSHIP": [
            "relationship",
            "association",
        ],
        "CORPORATE": [
            "corporate",
            "ownership",
            "directorship",
            "shareholding",
        ],
        "FINANCIAL": [
            "financial",
            "transactions",
        ],
        "LEGAL": [
            "legal proceeding",
            "court",
        ],
        "REGULATORY": [
            "regulator",
            "regulatory",
        ],
        "DIGITAL_FOOTPRINT": [
            "digital footprint",
        ],
        "HISTORICAL": [
            "historical records",
        ],
        "NETWORK": [
            "relationships",
            "people or organizations",
        ],
        "LOCATION": [
            "location",
            "address",
        ],
        "ADVERSE_MEDIA": [
            "adverse reporting",
            "allegations",
        ],
    }

    statement = hypothesis.statement.lower()

    return any(
        term.lower() in statement
        for term in category_terms.get(
            category,
            [],
        )
    )


# ============================================================
# PLAN GENERATOR
# ============================================================

def generate_search_plan(
    hypothesis_set: HypothesisSet,
) -> SearchPlan:

    targets = extract_targets_from_question(
        hypothesis_set.source_question
    )

    tasks: List[SearchTask] = []

    for category in hypothesis_set.categories_used:

        matching_hypotheses = [
            hypothesis
            for hypothesis in hypothesis_set.hypotheses
            if _hypothesis_matches_category(
                hypothesis,
                category,
            )
        ]

        for hypothesis in matching_hypotheses:

            tasks.extend(
                create_tasks_for_category(
                    category=category,
                    hypothesis=hypothesis,
                    targets=targets,
                )
            )

    tasks.sort(
        key=lambda task: (
            task.priority,
            task.metadata.get("direction", ""),
            task.category or "",
            task.query,
        )
    )

    return SearchPlan(
        investigation_question=hypothesis_set.source_question,
        tasks=tasks,
        categories=list(
            hypothesis_set.categories_used
        ),
        target_entities=targets,
        metadata={
            "planner_version": "DOA-SP-1.1",
            "execution_started": False,
            "search_performed": False,
            "fact_establishment": False,
            "hypothesis_text_used_as_query": False,
        },
    )


def generate_search_plan_for_question(
    question: str,
) -> SearchPlan:

    from journalist_research.question_engine.hypothesis_builder import (
        build_from_question,
    )

    hypothesis_set = build_from_question(
        question
    )

    return generate_search_plan(
        hypothesis_set
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_search_plan(
    plan: SearchPlan,
) -> List[str]:

    errors: List[str] = []

    if not plan.investigation_question.strip():
        errors.append(
            "Investigation question cannot be empty."
        )

    if not plan.tasks:
        errors.append(
            "Search plan contains no tasks."
        )

    if not plan.target_entities:
        errors.append(
            "No explicit target entity detected."
        )

    for index, task in enumerate(
        plan.tasks,
        start=1,
    ):

        if not task.query.strip():
            errors.append(
                f"Task {index}: empty query."
            )

        if task.metadata.get("direction") not in {
            "SUPPORTING",
            "COUNTER",
        }:
            errors.append(
                f"Task {index}: invalid evidence direction."
            )

        if not task.source_types:
            errors.append(
                f"Task {index}: no source types assigned."
            )

        if task.metadata.get(
            "fact_establishment"
        ) is not False:
            errors.append(
                f"Task {index}: fact establishment flag invalid."
            )

        # A search query must not simply be the hypothesis sentence.
        if (
            len(task.query.split()) > 12
            and "may be" in task.query.lower()
        ):
            errors.append(
                f"Task {index}: hypothesis prose appears in search query."
            )

    supporting = sum(
        1
        for task in plan.tasks
        if task.metadata.get("direction") == "SUPPORTING"
    )

    counter = sum(
        1
        for task in plan.tasks
        if task.metadata.get("direction") == "COUNTER"
    )

    if supporting == 0:
        errors.append(
            "No supporting-evidence tasks generated."
        )

    if counter == 0:
        errors.append(
            "No counter-evidence tasks generated."
        )

    return errors


# ============================================================
# QUERY NORMALIZATION / DEDUPLICATION
# ============================================================

def normalize_query(query: str) -> str:
    """
    Normalize a search query for duplicate detection.

    This does NOT alter the actual query sent to a search engine.
    It is only used for comparison.
    """

    value = query.strip().lower()

    # Normalize smart quotes.
    value = (
        value.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    # Collapse whitespace.
    value = re.sub(r"\s+", " ", value)

    # Remove punctuation that does not materially affect
    # duplicate detection.
    value = re.sub(
        r"[.,;:!?()\[\]{}]",
        " ",
        value,
    )

    value = re.sub(r"\s+", " ", value).strip()

    return value


def query_tokens(query: str) -> set[str]:
    """
    Return normalized lexical tokens.

    Quoted entity names remain represented by their words.
    """

    normalized = normalize_query(query)

    return {
        token
        for token in normalized.split()
        if token
    }


def query_similarity(
    query_a: str,
    query_b: str,
) -> float:
    """
    Jaccard token similarity.

    1.0 = identical token sets
    0.0 = no shared tokens
    """

    a = query_tokens(query_a)
    b = query_tokens(query_b)

    if not a or not b:
        return 0.0

    return len(a & b) / len(a | b)


def is_near_duplicate(
    query_a: str,
    query_b: str,
    threshold: float = 0.80,
) -> bool:

    if normalize_query(query_a) == normalize_query(query_b):
        return True

    return (
        query_similarity(query_a, query_b)
        >= threshold
    )


# ============================================================
# TASK PRIORITY
# ============================================================

SOURCE_PRIORITY = {
    SourceType.COURT: 10,
    SourceType.GOVERNMENT: 10,
    SourceType.REGULATORY: 10,
    SourceType.CORPORATE: 9,
    SourceType.ARCHIVED_WEB: 8,
    SourceType.PUBLIC_DATABASE: 7,
    SourceType.JOURNALISM: 6,
    SourceType.SOCIAL_MEDIA: 4,
    SourceType.FORUM: 2,
    SourceType.DARK_WEB: 1,
    SourceType.USER_SUBMITTED: 1,
    SourceType.UNKNOWN: 0,
}


def calculate_task_priority(
    task: SearchTask,
) -> Tuple[int, int, str]:
    """
    Returns a deterministic sorting key.

    Higher source quality and counter-evidence receive
    stronger execution priority.

    Counter searches are deliberately prioritized so that
    the engine does not build an apparently convincing case
    before actively looking for disconfirming evidence.
    """

    direction = task.metadata.get(
        "direction",
        "SUPPORTING",
    )

    direction_score = (
        100
        if direction == "COUNTER"
        else 50
    )

    source_score = max(
        (
            SOURCE_PRIORITY.get(
                source,
                0,
            )
            for source in task.source_types
        ),
        default=0,
    )

    hypothesis_priority = (
        100 - int(task.priority or 0)
    )

    return (
        direction_score
        + source_score
        + hypothesis_priority,
        source_score,
        task.query,
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_search_tasks(
    tasks: List[SearchTask],
    similarity_threshold: float = 0.80,
) -> Tuple[List[SearchTask], List[Dict[str, object]]]:
    """
    Remove exact and near-duplicate queries.

    Important:
        Supporting and counter searches are NEVER merged
        merely because their wording is similar.

    The evidence direction is part of the deduplication key.
    """

    kept: List[SearchTask] = []

    removed: List[Dict[str, object]] = []

    buckets: Dict[str, List[SearchTask]] = {}

    for task in tasks:

        direction = task.metadata.get(
            "direction",
            "SUPPORTING",
        )

        bucket_key = direction

        candidates = buckets.setdefault(
            bucket_key,
            [],
        )

        duplicate_of: Optional[SearchTask] = None

        for existing in candidates:

            if is_near_duplicate(
                task.query,
                existing.query,
                similarity_threshold,
            ):
                duplicate_of = existing
                break

        if duplicate_of is not None:

            removed.append(
                {
                    "removed_query": task.query,
                    "kept_query": duplicate_of.query,
                    "direction": direction,
                    "category": task.category,
                    "reason": (
                        "EXACT_DUPLICATE"
                        if normalize_query(
                            task.query
                        )
                        == normalize_query(
                            duplicate_of.query
                        )
                        else "NEAR_DUPLICATE"
                    ),
                }
            )

            continue

        candidates.append(task)
        kept.append(task)

    return kept, removed


# ============================================================
# FINAL SEARCH QUEUE
# ============================================================

def build_execution_queue(
    tasks: List[SearchTask],
    similarity_threshold: float = 0.80,
) -> Tuple[List[SearchTask], List[Dict[str, object]]]:
    """
    Build the final queue that a future web-search executor
    will consume.

    Stages:
        1. Deduplicate
        2. Prioritize
        3. Assign deterministic execution order
    """

    unique_tasks, removed = (
        deduplicate_search_tasks(
            tasks,
            similarity_threshold,
        )
    )

    unique_tasks.sort(
        key=calculate_task_priority,
        reverse=True,
    )

    for index, task in enumerate(
        unique_tasks,
        start=1,
    ):

        task.metadata[
            "execution_order"
        ] = index

        task.metadata[
            "deduplication_status"
        ] = "UNIQUE"

        task.metadata[
            "search_performed"
        ] = False

        task.metadata[
            "fact_establishment"
        ] = False

    return unique_tasks, removed


def optimize_search_plan(
    plan: SearchPlan,
    similarity_threshold: float = 0.80,
) -> SearchPlan:
    """
    Optimize an existing SearchPlan without executing searches.
    """

    original_count = len(plan.tasks)

    queue, removed = build_execution_queue(
        plan.tasks,
        similarity_threshold,
    )

    plan.tasks = queue

    plan.metadata[
        "original_task_count"
    ] = original_count

    plan.metadata[
        "optimized_task_count"
    ] = len(queue)

    plan.metadata[
        "duplicates_removed"
    ] = len(removed)

    plan.metadata[
        "search_queue_ready"
    ] = True

    plan.metadata[
        "search_performed"
    ] = False

    plan.metadata[
        "fact_establishment"
    ] = False

    plan.metadata[
        "removed_queries"
    ] = removed

    return plan



# ============================================================
# SOURCE-AWARE EXECUTION QUEUE
# ============================================================

# Lower number = earlier execution.
#
# Primary / authoritative sources are deliberately preferred.
# Journalism is useful for discovery and corroboration, but
# should not outrank court, government, regulatory or corporate
# primary records.

SOURCE_EXECUTION_PRIORITY = {
    SourceType.COURT: 1,
    SourceType.GOVERNMENT: 2,
    SourceType.REGULATORY: 3,
    SourceType.CORPORATE: 4,
    SourceType.ARCHIVED_WEB: 5,
    SourceType.PUBLIC_DATABASE: 6,
    SourceType.JOURNALISM: 7,
    SourceType.SOCIAL_MEDIA: 8,
    SourceType.FORUM: 9,
    SourceType.DARK_WEB: 10,
    SourceType.USER_SUBMITTED: 11,
    SourceType.UNKNOWN: 12,
}


def get_primary_source_rank(
    task: SearchTask,
) -> int:
    """
    Return the best source priority available to a task.
    """

    if not task.source_types:
        return SOURCE_EXECUTION_PRIORITY[
            SourceType.UNKNOWN
        ]

    return min(
        SOURCE_EXECUTION_PRIORITY.get(
            source,
            SOURCE_EXECUTION_PRIORITY[
                SourceType.UNKNOWN
            ],
        )
        for source in task.source_types
    )


def get_task_execution_class(
    task: SearchTask,
) -> str:
    """
    Classify a task for deterministic execution.

    ENTITY_RESOLUTION must precede broad investigative searches.
    COUNTER is retained but never allowed to bypass entity
    resolution.
    """

    category = (
        task.category or ""
    ).upper()

    if category == "IDENTITY":
        return "ENTITY_RESOLUTION"

    if category in {
        "CORPORATE",
        "LEGAL",
        "REGULATORY",
        "LOCATION",
    }:
        return "PRIMARY_RECORD"

    if category in {
        "DIGITAL_FOOTPRINT",
        "HISTORICAL",
    }:
        return "HISTORICAL_DIGITAL"

    if category in {
        "RELATIONSHIP",
        "NETWORK",
    }:
        return "RELATIONSHIP"

    if category == "FINANCIAL":
        return "FINANCIAL"

    if category == "ADVERSE_MEDIA":
        return "MEDIA"

    return "GENERAL"


EXECUTION_CLASS_PRIORITY = {
    "ENTITY_RESOLUTION": 1,
    "PRIMARY_RECORD": 2,
    "HISTORICAL_DIGITAL": 3,
    "RELATIONSHIP": 4,
    "FINANCIAL": 5,
    "MEDIA": 6,
    "GENERAL": 7,
}


def initialize_task_execution_state(
    task: SearchTask,
) -> None:
    """
    Add execution bookkeeping without performing a search.
    """

    task.metadata.setdefault(
        "search_status",
        "PENDING",
    )

    task.metadata.setdefault(
        "attempts",
        0,
    )

    task.metadata.setdefault(
        "retrieved_count",
        0,
    )

    task.metadata.setdefault(
        "search_performed",
        False,
    )

    task.metadata.setdefault(
        "fact_establishment",
        False,
    )

    task.metadata.setdefault(
        "result_ids",
        [],
    )

    task.metadata.setdefault(
        "error",
        None,
    )

    task.metadata[
        "execution_class"
    ] = get_task_execution_class(task)

    task.metadata[
        "primary_source_rank"
    ] = get_primary_source_rank(task)


def build_source_aware_execution_queue(
    plan: SearchPlan,
) -> SearchPlan:
    """
    Convert an optimized plan into a deterministic,
    source-aware execution queue.

    No network activity occurs here.
    """

    for task in plan.tasks:
        initialize_task_execution_state(task)

    # --------------------------------------------------------
    # Entity resolution is always first.
    # Within a class, primary sources outrank weaker sources.
    # Counter/supporting remain visible and are never discarded.
    # --------------------------------------------------------

    plan.tasks.sort(
        key=lambda task: (
            EXECUTION_CLASS_PRIORITY.get(
                task.metadata[
                    "execution_class"
                ],
                99,
            ),

            task.metadata[
                "primary_source_rank"
            ],

            0
            if task.metadata.get(
                "direction"
            ) == "COUNTER"
            else 1,

            task.category or "",

            task.query,
        )
    )

    for index, task in enumerate(
        plan.tasks,
        start=1,
    ):

        task.metadata[
            "execution_order"
        ] = index

        task.metadata[
            "queue_status"
        ] = "READY"

        task.metadata[
            "search_status"
        ] = "PENDING"

        task.metadata[
            "search_performed"
        ] = False

        task.metadata[
            "fact_establishment"
        ] = False

    plan.metadata[
        "queue_type"
    ] = "SOURCE_AWARE"

    plan.metadata[
        "queue_status"
    ] = "READY"

    plan.metadata[
        "search_performed"
    ] = False

    plan.metadata[
        "fact_establishment"
    ] = False

    return plan


def mark_task_search_started(
    task: SearchTask,
) -> None:
    """
    State transition used later by the actual search executor.
    """

    task.metadata[
        "search_status"
    ] = "RUNNING"

    task.metadata[
        "attempts"
    ] = int(
        task.metadata.get(
            "attempts",
            0,
        )
    ) + 1

    task.metadata[
        "search_performed"
    ] = True

    # Search itself is never proof.
    task.metadata[
        "fact_establishment"
    ] = False


def mark_task_search_completed(
    task: SearchTask,
    retrieved_count: int,
    result_ids: Optional[List[str]] = None,
) -> None:
    """
    Record search completion.

    Retrieved results remain unverified until converted into
    source/document/claim/evidence objects.
    """

    task.metadata[
        "search_status"
    ] = "COMPLETED"

    task.metadata[
        "retrieved_count"
    ] = max(
        0,
        int(retrieved_count),
    )

    task.metadata[
        "result_ids"
    ] = list(
        result_ids or []
    )

    task.metadata[
        "fact_establishment"
    ] = False


def mark_task_search_failed(
    task: SearchTask,
    error: str,
) -> None:

    task.metadata[
        "search_status"
    ] = "FAILED"

    task.metadata[
        "error"
    ] = str(error)

    task.metadata[
        "fact_establishment"
    ] = False


def validate_source_aware_queue(
    plan: SearchPlan,
) -> List[str]:

    errors: List[str] = []

    if plan.metadata.get(
        "queue_type"
    ) != "SOURCE_AWARE":
        errors.append(
            "Queue type is not SOURCE_AWARE."
        )

    if plan.metadata.get(
        "queue_status"
    ) != "READY":
        errors.append(
            "Queue status is not READY."
        )

    expected_orders = list(
        range(
            1,
            len(plan.tasks) + 1,
        )
    )

    actual_orders = [
        task.metadata.get(
            "execution_order"
        )
        for task in plan.tasks
    ]

    if actual_orders != expected_orders:
        errors.append(
            "Execution order is not contiguous."
        )

    for index, task in enumerate(
        plan.tasks,
        start=1,
    ):

        if task.metadata.get(
            "search_status"
        ) != "PENDING":
            errors.append(
                f"Task {index}: initial status is not PENDING."
            )

        if task.metadata.get(
            "search_performed"
        ) is not False:
            errors.append(
                f"Task {index}: search_performed must be FALSE."
            )

        if task.metadata.get(
            "fact_establishment"
        ) is not False:
            errors.append(
                f"Task {index}: fact_establishment must be FALSE."
            )

        if (
            task.metadata.get(
                "primary_source_rank"
            )
            is None
        ):
            errors.append(
                f"Task {index}: source rank missing."
            )

        if not task.metadata.get(
            "execution_class"
        ):
            errors.append(
                f"Task {index}: execution class missing."
            )

    return errors


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "SearchPlan",
    "generate_search_plan",
    "generate_search_plan_for_question",
    "validate_search_plan",
    "extract_targets_from_question",
]
