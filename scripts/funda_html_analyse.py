"""Analyseer de structuur van funda.nl's zoekresultaten.

Vervolg op funda_html_verkenning.py. Print een compacte structuurrapportage van
een zoekpagina, zodat de parser voor de HTML-fallback op echte markup gebouwd
kan worden zonder de hele pagina te hoeven downloaden.

Kijkt bewust eerst naar gestructureerde data (JSON-LD, embedded state): die is
veel minder breekbaar dan het scrapen van divs en classnames.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from curl_cffi import requests as curl_requests

BASIS = "https://www.funda.nl/zoeken/koop"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

PARAMS = {
    "selected_area": '["den-haag,5km"]',
    "price": "230000-310000",
    "object_type": '["apartment"]',
    "floor_area": "52-",
    "availability": '["available"]',
}


def haal(params: dict[str, str]) -> str:
    url = f"{BASIS}?{'&'.join(f'{k}={quote(v, safe=chr(39))}' for k, v in params.items())}"
    print(f"URL: {url}")
    resp = curl_requests.get(
        url,
        headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
        impersonate="safari15_5",
        timeout=30,
    )
    print(f"status: {resp.status_code}, lengte: {len(resp.text or '')}\n")
    return resp.text or ""


def toon_json_ld(html: str) -> None:
    print("=" * 70)
    print("JSON-LD blokken")
    print("=" * 70)
    blokken = re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    print(f"aantal: {len(blokken)}")
    for i, blok in enumerate(blokken):
        tekst = blok.strip()
        try:
            data = json.loads(tekst)
        except Exception as exc:
            print(f"  [{i}] onparseerbaar ({exc}), eerste 200: {tekst[:200]!r}")
            continue
        soort = data.get("@type") if isinstance(data, dict) else type(data).__name__
        print(f"  [{i}] @type={soort}, lengte={len(tekst)}")
        # Een ItemList met woningen is precies wat we willen.
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            items = data.get("itemListElement") or []
            print(f"      itemListElement: {len(items)} items")
            if items:
                print(f"      eerste item: {json.dumps(items[0], ensure_ascii=False)[:900]}")
        elif isinstance(data, dict):
            print(f"      sleutels: {list(data.keys())[:15]}")


def toon_embedded_state(html: str) -> None:
    print("\n" + "=" * 70)
    print("Embedded state / hydration")
    print("=" * 70)
    for naam, patroon in (
        ("__NEXT_DATA__", r'id="__NEXT_DATA__"[^>]*>(.*?)</script>'),
        ("__NUXT__", r"window\.__NUXT__\s*=\s*(.*?)</script>"),
        ("__INITIAL_STATE__", r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>"),
        ("self.__next_f", r"self\.__next_f\.push"),
    ):
        m = re.search(patroon, html, re.DOTALL)
        print(f"  {naam}: {'GEVONDEN' if m else 'niet gevonden'}")
        if m and m.lastindex:
            print(f"    eerste 300: {m.group(1)[:300]!r}")


def toon_kaart_markup(html: str) -> None:
    print("\n" + "=" * 70)
    print("Markup rond de eerste woning-links")
    print("=" * 70)
    treffers = list(re.finditer(r'href="(/detail/koop/[^"]+)"', html))
    print(f"totaal detail-links (incl. dubbel): {len(treffers)}")
    uniek = []
    gezien = set()
    for m in treffers:
        if m.group(1) not in gezien:
            gezien.add(m.group(1))
            uniek.append(m)
    print(f"unieke detail-links: {len(uniek)}\n")

    for m in uniek[:1]:
        start = max(0, m.start() - 1500)
        eind = min(len(html), m.end() + 1500)
        fragment = html[start:eind]
        # Whitespace indikken zodat het leesbaar in de log past.
        fragment = re.sub(r"\s+", " ", fragment)
        print(f"--- kaart rond {m.group(1)} ---")
        print(fragment[:2600])
        print()


def toon_totaal(html: str) -> None:
    print("\n" + "=" * 70)
    print("Totaal-aantal signalen")
    print("=" * 70)
    for patroon in (
        r"([\d.]+)\s*(?:koop)?woningen\b",
        r"([\d.]+)\s*resultaten\b",
        r'"totalCount"\s*:\s*(\d+)',
        r'"total"\s*:\s*(\d+)',
        r"resultaten van\s*([\d.]+)",
    ):
        for m in re.finditer(patroon, html, re.IGNORECASE):
            omgeving = re.sub(r"\s+", " ", html[max(0, m.start() - 90):m.end() + 90])
            print(f"  {patroon} -> {m.group(1)!r} | ...{omgeving}...")
            break


def main() -> int:
    html = haal(PARAMS)
    toon_json_ld(html)
    toon_embedded_state(html)
    toon_totaal(html)
    toon_kaart_markup(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
