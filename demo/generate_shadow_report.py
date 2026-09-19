"""
Generate the shadow-deployment report for fraud-v3-candidate.

The candidate was trained offline with `card_chargeback_rate` computed over
the whole history (notebook 01). In shadow, the serving path can only see
chargebacks filed *so far*, so the same model meets a feature that looks
different from the one it learned on. This script scores exactly that: the
offline-trained model, on the shadow window, with the feature as it exists at
scoring time. It writes what a data scientist would receive from the model
platform -- numbers, no diagnosis. The word "leak" appears nowhere on purpose.

Deterministic. Called by demo/reset-demo.sh and demo/build_history.sh.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from demo.verify_leakage import (  # noqa: E402
    BASE_COLUMNS, REPO, base_features, fit, leaky_rate, load, pit_rate, score, split,
)

REGISTRY = REPO / "ml" / "registry"
CANDIDATE, CHAMPION = "fraud-v3-candidate", "fraud-v2"


def main() -> None:
    df = load()
    train, test = split(df)
    Xtr, Xte = base_features(df, train), base_features(df, test)

    champion = fit(Xtr, train.is_fraud)
    champ_auc, champ_ap = score(champion, Xte, test.is_fraud)

    rate = leaky_rate(df)
    Xtr_off = Xtr.assign(card_chargeback_rate=train.card_token.map(rate).to_numpy())
    Xte_off = Xte.assign(card_chargeback_rate=test.card_token.map(rate).to_numpy())
    candidate = fit(Xtr_off, train.is_fraud)
    off_auc, off_ap = score(candidate, Xte_off, test.is_fraud)

    # Shadow: the offline-trained candidate meets the feature as served.
    served = pit_rate(df, test)
    Xte_shadow = Xte.assign(card_chargeback_rate=served)
    sh_auc, sh_ap = score(candidate, Xte_shadow, test.is_fraud)

    months = test.timestamp.dt.strftime("%Y-%m").to_numpy()
    p = candidate.predict_proba(Xte_shadow)[:, 1]
    from sklearn.metrics import roc_auc_score
    by_month = [{"month": m, "n": int((months == m).sum()),
                 "auc": round(float(roc_auc_score(test.is_fraud[months == m], p[months == m])), 3)}
                for m in sorted(set(months)) if (months == m).sum() > 500]

    report = {
        "model": CANDIDATE,
        "champion": CHAMPION,
        "generated_at": "2026-09-16T08:40:00Z",
        "window": {
            "start": str(test.timestamp.min().date()), "end": str(test.timestamp.max().date()),
            "scored_transactions": int(len(test)),
            "labels": "confirmed fraud as of 2026-09-15; roughly 85% of fraud is eventually disputed",
        },
        "offline": {"auc": round(off_auc, 4), "pr_auc": round(off_ap, 4),
                    "source": "ml/notebooks/01_fraud_exploration.ipynb, cell 6"},
        "shadow": {"auc": round(sh_auc, 4), "pr_auc": round(sh_ap, 4), "by_month": by_month},
        "champion_same_window": {"auc": round(champ_auc, 4), "pr_auc": round(champ_ap, 4)},
        "features": BASE_COLUMNS + ["card_chargeback_rate"],
        "feature_serving": {
            "card_chargeback_rate": {
                "source": "card_history nightly batch",
                "computed_from": "chargebacks filed as of scoring time, per card",
            }
        },
        "feature_stats": {
            "card_chargeback_rate": {
                "training_nonzero_share": round(float((Xtr_off.card_chargeback_rate > 0).mean()), 4),
                "shadow_nonzero_share": round(float((served > 0).mean()), 4),
            }
        },
        "status": "blocked",
        "reason": "shadow underperforms the champion on the same window",
        "ticket": "TESS-2310",
    }
    (REGISTRY / "shadow").mkdir(parents=True, exist_ok=True)
    (REGISTRY / "shadow" / f"{CANDIDATE}.json").write_text(json.dumps(report, indent=2) + "\n")

    models = {"models": [
        {"name": CHAMPION, "role": "champion", "status": "production", "deployed": "2026-02-12",
         "auc_holdout": round(champ_auc, 3), "pr_auc_holdout": round(champ_ap, 3), "features": len(BASE_COLUMNS),
         "owner": "ml-fraud"},
        {"name": CANDIDATE, "role": "candidate", "status": "shadow", "registered": "2026-09-16",
         "auc_holdout": round(off_auc, 3), "pr_auc_holdout": round(off_ap, 3), "features": len(BASE_COLUMNS) + 1,
         "shadow_report": f"ml/registry/shadow/{CANDIDATE}.json",
         "notebook": "ml/notebooks/01_fraud_exploration.ipynb",
         "investigation_notebook": "ml/notebooks/03_v3_shadow_investigation.ipynb",
         "owner": "ml-fraud", "ticket": "TESS-2310"},
    ]}
    (REGISTRY / "models.json").write_text(json.dumps(models, indent=2) + "\n")

    print(f"champion (same window)   AUC={champ_auc:.4f}  PR-AUC={champ_ap:.4f}")
    print(f"candidate offline        AUC={off_auc:.4f}  PR-AUC={off_ap:.4f}")
    print(f"candidate shadow         AUC={sh_auc:.4f}  PR-AUC={sh_ap:.4f}   by month: {by_month}")
    stats = report["feature_stats"]["card_chargeback_rate"]
    print(f"feature non-zero share   train={stats['training_nonzero_share']:.1%}  shadow={stats['shadow_nonzero_share']:.1%}")
    print(f"wrote {REGISTRY.relative_to(REPO)}/models.json and shadow/{CANDIDATE}.json")


if __name__ == "__main__":
    main()
