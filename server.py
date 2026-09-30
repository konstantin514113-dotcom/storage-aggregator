"""Статический сервер прототипа kubometr.html для Railway.

storage-parser/*.py — отдельные batch-скрипты (2ГИС, краулер, dedupe), запускаются
разово через `railway run`, а не этим сервером.
"""
import http.server
import os

PORT = int(os.environ.get("PORT", 8080))
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.path = "/kubometr.html"
        return super().do_GET()


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {ROOT} on 0.0.0.0:{PORT}")
        httpd.serve_forever()
