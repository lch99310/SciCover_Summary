/* ============================================
   TypeScript Interfaces for SciCover Data
   ============================================ */

export interface BilingualText {
  zh: string;
  en: string;
}

export interface ArticleImage {
  url: string;
  caption: BilingualText;
}

export interface CoverImage {
  url: string;
  credit: string;
}

export interface KeyArticle {
  title: string;
  authors: string[];
  doi: string;
  pages: string;
}

export interface ArticleLinks {
  official: string;
  doi: string;
  preprint?: string;
}

export interface CoverStory {
  title: BilingualText;
  summary: BilingualText;
  keyArticle: KeyArticle;
  images: ArticleImage[];
  links: ArticleLinks;
}

export type JournalName =
  | 'Science'
  | 'Nature'
  | 'Cell'
  | 'Political Geography'
  | 'International Organization'
  | 'American Sociological Review';

export interface ArticleDetail {
  id: string;
  journal: JournalName;
  volume: string;
  issue: string;
  date: string;
  coverImage: CoverImage;
  coverStory: CoverStory;
}

export interface ArticleIndexEntry {
  id: string;
  journal: string;
  date: string;
  path: string;
  title_zh: string;
  title_en: string;
  cover_url?: string;
}

export interface ArticleIndex {
  lastUpdated: string;
  articles: ArticleIndexEntry[];
}

export interface LatestArticles {
  Science: string;
  Nature: string;
  Cell: string;
  'Political Geography': string;
  'International Organization': string;
  'American Sociological Review': string;
}
