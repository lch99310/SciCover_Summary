import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Catches render-time errors anywhere in the component tree and
 * displays a fallback UI instead of crashing to a blank screen.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(_error: Error): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[SciCover] Uncaught render error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          padding: '2rem',
          fontFamily: 'Inter, sans-serif',
          color: 'var(--color-text-secondary, #6B6B6B)',
          textAlign: 'center',
        }}>
          <h2 style={{ marginBottom: '0.5rem', color: 'var(--color-text-primary, #1A1A1A)' }}>
            Something went wrong
          </h2>
          <p>Please try refreshing the page.</p>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '1rem',
              padding: '0.5rem 1.5rem',
              border: '1px solid var(--color-border, #ccc)',
              borderRadius: '4px',
              background: 'var(--color-bg-surface, #fff)',
              color: 'var(--color-text-primary, #1A1A1A)',
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Refresh
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
