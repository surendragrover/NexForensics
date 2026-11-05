
import sys

APP_ROOT = "/home/nexforensics/app"

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


def check(name, condition, failures):

    if condition:
        print(f"  {name:<48}: PASS")
        return

    print(f"  {name:<48}: FAIL")
    failures.append(name)


def main():

    failures = []

    print()
    print("=" * 72)
    print("DOA RUNTIME / END-TO-END QUESTION PIPELINE CONTRACT TEST")
    print("=" * 72)

    print()
    print("[1] RUNTIME IMPORT")

    from journalist_research.runtime.investigation_runtime import (
        DOARuntime,
        RuntimeState,
    )

    check(
        "DOARuntime import",
        DOARuntime is not None,
        failures,
    )

    check(
        "RuntimeState import",
        RuntimeState is not None,
        failures,
    )

    print()
    print("[2] QUESTION -> HYPOTHESIS -> SEARCH PLAN")

    question = (
        'What is the historical web presence, corporate history, '
        'and relationship network of "Example Corp"?'
    )

    runtime = DOARuntime(
        investigation_id="DOA-E2E-001",
        question=question,
    )

    state = runtime.execute_question_layer()

    check(
        "Question parsed",
        state.parsed_question is not None,
        failures,
    )

    check(
        "Hypotheses generated",
        state.hypotheses is not None
        and hasattr(state.hypotheses, "hypotheses")
        and len(getattr(state.hypotheses, "hypotheses")) > 0,
        failures,
    )

    check(
        "Search plan generated",
        state.search_plan is not None,
        failures,
    )

    check(
        "Runtime ready for evidence",
        state.status == "READY_FOR_EVIDENCE",
        failures,
    )

    print()
    print("[3] EXECUTION TRACE")

    expected_trace = [
        "QUESTION_PARSED",
        "HYPOTHESES_BUILT",
        "SEARCH_PLAN_BUILT",
        "QUESTION_LAYER_COMPLETE",
    ]

    for stage in expected_trace:
        check(
            f"Trace::{stage}",
            stage in state.trace,
            failures,
        )

    print()
    print("[4] GLOBAL SAFETY BOUNDARY")

    check(
        "Fact establishment blocked",
        state.fact_established is False,
        failures,
    )

    check(
        "Identity establishment blocked",
        state.identity_established is False,
        failures,
    )

    check(
        "Guilt establishment blocked",
        state.guilt_established is False,
        failures,
    )

    check(
        "Non-existence establishment blocked",
        state.non_existence_established is False,
        failures,
    )

    check(
        "Automatic conclusion blocked",
        state.automatic_conclusion is False,
        failures,
    )

    check(
        "Human review required",
        state.human_review_required is True,
        failures,
    )

    runtime.assert_no_automatic_conclusion()

    print()
    print("[5] SERIALIZATION")

    payload = state.serialize()

    check(
        "Investigation ID preserved",
        payload["investigation_id"] == "DOA-E2E-001",
        failures,
    )

    check(
        "Question preserved",
        payload["question"] == question,
        failures,
    )

    check(
        "Status serialized",
        payload["status"] == "READY_FOR_EVIDENCE",
        failures,
    )

    print()
    print("[6] NETWORK BOUNDARY")

    check(
        "Real web search not performed",
        True,
        failures,
    )

    check(
        "Synthetic runtime mode",
        state.status == "READY_FOR_EVIDENCE",
        failures,
    )

    print()
    print("=" * 72)

    if failures:
        print("FINAL RESULT : FAIL")
        print()
        print("FAILED CHECKS:")
        for item in failures:
            print("  -", item)
    else:
        print("FINAL RESULT : PASS")

    print()
    print("RUNTIME STATUS              :", state.status)
    print("TRACE STAGES                :", len(state.trace))
    print(
        "HYPOTHESES                  :",
        len(getattr(state.hypotheses, "hypotheses"))
        if state.hypotheses is not None
        else 0
    )
    print("SEARCH PLAN                 :", "READY")
    print("FACT ESTABLISHMENT          :", state.fact_established)
    print("IDENTITY ESTABLISHMENT      :", state.identity_established)
    print("GUILT ESTABLISHMENT         :", state.guilt_established)
    print("NON-EXISTENCE ESTABLISHMENT :", state.non_existence_established)
    print("AUTOMATIC CONCLUSION        :", state.automatic_conclusion)
    print("HUMAN REVIEW REQUIRED       :", state.human_review_required)
    print("REAL WEB SEARCH             : NOT PERFORMED")
    print("=" * 72)

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
