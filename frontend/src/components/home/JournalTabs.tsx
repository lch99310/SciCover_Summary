import { JOURNALS } from '../../lib/constants';
import type { JournalName } from '../../lib/types';
import './JournalTabs.css';

interface JournalTabsProps {
  active: JournalName | 'all';
  onChange: (journal: JournalName | 'all') => void;
}

export function JournalTabs({ active, onChange }: JournalTabsProps) {
  return (
    <div className="journal-tabs container">
      <div className="journal-tabs__inner">
        <button
          className={`journal-tabs__tab ${active === 'all' ? 'journal-tabs__tab--active' : ''}`}
          onClick={() => onChange('all')}
        >
          All Journals
        </button>
        {JOURNALS.map((j) => (
          <button
            key={j.name}
            className={`journal-tabs__tab ${active === j.name ? 'journal-tabs__tab--active' : ''}`}
            style={
              active === j.name
                ? ({ '--tab-active-color': j.color } as React.CSSProperties)
                : undefined
            }
            onClick={() => onChange(j.name)}
          >
            {j.label}
          </button>
        ))}
      </div>
    </div>
  );
}
