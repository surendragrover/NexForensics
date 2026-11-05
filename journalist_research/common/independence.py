"""
One independence rule for DOA.

Independence is counted by LINEAGE, not by URL or domain.  Wire copies,
syndicated reprints, archive captures and pages derived from one origin
collapse to one lineage.  A single source is 1 lineage (never 0).
NOT_EVIDENCE sources contribute no lineage.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from .status import SourceTier, ADEQUATE, tier_of


def _get(src: Any, key: str, default=None):
    if isinstance(src, dict):
        return src.get(key, default)
    return getattr(src, key, default)


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    host = re.sub(r"^www\.", "", host)
    return host


def lineage_key(src: Any) -> str:
    """Explicit lineage beats derived_from beats wire id beats origin domain."""
    for key in ("lineage_id", "derived_from", "wire_id", "origin_id"):
        val = _get(src, key)
        if val:
            return f"{key}:{val}"
    archive_of = _get(src, "archive_of")
    if archive_of:
        return f"domain:{_domain(archive_of)}"
    publisher = (_get(src, "publisher") or "").strip().lower()
    if publisher:
        return f"publisher:{publisher}"
    return f"domain:{_domain(_get(src, 'url', ''))}"


def lineages(sources: Iterable[Any]) -> Dict[str, List[Any]]:
    groups: Dict[str, List[Any]] = {}
    for s in sources:
        if tier_of(_get(s, "tier")) == SourceTier.NOT_EVIDENCE:
            continue
        groups.setdefault(lineage_key(s), []).append(s)
    return groups


def independent_count(sources: Iterable[Any]) -> int:
    return len(lineages(sources))


def adequate_count(sources: Iterable[Any]) -> int:
    """Lineages whose best member is of adequate quality (PRIMARY/HIGH/MEDIUM)."""
    n = 0
    for members in lineages(sources).values():
        if any(tier_of(_get(m, "tier")) in ADEQUATE for m in members):
            n += 1
    return n


def best_tier(sources: Iterable[Any]):
    order = [SourceTier.PRIMARY_OFFICIAL, SourceTier.HIGH, SourceTier.MEDIUM,
             SourceTier.LOW, SourceTier.SELF_REPORTED]
    tiers = {tier_of(_get(s, "tier")) for s in sources}
    for t in order:
        if t in tiers:
            return t
    return None
