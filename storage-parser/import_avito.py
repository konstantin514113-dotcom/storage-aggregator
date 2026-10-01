"""Импорт выгрузки Авито в storages (source='avito').

Avito не отдаёт официального API для массового сбора объявлений — выгрузка
собирается вручную/через браузер (см. README: "через Claude в Chrome") в CSV
по шаблону ниже и импортируется этим скриптом. Формат — см.
avito_import_template.csv в корне репозитория.

Колонки CSV (обязательные помечены *):
    city*        — город как в cities.csv (для сопоставления с 2ГИС-записями)
    region       — регион (если не указан — возьмётся пустым)
    category     — self_storage | warehouse_rental | logistics | wholesale |
                   industrial; по умолчанию self_storage (на Авито подавляющее
                   большинство объявлений "сдам бокс/склад" — это оно)
    url*         — ссылка на объявление (используется как основа source_id)
    name*        — заголовок объявления или название продавца
    address      — адрес, если указан в объявлении
    price        — цена, ₽/мес (число, без пробелов и "₽")
    phone        — телефон продавца, если собран (на Авито часто открыт,
                   в отличие от демо-ключа 2ГИС — см. README)
    box_sizes    — размер бокса/площадь свободным текстом, если есть
    lat, lon     — координаты, если известны (Avito обычно не даёт точных
                   координат в самом объявлении — можно оставить пустыми)

source_id — числовой id объявления, извлечённый из url (Avito URL оканчивается
на "_<id>"), либо md5(url), если извлечь не удалось.

Запуск:
    python import_avito.py avito_import.csv
    python import_avito.py avito_import.csv --dry-run
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import config
from db.connection import get_cursor

AVITO_ID_RE = re.compile(r"_(\d+)(?:[/?#]|$)")
DEFAULT_CATEGORY = "self_storage"
VALID_CATEGORIES = set(config.SEARCH_CATEGORIES)


def extract_source_id(url: str) -> str:
    match = AVITO_ID_RE.search(url)
    if match:
        return match.group(1)
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def parse_price(raw: str) -> float | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d.]", "", raw)
    return float(digits) if digits else None


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    errors = []
    parsed = []
    for i, row in enumerate(rows, start=2):  # +1 за заголовок, +1 за 1-индексацию
        city = (row.get("city") or "").strip()
        url = (row.get("url") or "").strip()
        name = (row.get("name") or "").strip()
        if not city or not url or not name:
            errors.append(f"строка {i}: нужны city, url, name (получено city={city!r}, url={url!r}, name={name!r})")
            continue
        category = (row.get("category") or DEFAULT_CATEGORY).strip()
        if category not in VALID_CATEGORIES:
            errors.append(f"строка {i}: неизвестная категория {category!r} (допустимо: {', '.join(VALID_CATEGORIES)})")
            continue
        parsed.append({
            "source_id": extract_source_id(url),
            "city": city,
            "region": (row.get("region") or "").strip(),
            "category": category,
            "name": name,
            "address": (row.get("address") or "").strip() or None,
            "price_from": parse_price(row.get("price", "")),
            "phone": (row.get("phone") or "").strip() or None,
            "box_sizes": (row.get("box_sizes") or "").strip() or None,
            "lat": float(row["lat"]) if row.get("lat") else None,
            "lon": float(row["lon"]) if row.get("lon") else None,
            "url": url,
        })

    if errors:
        print(f"Пропущено строк с ошибками: {len(errors)}", file=sys.stderr)
        for e in errors[:20]:
            print(f"  {e}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ...и ещё {len(errors) - 20}", file=sys.stderr)

    return parsed


def upsert_row(cur, row: dict) -> None:
    cur.execute(
        """
        INSERT INTO storages (source, source_id, category, city, region, name, address, lat, lon, phone, price_from, box_sizes, raw_json, updated_at)
        VALUES ('avito', %(source_id)s, %(category)s, %(city)s, %(region)s, %(name)s, %(address)s, %(lat)s, %(lon)s, %(phone)s, %(price_from)s, %(box_sizes)s, %(raw)s, now())
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            phone = EXCLUDED.phone,
            price_from = EXCLUDED.price_from,
            box_sizes = EXCLUDED.box_sizes,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        {**row, "raw": json.dumps({"url": row["url"]}, ensure_ascii=False)},
    )


def run(csv_path: Path, dry_run: bool):
    rows = load_rows(csv_path)
    print(f"Валидных строк: {len(rows)}")

    if dry_run:
        for row in rows[:10]:
            print(f"  [dry-run] {row['city']} / {row['category']} / {row['name']}")
        if len(rows) > 10:
            print(f"  ...и ещё {len(rows) - 10}")
        return

    with get_cursor() as cur:
        for row in rows:
            upsert_row(cur, row)
    print(f"Записано в storages (source=avito): {len(rows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="только проверить и показать строки, не писать в БД")
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"Файл не найден: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    run(args.csv_path, args.dry_run)
