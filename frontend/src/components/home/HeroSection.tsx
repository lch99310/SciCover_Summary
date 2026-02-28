import { Link } from 'react-router-dom';
import type { ArticleDetail } from '../../lib/types';
import { JOURNAL_RAW_COLORS } from '../../lib/constants';
import { format } from 'date-fns';
import './HeroSection.css';

interface HeroSectionProps {
  article: ArticleDetail;
}

export function HeroSection({ article }: HeroSectionProps) {
  const { coverStory, journal, date, coverImage } = article;
  const journalColor = JOURNAL_RAW_COLORS[journal];
  const formattedDate = format(new Date(date), 'MMMM d, yyyy');

  return (
    <Link to={`/article/${article.id}`} className="hero">
      <div className="hero__image-wrapper">
        <div
          className="hero__image"
          style={{ backgroundImage: `url(${coverImage.url})` }}
        />
        <div className="hero__gradient" />
      </div>
      <div className="hero__content container">
        <div className="hero__meta">
          <span
            className="hero__badge"
            style={{ backgroundColor: journalColor }}
          >
            {journal}
          </span>
          <span className="hero__date">{formattedDate}</span>
        </div>
        <h1 className="hero__title-zh heading-zh">{coverStory.title.zh}</h1>
        <h2 className="hero__title-en heading-en">{coverStory.title.en}</h2>
        <span className="hero__cta">Read More &rarr;</span>
      </div>
    </Link>
  );
}
