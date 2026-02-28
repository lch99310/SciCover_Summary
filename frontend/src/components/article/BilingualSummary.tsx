import type { BilingualText } from '../../lib/types';
import './BilingualSummary.css';

interface BilingualSummaryProps {
  title: BilingualText;
  summary: BilingualText;
  journalColor: string;
}

export function BilingualSummary({ title, summary, journalColor }: BilingualSummaryProps) {
  return (
    <div className="bilingual-summary">
      <section
        className="bilingual-summary__section bilingual-summary__zh"
        style={{ '--section-accent': journalColor } as React.CSSProperties}
      >
        <span className="bilingual-summary__lang-label">中文</span>
        <h2 className="bilingual-summary__title-zh heading-zh">{title.zh}</h2>
        <div className="bilingual-summary__body-zh body-zh" lang="zh-Hans">
          {summary.zh.split('\n\n').map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      </section>

      <hr className="bilingual-summary__divider" />

      <section
        className="bilingual-summary__section bilingual-summary__en"
        style={{ '--section-accent': journalColor } as React.CSSProperties}
      >
        <span className="bilingual-summary__lang-label">English</span>
        <h2 className="bilingual-summary__title-en heading-en">{title.en}</h2>
        <div className="bilingual-summary__body-en body-en" lang="en">
          {summary.en.split('\n\n').map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      </section>
    </div>
  );
}
