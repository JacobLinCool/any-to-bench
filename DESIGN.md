---
name: any-to-bench
description: An OMR answer card on a scanner bed — the pre-printed structure is in an ink the machine cannot see, and only the marks count.
colors:
  stock: "#f4f7f8"
  stock-shaded: "#e4eef2"
  bed: "#161c21"
  bed-deep: "#0d1215"
  bed-content: "#d7e5ea"
  graphite: "#1b2126"
  graphite-soft: "#4a555d"
  dropout: "#6fb9cf"
  dropout-ink: "#2e7a92"
  dropout-soft: "#cbe3ea"
  dropout-faint: "#e2f0f4"
  cinnabar: "#d8382a"
  cinnabar-ink: "#c22e21"
  cinnabar-deep: "#b92c20"
typography:
  display:
    fontFamily: "'Archivo Variable', ui-sans-serif, system-ui, 'PingFang TC', 'Noto Sans TC', sans-serif"
    fontSize: "clamp(2.6rem, 7.2vw, 5.4rem)"
    fontWeight: 800
    lineHeight: 0.94
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "'Archivo Variable', ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.75rem, 3.4vw, 2.75rem)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  title:
    fontFamily: "'Archivo Variable', ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "normal"
  body:
    fontFamily: "'Archivo Variable', ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.625
    letterSpacing: "normal"
  label:
    fontFamily: "'Archivo Variable', ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.14em"
  mono:
    fontFamily: "'Spline Sans Mono Variable', ui-monospace, 'PingFang TC', monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.625
    letterSpacing: "normal"
    fontFeature: "tabular-nums"
  han:
    fontFamily: "'PingFang TC', 'Noto Sans TC', 'Hiragino Sans CNS', 'Microsoft JhengHei', sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.9
    letterSpacing: "normal"
rounded:
  none: "0px"
spacing:
  hairline: "1px"
  grid: "28px"
  page: "1rem"
  page-wide: "2rem"
  sheet: "1.5rem"
  sheet-wide: "3rem"
  sheet-full: "4rem"
  stack: "1.5rem"
components:
  sheet:
    backgroundColor: "{colors.stock}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "2rem 1.5rem"
  button-commit:
    backgroundColor: "{colors.cinnabar}"
    textColor: "#ffffff"
    rounded: "{rounded.none}"
    padding: "1rem 1.75rem"
    typography: "{typography.body}"
  button-commit-hover:
    backgroundColor: "{colors.cinnabar-deep}"
  button-seal:
    backgroundColor: "transparent"
    textColor: "{colors.cinnabar-ink}"
    rounded: "{rounded.none}"
    padding: "0.5rem 0.875rem"
    typography: "{typography.label}"
  button-seal-hover:
    backgroundColor: "{colors.cinnabar}"
    textColor: "#ffffff"
  button-seal-broken:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.stock}"
  button-state:
    backgroundColor: "transparent"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0.5rem 0.875rem"
    typography: "{typography.label}"
  button-state-on:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.stock}"
  button-solid:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.stock}"
    rounded: "{rounded.none}"
    padding: "0 1rem"
  button-solid-hover:
    backgroundColor: "{colors.cinnabar}"
  input-field:
    backgroundColor: "rgb(255 255 255 / 0.7)"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0.625rem 0.75rem"
    typography: "{typography.mono}"
  mark:
    backgroundColor: "transparent"
    rounded: "{rounded.none}"
    width: "1.75rem"
    height: "1.25rem"
  mark-filled:
    backgroundColor: "{colors.graphite}"
  register-stub:
    backgroundColor: "{colors.stock}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0.75rem 1rem"
    typography: "{typography.mono}"
  register-stub-hover:
    backgroundColor: "{colors.dropout-faint}"
  rail-row:
    backgroundColor: "transparent"
    textColor: "{colors.graphite-soft}"
    rounded: "{rounded.none}"
    padding: "0.3rem 0.45rem"
  rail-row-active:
    backgroundColor: "{colors.dropout-faint}"
    textColor: "{colors.graphite}"
  key-panel:
    backgroundColor: "{colors.dropout-faint}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.none}"
    padding: "0.875rem 1rem"
---

# Design System: any-to-bench

**Scope: the `site/` web surface only.** This system governs the landing page
(`site/src/App.svelte`), the bundle viewer (`site/src/Viewer.svelte`), and the shared
components in `site/src/lib/`. It does not govern the Python CLI, `docs/`, or the README;
those have no visual system and should not be given one from this file.

## Overview

**Creative North Star: "The Answer Card"**

The surface is a Taiwanese OMR answer card lying on a scanner bed. Everything a candidate
is given — the grid, the rules, the field captions, the option letters — is pre-printed in
a cyan the scanner's lamp does not return, so it exists only for the human. Everything that
counts is graphite: the filled square, the question number, the words of the paper itself.
The product does the same thing to an exam, and the interface argues by being the thing it
describes. A visitor can prove the claim in one click: scanner view is a real document state
that zeroes the drop-out ink and leaves the marks standing alone.

Density is high and unapologetically clerical. Content sits on cool card stock lifted off a
near-black bed by the single shadow in the whole system; the stock never rounds, never
gains a second shadow, and never floats over a gradient. Type is Archivo for everything
Latin and structural, Spline Sans Mono for every number that identifies something, and a
Traditional Chinese face leading the stack wherever real exam prose appears — the papers
are in Chinese, and the design treats that as the primary reading case rather than an i18n
afterthought. Numerals are tabular everywhere, because columns of them are the point.

This world refuses three things by name: the dev-tool dark hero (the dark is a scanner bed,
and content never sits on it), exam-paper pastiche (no fake staples, coffee rings, torn
edges, or handwriting fonts), and stock DaisyUI (radii, depth, and noise are all zeroed in
a custom `omr` theme so the component library cannot speak in its own accent).

**Key Characteristics:**

- Zero radii throughout — card stock is guillotined, not rounded.
- Exactly one elevation in the system: stock lifting off the bed.
- Two-tier inks: a fill tier and a contrast-checked reading tier for both cyan and cinnabar.
- Cinnabar is rationed to commitment, the seal over an answer key, and refusal.
- Hairline seams (1px) instead of margins wherever cells meet.
- Tabular numerals globally; mono for every identifying number.
- One authored motion moment: graphite growing into a square.

## Colors

Cool, printed, and three-voiced: a cyan that the machine cannot see, a graphite that is
everything the machine can, and a cinnabar spent only where something is committed or
refused.

### Primary

- **Cinnabar** (#d8382a): The act that commits. It appears on the landing page's single
  primary action, on the sealed-key control, and as the focus-visible outline and caret
  color. As a fill it carries white text (4.65:1). Its scarcity is the whole point — on the
  landing page's first viewport it appears exactly once, sitting where a card is signed.
- **Cinnabar Ink** (#c22e21): The same red wherever it must be *read* rather than filled —
  the sealed-key button's label and border, matching-rule answer arrows, error glyphs.
  5.26:1 on stock.
- **Cinnabar Deep** (#b92c20): The hover darkening under white text on the primary action.
  It is currently written literally at its two call sites rather than declared in `:root`;
  promote it to a custom property before a third use invents a fourth red.

### Secondary

- **Drop-Out Cyan** (#6fb9cf): The ink the scanner is blind to. It owns every pre-printed
  thing: the measuring grid, dividing rules, the footer's link row on the bed, the dot
  separators between question metadata. Never used for anything a grader depends on.
- **Drop-Out Ink** (#2e7a92): Drop-out cyan where it must still be legible — field labels,
  register stub numbers, the hairline outline of an unfilled mark. 4.52:1 on stock, so the
  OWN-WORLD claim is readable before the visitor ever touches the scanner toggle.
- **Drop-Out Soft** (#cbe3ea): The printed hairline. Every cell seam, table row rule, and
  panel border in the light parts of the interface.
- **Drop-Out Faint** (#e2f0f4): The printed tint. The ground of an opened answer key, a
  hovered register stub, and the travelling band in the viewer's question rail.

### Neutral

- **Graphite** (#1b2126): Content that counts. Headlines, question numbers, exam prose, the
  filled mark, and the heavy 2px rules that separate a total from its rows.
- **Graphite Soft** (#4a555d): Supporting prose, captions, point values, and any label that
  is graphite in role but secondary in rank.
- **Card Stock** (#f4f7f8): Every surface a word is read on.
- **Stock Shaded** (#e4eef2): The shaded zone of the stock; available for a second-order
  panel, used sparingly.
- **Scanner Bed** (#161c21) / **Bed Deep** (#0d1215): The page ground and the scrollbar
  track. The bed is where the card lies; long-form content is never set directly on it.
- **Bed Content** (#d7e5ea): The only text color permitted on the bed — the footer's
  issuing block.

### Named Rules

**The Drop-Out Rule.** Anything pre-printed — grids, rules, field captions, option letters,
stub numbers, ordinal markers — is drawn in a drop-out token and carries `.drops-out` when
it is an element rather than a border. Anything a score depends on is graphite. If you
cannot say which side a new element is on, it does not belong on the card.

**The Two-Ink Rule.** Every accent has a fill tier and a reading tier, and they are not
interchangeable. Cyan fills with `dropout`, reads with `dropout-ink`. Cinnabar fills with
`cinnabar`, reads with `cinnabar-ink`. Text and hairlines take the reading tier; areas take
the fill tier. Never set body-sized text in a fill-tier ink.

**The Reserved Cinnabar Rule.** Cinnabar is spent on three things only: the act that commits
(the primary action), the seal over an answer key, and refusal (focus rings, carets, error
marks). It is never used for emphasis, decoration, hover warmth, or active navigation — the
viewer's travelling band is graphite plus the printed tint for exactly this reason.

## Typography

**Display / Body Font:** Archivo Variable (with `ui-sans-serif`, `system-ui`)
**Label / Mono Font:** Spline Sans Mono Variable (with `ui-monospace`)
**Exam Prose Font:** PingFang TC → Noto Sans TC → Hiragino Sans CNS → Microsoft JhengHei

**Character:** Archivo is a grotesque with enough width and weight range to set a headline
at 800 that still reads as printed instruction rather than marketing. Spline Sans Mono
supplies the clerical register: every number that identifies something is monospaced and
tabular, so a column of question numbers or point values lines up the way it does on a real
card. The Han face leads its own stack because the exams are Traditional Chinese and that
prose is the primary reading material, not a fallback.

### Hierarchy

- **Display** (800, `clamp(2.6rem, 7.2vw, 5.4rem)`, 0.94, −0.04em): One per page, on the
  issued card. Tightly tracked and set to a `19ch` measure with `text-balance` so it breaks
  like a printed heading, not a paragraph.
- **Headline** (700, `clamp(1.75rem, 3.4vw, 2.75rem)`, 1.05, −0.03em): Section heads. The
  viewer's own first-run heading is the same voice one step smaller
  (`clamp(2.1rem, 5vw, 3.6rem)` at 800).
- **Title** (600, 1.125rem, 1.4): In-panel headings. Exam section titles use the same rank
  at 1.25rem in the Han face, because they are exam content rather than interface chrome.
- **Body** (400, 1rem, 1.625): Prose, capped at a 62–68ch measure. The landing lede steps up
  to 1.125rem; supporting copy inside panels steps down to 0.9375rem.
- **Label** (600, 0.6875rem, +0.14em, uppercase): The `field-label` — a printed field
  caption. It names what a value *is*: Form, Reads, Graded by rule, Official key, and every
  table column head. It is set in drop-out ink, so it disappears under the scanner lamp.
- **Mono** (400/600, 0.6875–1.875rem, tabular): Question numbers, stub numbers, point
  values, bundle names, dataset ids, commands, and JSON. Question numbers are the loud end
  of this ramp (1.5rem rising to 1.875rem), semibold, and graphite.
- **Han** (400, 0.9375–1rem, 1.9): Exam prose, options, instructions, and table cells drawn
  from a bundle.

### Named Rules

**The Tabular Rule.** `font-variant-numeric: tabular-nums` is set on `body` and is never
overridden. Any number that identifies a thing — question, stub, score, count — is set in
the mono face; any number inside a sentence stays in Archivo.

**The Han Lead Rule.** Third-party exam content is wrapped in `.han`: the TC face leads,
line-height opens to 1.9, and `overflow-wrap: anywhere` is mandatory. A bundle is untrusted
input, and one unbroken token must never set the width of the page.

**The Field Caption Rule.** Uppercase letterspaced type exists in exactly one role: a
printed field caption naming the value directly beneath or beside it. It is never used as a
kicker above a headline, as a section eyebrow, or as button text on a primary action.

## Layout

The page is a stack of cards on a bed. A single centered column — `76rem` on the landing
page, `82rem` in the viewer — sits inside a `1rem` page gutter that opens to `2rem` from the
`sm` breakpoint (640px). Cards are separated by a `1.5rem` stack gap that opens to `2.5rem`
on the landing page at `sm`. Card interiors run `1.5rem` padding on mobile, `3rem` at `sm`,
and `4rem` at `lg` (1024px) for the widest sheets.

Inside a card, related cells are laid out as a CSS grid with `gap: 1px` over a
`dropout-soft` ground, so the seam between two cells is a printed hairline rather than
whitespace — the pipeline row, the reads/writes comparison, the two-paths block, and the
register grid are all built this way. The `.ruled` measuring grid is a 28px module; content
placed on it aligns to it, and it is the only patterned ground in the system.

The viewer's reading layout is a `15rem` rail beside a fluid column at `lg`, with the rail
sticky at `1.5rem` from the top and stacking above the paper below `lg`. Wide content that
cannot shrink — tables, KaTeX display math, code blocks — scrolls inside its own
`overflow-x: auto` box; the document itself never scrolls sideways.

**The Hairline Seam Rule.** Where cells meet, the border belongs to the container and the
gap is 1px of `dropout-soft` showing through. A section that ends mid-row still closes with
a rule across its full width, the way a printed register does.

## Elevation & Depth

This system has one shadow and no others. DaisyUI's `--depth` and `--noise` are both set to
`0`, and no component adds elevation of its own. Depth is the physical relationship between
two materials: near-black bed below, cool stock above, lit from the top.

### Shadow Vocabulary

- **The Sheet** (`box-shadow: 0 1px 0 color-mix(in oklab, #fff 55%, transparent) inset, 0 18px 44px -18px rgb(0 0 0 / 0.72), 0 2px 6px -2px rgb(0 0 0 / 0.45)`):
  Card stock lifted off the scanner bed. The inset top hairline is the lit top edge of the
  stock; the two offset shadows are its cast shadow. Applied by `.sheet` and nowhere else.

**The One Elevation Rule.** There is exactly one shadow in this world and it means "this is
the card". Hover does not lift, modals do not float higher, and nothing gains a second
shadow to signal importance. State is signalled by ink and rule, never by altitude.

**The No Halo Rule.** The sheet shadow is offset and blurred, in that order. A zero-offset
glow around a surface is a screen effect; stock on a bed casts its shadow downward.

## Shapes

Every radius in the system is `0`, enforced at the theme level (`--radius-selector`,
`--radius-field`, `--radius-box` all zero) so nothing inherits a rounded corner from the
component library. The form language is orthogonal throughout: rectangles, hairlines, and
the wide-rectangle mark.

Three weights of rule carry structure. A 1px `dropout-soft` hairline divides peers (table
rows, list items, cell seams). A 1px `dropout-ink` line marks a printed margin (section
instructions are set behind one). A 2px graphite rule marks a real boundary — the signature
strip, a table's header and total rows, and the top edge of an opened answer key.

The mark itself is the system's signature geometry: a wide rectangle, not a bubble
(`1.25rem × 0.875rem` small, `1.75rem × 1.25rem` default, `2.5rem × 1.75rem` large), outlined
with a 1.5px inset drop-out hairline and filled by an inset-2px graphite block. Taiwanese
answer cards instruct candidates to fill a square, and the shape is that square.

**The Zero Radius Rule.** Nothing rounds. If a control looks like it needs a radius to feel
finished, it needs different padding or a different rule weight instead.

## Components

### The Sheet (signature component)

The card itself, and the only container in the system. Stock ground, graphite text, no
radius, the one shadow. It draws its own registration marks — four 14×3px graphite ticks
inset 14px from each corner, marking the true edges of the readable area — and, unless
suppressed, a timing track down the left edge (3px wide, 6px-on/8px-off, inset 7px, 70%
opacity), the clock a scanner counts rows by. Both are printed in graphite, so both survive
scanner view. Compact sheets used as toolbars or rails turn the track off; sheets holding a
paper keep it. Padding is set per instance from the sheet spacing steps.

### The Mark (signature component)

The atom of the world. An unfilled mark is a drop-out hairline outline; a filled mark is a
graphite block. It is the only place motion is authored: the fill scales from `0.15` to `1`
over 320ms on `cubic-bezier(0.16, 1, 0.3, 1)` with a 200ms opacity fade. It carries meaning
everywhere it appears — a pipeline step, a correct option once the seal is broken, a
question that grades by script rather than by judge. It owns its geometry in component CSS
rather than in utility classes, deliberately (see the Do's).

### Buttons

- **Shape:** Square (0 radius), 1px borders where bordered.
- **Commit (primary):** Cinnabar fill, white text, `1rem 1.75rem` padding, semibold. On
  hover it darkens to cinnabar deep and the label gains `0.01em` of tracking with the arrow
  advancing 4px. One per page, placed where a card is signed.
- **Seal:** The key-revealing control. Sealed, it is an outlined cinnabar-ink label on
  nothing; hovered, it fills cinnabar with white text; broken, it inverts to a graphite
  fill with stock text. This is the only three-state control in the system and the only
  non-primary use of cinnabar.
- **State toggle:** Scanner view. Off, a graphite label inside a 26%-graphite hairline;
  hovered, a 7% graphite wash; on, a solid graphite fill with stock text. `aria-pressed`
  carries the state.
- **Solid:** The viewer's submit button. Graphite fill, stock text, joined to its input with
  a shared border (`border-l-0`); hover flips the fill to cinnabar because submitting is a
  commit.
- **Underlined link:** A graphite label over a 2px graphite bottom rule that shifts to
  drop-out ink on hover. Used for the secondary route out of a section.

### Inputs / Fields

- **Style:** A 1px border (graphite for a primary field, dropout-soft for a filter) over a
  70%-white well on stock, mono type, `0.625rem 0.75rem` padding, no radius.
- **Focus:** The border turns cinnabar and the native outline is suppressed on the field
  itself; every other focusable element takes the global 2px cinnabar outline at 2px offset.
- **Caret:** Cinnabar, everywhere.

The same 70%-white well is the ground for read-only code: `pre` blocks and the copy line
both sit on it inside a dropout-soft hairline. It is the one recurring surface value that
is not yet a named token.

### Register Stub

The viewer's list of issued bundles: a grid of stubs, each a drop-out ordinal in mono, then
a truncated bundle name in mono, on stock, bordered right and bottom so the grid reads as
ruled paper. Hover tints to drop-out faint. Stubs are numbered against their full section
and the number does not change as the filter narrows the list.

### Question Rail

A sticky column of rows, one per question: mono number on the left, mark on the right. Hover
tints; the active row takes a graphite left hairline, the printed tint, and semibold weight.
Transitions are 160ms `ease-out` on color only.

### Key Panel

The revealed answer key: a 2px graphite top rule over a drop-out faint ground with a field
caption reading "Official key". The same construction carries ingest warnings. It is the
system's one "this is authoritative" container.

### Copy Line

A command in mono on the white well, wrapping rather than scrolling, with a bordered copy
button on its right edge that swaps its icon and label to a check and "Copied" for 1.6s.

## Do's and Don'ts

### Do:

- **Do** keep the world's furniture (`.sheet`, `.registered`, `.registered-marks`,
  `.timing-track`, `.ruled`, `.field-label`, `.han`, `.scanning`, `.drops-out`) as plain
  global CSS in `app.css`, and let components own their own geometry in component `<style>`.
  Tailwind emits `@utility` rules only where its scanner sees the name used, and it has
  silently dropped this world's classes twice — once because an unanchored `lib/` rule in
  `.gitignore` hid `site/src/lib` from source detection, so every mark rendered 0×0 and
  review looked fine.
- **Do** keep `check-css.mjs` in the build (`pnpm build` runs it after `vite build`) and add
  any new world class to its `REQUIRED` list. A design that vanishes without an error is the
  failure this guards against.
- **Do** implement a view like scanner view as a document state — a class on `<html>` that
  re-points the drop-out custom properties to `transparent` — so every layer, including
  anything portalled out of the tree, changes together.
- **Do** mark every pre-printed element with `.drops-out` so it disappears under the lamp,
  and check a new screen by turning scanner view on: what remains must be exactly what a
  grader is allowed to depend on.
- **Do** put load-bearing numbers in the mono face with tabular figures.
- **Do** let untrusted bundle content wrap (`.han`) and let unshrinkable content scroll in
  its own box.
- **Do** respect `prefers-reduced-motion`; the global reduction to 0.01ms is already in
  place and no component may opt out.

### Don't:

- **Don't** introduce a radius anywhere, or accept DaisyUI's defaults for radius, depth, or
  noise — the `omr` theme zeroes all three on purpose.
- **Don't** add a second shadow, a hover lift, or a zero-offset glow. One elevation exists
  and it belongs to `.sheet`.
- **Don't** spend cinnabar on emphasis, decoration, active states, or navigation. If it is
  not a commit, a seal, or a refusal, it is graphite.
- **Don't** set text in a fill-tier ink (`dropout`, `cinnabar`) where it has to be read; the
  `-ink` tier exists because those two fail contrast on stock.
- **Don't** implement scanner view — or any state change — as a CSS `filter`,
  `mix-blend-mode`, or opacity fade over the whole page.
- **Don't** put content directly on the scanner bed. The bed carries the footer's issuing
  block and nothing else; words are read on stock.
- **Don't** use uppercase letterspaced type as a kicker or eyebrow above a headline. It is a
  field caption and only a field caption.
- **Don't** reach for exam-paper pastiche — torn edges, staples, paper texture, handwriting
  faces, skewed photographic scans. The world is a printed card, not a prop.
- **Don't** animate anything but the mark's fill. Everything else is a color or border
  transition of 160–220ms.
