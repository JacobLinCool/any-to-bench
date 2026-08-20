/** The world's ink, handed to ECharts.
 *
 * ECharts cannot read CSS custom properties, so the tokens are resolved once at
 * runtime. Pre-printed furniture — axes, grid, ring lines, axis names — takes
 * the drop-out ink; the data takes graphite. Same hierarchy as the rest of the
 * page, expressed in the one place Tailwind cannot reach.
 */

export type Palette = {
  graphite: string
  graphiteSoft: string
  dropout: string
  dropoutInk: string
  dropoutSoft: string
  stock: string
  cinnabar: string
}

const TOKENS: Record<keyof Palette, string> = {
  graphite: '--omr-graphite',
  graphiteSoft: '--omr-graphite-soft',
  dropout: '--omr-dropout',
  dropoutInk: '--omr-dropout-ink',
  dropoutSoft: '--omr-dropout-soft',
  stock: '--omr-stock',
  cinnabar: '--omr-cinnabar',
}

/** Server-side rendering has no document; these are the same values app.css declares. */
const FALLBACK: Palette = {
  graphite: '#1b2126',
  graphiteSoft: '#4a555d',
  dropout: '#6fb9cf',
  dropoutInk: '#2e7a92',
  dropoutSoft: '#cbe3ea',
  stock: '#f4f7f8',
  cinnabar: '#d8382a',
}

export function palette(): Palette {
  let resolved = FALLBACK
  if (typeof document !== 'undefined') {
    const style = getComputedStyle(document.documentElement)
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
    resolved = {
      graphite: read(TOKENS.graphite, FALLBACK.graphite),
      graphiteSoft: read(TOKENS.graphiteSoft, FALLBACK.graphiteSoft),
      dropout: read(TOKENS.dropout, FALLBACK.dropout),
      dropoutInk: read(TOKENS.dropoutInk, FALLBACK.dropoutInk),
      dropoutSoft: read(TOKENS.dropoutSoft, FALLBACK.dropoutSoft),
      stock: read(TOKENS.stock, FALLBACK.stock),
      cinnabar: read(TOKENS.cinnabar, FALLBACK.cinnabar),
    }
  }
  return resolved
}

export const MONO =
  "'Spline Sans Mono Variable', ui-monospace, SFMono-Regular, Menlo, monospace"

/** Series are told apart by rule, never by hue: this world has one ink for data.
 * Four rules is the practical ceiling — past that the outlines stop being
 * distinguishable and the chart should carry fewer series instead. */
export const DASH: (string | number[])[] = ['solid', 'dashed', 'dotted', [9, 3, 2, 3]]
export const MAX_SERIES = 4

/** Shared option fragments. Zero radius, no shadow, no easing — the Mark is the
 * only thing in this design that animates. */
export function base(p: Palette) {
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: MONO, color: p.graphiteSoft },
    aria: { enabled: true },
    tooltip: {
      backgroundColor: p.stock,
      borderColor: p.graphite,
      borderWidth: 1,
      borderRadius: 0,
      padding: [8, 10],
      textStyle: { color: p.graphite, fontFamily: MONO, fontSize: 12 },
      extraCssText: 'box-shadow:none;',
    },
  }
}
