"""Клиент 2ГИС Places API (Каталог 3.0).

Документация: https://docs.2gis.com/ru/api/search/places/overview
Эндпоинт: GET https://catalog.api.2gis.com/3.0/items

ВНИМАНИЕ: код не проверен против живого API (в этой сессии нет DGIS_API_KEY и нет
доступа к catalog.api.2gis.com из песочницы). Перед боевым прогоном свериться с
актуальной документацией и прогнать count_cities.py на 1-2 городах — особенно поля
`result.total` для подсчёта и лимиты page/page_size.
"""
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

BASE_URL = "https://catalog.api.2gis.com/3.0/items"
MAX_PAGE_SIZE = 50
MAX_PAGES = 20  # защита от случайного выжигания лимита демо-ключа


@dataclass
class DgisItem:
    source_id: str
    name: str
    address: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    rubrics: str
    phone: Optional[str]
    site: Optional[str]
    raw: dict = field(repr=False, default_factory=dict)


class DgisError(RuntimeError):
    pass


class DgisClient:
    def __init__(self, api_key: str = None, delay_s: float = None):
        self.api_key = api_key or config.DGIS_API_KEY
        self.delay_s = config.DGIS_REQUEST_DELAY_S if delay_s is None else delay_s
        if not self.api_key:
            raise DgisError("DGIS_API_KEY не задан")
        self._client = httpx.Client(timeout=20.0)

    def close(self):
        self._client.close()

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        retry=retry_if_exception_type((httpx.TransportError, DgisError)),
    )
    def _get(self, params: dict) -> dict:
        params = {**params, "key": self.api_key}
        resp = self._client.get(BASE_URL, params=params)
        if resp.status_code == 429:
            raise DgisError("2GIS API: 429 rate limited")
        resp.raise_for_status()
        data = resp.json()
        code = data.get("meta", {}).get("code", 200)
        if code != 200:
            raise DgisError(f"2GIS API error: {data.get('meta')}")
        time.sleep(self.delay_s)
        return data

    def count(self, lat: float, lon: float, query: str, radius_m: int = None) -> int:
        """Один запрос — количество результатов (для count_cities.py)."""
        params = {
            "q": query,
            "point": f"{lon},{lat}",
            "radius": radius_m or config.DGIS_RADIUS_M,
            "page_size": 1,
        }
        data = self._get(params)
        result = data.get("result", {})
        total = result.get("total")
        if total is not None:
            return int(total)
        # fallback, если API в этой версии не отдаёт total: считаем по факту наличия items
        return len(result.get("items", []))

    def search(self, lat: float, lon: float, query: str, radius_m: int = None) -> Iterator[DgisItem]:
        """Постраничный обход результатов поиска."""
        page = 1
        while page <= MAX_PAGES:
            params = {
                "q": query,
                "point": f"{lon},{lat}",
                "radius": radius_m or config.DGIS_RADIUS_M,
                "page": page,
                "page_size": MAX_PAGE_SIZE,
                "fields": "items.point,items.address,items.contact_groups,items.rubrics",
            }
            data = self._get(params)
            items = data.get("result", {}).get("items", [])
            if not items:
                return
            for raw in items:
                yield _parse_item(raw)
            if len(items) < MAX_PAGE_SIZE:
                return
            page += 1


def _parse_item(raw: dict) -> DgisItem:
    point = raw.get("point") or {}
    contact_groups = raw.get("contact_groups") or []
    phone = None
    site = None
    for group in contact_groups:
        for contact in group.get("contacts", []):
            if contact.get("type") == "phone" and not phone:
                phone = contact.get("value") or contact.get("text")
            if contact.get("type") == "website" and not site:
                site = contact.get("value") or contact.get("text")
    rubrics = ", ".join(r.get("name", "") for r in raw.get("rubrics", []) if r.get("name"))
    return DgisItem(
        source_id=str(raw.get("id")),
        name=raw.get("name", ""),
        address=raw.get("address_name") or (raw.get("address") or {}).get("name"),
        lat=point.get("lat"),
        lon=point.get("lon"),
        rubrics=rubrics,
        phone=phone,
        site=site,
        raw=raw,
    )
