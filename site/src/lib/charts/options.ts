/** Chart options, framework-free on purpose.
 *
 * The Svelte components and the Node renderer under site/scripts both call
 * these, so a figure in a report and the chart on the page are the same object
 * fed the same data. Nothing here touches the DOM.
 */

import {
  COST_LABEL,
  axisNames,
  byModel,
  costIsTokens,
  effortLabel,
  fmtScore,
  type Average,
  type CostMetric,
  type EntryScore,
} from '../results'
import { DASH, MONO, base, palette, seriesRule, type Palette } from './theme'

export type ChartOptions = {
  cost: CostMetric
  average: Average
  /** A 0–100 axis on scores that all sit above 90 is a row of flat lines. */
  origin?: 'zoom' | 'zero'
  /** From `modelNames` over the whole board, so every chart on a page agrees
   * about which prefixes are droppable. Absent, models print their full id. */
  names?: ReadonlyMap<string, string>
}

/** A model's display name — see `modelNames` for when the prefix survives. */
function modelName(opts: ChartOptions, model: string): string {
  return opts.names?.get(model) ?? model
}

function floor5(value: number): number {
  return Math.max(0, Math.floor(value / 5) * 5)
}

/** Lowest gridline, and the fact that it is not zero, stated rather than implied. */
export function scoreFloor(scores: EntryScore[], origin: 'zoom' | 'zero'): number {
  if (origin === 'zero') return 0
  const values = scores.map((s) => s.score).filter((v): v is number => v !== null)
  if (!values.length) return 0
  return Math.min(floor5(Math.min(...values)), 80)
}

const AXIS = (p: Palette) => ({
  axisLine: { lineStyle: { color: p.dropoutInk, width: 1 } },
  axisTick: { lineStyle: { color: p.dropoutInk } },
  axisLabel: { color: p.dropoutInk, fontFamily: MONO, fontSize: 10 },
  nameTextStyle: { color: p.dropoutInk, fontFamily: MONO, fontSize: 10 },
  splitLine: { lineStyle: { color: p.dropoutSoft, width: 1 } },
})

export function buildParetoOption(scores: EntryScore[], opts: ChartOptions) {
  const p = palette()
  const origin = opts.origin ?? 'zoom'
  const usable = scores.filter((s) => s.score !== null && s.cost > 0)
  const min = scoreFloor(usable, origin)
  const families = byModel(usable)

  /* Model names live in the legend, not on the points. Written on the chart
   * they read better — right up until two models score alike, which is the
   * normal case up here: a name is drawn rightward from its last point and
   * lands on whatever else is scoring 95%. Nudging them apart, folding them
   * into the point label, and labelling only the line ends each bought one
   * more configuration before colliding again. A legend does not degrade as
   * entries accumulate, and it is what the radar on this page already uses.
   * Identity is still on screen and still not behind a pointer. */
  const series: Record<string, unknown>[] = families.map((family, i) => {
    // The legend tells models apart by line rule, and a model that sat one
    // effort has no line to carry one — so that point names itself. Identity
    // goes on the chart exactly where the legend cannot reach it.
    const lone = family.scores.length === 1
    const rule = seriesRule(i)
    return {
      type: 'line',
      name: modelName(opts, family.model),
      data: family.scores.map((s) => ({
        value: [s.cost, s.score],
        name: `${modelName(opts, family.model)} · ${effortLabel(s.entry.effort)}`,
      })),
      symbol: rule.symbol,
      symbolSize: rule.symbol === 'rect' ? [10, 7] : 9,
      itemStyle: { color: p.graphite, borderRadius: 0 },
      lineStyle: { color: p.graphiteSoft, width: 1, type: rule.dash },
      label: {
        show: true,
        position: 'top',
        distance: 8,
        // Otherwise only the ends of the line are named: effort is ordered along
        // it, so the two ends say which way it runs, and the exact value of
        // every point is a row in the table under the chart.
        formatter: (item: { dataIndex: number; data: { name: string } }) => {
          if (lone) return item.data.name
          const ends = item.dataIndex === 0 || item.dataIndex === family.scores.length - 1
          return ends ? (item.data.name.split(' · ')[1] ?? '') : ''
        },
        color: lone ? p.graphite : p.graphiteSoft,
        fontFamily: MONO,
        fontSize: lone ? 11 : 9,
        fontWeight: lone ? 600 : 'normal',
      },
      emphasis: { focus: 'series', lineStyle: { color: p.graphite, width: 2 } },
      labelLayout: { moveOverlap: 'shiftY', hideOverlap: false },
      z: 3,
    }
  })

  // The frontier is a boundary, so it gets the world's boundary weight: 2px graphite.
  const front = usable
    .filter((s) =>
      !usable.some(
        (other) =>
          other !== s &&
          other.cost <= s.cost &&
          (other.score as number) >= (s.score as number) &&
          (other.cost < s.cost || (other.score as number) > (s.score as number)),
      ),
    )
    .sort((a, b) => a.cost - b.cost)
  if (front.length > 1) {
    series.unshift({
      type: 'line',
      name: 'frontier',
      step: 'end',
      data: front.map((s) => [s.cost, s.score]),
      symbol: 'none',
      lineStyle: { color: p.graphite, width: 2 },
      silent: true,
      z: 1,
    })
  }

  const spreads = usable.filter((s) => s.spread !== null)
  if (spreads.length) {
    series.push({
      type: 'custom',
      name: 'spread',
      silent: true,
      z: 2,
      data: spreads.map((s) => [s.cost, s.score, s.spread]),
      renderItem: (_params: unknown, api: ChartApi) => {
        const centre = api.value(1) as number
        const sd = api.value(2) as number
        const [x = 0] = api.coord([api.value(0), centre])
        const [, yTop = 0] = api.coord([api.value(0), centre + sd])
        const [, yBottom = 0] = api.coord([api.value(0), centre - sd])
        const style = { stroke: p.graphiteSoft, lineWidth: 1, fill: 'none' }
        return {
          type: 'group',
          children: [
            { type: 'line', shape: { x1: x, y1: yTop, x2: x, y2: yBottom }, style },
            { type: 'line', shape: { x1: x - 3, y1: yTop, x2: x + 3, y2: yTop }, style },
            { type: 'line', shape: { x1: x - 3, y1: yBottom, x2: x + 3, y2: yBottom }, style },
          ],
        }
      },
    })
  }

  return {
    ...base(p),
    grid: { left: 58, right: 40, top: 24, bottom: 52 + 18 * families.length },
    legend: {
      bottom: 0,
      orient: 'vertical',
      left: 'center',
      itemGap: 6,
      textStyle: { color: p.graphiteSoft, fontFamily: MONO, fontSize: 11 },
      // A key, not a control: the frontier is computed from every entry on the
      // chart, so letting the legend hide one would leave a boundary drawn
      // through points nobody can see. Filtering belongs to the picker, which
      // recomputes the whole thing.
      selectedMode: false,
      // Wide enough that the rule either side of the symbol is legible — the
      // rule is the only thing telling two models apart in a one-ink world.
      itemWidth: 38,
      itemHeight: 8,
      data: families.map((family) => modelName(opts, family.model)),
    },
    xAxis: {
      ...AXIS(p),
      type: costIsTokens(opts.cost) ? 'log' : 'value',
      name: COST_LABEL[opts.cost],
      nameLocation: 'middle',
      nameGap: 32,
      splitLine: { show: false },
    },
    yAxis: {
      ...AXIS(p),
      type: 'value',
      min,
      max: 100,
      name: min > 0 ? `score % — axis starts at ${min}%` : 'score %',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: { ...AXIS(p).axisLabel, formatter: '{value}%' },
    },
    tooltip: {
      ...base(p).tooltip,
      trigger: 'item',
      formatter: (item: { data: { name?: string; value: number[] } }) => {
        const [x = 0, y = 0] = item.data.value ?? []
        const label = item.data.name ?? ''
        return `${label}<br>${fmtScore(y)}% · ${x.toLocaleString()} ${COST_LABEL[opts.cost]}`
      },
    },
    series,
  }
}

type ChartApi = {
  coord: (values: unknown[]) => number[]
  value: (index: number) => unknown
}

/** The inner edge of the rings.
 *
 * Exported because small multiples have to share it: panels drawn on different
 * scales are shapes that cannot be compared, which is the one thing a wall of
 * them is for.
 */
export function radarFloor(scores: EntryScore[], origin: 'zoom' | 'zero' = 'zoom'): number {
  if (origin === 'zero') return 0
  const perPaper = scores.flatMap((s) => s.papers.map((paper) => paper.percentage ?? 100))
  return Math.min(floor5(Math.min(100, ...perPaper)), 80)
}

type RadarOptions = ChartOptions & {
  grouped?: boolean
  /** Pin the scale — see radarFloor. */
  floor?: number
  /** One panel of a wall: no legend, and the caption is HTML outside the chart. */
  solo?: boolean
}

export function buildRadarOption(
  scores: EntryScore[],
  subsets: string[],
  opts: RadarOptions,
) {
  const p = palette()
  const min = opts.floor ?? radarFloor(scores, opts.origin ?? 'zoom')

  /* A solo panel is small, so its axis names are the first thing to go: past a
   * handful of axes they collide into a grey ring and stop being labels at all.
   * The panels share an axis order, so the wall still reads by position, and
   * the table under it names every column. */
  const named = !opts.solo || subsets.length <= 6
  const names = axisNames(subsets)
  const indicator = subsets.map((_, i) => ({ name: named ? names[i]! : '', min, max: 100 }))

  const series = {
    type: 'radar',
    symbol: 'rect',
    symbolSize: opts.solo ? [5, 4] : [7, 5],
    data: scores.map((s, i) => ({
      name: `${modelName(opts, s.entry.model)} · ${effortLabel(s.entry.effort)}`,
      value: subsets.map(
        (subset) => s.papers.find((paper) => paper.subset === subset)?.percentage ?? null,
      ),
      itemStyle: { color: p.graphite },
      lineStyle: {
        color: opts.solo ? p.graphite : p.graphiteSoft,
        width: 1,
        type: opts.solo ? 'solid' : DASH[i % DASH.length],
      },
      areaStyle: undefined,
      emphasis: { lineStyle: { color: p.graphite, width: 2 } },
    })),
  }

  const radar = {
    shape: 'polygon',
    radius: opts.solo ? (named ? '58%' : '76%') : '62%',
    center: ['50%', opts.solo ? '50%' : '44%'],
    indicator,
    axisName: { color: p.dropoutInk, fontFamily: MONO, fontSize: 10 },
    axisLine: { lineStyle: { color: p.dropoutSoft } },
    splitLine: { lineStyle: { color: p.dropoutSoft } },
    splitArea: { show: false },
  }

  /* ECharts prints the raw value, and a paper marked out of nine arrives here as
   * 44.44444444444444 — so the rows are written by hand to run through
   * fmtScore. Naming them here also covers the solo panel, whose ring is too
   * small to carry axis labels: the value still says which subject it is. */
  const tooltip = {
    ...base(p).tooltip,
    trigger: 'item',
    formatter: (item: { name: string; value: (number | null)[] }) => {
      const rows = names.map((name, i) => {
        const value = item.value?.[i]
        const mark = value === null || value === undefined ? '–' : `${fmtScore(value)}%`
        return (
          '<div style="display:flex;gap:24px;justify-content:space-between">' +
          `<span>${name}</span><span style="font-weight:600">${mark}</span></div>`
        )
      })
      return `<div style="margin-bottom:4px">${item.name}</div>${rows.join('')}`
    },
  }

  if (opts.solo) {
    return { ...base(p), radar, tooltip, series: [series] }
  }

  return {
    ...base(p),
    radar,
    legend: {
      bottom: 0,
      orient: 'vertical',
      left: 'center',
      itemGap: 6,
      textStyle: { color: p.graphiteSoft, fontFamily: MONO, fontSize: 11 },
      inactiveColor: p.dropoutInk,
      itemWidth: 20,
      itemHeight: 8,
      data: scores.map((s) => `${modelName(opts, s.entry.model)} · ${effortLabel(s.entry.effort)}`),
    },
    tooltip,
    series: [series],
  }
}
