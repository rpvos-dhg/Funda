"""Eenmalige verkenning van funda.nl's publieke zoekpagina.

Doel: vaststellen welke URL-filters werken (straal, prijs, oppervlakte,
woningtype, sortering, paginering) en hoe de HTML eruitziet, zodat de
HTML-fallback in `funda_html_zoek.py` op echte structuur gebouwd kan worden in
plaats van op aannames.

Draait via de workflow "Funda HTML verkenning" en bewaart de opgehaalde HTML in
`html_dump/` zodat die als artifact te downloaden is.

Bevat geen persoonlijke gegevens: alle zoekopdrachten gebruiken Den Haag en een
vaste voorbeeld-postcode.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as curl_requests

BASIS = "https://www.funda.nl/zoeken/koop"
DUMP_DIR = Path("html_dump")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def bouw_url(**params: str) -> str:
    delen = [f"{k}={quote(v, safe='')}" for k, v in params.items()]
    return f"{BASIS}?{'&'.join(delen)}"


def haal(url: str) -> tuple[int, str]:
    resp = curl_requests.get(
        url,
        headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
        impersonate="safari15_5",
        timeout=30,
    )
    return resp.status_code, (resp.text or "")


def tel_resultaten(html: str) -> dict[str, object]:
    """Haal de signalen uit de HTML die zeggen hoeveel treffers er zijn."""
    # Funda toont ergens een totaal ("123 koopwoningen"/"resultaten").
    totaal = None
    for patroon in (
        r"([\d.]+)\s*(?:koop)?woningen\b",
        r"([\d.]+)\s*resultaten\b",
        r'"totalCount"\s*:\s*(\d+)',
        r'"total"\s*:\s*(\d+)',
    ):
        m = re.search(patroon, html, re.IGNORECASE)
        if m:
            totaal = m.group(1)
            break

    # Unieke detail-links: dit worden straks de woningen.
    links = set(re.findall(r'href="(/detail/koop/[^"]+)"', html))
    if not links:
        links = set(re.findall(r'href="(https://www\.funda\.nl/detail/koop/[^"]+)"', html))
    return {
        "totaal_tekst": totaal,
        "unieke_detail_links": len(links),
        "voorbeeld_link": sorted(links)[0] if links else None,
        "bot_muur": "Je bent bijna op de pagina" in html,
        "lengte": len(html),
    }


VARIANTEN: list[tuple[str, dict[str, str]]] = [
    ("A stad kaal", {"selected_area": '["den-haag"]'}),
    ("B stad + straal 5km", {"selected_area": '["den-haag,5km"]'}),
    ("C postcode + straal 5km", {"selected_area": '["2596ec,5km"]'}),
    ("D postcode kaal", {"selected_area": '["2596ec"]'}),
    (
        "E stad + prijs",
        {"selected_area": '["den-haag"]', "price": "230000-310000"},
    ),
    (
        "F stad + prijs + appartement",
        {
            "selected_area": '["den-haag"]',
            "price": "230000-310000",
            "object_type": '["apartment"]',
        },
    ),
    (
        "G volledige filterset",
        {
            "selected_area": '["den-haag,5km"]',
            "price": "230000-310000",
            "object_type": '["apartment"]',
            "floor_area": "52-",
            "availability": '["available"]',
        },
    ),
    (
        "H volledige set + sorteer oudste",
        {
            "selected_area": '["den-haag,5km"]',
            "price": "230000-310000",
            "object_type": '["apartment"]',
            "floor_area": "52-",
            "availability": '["available"]',
            "sort": "date_up",
        },
    ),
    (
        "I volledige set + pagina 2",
        {
            "selected_area": '["den-haag,5km"]',
            "price": "230000-310000",
            "object_type": '["apartment"]',
            "floor_area": "52-",
            "availability": '["available"]',
            "search_result": "2",
        },
    ),
]


def main() -> int:
    DUMP_DIR.mkdir(exist_ok=True)
    print("Funda HTML-verkenning\n")

    for naam, params in VARIANTEN:
        url = bouw_url(**params)
        try:
            status, html = haal(url)
        except Exception as exc:
            print(f"{naam}: EXCEPTIE {type(exc).__name__}: {exc}")
            continue
        info = tel_resultaten(html)
        print(f"{naam}")
        print(f"  url: {url}")
        print(f"  status: {status}  {info}")

        veilig = re.sub(r"[^a-z0-9]+", "_", naam.lower()).strip("_")
        (DUMP_DIR / f"{veilig}.html").write_text(html, encoding="utf-8")

    print("\nHTML weggeschreven naar html_dump/ (zie artifact).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
