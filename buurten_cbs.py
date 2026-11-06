"""Buurtnaam bij een coördinaat, via de open CBS-buurtgrenzen van PDOK.

Waarom: de buurtfilters in funda_zoek.py draaien op funda's `neighbourhood`.
Een bron als huispedia levert geen buurtnaam in de zoekresultaten, wel lat/lon.
Funda's buurtnamen zijn de CBS-buurtnamen; gemeten op 6 nov 2026 gaf
punt-in-polygoon op de CBS-buurten 2024 voor 51 van de 51 vergeleken
funda-woningen exact dezelfde naam als funda (bijv. "Leyenburg",
"Venen, Oorden en Raden", "Kom Loosduinen").

Bron: PDOK OGC API "CBS Wijken en Buurten" (open data, geen sleutel). Twee
verzoeken per gemeentelijst, en de grenzen veranderen maar eens per jaar, dus
ze horen in een cache. robots.txt van api.pdok.nl verbiedt alleen
`/bzk/locatieserver/*` (de adres-zoekdienst); daar komt deze module niet.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable
from urllib.parse import quote

PDOK_URL = ("https://api.pdok.nl/cbs/wijken-en-buurten-{jaar}/ogc/v1/collections/buurten/items"
            "?f=json&limit=1000&gemeentenaam={naam}")

STANDAARD_JAAR = 2024

# URL-slug (zoals huispedia hem gebruikt) -> CBS-gemeentenaam.
CBS_GEMEENTE = {
    "den-haag": "'s-Gravenhage",
    "leidschendam-voorburg": "Leidschendam-Voorburg",
    "rijswijk": "Rijswijk",
}


def buurten_url(gemeente: str, jaar: int = STANDAARD_JAAR) -> str:
    naam = CBS_GEMEENTE.get(gemeente, gemeente)
    return PDOK_URL.format(jaar=jaar, naam=quote(naam, safe=""))


def parse_buurten(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """Compacte buurtlijst: naam, gemeente, bbox en ringen (lon, lat)."""
    uit = []
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        xs = [p[0] for poly in polys for p in poly[0]]
        ys = [p[1] for poly in polys for p in poly[0]]
        if not xs:
            continue
        uit.append({
            "buurt": props.get("buurtnaam"),
            "gemeente": props.get("gemeentenaam"),
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "polygonen": [[[[round(x, 6), round(y, 6)] for x, y, *_ in ring] for ring in poly]
                          for poly in polys],
        })
    if geojson.get("numberReturned") and len(geojson.get("features") or []) >= 1000:
        raise ValueError("Meer dan 1000 buurten in één antwoord; pagineren nodig")
    return uit


def _in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    binnen = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            binnen = not binnen
        j = i
    return binnen


class BuurtBepaler:
    """`bepaler(lat, lon)` -> CBS-buurtnaam of None."""

    def __init__(self, buurten: list[dict[str, Any]]) -> None:
        self._buurten = buurten

    def __len__(self) -> int:
        return len(self._buurten)

    def __call__(self, lat: float | None, lon: float | None) -> str | None:
        if lat is None or lon is None:
            return None
        x, y = float(lon), float(lat)
        for b in self._buurten:
            x0, y0, x1, y1 = b["bbox"]
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            for poly in b["polygonen"]:
                if _in_ring(x, y, poly[0]) and not any(_in_ring(x, y, gat) for gat in poly[1:]):
                    return b["buurt"]
        return None


def laad_bepaler(
    gemeenten: Iterable[str],
    haal: Callable[[str], str],
    *,
    jaar: int = STANDAARD_JAAR,
) -> BuurtBepaler:
    """Haal de buurtgrenzen op (één verzoek per gemeente) en bouw een bepaler.

    `haal(url) -> tekst` is de HTTP-functie van de aanroeper, zodat cache,
    pauzes en het verzoekbudget op één plek blijven.
    """
    buurten: list[dict[str, Any]] = []
    for gemeente in gemeenten:
        buurten.extend(parse_buurten(json.loads(haal(buurten_url(gemeente, jaar)))))
    return BuurtBepaler(buurten)
