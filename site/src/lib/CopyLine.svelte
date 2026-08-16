<script lang="ts">
  import { Check, Copy } from '@lucide/svelte'

  type Props = { command: string; label?: string }
  let { command, label }: Props = $props()
  let copied = $state(false)
  let timer: ReturnType<typeof setTimeout> | undefined

  async function copy() {
    try {
      await navigator.clipboard.writeText(command)
      copied = true
      clearTimeout(timer)
      timer = setTimeout(() => (copied = false), 1600)
    } catch {
      copied = false
    }
  }
</script>

<div class="group">
  {#if label}<span class="field-label drops-out mb-1.5 block">{label}</span>{/if}
  <div class="flex items-stretch border border-[var(--omr-dropout-soft)] bg-white/60">
    <!-- Commands wrap rather than scroll: a command you can read in full beats one
         you have to drag sideways, and the copy button carries the exact text. -->
    <code
      class="min-w-0 flex-1 px-3 py-2.5 font-mono text-[0.8125rem] leading-relaxed
             break-words whitespace-pre-wrap">{command}</code
    >
    <button
      type="button"
      onclick={copy}
      class="flex shrink-0 items-center gap-1.5 border-l border-[var(--omr-dropout-soft)] px-3
             text-[0.6875rem] font-semibold tracking-[0.12em] uppercase
             text-[var(--omr-graphite-soft)] transition-colors
             hover:bg-[var(--omr-dropout-faint)] hover:text-[var(--omr-graphite)]"
      aria-label={copied ? 'Command copied' : `Copy: ${command}`}
    >
      {#if copied}
        <Check size={14} strokeWidth={2.25} aria-hidden="true" />
        <span>Copied</span>
      {:else}
        <Copy size={14} strokeWidth={2.25} aria-hidden="true" />
        <span>Copy</span>
      {/if}
    </button>
  </div>
</div>
