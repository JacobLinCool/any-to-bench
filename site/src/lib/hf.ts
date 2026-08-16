/** Reading a2b bundles straight off the Hugging Face CDN.
 *
 * Deliberately not the datasets-server /rows API: that serves a flattened,
 * lossy projection of the same data (composite nesting, options and matching
 * items are stringified) and returns 500 whenever its queue is behind. The raw
 * bundle files are static objects on the CDN and are the canonical artifact.
 *
 * Subset discovery uses the same rule the CLI does — a top-level directory
 * containing bundle/exam.json — so the site and `a2b download` can never
 * disagree about what counts as a bundle.
 */

import type { Bundle, Exam, Grading, Manifest } from './bundle'

const HOST = 'https://huggingface.co'

export const DEFAULT_REPO = 'JacobLinCool/taiwan-exams'

export class HubError extends Error {
  constructor(
    message: string,
    readonly hint?: string,
  ) {
    super(message)
    this.name = 'HubError'
  }
}

export function isRepoId(value: string): boolean {
  return /^[\w.-]+\/[\w.-]+$/.test(value.trim())
}

export function fileUrl(repo: string, path: string): string {
  return `${HOST}/datasets/${repo}/resolve/main/${path.split('/').map(encodeURIComponent).join('/')}`
}

export function assetUrl(repo: string, subset: string, asset: string): string {
  return fileUrl(repo, `${subset}/bundle/${asset}`)
}

export function repoUrl(repo: string, subset?: string): string {
  return subset
    ? `${HOST}/datasets/${repo}/viewer/${encodeURIComponent(subset)}`
    : `${HOST}/datasets/${repo}`
}

async function getJson<T>(url: string, what: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url)
  } catch {
    throw new HubError(
      `Could not reach Hugging Face while loading ${what}.`,
      'Check the connection and try again — this page talks to huggingface.co directly.',
    )
  }
  if (response.status === 401 || response.status === 403) {
    throw new HubError(
      'That dataset is private or gated.',
      'This viewer runs entirely in your browser with no credentials, so it can only open public datasets.',
    )
  }
  if (response.status === 404) throw new HubError(`No ${what} found at that address.`)
  if (response.status === 429) {
    throw new HubError(
      'Hugging Face is rate-limiting this browser.',
      'Anonymous requests are capped. Wait a minute and reload — or sign in on huggingface.co in this browser, which raises the limit.',
    )
  }
  if (response.status >= 500) {
    throw new HubError(
      `Hugging Face is having trouble serving ${what}.`,
      'This is on their side, not the dataset. Reloading in a moment usually works.',
    )
  }
  if (!response.ok) throw new HubError(`Hugging Face returned ${response.status} for ${what}.`)
  return (await response.json()) as T
}

type TreeEntry = { type: 'file' | 'directory'; path: string }

/** Every subset in the repo, in the order the Hub lists them. */
export async function listSubsets(repo: string): Promise<string[]> {
  const tree = await getJson<TreeEntry[]>(
    `${HOST}/api/datasets/${repo}/tree/main`,
    `the dataset ${repo}`,
  )
  const dirs = tree.filter((e) => e.type === 'directory').map((e) => e.path)
  if (!dirs.length) {
    throw new HubError(
      `${repo} holds no bundles.`,
      'A bundle is a top-level folder containing bundle/exam.json — publish one with `a2b upload`.',
    )
  }
  return dirs.sort()
}

export async function loadBundle(repo: string, subset: string): Promise<Bundle> {
  const at = (file: string) => fileUrl(repo, `${subset}/bundle/${file}`)
  const [exam, grading, manifest] = await Promise.all([
    getJson<Exam>(at('exam.json'), `the exam in ${subset}`),
    getJson<Grading>(at('grading.json'), `the grading spec in ${subset}`),
    getJson<Manifest>(at('manifest.json'), `the manifest in ${subset}`),
  ])
  return { name: subset, exam, grading, manifest }
}

/** Just enough of a bundle to draw its stub in the register. */
export type SubsetCard = { name: string; exam?: Exam; error?: string }

export async function peek(repo: string, subset: string): Promise<SubsetCard> {
  try {
    const exam = await getJson<Exam>(fileUrl(repo, `${subset}/bundle/exam.json`), subset)
    return { name: subset, exam }
  } catch (error) {
    return { name: subset, error: error instanceof Error ? error.message : 'unreadable' }
  }
}
