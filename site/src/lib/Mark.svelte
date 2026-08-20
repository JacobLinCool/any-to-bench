<script lang="ts">
  /* The atom of this world. Taiwanese answer cards are filled squares, not
   * bubbles — the printed instruction reads 用 2B 鉛筆塗滿方格，但不超出格外
   * ("fill the square with a 2B pencil, but not outside it"). The empty square is
   * pre-printed in the drop-out ink; the graphite fill is what the machine reads.
   *
   * Geometry lives in this component's own CSS rather than in utility classes.
   * Every mark once rendered 0×0 because an unanchored `lib/` in .gitignore hid
   * this whole directory from Tailwind's source detection; owning the geometry
   * here means no scanner decision can flatten the world's atom again. */
  type Props = {
    filled?: boolean
    label?: string
    size?: 'sm' | 'md' | 'lg'
  }
  let { filled = false, label, size = 'md' }: Props = $props()
</script>

<span class="wrap">
  <span
    class="mark"
    class:is-filled={filled}
    data-size={size}
    aria-hidden="true"
  ></span>
  {#if label}
    <span class="mark-label">{label}</span>
  {/if}
</span>

<style>
  .wrap {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }
  .mark {
    position: relative;
    display: inline-block;
    flex: none;
    /* The outline is pre-printed: it drops out under the lamp. */
    box-shadow: inset 0 0 0 1.5px var(--omr-dropout-ink);
    transition: box-shadow 220ms cubic-bezier(0.16, 1, 0.3, 1);
  }
  .mark[data-size='sm'] {
    width: 1.25rem;
    height: 0.875rem;
  }
  .mark[data-size='md'] {
    width: 1.75rem;
    height: 1.25rem;
  }
  .mark[data-size='lg'] {
    width: 2.5rem;
    height: 1.75rem;
  }
  .mark::after {
    content: '';
    position: absolute;
    inset: 2px;
    background: var(--omr-graphite);
    transform: scale(0.15);
    opacity: 0;
    transition:
      transform 320ms cubic-bezier(0.16, 1, 0.3, 1),
      opacity 200ms ease-out;
  }
  .mark.is-filled::after {
    transform: scale(1);
    opacity: 1;
  }
  .mark-label {
    font-size: 0.8125rem;
    letter-spacing: 0.01em;
    color: var(--omr-graphite-soft);
  }
</style>
