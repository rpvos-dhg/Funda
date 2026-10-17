"""Zijn er nog andere ingangen naar funda's zoekresultaten?

De zoekpagina geeft 403 vanaf een Actions-runner. Dit script test systematisch
of er andere paden zijn die wél doorkomen, zodat de keuze op meting rust en niet
op aannames:

- de zoekpagina met afsluitende slash (wat pyfunda v3.1.5 gebruikt)
- Nuxt-payload-paden, die een Vue-app vaak los van de HTML ophaalt
- een woning-detailpagina als HTML (het detail-endpoint werkt al wel)
- sitemap en RSS, voor zover funda die publiceert

Per pad: status, lengte, en of er woninglinks in zitten.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from curl_cffi import requests as curl_requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "nl-NL,nl;q=0.9",
    "user-agent": UA,
}

PARAMS = {
    "selected_area": '["2563bk,5km"]',
    "price": "230000-310000",
    "object_type": '["apartment"]',
    "floor_area": "52-",
    "availability": '["available"]',
}
QUERY = "&".join(f"{k}={quote(v, safe=chr(39))}" for k, v in PARAMS.items())

PADEN = [
    ("zoekpagina zonder slash", f"https://www.funda.nl/zoeken/koop?{QUERY}"),
    ("zoekpagina MET slash (pyfunda v3.1.5)", f"https://www.funda.nl/zoeken/koop/?{QUERY}"),
    ("zoekpagina kaal, geen filters", "https://www.funda.nl/zoeken/koop/"),
    ("Nuxt payload", f"https://www.funda.nl/zoeken/koop/_payload.json?{QUERY}"),
    ("Nuxt payload, kaal", "https://www.funda.nl/zoeken/koop/_payload.json"),
    ("detailpagina als HTML", "https://www.funda.nl/detail/koop/den-haag/appartement-jonckbloetplein-30/44576894/"),
    ("sitemap index", "https://www.funda.nl/sitemap.xml"),
    ("robots.txt", "https://www.funda.nl/robots.txt"),
    ("homepage", "https://www.funda.nl/"),
]


def meet(naam: str, url: str) -> None:
    try:
        resp = curl_requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=30)
    except Exception as exc:
        print(f"  {naam:40} | EXC {type(exc).__name__}: {str(exc)[:40]}")
        return
    tekst = resp.text or ""
    links = len(set(re.findall(r'/detail/koop/[^"\s<]+', tekst)))
    nuxt = "__NUXT" in tekst or '"data"' in tekst[:400]
    print(f"  {naam:40} | status={resp.status_code} len={len(tekst)} "
          f"woninglinks={links} nuxt-achtig={nuxt}")


def main() -> int:
    print("Alternatieve ingangen naar funda\n")
    for naam, url in PADEN:
        meet(naam, url)
    print("\nrobots.txt is puur informatief hier: het zegt wat funda wíl, "
          "niet wat technisch lukt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
