"""Сервер прототипа kubometr.html для Railway: статика + JSON API к Postgres + SEO-страницы городов.

GET  /api/cities             — города, в которых есть записи (отсортированы по числу складов)
GET  /api/storages?city=...  — склады города (дубли по duplicate_of уже исключены)
POST /api/bookings           — создать заявку на бронь {storage_id, phone, date_from?, months?}
GET  /sklady/<slug>          — SEO-страница города: свой title/description + отрисованные
                                 карточки в исходном HTML (не только через JS), чтобы индексировалось
GET  /sitemap.xml, /robots.txt
"""
import html
import http.server
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage-parser"))
from db.connection import get_cursor

PORT = int(os.environ.get("PORT", 8080))
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE_URL = os.environ.get("SITE_URL", "https://storage-aggregator-web-production.up.railway.app")
SERVICE_FEE = 500  # должен совпадать с SERVICE_FEE в kubometr.html
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(city: str) -> str:
    out = []
    for ch in city.lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.send_home()
        if path == "/api/cities":
            return self.send_cities()
        if path == "/api/storages":
            return self.send_storages()
        if path == "/sitemap.xml":
            return self.send_sitemap()
        if path == "/robots.txt":
            return self.send_robots()
        if path.startswith("/sklady/"):
            return self.send_city_page(path[len("/sklady/"):])
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/bookings":
            return self.create_booking()
        self.send_json({"error": "not found"}, 404)

    def send_html(self, body: str, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, body: str, content_type="text/plain; charset=utf-8", status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_cities(self):
        try:
            rows = fetch_cities_with_counts()
            self.send_json([r["city"] for r in rows])
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def send_storages(self):
        qs = parse_qs(urlparse(self.path).query)
        city = (qs.get("city") or [""])[0]
        if not city:
            return self.send_json({"error": "city is required"}, 400)
        try:
            self.send_json(fetch_storages(city))
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    # ---------- SEO-страницы ----------
    def send_home(self):
        try:
            cities = fetch_cities_with_counts()
        except Exception:
            cities = []
        nav_html = render_city_nav(cities)
        page = read_template()
        page = inject_before(page, "</body>", nav_html)
        self.send_html(page)

    def send_city_page(self, slug):
        slug = slug.strip("/")
        try:
            cities = fetch_cities_with_counts()
        except Exception as e:
            return self.send_html(f"<h1>Ошибка базы данных</h1><p>{html.escape(str(e))}</p>", 500)

        match = next((c for c in cities if slugify(c["city"]) == slug), None)
        if not match:
            return self.send_html("<h1>Город не найден</h1><p><a href=\"/\">На главную</a></p>", 404)

        city = match["city"]
        try:
            storages = fetch_storages(city)
        except Exception as e:
            return self.send_html(f"<h1>Ошибка базы данных</h1><p>{html.escape(str(e))}</p>", 500)

        prices = [s["price_from"] for s in storages if s["price_from"] is not None]
        min_price = int(min(prices)) if prices else None
        title = f"Аренда склада в {city} — мини-склады и self-storage | Куб"
        if min_price:
            description = (
                f"{len(storages)} складов и боксов для хранения в {city}: цены от "
                f"{min_price:,} ₽/мес. Сравните варианты и оставьте заявку на Кубе."
            ).replace(",", " ")
        else:
            description = f"{len(storages)} складов и боксов для хранения в {city}. Сравните варианты на Кубе."

        page = read_template()
        page = page.replace(
            "<title>Куб — мини-склады в вашем городе</title>",
            f"<title>{html.escape(title)}</title>\n"
            f'<meta name="description" content="{html.escape(description)}">\n'
            f'<link rel="canonical" href="{SITE_URL}/sklady/{slug}">',
        )
        page = page.replace(
            '<div class="cards" id="cards"></div>',
            f'<div class="cards" id="cards">{render_cards_html(storages)}</div>',
        )
        page = inject_before(
            page, "</head>",
            f'<script>window.PRESET_CITY = {json.dumps(city, ensure_ascii=False)};</script>\n',
        )
        page = inject_before(page, "</body>", render_city_nav(cities, current=city))
        self.send_html(page)

    def send_sitemap(self):
        try:
            cities = fetch_cities_with_counts()
        except Exception:
            cities = []
        urls = [f"{SITE_URL}/"] + [f"{SITE_URL}/sklady/{slugify(c['city'])}" for c in cities]
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        for u in urls:
            body += f"  <url><loc>{html.escape(u)}</loc></url>\n"
        body += "</urlset>\n"
        self.send_text(body, "application/xml; charset=utf-8")

    def send_robots(self):
        self.send_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")

    def create_booking(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "invalid json"}, 400)

        storage_id = payload.get("storage_id")
        phone = (payload.get("phone") or "").strip()
        date_from = (payload.get("date_from") or "").strip() or None
        try:
            months = max(1, int(payload.get("months") or 1))
        except (TypeError, ValueError):
            months = 1

        if not isinstance(storage_id, int):
            return self.send_json({"error": "storage_id must be an integer"}, 400)
        if len(phone) < 5:
            return self.send_json({"error": "phone is required"}, 400)
        if date_from and not DATE_RE.match(date_from):
            return self.send_json({"error": "date_from must be YYYY-MM-DD"}, 400)

        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT id FROM storages WHERE id = %(id)s AND duplicate_of IS NULL",
                    {"id": storage_id},
                )
                if not cur.fetchone():
                    return self.send_json({"error": "storage not found"}, 404)
                cur.execute(
                    """
                    INSERT INTO bookings (storage_id, client_phone, date_from, months, service_fee)
                    VALUES (%(storage_id)s, %(phone)s, %(date_from)s, %(months)s, %(fee)s)
                    RETURNING id
                    """,
                    {
                        "storage_id": storage_id,
                        "phone": phone,
                        "date_from": date_from,
                        "months": months,
                        "fee": SERVICE_FEE,
                    },
                )
                booking_id = cur.fetchone()["id"]
            self.send_json({"id": booking_id, "status": "new"}, 201)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)


_CATEGORY_LABELS = {
    "self_storage": "самохранение",
    "warehouse_rental": "аренда склада",
    "logistics": "логистика",
    "wholesale": "опт",
    "industrial": "промышленный",
}
_SOURCE_LABELS = {"dgis": "2ГИС", "avito": "Avito"}
_TEMPLATE_CACHE = None


def read_template() -> str:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        with open(os.path.join(ROOT, "kubometr.html"), encoding="utf-8") as f:
            _TEMPLATE_CACHE = f.read()
    return _TEMPLATE_CACHE


def inject_before(page: str, marker: str, snippet: str) -> str:
    return page.replace(marker, snippet + marker, 1)


def fetch_cities_with_counts():
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
        return cur.fetchall()


def fetch_storages(city: str):
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
        return cur.fetchall()


def render_cards_html(storages, limit=60) -> str:
    parts = []
    for s in storages[:limit]:
        size = f', {html.escape(s["box_sizes"])}' if s["box_sizes"] else ""
        if s["price_from"] is not None:
            price_num = f'{int(round(s["price_from"])):,}'.replace(",", " ")
            price_html = f"<b>{price_num} ₽</b><span> / мес{size}</span>"
        else:
            price_html = f"<b>цена по запросу</b><span>{size}</span>"
        badges = "".join(
            f'<span class="badge">{html.escape(b)}</span>'
            for b in [_CATEGORY_LABELS.get(s["category"], s["category"]), _SOURCE_LABELS.get(s["source"], s["source"])]
            if b
        )
        name = html.escape(s["name"] or "Без названия")
        addr = html.escape(s["address"] or s["city"] or "")
        parts.append(
            '<div class="card">'
            f'<div class="card-top"><div><h3>{name}</h3><div class="addr">{addr}</div></div></div>'
            f'<div class="badges">{badges}</div>'
            f'<div class="card-bottom"><div class="price">{price_html}</div>'
            f'<button class="btn btn-primary btn-sm" data-book="{s["id"]}">Забронировать</button></div>'
            "</div>"
        )
    return "".join(parts)


def render_city_nav(cities, current=None) -> str:
    if not cities:
        return ""
    links = []
    for c in cities:
        city = c["city"]
        slug = slugify(city)
        cls = ' class="active"' if city == current else ""
        links.append(f'<a href="/sklady/{slug}"{cls}>{html.escape(city)} ({c["n"]})</a>')
    return (
        '<nav class="wrap" style="padding:16px 16px 30px;display:flex;flex-wrap:wrap;gap:10px;font-size:14px">'
        + "".join(links) + "</nav>\n"
    )


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Serving {ROOT} on 0.0.0.0:{PORT}")
        httpd.serve_forever()
