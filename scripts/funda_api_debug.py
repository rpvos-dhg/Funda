"""Diagnose-probe voor de Funda-API.

Draait los van de dagelijkse run en print rauwe HTTP-status, response-headers en
een stukje body van de zoek- en detail-endpoints. Bedoeld om te zien *waarom*
een zoekopdracht faalt (bijv. 401) in plaats van alleen "0 resultaten".

Gebruik (lokaal of via de handmatige workflow "Funda API debug"; niet meer
automatisch na een mislukte dagelijkse run):

    python scripts/funda_api_debug.py

Eén vaste client per host, dezelfde als de dagelijkse run: voor funda's
API-hosts de eerlijke client uit funda_zoek.py (eigen user-agent, geen
browser- of app-profiel), voor www.funda.nl het ene safari-profiel van de
HTML-zoeker. Geen varianten om te kijken welke er wél doorkomt: dat is
botbescherming omzeilen (zie CLAUDE.md).

Print nooit persoonlijke gegevens: de probe gebruikt een vaste dummy-postcode
en leest funda_personal.json niet.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curl_cffi import requests as curl_requests  # noqa: E402

from funda_zoek import EERLIJKE_UA, Funda  # noqa: E402  (de gepatchte, eerlijke client)

API_SEARCH = "https://listing-search-wonen.funda.io/_msearch/template"
DETAIL_TINY_ID = 43117443   # dezelfde woning die pyfunda zelf als test gebruikt
SEARCH_INDEX = "listings-wonen-searcher-alias-prod"

# Neutrale zoekopdracht: Den Haag centrum, ruime prijsband. Geen privégegevens.
PROBE_POSTCODE = "2511cv"

TEMPLATE_OUD = "search_result_20250805"
TEMPLATE_NIEUW = "search_result_20260227"

# Zelfde profiel als funda_html_zoek.HtmlZoeker, voor www.funda.nl.
WWW_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
WWW_IMPERSONATE = "safari15_5"

INTERESSANTE_HEADERS = (
    "server", "www-authenticate", "content-type", "cf-ray", "cf-mitigated",
    "x-amzn-errortype", "x-amz-apigw-id", "x-cache", "via", "x-envoy-upstream-service-time",
    "retry-after", "x-ratelimit-remaining",
)


def zoek_body(template_id: str) -> str:
    params = {
        "availability": ["available"],
        "type": ["single"],
        "zoning": ["residential"],
        "object_type": ["apartment"],
        "publication_date": {"no_preference": True},
        "offering_type": "buy",
        "page": {"from": 0},
        "sort": {"field": None, "order": None},
        "radius_search": {
            "index": "geo-wonen-alias-prod",
            "id": f"{PROBE_POSTCODE}-0",
            "path": "area_with_radius.5",
        },
        "price": {"selling_price": {"from": 200000, "to": 400000}},
    }
    index_line = json.dumps({"index": SEARCH_INDEX})
    query_line = json.dumps({"id": template_id, "params": params})
    return f"{index_line}\n{query_line}\n"


def eerlijke_headers() -> dict[str, str]:
    return {"user-agent": EERLIJKE_UA, "accept": "application/json",
            "content-type": "application/json"}


def toon(naam: str, response) -> int:
    status = getattr(response, "status_code", 0)
    print(f"\n--- {naam} ---")
    print(f"  status: {status}")
    headers = getattr(response, "headers", {}) or {}
    for sleutel in INTERESSANTE_HEADERS:
        waarde = headers.get(sleutel)
        if waarde:
            print(f"  {sleutel}: {waarde}")
    try:
        body = response.text or ""
    except Exception:
        body = "<geen tekst>"
    print(f"  body[:500]: {body[:500]!r}")
    return status


def probeer(naam: str, fn) -> int:
    try:
        return toon(naam, fn())
    except Exception as exc:
        print(f"\n--- {naam} ---")
        print(f"  EXCEPTIE: {type(exc).__name__}: {exc}")
        return -1


def main() -> int:
    print("Funda API debug-probe")
    print(f"python {sys.version.split()[0]}")

    resultaten: dict[str, int] = {}

    # Zoek-API: dezelfde eerlijke client (gewone curl, geen impersonate), alleen
    # de template verschilt. Zegt of de 401 er nog is.
    def zoek_call(template_id: str):
        return curl_requests.post(API_SEARCH, headers=eerlijke_headers(),
                                  data=zoek_body(template_id), timeout=30)

    resultaten["zoek nieuw template"] = probeer("ZOEK template=nieuw", lambda: zoek_call(TEMPLATE_NIEUW))
    resultaten["zoek oud template"] = probeer("ZOEK template=oud", lambda: zoek_call(TEMPLATE_OUD))

    # Detail-endpoint: precies de client van de dagelijkse run.
    print("\n--- DETAIL via de client van de dagelijkse run ---")
    f = Funda()
    try:
        listing = f.get_listing(DETAIL_TINY_ID)
        print(f"  statussen: {f._statussen}")
        print(f"  titel: {(listing.data or {}).get('title')!r}")
        resultaten["detail tinyId"] = 200
    except Exception as exc:
        print(f"  statussen: {f._statussen}")
        print(f"  EXCEPTIE: {type(exc).__name__}: {exc}")
        resultaten["detail tinyId"] = (f._statussen or [-1])[-1]

    resultaten["www.funda.nl homepage"] = probeer(
        "HOMEPAGE www.funda.nl",
        lambda: curl_requests.get("https://www.funda.nl/", headers={"user-agent": WWW_UA},
                                  impersonate=WWW_IMPERSONATE, timeout=30),
    )

    # Is de publieke zoekpagina bruikbaar vanaf een Actions-runner, of staat er
    # een bot-muur voor? Zelfde profiel als de HTML-zoeker.
    zoek_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=%5B%22den-haag%22%5D&price=%22230000-310000%22"
    )
    print("\n--- ZOEKPAGINA (HTML-fallback) ---")
    try:
        resp = curl_requests.get(
            zoek_url,
            headers={"user-agent": WWW_UA, "accept-language": "nl-NL,nl;q=0.9"},
            impersonate=WWW_IMPERSONATE,
            timeout=30,
        )
        html = resp.text or ""
        print(f"  status: {resp.status_code}")
        print(f"  lengte: {len(html)}")
        print(f"  bot-interstitial: {'Je bent bijna op de pagina' in html}")
        print(f"  aantal /koop/-links: {html.count('/koop/')}")
        print(f"  __NEXT_DATA__ aanwezig: {'__NEXT_DATA__' in html}")
        print(f"  title: {html[html.find('<title>'):html.find('</title>') + 8][:120]!r}")
        resultaten["zoekpagina HTML"] = resp.status_code
    except Exception as exc:
        print(f"  EXCEPTIE: {type(exc).__name__}: {exc}")
        resultaten["zoekpagina HTML"] = -1

    # Wat doet pyfunda zelf? (de gepatchte client: template-fix en eerlijke client)
    print("\n--- pyfunda via de eigen client ---")
    try:
        treffers = Funda().search_listing(
            location=PROBE_POSTCODE,
            radius_km=5,
            offering_type="buy",
            price_min=200000,
            price_max=400000,
            object_type=["apartment"],
            availability=["available"],
            page=0,
        )
        print(f"  search_listing: {len(treffers)} resultaten")
        resultaten["pyfunda search_listing"] = len(treffers)
    except Exception as exc:
        print(f"  search_listing EXCEPTIE: {type(exc).__name__}: {exc}")
        resultaten["pyfunda search_listing"] = -1
    except BaseException:
        traceback.print_exc()
        resultaten["pyfunda search_listing"] = -1

    print("\n=== Samenvatting ===")
    for naam, status in resultaten.items():
        print(f"  {naam}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
