"""Diagnose-probe voor de Funda-API.

Draait los van de dagelijkse run en print rauwe HTTP-status, response-headers en
een stukje body van de zoek- en detail-endpoints. Bedoeld om te zien *waarom*
een zoekopdracht faalt (bijv. 401) in plaats van alleen "0 resultaten".

Gebruik (lokaal of via de workflow "Funda API debug"):

    python scripts/funda_api_debug.py

Print nooit persoonlijke gegevens: de probe gebruikt een vaste dummy-postcode
en leest funda_personal.json niet.
"""

from __future__ import annotations

import json
import sys
import traceback

from curl_cffi import requests as curl_requests

API_SEARCH = "https://listing-search-wonen.funda.io/_msearch/template"
API_DETAIL_TINY = "https://listing-detail-page.funda.io/api/v4/listing/object/nl/tinyId/43117443"
SEARCH_INDEX = "listings-wonen-searcher-alias-prod"

# Neutrale zoekopdracht: Den Haag centrum, ruime prijsband. Geen privégegevens.
PROBE_POSTCODE = "2511cv"

TEMPLATE_OUD = "search_result_20250805"
TEMPLATE_NIEUW = "search_result_20260227"

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


def basis_headers(voor_zoek: bool, app_versie: bool = False) -> dict[str, str]:
    headers = {
        "user-agent": "Dart/3.9 (dart:io)",
        "accept-encoding": "gzip",
    }
    if voor_zoek:
        headers.update({
            "content-type": "application/json",
            "referer": "https://www.funda.nl/",
            "accept": "application/json",
        })
    else:
        headers.update({
            "x-funda-app-platform": "android",
            "content-type": "application/json",
        })
    if app_versie:
        headers["x-funda-app-version"] = "7.14.11"
    return headers


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

    def zoek_call(template_id: str, impersonate: str | None, app_versie: bool = False):
        kwargs = {"impersonate": impersonate} if impersonate else {}
        return curl_requests.post(
            API_SEARCH,
            headers=basis_headers(voor_zoek=True, app_versie=app_versie),
            data=zoek_body(template_id),
            timeout=30,
            **kwargs,
        )

    resultaten["zoek nieuw template, safari15_5"] = probeer(
        "ZOEK template=nieuw impersonate=safari15_5",
        lambda: zoek_call(TEMPLATE_NIEUW, "safari15_5"),
    )
    resultaten["zoek oud template, safari15_5"] = probeer(
        "ZOEK template=oud impersonate=safari15_5",
        lambda: zoek_call(TEMPLATE_OUD, "safari15_5"),
    )
    resultaten["zoek nieuw template, chrome124"] = probeer(
        "ZOEK template=nieuw impersonate=chrome124",
        lambda: zoek_call(TEMPLATE_NIEUW, "chrome124"),
    )
    resultaten["zoek nieuw template, geen impersonate"] = probeer(
        "ZOEK template=nieuw impersonate=geen",
        lambda: zoek_call(TEMPLATE_NIEUW, None),
    )
    resultaten["zoek nieuw template, met app-versie header"] = probeer(
        "ZOEK template=nieuw impersonate=safari15_5 + x-funda-app-version",
        lambda: zoek_call(TEMPLATE_NIEUW, "safari15_5", app_versie=True),
    )

    resultaten["detail tinyId, safari15_5"] = probeer(
        "DETAIL tinyId impersonate=safari15_5",
        lambda: curl_requests.get(
            API_DETAIL_TINY,
            headers=basis_headers(voor_zoek=False),
            impersonate="safari15_5",
            timeout=30,
        ),
    )
    resultaten["www.funda.nl homepage"] = probeer(
        "HOMEPAGE www.funda.nl",
        lambda: curl_requests.get(
            "https://www.funda.nl/",
            headers={"user-agent": "Mozilla/5.0"},
            impersonate="safari15_5",
            timeout=30,
        ),
    )

    # Terugvaloptie verkennen: is de publieke zoekpagina server-rendered en
    # bruikbaar vanaf een Actions-runner, of staat er een bot-muur voor?
    zoek_url = (
        "https://www.funda.nl/zoeken/koop"
        "?selected_area=%5B%22den-haag%22%5D&price=%22230000-310000%22"
    )
    print("\n--- ZOEKPAGINA (HTML-fallback) ---")
    try:
        resp = curl_requests.get(
            zoek_url,
            headers={
                "user-agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
                ),
                "accept-language": "nl-NL,nl;q=0.9",
            },
            impersonate="safari15_5",
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

    # Wat doet pyfunda zelf? (gebruikt de geïnstalleerde versie, incl. onze patch)
    print("\n--- pyfunda via de eigen client ---")
    try:
        sys.path.insert(0, ".")
        from funda_zoek import Funda  # noqa: PLC0415  (bewust laat: patch meenemen)

        f = Funda()
        print(f"  gekozen fingerprint: {getattr(f, '_fingerprint', None)}")
        try:
            treffers = f.search_listing(
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
    except Exception:
        traceback.print_exc()
        resultaten["pyfunda search_listing"] = -1

    print("\n=== Samenvatting ===")
    for naam, status in resultaten.items():
        print(f"  {naam}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
