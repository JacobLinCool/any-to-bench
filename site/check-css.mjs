/* Fail the build if the world's furniture did not reach the stylesheet.
 *
 * Tailwind emits `@utility` rules only where its scanner sees the name used, and
 * it has silently dropped ours twice: the mark's sizes (built by indexing an
 * object of class strings) and then the card's registration marks and timing
 * track. Both shipped looking fine in review and rendering as nothing. A grep of
 * the built CSS is cheap and catches the whole class of failure.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const DIR = 'dist/assets'
// One utility sourced from src/lib is included on purpose: a .gitignore rule
// once hid that whole directory from Tailwind's source detection, and every
// class in it vanished from the build without a single error.
const REQUIRED = [
  'gap-x-8',
  'sheet',
  'registered-marks',
  'timing-track',
  'ruled',
  'field-label',
  'han',
  'scanning',
  'drops-out',
]

const css = readdirSync(DIR)
  .filter((f) => f.endsWith('.css'))
  .map((f) => readFileSync(join(DIR, f), 'utf8'))
  .join('\n')

const missing = REQUIRED.filter((name) => !css.includes(`.${name}`))
if (missing.length) {
  console.error(`Built CSS is missing: ${missing.join(', ')}`)
  console.error('These are the design system’s own classes; a page without them is not the design.')
  process.exit(1)
}
console.log(`css check: all ${REQUIRED.length} world classes present`)
