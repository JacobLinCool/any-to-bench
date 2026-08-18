"""The ablation figure: per-question writer spread across the guidance spectrum.

Twelve lines, one per question, over {full rubric, answer key only, nothing}.
The five high-discrimination questions are drawn in color; the prose essays sit
flat at the bottom in every condition, which is the point.
"""

from __future__ import annotations

import statistics as st

import matplotlib.pyplot as plt
from analyse_ablate import KEEP, load, spread
from figures24 import CLAUDE, CODEX, FIG, INK, MUTED, RULE

CONDS = [
    ("full rubric", "reports24", "--r1"),
    ("answer key only", "reports_ab", ""),
    ("nothing", "reports_bare", ""),
]
SHORT = {
    "ast-113-civics--q36.b": "civics 36",
    "ast-115-civics--q35": "civics 35",
    "ast-113-geography--q37": "geog. 37",
    "ast-115-geography--q23.c": "geog. 23 (drawing)",
    "gsat-115-math-a--q20": "math 20",
}


def main() -> None:
    cells = [load(d, s) for _, d, s in CONDS]
    fig, ax = plt.subplots(figsize=(5.4, 2.6))
    for qid in KEEP:
        ys = [spread(c, qid) for c in cells]
        hi = qid in SHORT
        color = (CODEX if "civics" in qid or "math" in qid else CLAUDE) if hi else RULE
        ax.plot(
            range(3),
            ys,
            color=color,
            lw=1.5 if hi else 1.0,
            marker="o",
            ms=3.2 if hi else 2.2,
            zorder=3 if hi else 2,
        )
        if hi:
            ax.annotate(
                SHORT[qid],
                (2, ys[2]),
                textcoords="offset points",
                xytext=(6, -2 if qid != "ast-113-civics--q36.b" else 4),
                fontsize=6.2,
                color=INK,
            )
    ax.text(2.02, 0.005, "essays", fontsize=6.2, color=MUTED, transform=ax.transData)
    ax.set_xticks(range(3), [c for c, _, _ in CONDS])
    ax.set_xlim(-0.15, 2.75)
    ax.set_ylabel("spread between the six writers")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    fig.savefig(FIG / "s24-ablate.pdf")
    plt.close(fig)
    print("s24-ablate.pdf")
    hi = [q for q in KEEP if spread(cells[0], q) >= 0.10]
    for i, (lbl, _, _) in enumerate(CONDS[1:], 1):
        med = st.median(spread(cells[i], q) / spread(cells[0], q) for q in hi)
        print(f"  median retention {lbl}: {med:.0%}")


if __name__ == "__main__":
    main()
