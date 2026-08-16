<script lang="ts">
  import { ScanLine } from '@lucide/svelte'
  import { scanner, toggleScanner } from './scanner.svelte'

  type Props = { class?: string }
  let { class: cls = '' }: Props = $props()
</script>

<button
  type="button"
  onclick={toggleScanner}
  aria-pressed={scanner.on}
  class="inline-flex items-center gap-2.5 border px-3.5 py-2 text-[0.6875rem] font-semibold
         tracking-[0.14em] uppercase transition-colors {cls}"
  class:on={scanner.on}
>
  <ScanLine size={15} strokeWidth={2.25} aria-hidden="true" />
  <span>{scanner.on ? 'Scanner view on' : 'Scanner view'}</span>
</button>

<style>
  button {
    border-color: color-mix(in oklab, var(--omr-graphite) 26%, transparent);
    color: var(--omr-graphite);
    background: transparent;
  }
  button:hover {
    background: color-mix(in oklab, var(--omr-graphite) 7%, transparent);
  }
  button.on {
    background: var(--omr-graphite);
    color: var(--omr-stock);
    border-color: var(--omr-graphite);
  }
</style>
