/** The only module that pulls ECharts in.
 *
 * Static imports, so the bundler keeps just the three series and three
 * components actually drawn; the module is loaded dynamically by EChart.svelte,
 * so the leaderboard table — the page's substance — never waits on a plotting
 * library.
 */

import { CustomChart, LineChart, RadarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { init as echartsInit, use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'

use([
  LineChart,
  RadarChart,
  CustomChart, // the error bars, drawn only when a run was repeated
  GridComponent,
  TooltipComponent,
  LegendComponent,
  SVGRenderer,
])

export type Chart = {
  setOption: (option: unknown, opts?: unknown) => void
  resize: () => void
  dispose: () => void
}

export function init(host: HTMLDivElement): Chart {
  return echartsInit(host, null, { renderer: 'svg' }) as unknown as Chart
}

/** The same option object, rendered to a standalone SVG string.
 *
 * This is why the option builders are framework-free: a figure in a report and
 * the chart on the page come out of one function fed one dataset, so they can
 * never drift apart.
 */
export function renderToSvg(option: unknown, width = 900, height = 520): string {
  const chart = echartsInit(null as unknown as HTMLDivElement, null, {
    renderer: 'svg',
    ssr: true,
    width,
    height,
  }) as unknown as Chart & { renderToSVGString: () => string }
  chart.setOption(option)
  const svg = chart.renderToSVGString()
  chart.dispose()
  return svg
}
