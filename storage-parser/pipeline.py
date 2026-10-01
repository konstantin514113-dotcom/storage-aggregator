"""Основной конвейер: cities.csv → 2ГИС Places API → Postgres (storages) + CSV.

Ищем все виды складов (self_storage, warehouse_rental, logistics, wholesale,
industrial — см. config.SEARCH_CATEGORIES), категория пишется в storages.category.

Запуск:
    python pipeline.py --min-population 100000
    python pipeline.py --city Казань --city Новосибирск --categories self_storage warehouse_rental
    python pipeline.py --min-population 100000 --csv-out output/storages.csv --dry-run
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import config
from db.connection import get_cursor
from sources.dgis import DgisClient


def load_cities(min_population: int, only_cities: list[str] | None) -> list[dict]:
    if not config.CITIES_CSV.exists():
        raise FileNotFoundError(
            f"{config.CITIES_CSV} не найден. См. README: scripts/fetch_cities.py"
        )
    with config.CITIES_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    cities = []
    for row in rows:
        try:
            population = int(row["population"])
            lat, lon = float(row["lat"]), float(row["lon"])
        except (KeyError, ValueError):
            continue
        if only_cities and row["city"] not in only_cities:
            continue
        if not only_cities and population < min_population:
            continue
        cities.append({**row, "population": population, "lat": lat, "lon": lon})
    return cities


def is_relevant(name: str) -> bool:
    # 2ГИС уже фильтрует текстовым поиском по запросу; здесь только отсекаем
    # явный мусор вроде стройматериалов/логистических терминалов (TITLE_EXCLUDE_KEYWORDS).
    lname = (name or "").lower()
    return not any(kw in lname for kw in config.TITLE_EXCLUDE_KEYWORDS)


def resolve_category(query_category: str, rubrics: str) -> str:
    # Рубрика 2ГИС — более точный сигнал, чем то, каким текстовым запросом
    # объект был найден (см. config.RUBRIC_CATEGORY_OVERRIDES).
    for substr, override in config.RUBRIC_CATEGORY_OVERRIDES.items():
        if substr in (rubrics or ""):
            return override
    return query_category


def upsert_storage(cur, city: str, region: str, category: str, item) -> None:
    # category намеренно не перетирается при повторном попадании по другому запросу —
    # остаётся первая категория, по которой запись была найдена.
    cur.execute(
        """
        INSERT INTO storages (source, source_id, category, city, region, name, address, lat, lon, phone, rubrics, raw_json, updated_at)
        VALUES ('dgis', %(source_id)s, %(category)s, %(city)s, %(region)s, %(name)s, %(address)s, %(lat)s, %(lon)s, %(phone)s, %(rubrics)s, %(raw)s, now())
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            phone = EXCLUDED.phone,
            rubrics = EXCLUDED.rubrics,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        {
            "source_id": item.source_id,
            "category": category,
            "city": city,
            "region": region,
            "name": item.name,
            "address": item.address,
            "lat": item.lat,
            "lon": item.lon,
            "phone": item.phone,
            "rubrics": item.rubrics,
            "raw": json.dumps(item.raw, ensure_ascii=False),
        },
    )
    if item.site:
        domain = item.site.split("//")[-1].split("/")[0]
        cur.execute(
            """
            INSERT INTO operator_sites (domain, city, status)
            VALUES (%(domain)s, %(city)s, 'pending')
            ON CONFLICT (domain) DO NOTHING
            """,
            {"domain": domain, "city": city},
        )


def run(min_population: int, only_cities: list[str] | None, categories: list[str], csv_out: Path | None, dry_run: bool):
    cities = load_cities(min_population, only_cities)
    print(f"Городов в выборке: {len(cities)}, категорий: {', '.join(categories)}")

    client = DgisClient()
    csv_rows = []
    total_found = 0
    try:
        for city in cities:
            for category in categories:
                for query in config.SEARCH_CATEGORIES[category]:
                    items = list(client.search(city["lat"], city["lon"], query))
                    items = [it for it in items if is_relevant(it.name)]
                    total_found += len(items)
                    print(f"{city['city']} / {category} / '{query}': {len(items)}")

                    if dry_run:
                        csv_rows.extend(
                            {
                                "city": city["city"], "region": city.get("region", ""),
                                "category": resolve_category(category, it.rubrics), "query": query, **vars(it),
                            }
                            for it in items
                        )
                        continue

                    with get_cursor() as cur:
                        for it in items:
                            resolved = resolve_category(category, it.rubrics)
                            upsert_storage(cur, city["city"], city.get("region", ""), resolved, it)
                            csv_rows.append({
                                "city": city["city"], "region": city.get("region", ""),
                                "category": resolved, "query": query, **vars(it),
                            })
    finally:
        client.close()

    print(f"Всего найдено (с учётом дублей между запросами): {total_found}")

    if csv_out:
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        with csv_out.open("w", encoding="utf-8", newline="") as f:
            fieldnames = ["city", "region", "category", "query", "source_id", "name", "address", "lat", "lon", "rubrics", "phone", "site"]
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"CSV записан: {csv_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-population", type=int, default=config.MIN_POPULATION)
    parser.add_argument("--city", action="append", dest="cities", help="ограничить конкретными городами (можно несколько раз)")
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=list(config.SEARCH_CATEGORIES),
        default=list(config.SEARCH_CATEGORIES),
        help="ограничить конкретными категориями складов",
    )
    parser.add_argument("--csv-out", type=Path, default=config.OUTPUT_DIR / "storages.csv")
    parser.add_argument("--dry-run", action="store_true", help="не писать в Postgres, только CSV")
    args = parser.parse_args()

    run(args.min_population, args.cities, args.categories, args.csv_out, args.dry_run)
