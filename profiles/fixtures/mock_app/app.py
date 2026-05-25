from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ITEMS: dict[str, dict] = {}
SETTINGS: dict[str, str] = {
    "alert_email": "alerts@example.test",
    "maintenance_window": "Sunday 02:00 UTC",
    "retention_days": "30",
}


def settings_html() -> bytes:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>OpsBoard Settings</title>
</head>
<body>
  <header>
    <h1>Workspace Settings</h1>
    <nav>
      <a href="/dashboard.html">Dashboard</a>
      <a href="/users.html">Users</a>
      <a href="/reports.html">Reports</a>
      <a href="/items.html">Items</a>
    </nav>
  </header>
  <main>
    <section>
      <h2>Notification Policy</h2>
      <p>Alert email: {SETTINGS['alert_email']}</p>
      <p>Maintenance window: {SETTINGS['maintenance_window']}</p>
      <p>Retention days: {SETTINGS['retention_days']}</p>
      <form action="/settings.html" method="post" aria-label="Notification policy">
        <label for="alert-email">Alert email</label>
        <input id="alert-email" name="alert_email" type="email" value="{SETTINGS['alert_email']}" required>
        <label for="maintenance-window">Maintenance window</label>
        <input id="maintenance-window" name="maintenance_window" type="text" value="{SETTINGS['maintenance_window']}" placeholder="Sunday 02:00 UTC">
        <label for="retention-days">Retention days</label>
        <input id="retention-days" name="retention_days" type="number" min="1" max="365" value="{SETTINGS['retention_days']}">
        <button type="submit">Save settings</button>
      </form>
    </section>
  </main>
</body>
</html>""".encode("utf-8")


class MockAppHandler(SimpleHTTPRequestHandler):
    def api_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/items":
            self.api_response(200, {"items": list(ITEMS.values())})
            return
        if self.path in {"/settings.html", "/settings"}:
            body = settings_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/items":
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length) or b"{}")
            name = str(payload.get("item_name", "")).strip()
            if not 1 <= len(name) <= 10:
                self.api_response(400, {"error": "Item Name Length: 1 ~ 10"})
                return
            item = {
                "item_name": name,
                "service_port": str(payload.get("service_port", "")).strip(),
                "enabled": bool(payload.get("enabled", False)),
            }
            ITEMS[name] = item
            self.api_response(200, {"item": item})
            return
        if self.path in {"/settings.html", "/settings"}:
            from urllib.parse import parse_qs

            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = parse_qs(self.rfile.read(length).decode("utf-8"))
            for key in ("alert_email", "maintenance_window", "retention_days"):
                if key in payload:
                    SETTINGS[key] = payload[key][0]
            self.send_response(303)
            self.send_header("Location", "/settings.html")
            self.end_headers()
            return
        target = self.path if self.path.endswith(".html") else "/dashboard.html"
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()

    def do_PATCH(self) -> None:
        if self.path.startswith("/api/items/"):
            name = unquote(self.path.rsplit("/", 1)[-1])
            item = ITEMS.get(name)
            if not item:
                self.api_response(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if "enabled" in payload:
                item["enabled"] = bool(payload["enabled"])
            self.api_response(200, {"item": item})
            return
        self.api_response(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        if self.path.startswith("/api/items/"):
            name = unquote(self.path.rsplit("/", 1)[-1])
            ITEMS.pop(name, None)
            self.api_response(200, {"deleted": name})
            return
        self.api_response(404, {"error": "not found"})


def main() -> None:
    root = Path(__file__).parent / "site"
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), lambda *args, **kwargs: MockAppHandler(*args, directory=str(root), **kwargs))
    print(f"OpsBoard mock app listening on http://0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
