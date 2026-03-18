from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from bambulab_metrics_exporter import __version__
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.metrics import ExporterMetrics


def build_app(metrics: ExporterMetrics, collector: PollingCollector) -> FastAPI:
    app = FastAPI(title="bambulab-metrics-exporter", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def root_handler() -> HTMLResponse:
        ready = collector.ready
        ready_color = "#22c55e" if ready else "#eab308"
        ready_label = "Connected" if ready else "Warming Up"
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bambu Lab Metrics Exporter</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --border: #334155;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
  }}
  body {{
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
  }}
  .container {{
    width: 100%;
    max-width: 480px;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }}
  header {{
    text-align: center;
  }}
  header h1 {{
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--text);
  }}
  header .version {{
    font-size: 0.85rem;
    color: var(--muted);
    margin-top: 0.25rem;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem 1.5rem;
  }}
  .card-title {{
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 1rem;
  }}
  .status-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
  }}
  .status-row + .status-row {{
    border-top: 1px solid var(--border);
  }}
  .status-name {{
    font-size: 0.95rem;
    color: var(--text);
  }}
  .status-badge {{
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    color: var(--muted);
  }}
  .dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  footer {{
    text-align: center;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  footer a {{
    color: var(--accent);
    text-decoration: none;
  }}
  footer a:hover {{
    text-decoration: underline;
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Bambu Lab Metrics Exporter</h1>
    <div class="version">v{__version__}</div>
  </header>
  <div class="card">
    <div class="card-title">Status</div>
    <div class="status-row">
      <span class="status-name">Health</span>
      <span class="status-badge">
        <span class="dot" style="background:#22c55e;"></span>
        Live
      </span>
    </div>
    <div class="status-row">
      <span class="status-name">Ready</span>
      <span class="status-badge">
        <span class="dot" style="background:{ready_color};"></span>
        {ready_label}
      </span>
    </div>
  </div>
  <footer>
    <a href="https://github.com/TheBlackBush/bambulab_metrics_exporter" target="_blank" rel="noopener">
      github.com/TheBlackBush/bambulab_metrics_exporter
    </a>
  </footer>
</div>
</body>
</html>"""
        return HTMLResponse(content=html)

    @app.get("/metrics")
    def metrics_handler() -> Response:
        data = generate_latest(metrics.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health_handler() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready_handler() -> dict[str, str]:
        if collector.ready:
            return {"status": "ready"}
        raise HTTPException(status_code=503, detail="warming_up")

    return app
