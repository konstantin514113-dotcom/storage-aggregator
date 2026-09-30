"""Склейка дублей между источниками (2ГИС / Avito / сайты операторов).

Правило: два storages-объекта считаются дублями, если расстояние между их
координатами меньше DEDUPE_RADIUS_M и похожесть названий (SequenceMatcher)
не ниже DEDUPE_NAME_SIMILARITY. При совпадении более ранняя запись (меньший id)
остаётся "главной", у остальных проставляется duplicate_of.

Запуск: python dedupe.py [--city Казань]
"""
import argparse
import sys
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from db.connection import get_cursor

DEDUPE_RADIUS_M = 60
DEDUPE_NAME_SIMILARITY = 0.55


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * r * asin(sqrt(a))


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def dedupe_city(city: str):
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT id, name, lat, lon FROM storages
            WHERE city = %(city)s AND duplicate_of IS NULL
              AND lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY id
            """,
            {"city": city},
        )
        rows = cur.fetchall()

    merges = []
    for i, a in enumerate(rows):
        if any(a["id"] == dup_id for _, dup_id in merges):
            continue
        for b in rows[i + 1 :]:
            if any(b["id"] == dup_id for _, dup_id in merges):
                continue
            dist = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if dist <= DEDUPE_RADIUS_M and name_similarity(a["name"], b["name"]) >= DEDUPE_NAME_SIMILARITY:
                merges.append((a["id"], b["id"]))

    if not merges:
        return 0

    with get_cursor() as cur:
        for master_id, dup_id in merges:
            cur.execute(
                "UPDATE storages SET duplicate_of = %(master)s, updated_at = now() WHERE id = %(dup)s",
                {"master": master_id, "dup": dup_id},
            )
    return len(merges)


def dedupe_all():
    with get_cursor(commit=False) as cur:
        cur.execute("SELECT DISTINCT city FROM storages WHERE duplicate_of IS NULL")
        cities = [row["city"] for row in cur.fetchall()]

    total = 0
    for city in cities:
        n = dedupe_city(city)
        total += n
        if n:
            print(f"{city}: склеено {n} дублей")
    print(f"Итого склеено дублей: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city")
    args = parser.parse_args()

    if args.city:
        n = dedupe_city(args.city)
        print(f"{args.city}: склеено {n} дублей")
    else:
        dedupe_all()
