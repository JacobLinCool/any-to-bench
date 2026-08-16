<script lang="ts">
  import { untrack } from 'svelte'
  import { ArrowLeft, ExternalLink, Loader, Search, TriangleAlert } from '@lucide/svelte'
  import Blocks from './lib/Blocks.svelte'
  import Mark from './lib/Mark.svelte'
  import QuestionCard from './lib/QuestionCard.svelte'
  import ScannerToggle from './lib/ScannerToggle.svelte'
  import Sheet from './lib/Sheet.svelte'
  import { examLeaves, isDeterministic, stats, type Bundle, type Question } from './lib/bundle'
  import { DEFAULT_REPO, HubError, isRepoId, listSubsets, loadBundle, repoUrl } from './lib/hf'

  const BASE = import.meta.env.BASE_URL

  let repo = $state('')
  let subset = $state('')
  let draft = $state(DEFAULT_REPO)

  let subsets = $state<string[] | null>(null)
  let bundle = $state<Bundle | null>(null)
  let busy = $state(false)
  let failure = $state<{ message: string; hint?: string } | null>(null)
  let filter = $state('')
  let revealed = $state(false)
  let activeId = $state('')
  // Only the newest request may write state: a stale rejection must never land
  // on top of a good result.
  let ticket = 0

  const shown = $derived(
    (subsets ?? []).filter((s) => s.toLowerCase().includes(filter.trim().toLowerCase())),
  )

  /* A register is ordered and sectioned, not a flat wall of stubs. a2b names a
   * bundle <exam>-<year>-<subject>, so the first two segments are real structure
   * we already have without fetching 164 files. Any repo whose names do not
   * follow that convention falls back to one ungrouped section, because this
   * viewer must open anyone's dataset, not only ours. */
  const NAMED = /^([A-Za-z]+)-(\d{2,4})-/
  const groups = $derived.by(() => {
    const buckets = new Map<string, string[]>()
    for (const name of subsets ?? []) {
      const m = NAMED.exec(name)
      const key = m ? `${m[1]} ${m[2]}` : ''
      const list = buckets.get(key) ?? []
      list.push(name)
      buckets.set(key, list)
    }
    const keep = new Set(shown)
    const named = [...buckets.keys()].filter(Boolean).length
    const sections =
      named < 2
        ? [{ title: '', items: subsets ?? [] }]
        : [...buckets.entries()]
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([title, items]) => ({ title: title || 'Other', items }))
    // Number every stub against its full section, then hide what the filter
    // excludes: a stub's number must not change as you type.
    return sections
      .map((section) => ({
        title: section.title,
        total: section.items.length,
        items: section.items
          .map((name, i) => ({ name, no: String(i + 1).padStart(2, '0') }))
          .filter((row) => keep.has(row.name)),
      }))
      .filter((section) => section.items.length > 0)
  })
  const summary = $derived(bundle ? stats(bundle) : null)
  const rows = $derived(bundle ? examLeaves(bundle.exam) : [])

  function readUrl() {
    const params = new URLSearchParams(location.search)
    repo = params.get('repo') ?? ''
    subset = params.get('subset') ?? ''
    if (repo) draft = repo
  }

  function writeUrl(next: { repo?: string; subset?: string }, replace = false) {
    const params = new URLSearchParams()
    if (next.repo) params.set('repo', next.repo)
    if (next.subset) params.set('subset', next.subset)
    const url = `${location.pathname}${params.toString() ? `?${params}` : ''}`
    if (replace) history.replaceState({}, '', url)
    else history.pushState({}, '', url)
  }

  async function sync() {
    const mine = ++ticket
    const current = () => mine === ticket
    failure = null
    if (!repo) {
      subsets = null
      bundle = null
      return
    }
    busy = true
    try {
      if (!subsets || !bundle || bundle.name !== subset) {
        subsets = await listSubsets(repo)
        if (subset && !subsets.includes(subset)) {
          throw new HubError(
            `${repo} has no bundle named "${subset}".`,
            `It publishes ${subsets.length} others — pick one from the register.`,
          )
        }
        // A repo holding exactly one bundle opens straight into it.
        if (!subset && subsets.length === 1) {
          subset = subsets[0]!
          writeUrl({ repo, subset }, true)
        }
      }
      const next = subset ? await loadBundle(repo, subset) : null
      if (!current()) return
      bundle = next
      revealed = false
      activeId = ''
    } catch (error) {
      if (!current()) return
      bundle = null
      failure =
        error instanceof HubError
          ? { message: error.message, hint: error.hint }
          : { message: error instanceof Error ? error.message : 'Something went wrong.' }
      if (!(error instanceof HubError) || !subsets) subsets = null
    } finally {
      if (current()) busy = false
    }
  }

  function open(name: string) {
    subset = name
    writeUrl({ repo, subset: name })
    void sync()
  }

  function back() {
    subset = ''
    bundle = null
    writeUrl({ repo })
  }

  function submit(event: SubmitEvent) {
    event.preventDefault()
    const next = draft.trim().replace(/^https?:\/\/huggingface\.co\/datasets\//, '')
    if (!isRepoId(next)) {
      failure = {
        message: 'That does not look like a dataset id.',
        hint: 'Use the owner/name form, for example JacobLinCool/taiwan-exams.',
      }
      return
    }
    repo = next
    subset = ''
    subsets = null
    bundle = null
    writeUrl({ repo })
    void sync()
  }

  $effect(() => {
    untrack(() => {
      readUrl()
      void sync()
    })
    const onPop = () => {
      readUrl()
      void sync()
    }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  })

  // The travelling band: which question the reader is inside.
  $effect(() => {
    if (!bundle) return
    const observer = new IntersectionObserver(
      (entries) => {
        const hit = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
        if (hit) activeId = hit.target.id.replace(/^q-/, '')
      },
      { rootMargin: '-88px 0px -55% 0px' },
    )
    for (const node of document.querySelectorAll('[id^="q-"]')) observer.observe(node)
    return () => observer.disconnect()
  })

  function jump(id: string) {
    document.getElementById(`q-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function ruleOf(q: Question) {
    return bundle?.grading.questions[q.id]?.rule
  }
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
            <label for="repo" class="sr-only">Hugging Face dataset id</label>
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
        {#if bundle}
          <div class="flex items-center gap-3">
            <ScannerToggle />
            <button
              type="button"
              onclick={() => (revealed = !revealed)}
              aria-pressed={revealed}
              class="border px-3.5 py-2 text-[0.6875rem] font-semibold tracking-[0.14em] uppercase
                     transition-colors"
              class:sealed={!revealed}
              class:broken={revealed}
            >
              {revealed ? 'Key shown' : 'Break the seal'}
            </button>
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
          Reading {subset ? `${subset} from ${repo}` : repo}…
        </p>
      </Sheet>
    {:else if !repo}
      <!-- ── First run ──────────────────────────────────────────────────── -->
      <Sheet class="px-6 py-10 sm:px-12 sm:py-14 lg:px-16">
        <h1
          class="max-w-[18ch] text-[clamp(2.1rem,5vw,3.6rem)] leading-[1] font-extrabold
                 tracking-[-0.035em] text-balance text-[var(--omr-graphite)]"
        >
          Open any bundle a2b has published.
        </h1>
        <p class="mt-6 max-w-[62ch] text-lg leading-relaxed text-[var(--omr-graphite-soft)]">
          Name a Hugging Face dataset above and this page reads its bundles straight from the repo —
          the paper as it was issued, its figures, and the grading rules behind every question. It
          runs entirely in your browser, so it can open any public dataset, not only ours.
        </p>
        <button
          type="button"
          onclick={() => {
            draft = DEFAULT_REPO
            repo = DEFAULT_REPO
            writeUrl({ repo })
            void sync()
          }}
          class="group mt-9 inline-flex items-center gap-3 bg-[var(--omr-cinnabar)] px-6 py-3.5
                 font-semibold text-white transition-colors hover:bg-[#b92c20]"
        >
          Start with {DEFAULT_REPO}
        </button>
      </Sheet>
    {:else if bundle && summary}
      <!-- ── The reading surface ────────────────────────────────────────── -->
      <div class="grid gap-6 lg:grid-cols-[15rem_1fr]">
        <!-- the answer card, doubling as the way through the paper -->
        <aside class="lg:sticky lg:top-6 lg:self-start">
          <Sheet track={false} class="px-4 py-5">
            <button
              type="button"
              onclick={back}
              class="field-label mb-4 inline-flex items-center gap-1.5 hover:text-[var(--omr-graphite)]"
            >
              <ArrowLeft size={13} strokeWidth={2.5} aria-hidden="true" /> All bundles
            </button>
            <p class="mb-1 font-mono text-sm break-all">{bundle.name}</p>
            <p class="drops-out mb-4 text-[0.75rem] text-[var(--omr-graphite-soft)]">
              {summary.questions} questions · {summary.points} points
            </p>
            <div
              class="flex max-h-[22rem] flex-wrap gap-1 overflow-y-auto lg:max-h-[60vh] lg:flex-col lg:flex-nowrap lg:gap-0"
            >
              {#each rows as q (q.id)}
                {@const rule = ruleOf(q)}
                <button
                  type="button"
                  onclick={() => jump(q.id)}
                  class="rail-row"
                  class:active={activeId === q.id}
                  aria-current={activeId === q.id ? 'true' : undefined}
                >
                  <span class="font-mono text-[0.6875rem] tabular-nums">{q.number ?? q.id}</span>
                  <Mark filled={!!rule && isDeterministic(rule)} size="sm" />
                </button>
              {/each}
            </div>
            <p class="drops-out mt-4 border-t border-[var(--omr-dropout-soft)] pt-3 text-[0.6875rem] leading-relaxed text-[var(--omr-graphite-soft)]">
              A filled square grades as a script. A blank one needs a judge — {summary.judged} here.
            </p>
          </Sheet>
        </aside>

        <div class="min-w-0 space-y-6">
          <Sheet class="min-w-0 px-6 py-8 sm:px-10 sm:py-10 lg:px-14">
            <h1
              class="han text-[clamp(1.5rem,3vw,2.35rem)] leading-[1.15] font-bold tracking-[-0.02em] text-[var(--omr-graphite)]"
              lang={bundle.exam.language}
            >
              {bundle.exam.title}
            </h1>
            <dl class="drops-out mt-6 flex flex-wrap gap-x-9 gap-y-3 border-t border-[var(--omr-dropout-soft)] pt-5">
              {#if bundle.exam.subject}
                <div>
                  <dt class="field-label">Subject</dt>
                  <dd class="han text-sm" lang={bundle.exam.language}>{bundle.exam.subject}</dd>
                </div>
              {/if}
              <div>
                <dt class="field-label">Graded by rule</dt>
                <dd class="font-mono text-sm tabular-nums">{summary.auto} / {summary.questions}</dd>
              </div>
              <div>
                <dt class="field-label">Figures</dt>
                <dd class="font-mono text-sm tabular-nums">{summary.figures}</dd>
              </div>
              {#if bundle.manifest.ingest_model}
                <div>
                  <dt class="field-label">Ingested by</dt>
                  <dd class="font-mono text-sm">{bundle.manifest.ingest_model}</dd>
                </div>
              {/if}
            </dl>

            {#if bundle.manifest.sources.length}
              <div class="mt-6">
                <span class="field-label mb-2 block">Built from</span>
                <ul class="flex flex-wrap gap-x-5 gap-y-1.5">
                  {#each bundle.manifest.sources as source (source.path)}
                    <li class="han font-mono text-[0.8125rem] text-[var(--omr-graphite-soft)]">
                      {source.path.split('/').pop()}
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            {#if bundle.manifest.warnings.length}
              <div class="mt-6 border-t-2 border-[var(--omr-graphite)] bg-[var(--omr-dropout-faint)] px-4 py-3.5">
                <span class="field-label mb-2 block">
                  Recorded at ingest ({bundle.manifest.warnings.length})
                </span>
                <ul class="space-y-2">
                  {#each bundle.manifest.warnings as warning, i (i)}
                    <li class="han text-[0.875rem] leading-relaxed text-[var(--omr-graphite-soft)]">
                      {warning}
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            {#if bundle.exam.description}
              <details class="mt-6 border-t border-[var(--omr-dropout-soft)] pt-5">
                <summary class="field-label cursor-pointer hover:text-[var(--omr-graphite)]">
                  Instructions as printed
                </summary>
                <div class="mt-4">
                  <Blocks
                    blocks={[{ type: 'text', markdown: bundle.exam.description }]}
                    {repo}
                    subset={bundle.name}
                    lang={bundle.exam.language}
                  />
                </div>
              </details>
            {/if}
          </Sheet>

          {#each bundle.exam.sections as section (section.id)}
            <Sheet class="px-6 py-8 sm:px-10 sm:py-10 lg:px-14">
              {#if section.title}
                <h2
                  class="han text-xl leading-snug font-bold text-[var(--omr-graphite)]"
                  lang={bundle.exam.language}
                >
                  {section.title}
                </h2>
              {/if}
              {#if section.instructions.length}
                <div class="mt-3 border-l border-[var(--omr-dropout-ink)] pl-4">
                  <Blocks
                    blocks={section.instructions}
                    {repo}
                    subset={bundle.name}
                    lang={bundle.exam.language}
                  />
                </div>
              {/if}

              <div class="mt-6">
                {#each section.questions as top (top.id)}
                  {#if top.children.length}
                    <div class="border-t border-[var(--omr-dropout-soft)] pt-8 first:border-t-0">
                      <div class="flex gap-4 sm:gap-6">
                        <div class="w-12 shrink-0 font-mono text-2xl font-semibold tabular-nums sm:w-16 sm:text-3xl">
                          {top.number ?? ''}
                        </div>
                        <div class="min-w-0 flex-1">
                          <Blocks
                            blocks={top.prompt}
                            {repo}
                            subset={bundle.name}
                            lang={bundle.exam.language}
                          />
                        </div>
                      </div>
                      <div class="mt-2 sm:pl-16">
                        {#each top.children as child (child.id)}
                          <QuestionCard
                            question={child}
                            grading={bundle.grading.questions[child.id]}
                            {repo}
                            subset={bundle.name}
                            lang={bundle.exam.language}
                            {revealed}
                          />
                        {/each}
                      </div>
                    </div>
                  {:else}
                    <QuestionCard
                      question={top}
                      grading={bundle.grading.questions[top.id]}
                      {repo}
                      subset={bundle.name}
                      lang={bundle.exam.language}
                      {revealed}
                    />
                  {/if}
                {/each}
              </div>
            </Sheet>
          {/each}
        </div>
      </div>
    {:else if subsets}
      <!-- ── The register of issued cards ───────────────────────────────── -->
      <Sheet class="px-6 py-8 sm:px-12 sm:py-10 lg:px-16">
        <div class="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h1 class="text-[clamp(1.6rem,3vw,2.4rem)] font-bold tracking-[-0.03em] text-[var(--omr-graphite)]">
              {subsets.length} bundles
            </h1>
            <a
              href={repoUrl(repo)}
              class="mt-1.5 inline-flex items-center gap-1.5 font-mono text-sm text-[var(--omr-graphite-soft)] underline-offset-4 hover:text-[var(--omr-graphite)] hover:underline"
            >
              {repo}
              <ExternalLink size={13} strokeWidth={2} aria-hidden="true" />
            </a>
          </div>
          <div>
            <label for="filter" class="field-label drops-out mb-1.5 block">Filter</label>
            <input
              id="filter"
              bind:value={filter}
              placeholder="e.g. math"
              class="w-56 border border-[var(--omr-dropout-soft)] bg-white/70 px-3 py-2 font-mono
                     text-sm outline-none focus:border-[var(--omr-cinnabar)]"
            />
          </div>
        </div>

        {#if shown.length === 0}
          <p class="mt-10 text-[var(--omr-graphite-soft)]">
            Nothing matches “{filter}”. Clear the filter to see all {subsets.length}.
          </p>
        {:else}
          {#each groups as group (group.title)}
            <section class="mt-9">
              {#if group.title}
                <h2
                  class="flex items-baseline justify-between border-b-2 border-[var(--omr-graphite)] pb-1.5"
                >
                  <span class="font-mono text-sm font-semibold tracking-wide uppercase">
                    {group.title}
                  </span>
                  <span class="field-label">{group.total}</span>
                </h2>
              {/if}
              <!-- The frame is on the container, so a section that ends mid-row still
                   closes with a rule across its full width, the way a printed register does. -->
              <ul
                class="grid border border-[var(--omr-dropout-soft)] sm:grid-cols-2 lg:grid-cols-3"
              >
                {#each group.items as row (row.name)}
                  <li>
                    <button
                      type="button"
                      onclick={() => open(row.name)}
                      class="group flex h-full w-full items-baseline gap-3 border-r border-b
                             border-[var(--omr-dropout-soft)] bg-[var(--omr-stock)] px-4 py-3
                             text-left transition-colors hover:bg-[var(--omr-dropout-faint)]"
                    >
                      <span
                        class="drops-out w-6 shrink-0 font-mono text-[0.6875rem] tabular-nums
                               text-[var(--omr-dropout-ink)]">{row.no}</span
                      >
                      <span class="min-w-0 flex-1 truncate font-mono text-[0.875rem]">{row.name}</span>
                    </button>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
        {/if}
      </Sheet>
    {/if}
  </main>
</div>

<style>
  .rail-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    width: 100%;
    min-width: 3.5rem;
    padding: 0.3rem 0.45rem;
    border-left: 1px solid transparent;
    color: var(--omr-graphite-soft);
    transition:
      background-color 160ms ease-out,
      border-color 160ms ease-out,
      color 160ms ease-out;
  }
  .rail-row:hover {
    background: var(--omr-dropout-faint);
    color: var(--omr-graphite);
  }
  /* The travelling band. Graphite hairline plus the printed tint — cinnabar is
     spoken for by the act that commits and by the seal. */
  .rail-row.active {
    border-left-color: var(--omr-graphite);
    background: var(--omr-dropout-faint);
    color: var(--omr-graphite);
    font-weight: 600;
  }

  button.sealed {
    border-color: var(--omr-cinnabar-ink);
    color: var(--omr-cinnabar-ink);
  }
  button.sealed:hover {
    background: var(--omr-cinnabar);
    color: #fff;
  }
  button.broken {
    border-color: var(--omr-graphite);
    background: var(--omr-graphite);
    color: var(--omr-stock);
  }

  :global(.spin) {
    animation: spin 1.1s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
