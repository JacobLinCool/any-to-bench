<script lang="ts">
  import type { ContentBlock } from './bundle'
  import { assetUrl } from './hf'
  import { renderInline, renderMarkdown } from './render'

  type Props = { blocks: ContentBlock[]; repo: string; subset: string; lang: string }
  let { blocks, repo, subset, lang }: Props = $props()
</script>

{#each blocks as block, i (i)}
  {#if block.type === 'text'}
    <div class="han prose-exam" {lang}>{@html renderMarkdown(block.markdown)}</div>
  {:else if block.type === 'image'}
    <figure class="my-5">
      <img
        src={assetUrl(repo, subset, block.asset)}
        alt={block.alt}
        loading="lazy"
        decoding="async"
        class="max-w-full border border-[var(--omr-dropout-soft)] bg-white"
      />
      {#if block.caption}
        <figcaption class="mt-2 text-[0.8125rem] text-[var(--omr-graphite-soft)]" {lang}>
          {block.caption}
        </figcaption>
      {/if}
    </figure>
  {:else if block.type === 'table'}
    <div class="my-5 overflow-x-auto">
      <table class="w-full border-collapse text-left text-[0.9375rem]">
        {#if block.caption}
          <caption class="mb-2 text-left text-[0.8125rem] text-[var(--omr-graphite-soft)]" {lang}>
            {block.caption}
          </caption>
        {/if}
        <thead>
          <tr class="border-b-2 border-[var(--omr-graphite)]">
            {#each block.header as cell, c (c)}
              <th scope="col" class="han px-3 py-2 font-semibold" {lang}
                >{@html renderInline(cell)}</th
              >
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each block.rows as row, r (r)}
            <tr class="border-b border-[var(--omr-dropout-soft)]">
              {#each row as cell, c (c)}
                <td class="han px-3 py-2" {lang}>{@html renderInline(cell)}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
{/each}

<style>
  .prose-exam :global(p) {
    margin: 0;
  }
  .prose-exam :global(p + p) {
    margin-top: 0.85em;
  }
  .prose-exam :global(ul),
  .prose-exam :global(ol) {
    margin: 0.6em 0;
    padding-left: 1.4em;
    list-style: revert;
  }
  .prose-exam :global(pre) {
    overflow-x: auto;
  }
  .prose-exam :global(code) {
    font-family: var(--font-mono);
    font-size: 0.9em;
  }
  .prose-exam :global(.katex-display) {
    margin: 0.9em 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0.2em 0;
  }
  .prose-exam :global(.math-error) {
    background: color-mix(in oklab, var(--omr-cinnabar) 12%, transparent);
    padding: 0 0.2em;
  }
</style>
