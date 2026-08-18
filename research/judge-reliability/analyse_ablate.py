"""Paired analysis of the rubric ablation.

Same 12 questions, same answer sheets, same six judges; the only difference is
whether the rubric exists. The with-rubric condition uses repeat 1 of the
original study so both sides are single-pass. Decision rule, fixed before the
run: if the high-discrimination questions' writer spread collapses by half or
more toward stratum-A levels, the rubric causes discrimination; if it
persists, discrimination lives in the question structure.
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
JUDGES = [f"{f}-{e}" for f in ("codex", "claude") for e in ("low", "medium", "high")]
WRITERS = [f"writer-{f}-{e}" for f in ("codex", "claude") for e in ("low", "medium", "high")]
prov = {p["pilot_id"]: p for p in json.loads((HERE / "provenance-study24.json").read_text())}
KEEP = sorted(q for q in prov if prov[q]["stratum"] in ("C", "D"))


def load(dirname: str, suffix: str) -> dict[tuple[str, str, str], float]:
    """{(qid, sheet, judge): p} from single-pass reports."""
    cells: dict[tuple[str, str, str], float] = {}
    for sheet in WRITERS + ["anchor-reference", "anchor-empty"]:
        for judge in JUDGES:
            f = HERE / dirname / f"{sheet}--judge-{judge}{suffix}.json"
            if not f.exists():
                continue
            rep = json.loads(f.read_text())
            for qid, q in rep["results"].items():
                if qid in prov and prov[qid]["stratum"] in ("C", "D") and q["mode"] == "judge":
                    cells[(qid, sheet, judge)] = q["awarded"] / q["max_points"]
    return cells


def spread(cells, qid) -> float:
    """SD of the six writers' mean scores on one question."""
    means = []
    for sheet in WRITERS:
        v = [cells[(qid, sheet, j)] for j in JUDGES if (qid, sheet, j) in cells]
        if v:
            means.append(st.fmean(v))
    return st.pstdev(means) if len(means) > 1 else float("nan")


def disagreement(cells, qid) -> float:
    """Mean (max-min) across judges, over the six writer answers."""
    sp = []
    for sheet in WRITERS:
        v = [cells[(qid, sheet, j)] for j in JUDGES if (qid, sheet, j) in cells]
        if len(v) > 1:
            sp.append(max(v) - min(v))
    return st.fmean(sp) if sp else float("nan")


def main() -> None:
    conds = [
        ("key+rubric", load("reports24", "--r1")),
        ("key only  ", load("reports_ab", "")),
        ("nothing   ", load("reports_bare", "")),
    ]
    conds = [(lbl, c) for lbl, c in conds if c]
    for lbl, c in conds:
        print(f"{lbl}: {len(c)} verdicts")
    print()

    print(
        f"{'question':<40} {'strat':<5} "
        + " ".join(f"{lbl.strip():>11}" for lbl, _ in conds)
        + "   (writer spread)"
    )
    pairs: dict[str, list[float]] = {}
    for qid in KEEP:
        vals = [spread(c, qid) for _, c in conds]
        pairs[qid] = vals
        print(f"{qid:<40} {prov[qid]['stratum']:<5} " + " ".join(f"{v:>11.3f}" for v in vals))

    hi = [q for q in KEEP if pairs[q][0] >= 0.10]
    print(f"\n高鑑別題 retention vs key+rubric ({len(hi)}):")
    for q in hi:
        base = pairs[q][0]
        rest = "  ".join(
            f"{lbl.strip()}={v / base:.0%}"
            for (lbl, _), v in zip(conds[1:], pairs[q][1:], strict=False)
        )
        print(f"  {q:<40} {rest}")
    for i, (lbl, _) in enumerate(conds[1:], start=1):
        med = st.median(pairs[q][i] / pairs[q][0] for q in hi)
        print(f"  median retention {lbl.strip()}: {med:.0%}")

    print(
        f"\n{'condition':<12} {'ICC':>6} {'judge分歧':>9} {'writer mean':>12} "
        f"{'empty':>7} {'reference':>10}"
    )
    from study24 import icc

    for lbl, cells in conds:
        tg = sorted({(q, s) for (q, s, _) in cells if s in WRITERS})
        m = [[cells.get((q, s, j)) for j in JUDGES] for (q, s) in tg]
        m = [r for r in m if all(v is not None for v in r)]
        sp = st.fmean([max(r) - min(r) for r in m])
        wm = st.fmean([v for (q, s, j), v in cells.items() if s in WRITERS])
        emp = [v for (q, s, j), v in cells.items() if s == "anchor-empty"]
        ref = [
            v
            for (q, s, j), v in cells.items()
            if s == "anchor-reference" and prov[q]["has_reference"]
        ]
        print(
            f"{lbl:<12} {icc(m):>6.3f} {sp:>9.3f} {wm:>12.3f} "
            f"{st.fmean(emp):>7.3f} {st.fmean(ref):>10.3f}"
        )


if __name__ == "__main__":
    main()
