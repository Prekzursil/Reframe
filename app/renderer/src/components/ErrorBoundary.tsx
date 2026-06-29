// ErrorBoundary.tsx — a small, reusable render-error containment boundary.
//
// React unmounts the ENTIRE tree from the nearest root when a render/lifecycle
// throw is uncaught, blanking the whole app. Wrapping a fragile subtree in this
// boundary contains the failure to an inline alert so the rest of the shell
// keeps working (DESIGN: a panel failure must never be app-fatal). It is a thin
// class component (the only React API able to catch render errors) with no
// dependencies, so any panel can adopt it.
import React from 'react';

export interface ErrorBoundaryProps {
  children: React.ReactNode;
  /** Inline fallback. Receives the caught error; defaults to a quiet alert. */
  fallback?: (error: Error) => React.ReactNode;
  /** Optional side-effect sink for logging/telemetry (never rethrows). */
  onError?: (error: Error, info: React.ErrorInfo) => void;
  /** Accessible label for the default fallback region. */
  label?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    this.props.onError?.(error, info);
  }

  render(): React.ReactNode {
    const { error } = this.state;
    if (error) {
      if (this.props.fallback) return this.props.fallback(error);
      return (
        <p
          className="error-boundary__fallback jobqueue__error"
          role="alert"
          aria-label={this.props.label}
        >
          {error.message}
        </p>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
