"""The asymmetry cut: the same six configurations acted as writers and as judges.

If intelligence matters for answering but not for grading, the effort dial must
move scores when turned on the writer side and leave verdicts alone when turned
on the judge side. Both directions come out of the same 3,456 verdicts.
"""

from __future__ import annotations

import itertools
import json
import statistics as st
from collections import defaultdict

from study24 import JUDGES, SHEETS, cells, icc, load, mat, spearman, within_sd

EFFORT = {"low": 0, "medium": 1, "high": 2}


def main() -> None:
    rows, prov = load()
    W = [r for r in rows if r["sheet"].startswith("writer-")]
    cm = cells(W)
    targets = sorted({(q, s) for (q, s, _) in cm})

    # ---- 1. writer side: does effort move the score? ----------------------
    print("=== 1. effort dial, writer side ===")
    for fam in ("codex", "claude"):
        means = {}
        for eff in ("low", "medium", "high"):
            v = [r["p"] for r in W if r["sheet"] == f"writer-{fam}-{eff}"]
            means[eff] = st.fmean(v)
            print(f"  writer {fam}-{eff:<7} mean={means[eff]:.3f}")
        print(f"  {fam} writer range (max-min over efforts): {max(means.values()) - min(means.values()):.3f}")

    # ---- 2. judge side: does effort move the verdict? ---------------------
    print("\n=== 2. effort dial, judge side ===")
    panel_mean = {
        (q, s): st.fmean([cm[(q, s, j)] for j in JUDGES if (q, s, j) in cm])
        for (q, s) in targets
    }
    for j in JUDGES:
        d = [cm[(q, s, j)] - panel_mean[(q, s)] for (q, s) in targets if (q, s, j) in cm]
        print(f"  judge {j:<14} leniency vs panel: {st.fmean(d):+.3f}")
    for fam in ("codex", "claude"):
        d = [
            abs(cm[(q, s, f"{fam}-low")] - cm[(q, s, f"{fam}-high")])
            for (q, s) in targets
            if (q, s, f"{fam}-low") in cm and (q, s, f"{fam}-high") in cm
        ]
        mlow = st.fmean([cm[(q, s, f"{fam}-low")] for (q, s) in targets if (q, s, f"{fam}-low") in cm])
        mhigh = st.fmean([cm[(q, s, f"{fam}-high")] for (q, s) in targets if (q, s, f"{fam}-high") in cm])
        print(
            f"  {fam} judge low vs high: mean|diff|={st.fmean(d):.3f}   "
            f"mean shift={mhigh - mlow:+.3f}"
        )

    # ---- 3. cheapest panel vs priciest panel ------------------------------
    print("\n=== 3. swap the whole panel: cheapest vs priciest ===")
    cheap = ["codex-low", "claude-low"]
    dear = ["codex-high", "claude-high"]
    per_t = {}
    for (q, s) in targets:
        c = [cm.get((q, s, j)) for j in cheap]
        e = [cm.get((q, s, j)) for j in dear]
        if all(v is not None for v in c + e):
            per_t[(q, s)] = (st.fmean(c), st.fmean(e))
    diffs = [abs(c - e) for c, e in per_t.values()]
    rho = spearman([c for c, _ in per_t.values()], [e for _, e in per_t.values()])
    print(
        f"  per-answer score, low-effort panel vs high-effort panel:\n"
        f"    mean|diff|={st.fmean(diffs):.3f}   max|diff|={max(diffs):.3f}   spearman={rho:.3f}   n={len(per_t)}"
    )
    for lbl, js in (("low-effort pair ", cheap), ("high-effort pair", dear), ("all six        ", JUDGES)):
        m = mat(W, js)
        print(f"  ICC({lbl}) = {icc(m):.3f}")
    # writer ranking under each panel
    for lbl, js in (("cheapest", cheap), ("priciest", dear)):
        wm = {
            s: st.fmean([cm[(q, s2, j)] for (q, s2, j) in cm if s2 == s and j in js])
            for s in SHEETS
            if s.startswith("writer-")
        }
        order = sorted(wm, key=wm.get, reverse=True)
        print(f"  writer ranking by {lbl} panel: " + " > ".join(o.removeprefix("writer-") for o in order))

    # ---- 4. anchors under low effort only ---------------------------------
    print("\n=== 4. validity restricted to low-effort judges ===")
    void = set(json.loads((__import__("pathlib").Path(__file__).resolve().parent / "study24-anchor-notes.json").read_text())["reference_missing_for"])
    lows = [r for r in rows if r["judge"].endswith("-low")]
    emp = [r["p"] for r in lows if r["sheet"] == "anchor-empty"]
    ref = [r["p"] for r in lows if r["sheet"] == "anchor-reference" and r["qid"] not in void]
    print(f"  empty:     mean={st.fmean(emp):.3f}   <=0.1 in {sum(x <= 0.1 for x in emp)}/{len(emp)}")
    print(f"  reference: mean={st.fmean(ref):.3f}   >=0.9 in {sum(x >= 0.9 for x in ref)}/{len(ref)}")
    sd, ex = within_sd(lows)
    print(f"  low-effort within-judge SD={sd:.4f}   identical across repeats={ex:.0%}")

    # ---- 5. variance decomposition ----------------------------------------
    print("\n=== 5. where does score variance come from? ===")
    m = mat(W, JUDGES)
    n, k = len(m), len(JUDGES)
    grand = st.fmean([x for r in m for x in r])
    rm = [st.fmean(r) for r in m]
    cmn = [st.fmean([m[i][j] for i in range(n)]) for j in range(k)]
    msr = k * sum((x - grand) ** 2 for x in rm) / (n - 1)
    msc = n * sum((x - grand) ** 2 for x in cmn) / (k - 1)
    mse = (
        sum((m[i][j] - grand) ** 2 for i in range(n) for j in range(k))
        - k * sum((x - grand) ** 2 for x in rm)
        - n * sum((x - grand) ** 2 for x in cmn)
    ) / ((n - 1) * (k - 1))
    var_t = max((msr - mse) / k, 0.0)   # answers
    var_j = max((msc - mse) / n, 0.0)   # judges
    var_e = max(mse, 0.0)               # residual + repeat noise
    tot = var_t + var_j + var_e
    print(f"  answers (which answer is graded): {var_t / tot:.1%}")
    print(f"  judges  (who grades it):          {var_j / tot:.1%}")
    print(f"  residual:                         {var_e / tot:.1%}")


if __name__ == "__main__":
    main()
