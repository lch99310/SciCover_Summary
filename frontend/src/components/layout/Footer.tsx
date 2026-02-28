import { SITE_NAME } from '../../lib/constants';
import './Footer.css';

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner container">
        <div className="footer__brand">
          <span className="footer__name">{SITE_NAME}</span>
          <span className="footer__tagline">
            AI-powered bilingual science journalism
          </span>
        </div>
        <div className="footer__meta">
          <span className="footer__disclaimer">
            Summaries are AI-generated for educational purposes.
            Always refer to the original publications for authoritative content.
          </span>
          <div className="footer__links">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="footer__link"
            >
              GitHub
            </a>
            <span className="footer__separator">·</span>
            <span className="footer__copyright">
              {new Date().getFullYear()} {SITE_NAME}
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
