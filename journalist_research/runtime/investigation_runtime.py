
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now():
    return datetime.now(timezone.utc)


@dataclass
class RuntimeState:
    investigation_id: str
    question: str

    parsed_question: Any = None
    hypotheses: Any = None
    search_plan: Any = None

    sources: List[Any] = field(default_factory=list)
    documents: List[Any] = field(default_factory=list)
    claims: List[Any] = field(default_factory=list)
    entities: List[Any] = field(default_factory=list)
    relationships: List[Any] = field(default_factory=list)
    timeline: Any = None
    contradictions: List[Any] = field(default_factory=list)
    evidence_graph: Any = None
    confidence: List[Any] = field(default_factory=list)
    negative_findings: List[Any] = field(default_factory=list)
    source_matrix: Any = None
    contradiction_report: Any = None
    dossier: Any = None

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    non_existence_established: bool = False
    automatic_conclusion: bool = False
    human_review_required: bool = True

    status: str = "NOT_STARTED"
    errors: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def mark(self, stage):
        self.trace.append(stage)
        self.updated_at = utc_now()

    def fail(self, message):
        self.errors.append(message)
        self.status = "FAILED"
        self.updated_at = utc_now()

    def serialize(self):
        def convert(value):
            if hasattr(value, "to_dict"):
                return value.to_dict()

            if hasattr(value, "__dataclass_fields__"):
                return {
                    k: convert(v)
                    for k, v in asdict(value).items()
                }

            if isinstance(value, list):
                return [convert(v) for v in value]

            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}

            if isinstance(value, datetime):
                return value.isoformat()

            return value

        return convert(self)


class DOARuntime:

    def __init__(self, investigation_id, question):
        self.state = RuntimeState(
            investigation_id=investigation_id,
            question=question,
        )

    def parse_question(self):
        from journalist_research.question_engine.question_parser import (
            parse_question
        )

        self.state.parsed_question = parse_question(
            self.state.question
        )

        self.state.mark("QUESTION_PARSED")
        return self.state.parsed_question

    def build_hypotheses(self):
        from journalist_research.question_engine.hypothesis_builder import (
            build_hypotheses
        )

        self.state.hypotheses = build_hypotheses(
            self.state.parsed_question
        )

        self.state.mark("HYPOTHESES_BUILT")
        return self.state.hypotheses

    def build_search_plan(self):
        from journalist_research.question_engine.search_plan import (
            generate_search_plan_for_question
        )

        self.state.search_plan = generate_search_plan_for_question(
            self.state.question
        )

        self.state.mark("SEARCH_PLAN_BUILT")
        return self.state.search_plan

    def assert_no_automatic_conclusion(self):

        if self.state.fact_established:
            raise RuntimeError(
                "Runtime attempted automatic fact establishment"
            )

        if self.state.identity_established:
            raise RuntimeError(
                "Runtime attempted automatic identity establishment"
            )

        if self.state.guilt_established:
            raise RuntimeError(
                "Runtime attempted automatic guilt establishment"
            )

        if self.state.non_existence_established:
            raise RuntimeError(
                "Runtime attempted automatic non-existence establishment"
            )

        if self.state.automatic_conclusion:
            raise RuntimeError(
                "Runtime attempted automatic conclusion"
            )

        if not self.state.human_review_required:
            raise RuntimeError(
                "Human review requirement was removed"
            )

        return True

    def execute_question_layer(self):

        self.state.status = "RUNNING"

        try:
            self.parse_question()
            self.build_hypotheses()
            self.build_search_plan()

            self.assert_no_automatic_conclusion()

            self.state.status = "READY_FOR_EVIDENCE"
            self.state.mark("QUESTION_LAYER_COMPLETE")

            return self.state

        except Exception as exc:
            self.state.fail(
                f"{type(exc).__name__}: {exc}"
            )
            raise

    def to_json(self):
        return json.dumps(
            self.state.serialize(),
            ensure_ascii=False,
            indent=2,
        )
