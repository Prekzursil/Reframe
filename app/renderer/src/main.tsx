// main.tsx — React 18 renderer entry (CONTRACTS.md §1: src/main.tsx).
// Mounts <App/> into #root from index.html. No global app state, no network —
// all compute flows through the preload `window.api` bridge.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { ErrorBoundary } from './components/ErrorBoundary';

const container = document.getElementById('root');
if (!container) {
  throw new Error('#root element not found in index.html');
}

// WU2 resilience: <ErrorBoundary> is the PRIMARY backstop. React has no built-in
// recovery — any error thrown while a child renders unmounts the whole tree and
// leaves a blank #root. Wrapping <App/> here converts that white-screen into a
// recoverable inline fallback (honest copy + a reload control) for the entire UI.
createRoot(container).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
