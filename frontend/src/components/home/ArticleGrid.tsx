import type { ArticleIndexEntry } from '../../lib/types';
import { ArticleCard } from './ArticleCard';
import './ArticleGrid.css';

interface ArticleGridProps {
  articles: ArticleIndexEntry[];
}

export function ArticleGrid({ articles }: ArticleGridProps) {
  if (articles.length === 0) {
    return (
      <div className="article-grid__empty container">
        <p>No articles found for this selection.</p>
      </div>
    );
  }

  return (
    <div className="article-grid container">
      <div className="article-grid__inner">
        {articles.map((article, index) => (
          <ArticleCard key={article.id} article={article} index={index} />
        ))}
      </div>
    </div>
  );
}
