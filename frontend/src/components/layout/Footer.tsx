import { Link } from 'react-router-dom';
import { SITE_NAME } from '../../lib/constants';
import './Footer.css';

export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__inner container">
        <div className="footer__brand">
          <span className="footer__name">{SITE_NAME}</span>
          <span className="footer__tagline">
            AI 驅動的雙語學術期刊封面故事摘要平台
          </span>
        </div>

        <div className="footer__intro">
          <p className="footer__intro-text" lang="zh-Hant">
            本站運用人工智慧技術，為讀者整理 Science、Nature、Cell
            等自然科學期刊以及 Political Geography、International Organization、American Sociological Review
            等社會科學期刊中的最新開放取用（Open Access）研究，以中英雙語摘要形式呈現，協助讀者快速瞭解全球學術前沿。
          </p>
          <p className="footer__intro-text" lang="zh-Hant">
            本站所有內容皆基於各期刊公開發布之開放取用文章。所有摘要均由 AI 生成，僅供教育與資訊參考，不構成學術引用依據。
            原始論文之著作權歸屬各出版機構與作者所有，本站不主張對原始論文內容之任何權利。
            如需引用，敬請參閱各期刊官方發表版本。
          </p>
          <p className="footer__intro-text" lang="en">
            This site leverages artificial intelligence to provide bilingual (Chinese/English) summaries of
            the latest Open Access research from leading natural-science journals (Science, Nature, Cell) and
            social-science journals (Political Geography, International Organization, American Sociological Review),
            helping readers stay informed about global academic developments.
          </p>
          <p className="footer__intro-text" lang="en">
            All content is based on publicly available Open Access articles from each journal.
            Summaries are AI-generated for educational and informational purposes only and do not constitute
            a basis for academic citation. Copyright of all original articles remains with the respective
            publishers and authors. For authoritative references, please consult the official publications.
          </p>
        </div>

        <div className="footer__meta">
          <div className="footer__credits">
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
          <div className="footer__links">
            <Link to="/privacy" className="footer__link">
              隱私權政策 / Privacy Policy
            </Link>
          </div>
          <span className="footer__copyright">
            &copy; {new Date().getFullYear()} {SITE_NAME}
          </span>
        </div>
      </div>
    </footer>
  );
}
