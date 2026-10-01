"""Сервер прототипа kubometr.html для Railway: статика + JSON API к Postgres + SEO-страницы городов.

GET  /api/cities             — города, в которых есть записи (отсортированы по числу складов)
GET  /api/storages?city=...  — склады города (дубли по duplicate_of уже исключены)
POST /api/bookings           — создать заявку на бронь {storage_id, phone, date_from?, months?}
GET  /sklady/<slug>          — SEO-страница города: свой title/description + отрисованные
                                 карточки в исходном HTML (не только через JS), чтобы индексировалось
GET  /sitemap.xml, /robots.txt
"""
import base64
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
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


PREPOSITIONAL_OVERRIDES = {
    "Нижний Новгород": "Нижнем Новгороде",
    "Ростов-на-Дону": "Ростове-на-Дону",
    "Санкт-Петербург": "Санкт-Петербурге",
    "Йошкар-Ола": "Йошкар-Оле",
    "Набережные Челны": "Набережных Челнах",
    "Великий Новгород": "Великом Новгороде",
    "Великие Луки": "Великих Луках",
    "Старый Оскол": "Старом Осколе",
    "Комсомольск-на-Амуре": "Комсомольске-на-Амуре",
    "Каменск-Уральский": "Каменске-Уральском",
    "Петропавловск-Камчатский": "Петропавловске-Камчатском",
    "Орехово-Зуево": "Орехово-Зуеве",
    "Сочи": "Сочи",
    "Ярославль": "Ярославле",
    "Грозный": "Грозном",
    "Орёл": "Орле",
    "Орел": "Орле",
}


def prepositional(city: str) -> str:
    """Город в предложном падеже ("в Казани", "в Волгограде") — для заголовков/описаний.
    Точный для override-списка, эвристика для остальных (не покрывает все исключения)."""
    if city in PREPOSITIONAL_OVERRIDES:
        return PREPOSITIONAL_OVERRIDES[city]
    if city.endswith("ь"):
        return city[:-1] + "и"
    if city.endswith(("а", "я")):
        return city[:-1] + "е"
    if city.endswith("о"):
        return city[:-1] + "е"
    if city.endswith("ый"):
        return city[:-2] + "ом"
    return city + "е"


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
        if path == "/admin":
            return self.send_admin()
        return super().do_GET()

    def check_admin_auth(self) -> bool:
        if not ADMIN_PASSWORD:
            self.send_html(
                "<h1>Админ-панель не настроена</h1>"
                "<p>Задайте переменную окружения ADMIN_PASSWORD на Railway.</p>",
                503,
            )
            return False
        auth = self.headers.get("Authorization", "")
        ok = False
        if auth.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                ok = user == ADMIN_USER and pwd == ADMIN_PASSWORD
            except Exception:
                ok = False
        if not ok:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Kub Admin"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

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
        city_prep = prepositional(city)
        title = f"Аренда склада в {city_prep} — мини-склады и self-storage | Куб"
        if min_price:
            price_str = f"{min_price:,}".replace(",", " ")
            description = (
                f"{len(storages)} складов и боксов для хранения в {city_prep}: цены от "
                f"{price_str} ₽/мес. Сравните варианты и оставьте заявку на Кубе."
            )
        else:
            description = f"{len(storages)} складов и боксов для хранения в {city_prep}. Сравните варианты на Кубе."

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

    # ---------- админ-панель ----------
    def send_admin(self):
        if not self.check_admin_auth():
            return
        qs = parse_qs(urlparse(self.path).query)
        city = (qs.get("city") or [""])[0]
        category = (qs.get("category") or [""])[0]
        sort = (qs.get("sort") or ["price"])[0]
        try:
            summary = fetch_admin_summary()
            storages = fetch_admin_storages(city or None, category or None, sort)
            bookings = fetch_bookings()
        except Exception as e:
            return self.send_html(f"<h1>Ошибка базы данных</h1><p>{html.escape(str(e))}</p>", 500)
        self.send_html(render_admin_page(summary, storages, bookings, city, category, sort))

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


def fetch_admin_summary():
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT city,
                   COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE category = 'self_storage') AS n_self,
                   MIN(price_from)::float AS min_price,
                   MAX(price_from)::float AS max_price
            FROM storages
            WHERE duplicate_of IS NULL
            GROUP BY city
            ORDER BY n DESC
            """
        )
        return cur.fetchall()


def fetch_admin_storages(city, category, sort):
    where = ["duplicate_of IS NULL"]
    params = {}
    if city:
        where.append("city = %(city)s")
        params["city"] = city
    if category:
        where.append("category = %(category)s")
        params["category"] = category
    order = "name" if sort == "name" else "price_from ASC NULLS LAST, name"
    query = (
        "SELECT id, source, category, city, name, address, "
        "price_from::float AS price_from, box_sizes, phone "
        "FROM storages WHERE " + " AND ".join(where) + f" ORDER BY {order} LIMIT 500"
    )
    with get_cursor(commit=False) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_bookings(limit=100):
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT b.id, b.created_at, b.client_phone, b.date_from, b.months,
                   b.service_fee::float AS service_fee, b.status,
                   s.name AS storage_name, s.city AS storage_city
            FROM bookings b
            JOIN storages s ON s.id = b.storage_id
            ORDER BY b.created_at DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        return cur.fetchall()


def render_admin_page(summary, storages, bookings, city, category, sort) -> str:
    total = sum(r["n"] for r in summary)
    summary_rows = "".join(
        f"<tr><td>{html.escape(r['city'])}</td><td>{r['n']}</td><td>{r['n_self']}</td>"
        f"<td>{int(r['min_price']) if r['min_price'] is not None else '—'}</td>"
        f"<td>{int(r['max_price']) if r['max_price'] is not None else '—'}</td></tr>"
        for r in summary
    )

    city_options = "".join(
        f'<option value="{html.escape(r["city"])}"{" selected" if r["city"] == city else ""}>{html.escape(r["city"])}</option>'
        for r in summary
    )
    cat_options = "".join(
        f'<option value="{k}"{" selected" if k == category else ""}>{v}</option>'
        for k, v in _CATEGORY_LABELS.items()
    )

    storage_rows = "".join(
        "<tr>"
        f"<td>{s['id']}</td>"
        f"<td>{_SOURCE_LABELS.get(s['source'], s['source'])}</td>"
        f"<td>{_CATEGORY_LABELS.get(s['category'], s['category'] or '—')}</td>"
        f"<td>{html.escape(s['city'] or '')}</td>"
        f"<td>{html.escape(s['name'] or '—')}</td>"
        f"<td>{html.escape(s['address'] or '—')}</td>"
        f"<td>{int(s['price_from']) if s['price_from'] is not None else '—'}</td>"
        f"<td>{html.escape(s['box_sizes'] or '—')}</td>"
        f"<td>{html.escape(s['phone'] or '—')}</td>"
        "</tr>"
        for s in storages
    )

    status_labels = {"new": "новая", "confirmed": "подтверждена", "cancelled": "отменена"}
    booking_rows = "".join(
        "<tr>"
        f"<td>{b['id']}</td>"
        f"<td>{html.escape(str(b['created_at']))}</td>"
        f"<td>{html.escape(b['storage_name'] or '—')} ({html.escape(b['storage_city'] or '')})</td>"
        f"<td>{html.escape(b['client_phone'])}</td>"
        f"<td>{html.escape(str(b['date_from']) if b['date_from'] else '—')}</td>"
        f"<td>{b['months']}</td>"
        f"<td>{int(b['service_fee']) if b['service_fee'] is not None else '—'}</td>"
        f"<td>{html.escape(status_labels.get(b['status'], b['status']))}</td>"
        "</tr>"
        for b in bookings
    )

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Куб — админ-панель</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
    background: #f6f5f2; color: #1c1b19; }}
  h1 {{ margin: 0 0 4px; }}
  h2 {{ margin: 32px 0 10px; font-size: 18px; }}
  .muted {{ color: #726e65; font-size: 14px; margin-bottom: 20px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #e4e1da; text-align: left; font-size: 13px; }}
  th {{ background: #fbe9df; color: #a5451f; position: sticky; top: 0; }}
  tr:hover td {{ background: #fafaf8; }}
  form {{ margin: 10px 0 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  select, button {{ font: inherit; padding: 7px 10px; border-radius: 7px; border: 1px solid #e4e1da; }}
  button {{ background: #c65a2e; color: #fff; border: none; cursor: pointer; }}
  .scroll {{ max-height: 70vh; overflow: auto; border: 1px solid #e4e1da; border-radius: 8px; }}
</style></head>
<body>
  <h1>Куб — админ-панель</h1>
  <div class="muted">Всего складов: {total} · заявок: {len(bookings)}</div>

  <h2>Сводка по городам</h2>
  <table>
    <tr><th>Город</th><th>Всего</th><th>self_storage</th><th>Мин. цена</th><th>Макс. цена</th></tr>
    {summary_rows}
  </table>

  <h2>Склады</h2>
  <form method="get" action="/admin">
    <select name="city"><option value="">Все города</option>{city_options}</select>
    <select name="category"><option value="">Все категории</option>{cat_options}</select>
    <select name="sort">
      <option value="price"{" selected" if sort == "price" else ""}>По цене</option>
      <option value="name"{" selected" if sort == "name" else ""}>По названию</option>
    </select>
    <button type="submit">Применить</button>
    <a href="/admin" style="margin-left:6px">Сбросить</a>
  </form>
  <div class="scroll">
  <table>
    <tr><th>ID</th><th>Источник</th><th>Категория</th><th>Город</th><th>Название</th>
        <th>Адрес</th><th>Цена</th><th>Размер</th><th>Телефон</th></tr>
    {storage_rows}
  </table>
  </div>
  <div class="muted">Показаны первые 500 записей по текущему фильтру.</div>

  <h2>Заявки (последние {len(bookings)})</h2>
  <div class="scroll">
  <table>
    <tr><th>ID</th><th>Создана</th><th>Склад</th><th>Телефон клиента</th>
        <th>С даты</th><th>Срок, мес.</th><th>Сбор, ₽</th><th>Статус</th></tr>
    {booking_rows or '<tr><td colspan="8">Пока нет заявок</td></tr>'}
  </table>
  </div>
</body></html>"""


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
