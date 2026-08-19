<script lang="ts">
  /** A chart is a rendering of an option object, so this wrapper owns nothing
   * but the canvas-less SVG surface, its size, and the scanner repaint. Every
   * decision about what is drawn lives in lib/charts/options.ts, which the
   * static renderer calls too. */
  /* The engine module is imported dynamically: the leaderboard table is the
     page's substance and must not wait on a plotting library. */
  import type { Chart } from './charts/engine'

  type Props = {
    option: Record<string, unknown>
    height?: string
    label: string
    description: string
  }
  let { option, height = '26rem', label, description }: Props = $props()

  let host = $state<HTMLDivElement | null>(null)
  let chart = $state<Chart | null>(null)
  const id = `chart-${Math.random().toString(36).slice(2, 8)}`

  $effect(() => {
    if (!host) return
    let live = true
    let instance: Chart | null = null
    let observer: ResizeObserver | null = null
    void import('./charts/engine').then(({ init }) => {
      if (!live || !host) return
      const made = init(host)
      instance = made
      chart = made
      observer = new ResizeObserver(() => made.resize())
      observer.observe(host)
    })
    return () => {
      live = false
      observer?.disconnect()
      instance?.dispose()
      chart = null
    }
  })

  // notMerge, because a scanner toggle re-colours every element: merging would
  // leave the old furniture visible under the new palette.
  $effect(() => {
    chart?.setOption(option, { notMerge: true })
  })
</script>

<figure class="m-0">
  <!-- The description is a sibling rather than an attribute: aria-description is
       not supported on role="img", and a real caption also serves the table below. -->
  <div bind:this={host} style:height role="img" aria-label={label} aria-describedby={id}></div>
  <figcaption {id} class="sr-only">{description}</figcaption>
</figure>
