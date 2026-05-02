import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { SITE_NAME } from '../../lib/constants';
import './LegalPage.css';

export function PrivacyPage() {
  useEffect(() => {
    document.title = `Privacy Policy / 隱私權政策 — ${SITE_NAME}`;
    return () => { document.title = SITE_NAME; };
  }, []);

  return (
    <article className="legal-page container reading-column">
      <header className="legal-page__header">
        <h1 className="legal-page__title">Privacy Policy / 隱私權政策</h1>
        <p className="legal-page__updated">
          Last updated / 最後更新：2026-05-02
        </p>
      </header>

      <section className="legal-page__section" lang="en">
        <h2>English</h2>

        <h3>1. Who we are</h3>
        <p>
          {SITE_NAME} (the &ldquo;Site&rdquo;) is a non-commercial educational
          project that publishes AI-generated bilingual summaries of Open Access
          academic articles. The Site is maintained by{' '}
          <a
            href="https://lch99310.github.io/chunghao_lee/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Chung-Hao Lee
          </a>{' '}
          and hosted on GitHub Pages.
        </p>

        <h3>2. Data we collect</h3>
        <p>
          We do not directly collect or store any personal data on our own
          servers. The Site is a static website served by GitHub Pages.
        </p>
        <p>
          We use <strong>Google Analytics 4</strong> to understand how visitors
          interact with the Site. Google Analytics may collect, in anonymized
          or aggregated form, information such as:
        </p>
        <ul>
          <li>IP address (anonymized by Google)</li>
          <li>Device type, browser, operating system, and screen size</li>
          <li>Pages visited and time spent</li>
          <li>Referring website</li>
          <li>Approximate geographic region</li>
        </ul>

        <h3>3. Cookies</h3>
        <p>
          Google Analytics sets cookies (such as <code>_ga</code> and{' '}
          <code>_ga_*</code>) in your browser to distinguish unique visitors and
          sessions. The Site itself stores small preference values in your
          browser&rsquo;s <code>localStorage</code> (theme choice, dismissal of
          this notice, last-selected journal tab). These preferences never leave
          your device.
        </p>

        <h3>4. Third-party services</h3>
        <ul>
          <li>
            <strong>GitHub Pages</strong> &mdash; hosting. See{' '}
            <a
              href="https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub&rsquo;s Privacy Statement
            </a>
            .
          </li>
          <li>
            <strong>Google Analytics 4</strong> &mdash; visit analytics. See{' '}
            <a
              href="https://policies.google.com/privacy"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google&rsquo;s Privacy Policy
            </a>
            .
          </li>
          <li>
            <strong>Google Fonts</strong> &mdash; web fonts. See{' '}
            <a
              href="https://developers.google.com/fonts/faq/privacy"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google Fonts &amp; Privacy
            </a>
            .
          </li>
        </ul>

        <h3>5. How to opt out</h3>
        <p>
          To opt out of Google Analytics tracking across all sites, you can
          install Google&rsquo;s official{' '}
          <a
            href="https://tools.google.com/dlpage/gaoptout"
            target="_blank"
            rel="noopener noreferrer"
          >
            Browser Add-on
          </a>
          , use your browser&rsquo;s &ldquo;Do Not Track&rdquo; setting, or
          block third-party cookies. You can also clear cookies and local
          storage at any time via your browser settings.
        </p>

        <h3>6. Your rights</h3>
        <p>
          Depending on your jurisdiction, you may have rights to access,
          correct, delete, or restrict the processing of personal data we
          process about you, and to lodge a complaint with a data protection
          authority. Because we do not directly store personal data, requests
          related to Google Analytics data should be directed to Google.
        </p>

        <h3>7. Changes to this policy</h3>
        <p>
          We may update this policy from time to time. The &ldquo;Last
          updated&rdquo; date above reflects the most recent revision.
        </p>

        <h3>8. Contact</h3>
        <p>
          For questions about this policy, please contact the maintainer via
          the personal homepage linked above.
        </p>
      </section>

      <hr className="legal-page__divider" />

      <section className="legal-page__section" lang="zh-Hant">
        <h2>繁體中文</h2>

        <h3>1. 我們是誰</h3>
        <p>
          {SITE_NAME}（以下稱「本站」）為一非商業性質的教育專案，提供以 AI
          生成的開放取用（Open Access）學術論文雙語摘要。本站由{' '}
          <a
            href="https://lch99310.github.io/chunghao_lee/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Chung-Hao Lee
          </a>{' '}
          維護，託管於 GitHub Pages。
        </p>

        <h3>2. 我們收集的資料</h3>
        <p>
          本站為靜態網站，不在自有伺服器上直接收集或儲存任何個人資料。
        </p>
        <p>
          本站使用 <strong>Google Analytics 4</strong>{' '}
          以了解訪客如何與本站互動。Google Analytics
          可能以匿名化或彙總形式收集下列資訊：
        </p>
        <ul>
          <li>IP 位址（由 Google 匿名化處理）</li>
          <li>裝置類型、瀏覽器、作業系統與螢幕尺寸</li>
          <li>造訪頁面與停留時間</li>
          <li>來源網站</li>
          <li>大致地理位置</li>
        </ul>

        <h3>3. Cookie 使用</h3>
        <p>
          Google Analytics 會在您的瀏覽器中設置 cookie（例如 <code>_ga</code>{' '}
          與 <code>_ga_*</code>），以辨識不重複訪客與工作階段。本站本身僅在您的
          瀏覽器 <code>localStorage</code>{' '}
          中保存少量偏好設定（主題、是否已關閉本提示、上次選取的期刊分類），
          這些偏好不會離開您的裝置。
        </p>

        <h3>4. 第三方服務</h3>
        <ul>
          <li>
            <strong>GitHub Pages</strong>：網站託管。詳見{' '}
            <a
              href="https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement"
              target="_blank"
              rel="noopener noreferrer"
            >
              GitHub 隱私權聲明
            </a>
            。
          </li>
          <li>
            <strong>Google Analytics 4</strong>：流量分析。詳見{' '}
            <a
              href="https://policies.google.com/privacy?hl=zh-TW"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google 隱私權政策
            </a>
            。
          </li>
          <li>
            <strong>Google Fonts</strong>：網頁字型。詳見{' '}
            <a
              href="https://developers.google.com/fonts/faq/privacy"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google Fonts 與隱私
            </a>
            。
          </li>
        </ul>

        <h3>5. 如何停用追蹤</h3>
        <p>
          若您不希望被 Google Analytics 追蹤，可安裝 Google 官方提供的{' '}
          <a
            href="https://tools.google.com/dlpage/gaoptout?hl=zh-TW"
            target="_blank"
            rel="noopener noreferrer"
          >
            停用工具瀏覽器外掛
          </a>
          、開啟瀏覽器的「Do Not Track」設定，或封鎖第三方 cookie。
          您也可隨時透過瀏覽器設定清除 cookie 與本機儲存資料。
        </p>

        <h3>6. 您的權利</h3>
        <p>
          依您所在司法管轄區之規定，您可能有權查閱、更正、刪除或限制本站處理
          您的個人資料，並可向當地資料保護主管機關提出申訴。由於本站並不直接
          儲存個人資料，與 Google Analytics 資料相關之請求請逕向 Google 提出。
        </p>

        <h3>7. 政策變更</h3>
        <p>
          本政策可能不定期更新，最新修訂日期以本頁頂部「最後更新」日期為準。
        </p>

        <h3>8. 聯絡方式</h3>
        <p>
          如對本政策有任何疑問，請透過上方連結之個人首頁與維護者聯絡。
        </p>
      </section>

      <p className="legal-page__back">
        <Link to="/">&larr; 回到首頁 / Back to home</Link>
      </p>
    </article>
  );
}
