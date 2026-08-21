/** Published evaluation results, and the arithmetic the leaderboard runs on.
 *
 * Mirrors src/any_to_bench/schemas/results.py. Every number shown on the page
 * comes out of `aggregate` below, so the two charts and the table can never
 * disagree about what a selection scores.
 */

export type RuleClass = 'deterministic' | 'judge'

export type PointBucket = {
  questions: number
  max_points: number
  skipped_points: number
  covered_max: number
  awarded: number
  full_credit: number
  unanswered: number
  errored: number
  skipped: number
}

export type PaperResult = {
  subset: string
  exam_id: string
  title: string
  subject: string | null
  language: string
  total_points: number
  judge_models: string[]
  runs: number
  ok_runs: number
  failed: string[]
  deterministic: PointBucket
  judge: PointBucket
  awarded_samples: number[]
  det_awarded_samples: number[]
  solve_secs: number | null
  grade_secs: number | null
  solve_usage: PhaseUsage
  grade_usage: PhaseUsage | null
  classification: 'rule-kind' | 'mode-fallback'
  warnings: string[]
}

export type PhaseUsage = {
  requests: number
  input_tokens: number
  output_tokens: number
  reasoning_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
}

export type ResultsEntry = {
  schema_version: string
  entry_id: string
  tool_version: string
  source_repo: string
  taker: {
    model: string
    effort: string | null
    agentic: boolean
    repeat: number
  }
  note: string | null
  published_at: string
  first_run_at: string
  last_run_at: string
  papers: PaperResult[]
}

export type PaperMeta = {
  subset: string
  source_repo: string
  title: string
  subject: string | null
  exam: string | null
  year: string | null
  total_points: number
  deterministic_points: number
  judge_points: number
  questions: number
  judge_questions: number
}

export type IndexEntry = {
  entry_id: string
  path: string
  model: string
  effort: string | null
  agentic: boolean
  judge_models: string[]
  tool_version: string
  repeat: number
  published_at: string
  papers: string[]
  ok_papers: number
  awarded: number
  covered_max: number
  percentage: number | null
  det_awarded: number
  det_covered_max: number
  det_percentage: number | null
  solve_output_tokens: number
  solve_secs: number
  grade_secs: number
  any_mode_fallback: boolean
  note: string | null
}

export type ResultsIndex = {
  schema_version: string
  generated_at: string
  tool_version: string
  source_repos: string[]
  papers: PaperMeta[]
  entries: IndexEntry[]
}

/** Effort is a dial, so it sorts as one; a provider default is not a level on it. */
export const EFFORTS = [
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
] as const

export function effortRank(effort: string | null): number {
  const i = EFFORTS.indexOf((effort ?? '') as (typeof EFFORTS)[number])
  return i === -1 ? -1 : i
}

export function effortLabel(effort: string | null): string {
  return effort ?? 'provider default'
}

/** What to print for each model, with the harness prefix dropped where it can be.
 *
 * `codex:gpt-5.6-sol` reads as `gpt-5.6-sol`, and on a board where nothing else
 * claims that name the prefix is noise in every label, legend and axis. It
 * stops being noise the moment two harnesses run the same weights — a coding
 * agent and a plain API call are different takers — so a shared bare name
 * sends every claimant back to its full id rather than printing two rows that
 * read alike. Callers keep the full id for titles and tooltips.
 */
export function modelNames(models: Iterable<string>): Map<string, string> {
  const claims = new Map<string, Set<string>>()
  for (const model of models) {
    const bare = model.slice(model.indexOf(':') + 1)
    claims.set(bare, (claims.get(bare) ?? new Set()).add(model))
  }
  const names = new Map<string, string>()
  for (const [bare, owners] of claims) {
    for (const model of owners) names.set(model, owners.size > 1 ? model : bare)
  }
  return names
}

export function entryLabel(entry: {
  model: string
  effort: string | null
}): string {
  return `${entry.model} · ${effortLabel(entry.effort)}`
}

/** Which halves of the score a selection counts. */
export type GradeFilter = 'all' | 'det'

/** How papers of different sizes are weighed against each other. */
export type Average = 'micro' | 'macro'

/** What goes on the Pareto chart's cost axis: two bases × two normalisations.
 *
 * Input tokens are deliberately absent: codex reports cache reads inside
 * input_tokens and claude reports them only under cache_read_tokens, so an
 * input-based axis compares accounting conventions rather than cost. Output
 * tokens and wall time mean the same thing for every taker.
 *
 * The totals answer "what did this selection cost"; the per-question figures
 * answer "what does this taker cost to run", which is the number that carries
 * to a paper nobody here has sat. They part company as soon as the selection
 * changes size, so both are offered rather than one being called the cost.
 */
export type CostMetric = 'output' | 'output-per-q' | 'secs' | 'secs-per-q'

export const COST_LABEL: Record<CostMetric, string> = {
  output: 'solve output tokens',
  'output-per-q': 'solve output tokens per question',
  secs: 'solve seconds',
  'secs-per-q': 'solve seconds per question',
}

export const COST_METRICS = Object.keys(COST_LABEL) as CostMetric[]

/** Tokens span more than a decade across takers and want a log axis; seconds do not. */
export function costIsTokens(cost: CostMetric): boolean {
  return cost.startsWith('output')
}

export function costIsPerQuestion(cost: CostMetric): boolean {
  return cost.endsWith('-per-q')
}

export type PaperScore = {
  subset: string
  awarded: number
  coveredMax: number
  percentage: number | null
}

export type EntryScore = {
  entry: IndexEntry
  /** Present only when the entry covers every selected paper. */
  eligible: boolean
  missing: string[]
  awarded: number
  coveredMax: number
  /** Points-weighted across the selection. */
  micro: number | null
  /** Every paper weighed alike. */
  macro: number | null
  score: number | null
  cost: number
  papers: PaperScore[]
  /** Questions the taker was asked across the selection, skipped ones excluded. */
  questions: number
  /** Sample standard deviation, only when every paper has the same replicate count ≥ 2. */
  spread: number | null
  runs: number
}

function bucketsFor(paper: PaperResult, filter: GradeFilter): PointBucket[] {
  return filter === 'det'
    ? [paper.deterministic]
    : [paper.deterministic, paper.judge]
}

/** Papers a filter empties out — with `det`, a writing paper has no rule-graded
 * question at all, and a leaderboard that silently scored it 0% would be lying. */
export function droppedByFilter(
  papers: PaperMeta[],
  filter: GradeFilter,
): PaperMeta[] {
  if (filter !== 'det') return []
  return papers.filter((p) => p.deterministic_points <= 0)
}

export function selectedPapers(
  index: ResultsIndex,
  subsets: string[],
  filter: GradeFilter,
): PaperMeta[] {
  const wanted = new Set(subsets)
  const chosen = index.papers.filter((p) => wanted.has(p.subset))
  const dropped = new Set(droppedByFilter(chosen, filter).map((p) => p.subset))
  return chosen.filter((p) => !dropped.has(p.subset))
}

function sampleStd(values: number[]): number | null {
  if (values.length < 2) return null
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const variance =
    values.reduce((total, v) => total + (v - mean) ** 2, 0) /
    (values.length - 1)
  return Math.sqrt(variance)
}

/** One entry's score over one selection of papers. */
export function scoreEntry(
  indexEntry: IndexEntry,
  entry: ResultsEntry | undefined,
  subsets: string[],
  filter: GradeFilter,
  average: Average,
  cost: CostMetric,
): EntryScore {
  const wanted = new Set(subsets)
  const papers = (entry?.papers ?? []).filter(
    (p) => wanted.has(p.subset) && p.ok_runs > 0,
  )
  const covered = new Set(papers.map((p) => p.subset))
  const missing = subsets.filter((s) => !covered.has(s))

  let awarded = 0
  let coveredMax = 0
  let costTotal = 0
  /* The denominator for a per-question cost is every question the taker was
   * actually asked — both halves, minus anything it could not attempt. Not the
   * questions the grade filter counts: solving a paper costs what it costs, and
   * dividing that by the rule-graded half alone would make the axis jump every
   * time someone changed what is being scored. */
  let attempted = 0
  const perPaper: PaperScore[] = []
  const replicateCounts = new Set<number>()
  for (const paper of papers) {
    const buckets = bucketsFor(paper, filter)
    const a = buckets.reduce((total, b) => total + b.awarded, 0)
    const m = buckets.reduce((total, b) => total + b.covered_max, 0)
    awarded += a
    coveredMax += m
    costTotal += costIsTokens(cost)
      ? paper.solve_usage.output_tokens
      : (paper.solve_secs ?? 0)
    for (const bucket of [paper.deterministic, paper.judge]) {
      attempted += bucket.questions - bucket.skipped
    }
    perPaper.push({
      subset: paper.subset,
      awarded: a,
      coveredMax: m,
      percentage: m > 0 ? (100 * a) / m : null,
    })
    replicateCounts.add(paper.ok_runs)
  }

  const micro = coveredMax > 0 ? (100 * awarded) / coveredMax : null
  const scored = perPaper.filter((p) => p.percentage !== null)
  const macro = scored.length
    ? scored.reduce((total, p) => total + (p.percentage as number), 0) /
      scored.length
    : null

  // A spread is only meaningful when every paper was actually repeated the same
  // number of times; anything else would be an error bar invented from one sample.
  let spread: number | null = null
  const runs = (replicateCounts.size === 1 ? [...replicateCounts][0] : 0) ?? 0
  if (runs >= 2 && papers.length) {
    const totals: number[] = []
    for (let i = 0; i < runs; i++) {
      let total = 0
      for (const paper of papers) {
        const samples =
          filter === 'det' ? paper.det_awarded_samples : paper.awarded_samples
        total += samples[i] ?? 0
      }
      totals.push(coveredMax > 0 ? (100 * total) / coveredMax : 0)
    }
    spread = sampleStd(totals)
  }

  return {
    entry: indexEntry,
    eligible: missing.length === 0 && papers.length > 0,
    missing,
    awarded,
    coveredMax,
    micro,
    macro,
    score: average === 'micro' ? micro : macro,
    cost: costIsPerQuestion(cost) && attempted > 0 ? costTotal / attempted : costTotal,
    questions: attempted,
    papers: perPaper,
    spread,
    runs,
  }
}

/** The frontier: entries no other entry beats on both axes at once. */
export function paretoFrontier(scores: EntryScore[]): EntryScore[] {
  const usable = scores.filter((s) => s.score !== null && s.cost > 0)
  return usable
    .filter(
      (candidate) =>
        !usable.some(
          (other) =>
            other !== candidate &&
            other.cost <= candidate.cost &&
            (other.score as number) >= (candidate.score as number) &&
            (other.cost < candidate.cost ||
              (other.score as number) > (candidate.score as number)),
        ),
    )
    .sort((a, b) => a.cost - b.cost)
}

/** Entries of one model, ordered along the effort dial — one polyline each. */
export function byModel(
  scores: EntryScore[],
): { model: string; scores: EntryScore[] }[] {
  const groups = new Map<string, EntryScore[]>()
  for (const score of scores) {
    const list = groups.get(score.entry.model) ?? []
    list.push(score)
    groups.set(score.entry.model, list)
  }
  return [...groups.entries()]
    .map(([model, list]) => ({
      model,
      scores: list.sort(
        (a, b) => effortRank(a.entry.effort) - effortRank(b.entry.effort),
      ),
    }))
    .sort((a, b) => a.model.localeCompare(b.model))
}

/** Short axis label: gsat-115-math-a reads as math-a once the exam is the group. */
export function shortSubject(subset: string): string {
  const parts = subset.split('-')
  return parts.length > 2 ? parts.slice(2).join('-') : subset
}

export function examGroups(
  papers: PaperMeta[],
): { exam: string; subsets: string[] }[] {
  const groups = new Map<string, string[]>()
  for (const paper of papers) {
    const key = paper.exam ?? 'other'
    groups.set(key, [...(groups.get(key) ?? []), paper.subset])
  }
  return [...groups.entries()]
    .map(([exam, subsets]) => ({ exam, subsets: subsets.sort() }))
    .sort((a, b) => a.exam.localeCompare(b.exam))
}

/** Collapse the per-paper scores onto one axis per examination.
 *
 * Twenty-one axes is a mush; three is a shape. Points-weighted inside each
 * group, so a group's value means the same thing the headline does.
 */
export function groupByExam(
  scores: EntryScore[],
  groups: { exam: string; subsets: string[] }[],
): EntryScore[] {
  return scores.map((score) => ({
    ...score,
    papers: groups.map(({ exam, subsets }) => {
      const rows = score.papers.filter((p) => subsets.includes(p.subset))
      const awarded = rows.reduce((total, p) => total + p.awarded, 0)
      const coveredMax = rows.reduce((total, p) => total + p.coveredMax, 0)
      return {
        subset: exam,
        awarded,
        coveredMax,
        percentage: coveredMax > 0 ? (100 * awarded) / coveredMax : null,
      }
    }),
  }))
}

/** Axis labels that stay unique.
 *
 * Two exams can set a paper on the same subject, and two axes both reading
 * `chinese` would put the reader on the wrong vertex — so a repeated short name
 * is qualified by its examination.
 */
export function axisNames(subsets: string[]): string[] {
  const short = subsets.map(shortSubject)
  const seen = new Map<string, number>()
  short.forEach((name) => seen.set(name, (seen.get(name) ?? 0) + 1))
  return subsets.map((subset, i) => {
    const name = short[i]!
    if ((seen.get(name) ?? 0) < 2) return name
    const exam = subset.split('-')[0]
    return exam && exam !== subset ? `${exam} ${name}` : name
  })
}
