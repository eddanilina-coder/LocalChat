"""HTTP server with static index.html and simple REST API."""

import json
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler

from . import config
from .state import connected, history


class IndexAndApiHandler(SimpleHTTPRequestHandler):
    """HTTP-обработчик, раздающий index.html и REST-эндпоинты."""

    def _send_json(self, obj: dict, status: int = 200) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # type: ignore[override]
        # REST API
        if self.path == "/api/health":
            self._send_json({"status": "ok"})
            return

        if self.path == "/api/users":
            users = list(connected.values())
            self._send_json({"users": users})
            return

        if self.path == "/api/history":
            self._send_json({"messages": list(history)})
            return

        # Статика
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"

        return super().do_GET()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logging.info("HTTP: " + format, *args)


def start_http_server() -> None:
    """Запуск HTTP-сервера в текущем потоке."""
    httpd = HTTPServer((config.HTTP_HOST, config.HTTP_PORT), IndexAndApiHandler)
    logging.info("HTTP server listening on %s:%d", config.HTTP_HOST, config.HTTP_PORT)
    httpd.serve_forever()

