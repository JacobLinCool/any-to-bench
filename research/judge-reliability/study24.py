"""Analysis for the 24-question, two-family study.

Adds what the single-family pilot could not ask: whether judges reward length
rather than quality, and whether a judge favours prose from its own family.
"""

from __future__ import annotations

import itertools
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHEETS = [
    "writer-codex-low", "writer-codex-medium", "writer-codex-high",
    "writer-claude-low", "writer-claude-medium", "writer-claude-high",
    "anchor-reference", "anchor-empty",
]
JUDGES = [f"{f}-{e}" for f in ("codex", "claude") for e in ("low", "medium", "high")]
REPS = [1, 2, 3]


def load():
    prov = {p["pilot_id"]: p for p in json.loads((HERE / "provenance-study24.json").read_text())}
    lengths: dict[tuple[str, str], int] = {}
    for sheet in SHEETS:
        f = HERE / f"study24-answers-{sheet}.json"
        if f.exists():
            for qid, a in json.loads(f.read_text())["answers"].items():
                lengths[(sheet, qid)] = len((a.get("text") or a.get("description") or "").strip())
    rows = []
    for sheet in SHEETS:
        for judge in JUDGES:
            for rep in REPS:
                f = HERE / "reports24" / f"{sheet}--judge-{judge}--r{rep}.json"
                if not f.exists():
                    continue
                rep_json = json.loads(f.read_text())
                for qid, q in rep_json["results"].items():
                    if q["mode"] != "judge":
                        continue  # judge crashed or produced nothing; not a score
                    d = q.get("detail") or {}
                    raw = (d.get("raw_totals") or [None])[0]
                    mx = q["max_points"]
                    rows.append({
                        "qid": qid, "stratum": prov[qid]["stratum"], "max": mx,
                        "type": prov[qid]["type"], "sheet": sheet, "judge": judge,
                        "jfam": judge.split("-")[0], "wfam": sheet.split("-")[1] if sheet.startswith("writer-") else "anchor",
                        "rep": rep, "p": q["awarded"] / mx if mx else 0.0,
                        "p_raw": (raw / mx) if (raw is not None and mx) else None,
                        "snapped": bool((d.get("snap_changed") or [False])[0]),
                        "len": lengths.get((sheet, qid), 0),
                    })
    return rows, prov


def cells(rows, key="p"):
    acc = defaultdict(list)
    for r in rows:
        if r[key] is not None:
            acc[(r["qid"], r["sheet"], r["judge"])].append(r[key])
    return {k: st.fmean(v) for k, v in acc.items()}


def within_sd(rows):
    acc = defaultdict(list)
    for r in rows:
        acc[(r["qid"], r["sheet"], r["judge"])].append(r["p"])
    var = [st.pvariance(v) for v in acc.values() if len(v) > 1]
    ex = sum(1 for v in acc.values() if len(v) > 1 and len(set(v)) == 1)
    n = sum(1 for v in acc.values() if len(v) > 1)
    return (st.fmean(var) ** 0.5 if var else float("nan")), (ex / n if n else float("nan"))


def icc(matrix):
    n, k = len(matrix), len(matrix[0]) if matrix else 0
    if n < 2 or k < 2:
        return float("nan")
    grand = st.fmean([x for r in matrix for x in r])
    rm = [st.fmean(r) for r in matrix]
    cmn = [st.fmean([matrix[i][j] for i in range(n)]) for j in range(k)]
    ssr = k * sum((m - grand) ** 2 for m in rm)
    ssc = n * sum((m - grand) ** 2 for m in cmn)
    sst = sum((matrix[i][j] - grand) ** 2 for i in range(n) for j in range(k))
    sse = sst - ssr - ssc
    msr, msc, mse = ssr / (n - 1), ssc / (k - 1), sse / ((n - 1) * (k - 1))
    den = msr + (k - 1) * mse + k * (msc - mse) / n
    return (msr - mse) / den if den else float("nan")


def mat(rows, judges):
    cm = cells(rows)
    tg = sorted({(q, s) for (q, s, _) in cm})
    m = [[cm.get((q, s, j)) for j in judges] for (q, s) in tg]
    return [r for r in m if all(v is not None for v in r)]


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = st.fmean(rx), st.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def main():
    rows, prov = load()
    got = len({(r["sheet"], r["judge"], r["rep"]) for r in rows})
    complete = sum(
        1 for _ in {(r["sheet"], r["judge"], r["rep"]) for r in rows}
    )
    per_pass = defaultdict(int)
    for r in rows:
        per_pass[(r["sheet"], r["judge"], r["rep"])] += 1
    full = sum(1 for v in per_pass.values() if v == 24)
    print(f"grading passes with usable verdicts: {got}/144 ({full} complete)   rows: {len(rows)}")
    del complete
    have = sorted({r["judge"] for r in rows})
    W = [r for r in rows if r["sheet"].startswith("writer-")]

    print("\n=== score by writer ===")
    for s in SHEETS:
        v = [r["p"] for r in rows if r["sheet"] == s]
        if v:
            print(f"  {s:<22} n={len(v):>4} mean={st.fmean(v):.3f} sd={st.pstdev(v):.3f} min={min(v):.2f}")

    if len(have) >= 2:
        print("\n=== agreement, writer answers only ===")
        for lbl, js in (("codex judges", JUDGES[:3]), ("claude judges", JUDGES[3:]), ("all six", JUDGES)):
            js = [j for j in js if j in have]
            if len(js) < 2:
                continue
            m, m1 = mat(W, js), mat([r for r in W if r["rep"] == 1], js)
            if len(m) > 1:
                sp = [max(r) - min(r) for r in m]
                print(f"  {lbl:<15} n={len(m):>3} ICC={icc(m):.3f} spread={st.fmean(sp):.3f} | single-run ICC={icc(m1):.3f}")

    print("\n=== verbosity: do judges pay for length? ===")
    cm = cells(W)
    lens = {(r["qid"], r["sheet"]): r["len"] for r in W}
    for j in [j for j in JUDGES if j in have]:
        pts = [(lens[(q, s)], cm[(q, s, j)]) for (q, s, jj) in cm if jj == j]
        by_q = defaultdict(list)
        for (q, s, jj), v in cm.items():
            if jj == j:
                by_q[q].append((lens[(q, s)], v))
        rhos = [spearman([a for a, _ in v], [b for _, b in v]) for v in by_q.values() if len(v) >= 4]
        rhos = [x for x in rhos if x == x]
        if rhos:
            print(f"  {j:<15} median within-question rho(length, score) = {st.median(rhos):+.2f}  over {len(rhos)} questions")

    print("\n=== self-preference: judge family vs writer family ===")
    for jf in ("codex", "claude"):
        js = [j for j in JUDGES if j.startswith(jf) and j in have]
        if not js:
            continue
        for wf in ("codex", "claude"):
            v = [cm[(q, s, j)] for (q, s, j) in cm if j in js and f"writer-{wf}-" in s]
            if v:
                print(f"  {jf} judges on {wf} answers: {st.fmean(v):.3f}  (n={len(v)})")

    print("\n=== stability ===")
    for j in [j for j in JUDGES if j in have]:
        sd, ex = within_sd([r for r in W if r["judge"] == j])
        print(f"  {j:<15} SD={sd:.4f} identical={ex:.0%}")

    print("\n=== stratum, writers only (n=6 questions each) ===")
    for s in "ABCD":
        sub = [r for r in W if r["stratum"] == s]
        js = [j for j in JUDGES if j in have]
        m = mat(sub, js)
        if len(m) > 1:
            sp = [max(r) - min(r) for r in m]
            sd, _ = within_sd(sub)
            print(f"  {s}  n={len(m):>3} ICC={icc(m):.3f} spread={st.fmean(sp):.3f} withinSD={sd:.4f}")


if __name__ == "__main__":
    main()
