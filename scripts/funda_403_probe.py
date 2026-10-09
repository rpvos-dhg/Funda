"""Meet welke client-presentatie funda.nl's zoekpagina nog accepteert.

Sinds 8 oktober 2026 geeft `www.funda.nl/zoeken/koop` een 403 vanaf een
Actions-runner, terwijl de homepage en het detail-endpoint het nog wél doen. Het
IP is dus niet volledig geweerd; alleen het zoekpad is strenger geworden.

Dit script probeert een matrix van TLS-profielen en headersets en rapporteert per
combinatie de status en het aantal gevonden woningkaarten. Daarmee is te zien óf
er nog een werkende combinatie is - en zo niet, dan is dat ook een antwoord.

Tijdelijk diagnostisch script; hoort niet in de dagelijkse run.
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from curl_cffi import requests as curl_requests

BASIS = "https://www.funda.nl/zoeken/koop"
HOMEPAGE = "https://www.funda.nl/"

PARAMS = {
    "selected_area": '["2563bk,5km"]',
    "price": "230000-310000",
    "object_type": '["apartment"]',
    "floor_area": "52-",
    "availability": '["available"]',
}

ZOEK_URL = f"{BASIS}?{'&'.join(f'{k}={quote(v, safe=chr(39))}' for k, v in PARAMS.items())}"

# Wat de code nu stuurt: alleen user-agent en taal.
HEADERS_MINIMAAL = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "accept-language": "nl-NL,nl;q=0.9",
}

# Wat een echte browser stuurt bij het navigeren naar een pagina.
HEADERS_BROWSER = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "accept-encoding": "gzip, deflate, br",
    "upgrade-insecure-requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "cache-control": "max-age=0",
}

# Idem, maar alsof je vanaf de funda-homepage doorklikt.
HEADERS_BROWSER_MET_REFERER = dict(HEADERS_BROWSER, **{
    "referer": "https://www.funda.nl/",
    "sec-fetch-site": "same-origin",
})

PROFIELEN = ["safari15_5", "chrome124", "chrome120", "chrome131", "safari17_0", "firefox133"]

HEADERSETS = [
    ("minimaal (huidige code)", HEADERS_MINIMAAL),
    ("browser-achtig", HEADERS_BROWSER),
    ("browser + referer", HEADERS_BROWSER_MET_REFERER),
]


def kaarten(html: str) -> int:
    return len(set(re.findall(r'href="(/detail/koop/[^"]+)"', html)))


def probeer(profiel: str, headers: dict, warm_op: bool) -> str:
    """Eén poging. `warm_op` bezoekt eerst de homepage, zoals een echte bezoeker."""
    try:
        sessie = curl_requests.Session(impersonate=profiel)
    except Exception as exc:
        return f"profiel onbekend ({type(exc).__name__})"

    try:
        if warm_op:
            r0 = sessie.get(HOMEPAGE, headers=headers, timeout=30)
            time.sleep(1.0)
            if r0.status_code != 200:
                return f"homepage {r0.status_code}"
        resp = sessie.get(ZOEK_URL, headers=headers, timeout=30)
    except Exception as exc:
        return f"EXC {type(exc).__name__}: {str(exc)[:50]}"

    html = resp.text or ""
    muur = "Je bent bijna op de pagina" in html
    return f"status={resp.status_code} kaarten={kaarten(html)} botmuur={muur} len={len(html)}"


def main() -> int:
    print("Matrix: TLS-profiel x headerset op de zoekpagina\n")
    print(f"URL: {ZOEK_URL}\n")

    for profiel in PROFIELEN:
        for naam, headers in HEADERSETS:
            uitkomst = probeer(profiel, headers, warm_op=False)
            print(f"  {profiel:12} | {naam:24} | {uitkomst}")
            time.sleep(0.8)

    print("\nMet homepage-bezoek vooraf (cookies/sessie opbouwen):")
    for profiel in ("chrome124", "safari15_5"):
        uitkomst = probeer(profiel, HEADERS_BROWSER_MET_REFERER, warm_op=True)
        print(f"  {profiel:12} | browser + referer + warmup | {uitkomst}")
        time.sleep(1.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
