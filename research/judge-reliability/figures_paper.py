"""Two figures the paper adds over the technical report.

The dial figure is the argument in one image: the same six configurations acted
as writers and as judges, so the reasoning-effort dial was turned once on each
side of the grading relation. Both panels share one y-span so flatness on the
right is a measurement, not an axis trick.
"""

from __future__ import annotations

import itertools
import statistics as st

import matplotlib.pyplot as plt

from figures24 import CLAUDE, CODEX, FIG, INK, MUTED
from study24 import JUDGES, cells, icc, load, mat

EFFORTS = ["low", "medium", "high"]


def f_dial(rows) -> None:
    W = [r for r in rows if r["sheet"].startswith("writer-")]
    cm = cells(W)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.4, 2.2), gridspec_kw={"wspace": 0.3})
    for fam, col, disp in (("codex", CODEX, "5.6 Luna"), ("claude", CLAUDE, "Sonnet 5")):
        w = [st.fmean([r["p"] for r in W if r["sheet"] == f"writer-{fam}-{e}"]) for e in EFFORTS]
        j = [
            st.fmean([v for (q, s, jj), v in cm.items() if jj == f"{fam}-{e}"])
            for e in EFFORTS
        ]
        a1.plot(range(3), w, color=col, lw=1.6, marker="o", ms=3.6, label=disp)
        a2.plot(range(3), j, color=col, lw=1.6, marker="o", ms=3.6, label=disp)
        # codex labels above the point, claude below: the lines cross on the
        # left panel and hug each other on the right, so one-sided offsets collide
        dy = (0, 5) if fam == "codex" else (0, -11)
        for e, v in zip(EFFORTS, w):
            a1.annotate(f"{v:.3f}", (EFFORTS.index(e), v), textcoords="offset points",
                        xytext=dy, ha="center", fontsize=6.0, color=MUTED)
        # No numeric labels on the judge panel: four lines live there now and
        # the numbers are in the text.

    # Frontier judges, graded once: dashed lines on the judge panel only.
    import json
    from pathlib import Path as _P
    HERE = _P(__file__).resolve().parent
    FRONTIER = (("sol", "#123f4f", "5.6 Sol"), ("opus", "#6e3419", "Opus 5"))
    for fam, col, disp in FRONTIER:
        means = []
        for e in EFFORTS:
            vals = []
            for sheet in [f"writer-{f}-{ef}" for f in ("codex", "claude") for ef in EFFORTS]:
                f = HERE / "reports_frontier" / f"{sheet}--judge-{fam}-{e}.json"
                for qid, q in json.loads(f.read_text())["results"].items():
                    if q["mode"] == "judge":
                        vals.append(q["awarded"] / q["max_points"])
            means.append(sum(vals) / len(vals))
        a2.plot(range(3), means, color=col, lw=1.3, ls="--", marker="o", ms=3.0, label=disp)
    for ax, title in ((a1, "effort turned on the writer"), (a2, "same dial turned on the judge")):
        ax.set_xticks(range(3), EFFORTS)
        ax.set_ylim(0.75, 0.97)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
        ax.set_title(title, fontsize=8, loc="left")
    a1.set_ylabel("mean score received")
    a2.set_ylabel("mean score given")
    a1.legend(frameon=False, fontsize=7, loc="lower right")
    a2.legend(frameon=False, fontsize=6.2, loc="lower right", ncols=2)
    fig.savefig(FIG / "s24-dial.pdf")
    plt.close(fig)
    print("s24-dial")


def f_panel(rows) -> None:
    W = [r for r in rows if r["sheet"].startswith("writer-") and r["rep"] == 1]
    cm = cells(W)
    tg = sorted({(q, s) for (q, s, _) in cm})
    ks, means, worst, best = [], [], [], []
    for k in range(2, 7):
        vals = []
        for combo in itertools.combinations(JUDGES, k):
            m = [[cm.get((q, s, j)) for j in combo] for (q, s) in tg]
            m = [r for r in m if all(v is not None for v in r)]
            v = icc(m)
            if v == v:
                vals.append(v)
        ks.append(k)
        means.append(st.fmean(vals))
        worst.append(min(vals))
        best.append(max(vals))
    fig, ax = plt.subplots(figsize=(2.7, 2.2))
    ax.fill_between(ks, worst, best, color=CODEX, alpha=0.12, linewidth=0)
    ax.plot(ks, worst, color=CLAUDE, lw=1.3, label="worst panel")
    ax.plot(ks, means, color=INK, lw=1.6, marker="o", ms=3.2, label="mean over panels")
    ax.set_xlabel("judges on the panel")
    ax.set_ylabel("ICC(2,1), single pass")
    ax.set_xticks(ks)
    ax.set_ylim(0.8, 1.0)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=6.6, loc="lower right")
    fig.savefig(FIG / "s24-panel.pdf")
    plt.close(fig)
    print("s24-panel")
    print("  k:", ks, "mean:", [round(v, 3) for v in means], "worst:", [round(v, 3) for v in worst])


def table_numbers(rows) -> None:
    W = [r for r in rows if r["sheet"].startswith("writer-")]
    print("stratum answer-spread (SD of per-answer means):")
    for s in "ABCD":
        sub = [r for r in W if r["stratum"] == s]
        cm = cells(sub)
        tg = sorted({(q, sh) for (q, sh, _) in cm})
        m = [[cm.get((q, sh, j)) for j in JUDGES] for (q, sh) in tg]
        m = [r for r in m if all(v is not None for v in r)]
        print(f"  {s}: answer-SD={st.pstdev([st.fmean(r) for r in m]):.3f}")
    for fam in ("codex", "claude"):
        L = st.fmean([r["len"] for r in W if fam in r["sheet"]])
        print(f"mean answer length {fam}: {L:.0f} chars")


if __name__ == "__main__":
    rows, prov = load()
    f_dial(rows)
    f_panel(rows)
    table_numbers(rows)
