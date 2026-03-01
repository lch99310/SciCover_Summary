import type { JournalName } from './types';

export const JOURNALS: { name: JournalName; color: string; label: string }[] = [
  { name: 'Science', color: 'var(--color-science)', label: 'Science' },
  { name: 'Nature', color: 'var(--color-nature)', label: 'Nature' },
  { name: 'Cell', color: 'var(--color-cell)', label: 'Cell' },
  { name: 'Political Geography', color: 'var(--color-polgeog)', label: 'Political Geography' },
  { name: 'International Organization', color: 'var(--color-intorg)', label: 'International Organization' },
  { name: 'American Sociological Review', color: 'var(--color-asr)', label: 'American Sociological Review' },
];

export const JOURNAL_COLORS: Record<JournalName, string> = {
  Science: 'var(--color-science)',
  Nature: 'var(--color-nature)',
  Cell: 'var(--color-cell)',
  'Political Geography': 'var(--color-polgeog)',
  'International Organization': 'var(--color-intorg)',
  'American Sociological Review': 'var(--color-asr)',
};

export const JOURNAL_RAW_COLORS: Record<JournalName, string> = {
  Science: '#B8271F',
  Nature: '#0D7EB5',
  Cell: '#2E7D32',
  'Political Geography': '#8B5CF6',
  'International Organization': '#D97706',
  'American Sociological Review': '#0891B2',
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
export const SITE_TAGLINE_ZH = '頂級學術期刊封面故事 · 雙語解讀';
export const SITE_TAGLINE_EN = 'Top Academic Journal Cover Stories · Bilingual Summaries';

/**
 * Map journal names to their default-cover image path under data/images/.
 * Each journal folder should contain a default-cover.jpg as a fallback.
 * Folder names must match what exists on disk.
 */
const DEFAULT_COVER_MAP: Record<string, string> = {
  Science: 'data/images/science/default-cover.jpg',
  Nature: 'data/images/nature/default-cover.jpg',
  Cell: 'data/images/cell/default-cover.jpg',
  'Political Geography': 'data/images/Political_Geography/default-cover.jpg',
  'International Organization': 'data/images/International_Organization/default-cover.jpg',
  'American Sociological Review': 'data/images/ASR/default-cover.jpg',
};

/**
 * Get the default cover image URL for a given journal.
 * Falls back to the Science default if the journal is unknown.
 */
export function getDefaultCoverUrl(journal: string): string {
  const path = DEFAULT_COVER_MAP[journal] || DEFAULT_COVER_MAP.Science;
  return getDataUrl(path);
}
