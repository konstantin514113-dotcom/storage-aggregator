"""Сервер прототипа kubometr.html для Railway: статика + JSON API к Postgres.

GET /api/cities             — города, в которых есть записи (отсортированы по числу складов)
GET /api/storages?city=...  — склады города (дубли по duplicate_of уже исключены)
"""
import http.server
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage-parser"))
from db.connection import get_cursor

PORT = int(os.environ.get("PORT", 8080))
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.path = "/kubometr.html"
            return super().do_GET()
        if path == "/api/cities":
            return self.send_cities()
        if path == "/api/storages":
            return self.send_storages()
        return super().do_GET()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_cities(self):
        try:
            with get_cursor(commit=False) as cur:
                cur.execute(
                    """
                    SELECT city, COUNT(*) AS n
                    FROM storages
                    WHERE duplicate_of IS NULL
                    GROUP BY city
                    ORDER BY n DESC, city
                    """
                )
                rows = cur.fetchall()
            self.send_json([r["city"] for r in rows])
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def send_storages(self):
        qs = parse_qs(urlparse(self.path).query)
        city = (qs.get("city") or [""])[0]
        if not city:
            return self.send_json({"error": "city is required"}, 400)
        try:
            with get_cursor(commit=False) as cur:
                cur.execute(
                    """
                    SELECT id, source, category, city, region, name, address,
                           lat, lon, phone, price_from::float AS price_from, box_sizes
                    FROM storages
                    WHERE duplicate_of IS NULL AND city = %(city)s
                    ORDER BY price_from ASC NULLS LAST, name
                    """,
                    {"city": city},
                )
                rows = cur.fetchall()
            self.send_json(rows)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {ROOT} on 0.0.0.0:{PORT}")
        httpd.serve_forever()
