import "./styles.css";

function App() {
  return (
    <main className="app-shell">
      <header className="app-header">
        <p className="eyebrow">Reframe</p>
        <h1>Media tooling coming soon</h1>
        <p className="lead">
          React + Vite + TypeScript scaffold. Wire this to the API once endpoints land.
        </p>
      </header>
      <section className="card">
        <h2>Next steps</h2>
        <ul>
          <li>Configure API base URL and shared fetch client.</li>
          <li>Add routing for Captions, Subtitle Styling, Shorts, and Jobs.</li>
          <li>Implement upload flows and status polling.</li>
        </ul>
      </section>
    </main>
  );
}

export default App;
