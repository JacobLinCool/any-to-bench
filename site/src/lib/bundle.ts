/** The shapes a2b writes into a bundle. Mirrors src/any_to_bench/schemas/. */

export type TextBlock = { type: 'text'; markdown: string }
export type ImageBlock = { type: 'image'; asset: string; alt: string; caption?: string | null }
export type TableBlock = { type: 'table'; header: string[]; rows: string[][]; caption?: string | null }
export type ContentBlock = TextBlock | ImageBlock | TableBlock

export type QuestionType =
  | 'single_choice'
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_blank'
  | 'matching'
  | 'short_answer'
  | 'essay'
  | 'drawing'
  | 'composite'

export type Option = { id: string; content: ContentBlock[] }
export type Blank = { id: string; label?: string | null }
export type MatchItem = { id: string; content: ContentBlock[] }
export type MatchingSpec = { left: MatchItem[]; right: MatchItem[] }

export type Question = {
  id: string
  number?: string | null
  type: QuestionType
  prompt: ContentBlock[]
  points: number
  options?: Option[] | null
  blanks?: Blank[] | null
  matching?: MatchingSpec | null
  children: Question[]
}

export type Section = {
  id: string
  title?: string | null
  instructions: ContentBlock[]
  questions: Question[]
}

export type Exam = {
  schema_version: string
  exam_id: string
  title: string
  subject?: string | null
  language: string
  description?: string | null
  total_points: number
  sections: Section[]
}

export type RubricLevel = { points: number; descriptor: string }
export type RubricCriterion = { id: string; description: string; levels: RubricLevel[] }

export type GradingRule =
  | {
      kind: 'choice'
      correct: string[]
      partial_credit: boolean
      wrong_selection_penalty: number
      negative_marking: number | null
    }
  | { kind: 'per_option'; correct: string[]; ratio_by_errors: number[] }
  | { kind: 'true_false'; correct: boolean; negative_marking: number | null }
  | {
      kind: 'fill_in_blank'
      blanks: Record<string, { accepted: string[]; weight: number }>
      all_or_nothing: boolean
    }
  | { kind: 'matching'; correct_pairs: Record<string, string>; all_or_nothing: boolean }
  | {
      kind: 'judge'
      reference_answer: string | null
      reference_assets: string[]
      rubric: RubricCriterion[]
      judge_instructions: string | null
      include_question_images: boolean
    }

export type QuestionGrading = {
  question_id: string
  max_points: number
  min_points: number
  rule: GradingRule
}

export type Grading = {
  exam_id: string
  judge?: { models: string[]; aggregation: string } | null
  questions: Record<string, QuestionGrading>
}

export type Manifest = {
  schema_version: string
  created_at: string
  tool_version: string
  ingest_model?: string | null
  /** Digests ride along in the file; they are never rendered. */
  sources: { path: string; sha256: string }[]
  warnings: string[]
}

export type Bundle = { name: string; exam: Exam; grading: Grading; manifest: Manifest }

/** Leaf questions in document order — the ones that carry a grading entry. */
export function leaves(question: Question): Question[] {
  return question.children.length ? question.children.flatMap(leaves) : [question]
}

export function examLeaves(exam: Exam): Question[] {
  return exam.sections.flatMap((s) => s.questions.flatMap(leaves))
}

/** Ancestors of a leaf, outermost first: composite stimulus a sub-question needs. */
export function ancestors(top: Question, leafId: string): Question[] {
  if (top.id === leafId) return []
  for (const child of top.children) {
    if (child.id === leafId) return [top]
    const deeper = ancestors(child, leafId)
    if (deeper.length || child.children.some((c) => c.id === leafId)) return [top, ...deeper]
  }
  return []
}

export const RULE_LABEL: Record<GradingRule['kind'], string> = {
  choice: 'Choice',
  per_option: 'Per-option',
  true_false: 'True / false',
  fill_in_blank: 'Fill in blank',
  matching: 'Matching',
  judge: 'LLM judge',
}

export const TYPE_LABEL: Record<QuestionType, string> = {
  single_choice: 'Single choice',
  multiple_choice: 'Multiple choice',
  true_false: 'True / false',
  fill_in_blank: 'Fill in blank',
  matching: 'Matching',
  short_answer: 'Short answer',
  essay: 'Essay',
  drawing: 'Drawing',
  composite: 'Composite',
}

/** Deterministic rules grade as scripts; judge rules cost a model call. */
export function isDeterministic(rule: GradingRule): boolean {
  return rule.kind !== 'judge'
}

export type BundleStats = {
  questions: number
  auto: number
  judged: number
  points: number
  figures: number
  types: { type: QuestionType; count: number }[]
}

export function stats(bundle: Bundle): BundleStats {
  const qs = examLeaves(bundle.exam)
  const counts = new Map<QuestionType, number>()
  let figures = 0
  const seen = new Set<string>()
  const walkBlocks = (blocks: ContentBlock[]) => {
    for (const b of blocks) if (b.type === 'image' && !seen.has(b.asset)) seen.add(b.asset)
  }
  for (const section of bundle.exam.sections) {
    walkBlocks(section.instructions)
    const stack = [...section.questions]
    while (stack.length) {
      const q = stack.pop()!
      walkBlocks(q.prompt)
      for (const o of q.options ?? []) walkBlocks(o.content)
      for (const m of [...(q.matching?.left ?? []), ...(q.matching?.right ?? [])])
        walkBlocks(m.content)
      stack.push(...q.children)
    }
  }
  figures = seen.size
  let auto = 0
  for (const q of qs) {
    counts.set(q.type, (counts.get(q.type) ?? 0) + 1)
    const rule = bundle.grading.questions[q.id]?.rule
    if (rule && isDeterministic(rule)) auto += 1
  }
  return {
    questions: qs.length,
    auto,
    judged: qs.length - auto,
    points: bundle.exam.total_points,
    figures,
    types: [...counts.entries()]
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count),
  }
}
