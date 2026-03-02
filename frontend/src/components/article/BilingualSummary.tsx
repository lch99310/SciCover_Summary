import type { ReactNode } from 'react';
import type { BilingualText } from '../../lib/types';
import './BilingualSummary.css';

interface BilingualSummaryProps {
  title: BilingualText;
  summary: BilingualText;
  journalColor: string;
}

/**
 * Detect if a summary uses the structured 4-part format.
 * Chinese: 【總結】...【研究問題】...【研究方法】...【結果】...
 * English: **Summary:** ... **Problem:** ... **Approach:** ... **Results:** ...
 */
function isStructured(text: string): boolean {
  return (
    text.includes('【總結】') ||
    text.includes('【研究問題】') ||
    /\*\*Summary:\*\*/.test(text) ||
    /\*\*Problem:\*\*/.test(text)
  );
}

/**
 * Parse Chinese structured summary into sections.
 * Splits on 【...】 headers and returns { header, body } pairs.
 */
function parseZhSections(text: string): { header: string; body: string }[] {
  const regex = /【([^】]+)】/g;
  const sections: { header: string; body: string }[] = [];

  // Check for leading text before first section marker
  const firstMatch = text.match(/【[^】]+】/);
  if (firstMatch && firstMatch.index && firstMatch.index > 0) {
    const leadingText = text.slice(0, firstMatch.index).trim();
    if (leadingText) {
      sections.push({ header: '', body: leadingText });
    }
  }

  const matches: { header: string; start: number; end: number }[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    matches.push({
      header: match[1],
      start: match.index,
      end: match.index + match[0].length,
    });
  }

  for (let i = 0; i < matches.length; i++) {
    const bodyStart = matches[i].end;
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const body = text.slice(bodyStart, bodyEnd).trim();
    sections.push({ header: matches[i].header, body });
  }

  return sections;
}

/**
 * Parse English structured summary into sections.
 * Splits on **Header:** markers and returns { header, body } pairs.
 */
function parseEnSections(text: string): { header: string; body: string }[] {
  const regex = /\*\*([^*]+):\*\*/g;
  const sections: { header: string; body: string }[] = [];

  // Check for leading text before first section marker
  const firstMatch = text.match(/\*\*[^*]+:\*\*/);
  if (firstMatch && firstMatch.index && firstMatch.index > 0) {
    const leadingText = text.slice(0, firstMatch.index).trim();
    if (leadingText) {
      sections.push({ header: '', body: leadingText });
    }
  }

  const matches: { header: string; start: number; end: number }[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    matches.push({
      header: match[1].trim(),
      start: match.index,
      end: match.index + match[0].length,
    });
  }

  for (let i = 0; i < matches.length; i++) {
    const bodyStart = matches[i].end;
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const body = text.slice(bodyStart, bodyEnd).trim();
    sections.push({ header: matches[i].header, body });
  }

  return sections;
}

/**
 * Render inline markdown: **bold** and *italic*.
 * Returns an array of React elements.
 */
function renderInlineMarkdown(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[1]) {
      parts.push(<strong key={key++}>{match[1]}</strong>);
    } else if (match[2]) {
      parts.push(<em key={key++}>{match[2]}</em>);
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

function StructuredSection({
  header,
  body,
  lang,
}: {
  header: string;
  body: string;
  lang: 'zh' | 'en';
}) {
  const paragraphs = body.split('\n\n').filter(Boolean);

  return (
    <div className="structured-section">
      {header && (
        <h4 className={`structured-section__header structured-section__header--${lang}`}>
          {header}
        </h4>
      )}
      {paragraphs.map((para, i) => (
        <p key={i}>
          {lang === 'en' ? renderInlineMarkdown(para) : para}
        </p>
      ))}
    </div>
  );
}

/**
 * Render plain (non-structured) paragraphs with inline markdown support.
 */
function PlainParagraphs({ text, lang }: { text: string; lang: 'zh' | 'en' }) {
  return (
    <>
      {text.split('\n\n').map((para, i) => (
        <p key={i}>
          {lang === 'en' ? renderInlineMarkdown(para) : para}
        </p>
      ))}
    </>
  );
}

export function BilingualSummary({ title, summary, journalColor }: BilingualSummaryProps) {
  const zhSections = isStructured(summary.zh) ? parseZhSections(summary.zh) : null;
  const enSections = isStructured(summary.en) ? parseEnSections(summary.en) : null;

  return (
    <div className="bilingual-summary">
      <section
        className="bilingual-summary__section bilingual-summary__zh"
        style={{ '--section-accent': journalColor } as React.CSSProperties}
      >
        <span className="bilingual-summary__lang-label">中文</span>
        <h2 className="bilingual-summary__title-zh heading-zh">{title.zh}</h2>
        <div className="bilingual-summary__body bilingual-summary__body-zh" lang="zh-Hant">
          {zhSections ? (
            zhSections.map((sec, i) => (
              <StructuredSection key={i} header={sec.header} body={sec.body} lang="zh" />
            ))
          ) : (
            <PlainParagraphs text={summary.zh} lang="zh" />
          )}
        </div>
      </section>

      <hr className="bilingual-summary__divider" />

      <section
        className="bilingual-summary__section bilingual-summary__en"
        style={{ '--section-accent': journalColor } as React.CSSProperties}
      >
        <span className="bilingual-summary__lang-label">English</span>
        <h2 className="bilingual-summary__title-en heading-en">{title.en}</h2>
        <div className="bilingual-summary__body bilingual-summary__body-en" lang="en">
          {enSections ? (
            enSections.map((sec, i) => (
              <StructuredSection key={i} header={sec.header} body={sec.body} lang="en" />
            ))
          ) : (
            <PlainParagraphs text={summary.en} lang="en" />
          )}
        </div>
      </section>
    </div>
  );
}
