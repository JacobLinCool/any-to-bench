<script lang="ts">
  import { untrack } from 'svelte'
  import { ArrowLeft, ChevronRight, ExternalLink, Loader, Search, TriangleAlert } from '@lucide/svelte'
  import EChart from './lib/EChart.svelte'
  import Mark from './lib/Mark.svelte'
  import Sheet from './lib/Sheet.svelte'
  import { buildParetoOption, buildRadarOption, radarFloor } from './lib/charts/options'
  import { MAX_SERIES } from './lib/charts/theme'
  import {
    DEFAULT_RESULTS_REPO,
    HubError,
    isRepoId,
    loadResultsEntry,
    loadResultsIndex,
    repoUrl,
  } from './lib/hf'
  import {
    COST_LABEL,
    COST_METRICS,
    byModel,
    droppedByFilter,
    effortLabel,
    effortRank,
    entryLabel,
    axisNames,
    examGroups,
    fmtScore,
    groupByExam,
    modelNames,
    paretoFrontier,
    scoreEntry,
    shortSubject,
    type Average,
    type CostMetric,
    type GradeFilter,
    type ResultsEntry,
    type ResultsIndex,
  } from './lib/results'

  const BASE = import.meta.env.BASE_URL

  let repo = $state('')
  let draft = $state(DEFAULT_RESULTS_REPO)
  let index = $state<ResultsIndex | null>(null)
  let loaded = $state<Record<string, ResultsEntry>>({})
  let busy = $state(false)
  let loadingEntries = $state(false)
  let failure = $state<{ message: string; hint?: string } | null>(null)

  let paperSel = $state<string[]>([])
  let entrySel = $state<string[]>([])
  let grade = $state<GradeFilter>('all')
  let average = $state<Average>('micro')
  let cost = $state<CostMetric>('output')
  let origin = $state<'zoom' | 'zero'>('zoom')
  let grouped = $state(false)
  let radarAll = $state(false)
  // Only the newest request may write state: a stale rejection must never land
  // on top of a good result.
  let ticket = 0

  const groups = $derived(index ? examGroups(index.papers) : [])

  /* Computed over the whole board rather than the current selection, so a
   * label never changes because of what happens to be ticked. */
  const names = $derived(modelNames((index?.entries ?? []).map((e) => e.model)))
  const modelName = $derived((model: string) => names.get(model) ?? model)

  /* The rail lists configurations the way the chart draws them: one block per
   * model, its efforts in dial order. Sixteen flat rows is a wall of text that
   * happens to be sorted; four blocks of four is the shape of the experiment. */
  const entryGroups = $derived.by(() => {
    const byName = new Map<string, ResultsIndex['entries']>()
    for (const entry of index?.entries ?? []) {
      const list = byName.get(entry.model) ?? []
      list.push(entry)
      byName.set(entry.model, list)
    }
    return [...byName.entries()]
      .map(([model, entries]) => ({
        model,
        entries: entries.sort((a, b) => effortRank(a.effort) - effortRank(b.effort)),
      }))
      .sort((a, b) => a.model.localeCompare(b.model))
  })

  // Both lists are long enough to bury the controls above them, so both fold.
  let papersOpen = $state(true)
  let entriesOpen = $state(true)
  const allPapers = $derived((index?.papers ?? []).map((p) => p.subset))
  const dropped = $derived(
    index
      ? droppedByFilter(
          index.papers.filter((p) => paperSel.includes(p.subset)),
          grade,
        )
      : [],
  )
  const activePapers = $derived(
    paperSel.filter((s) => !dropped.some((p) => p.subset === s)),
  )

  const scores = $derived(
    (index?.entries ?? [])
      .filter((e) => entrySel.includes(e.entry_id))
      .map((e) => scoreEntry(e, loaded[e.entry_id], activePapers, grade, average, cost))
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1)),
  )
  const ranked = $derived(scores.filter((s) => s.eligible))
  const excluded = $derived(scores.filter((s) => !s.eligible))
  const frontier = $derived(new Set(paretoFrontier(ranked).map((s) => s.entry.entry_id)))
  const families = $derived(byModel(ranked))
  const repeated = $derived(ranked.some((s) => s.runs >= 2))
  const resourceBacked = $derived(
    (index?.papers ?? []).some(
      (paper) => activePapers.includes(paper.subset) && (paper.resource_files ?? 0) > 0,
    ),
  )

  /* A radar reads by outline, and outlines can only be told apart by rule —
   * four of them, since this world has one ink for data. So the chart carries
   * the leaders and says so; the table beneath it carries everyone. Collapsing
   * to one axis per examination is offered but not the default: three axes
   * average away exactly the per-subject differences the chart exists to show. */
  const radarShown = $derived(radarAll ? ranked : ranked.slice(0, MAX_SERIES))
  const radarHidden = $derived(ranked.length - radarShown.length)
  const radarGrouped = $derived(grouped)
  const radarScores = $derived(radarGrouped ? groupByExam(radarShown, groups) : radarShown)
  const radarSubsets = $derived(radarGrouped ? groups.map((g) => g.exam) : activePapers)
  const radarAxisNames = $derived(axisNames(radarSubsets))
  const chartOpts = $derived({ cost, average, origin, names })
  const paretoOption = $derived(buildParetoOption(ranked, chartOpts))
  /* Past four outlines one radar is a ball of wool, so the chart changes kind
   * rather than degrading: a wall of small multiples, one panel per
   * configuration, every panel on the scale computed once from all of them. */
  const wall = $derived(radarScores.length > MAX_SERIES)
  const radarScale = $derived(radarFloor(radarScores, origin))
  const radarOption = $derived(
    buildRadarOption(radarScores, radarSubsets, { ...chartOpts, floor: radarScale }),
  )
  // Mirrors the `named` rule in buildRadarOption: the caption has to say so.
  const radarNamed = $derived(!wall || radarSubsets.length <= 6)
  const soloOptions = $derived(
    wall
      ? radarScores.map((row) =>
          buildRadarOption([row], radarSubsets, {
            ...chartOpts,
            floor: radarScale,
            solo: true,
          }),
        )
      : [],
  )

  /* Selections travel in the URL, so a view can be sent to someone. Group
   * shorthands keep that URL short as the corpus grows: `papers=gsat,ast`
   * survives a corpus that later holds hundreds of papers, an explicit list
   * does not. */
  function encodePapers(): string {
    if (!index || paperSel.length === allPapers.length) return 'all'
    const chosen = new Set(paperSel)
    const whole = groups.filter((g) => g.subsets.every((s) => chosen.has(s)))
    const covered = new Set(whole.flatMap((g) => g.subsets))
    if (covered.size === chosen.size && whole.length) return whole.map((g) => g.exam).join(',')
    return paperSel.join(',')
  }

  /* The opening view is the papers every configuration sat.
   *
   * A taker that sat a second corpus — 統測 on top of 會考 / 學測 / 分科 — would
   * otherwise push everyone else out of the ranking on first load, because the
   * board refuses to score a configuration on a shorter exam. The shared set
   * makes the opening view a real comparison; the rest is one group toggle
   * away, and an explicit `papers=all` still means all of them.
   */
  function commonPapers(): string[] {
    const entries = index?.entries ?? []
    if (!entries.length) return allPapers
    const shared = allPapers.filter((s) => entries.every((e) => e.papers.includes(s)))
    return shared.length ? shared : allPapers
  }

  function decodePapers(raw: string | null): string[] {
    if (!index) return []
    if (!raw) return commonPapers()
    if (raw === 'all') return allPapers
    const tokens = raw.split(',').filter(Boolean)
    const out = new Set<string>()
    for (const token of tokens) {
      const group = groups.find((g) => g.exam === token)
      if (group) group.subsets.forEach((s) => out.add(s))
      else if (allPapers.includes(token)) out.add(token)
    }
    return out.size ? [...out] : allPapers
  }

  function readUrl() {
    const params = new URLSearchParams(location.search)
    repo = params.get('repo') ?? ''
    if (repo) draft = repo
    grade = params.get('grade') === 'det' ? 'det' : 'all'
    average = params.get('avg') === 'macro' ? 'macro' : 'micro'
    const x = params.get('x') as CostMetric | null
    cost = x && COST_METRICS.includes(x) ? x : 'output'
  }

  function applySelectionFromUrl() {
    const params = new URLSearchParams(location.search)
    paperSel = decodePapers(params.get('papers'))
    const raw = params.get('entries')
    const ids = (index?.entries ?? []).map((e) => e.entry_id)
    entrySel =
      !raw || raw === 'all' ? ids : raw.split(',').filter((id) => ids.includes(id))
    if (!entrySel.length) entrySel = ids
  }

  function writeUrl(replace = true) {
    if (!index) return
    const params = new URLSearchParams()
    if (repo) params.set('repo', repo)
    params.set('papers', encodePapers())
    params.set(
      'entries',
      entrySel.length === index.entries.length ? 'all' : entrySel.join(','),
    )
    if (grade !== 'all') params.set('grade', grade)
    if (average !== 'micro') params.set('avg', average)
    if (cost !== 'output') params.set('x', cost)
    const url = `${location.pathname}?${params}`
    if (replace) history.replaceState({}, '', url)
    else history.pushState({}, '', url)
  }

  async function sync() {
    const mine = ++ticket
    const current = () => mine === ticket
    failure = null
    if (!repo) {
      index = null
      return
    }
    busy = true
    try {
      const next = await loadResultsIndex(repo)
      if (!current()) return
      index = next
      loaded = {}
      applySelectionFromUrl()
      writeUrl()
    } catch (error) {
      if (!current()) return
      index = null
      failure =
        error instanceof HubError
          ? { message: error.message, hint: error.hint }
          : { message: error instanceof Error ? error.message : 'Something went wrong.' }
    } finally {
      if (current()) busy = false
    }
  }

  /** Per-paper rows are fetched only for the entries actually on screen. */
  async function fetchSelected() {
    if (!index) return
    const wanted = index.entries.filter((e) => entrySel.includes(e.entry_id) && !loaded[e.entry_id])
    if (!wanted.length) return
    loadingEntries = true
    try {
      const fetched = await Promise.all(wanted.map((e) => loadResultsEntry(repo, e)))
      const next = { ...loaded }
      wanted.forEach((e, i) => (next[e.entry_id] = fetched[i]!))
      loaded = next
    } catch (error) {
      failure =
        error instanceof HubError
          ? { message: error.message, hint: error.hint }
          : { message: error instanceof Error ? error.message : 'Something went wrong.' }
    } finally {
      loadingEntries = false
    }
  }

  function submit(event: SubmitEvent) {
    event.preventDefault()
    const next = draft.trim().replace(/^https?:\/\/huggingface\.co\/datasets\//, '')
    if (!isRepoId(next)) {
      failure = {
        message: 'That does not look like a dataset id.',
        hint: `Use the owner/name form, for example ${DEFAULT_RESULTS_REPO}.`,
      }
      return
    }
    repo = next
    index = null
    writeUrl(false)
    void sync()
  }

  function togglePaper(subset: string) {
    paperSel = paperSel.includes(subset)
      ? paperSel.filter((s) => s !== subset)
      : [...paperSel, subset]
    writeUrl()
  }

  function toggleGroup(exam: string) {
    const group = groups.find((g) => g.exam === exam)
    if (!group) return
    const whole = group.subsets.every((s) => paperSel.includes(s))
    const set = new Set(paperSel)
    group.subsets.forEach((s) => (whole ? set.delete(s) : set.add(s)))
    paperSel = [...set]
    writeUrl()
  }

  function toggleEntryGroup(model: string) {
    const group = entryGroups.find((g) => g.model === model)
    if (!group) return
    const ids = group.entries.map((e) => e.entry_id)
    const whole = ids.every((id) => entrySel.includes(id))
    const set = new Set(entrySel)
    ids.forEach((id) => (whole ? set.delete(id) : set.add(id)))
    entrySel = [...set]
    writeUrl()
    void fetchSelected()
  }

  function toggleEntry(id: string) {
    entrySel = entrySel.includes(id) ? entrySel.filter((e) => e !== id) : [...entrySel, id]
    writeUrl()
    void fetchSelected()
  }

  function narrowToCommon() {
    const common = activePapers.filter((s) =>
      scores.every((score) => !score.missing.includes(s)),
    )
    paperSel = common
    writeUrl()
  }

  type CostBasis = 'output' | 'secs'
  type CostPer = 'total' | 'question'
  const costBasis = $derived<CostBasis>(cost.startsWith('output') ? 'output' : 'secs')
  const costPer = $derived<CostPer>(cost.endsWith('-per-q') ? 'question' : 'total')

  function setCost(basis: CostBasis, per: CostPer) {
    cost = (per === 'question' ? `${basis}-per-q` : basis) as CostMetric
    writeUrl()
  }

  function setGrade(next: GradeFilter) {
    grade = next
    writeUrl()
  }

  $effect(() => {
    untrack(() => {
      readUrl()
      void sync()
    })
    const onPop = () => {
      readUrl()
      if (index) applySelectionFromUrl()
      else void sync()
    }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  })

  // Whatever is selected must be on hand; the index alone cannot score a subset.
  $effect(() => {
    entrySel.length
    void fetchSelected()
  })

  const fmtPct = (v: number | null) => (v === null ? '–' : `${fmtScore(v)}%`)
  /* The leaderboard prints its scores as a right-aligned run of tabular
     figures, and there a trimmed 95% knocks the decimal point out of line with
     the 95.2% above it — so that one column keeps a fixed decimal. Everywhere a
     score is read on its own, fmtScore still decides what it is worth showing. */
  const fmtPctFixed = (v: number | null) => (v === null ? '–' : `${v.toFixed(1)}%`)
  const fmtNum = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  /* Cost spans four orders of magnitude across the four axes, so the precision
     is chosen per column rather than fixed — but from the column's largest
     value, not each cell's, or a column of tabular figures ends up ragged. */
  const costDigits = $derived.by(() => {
    const max = Math.max(0, ...ranked.map((r) => r.cost))
    return max >= 100 ? 0 : max >= 10 ? 1 : 2
  })
  const fmtCost = (v: number) =>
    v.toLocaleString('en-US', {
      minimumFractionDigits: costDigits,
      maximumFractionDigits: costDigits,
    })

  const paretoDescription = $derived(
    ranked.length
      ? `${ranked.length} configurations over ${activePapers.length} papers. ` +
        `Scores run from ${fmtPct(ranked[ranked.length - 1]?.score ?? null)} to ` +
        `${fmtPct(ranked[0]?.score ?? null)}; the frontier holds ` +
        `${[...frontier].length} of them.`
      : 'No configuration covers every selected paper.',
  )
  const soloDescription = (row: (typeof radarScores)[number]) =>
    radarSubsets
      .map(
        (subset, i) =>
          `${radarAxisNames[i]} ${fmtPct(
            row.papers.find((paper) => paper.subset === subset)?.percentage ?? null,
          )}`,
      )
      .join(', ')

  const radarDescription = $derived(
    `Per-subject scores over ${radarSubsets.length} ${radarGrouped ? 'examinations' : 'papers'} ` +
      `for ${radarScores.length} configurations.`,
  )
</script>

<div class="min-h-screen px-4 py-6 sm:px-8 sm:py-10">
  <main class="mx-auto max-w-[82rem] space-y-6">
    <!-- ── Address bar ───────────────────────────────────────────────────── -->
    <Sheet track={false} class="px-5 py-5 sm:px-8">
      <div class="flex flex-wrap items-end justify-between gap-5">
        <div class="min-w-0 flex-1">
          <a
            href={BASE}
            class="field-label inline-flex items-center gap-1.5 hover:text-[var(--omr-graphite)]"
          >
            <ArrowLeft size={13} strokeWidth={2.5} aria-hidden="true" /> any-to-bench
          </a>
          <form onsubmit={submit} class="mt-3 flex max-w-xl items-stretch">
            <label for="repo" class="sr-only">Hugging Face results dataset id</label>
            <input
              id="repo"
              bind:value={draft}
              spellcheck="false"
              autocapitalize="off"
              autocomplete="off"
              placeholder="owner/dataset"
              class="min-w-0 flex-1 border border-[var(--omr-graphite)] bg-white/70 px-3 py-2.5
                     font-mono text-sm outline-none focus:border-[var(--omr-cinnabar)]"
            />
            <button
              type="submit"
              class="inline-flex shrink-0 items-center gap-2 border border-l-0
                     border-[var(--omr-graphite)] bg-[var(--omr-graphite)] px-4 text-sm
                     font-semibold text-[var(--omr-stock)] hover:bg-[var(--omr-cinnabar)]
                     hover:border-[var(--omr-cinnabar)]"
            >
              <Search size={15} strokeWidth={2.5} aria-hidden="true" />
              Open
            </button>
          </form>
        </div>
        {#if index}
          <div class="flex items-center gap-3">
            <a
              href={repoUrl(repo)}
              target="_blank"
              rel="noreferrer"
              class="field-label inline-flex items-center gap-1.5 hover:text-[var(--omr-graphite)]"
            >
              On the Hub <ExternalLink size={12} strokeWidth={2.5} aria-hidden="true" />
            </a>
          </div>
        {/if}
      </div>
    </Sheet>

    {#if failure}
      <Sheet track={false} class="px-6 py-8 sm:px-10">
        <div class="flex gap-4">
          <TriangleAlert
            size={22}
            strokeWidth={2}
            class="mt-0.5 shrink-0 text-[var(--omr-cinnabar)]"
            aria-hidden="true"
          />
          <div>
            <p class="text-lg font-semibold text-[var(--omr-graphite)]">{failure.message}</p>
            {#if failure.hint}
              <p class="mt-2 max-w-[62ch] leading-relaxed text-[var(--omr-graphite-soft)]">
                {failure.hint}
              </p>
            {/if}
          </div>
        </div>
      </Sheet>
    {/if}

    {#if busy}
      <Sheet track={false} class="px-6 py-10 sm:px-10">
        <p class="flex items-center gap-3 text-[var(--omr-graphite-soft)]">
          <Loader size={18} class="spin" strokeWidth={2} aria-hidden="true" />
          Reading the leaderboard in {repo}…
        </p>
      </Sheet>
    {:else if !repo || !index}
      <!-- ── First run ──────────────────────────────────────────────────── -->
      <Sheet class="px-6 py-10 sm:px-12 sm:py-14 lg:px-16">
        <h1
          class="max-w-[20ch] text-[clamp(2.1rem,5vw,3.6rem)] leading-[1] font-extrabold
                 tracking-[-0.035em] text-balance text-[var(--omr-graphite)]"
        >
          Scores, over exactly the papers you choose.
        </h1>
        <p class="mt-6 max-w-[62ch] text-lg leading-relaxed text-[var(--omr-graphite-soft)]">
          Name a results dataset above and this page reads it straight from the repo: every
          configuration that sat the papers, what each one earned, and what it spent getting there.
          Pick the subjects, decide whether judged questions count, and the table and charts follow.
        </p>
        <button
          type="button"
          onclick={() => {
            draft = DEFAULT_RESULTS_REPO
            repo = DEFAULT_RESULTS_REPO
            writeUrl(false)
            void sync()
          }}
          class="group mt-9 inline-flex items-center gap-3 bg-[var(--omr-cinnabar)] px-6 py-3.5
                 font-semibold text-white transition-colors hover:bg-[#b92c20]"
        >
          Start with {DEFAULT_RESULTS_REPO}
        </button>
      </Sheet>
    {:else}
      <!-- `min-w-0` on both columns: a grid item's default `min-width: auto`
           refuses to shrink below its content, and the board table is 44rem
           wide by design. Without it that table sets the page's width and the
           whole document scrolls sideways on a phone — the `overflow-x-auto`
           around it never gets the chance to do its job. -->
      <div class="grid gap-6 lg:grid-cols-[17rem_1fr]">
        <!-- ── What the marks are counted over ───────────────────────────── -->
        <!-- Padding clears the registration marks: they occupy the first 28px of
             the corner, and a field label set inside that lands underneath one. -->
        <aside
          class="min-w-0 space-y-6 lg:sticky lg:top-6 lg:-mx-5 lg:max-h-[calc(100vh-3rem)] lg:self-start
                 lg:overflow-y-auto lg:overscroll-contain lg:px-5 lg:pb-6"
        >
          <Sheet track={false} class="px-5 pt-8 pb-6">
            <p class="field-label">Counted</p>
            <div class="mt-3 grid grid-cols-2 gap-px bg-[var(--omr-dropout-soft)]">
              {#each [['all', 'Every question'], ['det', 'Rule-graded only']] as [value, label] (value)}
                <button
                  type="button"
                  onclick={() => setGrade(value as GradeFilter)}
                  aria-pressed={grade === value}
                  class="bg-[var(--omr-stock)] px-2 py-2 text-xs font-semibold
                         text-[var(--omr-graphite-soft)] transition-colors"
                  class:on={grade === value}
                >
                  {label}
                </button>
              {/each}
            </div>
            <p class="mt-2 text-xs leading-relaxed text-[var(--omr-graphite-soft)]">
              Judged points depend on the judge model, which differs between entries. Rule-graded
              points are scored by program and always compare.
            </p>

            <p class="field-label mt-5">Averaged</p>
            <div class="mt-3 grid grid-cols-2 gap-px bg-[var(--omr-dropout-soft)]">
              {#each [['micro', 'By points'], ['macro', 'By paper']] as [value, label] (value)}
                <button
                  type="button"
                  onclick={() => {
                    average = value as Average
                    writeUrl()
                  }}
                  aria-pressed={average === value}
                  class="bg-[var(--omr-stock)] px-2 py-2 text-xs font-semibold
                         text-[var(--omr-graphite-soft)] transition-colors"
                  class:on={average === value}
                >
                  {label}
                </button>
              {/each}
            </div>

            <p class="field-label mt-5">Cost axis</p>
            <div class="mt-3 grid grid-cols-2 gap-px bg-[var(--omr-dropout-soft)]">
              {#each [['output', 'Output tokens'], ['secs', 'Seconds']] as [value, label] (value)}
                <button
                  type="button"
                  onclick={() => setCost(value as CostBasis, costPer)}
                  aria-pressed={costBasis === value}
                  class="bg-[var(--omr-stock)] px-2 py-2 text-xs font-semibold
                         text-[var(--omr-graphite-soft)] transition-colors"
                  class:on={costBasis === value}
                >
                  {label}
                </button>
              {/each}
            </div>
            <div class="mt-px grid grid-cols-2 gap-px bg-[var(--omr-dropout-soft)]">
              {#each [['total', 'Total'], ['question', 'Per question']] as [value, label] (value)}
                <button
                  type="button"
                  onclick={() => setCost(costBasis, value as CostPer)}
                  aria-pressed={costPer === value}
                  class="bg-[var(--omr-stock)] px-2 py-2 text-xs font-semibold
                         text-[var(--omr-graphite-soft)] transition-colors"
                  class:on={costPer === value}
                >
                  {label}
                </button>
              {/each}
            </div>
            <p class="mt-2 text-xs leading-relaxed text-[var(--omr-graphite-soft)]">
              A total is what this selection cost; a per-question figure is what the taker costs
              to run, and carries to a paper nobody here has sat. Both divide by every question
              asked, judged half included, whatever the grade filter counts.
            </p>
          </Sheet>

          <!-- ── Which papers ─────────────────────────────────────────────── -->
          <Sheet track={false} class="px-5 pt-8 pb-6">
            <button
              type="button"
              onclick={() => (papersOpen = !papersOpen)}
              aria-expanded={papersOpen}
              aria-controls="papers-list"
              class="flex w-full items-center gap-2 text-left"
            >
              <ChevronRight
                size={13}
                strokeWidth={2.5}
                class="shrink-0 text-[var(--omr-dropout-ink)] transition-transform"
                style={papersOpen ? 'transform: rotate(90deg)' : ''}
                aria-hidden="true"
              />
              <span class="field-label flex-1">Papers</span>
              <span class="font-mono text-xs text-[var(--omr-graphite-soft)]">
                {activePapers.length}/{allPapers.length}
              </span>
            </button>
            {#if papersOpen}
              <div id="papers-list">
                {#each groups as group (group.exam)}
                  <div class="mt-4">
                    <button
                      type="button"
                      onclick={() => toggleGroup(group.exam)}
                      class="flex w-full items-baseline gap-2 text-left
                             hover:text-[var(--omr-cinnabar-ink)]"
                      title="Select or clear every {group.exam} paper"
                    >
                      <span class="field-label flex-1">{group.exam}</span>
                      <span class="font-mono text-[0.6875rem] text-[var(--omr-graphite-soft)]">
                        {group.subsets.filter((s) => paperSel.includes(s)).length}/{group.subsets
                          .length}
                      </span>
                    </button>
                    <ul class="mt-1.5 space-y-1">
                      {#each group.subsets as subset (subset)}
                        <li>
                          <button
                            type="button"
                            onclick={() => togglePaper(subset)}
                            aria-pressed={paperSel.includes(subset)}
                            class="row"
                            class:picked={paperSel.includes(subset)}
                          >
                            <Mark size="sm" filled={paperSel.includes(subset)} />
                            <span class="font-mono text-xs">{shortSubject(subset)}</span>
                          </button>
                        </li>
                      {/each}
                    </ul>
                  </div>
                {/each}
              </div>
            {/if}
          </Sheet>

          <!-- ── Which configurations ─────────────────────────────────────── -->
          <Sheet track={false} class="px-5 pt-8 pb-6">
            <button
              type="button"
              onclick={() => (entriesOpen = !entriesOpen)}
              aria-expanded={entriesOpen}
              aria-controls="entries-list"
              class="flex w-full items-center gap-2 text-left"
            >
              <ChevronRight
                size={13}
                strokeWidth={2.5}
                class="shrink-0 text-[var(--omr-dropout-ink)] transition-transform"
                style={entriesOpen ? 'transform: rotate(90deg)' : ''}
                aria-hidden="true"
              />
              <span class="field-label flex-1">Configurations</span>
              <span class="font-mono text-xs text-[var(--omr-graphite-soft)]">
                {entrySel.length}/{index.entries.length}
              </span>
            </button>
            {#if entriesOpen}
              <div id="entries-list">
                {#each entryGroups as group (group.model)}
                  <div class="mt-4">
                    <button
                      type="button"
                      onclick={() => toggleEntryGroup(group.model)}
                      class="flex w-full items-baseline gap-2 text-left
                             hover:text-[var(--omr-cinnabar-ink)]"
                      title="Select or clear every {group.model} run"
                    >
                      <span
                        class="min-w-0 flex-1 truncate font-mono text-[0.6875rem] font-semibold
                               text-[var(--omr-dropout-ink)]">{modelName(group.model)}</span
                      >
                      <span class="font-mono text-[0.6875rem] text-[var(--omr-graphite-soft)]">
                        {group.entries.filter((e) => entrySel.includes(e.entry_id))
                          .length}/{group.entries.length}
                      </span>
                    </button>
                    <ul class="mt-1.5 space-y-1">
                      {#each group.entries as entry (entry.entry_id)}
                        <li>
                          <button
                            type="button"
                            onclick={() => toggleEntry(entry.entry_id)}
                            aria-pressed={entrySel.includes(entry.entry_id)}
                            class="row"
                            class:picked={entrySel.includes(entry.entry_id)}
                          >
                            <Mark size="sm" filled={entrySel.includes(entry.entry_id)} />
                            <span class="font-mono text-xs">{effortLabel(entry.effort)}</span>
                          </button>
                        </li>
                      {/each}
                    </ul>
                  </div>
                {/each}
              </div>
            {/if}
          </Sheet>
        </aside>

        <div class="min-w-0 space-y-6">
          <!-- ── The board ─────────────────────────────────────────────── -->
          <Sheet class="px-6 py-7 sm:px-10">
            <div class="flex flex-wrap items-baseline justify-between gap-3">
              <h1
                class="text-[clamp(1.6rem,3vw,2.4rem)] leading-[1.05] font-bold
                       tracking-[-0.03em] text-[var(--omr-graphite)]"
              >
                {activePapers.length} paper{activePapers.length === 1 ? '' : 's'},
                {ranked.length} configuration{ranked.length === 1 ? '' : 's'}
              </h1>
              {#if loadingEntries}
                <p class="flex items-center gap-2 font-mono text-xs text-[var(--omr-graphite-soft)]">
                  <Loader size={13} class="spin" strokeWidth={2} aria-hidden="true" /> reading
                </p>
              {/if}
            </div>

            {#if excluded.length}
              <p class="mt-4 max-w-[70ch] text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
                {excluded.length} selected configuration{excluded.length === 1 ? '' : 's'} did not
                sit every chosen paper, so {excluded.length === 1 ? 'it is' : 'they are'} left out of
                the ranking rather than scored on a shorter exam.
                <button
                  type="button"
                  onclick={narrowToCommon}
                  class="underline decoration-[var(--omr-dropout-ink)] underline-offset-4
                         hover:text-[var(--omr-graphite)]"
                >
                  Narrow the papers to the common set
                </button>.
              </p>
            {/if}

            {#if dropped.length}
              <p class="mt-4 max-w-[70ch] text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
                Rule-graded only drops {dropped.length} paper{dropped.length === 1 ? '' : 's'} with
                no rule-graded question at all —
                <span class="font-mono">{dropped.map((p) => p.subset).join(', ')}</span>, worth
                {fmtNum(dropped.reduce((t, p) => t + p.total_points, 0))} points. They are out of
                every figure below.
              </p>
            {/if}

            <div class="mt-6 overflow-x-auto">
              <table class="w-full min-w-[44rem] border-collapse text-left">
                <caption class="sr-only">
                  Configurations ranked over the selected papers
                </caption>
                <thead>
                  <tr class="border-b-2 border-[var(--omr-graphite)]">
                    <th scope="col" class="field-label pb-2">#</th>
                    <th scope="col" class="field-label pb-2">Model</th>
                    <th scope="col" class="field-label pb-2">Effort</th>
                    <th scope="col" class="field-label pb-2 text-right">Score</th>
                    <th scope="col" class="field-label pb-2 text-right">
                      {average === 'micro' ? 'By points' : 'By paper'}
                    </th>
                    <th scope="col" class="field-label pb-2 text-right">{COST_LABEL[cost]}</th>
                    {#if resourceBacked}
                      <th scope="col" class="field-label pb-2 text-right">Resources</th>
                      <th scope="col" class="field-label pb-2 text-right">Citations</th>
                    {/if}
                    <th scope="col" class="field-label pb-2 text-right">Frontier</th>
                  </tr>
                </thead>
                <tbody>
                  {#each ranked as row, i (row.entry.entry_id)}
                    <tr class="border-b border-[var(--omr-dropout-soft)]">
                      <td class="py-3 pr-3 font-mono text-sm tabular-nums">
                        {String(i + 1).padStart(2, '0')}
                      </td>
                      <th
                        scope="row"
                        class="py-3 pr-4 font-mono text-sm font-normal"
                        title={row.entry.model}
                      >
                        {modelName(row.entry.model)}
                      </th>
                      <td class="py-3 pr-4 text-sm text-[var(--omr-graphite-soft)]">
                        {effortLabel(row.entry.effort)}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                        {row.awarded.toFixed(1)}/{fmtScore(row.coveredMax)}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono tabular-nums">
                        {fmtPctFixed(row.score)}{#if row.spread !== null}<span
                            class="text-[var(--omr-graphite-soft)]"
                          >
                            ± {fmtScore(row.spread)}</span
                          >{/if}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                        {fmtCost(row.cost)}
                      </td>
                      {#if resourceBacked}
                        <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                          {row.resourceFiles ? `${row.resourceExposedFiles}/${row.resourceFiles}` : '—'}
                        </td>
                        <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                          {row.citationsSubmitted
                            ? `${row.citationsVerified}v/${row.citationsSubmitted}${
                                row.citationsUnverifiable
                                  ? ` · ${row.citationsUnverifiable} binary`
                                  : ''
                              }`
                            : '—'}
                        </td>
                      {/if}
                      <td class="py-3 text-right font-mono text-sm">
                        {frontier.has(row.entry.entry_id) ? '●' : ''}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>

            <p class="mt-5 max-w-[74ch] text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
              {#if repeated}
                Spreads are sample standard deviations over repeated runs.
              {:else}
                One run per paper: the run-to-run spread of these numbers is unknown, so treat small
                gaps as unresolved.
              {/if}
              Cost counts the taker only — a judge's tokens are the judge's, and they would move
              this axis every time you tick a paper.
            </p>
          </Sheet>

          <!-- ── Cost against score ────────────────────────────────────── -->
          <Sheet class="px-6 py-7 sm:px-10">
            <div class="flex flex-wrap items-baseline justify-between gap-3">
              <h2 class="text-xl font-bold tracking-[-0.02em] text-[var(--omr-graphite)]">
                What each score cost
              </h2>
              <button
                type="button"
                onclick={() => (origin = origin === 'zoom' ? 'zero' : 'zoom')}
                aria-pressed={origin === 'zero'}
                class="field-label hover:text-[var(--omr-graphite)]"
              >
                {origin === 'zoom' ? 'Show from zero' : 'Zoom to the scores'}
              </button>
            </div>
            <p class="mt-2 max-w-[70ch] text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
              One line per model, its points ordered along the effort dial and its ends named. The
              heavy step line is the frontier: everything below and right of it is beaten on both
              axes at once. Every point's exact effort is in the table below.
            </p>
            {#if ranked.length}
              <div class="mt-5">
                <EChart
                  option={paretoOption}
                  label="Score against cost for every selected configuration"
                  description={paretoDescription}
                />
              </div>
              <details class="mt-3">
                <summary class="field-label cursor-pointer">Read as a table</summary>
                <div class="mt-3 overflow-x-auto">
                  <table class="w-full min-w-[30rem] border-collapse text-left">
                    <thead>
                      <tr class="border-b-2 border-[var(--omr-graphite)]">
                        <th scope="col" class="field-label pb-2">Configuration</th>
                        <th scope="col" class="field-label pb-2 text-right">Score</th>
                        <th scope="col" class="field-label pb-2 text-right">{COST_LABEL[cost]}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each ranked as row (row.entry.entry_id)}
                        <tr class="border-b border-[var(--omr-dropout-soft)]">
                          <th scope="row" class="py-2 pr-4 font-mono text-xs font-normal">
                            {modelName(row.entry.model)} · {effortLabel(row.entry.effort)}
                          </th>
                          <td class="py-2 pr-4 text-right font-mono text-xs tabular-nums">
                            {fmtPct(row.score)}
                          </td>
                          <td class="py-2 text-right font-mono text-xs tabular-nums">
                            {fmtCost(row.cost)}
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </details>
            {/if}
          </Sheet>

          <!-- ── Shape across the corpus ───────────────────────────────── -->
          <Sheet class="px-6 py-7 sm:px-10">
            <div class="flex flex-wrap items-baseline justify-between gap-3">
              <h2 class="text-xl font-bold tracking-[-0.02em] text-[var(--omr-graphite)]">
                Where the marks fall
              </h2>
              <div class="flex items-center gap-4">
                {#if radarHidden > 0 || radarAll}
                  <button
                    type="button"
                    onclick={() => (radarAll = !radarAll)}
                    aria-pressed={radarAll}
                    class="field-label hover:text-[var(--omr-graphite)]"
                  >
                    {radarAll ? `Top ${MAX_SERIES} only` : `All ${ranked.length}`}
                  </button>
                {/if}
                {#if groups.length > 1 && activePapers.length > groups.length}
                  <button
                    type="button"
                    onclick={() => (grouped = !grouped)}
                    aria-pressed={grouped}
                    class="field-label hover:text-[var(--omr-graphite)]"
                  >
                    {radarGrouped ? 'One axis per paper' : 'Group by examination'}
                  </button>
                {/if}
              </div>
            </div>
            <p class="mt-2 max-w-[70ch] text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
              Each reasoning effort is its own outline. Area is not a score, and the shape depends
              on the order of the axes — read the vertices, not the size.
              {#if wall}
                Outlines are told apart by rule alone and there are only four rules, so past four
                configurations this becomes one panel each, every panel on the same rings and the
                same axes in the same order.{#if !radarNamed}{' '}The axes are unlabelled at this
                  size; the table below names them.{/if}
              {:else if radarHidden > 0}
                Outlines are told apart by rule alone, and past four they stop being
                distinguishable, so the chart shows the leading {MAX_SERIES} and the table below
                carries all {ranked.length}.{/if}
            </p>
            {#if ranked.length}
              {#if wall}
                <div class="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 xl:grid-cols-4">
                  {#each radarScores as row, i (row.entry.entry_id)}
                    <div class="min-w-0">
                      <EChart
                        option={soloOptions[i]!}
                        height={radarNamed ? '10rem' : '9rem'}
                        label="Per-subject scores for {entryLabel(row.entry)}"
                        description={soloDescription(row)}
                      />
                      <p
                        class="-mt-1 truncate text-center font-mono text-[0.6875rem]
                               text-[var(--omr-graphite)]"
                        title={entryLabel(row.entry)}
                      >
                        {modelName(row.entry.model)}
                      </p>
                      <p
                        class="truncate text-center font-mono text-[0.6875rem]
                               text-[var(--omr-graphite-soft)]"
                      >
                        {effortLabel(row.entry.effort)} · {fmtPct(row.score)}
                      </p>
                    </div>
                  {/each}
                </div>
              {:else}
                <div class="mt-5">
                  <EChart
                    option={radarOption}
                    height="30rem"
                    label="Per-subject scores for every selected configuration"
                    description={radarDescription}
                  />
                </div>
              {/if}
              <details class="mt-3">
                <summary class="field-label cursor-pointer">Read as a table</summary>
                <div class="mt-3 overflow-x-auto">
                  <table class="w-full min-w-[36rem] border-collapse text-left">
                    <thead>
                      <tr class="border-b-2 border-[var(--omr-graphite)]">
                        <th scope="col" class="field-label pb-2">Configuration</th>
                        {#each radarSubsets as subset, i (subset)}
                          <th scope="col" class="field-label pb-2 text-right">
                            {radarAxisNames[i]}
                          </th>
                        {/each}
                      </tr>
                    </thead>
                    <tbody>
                      {#each radarScores as row (row.entry.entry_id)}
                        <tr class="border-b border-[var(--omr-dropout-soft)]">
                          <th scope="row" class="py-2 pr-4 font-mono text-xs font-normal">
                            {modelName(row.entry.model)} · {effortLabel(row.entry.effort)}
                          </th>
                          {#each radarSubsets as subset (subset)}
                            <td class="py-2 pr-3 text-right font-mono text-xs tabular-nums">
                              {fmtPct(
                                row.papers.find((paper) => paper.subset === subset)?.percentage ??
                                  null,
                              )}
                            </td>
                          {/each}
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </details>
            {/if}
          </Sheet>

        </div>
      </div>
    {/if}
  </main>
</div>

<style>
  /* Selection is a filled square, not a font weight. Reading a list by boldness
     means holding the unselected rows in your head to have something to compare
     against; a mark is either filled or it is not, and a whole column of them
     answers "what is on?" without reading a single word. */
  .row {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 0.5rem;
    text-align: left;
    color: var(--omr-graphite-soft);
    transition: color 150ms ease-out;
  }
  .row.picked {
    color: var(--omr-graphite);
  }
  .row:hover {
    color: var(--omr-cinnabar-ink);
  }
  .on {
    background: var(--omr-graphite);
    color: var(--omr-stock);
  }
</style>
