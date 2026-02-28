import { useState } from 'react';
import type { ArticleLinks, KeyArticle } from '../../lib/types';
import './ArticleLinks.css';

interface ArticleLinksProps {
  keyArticle: KeyArticle;
  links: ArticleLinks;
}

/**
 * Detect preprint platform from URL and return a display label.
 */
function getPreprintLabel(url: string): string {
  if (url.includes('arxiv.org')) return 'arXiv 預印本';
  if (url.includes('biorxiv.org')) return 'bioRxiv 預印本';
  if (url.includes('ssrn.com')) return 'SSRN 預印本';
  if (url.includes('socarxiv') || url.includes('socopen.org')) return 'SocArXiv 預印本';
  if (url.includes('osf.io')) return 'OSF 預印本';
  return '預印本';
}

export function ArticleLinksSection({ keyArticle, links }: ArticleLinksProps) {
  const [showToast, setShowToast] = useState(false);

  const handleDisabledClick = () => {
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2500);
  };

  const preprintLabel = links.preprint ? getPreprintLabel(links.preprint) : '預印本';

  return (
    <div className="article-links">
      <div className="article-links__paper">
        <h3 className="article-links__heading">重點研究論文</h3>
        <p className="article-links__paper-title">{keyArticle.title}</p>
        <p className="article-links__paper-authors">
          {keyArticle.authors.join(', ')}
          {keyArticle.pages && ` — pp. ${keyArticle.pages}`}
        </p>
        <p className="article-links__paper-doi">
          DOI: {keyArticle.doi}
        </p>
      </div>

      <div className="article-links__buttons">
        <a
          href={links.official}
          target="_blank"
          rel="noopener noreferrer"
          className="article-links__btn article-links__btn--primary"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
          期刊原文
        </a>

        <a
          href={links.doi}
          target="_blank"
          rel="noopener noreferrer"
          className="article-links__btn article-links__btn--secondary"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
          DOI 連結
        </a>

        {links.preprint ? (
          <a
            href={links.preprint}
            target="_blank"
            rel="noopener noreferrer"
            className="article-links__btn article-links__btn--open"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
            {preprintLabel}
          </a>
        ) : (
          <button
            type="button"
            className="article-links__btn article-links__btn--disabled"
            onClick={handleDisabledClick}
            title="此論文目前沒有公開的預印本連結"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
            預印本
          </button>
        )}
      </div>

      {showToast && (
        <div className="article-links__toast">
          此論文目前沒有公開的預印本連結
        </div>
      )}
    </div>
  );
}
