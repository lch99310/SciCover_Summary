import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { Footer } from './Footer';

interface LayoutProps {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
}

export function Layout({ theme, onToggleTheme }: LayoutProps) {
  return (
    <div className="app-layout">
      <Header
        theme={theme}
        onToggleTheme={onToggleTheme}
      />
      <main className="main-content">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
