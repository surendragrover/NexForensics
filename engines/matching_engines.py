"""
engines/matching_engines.py — dataset & MO-fingerprint matching engines.

These are lead-generation tools only: they surface candidate matches
from existing datasets/case history for a human investigator to verify.
They never auto-confirm identity, auto-merge cases, or take any action
on their own.

Extracted from gradio_app.py (was ~230 lines inline at module top).
"""

from config import log, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
from mo_fingerprint_scoring_v54 import MOFingerprintScoringV54


class DatasetSearchEngine:
    def __init__(self):
        self.ready = False
        try:
            import mysql.connector
            self._driver = mysql.connector
            # quick connectivity check at startup so STATUS reflects reality
            conn = self._connect()
            conn.close()
            self.ready = True
            log.info("Dataset Search (MySQL master_search_index) ✓")
        except Exception as e:
            log.warning(f"Dataset Search not available: {e}")

    def _connect(self):
        return self._driver.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME, connection_timeout=5,
        )

    def search(self, query_text, limit=15):
        """FULLTEXT search across every synced dataset. Returns a list of
        {entity_name, entity_type, dataset, source_table, data, relevance}
        dicts, highest-relevance first. Falls back to a LIKE search for
        short/stopword-only queries where MySQL's FULLTEXT natural-language
        mode returns nothing (it ignores very short or overly common terms)."""
        if not self.ready or not query_text or not query_text.strip():
            return []
        q = query_text.strip()[:200]
        try:
            conn = self._connect()
            cur = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT entity_name, entity_type, dataset, source_table, data,
                       MATCH(entity_name, data) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance
                FROM master_search_index
                WHERE MATCH(entity_name, data) AGAINST (%s IN NATURAL LANGUAGE MODE)
                ORDER BY relevance DESC
                LIMIT %s
            """, (q, q, limit))
            rows = cur.fetchall()
            if not rows:
                # FULLTEXT natural-language mode silently skips short/common
                # words — retry with a plain LIKE so short names still hit.
                like_q = f"%{q}%"
                cur.execute("""
                    SELECT entity_name, entity_type, dataset, source_table, data, 0 AS relevance
                    FROM master_search_index
                    WHERE entity_name LIKE %s OR data LIKE %s
                    LIMIT %s
                """, (like_q, like_q, limit))
                rows = cur.fetchall()
            cur.close()
            conn.close()
            return rows
        except Exception as e:
            log.error(f"Dataset search error: {e}")
            return []

    def summarize(self, rows):
        """Groups raw search rows into a compact structure for the report:
        counts per dataset + a short list of top hits for display."""
        if not rows:
            return {"count": 0, "datasets": {}, "top": []}
        datasets = {}
        for r in rows:
            ds = r.get("dataset") or "unknown"
            datasets[ds] = datasets.get(ds, 0) + 1
        top = [{
            "name": (r.get("entity_name") or "")[:120],
            "type": r.get("entity_type") or "",
            "dataset": r.get("dataset") or "",
            "detail": (r.get("data") or "")[:220],
        } for r in rows[:8]]
        return {"count": len(rows), "datasets": datasets, "top": top}



# ============================================================
# MO FINGERPRINTING — matches this case's Modus Operandi
# (crime signature) against `crime_scenes` for other cases with a
# similar signature, and surfaces any already-confirmed connections
# from `case_links`. Purely a lead-generation tool for the
# investigator — it NEVER auto-merges cases, only flags candidates
# for human verification.
#
# Assumed schema (adjust column names here if the real tables differ):
#   crime_scenes(case_id, mo_description, location, crime_type, occurred_at)
#   case_links(case_id, linked_case_id, link_type, confidence, notes)
# ============================================================
class MOFingerprintEngine:
    def __init__(self):
        self.ready = False
        # Concept-based MO fingerprint scorer (entry method / weapons /
        # planning / escape) — runs locally, no DB needed, so it's always
        # available even when `self.ready` (DB connectivity) is False.
        self.scorer = MOFingerprintScoringV54(diagnostic=False)
        try:
            import mysql.connector
            self._driver = mysql.connector
            conn = self._connect()
            conn.close()
            self.ready = True
            log.info("MO Fingerprinting (crime_scenes/case_links) ✓")
        except Exception as e:
            log.warning(f"MO Fingerprinting not available: {e}")

    def _connect(self):
        return self._driver.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME, connection_timeout=5,
        )

    def find_linked_cases(self, case_id, modus, location, crime_category=None, limit=10):
        result = {
            "query_used": (modus or "")[:200],
            "linked_cases": [], "confirmed_links": [], "note": "",
        }
        if not self.ready:
            result["note"] = "MO Fingerprinting unavailable (DB not reachable)."
            return result
        if not (modus or "").strip():
            result["note"] = "No Modus Operandi text provided — nothing to fingerprint."
            return result

        try:
            conn = self._connect()
            cur = conn.cursor(dictionary=True)
            cat = (crime_category or "").strip()
            rows = []

            # 1a. Prefer matches within the SAME crime category first —
            # this is what was missing before: crime_category was accepted
            # as a parameter but never actually used in the query, so a
            # Cybercrime case could match against an unrelated Robbery case
            # just because a few words overlapped.
            if cat:
                cur.execute("""
                    SELECT case_id, mo_description, location, crime_type, occurred_at,
                           entry_method, behaviour_at_scene, planning_level, team_size,
                           escape_method, mo_signature, profile_confidence,
                           MATCH(mo_description) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance
                    FROM crime_scenes
                    WHERE MATCH(mo_description) AGAINST (%s IN NATURAL LANGUAGE MODE)
                      AND (%s = '' OR case_id != %s)
                      AND LOWER(crime_type) LIKE %s
                    ORDER BY relevance DESC
                    LIMIT %s
                """, (modus, modus, case_id or "", case_id or "", f"%{cat.lower()}%", limit))
                rows = cur.fetchall()
                for r in rows:
                    r["category_match"] = True

            # 1b. Only if no same-category match exists, fall back to a
            # category-agnostic search — but flag every such result as
            # cross-category so it's shown as a weaker, caveated lead
            # rather than an equally-confident match.
            if not rows:
                cur.execute("""
                    SELECT case_id, mo_description, location, crime_type, occurred_at,
                           entry_method, behaviour_at_scene, planning_level, team_size,
                           escape_method, mo_signature, profile_confidence,
                           MATCH(mo_description) AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance
                    FROM crime_scenes
                    WHERE MATCH(mo_description) AGAINST (%s IN NATURAL LANGUAGE MODE)
                      AND (%s = '' OR case_id != %s)
                    ORDER BY relevance DESC
                    LIMIT %s
                """, (modus, modus, case_id or "", case_id or "", limit))
                rows = cur.fetchall()
                for r in rows:
                    r["category_match"] = False

            if not rows:
                # FULLTEXT can silently skip short/common phrases — LIKE fallback
                like_q = f"%{modus.strip()[:80]}%"
                cur.execute("""
                    SELECT case_id, mo_description, location, crime_type, occurred_at,
                           entry_method, behaviour_at_scene, planning_level, team_size,
                           escape_method, mo_signature, profile_confidence,
                           0 AS relevance
                    FROM crime_scenes
                    WHERE mo_description LIKE %s
                      AND (%s = '' OR case_id != %s)
                    LIMIT %s
                """, (like_q, case_id or "", case_id or "", limit))
                rows = cur.fetchall()
                for r in rows:
                    r["category_match"] = False

            # Concept-based MO fingerprint score — re-scores every SQL
            # candidate with MOFingerprintScoringV54 (entry method / weapons
            # / planning / escape dimensions) instead of relying only on
            # MySQL's FULLTEXT relevance, then re-ranks by that score so the
            # strongest MO-signature match surfaces first.
            for r in rows:
                fp = self.scorer.score_mo(modus, r.get("mo_description") or "")
                r["fingerprint_score"] = fp.get("total_score", 0)
                r["fingerprint_match_level"] = fp.get("match_level", "LOW")
            rows.sort(key=lambda r: r.get("fingerprint_score", 0), reverse=True)

            # p23 (2026-11-07): a candidate is a usable link only if its MO
            # fingerprint score reaches the threshold AND it is the same crime
            # category (analysis/report_rules.json -> mo_links). Others are kept
            # in `suppressed_links` for transparency but never reach hypotheses,
            # Strongest Lead or the summary.
            try:
                from analysis.report_rules import filter_mo_links, mo_none_text
                rows, suppressed = filter_mo_links(rows)
            except Exception as _fe:
                log.warning(f"MO link filter unavailable: {_fe}")
                suppressed = []
                mo_none_text = lambda: "No MO link found."
            result["linked_cases"] = rows
            result["suppressed_links"] = suppressed

            # 2. Any links already confirmed by a human for this case
            if (case_id or "").strip():
                cur.execute("""
                    SELECT case_id, linked_case_id, link_type, confidence, notes
                    FROM case_links
                    WHERE case_id = %s OR linked_case_id = %s
                """, (case_id, case_id))
                result["confirmed_links"] = cur.fetchall()

            cur.close()
            conn.close()

            if not rows and suppressed:
                result["note"] = (mo_none_text() + f" {len(suppressed)} lower-scoring or different-category "
                                  "candidate(s) were suppressed and are not used as leads.")
            elif rows:
                any_cross_category = any(not r.get("category_match", True) for r in rows)
                result["note"] = (
                    f"{len(rows)} case(s) share a similar MO signature — "
                    "these are POSSIBLE links only, verify independently before connecting cases."
                    + (" ⚠ No matches within the same crime category were found — the case(s) "
                       "below are from a DIFFERENT category and the match is text-similarity only."
                       if any_cross_category else "")
                )
            elif not result["confirmed_links"]:
                result["note"] = "No similar MO signature found, and no confirmed links on record."
        except Exception as e:
            log.error(f"MO Fingerprinting query error: {e}")
            result["note"] = f"MO Fingerprinting query failed: {e}"
        return result
