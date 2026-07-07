// ErrorBoundary.tsx — the top-level renderer crash backstop (WU2 resilience).
//
// React has NO built-in recovery: any error thrown during a child's render (or a
// lifecycle/effect that re-throws to the nearest boundary) unmounts the ENTIRE
// tree, leaving a blank #root the user cannot escape. This class component is the
// PRIMARY backstop wired around <App/> in main.tsx: getDerivedStateFromError swaps
// the crashed subtree for an inline, honest fallback (what happened + a reload
// affordance) so a single failing component degrades to a recoverable message
// instead of a white screen. componentDidCatch logs the failure for diagnosis.
//
// Deliberately self-contained (inline styles, no stylesheet import): the fallback
// must render even when a broken CSS load or bridge is the very thing that failed.
import React from 'react';

export interface ErrorBoundaryProps {
  /** The subtree this boundary protects. */
  children: React.ReactNode;
  /**
   * Reload handler for the fallback control. Injectable for tests; defaults to a
   * full window reload (the honest recovery for a crashed renderer). Kept as a
   * prop so the packaged app and unit tests share one code path.
   */
  onReload?: () => void;
}

interface ErrorBoundaryState {
  /** The caught error, or null while the subtree is healthy. */
  error: Error | null;
}

const FALLBACK_STYLE: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '0.75rem',
  alignItems: 'flex-start',
  maxWidth: '32rem',
  margin: '4rem auto',
  padding: '1.5rem',
  borderRadius: '0.5rem',
  border: '1px solid #3a3a44',
  background: '#1a1a20',
  color: '#e6e6ea',
  font: '14px/1.5 system-ui, sans-serif',
};

const BUTTON_STYLE: React.CSSProperties = {
  padding: '0.5rem 1rem',
  borderRadius: '0.375rem',
  border: '1px solid #5a5a68',
  background: '#2a2a34',
  color: '#e6e6ea',
  cursor: 'pointer',
  font: 'inherit',
};

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // The one place we learn WHY the renderer crashed — log it (component stack
    // included) so a packaged-build crash is diagnosable, then show the fallback.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] renderer subtree crashed:', error, info.componentStack);
  }

  private handleReload = (): void => {
    const { onReload } = this.props;
    if (onReload) {
      onReload();
    } else {
      window.location.reload();
    }
  };

  render(): React.ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    return (
      <div role="alert" style={FALLBACK_STYLE} data-testid="error-boundary-fallback">
        <h1 style={{ margin: 0, fontSize: '1.1rem' }}>Something went wrong</h1>
        <p style={{ margin: 0 }}>
          Reframe hit an unexpected error and could not finish drawing this screen. Your files and
          projects are safe — reloading usually clears it.
        </p>
        <p style={{ margin: 0, opacity: 0.75, fontSize: '0.85rem' }} data-role="error-detail">
          {error.message}
        </p>
        <button type="button" data-action="reload" style={BUTTON_STYLE} onClick={this.handleReload}>
          Reload Reframe
        </button>
      </div>
    );
  }
}

export default ErrorBoundary;
