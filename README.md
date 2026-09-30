# storage-aggregator (Куб)

Агрегатор мини-складов (self storage) по России. Модель — как Booking: клиент ищет и
бронирует бокс, площадка берёт комиссию ~6000 ₽ с брони со склада. Фокус — мини-склады
для частных лиц, в первую очередь регионы (не Москва).

## Структура репозитория

```
storage-aggregator/
├── cities.csv                  # пример списка городов (см. "Список городов" ниже)
├── count_cities.py             # подсчёт складов по городам, 1 запрос 2ГИС на город
├── kubometr.html                # прототип сайта (поиск/фильтры/карточки/бронь/калькулятор), тестовые данные
├── scripts/
│   └── fetch_cities.py         # сборка полного cities.csv из GeoNames (нужен доступ в интернет)
└── storage-parser/
    ├── config.py                # чтение .env / переменных окружения
    ├── requirements.txt
    ├── db/
    │   ├── schema.sql           # таблицы storages, operator_sites
    │   └── connection.py        # подключение к Postgres, применение схемы
    ├── sources/
    │   ├── dgis.py              # клиент 2ГИС Places API (Каталог 3.0)
    │   └── yandex.py            # заглушка — пока не используется
    ├── crawler/
    │   └── site_crawler.py      # обход сайта оператора + извлечение данных через Claude API
    ├── dedupe.py                # склейка дублей (по гео + похожести названия)
    └── pipeline.py               # основной конвейер: cities.csv → 2ГИС → Postgres/CSV
```

## Переменные окружения

Скопируйте `.env.example` в `.env` (или задайте в Railway → Variables):

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | строка подключения к Postgres (в Railway — `${{Postgres.DATABASE_URL}}`) |
| `DGIS_API_KEY` | ключ 2ГИС Places API (демо-ключ — 1000 запросов) |
| `ANTHROPIC_API_KEY` | ключ Claude API для краулера сайтов операторов |
| `MIN_POPULATION` | порог населения города для выборки из `cities.csv` (по умолчанию `100000`) |
| `DGIS_RADIUS_M` | радиус поиска вокруг центра города, метры (по умолчанию `15000`) |

## Список городов

`cities.csv` в репозитории — это **проверочный пример** (около 15 крупных региональных
городов), не полный список из 1117 городов России. Полный список набирать вручную по
памяти недостоверно (населённость и координаты меняются, ошибка легко закрадывается),
поэтому он собирается скриптом из открытых данных:

```bash
python scripts/fetch_cities.py --min-population 0 --out cities.csv
```

Скрипт скачивает `RU.zip` с GeoNames (`download.geonames.org`, CC BY 4.0) и формирует
`cities.csv` с колонками `city,region,population,lat,lon`. Запускать там, где есть
доступ в интернет (локально или через `railway run`) — в текущей облачной сессии
Claude Code сетевая политика окружения блокирует внешние хосты кроме GitHub/PyPI/npm.
Итоговое число строк может немного отличаться от официальных 1117 «городов» Росстата —
GeoNames классифицирует населённые пункты иначе, чем российское законодательство.

## План на демо-ключ 2ГИС (1000 запросов)

1. `python count_cities.py --min-population 100000` — по городам от 100 тыс. (~170 запросов).
2. `python count_cities.py --city Казань --all-queries` — тест всех 5 поисковых формулировок
   в одном городе (~30 запросов с пагинацией), выбрать 2 лучшие по `storage-parser/config.py::SEARCH_QUERIES`.
3. `python storage-parser/pipeline.py --min-population <порог по итогам шага 1>` — выгрузка
   по отобранным городам (~700 запросов, резерв ~100).

## Запуск локально

```bash
cd storage-parser
pip install -r requirements.txt
python db/connection.py           # применить schema.sql к Postgres
python ../count_cities.py --min-population 100000
python pipeline.py --min-population 100000
```

## Деплой на Railway

Сервис подключён к проекту `storage-aggregator` (Postgres уже развёрнут там же).
`railway.json` в корне поднимает `server.py` — отдаёт `kubometr.html` как статический
прототип на сгенерированном Railway-домене. Скрипты `storage-parser/*.py` запускаются
разово через `railway run python storage-parser/pipeline.py ...` или Railway Cron —
это batch-джобы, не веб-сервер.

Переменные сервиса: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `DGIS_API_KEY`,
`ANTHROPIC_API_KEY`.

## Дальше по плану

- Импорт выгрузки Авито (собирается вручную через Claude в Chrome) как источник `avito`
  в `storages.source` — см. `storage-parser/dedupe.py` для склейки дублей с 2ГИС/сайтами.
- Перенос `kubometr.html` на реальные данные из Postgres (сейчас в разметке — тестовые
  карточки).
