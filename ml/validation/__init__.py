"""
The four validation gates every change to ml/ passes before it can merge.

Specified in .github/workflows/model-validation.yml; each module is a
``python -m`` entry point with exactly the flags the workflow uses.

    python -m ml.validation.leakage     --fail-on-leak     Gate 1: point-in-time correctness
    python -m ml.validation.performance --min-pr-auc 0.15  Gate 2: performance floor, temporal split
    python -m ml.validation.drift       --max-psi 0.25     Gate 3: training vs recent traffic
    python -m ml.validation.fairness    --report fairness.md   Gate 4: per-slice report

Gate 1 runs first on purpose. Gates 2-4 measure a model; if a feature is
leaking, every number they produce is fiction. The test suite keeps the
notebook-01 definition of ``card_chargeback_rate`` as a negative fixture so
that Gate 1 is proven to fail on the exact mistake that reached shadow.

Each gate exposes ``main(argv) -> int`` and a pure entry point --
``run_probes`` for Gate 1, ``evaluate`` for Gates 2-4 -- so the tests and the
notebook call the same code the workflow does.
"""
