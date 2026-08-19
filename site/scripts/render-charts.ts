/** Static figures from published results, drawn by the page's own code.
 *
 * Usage: node --experimental-strip-types site/scripts/render-charts.ts \
 *          --in <dir with results-index.json and <entry>.json> --out <dir>
 *
 * The directory is what `a2b results publish --dry-run` writes, or anything
 * fetched with `a2b results fetch`.
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { buildParetoOption, buildRadarOption } from '../src/lib/charts/options.ts'
import { renderToSvg } from '../src/lib/charts/engine.ts'
import { MAX_SERIES } from '../src/lib/charts/theme.ts'
import {
  droppedByFilter,
  examGroups,
  groupByExam,
  scoreEntry,
  type ResultsEntry,
  type ResultsIndex,
} from '../src/lib/results.ts'

function arg(name: string, fallback: string): string {
  const i = process.argv.indexOf(`--${name}`)
  return i === -1 ? fallback : (process.argv[i + 1] ?? fallback)
}

const inDir = arg('in', '.')
const outDir = arg('out', 'fig')
const grade = arg('grade', 'all') === 'det' ? 'det' : 'all'

const index: ResultsIndex = JSON.parse(readFileSync(join(inDir, 'results-index.json'), 'utf8'))
const entries: Record<string, ResultsEntry> = {}
for (const file of readdirSync(inDir).filter((f) => f.endsWith('.json'))) {
  if (basename(file) === 'results-index.json') continue
  const entry: ResultsEntry = JSON.parse(readFileSync(join(inDir, file), 'utf8'))
  entries[entry.entry_id] = entry
}
for (const entry of index.entries) {
  if (entries[entry.entry_id]) continue
  const nested = join(inDir, `results-${entry.entry_id}`, 'entry.json')
  try {
    entries[entry.entry_id] = JSON.parse(readFileSync(nested, 'utf8'))
  } catch {
    console.warn(`no per-paper rows for ${entry.entry_id}; it will be left out`)
  }
}

const dropped = droppedByFilter(index.papers, grade)
const papers = index.papers
  .map((p) => p.subset)
  .filter((s) => !dropped.some((d) => d.subset === s))
const scores = index.entries
  .map((e) => scoreEntry(e, entries[e.entry_id], papers, grade, 'micro', 'output'))
  .filter((s) => s.eligible)
  .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))

const groups = examGroups(index.papers.filter((p) => papers.includes(p.subset)))
mkdirSync(outDir, { recursive: true })

const figures: [string, string][] = [
  ['results-pareto.svg', renderToSvg(buildParetoOption(scores, { cost: 'output', average: 'micro' }), 900, 520)],
  [
    // Four outlines is what rule alone can keep apart; the leaders, per paper.
    'results-radar.svg',
    renderToSvg(
      buildRadarOption(scores.slice(0, MAX_SERIES), papers, {
        cost: 'output',
        average: 'micro',
      }),
      820,
      680,
    ),
  ],
  [
    'results-radar-by-exam.svg',
    renderToSvg(
      buildRadarOption(
        groupByExam(scores.slice(0, MAX_SERIES), groups),
        groups.map((g) => g.exam),
        { cost: 'output', average: 'micro' },
      ),
      760,
      600,
    ),
  ],
]
for (const [name, svg] of figures) {
  writeFileSync(join(outDir, name), svg)
  console.log(`${join(outDir, name)}  ${(svg.length / 1024).toFixed(1)} kB`)
}
console.log(`${scores.length} configurations over ${papers.length} papers`)
