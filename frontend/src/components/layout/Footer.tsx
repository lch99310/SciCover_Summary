import { SITE_NAME } from '../../lib/constants';
import './Footer.css';

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner container">
        <div className="footer__brand">
          <span className="footer__name">{SITE_NAME}</span>
          <span className="footer__tagline">
            AI 驅動的雙語科學期刊封面故事摘要平台
          </span>
        </div>

        <div className="footer__intro">
          <p className="footer__intro-text" lang="zh-Hant">
            本站透過人工智慧技術，自動擷取並翻譯 Science、Nature、Cell
            等國際頂尖科學期刊的每期封面故事，以中英雙語呈現研究摘要，旨在協助中文讀者快速掌握全球最新科學進展。
          </p>
          <p className="footer__intro-text" lang="zh-Hant">
            所有摘要內容均由 AI 自動生成，僅供教育與資訊參考用途，不構成任何學術引用依據。
            文章之著作權歸屬原出版機構與作者所有，本站不主張對原始論文內容之任何權利。
            如需引用，請以各期刊官方發表版本為準。
          </p>
          <p className="footer__intro-text" lang="en">
            This site uses artificial intelligence to automatically extract and translate cover stories
            from leading international science journals including Science, Nature, and Cell, presenting
            bilingual (Chinese/English) research summaries to help readers stay up to date with the
            latest scientific advances.
          </p>
          <p className="footer__intro-text" lang="en">
            All summaries are AI-generated and intended solely for educational and informational purposes.
            They do not constitute a basis for academic citation. Copyright of all articles belongs to
            the original publishers and authors. For authoritative content, please refer to the official
            publications from each journal.
          </p>
        </div>

        <div className="footer__meta">
          <div className="footer__credits">
            <p className="footer__credit-text" lang="zh-Hant">
              本站由{' '}
              <a
                href="https://lch99310.github.io/chunghao_lee/"
                target="_blank"
                rel="noopener noreferrer"
                className="footer__link"
              >
                Chung-Hao Lee
              </a>
              {' '}開發與維護
            </p>
            <p className="footer__credit-text" lang="en">
              Developed and maintained by{' '}
              <a
                href="https://lch99310.github.io/chunghao_lee/"
                target="_blank"
                rel="noopener noreferrer"
                className="footer__link"
              >
                Chung-Hao Lee
              </a>
            </p>
          </div>
          <span className="footer__copyright">
            &copy; {new Date().getFullYear()} {SITE_NAME}
          </span>
        </div>
      </div>
    </footer>
  );
}
