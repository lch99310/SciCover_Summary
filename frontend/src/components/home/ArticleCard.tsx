import { Link } from 'react-router-dom';
import type { ArticleIndexEntry } from '../../lib/types';
import { JOURNAL_RAW_COLORS, getDataUrl, getDefaultCoverUrl } from '../../lib/constants';
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

  const coverImageUrl = article.cover_url
    ? getDataUrl(article.cover_url)
    : getDefaultCoverUrl(article.journal);

  const handleImageError = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const target = e.currentTarget;
    const fallback = getDefaultCoverUrl(article.journal);
    if (target.src !== fallback) {
      target.src = fallback;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.08 }}
    >
      <Link to={`/article/${article.id}`} className="article-card">
        <div className="article-card__image-wrapper">
          <img
            className="article-card__image"
            src={coverImageUrl}
            alt={article.title_en || article.title_zh}
            loading="lazy"
            onError={handleImageError}
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
