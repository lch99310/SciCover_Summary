import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { Footer } from './Footer';
import type { JournalName } from '../../lib/types';

interface LayoutProps {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  activeJournal?: JournalName | 'all';
  onJournalChange?: (journal: JournalName | 'all') => void;
}

export function Layout({ theme, onToggleTheme, activeJournal, onJournalChange }: LayoutProps) {
  return (
    <div className="app-layout">
      <Header
        theme={theme}
        onToggleTheme={onToggleTheme}
        activeJournal={activeJournal}
        onJournalChange={onJournalChange}
      />
      <main className="main-content">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
