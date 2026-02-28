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

export const DATA_BASE_URL = import.meta.env.VITE_DATA_BASE_URL || '';

export const SITE_NAME = 'SciCover';
export const SITE_TAGLINE_ZH = '全球顶级科学期刊封面故事 · 双语解读';
export const SITE_TAGLINE_EN = 'Top Science Journal Cover Stories · Bilingual Summaries';
