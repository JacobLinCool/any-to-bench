#!/usr/bin/env bash
# Build the arXiv submission bundle and verify it compiles standalone.
#
# arXiv compiles what you upload and nothing else, so the check that matters is
# a clean-room build: stage only the files the bundle claims to need, compile
# there, and compare the page count against the local build. The bundle is a
# build artifact and is not committed.
#
# The bibliography is a plain thebibliography environment (neurips is loaded
# with nonatbib), so no .bbl is required. \pdfoutput=1 in paper.tex keeps arXiv
# on pdflatex.
set -euo pipefail

cd "$(dirname "$0")"
OUT="arxiv-grading-needs-a-rubric.tar.gz"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Figures are build artifacts too; refuse to ship a bundle against missing or
# stale ones rather than silently packaging whatever happens to be on disk.
# Staleness is measured against the figure scripts, not paper.tex: editing prose
# does not stale a figure, and a warning that fires every time gets ignored.
NEWEST_SCRIPT=$(ls -t ../figures*.py | head -1)
for f in $(grep -o 'fig/[a-z0-9-]*\.pdf' paper.tex | sort -u); do
  [ -f "$f" ] || { echo "missing $f -- run the figure scripts first" >&2; exit 1; }
  [ "$f" -nt "$NEWEST_SCRIPT" ] || echo "note: $f predates $NEWEST_SCRIPT" >&2
  mkdir -p "$STAGE/fig" && cp "$f" "$STAGE/fig/"
done
cp paper.tex neurips_2025.sty "$STAGE/"

tar czf "$OUT" -C "$STAGE" .

# Clean room: compile the staged copy with nothing else reachable.
( cd "$STAGE" && latexmk -pdf -interaction=nonstopmode paper.tex >/dev/null 2>&1 ) \
  || { echo "clean-room build FAILED" >&2; exit 1; }

pages() { pdfinfo "$1" | awk '/^Pages/ {print $2}'; }
got=$(pages "$STAGE/paper.pdf")
want=$(pages paper.pdf)
over=$(grep -c Overfull "$STAGE/paper.log" || true)
[ "$got" = "$want" ] || { echo "page mismatch: bundle $got vs local $want" >&2; exit 1; }

# The plain-text abstract for the arXiv form, derived from paper.tex so the
# two cannot drift apart. Fails loudly rather than shipping stray markup.
python3 - <<'ABS'
import re, textwrap
from pathlib import Path
a = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
              Path("paper.tex").read_text(), re.S).group(1)
a = a.replace("\\noindent", "").replace("\\textsc{any-to-bench}", "any-to-bench")
a = re.sub(r"\\,\\%", "%", a).replace("{,}", ",")
a = re.sub(r"\s+", " ", a.replace("~", " ")).strip()
leftover = [c for c in a if c in "\\{}"]
assert not leftover, f"unconverted markup in abstract: {leftover}"
assert len(a) <= 1920, f"abstract is {len(a)} chars, over the arXiv limit"
Path("arxiv-abstract.txt").write_text(textwrap.fill(a, 79) + "\n")
print(f"arxiv-abstract.txt  ({len(a.split())} words, {len(a)}/1920 chars)")
ABS

echo "$OUT  ($(du -h "$OUT" | cut -f1), $(tar tzf "$OUT" | grep -vc '/$') files)"
echo "clean-room build ok: $got pages, $over overfull"
