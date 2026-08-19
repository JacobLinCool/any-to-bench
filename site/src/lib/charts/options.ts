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
  effortLabel,
  type Average,
  type CostMetric,
  type EntryScore,
} from '../results'
import { DASH, MONO, base, palette, type Palette } from './theme'

export type ChartOptions = {
  cost: CostMetric
  average: Average
  /** A 0–100 axis on scores that all sit above 90 is a row of flat lines. */
  origin?: 'zoom' | 'zero'
  scanning?: boolean
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
  const p = palette(opts.scanning)
  const origin = opts.origin ?? 'zoom'
  const usable = scores.filter((s) => s.score !== null && s.cost > 0)
  const min = scoreFloor(usable, origin)
  const families = byModel(usable)

  const series: Record<string, unknown>[] = families.map((family, i) => ({
    type: 'line',
    name: family.model,
    data: family.scores.map((s) => ({
      value: [s.cost, s.score],
      name: `${family.model} · ${effortLabel(s.entry.effort)}`,
    })),
    symbol: 'rect',
    symbolSize: [10, 7],
    itemStyle: { color: p.graphite, borderRadius: 0 },
    lineStyle: { color: p.graphiteSoft, width: 1, type: DASH[i % DASH.length] },
    label: {
      show: true,
      position: 'top',
      distance: 8,
      formatter: (item: { data: { name: string } }) => item.data.name.split(' · ')[1] ?? '',
      color: p.graphiteSoft,
      fontFamily: MONO,
      fontSize: 9,
    },
    // Identity belongs on the chart, not behind a pointer.
    endLabel: {
      show: true,
      distance: 9,
      formatter: family.model,
      color: p.graphite,
      fontFamily: MONO,
      fontSize: 11,
      fontWeight: 600,
    },
    emphasis: { focus: 'series', lineStyle: { color: p.graphite, width: 2 } },
    z: 3,
  }))

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
    grid: { left: 58, right: 132, top: 24, bottom: 52 },
    xAxis: {
      ...AXIS(p),
      type: opts.cost === 'output' ? 'log' : 'value',
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
        return `${label}<br>${y.toFixed(1)}% · ${x.toLocaleString()} ${COST_LABEL[opts.cost]}`
      },
    },
    series,
  }
}

type ChartApi = {
  coord: (values: unknown[]) => number[]
  value: (index: number) => unknown
}

export function buildRadarOption(
  scores: EntryScore[],
  subsets: string[],
  opts: ChartOptions & { grouped?: boolean },
) {
  const p = palette(opts.scanning)
  const origin = opts.origin ?? 'zoom'
  const perPaper = scores.flatMap((s) => s.papers.map((paper) => paper.percentage ?? 100))
  const min = origin === 'zero' ? 0 : Math.min(floor5(Math.min(100, ...perPaper)), 80)

  const names = axisNames(subsets)
  const indicator = subsets.map((_, i) => ({ name: names[i]!, min, max: 100 }))

  return {
    ...base(p),
    radar: {
      shape: 'polygon',
      radius: '62%',
      center: ['50%', '44%'],
      indicator,
      axisName: { color: p.dropoutInk, fontFamily: MONO, fontSize: 10 },
      axisLine: { lineStyle: { color: p.dropoutSoft } },
      splitLine: { lineStyle: { color: p.dropoutSoft } },
      splitArea: { show: false },
    },
    legend: {
      bottom: 0,
      orient: 'vertical',
      left: 'center',
      itemGap: 6,
      textStyle: { color: p.graphiteSoft, fontFamily: MONO, fontSize: 11 },
      inactiveColor: p.dropoutInk,
      itemWidth: 20,
      itemHeight: 8,
      data: scores.map((s) => `${s.entry.model} · ${effortLabel(s.entry.effort)}`),
    },
    tooltip: { ...base(p).tooltip, trigger: 'item' },
    series: [
      {
        type: 'radar',
        symbol: 'rect',
        symbolSize: [7, 5],
        data: scores.map((s, i) => ({
          name: `${s.entry.model} · ${effortLabel(s.entry.effort)}`,
          value: subsets.map(
            (subset) => s.papers.find((paper) => paper.subset === subset)?.percentage ?? null,
          ),
          itemStyle: { color: p.graphite },
          lineStyle: { color: p.graphiteSoft, width: 1, type: DASH[i % DASH.length] },
          areaStyle: undefined,
          emphasis: { lineStyle: { color: p.graphite, width: 2 } },
        })),
      },
    ],
  }
}
