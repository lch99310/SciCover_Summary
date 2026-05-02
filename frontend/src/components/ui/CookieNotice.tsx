import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './CookieNotice.css';

const STORAGE_KEY = 'scicover-cookie-notice-dismissed';

export function CookieNotice() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (localStorage.getItem(STORAGE_KEY) !== '1') {
      setVisible(true);
    }
  }, []);

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, '1');
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="cookie-notice" role="dialog" aria-live="polite" aria-label="Cookie notice">
      <div className="cookie-notice__inner">
        <div className="cookie-notice__text">
          <p lang="zh-Hant">
            本站使用 Google Analytics 收集匿名化的造訪統計，以協助改善內容。
            繼續瀏覽即表示您了解相關資料處理方式。
          </p>
          <p lang="en">
            This site uses Google Analytics to collect anonymized visit statistics
            to help improve our content. By continuing to browse, you acknowledge this.
          </p>
        </div>
        <div className="cookie-notice__actions">
          <Link to="/privacy" className="cookie-notice__link">
            了解更多 / Learn more
          </Link>
          <button
            type="button"
            className="cookie-notice__dismiss"
            onClick={dismiss}
            aria-label="Dismiss cookie notice"
          >
            知道了 / Got it
          </button>
        </div>
      </div>
    </div>
  );
}
