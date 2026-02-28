import { useState, useEffect, useMemo } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
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

  const filteredArticles = useMemo(() => {
    if (!index) return [];
    const articles = activeJournal === 'all'
      ? index.articles
      : index.articles.filter((a) => a.journal === activeJournal);
    // Skip the first article if it's the hero (shown in hero section)
    if (activeJournal === 'all' && articles.length > 0) {
      return articles.slice(1);
    }
    return articles;
  }, [index, activeJournal]);

  if (isLoading || heroLoading) return <LoadingSpinner />;

  if (isError) {
    return (
      <div className="container" style={{ padding: '4rem 1.5rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--color-text-secondary)' }}>
          Failed to load articles. Please check that data files are deployed correctly.
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
    </>
  );
}

function AppContent() {
  const { theme, toggleTheme } = useTheme();
  const [activeJournal, setActiveJournal] = useState<JournalName | 'all'>('all');

  return (
    <HashRouter>
      <Routes>
        <Route
          element={
            <Layout
              theme={theme}
              onToggleTheme={toggleTheme}
              activeJournal={activeJournal}
              onJournalChange={setActiveJournal}
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
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
