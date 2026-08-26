"""Welke gebied-/straalnotaties accepteert funda.nl's zoekpagina?

De HTML-fallback is gebouwd en gevalideerd met een plaatsnaam ("den-haag"), maar
de echte config zoekt vanaf een postcode met een straal die niet per se een van
funda's ondersteunde waarden is. Dit script meet welke notaties werken.

Output is bewust compact zodat het in de Actions-log-staart past.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from curl_cffi import requests as curl_requests

BASIS = "https://www.funda.nl/zoeken/koop"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Neutrale voorbeeldpostcode in Den Haag (Bomenbuurt), niet de echte config.
PC = "2563bk"

VARIANTEN = [
    "den-haag,5km",          # bekend werkend, referentie
    f"{PC},6km",             # wat de code nu genereert bij radius_km=6
    f"{PC},5km",             # straal gesnapt naar een gangbare waarde
    f"{PC},10km",
    PC,                      # postcode zonder straal
    f"{PC.upper()},5km",     # hoofdletters
    "2563 bk,5km",           # met spatie
    "den-haag,6km",          # plaatsnaam met niet-gangbare straal
]


def meet(gebied: str) -> dict[str, object]:
    params = {
        "selected_area": f'["{gebied}"]',
        "price": "230000-310000",
        "object_type": '["apartment"]',
        "floor_area": "52-",
        "availability": '["available"]',
    }
    url = f"{BASIS}?{'&'.join(f'{k}={quote(v, safe=chr(39))}' for k, v in params.items())}"
    try:
        resp = curl_requests.get(
            url,
            headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
            impersonate="safari15_5",
            timeout=30,
        )
    except Exception as exc:
        return {"status": f"EXC {type(exc).__name__}", "kaarten": 0, "titel": str(exc)[:60]}

    html = resp.text or ""
    kaarten = len({m for m in re.findall(r'href="(/detail/koop/[^"]+)"', html)})
    titel = re.search(r"<title>(.*?)</title>", html)
    geen = bool(re.search(r"geen resultaten|niets gevonden|0 (?:koop)?woningen", html, re.I))
    return {
        "status": resp.status_code,
        "kaarten": kaarten,
        "geen_resultaten_tekst": geen,
        "titel": (titel.group(1)[:70] if titel else "?"),
    }


def main() -> int:
    print("Gebied-/straalnotaties op funda.nl\n")
    for gebied in VARIANTEN:
        info = meet(gebied)
        print(f"  {gebied!r:22} -> status={info['status']} kaarten={info['kaarten']} "
              f"leeg={info.get('geen_resultaten_tekst')} | {info['titel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
