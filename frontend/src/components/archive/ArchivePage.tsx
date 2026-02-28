import { useState, useMemo } from 'react';
import { useArticleIndex } from '../../hooks/useArticles';
import { ArticleGrid } from '../home/ArticleGrid';
import { LoadingSpinner } from '../ui/LoadingSpinner';
import { Link } from 'react-router-dom';
import './ArchivePage.css';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

export function ArchivePage() {
  const { data: index, isLoading } = useArticleIndex();

  // Extract available years from data
  const availableYears = useMemo(() => {
    if (!index) return [];
    const years = new Set(index.articles.map((a) => new Date(a.date).getFullYear()));
    return Array.from(years).sort((a, b) => b - a);
  }, [index]);

  const [selectedYear, setSelectedYear] = useState<number>(() => {
    return new Date().getFullYear();
  });

  const [selectedMonth, setSelectedMonth] = useState<number>(() => {
    return new Date().getMonth();
  });

  // Filter articles for selected year/month
  const filteredArticles = useMemo(() => {
    if (!index) return [];
    return index.articles.filter((a) => {
      const d = new Date(a.date);
      return d.getFullYear() === selectedYear && d.getMonth() === selectedMonth;
    });
  }, [index, selectedYear, selectedMonth]);

  // Check which months have data for the selected year
  const monthsWithData = useMemo(() => {
    if (!index) return new Set<number>();
    const months = new Set<number>();
    index.articles.forEach((a) => {
      const d = new Date(a.date);
      if (d.getFullYear() === selectedYear) {
        months.add(d.getMonth());
      }
    });
    return months;
  }, [index, selectedYear]);

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="archive-page">
      <div className="archive-page__header container">
        <Link to="/" className="archive-page__back">&larr; Back to Home</Link>
        <h1 className="archive-page__title heading-en">Archive</h1>
        <p className="archive-page__subtitle">
          Browse past cover story summaries by date
        </p>
      </div>

      <div className="archive-page__nav container">
        <div className="archive-nav__years">
          {availableYears.map((year) => (
            <button
              key={year}
              className={`archive-nav__year-btn ${selectedYear === year ? 'archive-nav__year-btn--active' : ''}`}
              onClick={() => setSelectedYear(year)}
            >
              {year}
            </button>
          ))}
        </div>

        <div className="archive-nav__months">
          {MONTHS.map((name, idx) => {
            const hasData = monthsWithData.has(idx);
            return (
              <button
                key={idx}
                className={`archive-nav__month-btn ${selectedMonth === idx ? 'archive-nav__month-btn--active' : ''} ${!hasData ? 'archive-nav__month-btn--disabled' : ''}`}
                onClick={() => hasData && setSelectedMonth(idx)}
                disabled={!hasData}
              >
                {name}
              </button>
            );
          })}
        </div>
      </div>

      <div className="archive-page__results">
        <ArticleGrid articles={filteredArticles} />
      </div>
    </div>
  );
}
