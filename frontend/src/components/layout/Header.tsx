import { Link } from 'react-router-dom';
import { SITE_NAME, JOURNALS } from '../../lib/constants';
import type { JournalName } from '../../lib/types';
import { ThemeToggle } from '../ui/ThemeToggle';
import './Header.css';

interface HeaderProps {
  activeJournal?: JournalName | 'all';
  onJournalChange?: (journal: JournalName | 'all') => void;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
}

export function Header({ activeJournal, onJournalChange, theme, onToggleTheme }: HeaderProps) {
  return (
    <header className="header">
      <div className="header__inner container">
        <Link to="/" className="header__logo">
          <span className="header__logo-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="8" r="3" stroke="currentColor" strokeWidth="2"/>
              <circle cx="6" cy="16" r="3" stroke="currentColor" strokeWidth="2"/>
              <circle cx="18" cy="16" r="3" stroke="currentColor" strokeWidth="2"/>
              <line x1="10.5" y1="10.5" x2="7.5" y2="13.5" stroke="currentColor" strokeWidth="1.5"/>
              <line x1="13.5" y1="10.5" x2="16.5" y2="13.5" stroke="currentColor" strokeWidth="1.5"/>
              <line x1="9" y1="16" x2="15" y2="16" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
          </span>
          <span className="header__logo-text">{SITE_NAME}</span>
        </Link>

        {onJournalChange && (
          <nav className="header__nav">
            <button
              className={`header__tab ${activeJournal === 'all' ? 'header__tab--active' : ''}`}
              onClick={() => onJournalChange('all')}
            >
              All
            </button>
            {JOURNALS.map((j) => (
              <button
                key={j.name}
                className={`header__tab ${activeJournal === j.name ? 'header__tab--active' : ''}`}
                style={activeJournal === j.name ? { '--tab-color': j.color } as React.CSSProperties : undefined}
                onClick={() => onJournalChange(j.name)}
              >
                {j.label}
              </button>
            ))}
          </nav>
        )}

        <div className="header__actions">
          <Link to="/archive" className="header__archive-link">Archive</Link>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </div>
    </header>
  );
}
