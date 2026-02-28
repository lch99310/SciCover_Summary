import { useParams, Link } from 'react-router-dom';
import { useArticle } from '../../hooks/useArticles';
import { JOURNAL_RAW_COLORS } from '../../lib/constants';
import { BilingualSummary } from './BilingualSummary';
import { FigureGallery } from './FigureGallery';
import { ArticleLinksSection } from './ArticleLinks';
import { LoadingSpinner } from '../ui/LoadingSpinner';
import { format } from 'date-fns';
import { motion } from 'framer-motion';
import './ArticleDetail.css';

export function ArticleDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: article, isLoading, error } = useArticle(id);

  if (isLoading) return <LoadingSpinner />;

  if (error || !article) {
    return (
      <div className="article-detail__error container reading-column">
        <h2>Article not found</h2>
        <p>The article you're looking for doesn't exist or failed to load.</p>
        <Link to="/" className="article-detail__back-link">&larr; Back to Home</Link>
      </div>
    );
  }

  const { coverStory, journal, volume, issue, date, coverImage } = article;
  const journalColor = JOURNAL_RAW_COLORS[journal];
  const formattedDate = format(new Date(date), 'MMMM d, yyyy');

  return (
    <motion.article
      className="article-detail"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
    >
      <div className="article-detail__header container reading-column">
        <Link to="/" className="article-detail__back-link">&larr; Back to Home</Link>

        <div className="article-detail__meta">
          <span
            className="article-detail__badge"
            style={{ backgroundColor: journalColor }}
          >
            {journal}
          </span>
          <span className="article-detail__info">
            Vol. {volume}, Issue {issue}
          </span>
          <span className="article-detail__date">{formattedDate}</span>
        </div>
      </div>

      <div className="article-detail__cover container reading-column">
        <FigureGallery
          images={coverStory.images}
          credit={coverImage.credit}
        />
      </div>

      <div className="article-detail__content container reading-column">
        <BilingualSummary
          title={coverStory.title}
          summary={coverStory.summary}
          journalColor={journalColor}
        />

        <ArticleLinksSection
          keyArticle={coverStory.keyArticle}
          links={coverStory.links}
        />
      </div>
    </motion.article>
  );
}
