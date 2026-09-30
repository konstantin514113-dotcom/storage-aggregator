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

# Поисковые формулировки для 2ГИС (рубрика "склады"/"хранение" не всегда размечена
# единообразно по городам, поэтому ищем текстом; после теста в Казани — см. README —
# оставить 2 лучшие и передавать их через --queries).
SEARCH_QUERIES = [
    "мини-склад",
    "склад для хранения вещей",
    "хранение вещей",
    "самостоятельное хранение",
    "склад временного хранения",
]

# Ключевые слова для грубой пост-фильтрации результатов 2ГИС (отсеять случайные
# совпадения вроде стройматериалов/логистических терминалов)
TITLE_INCLUDE_KEYWORDS = [
    "склад",
    "storage",
    "хранени",
    "бокс",
]
TITLE_EXCLUDE_KEYWORDS = [
    "стройматериал",
    "металлопрокат",
    "оптов",
    "логистическ",
    "таможен",
]
