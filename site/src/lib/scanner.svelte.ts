/** Scanner view: the drop-out ink is gone and only the marks remain.
 *
 * It is a document state rather than a CSS filter, because that is what it is in
 * life — the same sheet under a lamp the pre-printed ink does not return. The
 * class lands on <html> so every layer, including anything portalled out of the
 * component tree, changes together.
 */
export const scanner = $state({ on: false })

export function toggleScanner(): void {
  scanner.on = !scanner.on
  document.documentElement.classList.toggle('scanning', scanner.on)
}
