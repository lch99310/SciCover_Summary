import type { JournalName } from './types';

export const JOURNALS: { name: JournalName; color: string; label: string }[] = [
  { name: 'Science', color: 'var(--color-science)', label: 'Science' },
  { name: 'Nature', color: 'var(--color-nature)', label: 'Nature' },
  { name: 'Cell', color: 'var(--color-cell)', label: 'Cell' },
];

export const JOURNAL_COLORS: Record<JournalName, string> = {
  Science: 'var(--color-science)',
  Nature: 'var(--color-nature)',
  Cell: 'var(--color-cell)',
};

export const JOURNAL_RAW_COLORS: Record<JournalName, string> = {
  Science: '#B8271F',
  Nature: '#0D7EB5',
  Cell: '#2E7D32',
};

/**
 * Resolve the base URL for data/image assets.
 * In production (GitHub Pages), Vite's import.meta.env.BASE_URL gives the
 * subpath (e.g. "/scicover/").  In dev mode it's just "/".
 */
const BASE = import.meta.env.BASE_URL || './';

/**
 * Build a full URL to a data or image asset.
 * If the path is already an absolute URL (https://...), return it as-is.
 * Usage: getDataUrl('data/index.json')  ->  '/scicover/data/index.json'
 *        getDataUrl('https://example.com/img.jpg')  ->  'https://example.com/img.jpg'
 */
export function getDataUrl(relativePath: string): string {
  if (relativePath.startsWith('http://') || relativePath.startsWith('https://')) {
    return relativePath;
  }
  const base = BASE.endsWith('/') ? BASE : `${BASE}/`;
  const path = relativePath.startsWith('/') ? relativePath.slice(1) : relativePath;
  return `${base}${path}`;
}

export const SITE_NAME = 'SciCover Summary';
export const SITE_TAGLINE_ZH = '全球頂級科學期刊封面故事 · 雙語解讀';
export const SITE_TAGLINE_EN = 'Top Science Journal Cover Stories · Bilingual Summaries';
