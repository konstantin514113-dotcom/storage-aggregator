"""Подсчёт складов по городам — 1 запрос к 2ГИС на город (или 5, если --all-queries).

Нужен для планирования расхода демо-ключа (1000 запросов), см. README:
1. python count_cities.py --min-population 100000          # ~170 запросов
2. python count_cities.py --city Казань --all-queries       # тест 5 формулировок в одном городе

Пишет CSV output/city_counts.csv: city,region,population,query,count
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "storage-parser"))
import config
from pipeline import load_cities
from sources.dgis import DgisClient

PRIMARY_QUERY = config.SEARCH_QUERIES[0]


def run(min_population: int, only_cities: list[str] | None, all_queries: bool, csv_out: Path):
    cities = load_cities(min_population, only_cities)
    queries = config.SEARCH_QUERIES if all_queries else [PRIMARY_QUERY]
    print(f"Городов: {len(cities)}, запросов на город: {len(queries)} "
          f"(итого ~{len(cities) * len(queries)} запросов к 2ГИС)")

    client = DgisClient()
    rows = []
    try:
        for city in cities:
            for query in queries:
                count = client.count(city["lat"], city["lon"], query)
                rows.append({
                    "city": city["city"],
                    "region": city.get("region", ""),
                    "population": city["population"],
                    "query": query,
                    "count": count,
                })
                print(f"{city['city']} / '{query}': {count}")
    finally:
        client.close()

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "region", "population", "query", "count"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV записан: {csv_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-population", type=int, default=config.MIN_POPULATION)
    parser.add_argument("--city", action="append", dest="cities")
    parser.add_argument("--all-queries", action="store_true", help="прогнать все 5 формулировок (обычно вместе с --city)")
    parser.add_argument("--csv-out", type=Path, default=config.OUTPUT_DIR / "city_counts.csv")
    args = parser.parse_args()

    run(args.min_population, args.cities, args.all_queries, args.csv_out)
