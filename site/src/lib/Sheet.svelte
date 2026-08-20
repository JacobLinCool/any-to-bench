<script lang="ts">
  import type { Snippet } from 'svelte'

  /* Card stock lifted off the scanner bed: the one elevation in this world.
   * Registration marks sit at the true corners of the readable area and the
   * timing track runs the left edge — the clock a scanner counts rows by. Both
   * are printed in graphite, the ink the lamp does return. */
  type Props = {
    children: Snippet
    track?: boolean
    ruled?: boolean
    class?: string
  }
  let { children, track = true, ruled = false, class: cls = '' }: Props = $props()
</script>

<div class="sheet registered relative {cls}" class:ruled>
  <span class="registered-marks"></span>
  {#if track}
    <span class="timing-track"></span>
  {/if}
  {@render children()}
</div>
