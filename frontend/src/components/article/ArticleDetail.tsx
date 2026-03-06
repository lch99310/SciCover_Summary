import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useArticle } from '../../hooks/useArticles';
import { JOURNAL_RAW_COLORS, SITE_NAME, SITE_URL } from '../../lib/constants';
import { BilingualSummary } from './BilingualSummary';
import { FigureGallery } from './FigureGallery';
import { ArticleLinksSection } from './ArticleLinks';
import { LoadingSpinner } from '../ui/LoadingSpinner';
import { safeFormatDate } from '../../lib/dateUtils';
import './ArticleDetail.css';

export function ArticleDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: article, isLoading, isNotFound, error } = useArticle(id);
  const [copied, setCopied] = useState(false);

  // Update document title for browser tab / native share sheet.
  useEffect(() => {
    if (article) {
      const title = article.coverStory.title;
      document.title = `${title.zh || title.en} — ${SITE_NAME}`;
      return () => { document.title = SITE_NAME; };
    }
  }, [article]);

  // Copy the clean (non-hash) share URL so link previews work.
  const handleShare = useCallback(async () => {
    const shareUrl = `${SITE_URL}/article/${id}`;
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      const input = document.createElement('input');
      input.value = shareUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [id]);

  const handleGoBack = () => {
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/');
    }
  };

  if (isLoading) return <LoadingSpinner />;

  if (error || isNotFound || !article) {
    return (
      <div className="article-detail__error container reading-column">
        <h2>找不到文章</h2>
        <p>您所尋找的文章不存在或載入失敗。</p>
        <button onClick={handleGoBack} className="article-detail__back-link">&larr; 回到上一頁 / Go Back</button>
      </div>
    );
  }

  const { coverStory, journal, volume, issue, date, coverImage } = article;
  const journalColor = JOURNAL_RAW_COLORS[journal];
  const formattedDate = safeFormatDate(date, 'MMMM d, yyyy');

  return (
    <article className="article-detail article-detail--enter">

      <div className="article-detail__header container reading-column">
        <div className="article-detail__nav">
          <button onClick={handleGoBack} className="article-detail__back-link">&larr; 回到上一頁 / Go Back</button>
          <button onClick={handleShare} className="article-detail__share-btn" title="複製分享連結 / Copy share link">
            {copied ? '已複製 / Copied!' : '分享 / Share'}
          </button>
        </div>

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
          journal={journal}
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
    </article>
  );
}
