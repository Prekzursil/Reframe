// main.tsx — React 18 renderer entry (CONTRACTS.md §1: src/main.tsx).
// Mounts <App/> into #root from index.html. No global app state, no network —
// all compute flows through the preload `window.api` bridge.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

const container = document.getElementById('root');
if (!container) {
  throw new Error('#root element not found in index.html');
}

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
