"""
Seed ml/notebooks/03_v3_shadow_investigation.ipynb: the notebook the data
scientist opens when the shadow report lands. Load cells and questions only --
the analysis is what Claude adds live. Cells carry stable ids so NotebookEdit
can address them.

Numbers in the prose come from the generated report, so the notebook cannot
disagree with the console. Deterministic; called by demo/reset-demo.sh.
"""

from __future__ import annotations

import json
import pathlib

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "ml" / "registry" / "shadow" / "fraud-v3-candidate.json"
OUT = REPO / "ml" / "notebooks" / "03_v3_shadow_investigation.ipynb"


def main() -> None:
    r = json.loads(REPORT.read_text())
    stats = r["feature_stats"]["card_chargeback_rate"]
    cells = [
        new_markdown_cell(id="title", source=(
            f"# {r['model']} — shadow run investigation\n\n"
            f"The model platform blocked the promotion ({r['ticket']}).\n\n"
            f"| | AUC | PR-AUC |\n|---|---|---|\n"
            f"| candidate, offline (notebook 01) | **{r['offline']['auc']:.3f}** | {r['offline']['pr_auc']:.3f} |\n"
            f"| candidate, shadow ({r['window']['start']} → {r['window']['end']}) | **{r['shadow']['auc']:.3f}** | {r['shadow']['pr_auc']:.3f} |\n"
            f"| champion {r['champion']}, same window | {r['champion_same_window']['auc']:.3f} | {r['champion_same_window']['pr_auc']:.3f} |\n\n"
            f"Offline it beat the champion by a wide margin. In shadow it is *worse* than the champion. Why?")),
        new_code_cell(id="imports", source=(
            "import json\nfrom pathlib import Path\n\nimport numpy as np\nimport pandas as pd\n"
            "from sklearn.ensemble import HistGradientBoostingClassifier\n"
            "from sklearn.metrics import average_precision_score, roc_auc_score\n\n"
            "ROOT = Path.cwd().resolve()\nwhile not (ROOT / \"pyproject.toml\").exists():\n    ROOT = ROOT.parent\nprint(ROOT)")),
        new_code_cell(id="load-report", source=(
            "report = json.loads((ROOT / \"ml/registry/shadow/fraud-v3-candidate.json\").read_text())\n"
            "pd.DataFrame({\n"
            "    \"offline\": report[\"offline\"],\n"
            "    \"shadow\": {k: v for k, v in report[\"shadow\"].items() if k != \"by_month\"},\n"
            "    \"champion\": report[\"champion_same_window\"],\n"
            "}).T")),
        new_code_cell(id="load-data", source=(
            "df = pd.read_parquet(ROOT / \"ml/data/transactions.parquet\").sort_values(\"timestamp\").reset_index(drop=True)\n"
            "cut = df.timestamp.quantile(0.70)          # same temporal split as notebook 01\n"
            "train, test = df[df.timestamp <= cut].copy(), df[df.timestamp > cut].copy()\n"
            "print(f\"train={len(train):,}  test={len(test):,}  test window {test.timestamp.min().date()} → {test.timestamp.max().date()}\")\n"
            "print(\"the shadow window is the test window\")")),
        new_markdown_cell(id="questions", source=(
            "## Questions\n\n"
            "1. Can the offline number be reproduced from notebook 01's feature set?\n"
            f"2. The report says `card_chargeback_rate` is non-zero for {stats['training_nonzero_share']:.1%} of training rows "
            f"but {stats['shadow_nonzero_share']:.1%} of scored rows. Does the feature look the same at training time as at scoring time?\n"
            "3. What does the candidate score without it?")),
    ]
    nb = new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    })
    nbformat.write(nb, OUT)
    print(f"wrote {OUT.relative_to(REPO)} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
