<script lang="ts">
  import Blocks from './Blocks.svelte'
  import Mark from './Mark.svelte'
  import { RULE_LABEL, TYPE_LABEL, type Question, type QuestionGrading } from './bundle'
  import { renderInline, renderMarkdown } from './render'

  type Props = {
    question: Question
    grading?: QuestionGrading
    repo: string
    subset: string
    lang: string
    revealed: boolean
  }
  let { question, grading, repo, subset, lang, revealed }: Props = $props()

  const rule = $derived(grading?.rule)

  const correctIds = $derived(
    rule && (rule.kind === 'choice' || rule.kind === 'per_option') ? new Set(rule.correct) : null,
  )
  const trueFalse = $derived(rule?.kind === 'true_false' ? rule.correct : null)

  // Kept out of the markup: a backtick template literal in the same attribute
  // list hid `scroll-mt-24` from Tailwind's scanner, so jumping to a question
  // landed it under the sticky toolbar.
  const anchor = $derived(`q-${question.id}`)
</script>

<article
  id={anchor}
  class="scroll-mt-24 border-t border-[var(--omr-dropout-soft)] py-8 first:border-t-0"
>
  <div class="flex gap-4 sm:gap-6">
    <div class="w-12 shrink-0 sm:w-16">
      <div class="font-mono text-2xl leading-none font-semibold tabular-nums sm:text-3xl">
        {question.number ?? question.id}
      </div>
      <div class="mt-2 font-mono text-[0.6875rem] text-[var(--omr-graphite-soft)]">
        {question.points}
        {question.points === 1 ? 'pt' : 'pts'}
      </div>
    </div>

    <div class="min-w-0 flex-1">
      <div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span class="field-label">{TYPE_LABEL[question.type]}</span>
        {#if rule}
          <span class="text-[var(--omr-dropout)]" aria-hidden="true">·</span>
          <span class="field-label">{RULE_LABEL[rule.kind]}</span>
        {/if}
      </div>

      <Blocks blocks={question.prompt} {repo} {subset} {lang} />

      {#if question.options?.length}
        <ul class="mt-5 space-y-2.5">
          {#each question.options as option (option.id)}
            <li class="flex items-start gap-3">
              <span class="pt-0.5">
                <Mark filled={revealed && !!correctIds?.has(option.id)} size="sm" />
              </span>
              <span
                class="shrink-0 pt-0.5 font-mono text-xs text-[var(--omr-graphite-soft)]"
                aria-hidden="true">{option.id}</span
              >
              <span class="han min-w-0 flex-1 text-[0.9375rem]" {lang}>
                {@html renderInline(
                  option.content.map((b) => (b.type === 'text' ? b.markdown : '')).join(' '),
                )}
              </span>
            </li>
          {/each}
        </ul>
      {/if}

      {#if question.blanks?.length}
        <dl class="mt-5 flex flex-wrap gap-x-8 gap-y-2">
          {#each question.blanks as blank (blank.id)}
            <div class="flex items-baseline gap-2">
              <dt class="font-mono text-xs text-[var(--omr-graphite-soft)]">
                {blank.label ?? blank.id}
              </dt>
              <dd
                class="min-w-[5rem] border-b border-[var(--omr-graphite)] pb-0.5 text-[0.9375rem]"
              >
                {#if revealed && rule?.kind === 'fill_in_blank'}
                  <span class="han" {lang}>{rule.blanks[blank.id]?.accepted.join(' / ') ?? ''}</span>
                {:else}
                  <span class="sr-only">blank</span>&nbsp;
                {/if}
              </dd>
            </div>
          {/each}
        </dl>
      {/if}

      {#if question.matching}
        <div class="mt-5 grid gap-6 sm:grid-cols-2">
          <div>
            <span class="field-label mb-2 block">Left</span>
            <ul class="space-y-1.5">
              {#each question.matching.left as item (item.id)}
                <li class="flex gap-2.5 text-[0.9375rem]">
                  <span class="font-mono text-xs text-[var(--omr-graphite-soft)]">{item.id}</span>
                  <span class="han" {lang}>
                    {@html renderInline(
                      item.content.map((b) => (b.type === 'text' ? b.markdown : '')).join(' '),
                    )}
                  </span>
                  {#if revealed && rule?.kind === 'matching'}
                    <span class="font-mono text-xs font-semibold text-[var(--omr-cinnabar-ink)]">
                      → {rule.correct_pairs[item.id] ?? '—'}
                    </span>
                  {/if}
                </li>
              {/each}
            </ul>
          </div>
          <div>
            <span class="field-label mb-2 block">Right</span>
            <ul class="space-y-1.5">
              {#each question.matching.right as item (item.id)}
                <li class="flex gap-2.5 text-[0.9375rem]">
                  <span class="font-mono text-xs text-[var(--omr-graphite-soft)]">{item.id}</span>
                  <span class="han" {lang}>
                    {@html renderInline(
                      item.content.map((b) => (b.type === 'text' ? b.markdown : '')).join(' '),
                    )}
                  </span>
                </li>
              {/each}
            </ul>
          </div>
        </div>
      {/if}

      {#if question.type === 'true_false'}
        <div class="mt-5 flex gap-6">
          <Mark filled={revealed && trueFalse === true} size="sm" label="True" />
          <Mark filled={revealed && trueFalse === false} size="sm" label="False" />
        </div>
      {/if}

      <!-- The key, sealed by default. -->
      {#if revealed && rule}
        <div class="mt-6 border-t-2 border-[var(--omr-graphite)] bg-[var(--omr-dropout-faint)] px-4 py-3.5">
          <span class="field-label mb-2 block">Official key</span>
          {#if rule.kind === 'choice' || rule.kind === 'per_option'}
            <p class="text-[0.9375rem]">
              <span class="font-mono font-semibold">{rule.correct.join(', ')}</span>
              {#if rule.kind === 'per_option'}
                <span class="text-[var(--omr-graphite-soft)]">
                  — each option marked independently; {rule.ratio_by_errors
                    .map((r, i) => `${i} wrong → ${Math.round(r * 100)}%`)
                    .join(', ')}
                </span>
              {:else if rule.partial_credit}
                <span class="text-[var(--omr-graphite-soft)]">— partial credit</span>
              {/if}
            </p>
          {:else if rule.kind === 'true_false'}
            <p class="font-mono text-[0.9375rem] font-semibold">{rule.correct}</p>
          {:else if rule.kind === 'fill_in_blank'}
            <p class="text-[0.9375rem] text-[var(--omr-graphite-soft)]">
              Accepted answers are shown in the blanks above.
            </p>
          {:else if rule.kind === 'matching'}
            <p class="font-mono text-[0.9375rem]">
              {Object.entries(rule.correct_pairs)
                .map(([l, r]) => `${l}→${r}`)
                .join('  ')}
            </p>
          {:else if rule.kind === 'judge'}
            {#if rule.reference_answer}
              <div class="han prose-exam text-[0.9375rem]" {lang}>
                {@html renderMarkdown(rule.reference_answer)}
              </div>
            {:else}
              <p class="text-[0.9375rem] text-[var(--omr-graphite-soft)]">
                No official reference answer was published for this question; a judge grades it from
                the printed instructions alone.
              </p>
            {/if}
            {#if rule.rubric.length}
              <ul class="mt-3 space-y-2">
                {#each rule.rubric as criterion (criterion.id)}
                  <li class="text-[0.875rem]">
                    <span class="font-semibold" {lang}>{criterion.description}</span>
                    <span class="text-[var(--omr-graphite-soft)]">
                      — {criterion.levels.map((l) => `${l.points}: ${l.descriptor}`).join(' · ')}
                    </span>
                  </li>
                {/each}
              </ul>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  </div>
</article>

<style>
  .prose-exam :global(p) {
    margin: 0;
  }
  .prose-exam :global(p + p) {
    margin-top: 0.85em;
  }
</style>
