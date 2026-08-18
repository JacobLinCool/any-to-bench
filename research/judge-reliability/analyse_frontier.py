"""Frontier judges against the cheap pool: equivalence, not saturation.

Six frontier-tier configurations (GPT-5.6 Sol and Claude Opus 5 at three
efforts) grade the same eight sheets, single pass. If cheap grading is really
at the ceiling, the frontier judges should reproduce the cheap panel's scores;
any systematic gap is what the saturation argument could not rule out.
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHEAP = [f"{f}-{e}" for f in ("codex", "claude") for e in ("low", "medium", "high")]
FRONT = [f"{f}-{e}" for f in ("sol", "opus") for e in ("low", "medium", "high")]
WRITERS = [f"writer-{f}-{e}" for f in ("codex", "claude") for e in ("low", "medium", "high")]
SHEETS = WRITERS + ["anchor-reference", "anchor-empty"]
prov = {p["pilot_id"]: p for p in json.loads((HERE / "provenance-study24.json").read_text())}


def load() -> dict[tuple[str, str, str], float]:
    cells: dict[tuple[str, str, str], float] = {}
    for sheet in SHEETS:
        for j in CHEAP:
            f = HERE / "reports24" / f"{sheet}--judge-{j}--r1.json"
            for qid, q in json.loads(f.read_text())["results"].items():
                if q["mode"] == "judge":
                    cells[(qid, sheet, j)] = q["awarded"] / q["max_points"]
        for j in FRONT:
            f = HERE / "reports_frontier" / f"{sheet}--judge-{j}.json"
            if f.exists():
                for qid, q in json.loads(f.read_text())["results"].items():
                    if q["mode"] == "judge":
                        cells[(qid, sheet, j)] = q["awarded"] / q["max_points"]
    return cells


def icc(matrix):
    n, k = len(matrix), len(matrix[0]) if matrix else 0
    if n < 2 or k < 2:
        return float("nan")
    grand = st.fmean([x for r in matrix for x in r])
    rm = [st.fmean(r) for r in matrix]
    cm = [st.fmean([matrix[i][j] for i in range(n)]) for j in range(k)]
    ssr = k * sum((m - grand) ** 2 for m in rm)
    ssc = n * sum((m - grand) ** 2 for m in cm)
    sst = sum((matrix[i][j] - grand) ** 2 for i in range(n) for j in range(k))
    sse = sst - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    den = msr + (k - 1) * mse + k * (msc - mse) / n
    return (msr - mse) / den if den else float("nan")


def mat(cells, judges, sheets):
    tg = sorted({(q, s) for (q, s, _) in cells if s in sheets})
    m = [[cells.get((q, s, j)) for j in judges] for (q, s) in tg]
    return [r for r in m if all(v is not None for v in r)]


def main() -> None:
    cells = load()
    got = sorted({j for (_, _, j) in cells if j in FRONT})
    print(f"frontier judges present: {got}")
    n_front = sum(1 for (q, s, j) in cells if j in FRONT)
    print(f"frontier verdicts: {n_front} (expect 1152)\n")

    consensus = {}
    for (q, s, j), v in cells.items():
        if j in CHEAP and s in WRITERS:
            consensus.setdefault((q, s), []).append(v)
    consensus = {k: st.fmean(v) for k, v in consensus.items()}

    print(f"{'judge':<12} {'mean given':>10} {'MAE vs cheap panel':>19}")
    for j in CHEAP + FRONT:
        vals = [v for (q, s, jj), v in cells.items() if jj == j and s in WRITERS]
        mae = [
            abs(cells[(q, s, j)] - consensus[(q, s)]) for (q, s) in consensus if (q, s, j) in cells
        ]
        tier = "cheap" if j in CHEAP else "FRONTIER"
        if vals:
            print(f"{j:<12} {st.fmean(vals):>10.3f} {st.fmean(mae):>19.3f}   {tier}")

    print()
    for lbl, js in (
        ("cheap 6", CHEAP),
        ("frontier 6", FRONT),
        ("all 12", CHEAP + FRONT),
        ("cheapest pair {luna-low, sonnet-low}", ["codex-low", "claude-low"]),
        ("priciest pair {sol-high, opus-high}", ["sol-high", "opus-high"]),
    ):
        m = mat(cells, js, WRITERS)
        if len(m) > 1:
            print(f"ICC({lbl}) = {icc(m):.3f}   n={len(m)}")

    # cheapest pair vs priciest pair, per answer
    a = mat(cells, ["codex-low", "claude-low", "sol-high", "opus-high"], WRITERS)
    if a:
        d = [abs(st.fmean(r[:2]) - st.fmean(r[2:])) for r in a]
        print(
            f"\n|cheapest pair - priciest frontier pair| per answer: "
            f"mean={st.fmean(d):.3f}  max={max(d):.3f}"
        )

    for j in FRONT:
        emp = [v for (q, s, jj), v in cells.items() if jj == j and s == "anchor-empty"]
        ref = [
            v
            for (q, s, jj), v in cells.items()
            if jj == j and s == "anchor-reference" and prov[q]["has_reference"]
        ]
        if emp:
            print(
                f"anchors {j:<11} empty={st.fmean(emp):.3f} "
                f"({sum(x <= 0.1 for x in emp)}/{len(emp)} zero-ish)  "
                f"reference={st.fmean(ref):.3f} ({sum(x >= 0.9 for x in ref)}/{len(ref)} >=0.9)"
            )


if __name__ == "__main__":
    main()
