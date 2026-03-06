import { useState, useEffect, useMemo } from 'react';
import { HashRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
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

  // Show only articles from the last 6 months on the homepage
  const { recentArticles, hasOlderArticles } = useMemo(() => {
    if (!index) return { recentArticles: [], hasOlderArticles: false };
    const now = new Date();
    const cutoff = new Date(now.getFullYear(), now.getMonth() - 6, now.getDate());

    const all = activeJournal === 'all'
      ? index.articles
      : index.articles.filter((a) => a.journal === activeJournal);

    const recent = all.filter((a) => {
      const d = new Date(a.date);
      return !isNaN(d.getTime()) && d >= cutoff;
    });

    const older = all.some((a) => {
      const d = new Date(a.date);
      return !isNaN(d.getTime()) && d < cutoff;
    });

    return { recentArticles: recent, hasOlderArticles: older };
  }, [index, activeJournal]);

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
      <ArticleGrid articles={recentArticles} />
      {hasOlderArticles && (
        <div className="container" style={{ textAlign: 'center', padding: '2rem 1.5rem 3rem' }}>
          <Link
            to="/archive"
            style={{
              display: 'inline-block',
              padding: '0.75rem 2rem',
              borderRadius: '8px',
              backgroundColor: 'var(--color-primary)',
              color: '#fff',
              textDecoration: 'none',
              fontWeight: 600,
              fontSize: 'var(--text-base)',
              transition: 'opacity 0.2s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
          >
            瀏覽歷史文章 / View Archive →
          </Link>
        </div>
      )}
    </>
  );
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function AppContent() {
  const { theme, toggleTheme } = useTheme();

  return (
    <HashRouter>
      <ScrollToTop />
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
