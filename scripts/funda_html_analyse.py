"""Analyseer de structuur van funda.nl's zoekresultaten.

Voorbereiding op de HTML-fallback: bepaalt of er bruikbare gestructureerde data
in de pagina zit (JSON-LD) en welke velden per woningkaart uit de tekst te halen
zijn. Output is bewust compact zodat het in de Actions-log-staart past.
"""

from __future__ import annotations

import html as html_mod
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

# Vue/Nuxt SSR zet elke woningkaart in een container met deze klasse.
KAART_SPLITS = '<div class="@container'


def haal() -> str:
    url = f"{BASIS}?{'&'.join(f'{k}={quote(v, safe=chr(39))}' for k, v in PARAMS.items())}"
    resp = curl_requests.get(
        url,
        headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
        impersonate="safari15_5",
        timeout=30,
    )
    print(f"status {resp.status_code}, lengte {len(resp.text or '')}")
    return resp.text or ""


def platte_tekst(fragment: str) -> str:
    zonder_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL)
    tekst = re.sub(r"<[^>]+>", " | ", zonder_script)
    tekst = html_mod.unescape(tekst)
    tekst = re.sub(r"(\s*\|\s*)+", " | ", tekst)
    return re.sub(r"[ \t]+", " ", tekst).strip()


def json_ld(html: str) -> None:
    print("\n### JSON-LD ###")
    blokken = re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    print(f"aantal blokken: {len(blokken)}")
    for i, blok in enumerate(blokken):
        try:
            data = json.loads(blok.strip())
        except Exception:
            print(f"  [{i}] onparseerbaar")
            continue
        if isinstance(data, dict):
            soort = data.get("@type")
            print(f"  [{i}] @type={soort} sleutels={list(data.keys())[:10]}")
            if soort == "ItemList":
                items = data.get("itemListElement") or []
                print(f"      {len(items)} items; eerste:")
                print(f"      {json.dumps(items[0], ensure_ascii=False)[:800]}")
        else:
            print(f"  [{i}] type={type(data).__name__} len={len(data)}")


def kaarten(html: str) -> None:
    print("\n### Woningkaarten (tekstinhoud) ###")
    delen = html.split(KAART_SPLITS)
    print(f"fragmenten na split op {KAART_SPLITS!r}: {len(delen) - 1}")

    met_link = [d for d in delen[1:] if "/detail/koop/" in d]
    print(f"fragmenten met detail-link: {len(met_link)}\n")

    for i, deel in enumerate(met_link[:3]):
        link = re.search(r'href="(/detail/koop/[^"]+)"', deel)
        tekst = platte_tekst(deel)
        print(f"--- kaart {i} ---")
        print(f"link: {link.group(1) if link else None}")
        print(f"tekst: {tekst[:700]}")
        print()


def main() -> int:
    h = haal()
    json_ld(h)
    kaarten(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
