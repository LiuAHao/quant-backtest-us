import { Activity, Database, FileText, LineChart } from "lucide-react";

const modules = [
  {
    title: "US Market Data",
    description: "Prepare adapters, calendars, instruments, and local daily-bar storage.",
    icon: Database,
  },
  {
    title: "Backtest Engine",
    description: "Design a new engine around US equities, ETFs, and future corporate-action handling.",
    icon: Activity,
  },
  {
    title: "Strategy Research",
    description: "Build reusable strategy templates for momentum, volatility, liquidity, and fundamentals.",
    icon: LineChart,
  },
  {
    title: "Reports",
    description: "Create JSON and HTML outputs once the US research workflow is defined.",
    icon: FileText,
  },
];

function App() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Quant Backtest US</p>
        <h1>US equity research skeleton</h1>
        <p className="summary">
          The old A-share implementation has been cleared. This workspace is ready for a fresh US data,
          backtesting, strategy, and reporting stack.
        </p>
        <div className="status-row" aria-label="Project status">
          <span>Backend: skeleton</span>
          <span>Data: local only</span>
          <span>Market: US equities</span>
        </div>
      </section>

      <section className="module-grid" aria-label="Planned modules">
        {modules.map((item) => {
          const Icon = item.icon;
          return (
            <article className="module-card" key={item.title}>
              <Icon size={22} aria-hidden="true" />
              <h2>{item.title}</h2>
              <p>{item.description}</p>
            </article>
          );
        })}
      </section>
    </main>
  );
}

export default App;
