"""Конфигурация storage-parser: переменные окружения + общие константы."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DGIS_API_KEY = os.environ.get("DGIS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

MIN_POPULATION = int(os.environ.get("MIN_POPULATION", "100000"))
DGIS_RADIUS_M = int(os.environ.get("DGIS_RADIUS_M", "15000"))
DGIS_REQUEST_DELAY_S = float(os.environ.get("DGIS_REQUEST_DELAY_S", "0.3"))

CITIES_CSV = ROOT / "cities.csv"
OUTPUT_DIR = ROOT / "output"

# Охват — все виды складов по России, с делением на категории (storages.category).
# Категория определяется тем, по какой формулировке найдена запись в 2ГИС; одна и та
# же организация может попасться по нескольким запросам — при upsert категория не
# перетирается повторно (см. pipeline.py). Рубрика "склады" в 2ГИС размечена не везде
# единообразно, поэтому ищем текстом, а не по rubric_id.
SEARCH_CATEGORIES = {
    "self_storage": [
        "мини-склад",
        "индивидуальное хранение",
        "хранение вещей",
        "бокс-склад",
        "склад временного хранения",
    ],
    "warehouse_rental": [
        "склад в аренду",
        "аренда складского помещения",
        "складское помещение",
    ],
    "logistics": [
        "логистический склад",
        "склад ответственного хранения",
        "распределительный склад",
    ],
    "wholesale": [
        "оптовый склад",
        "торговая база",
    ],
    "industrial": [
        "промышленный склад",
        "производственный склад",
    ],
}

# Общая формулировка для первого прохода count_cities.py (1 запрос на город, чтобы
# оценить порядок величины до того, как тратить лимит на все категории/формулировки).
PRIMARY_QUERY = "склад"

# Ключевые слова для грубой пост-фильтрации результатов 2ГИС (отсеять явно
# нерелевантные совпадения — не сами оптовые/логистические/промышленные склады,
# они теперь отдельные категории, а смежный бизнес вроде розницы стройматериалов).
TITLE_EXCLUDE_KEYWORDS = [
    "магазин стройматериал",
    "металлопрокат",
]
