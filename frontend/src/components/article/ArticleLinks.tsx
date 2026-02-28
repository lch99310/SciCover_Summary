import type { ArticleLinks, KeyArticle } from '../../lib/types';
import './ArticleLinks.css';

interface ArticleLinksProps {
  keyArticle: KeyArticle;
  links: ArticleLinks;
}

export function ArticleLinksSection({ keyArticle, links }: ArticleLinksProps) {
  return (
    <div className="article-links">
      <div className="article-links__paper">
        <h3 className="article-links__heading">Key Research Article</h3>
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
          Official Article
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
          DOI Link
        </a>

        {links.preprint && (
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
            Open Access Preprint
          </a>
        )}
      </div>
    </div>
  );
}
