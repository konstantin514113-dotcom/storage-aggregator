"""Служебный скрипт: собрать cities.csv через fetch_cities.py и построчно
вывести в stdout (для прогона на Railway, где есть доступ к GeoNames, но нет
способа скачать получившийся файл обратно иначе как через логи деплоя).

Использование: python scripts/dump_cities_to_log.py [min_population]
(по умолчанию 0 — без порога)

Не часть обычного пайплайна — разовый инструмент.
"""
import subprocess
import sys
from pathlib import Path

OUT = Path("/tmp/cities_full.csv")
min_population = sys.argv[1] if len(sys.argv) > 1 else "0"

subprocess.run(
    [sys.executable, "scripts/fetch_cities.py", "--min-population", min_population, "--out", str(OUT)],
    check=True,
)

print("=== CITIES_CSV_BEGIN ===")
with OUT.open(encoding="utf-8") as f:
    for line in f:
        print(line.rstrip("\n"))
print("=== CITIES_CSV_END ===")
