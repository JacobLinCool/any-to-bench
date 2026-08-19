<script lang="ts">
  import { untrack } from 'svelte'
  import { ArrowLeft, ExternalLink, Loader, Search, TriangleAlert } from '@lucide/svelte'
  import EChart from './lib/EChart.svelte'
  import ScannerToggle from './lib/ScannerToggle.svelte'
  import Sheet from './lib/Sheet.svelte'
  import { buildParetoOption, buildRadarOption } from './lib/charts/options'
  import { MAX_SERIES } from './lib/charts/theme'
  import { scanner } from './lib/scanner.svelte'
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
    byModel,
    droppedByFilter,
    effortLabel,
    axisNames,
    examGroups,
    groupByExam,
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
  const chartOpts = $derived({ cost, average, origin, scanning: scanner.on })
  const paretoOption = $derived(buildParetoOption(ranked, chartOpts))
  const radarOption = $derived(buildRadarOption(radarScores, radarSubsets, chartOpts))

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

  function decodePapers(raw: string | null): string[] {
    if (!index) return []
    if (!raw || raw === 'all') return allPapers
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
    cost = params.get('x') === 'secs' ? 'secs' : 'output'
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

  const fmtPct = (v: number | null) => (v === null ? '–' : `${v.toFixed(1)}%`)
  const fmtNum = (v: number) => v.toLocaleString('en-US', { maximumFractionDigits: 0 })

  const paretoDescription = $derived(
    ranked.length
      ? `${ranked.length} configurations over ${activePapers.length} papers. ` +
        `Scores run from ${fmtPct(ranked[ranked.length - 1]?.score ?? null)} to ` +
        `${fmtPct(ranked[0]?.score ?? null)}; the frontier holds ` +
        `${[...frontier].length} of them.`
      : 'No configuration covers every selected paper.',
  )
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
            <ScannerToggle />
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
      <div class="grid gap-6 lg:grid-cols-[17rem_1fr]">
        <!-- ── What the marks are counted over ───────────────────────────── -->
        <aside class="space-y-6 lg:sticky lg:top-6 lg:self-start">
          <Sheet track={false} class="px-4 py-5">
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
                  onclick={() => {
                    cost = value as CostMetric
                    writeUrl()
                  }}
                  aria-pressed={cost === value}
                  class="bg-[var(--omr-stock)] px-2 py-2 text-xs font-semibold
                         text-[var(--omr-graphite-soft)] transition-colors"
                  class:on={cost === value}
                >
                  {label}
                </button>
              {/each}
            </div>
          </Sheet>

          <Sheet track={false} class="px-4 py-5">
            <div class="flex items-baseline justify-between">
              <p class="field-label">Papers</p>
              <p class="font-mono text-xs text-[var(--omr-graphite-soft)]">
                {activePapers.length}/{allPapers.length}
              </p>
            </div>
            {#each groups as group (group.exam)}
              <div class="mt-4">
                <button
                  type="button"
                  onclick={() => toggleGroup(group.exam)}
                  class="field-label hover:text-[var(--omr-graphite)]"
                >
                  {group.exam} ({group.subsets.length})
                </button>
                <ul class="mt-1.5 space-y-0.5">
                  {#each group.subsets as subset (subset)}
                    <li>
                      <button
                        type="button"
                        onclick={() => togglePaper(subset)}
                        aria-pressed={paperSel.includes(subset)}
                        class="w-full text-left font-mono text-xs transition-colors"
                        class:picked={paperSel.includes(subset)}
                        class:unpicked={!paperSel.includes(subset)}
                      >
                        {shortSubject(subset)}
                      </button>
                    </li>
                  {/each}
                </ul>
              </div>
            {/each}
          </Sheet>
        </aside>

        <div class="space-y-6">
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
                    <th scope="col" class="field-label pb-2 text-right">Frontier</th>
                  </tr>
                </thead>
                <tbody>
                  {#each ranked as row, i (row.entry.entry_id)}
                    <tr class="border-b border-[var(--omr-dropout-soft)]">
                      <td class="py-3 pr-3 font-mono text-sm tabular-nums">
                        {String(i + 1).padStart(2, '0')}
                      </td>
                      <th scope="row" class="py-3 pr-4 font-mono text-sm font-normal">
                        {row.entry.model}
                      </th>
                      <td class="py-3 pr-4 text-sm text-[var(--omr-graphite-soft)]">
                        {effortLabel(row.entry.effort)}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                        {row.awarded.toFixed(1)}/{row.coveredMax.toFixed(0)}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono tabular-nums">
                        {fmtPct(row.score)}{#if row.spread !== null}<span
                            class="text-[var(--omr-graphite-soft)]"
                          >
                            ± {row.spread.toFixed(1)}</span
                          >{/if}
                      </td>
                      <td class="py-3 pr-4 text-right font-mono text-sm tabular-nums">
                        {fmtNum(row.cost)}
                      </td>
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
                            {row.entry.model} · {effortLabel(row.entry.effort)}
                          </th>
                          <td class="py-2 pr-4 text-right font-mono text-xs tabular-nums">
                            {fmtPct(row.score)}
                          </td>
                          <td class="py-2 text-right font-mono text-xs tabular-nums">
                            {fmtNum(row.cost)}
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
              {#if radarHidden > 0}
                Outlines are told apart by rule alone, and past four they stop being
                distinguishable, so the chart shows the leading {MAX_SERIES} and the table below
                carries all {ranked.length}.{/if}
            </p>
            {#if ranked.length}
              <div class="mt-5">
                <EChart
                  option={radarOption}
                  height="30rem"
                  label="Per-subject scores for every selected configuration"
                  description={radarDescription}
                />
              </div>
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
                            {row.entry.model} · {effortLabel(row.entry.effort)}
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

          <!-- ── Which configurations are being compared ───────────────── -->
          <Sheet track={false} class="px-6 py-6 sm:px-10">
            <p class="field-label">Configurations</p>
            <ul class="mt-3 grid gap-x-8 gap-y-1 sm:grid-cols-2">
              {#each index.entries as entry (entry.entry_id)}
                <li>
                  <button
                    type="button"
                    onclick={() => toggleEntry(entry.entry_id)}
                    aria-pressed={entrySel.includes(entry.entry_id)}
                    class="w-full text-left font-mono text-xs transition-colors"
                    class:picked={entrySel.includes(entry.entry_id)}
                    class:unpicked={!entrySel.includes(entry.entry_id)}
                  >
                    {entry.model} · {effortLabel(entry.effort)}
                  </button>
                </li>
              {/each}
            </ul>
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
            {#if families.length}
              <p class="mt-3 font-mono text-xs text-[var(--omr-graphite-soft)]">
                {families.map((f) => `${f.model} ×${f.scores.length}`).join('   ')}
              </p>
            {/if}
          </Sheet>
        </div>
      </div>
    {/if}
  </main>
</div>

<style>
  /* The picked/unpicked pair is this page's mark: a chosen row is graphite on
     stock, an unchosen one is drop-out furniture that the scanner ignores. */
  .picked {
    color: var(--omr-graphite);
    font-weight: 600;
  }
  .unpicked {
    color: var(--omr-dropout-ink);
  }
  .picked:hover,
  .unpicked:hover {
    color: var(--omr-cinnabar-ink);
  }
  .on {
    background: var(--omr-graphite);
    color: var(--omr-stock);
  }
</style>
