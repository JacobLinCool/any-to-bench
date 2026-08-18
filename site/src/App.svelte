<script lang="ts">
  import { ArrowRight, Github, Package } from '@lucide/svelte'
  import CopyLine from './lib/CopyLine.svelte'
  import Mark from './lib/Mark.svelte'
  import ScannerToggle from './lib/ScannerToggle.svelte'
  import Sheet from './lib/Sheet.svelte'
  import { renderInline, renderMarkdown } from './lib/render'
  import { scanner } from './lib/scanner.svelte'

  const BASE = import.meta.env.BASE_URL

  const PIPELINE = [
    { n: '1', key: 'ingest', body: 'papers, keys and marking schemes become one bundle' },
    { n: '2', key: 'validate', body: 'the bundle is checked for internal consistency' },
    { n: '3', key: 'solve', body: 'a model sits the exam and files an answer sheet' },
    { n: '4', key: 'grade', body: 'rules run as scripts; only open questions reach a judge' },
  ]

  // A real question from gsat-115-math-a, rendered from the same bundle the
  // viewer reads. Nothing here is illustrative.
  const DEMO = {
    number: '1.',
    points: 5,
    prompt:
      '財神廟舉辦抽發財金活動：參加者抽兩次籤，每次抽籤出現「吉」、「祥」的機率皆為 $\\frac{1}{3}$。如果兩次都抽得「吉」，獲得獎金 180 元；如果兩次都抽得「祥」，獲得獎金 90 元；其餘情況則無獎金。試問參加者可獲獎金的期望值為何？',
    options: [
      { id: '1', md: '20 元' },
      { id: '2', md: '30 元' },
      { id: '3', md: '45 元' },
      { id: '4', md: '60 元' },
      { id: '5', md: '90 元' },
    ],
    correct: '2',
  }

  const MACHINE_READS = `"q1": {
  "type": "object",
  "properties": {
    "type":     { "const": "single_choice" },
    "selected": { "enum": ["1","2","3","4","5"] }
  },
  "required": ["type", "selected"],
  "additionalProperties": false
}`

  const GRADES_AS = `"q1": {
  "max_points": 5.0,
  "rule": { "kind": "choice", "correct": ["2"] }
}`

  const CORPUS = [
    { label: '學測 General Scholastic Ability Test', code: 'gsat', subsets: 21, years: '113–115' },
    { label: '分科測驗 Advanced Subjects Test', code: 'ast', subsets: 23, years: '113–115' },
    { label: '統測 vocational Unified Entrance Exam', code: 'tve', subsets: 120, years: '113–115' },
    { label: '會考 Comprehensive Assessment Program', code: 'cap', subsets: 18, years: '113–115' },
  ]

  let sealed = $state(true)
</script>

<div class="min-h-screen px-4 py-6 sm:px-8 sm:py-10 lg:py-14">
  <main class="mx-auto max-w-[76rem] space-y-6 sm:space-y-10">
    <!-- ── The card issued to the visitor ────────────────────────────────── -->
    <Sheet class="px-6 pt-8 pb-6 sm:px-12 sm:pt-12 sm:pb-8 lg:px-16">
      <div
        class="drops-out mb-10 flex flex-wrap gap-x-10 gap-y-4 border-b
               border-[var(--omr-dropout-soft)] pb-5 sm:mb-14"
      >
        <div>
          <span class="field-label block">Form</span>
          <span class="font-mono text-sm">any-to-bench · a2b</span>
        </div>
        <div>
          <span class="field-label block">Reads</span>
          <span class="text-sm">exam PDFs · photos · answer keys · marking schemes</span>
        </div>
        <div>
          <span class="field-label block">Issues</span>
          <span class="text-sm">a machine-gradable bundle</span>
        </div>
      </div>

      <h1
        class="max-w-[19ch] text-[clamp(2.6rem,7.2vw,5.4rem)] leading-[0.94] font-extrabold
               tracking-[-0.04em] text-balance text-[var(--omr-graphite)]"
      >
        Only the marks count.
      </h1>

      <p class="mt-7 max-w-[64ch] text-lg leading-relaxed text-[var(--omr-graphite-soft)]">
        An answer card prints its grid in an ink the scanner cannot see, so nothing but the pencil
        reaches the machine. <strong class="font-semibold text-[var(--omr-graphite)]"
          >any-to-bench does that to an exam</strong
        >: it reads your papers once, expensively, and converts them into structure — a strict
        answer schema and a grading spec — so that scoring a model afterwards needs almost no
        intelligence at all, forever.
      </p>

      <!-- the pipeline as one row of a card -->
      <ol
        class="mt-12 grid gap-px border border-[var(--omr-dropout-soft)]
               bg-[var(--omr-dropout-soft)] sm:grid-cols-2 lg:grid-cols-4"
      >
        {#each PIPELINE as step (step.key)}
          <li class="bg-[var(--omr-stock)] px-5 py-5">
            <div class="flex items-center gap-3">
              <span
                class="drops-out font-mono text-[0.6875rem] text-[var(--omr-graphite-soft)]"
                aria-hidden="true">{step.n}</span
              >
              <Mark filled size="sm" />
              <code class="font-mono text-[0.9375rem] font-semibold">{step.key}</code>
            </div>
            <p class="mt-3 text-sm leading-relaxed text-[var(--omr-graphite-soft)]">{step.body}</p>
          </li>
        {/each}
      </ol>

      <!-- the signature strip: where a card is signed, and the one cinnabar act -->
      <div
        class="mt-10 flex flex-col gap-6 border-t-2 border-[var(--omr-graphite)] pt-6
               lg:flex-row lg:items-end lg:justify-between"
      >
        <div class="w-full max-w-md">
          <CopyLine label="Install" command="uv tool install any-to-bench" />
        </div>
        <a
          href="{BASE}viewer.html"
          class="group inline-flex shrink-0 items-center justify-center gap-3
                 bg-[var(--omr-cinnabar)] px-7 py-4 text-base font-semibold text-white
                 transition-[background-color,letter-spacing] hover:bg-[#b92c20]
                 hover:tracking-[0.01em]"
        >
          Open a real exam
          <ArrowRight
            size={18}
            strokeWidth={2.5}
            class="transition-transform group-hover:translate-x-1"
            aria-hidden="true"
          />
        </a>
      </div>
    </Sheet>

    <!-- ── The mechanism, dramatized ─────────────────────────────────────── -->
    <section aria-labelledby="reads-heading" class="space-y-6">
      <Sheet class="px-6 py-8 sm:px-12 sm:py-12 lg:px-16">
        <div class="flex flex-wrap items-end justify-between gap-5">
          <h2
            id="reads-heading"
            class="max-w-[22ch] text-[clamp(1.75rem,3.4vw,2.75rem)] leading-[1.05]
                   font-bold tracking-[-0.03em] text-[var(--omr-graphite)]"
          >
            What a machine actually reads
          </h2>
          <ScannerToggle />
        </div>

        <p class="mt-5 max-w-[68ch] leading-relaxed text-[var(--omr-graphite-soft)]">
          Below is question 1 of the 115 GSAT mathematics A paper, exactly as its bundle stores it.
          Turn on scanner view: the pre-printed structure drops away and what remains is the part a
          grader is allowed to depend on.
        </p>

        <div class="mt-10 grid gap-px bg-[var(--omr-dropout-soft)] lg:grid-cols-[1.15fr_1fr]">
          <!-- as printed: the specimen sits on the measuring ground -->
          <div class="ruled min-w-0 bg-[var(--omr-stock)] p-6 sm:p-8">
            <span class="field-label drops-out mb-5 block">As issued</span>
            <div class="flex gap-4">
              <span
                class="shrink-0 pt-0.5 font-mono text-2xl font-semibold tabular-nums
                       text-[var(--omr-graphite)]">{DEMO.number}</span
              >
              <div class="min-w-0 flex-1">
                <div class="han prose-exam" lang="zh-TW">
                  {@html renderMarkdown(DEMO.prompt)}
                </div>
                <ul class="mt-6 space-y-2.5">
                  {#each DEMO.options as option (option.id)}
                    <li class="flex items-center gap-3">
                      <Mark filled={!sealed && option.id === DEMO.correct} size="sm" />
                      <span
                        class="drops-out font-mono text-xs text-[var(--omr-graphite-soft)]"
                        aria-hidden="true">{option.id}</span
                      >
                      <span class="han text-[0.9375rem]" lang="zh-TW"
                        >{@html renderInline(option.md)}</span
                      >
                    </li>
                  {/each}
                </ul>
                <div class="mt-6">
                  {#if sealed}
                    <button
                      type="button"
                      onclick={() => (sealed = false)}
                      class="border border-[var(--omr-cinnabar-ink)] px-3.5 py-2 text-[0.6875rem]
                             font-semibold tracking-[0.14em] uppercase
                             text-[var(--omr-cinnabar-ink)] transition-colors
                             hover:bg-[var(--omr-cinnabar)] hover:text-white"
                    >
                      Break the seal
                    </button>
                  {:else}
                    <p class="text-[0.8125rem] text-[var(--omr-graphite-soft)]">
                      Official key: option <strong class="text-[var(--omr-graphite)]">2</strong>,
                      worth {DEMO.points} points. No model was asked.
                    </p>
                  {/if}
                </div>
              </div>
            </div>
          </div>

          <!-- what survives -->
          <div class="min-w-0 bg-[var(--omr-stock)] p-6 sm:p-8">
            <span class="field-label drops-out mb-5 block">What the machine reads</span>
            <div class="space-y-6">
              <div class="min-w-0">
                <p class="mb-2 font-mono text-xs text-[var(--omr-graphite-soft)]">
                  answer_schema.json
                </p>
                <pre
                  class="overflow-x-auto border border-[var(--omr-dropout-soft)] bg-white/70 p-3.5
                         font-mono text-[0.75rem] leading-relaxed">{MACHINE_READS}</pre>
              </div>
              <div class="min-w-0">
                <p class="mb-2 font-mono text-xs text-[var(--omr-graphite-soft)]">grading.json</p>
                <pre
                  class="overflow-x-auto border border-[var(--omr-dropout-soft)] bg-white/70 p-3.5
                         font-mono text-[0.75rem] leading-relaxed">{GRADES_AS}</pre>
              </div>
              <p class="text-sm leading-relaxed text-[var(--omr-graphite-soft)]">
                {#if scanner.on}
                  This is all that is left, and it is enough: the score is a pure function of the
                  answer sheet.
                {:else}
                  Everything to the left is scaffolding for a human reader. This is the contract a
                  grader runs on.
                {/if}
              </p>
            </div>
          </div>
        </div>
      </Sheet>
    </section>

    <!-- ── Two paths ─────────────────────────────────────────────────────── -->
    <section aria-labelledby="paths-heading">
      <Sheet class="px-6 py-8 sm:px-12 sm:py-12 lg:px-16">
        <h2
          id="paths-heading"
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] leading-[1.05] font-bold
                 tracking-[-0.03em] text-[var(--omr-graphite)]"
        >
          Two ways in
        </h2>

        <div class="mt-10 grid gap-px bg-[var(--omr-dropout-soft)] lg:grid-cols-2">
          <div class="min-w-0 bg-[var(--omr-stock)] p-6 sm:p-8">
            <div class="mb-4 flex items-center gap-3">
              <Mark filled size="sm" />
              <h3 class="text-lg font-semibold text-[var(--omr-graphite)]">Score a model</h3>
            </div>
            <p class="mb-6 max-w-[52ch] text-[0.9375rem] leading-relaxed text-[var(--omr-graphite-soft)]">
              Pull a published bundle and point any model at it. Fixed-answer questions grade with
              no model calls at all, so the same answer sheet earns the same score every time.
            </p>
            <div class="space-y-3">
              <CopyLine
                command="a2b download JacobLinCool/taiwan-exams --name gsat-115-math-a -o bundle"
              />
              <CopyLine command="a2b solve bundle --model openai:gpt-5.6-sol -o answers.json" />
              <CopyLine command="a2b grade bundle answers.json -o report.json" />
            </div>
          </div>

          <div class="min-w-0 bg-[var(--omr-stock)] p-6 sm:p-8">
            <div class="mb-4 flex items-center gap-3">
              <Mark size="sm" />
              <h3 class="text-lg font-semibold text-[var(--omr-graphite)]">Convert your own exam</h3>
            </div>
            <p class="mb-6 max-w-[52ch] text-[0.9375rem] leading-relaxed text-[var(--omr-graphite-soft)]">
              Give it everything you have for one exam — the paper, the official key, the marking
              scheme — as PDFs or photos. Ingest is slow and expensive on purpose: it is paid once
              and reused by everyone who benchmarks against the result.
            </p>
            <div class="space-y-3">
              <CopyLine
                command="a2b ingest exam.pdf key.pdf scheme.pdf -o bundle --model codex:gpt-5.6-sol"
              />
              <CopyLine command="a2b validate bundle" />
              <CopyLine command="a2b upload bundle your-name/your-exams --name paper-1" />
            </div>
          </div>
        </div>
      </Sheet>
    </section>

    <!-- ── The register of what has been issued ──────────────────────────── -->
    <section aria-labelledby="corpus-heading">
      <Sheet class="px-6 py-8 sm:px-12 sm:py-12 lg:px-16">
        <h2
          id="corpus-heading"
          class="text-[clamp(1.75rem,3.4vw,2.75rem)] leading-[1.05] font-bold
                 tracking-[-0.03em] text-[var(--omr-graphite)]"
        >
          Already issued
        </h2>
        <p class="mt-5 max-w-[68ch] leading-relaxed text-[var(--omr-graphite-soft)]">
          Four Taiwanese national examinations across the same three years: the three that open
          university, ingested with
          <code class="font-mono text-[0.9em] text-[var(--omr-graphite)]">codex:gpt-5.6-sol</code>,
          and the one that closes junior high, ingested with
          <code class="font-mono text-[0.9em] text-[var(--omr-graphite)]">claude:claude-opus-5</code
          > — published as one dataset.
        </p>

        <!-- A table cannot shrink below its min-content width, so it scrolls in its own
             box rather than setting the width of the page. -->
        <div class="mt-9 overflow-x-auto">
          <table class="w-full min-w-[30rem] border-collapse text-left">
            <caption class="sr-only">Exams in the taiwan-exams dataset</caption>
            <thead>
              <tr class="border-b-2 border-[var(--omr-graphite)]">
                <th scope="col" class="field-label pb-2">Examination</th>
                <th scope="col" class="field-label pb-2">Prefix</th>
                <th scope="col" class="field-label pb-2 text-right">Years</th>
                <th scope="col" class="field-label pb-2 text-right">Papers</th>
              </tr>
            </thead>
            <tbody>
              {#each CORPUS as row (row.code)}
                <tr class="border-b border-[var(--omr-dropout-soft)]">
                  <th scope="row" class="py-3.5 pr-4 font-normal text-[var(--omr-graphite)]">
                    {row.label}
                  </th>
                  <td class="py-3.5 pr-4 font-mono text-sm text-[var(--omr-graphite-soft)]"
                    >{row.code}</td
                  >
                  <td class="py-3.5 pr-4 text-right font-mono text-sm tabular-nums">{row.years}</td>
                  <td class="py-3.5 text-right font-mono tabular-nums">{row.subsets}</td>
                </tr>
              {/each}
              <tr class="border-t-2 border-[var(--omr-graphite)]">
                <th scope="row" class="py-3.5 pr-4 font-semibold text-[var(--omr-graphite)]">
                  7,772 questions — 7,453 graded by rule, 319 by judge
                </th>
                <td></td>
                <td></td>
                <td class="py-3.5 text-right font-mono text-lg font-semibold tabular-nums">182</td>
              </tr>
            </tbody>
          </table>
        </div>

        <a
          href="{BASE}viewer.html"
          class="group mt-9 inline-flex items-center gap-2.5 border-b-2 border-[var(--omr-graphite)]
                 pb-1 font-semibold text-[var(--omr-graphite)] transition-colors
                 hover:border-[var(--omr-dropout-ink)] hover:text-[var(--omr-dropout-ink)]"
        >
          Read any of them
          <ArrowRight
            size={17}
            strokeWidth={2.5}
            class="transition-transform group-hover:translate-x-1"
            aria-hidden="true"
          />
        </a>
      </Sheet>
    </section>

    <!-- ── Issuing block ─────────────────────────────────────────────────── -->
    <footer class="px-2 pt-6 pb-4 sm:px-4">
      <div
        class="flex flex-col gap-6 border-t border-[color-mix(in_oklab,var(--omr-dropout)_30%,transparent)]
               pt-7 sm:flex-row sm:items-start sm:justify-between"
      >
        <div class="max-w-[46ch]">
          <p class="font-mono text-sm text-[var(--omr-dropout)]">any-to-bench</p>
          <p class="mt-2 text-sm leading-relaxed text-[color-mix(in_oklab,var(--color-neutral-content)_72%,transparent)]">
            Exam content belongs to the examination boards that published it. This tool only
            restructures material you already hold.
          </p>
        </div>
        <nav aria-label="Project links" class="flex flex-wrap gap-x-7 gap-y-3 text-sm">
          <a
            class="inline-flex items-center gap-2 text-[var(--omr-dropout)] underline-offset-4 hover:underline"
            href="https://github.com/JacobLinCool/any-to-bench"
          >
            <Github size={15} strokeWidth={2} aria-hidden="true" /> Source
          </a>
          <a
            class="inline-flex items-center gap-2 text-[var(--omr-dropout)] underline-offset-4 hover:underline"
            href="https://pypi.org/project/any-to-bench/"
          >
            <Package size={15} strokeWidth={2} aria-hidden="true" /> PyPI
          </a>
          <a
            class="text-[var(--omr-dropout)] underline-offset-4 hover:underline"
            href="https://huggingface.co/datasets/JacobLinCool/taiwan-exams"
          >
            Dataset
          </a>
        </nav>
      </div>
    </footer>
  </main>
</div>

<style>
  /* Exam prose keeps its own rhythm; KaTeX inherits the surrounding size. */
  .prose-exam :global(p) {
    margin: 0;
  }
  .prose-exam :global(p + p) {
    margin-top: 0.85em;
  }
  .prose-exam :global(.katex) {
    font-size: 1.04em;
  }
</style>
