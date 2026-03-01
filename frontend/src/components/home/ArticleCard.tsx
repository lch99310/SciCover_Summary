import { Link } from 'react-router-dom';
import type { ArticleIndexEntry } from '../../lib/types';
import { JOURNAL_RAW_COLORS, getDataUrl } from '../../lib/constants';
import type { JournalName } from '../../lib/types';
import { format } from 'date-fns';
import { motion } from 'framer-motion';
import './ArticleCard.css';

interface ArticleCardProps {
  article: ArticleIndexEntry;
  index: number;
}

export function ArticleCard({ article, index }: ArticleCardProps) {
  const journalColor = JOURNAL_RAW_COLORS[article.journal as JournalName] || '#666';
  const formattedDate = format(new Date(article.date), 'MMM d, yyyy');

  // Use the article's own cover_url if available; fall back to convention path
  const defaultCoverMap: Record<string, string> = {
    'Political Geography': 'images/Political_Geography/PG-cover.png',
    'International Organization': 'images/International_Organization/IO-cover.png',
    'American Sociological Review': 'images/ASR/ASR-cover.png',
  };
  const journalSlug = article.journal.toLowerCase();
  const fallbackUrl = defaultCoverMap[article.journal]
    ? getDataUrl(defaultCoverMap[article.journal])
    : getDataUrl(`images/${journalSlug}/${article.id}-cover.jpg`);
  const coverImageUrl = article.cover_url
    ? getDataUrl(article.cover_url)
    : fallbackUrl;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.08 }}
    >
      <Link to={`/article/${article.id}`} className="article-card">
        <div className="article-card__image-wrapper">
          <div
            className="article-card__image"
            style={{ backgroundImage: `url(${coverImageUrl})` }}
          />
          <div className="article-card__image-overlay" style={{ backgroundColor: journalColor }} />
        </div>
        <div className="article-card__body">
          <div className="article-card__meta">
            <span
              className="article-card__badge"
              style={{ backgroundColor: journalColor }}
            >
              {article.journal}
            </span>
            <span className="article-card__date">{formattedDate}</span>
          </div>
          <h3 className="article-card__title-zh heading-zh">{article.title_zh}</h3>
          <p className="article-card__title-en heading-en">{article.title_en}</p>
        </div>
      </Link>
    </motion.div>
  );
}
