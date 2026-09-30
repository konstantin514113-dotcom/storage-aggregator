"""Служебный скрипт: прогнать pipeline.py --dry-run для города и построчно
вывести итоговый CSV в stdout (для разового прогона на Railway, откуда файл
иначе не забрать — см. dump_cities_to_log.py с той же идеей).

Использование: python scripts/dry_run_pipeline_to_log.py <Город> [категории...]
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/pipeline_dry_run.csv")

if len(sys.argv) < 2:
    print("Использование: dry_run_pipeline_to_log.py <Город> [категории...]", file=sys.stderr)
    sys.exit(2)

city = sys.argv[1]
categories = sys.argv[2:]

cmd = [
    sys.executable, "storage-parser/pipeline.py",
    "--city", city,
    "--dry-run",
    "--csv-out", str(OUT),
]
if categories:
    cmd += ["--categories", *categories]

subprocess.run(cmd, check=True, cwd=ROOT)

print("=== PIPELINE_CSV_BEGIN ===")
with OUT.open(encoding="utf-8") as f:
    for line in f:
        print(line.rstrip("\n"))
print("=== PIPELINE_CSV_END ===")
