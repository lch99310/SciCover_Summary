import { useState, useEffect, useMemo } from 'react';
import { HashRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/layout/Layout';
import { useTheme } from './hooks/useTheme';
import { useArticleIndex } from './hooks/useArticles';
import { HeroSection } from './components/home/HeroSection';
import { JournalTabs } from './components/home/JournalTabs';
import { ArticleGrid } from './components/home/ArticleGrid';
import { ArticleDetail } from './components/article/ArticleDetail';
import { ArchivePage } from './components/archive/ArchivePage';
import { LoadingSpinner } from './components/ui/LoadingSpinner';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import type { JournalName, ArticleDetail as ArticleDetailType } from './lib/types';
import { getDataUrl } from './lib/constants';
import './styles/global.css';

/** Number of days to consider "recent" for the homepage. */
const RECENT_DAYS = 30;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function HomePage() {
  const [activeJournal, setActiveJournal] = useState<JournalName | 'all'>('all');
  const { data: index, isLoading, isError } = useArticleIndex();
  const [heroArticle, setHeroArticle] = useState<ArticleDetailType | null>(null);
  const [heroLoading, setHeroLoading] = useState(true);

  // Load the hero (latest) article detail
  useEffect(() => {
    if (!index || index.articles.length === 0) {
      setHeroLoading(false);
      return;
    }
    const latest = index.articles[0];
    fetch(getDataUrl(`data/${latest.path}`))
      .then((r) => {
        if (!r.ok) throw new Error('Failed to load hero article');
        return r.json();
      })
      .then((data) => {
        setHeroArticle(data);
        setHeroLoading(false);
      })
      .catch(() => setHeroLoading(false));
  }, [index]);

  // Split articles into recent (last RECENT_DAYS days) and older.
  const { recentArticles, olderCount } = useMemo(() => {
    if (!index) return { recentArticles: [], olderCount: 0 };
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - RECENT_DAYS);

    const recent = index.articles.filter((a) => {
      const d = new Date(a.date);
      return !isNaN(d.getTime()) && d >= cutoff;
    });
    const older = index.articles.length - recent.length;

    return { recentArticles: recent, olderCount: older };
  }, [index]);

  const filteredArticles = useMemo(() => {
    const articles = activeJournal === 'all'
      ? recentArticles
      : recentArticles.filter((a) => a.journal === activeJournal);
    return articles;
  }, [recentArticles, activeJournal]);

  if (isLoading || heroLoading) return <LoadingSpinner />;

  if (isError) {
    return (
      <div className="container" style={{ padding: '4rem 1.5rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--color-text-secondary)' }}>
          文章載入失敗，請確認資料檔案已正確部署。
        </p>
      </div>
    );
  }

  return (
    <>
      {heroArticle && activeJournal === 'all' && (
        <HeroSection article={heroArticle} />
      )}
      <JournalTabs active={activeJournal} onChange={setActiveJournal} />
      <ArticleGrid articles={filteredArticles} />

      {olderCount > 0 && (
        <div className="container" style={{ textAlign: 'center', padding: '2rem 1.5rem 3rem' }}>
          <Link
            to="/archive"
            style={{
              display: 'inline-block',
              padding: '0.75rem 2rem',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--color-text-primary)',
              textDecoration: 'none',
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--step-0)',
              transition: 'var(--transition-base)',
            }}
          >
            查看更多歷史文章 / View {olderCount} more in Archive &rarr;
          </Link>
        </div>
      )}
    </>
  );
}

function AppContent() {
  const { theme, toggleTheme } = useTheme();

  return (
    <HashRouter>
      <Routes>
        <Route
          element={
            <Layout
              theme={theme}
              onToggleTheme={toggleTheme}
            />
          }
        >
          <Route path="/" element={<HomePage />} />
          <Route path="/article/:id" element={<ArticleDetail />} />
          <Route path="/archive" element={<ArchivePage />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AppContent />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
