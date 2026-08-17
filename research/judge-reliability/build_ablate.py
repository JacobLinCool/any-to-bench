"""Build the rubric-ablation bundle.

The stratum contrast in the paper is confounded: stratum A differs from C and D
in question type, not only in rubric presence. This bundle removes the confound
by construction: the same 12 C/D questions, the same figures, the same
reference answers, with only the rubric (criteria, levels, judge instructions)
stripped — exactly the shape stratum-A rules have. The same judges then
re-grade the same answer sheets, and any change in discrimination is the
rubric's own effect.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from any_to_bench.bundle import BundleManifest, ExamBundle
from any_to_bench.schemas.answers import AnswerSheet, generate_answer_schema
from any_to_bench.schemas.exam import Exam, Section
from any_to_bench.schemas.grading import GradingSpec, QuestionGrading

HERE = Path(__file__).resolve().parent
SRC = HERE / "study24"
# "bare" also strips the official reference answer, leaving zero guidance:
# the third point on the spectrum {nothing, key only, key + rubric}.
BARE = len(sys.argv) > 1 and sys.argv[1] == "bare"
NAME = "ablate12bare" if BARE else "ablate12"
OUT = HERE / NAME
EXAM_ID = f"judge-reliability-{NAME}"
SHEETS = [
    "writer-codex-low", "writer-codex-medium", "writer-codex-high",
    "writer-claude-low", "writer-claude-medium", "writer-claude-high",
    "anchor-reference", "anchor-empty",
]


def walk_assets(node: dict, acc: set[str]) -> None:
    for b in node.get("prompt") or []:
        if b.get("type") == "image":
            acc.add(b["asset"])
    for opt in node.get("options") or []:
        for b in opt.get("content") or []:
            if b.get("type") == "image":
                acc.add(b["asset"])
    for c in node.get("children") or []:
        walk_assets(c, acc)


def leaf_ids(node: dict, acc: set[str]) -> None:
    if node.get("children"):
        for c in node["children"]:
            leaf_ids(c, acc)
    else:
        acc.add(node["id"])


def main() -> None:
    prov = json.loads((HERE / "provenance-study24.json").read_text("utf-8"))
    keep = {p["pilot_id"] for p in prov if p["stratum"] in ("C", "D")}

    exam_src = json.loads((SRC / "exam.json").read_text("utf-8"))
    grading_src = json.loads((SRC / "grading.json").read_text("utf-8"))

    sections_raw = [s for s in exam_src["sections"] if s["id"] in ("stratum-C", "stratum-D")]
    leaves: set[str] = set()
    assets: set[str] = set()
    for s in sections_raw:
        for q in s["questions"]:
            leaf_ids(q, leaves)
            walk_assets(q, assets)
    assert leaves == keep, (leaves ^ keep)

    questions: dict[str, QuestionGrading] = {}
    for qid in sorted(keep):
        qg = json.loads(json.dumps(grading_src["questions"][qid]))
        qg["rule"]["rubric"] = []
        qg["rule"]["judge_instructions"] = None
        if BARE:
            qg["rule"]["reference_answer"] = None
            qg["rule"]["reference_assets"] = []
        assets.update(qg["rule"].get("reference_assets") or [])
        questions[qid] = QuestionGrading.model_validate(qg)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for a in sorted(assets):
        shutil.copy2(SRC / a, OUT / a)

    total = sum(q["points"] for s in sections_raw for q in s["questions"])
    exam = Exam(
        schema_version="1",
        exam_id=EXAM_ID,
        title="Rubric ablation: strata C and D of the judge-reliability study",
        subject="mixed",
        language="zh-TW",
        total_points=total,
        sections=[Section.model_validate(s) for s in sections_raw],
    )
    bundle = ExamBundle(
        root=OUT,
        exam=exam,
        grading=GradingSpec(exam_id=EXAM_ID, questions=questions),
        answer_schema=generate_answer_schema(exam),
        manifest=BundleManifest(ingest_model="(derived from study24; rubrics stripped)"),
    )
    bundle.save()
    print(f"{NAME}: {len(questions)} questions, {total:g} points, {len(assets)} assets")

    for name in SHEETS:
        src = json.loads((HERE / f"study24-answers-{name}.json").read_text("utf-8"))
        sheet = AnswerSheet(
            exam_id=EXAM_ID,
            taker=src["taker"],
            answers={qid: a for qid, a in src["answers"].items() if qid in keep},
        )
        problems = bundle.validate_answer_sheet(sheet)
        assert not problems, (name, problems)
        (HERE / f"{NAME}-answers-{name}.json").write_text(
            sheet.model_dump_json(indent=2), "utf-8"
        )
        print(f"{NAME}-answers-{name}.json ({len(sheet.answers)} answers)")


if __name__ == "__main__":
    main()
