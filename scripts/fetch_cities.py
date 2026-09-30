"""Сборка cities.csv из открытых данных GeoNames.

Скачивает RU.zip (населённые пункты России, CC BY 4.0, https://www.geonames.org/export/)
и формирует cities.csv с колонками city,region,population,lat,lon — отбирая записи
с feature_code из ADMIN_FEATURE_CODES (административные центры / города) и населением
не ниже --min-population.

Требует доступ в интернет к download.geonames.org — не работает из песочницы
Claude Code с ограниченной сетевой политикой (см. README); запускать локально или
через `railway run python scripts/fetch_cities.py`.

Итоговое число строк ориентировочно близко к 1117 «городам» Росстата, но не гарантированно
совпадает — GeoNames не хранит российский юридический статус "город" напрямую, только
feature_code геообъекта.

ВАЖНО про названия: поле "name" в GeoNames для многих российских населённых
пунктов — это английский экзоним или транслитерация (например "Moscow", а не
"Москва"), не гарантированно кириллица. Была попытка чинить это эвристикой
"первое кириллическое имя из alternatenames", но alternatenames там не помечены
языком — эвристика хватала названия на осетинском/чувашском/марийском/якутском
и советские исторические имена (Москва → "Мæскуы", Пермь → "Молотов",
Набережные Челны → "Брежнев"), то есть правдоподобно выглядящие, но фактически
неверные. Хуже, чем английское название. Поэтому здесь просто row["name"] как
есть — годится как ключ для city_name_overrides.csv (geonameid,city), который
можно дополнять вручную для городов, где это важно (в первую очередь — крупные,
из MIN_POPULATION-выборки).
"""
import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path

import httpx

GEONAMES_RU_URL = "https://download.geonames.org/export/dump/RU.zip"
ADMIN1_CODES_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
OVERRIDES_PATH = Path(__file__).resolve().parent / "city_name_overrides.csv"

# см. https://www.geonames.org/export/codes.html
# Намеренно БЕЗ голого "PPL" — это код для любого населённого пункта, включая
# деревни; с ним выборка вместо городов утаскивает сотни тысяч мелких сёл.
# Оставлены только коды, отмечающие населённый пункт как административный
# центр того или иного уровня — приближение к "городам" без легальной точности
# (см. docstring модуля).
ADMIN_FEATURE_CODES = {"PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLG"}

GEONAMES_COLUMNS = [
    "geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
    "feature_class", "feature_code", "country_code", "cc2", "admin1_code",
    "admin2_code", "admin3_code", "admin4_code", "population", "elevation",
    "dem", "timezone", "modification_date",
]


def fetch_admin1_names() -> dict[str, str]:
    resp = httpx.get(ADMIN1_CODES_URL, timeout=30.0)
    resp.raise_for_status()
    names = {}
    for line in resp.text.splitlines():
        code, name, *_ = line.split("\t")
        names[code] = name
    return names


def load_overrides() -> dict[str, str]:
    """geonameid -> правильное русское название. См. docstring модуля."""
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open(encoding="utf-8") as f:
        return {row["geonameid"]: row["city"] for row in csv.DictReader(f)}


def fetch_geonames_ru() -> list[dict]:
    resp = httpx.get(GEONAMES_RU_URL, timeout=60.0)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        raw = zf.read("RU.txt").decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw), fieldnames=GEONAMES_COLUMNS, delimiter="\t")
    return list(reader)


def build_cities_csv(min_population: int, out_path: Path):
    admin1_names = fetch_admin1_names()
    overrides = load_overrides()
    rows = fetch_geonames_ru()

    seen_names = set()
    cities = []
    for row in rows:
        if row["feature_code"] not in ADMIN_FEATURE_CODES:
            continue
        population = int(row["population"] or 0)
        if population < min_population:
            continue
        name = overrides.get(row["geonameid"], row["name"])
        if name in seen_names:
            continue
        seen_names.add(name)
        admin1_code = f"RU.{row['admin1_code']}"
        cities.append({
            "city": name,
            "region": admin1_names.get(admin1_code, ""),
            "population": population,
            "lat": row["latitude"],
            "lon": row["longitude"],
        })

    cities.sort(key=lambda c: -c["population"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "region", "population", "lat", "lon"])
        writer.writeheader()
        writer.writerows(cities)

    print(f"Записано {len(cities)} городов в {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-population", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "cities.csv")
    args = parser.parse_args()

    try:
        build_cities_csv(args.min_population, args.out)
    except httpx.HTTPError as exc:
        print(f"Не удалось скачать данные GeoNames: {exc}", file=sys.stderr)
        print("Запустите скрипт там, где есть доступ к download.geonames.org", file=sys.stderr)
        sys.exit(1)
