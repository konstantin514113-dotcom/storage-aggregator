"""Служебный скрипт: собрать cities.csv через fetch_cities.py и построчно
вывести в stdout (для прогона на Railway, где есть доступ к GeoNames, но нет
способа скачать получившийся файл обратно иначе как через логи деплоя).

Не часть обычного пайплайна — разовый инструмент.
"""
import subprocess
import sys
from pathlib import Path

OUT = Path("/tmp/cities_full.csv")

subprocess.run(
    [sys.executable, "scripts/fetch_cities.py", "--min-population", "0", "--out", str(OUT)],
    check=True,
)

print("=== CITIES_CSV_BEGIN ===")
with OUT.open(encoding="utf-8") as f:
    for line in f:
        print(line.rstrip("\n"))
print("=== CITIES_CSV_END ===")
