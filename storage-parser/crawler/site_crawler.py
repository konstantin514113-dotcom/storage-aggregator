"""Краулер сайтов операторов мини-складов.

Берёт домен (обычно из DgisItem.site), скачивает главную страницу и страницы
контактов/цен (по ключевым словам в ссылках), склеивает текст и просит Claude
вытащить структурированные данные: телефон, адреса боксов, цены, размеры.
Результат пишется в таблицу operator_sites.

Запуск: python crawler/site_crawler.py --domain example.ru
        python crawler/site_crawler.py --pending   # все operator_sites со status='pending'
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from anthropic import Anthropic
from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from db.connection import get_cursor

RELEVANT_LINK_KEYWORDS = ["контакт", "contact", "цен", "price", "тариф", "адрес", "склад", "box"]
MAX_PAGES_PER_SITE = 4
REQUEST_TIMEOUT = 15.0

EXTRACTION_PROMPT = """\
Ты обрабатываешь текст сайта оператора мини-складов (self storage) в России.
Извлеки структурированные данные и верни ТОЛЬКО валидный JSON без пояснений, по схеме:

{{
  "operator_name": string | null,
  "phone": string | null,
  "email": string | null,
  "addresses": [string],
  "price_from": number | null,       // минимальная цена в рублях в месяц
  "box_sizes": string | null,        // например "1–20 м³" свободным текстом
  "cities": [string]
}}

Если поле не найдено — null (или пустой список). Не выдумывай данные, которых нет в тексте.

Текст сайта ({domain}):
---
{text}
---
"""


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _relevant_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = (a.get_text() or "").lower()
        if any(kw in href.lower() or kw in label for kw in RELEVANT_LINK_KEYWORDS):
            full = urljoin(base_url, href)
            if urlparse(full).netloc == urlparse(base_url).netloc:
                links.add(full)
    return list(links)[: MAX_PAGES_PER_SITE - 1]


def crawl_domain(domain: str) -> dict:
    base_url = domain if domain.startswith("http") else f"https://{domain}"
    texts = []
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(base_url)
        resp.raise_for_status()
        texts.append(_extract_text(resp.text))
        for link in _relevant_links(resp.text, base_url):
            try:
                sub = client.get(link)
                sub.raise_for_status()
                texts.append(_extract_text(sub.text))
            except httpx.HTTPError:
                continue
    full_text = "\n\n".join(texts)[:15000]  # ограничение на размер промпта

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(domain=domain, text=full_text)}],
    )
    raw_text = message.content[0].text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw_text[start : end + 1])
        raise ValueError(f"Claude вернул не-JSON для {domain}: {raw_text[:200]}")


def save_result(domain: str, city: str | None, extracted: dict, status: str = "crawled"):
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO operator_sites (domain, operator_name, city, phone, email, status, raw_extracted, crawled_at)
            VALUES (%(domain)s, %(operator_name)s, %(city)s, %(phone)s, %(email)s, %(status)s, %(raw)s, now())
            ON CONFLICT (domain) DO UPDATE SET
                operator_name = EXCLUDED.operator_name,
                phone = COALESCE(EXCLUDED.phone, operator_sites.phone),
                email = COALESCE(EXCLUDED.email, operator_sites.email),
                status = EXCLUDED.status,
                raw_extracted = EXCLUDED.raw_extracted,
                crawled_at = now()
            """,
            {
                "domain": domain,
                "operator_name": extracted.get("operator_name"),
                "city": city,
                "phone": extracted.get("phone"),
                "email": extracted.get("email"),
                "status": status,
                "raw": json.dumps(extracted, ensure_ascii=False),
            },
        )


def crawl_and_save(domain: str, city: str | None = None):
    try:
        extracted = crawl_domain(domain)
        save_result(domain, city, extracted, status="crawled")
        print(f"[ok] {domain}: {extracted.get('operator_name')}")
    except Exception as exc:  # noqa: BLE001 — краулинг стороннего сайта, много непредвиденных ошибок
        save_result(domain, city, {}, status="failed")
        print(f"[fail] {domain}: {exc}")


def crawl_pending():
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT domain, city FROM operator_sites WHERE status = 'pending'")
        rows = cur.fetchall()
    for row in rows:
        crawl_and_save(row["domain"], row["city"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain")
    parser.add_argument("--pending", action="store_true")
    args = parser.parse_args()

    if args.domain:
        crawl_and_save(args.domain)
    elif args.pending:
        crawl_pending()
    else:
        parser.error("укажите --domain <домен> или --pending")
