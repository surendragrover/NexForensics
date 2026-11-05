
"""
DOA Phase 5 - Document Intelligence + Claim Extraction Integration

Connects canonical DocumentRecord objects to the existing
claim_extractor module.

Preserves:
- claim text
- claim classification
- source ID
- document ID
- extraction provenance
- uncertainty and negation
- safety invariants

A claim is never automatically treated as truth.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from journalist_research.evidence import claim_extractor


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def stable_claim_id(
    document_id: str,
    text: str,
    index: int,
) -> str:
    raw = (
        str(document_id)
        + "|"
        + str(index)
        + "|"
        + str(text)
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return "DCL_" + digest


@dataclass
class DocumentClaimLink:

    claim_id: str
    text: str

    source_id: str
    document_id: str

    classification: str = "UNCERTAIN"

    extraction_confidence: Optional[float] = None

    original_claim_id: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # Absolute safety boundaries.
    fact_established: bool = False
    truth_verified: bool = False
    human_verified: bool = False
    identity_established: bool = False
    guilt_established: bool = False


@dataclass
class DocumentIntelligenceResult:

    document_id: str
    source_id: str

    claims: List[DocumentClaimLink] = field(
        default_factory=list
    )

    extraction_status: str = "NOT_ASSESSED"

    processed_at: str = field(
        default_factory=utc_now
    )

    errors: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    fact_established: bool = False
    identity_established: bool = False
    guilt_established: bool = False
    automatic_conclusion: bool = False
    human_review_required: bool = True


class DocumentIntelligence:

    def __init__(self):
        self.extractor = claim_extractor

        self.extract_function = (
            getattr(
                self.extractor,
                "extract_document_claims",
                None,
            )
            or getattr(
                self.extractor,
                "extract_claims",
                None,
            )
        )

        if self.extract_function is None:
            raise RuntimeError(
                "No supported claim extraction function found"
            )

    @staticmethod
    def _classification(value):

        if value is None:
            return "UNCERTAIN"

        if hasattr(value, "value"):
            value = value.value

        if hasattr(value, "name"):
            value = value.name

        value = str(value).upper().strip()

        allowed = {
            "ASSERTION",
            "ALLEGATION",
            "UNCERTAIN",
            "NEGATED",
            "OBSERVATION",
        }

        if value in allowed:
            return value

        return "UNCERTAIN"

    @staticmethod
    def _claim_text(item):

        if isinstance(item, str):
            return item.strip()

        for field_name in (
            "text",
            "claim_text",
            "statement",
            "sentence",
            "content",
        ):
            value = getattr(
                item,
                field_name,
                None,
            )

            if isinstance(value, str) and value.strip():
                return value.strip()

        if isinstance(item, dict):
            for field_name in (
                "text",
                "claim_text",
                "statement",
                "sentence",
                "content",
            ):
                value = item.get(field_name)

                if isinstance(value, str) and value.strip():
                    return value.strip()

        return ""

    @staticmethod
    def _get(item, *names):

        if isinstance(item, dict):
            for name in names:
                if name in item:
                    return item[name]

        for name in names:
            value = getattr(item, name, None)

            if value is not None:
                return value

        return None

    @staticmethod
    def _invoke_extractor(
        function,
        document,
        source,
    ):

        signature = inspect.signature(function)

        kwargs = {}

        content = getattr(
            document,
            "content",
            "",
        )

        document_id = getattr(
            document,
            "document_id",
            "",
        )

        source_id = getattr(
            source,
            "source_id",
            "",
        )

        document_map = {
            "document": document,
            "document_record": document,
            "doc": document,
            "record": document,
        }

        source_map = {
            "source": source,
            "source_record": source,
        }

        content_names = {
            "text",
            "content",
            "body",
            "document_text",
            "raw_text",
            "document_content",
        }

        source_id_names = {
            "source_id",
            "sourceid",
        }

        document_id_names = {
            "document_id",
            "documentid",
            "doc_id",
        }

        required_unknown = []

        for name, parameter in signature.parameters.items():

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            if name in document_map:
                kwargs[name] = document_map[name]

            elif name in source_map:
                kwargs[name] = source_map[name]

            elif name.lower() in content_names:
                kwargs[name] = content

            elif name.lower() in source_id_names:
                kwargs[name] = source_id

            elif name.lower() in document_id_names:
                kwargs[name] = document_id

            elif parameter.default is inspect.Parameter.empty:
                required_unknown.append(name)

        if required_unknown:
            # A single unknown required parameter is accepted
            # as document content only when no other argument
            # has already been mapped.
            if (
                len(required_unknown) == 1
                and len(kwargs) == 0
            ):
                kwargs[required_unknown[0]] = content
            else:
                raise TypeError(
                    "Unsupported extractor parameters: "
                    + ", ".join(required_unknown)
                )

        signature.bind(**kwargs)

        return function(**kwargs)

    @staticmethod
    def _normalize_output(output):

        if output is None:
            return []

        if isinstance(output, dict):
            for key in (
                "claims",
                "extracted_claims",
                "results",
            ):
                if key in output:
                    output = output[key]
                    break

        elif not isinstance(output, (list, tuple)):
            claims = getattr(
                output,
                "claims",
                None,
            )

            if claims is not None:
                output = claims
            else:
                output = [output]

        if isinstance(output, tuple):
            output = list(output)

        if not isinstance(output, list):
            raise TypeError(
                "Extractor output is not a claim collection"
            )

        return output

    def process(
        self,
        document,
        source,
    ) -> DocumentIntelligenceResult:

        document_id = getattr(
            document,
            "document_id",
            None,
        )

        source_id = getattr(
            source,
            "source_id",
            None,
        )

        content = getattr(
            document,
            "content",
            None,
        )

        if not document_id:
            raise ValueError("Document ID is required")

        if not source_id:
            raise ValueError("Source ID is required")

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Document content is empty")

        if getattr(document, "fact_establishment", False):
            raise ValueError(
                "Document violates fact-establishment boundary"
            )

        result = DocumentIntelligenceResult(
            document_id=document_id,
            source_id=source_id,
        )

        try:

            raw_output = self._invoke_extractor(
                self.extract_function,
                document,
                source,
            )

            extracted = self._normalize_output(
                raw_output
            )

            for index, item in enumerate(
                extracted,
                start=1,
            ):

                text = self._claim_text(item)

                if not text:
                    continue

                original_id = self._get(
                    item,
                    "claim_id",
                    "id",
                )

                classification = self._classification(
                    self._get(
                        item,
                        "classification",
                        "claim_type",
                        "category",
                        "status",
                    )
                )

                confidence = self._get(
                    item,
                    "confidence",
                    "extraction_confidence",
                )

                if confidence is not None:
                    try:
                        confidence = float(confidence)
                    except (TypeError, ValueError):
                        confidence = None

                    if (
                        confidence is not None
                        and not 0.0 <= confidence <= 1.0
                    ):
                        confidence = None

                link = DocumentClaimLink(
                    claim_id=stable_claim_id(
                        document_id,
                        text,
                        index,
                    ),
                    text=text,
                    source_id=source_id,
                    document_id=document_id,
                    classification=classification,
                    extraction_confidence=confidence,
                    original_claim_id=(
                        str(original_id)
                        if original_id is not None
                        else None
                    ),
                    metadata={
                        "extractor": self.extract_function.__name__,
                        "extraction_index": index,
                        "original_metadata": (
                            self._get(item, "metadata") or {}
                        ),
                    },
                )

                result.claims.append(link)

            result.extraction_status = (
                "EXTRACTED"
                if result.claims
                else "NO_CLAIMS_EXTRACTED"
            )

            result.metadata = {
                "extractor": self.extract_function.__name__,
                "input_characters": len(content),
                "claims_extracted": len(result.claims),
                "fact_establishment": False,
                "truth_verification": False,
            }

        except Exception as exc:

            result.extraction_status = "EXTRACTION_ERROR"

            result.errors.append(
                type(exc).__name__
                + ": "
                + str(exc)[:500]
            )

        return result

    @staticmethod
    def validate_result(result):

        errors = []

        if not result.document_id:
            errors.append("Missing document ID")

        if not result.source_id:
            errors.append("Missing source ID")

        if result.fact_established:
            errors.append("Fact establishment violation")

        if result.identity_established:
            errors.append("Identity establishment violation")

        if result.guilt_established:
            errors.append("Guilt establishment violation")

        if result.automatic_conclusion:
            errors.append("Automatic conclusion violation")

        if not result.human_review_required:
            errors.append("Human review requirement missing")

        seen = set()

        for claim in result.claims:

            if not claim.text.strip():
                errors.append("Empty claim text")

            if claim.source_id != result.source_id:
                errors.append("Claim source linkage mismatch")

            if claim.document_id != result.document_id:
                errors.append("Claim document linkage mismatch")

            if claim.fact_established:
                errors.append("Claim fact boundary violation")

            if claim.truth_verified:
                errors.append("Claim truth boundary violation")

            if claim.human_verified:
                errors.append("Claim human-review boundary violation")

            if claim.identity_established:
                errors.append("Claim identity boundary violation")

            if claim.guilt_established:
                errors.append("Claim guilt boundary violation")

            if claim.claim_id in seen:
                errors.append("Duplicate claim ID")

            seen.add(claim.claim_id)

        return errors

    @staticmethod
    def serialize(result):

        return {
            "document_id": result.document_id,
            "source_id": result.source_id,
            "extraction_status": result.extraction_status,
            "processed_at": result.processed_at,
            "claims": [
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "classification": claim.classification,
                    "source_id": claim.source_id,
                    "document_id": claim.document_id,
                    "extraction_confidence": (
                        claim.extraction_confidence
                    ),
                    "original_claim_id": (
                        claim.original_claim_id
                    ),
                    "metadata": claim.metadata,
                    "fact_established": False,
                    "truth_verified": False,
                    "human_verified": False,
                    "identity_established": False,
                    "guilt_established": False,
                }
                for claim in result.claims
            ],
            "errors": result.errors,
            "metadata": result.metadata,
            "fact_established": False,
            "identity_established": False,
            "guilt_established": False,
            "automatic_conclusion": False,
            "human_review_required": True,
        }
