"""Offline tests voor de huispedia-bron en de CBS-buurtbepaling. Geen netwerk.

De fixtures zijn nagebouwd op echte markup van huispedia.nl (gemeten 6 nov
2026): de zoekpagina is een Inertia-app met de resultaten als HTML-ge-escapete
JSON in `<div id="app" data-page="...">`, onder props.searchData.mapProperties;
de detailpagina heeft schema.org JSON-LD. De woningen hieronder zijn verzonnen,
de veldnamen en vorm zijn echt.

Draaien: python test_bron_huispedia.py
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from bron_huispedia import (
    HuispediaZoeker,
    adres_sleutel,
    bouw_zoek_url,
    maak_zoeker,
    naar_listing,
    parse_detail,
    parse_zoekpagina,
)
from buurten_cbs import BuurtBepaler, buurten_url, parse_buurten

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from bronnen_derden_probe import parse_robots, robots_toegestaan  # noqa: E402


def record(**over) -> dict:
    """Eén mapProperties-record met precies de velden die huispedia levert."""
    basis = {
        "street": "Teststraat", "street_slug": "teststraat", "postcode": "2547AA",
        "hnum": 10, "hchar": None, "hnumchar": "10", "lon": 4.2700, "lat": 52.0600,
        "city_name": "Den Haag", "city_slug": "den-haag", "woonoppervlakte": 70,
        "perceeloppervlakte": None, "object_type": "appartement", "bouwjaar": 1965,
        "aantal_kamers": 3, "energie_label": "C", "img_src": "id_1_2.jpg",
        "img_storage_location": "huispedia_server", "office_id": 1,
        "office_name": "Voorbeeld Makelaars", "user_id": 1, "price_valuation_enabled": True,
        "updated_at": 1793810414, "price_sale": 280000, "price_label": "PRICE_INITIAL",
        "market_label": "NEW_ON_THE_MARKET", "valuation_label": "HIGH", "price_rent": None,
        "price_min_bid": None, "price_aot_indication": None, "price_search": 280000,
        "available_on_term_at": None, "available_on_term_from": None, "status": "TE KOOP",
        "status_updated_at": 1793810414, "status_updated_by": "REALTOR", "counts_images": 30,
        "listing_type": "basic", "ml_sale_price_m": 275460,
        "property_description_features": None, "early_discovery_seconds": None,
        "id": "1000001", "isFavorite": False,
    }
    basis.update(over)
    return basis


def zoekpagina(recs: list[dict], totaal: int | None = None) -> str:
    pagina = {
        "component": "Search/SearchPage",
        "props": {
            "errors": {}, "auth": {"user": None}, "csrf_token": "x",
            "app_data": {"searchFilters": {"propertyType": "appartement"}},
            "searchData": {
                "type": "city", "total_results": len(recs) if totaal is None else totaal,
                "properties": recs[:10], "mapData": {"locationPolygons": []},
                "title": "Koopwoningen in Den Haag", "cache": False,
                "mapProperties": recs,
            },
        },
        "url": "/koopwoningen/den-haag/appartement", "version": "1",
    }
    attr = html.escape(json.dumps(pagina, separators=(",", ":")), quote=True)
    return (f'<html><body><section class="hp-nav"></section>\n    <div id="app" data-page="{attr}">'
            "</div></body></html>")


DETAIL = """<html><head>
<script type="application/ld+json">{"@context":"http://schema.org","@type":"Organization","name":"Huispedia.nl"}</script>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"RealEstateListing","@id":"https://huispedia.nl/den-haag/2547aa/teststraat/10#listing",
 "description":"Gelegen aan de Teststraat ligt dit appartement op de tweede etage.",
 "datePosted":"2026-10-22","dateModified":"2026-11-01T22:20:38+01:00"},
{"@type":["Apartment","Product"],"@id":"https://huispedia.nl/den-haag/2547aa/teststraat/10#home",
 "geo":{"@type":"GeoCoordinates","latitude":52.06,"longitude":4.27},
 "accommodationCategory":"Galerijflat","floorSize":{"value":70},"numberOfRooms":3,"numberOfBedrooms":2,
 "additionalProperty":[{"@type":"PropertyValue","name":"Soort appartement","value":"Galerijflat"},
  {"@type":"PropertyValue","name":"Gelegen op","value":"2e verdieping"},
  {"@type":"PropertyValue","name":"Maandelijkse bijdrage","value":"€ 330 per maand"}]},
{"@type":"Offer","@id":"https://huispedia.nl/den-haag/2547aa/teststraat/10#offer","price":280000},
{"@type":"Place","@id":"https://huispedia.nl/gemeente/s-gravenhage/buurt/leyenburg#place","name":"Leyenburg",
 "containedInPlace":{"@type":"Place","@id":"https://huispedia.nl/gemeente/s-gravenhage/wijk/wijk-32-leyenburg#place","name":"Leyenburg"}}
]}</script></head><body></body></html>"""


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return voorwaarde


def test_url() -> bool:
    print("test: zoek-URL")
    url = bouw_zoek_url("den-haag", prijs_min=230000, prijs_max=310000, m2_min=55)
    delen = urlsplit(url)
    staat = json.loads(unquote(parse_qs(delen.query)["searchQueryState"][0]))
    ok = check("pad", delen.path == "/koopwoningen/den-haag/appartement", delen.path)
    ok &= check("prijsfilter", staat["filter"]["price"] == {"min": 230000, "max": 310000})
    ok &= check("m2-filter", staat["filter"]["surface"]["min"] == 55)
    ok &= check("type", staat["filter"]["object_type"] == "appartement")
    ok &= check("geen /api/", "/api/" not in url)
    return ok


def test_parse() -> bool:
    print("test: zoekpagina parsen")
    recs = [record(), record(id="2", hnum=906, hchar="C", hnumchar="906-C", postcode="2544CA")]
    totaal, uit = parse_zoekpagina(zoekpagina(recs))
    ok = check("aantal", totaal == 2 and len(uit) == 2, f"{totaal} {len(uit)}")
    d = naar_listing(uit[1])
    ok &= check("titel met toevoeging", d["title"] == "Teststraat 906-C", d["title"])
    ok &= check("sleutel bron-onafhankelijk", d["global_id"] == "huispedia:2544CA-906-C", d["global_id"])
    ok &= check("funda-veldnamen", d["price"] == 280000 and d["living_area"] == 70
                and d["city"] == "Den Haag" and d["postcode"] == "2544CA" and d["house_number"] == 906)
    ok &= check("coördinaten", d["latitude"] == 52.06 and d["longitude"] == 4.27)
    ok &= check("appartement geeft geen house_type", d["house_type"] is None)
    ok &= check("woonhuis wél", naar_listing(record(object_type="woonhuis"))["house_type"] == "woonhuis")
    ok &= check("detail-URL", d["detail_url"] == "https://huispedia.nl/den-haag/2544ca/teststraat/906",
                d["detail_url"])
    try:
        parse_zoekpagina("<html><div id='app'></div></html>")
        ok &= check("kapotte pagina gooit", False, "geen exception")
    except ValueError:
        ok &= check("kapotte pagina gooit (geen stille nul)", True)
    ok &= check("adres_sleutel normaliseert", adres_sleutel("2547 cb", 811) == "2547CB-811")
    return ok


def test_detail() -> bool:
    print("test: detailpagina (JSON-LD)")
    d = parse_detail(DETAIL)
    ok = check("buurt (eigen veld)", d.get("huispedia_buurt") == "Leyenburg", str(d.get("huispedia_buurt")))
    ok &= check("overschrijft CBS-buurt niet", "neighbourhood" not in d)
    ok &= check("gelegen_op voor is_begane_grond", d.get("gelegen_op") == "2e verdieping")
    ok &= check("publicatiedatum", d.get("publication_date") == "2026-10-22")
    ok &= check("subtype", d.get("house_type") == "Galerijflat")
    ok &= check("slaapkamers", d.get("bedrooms") == 2)
    ok &= check("kenmerken in omschrijving", "Maandelijkse bijdrage: € 330" in d.get("description", ""))
    return ok


def test_zoeker() -> bool:
    print("test: drop-in zoeker")
    dh = [record(), record(id="2", hnum=12, hnumchar="12", status="ONDER BOD KOOP"),
          record(id="3", hnum=14, hnumchar="14", price_sale=320000, price_search=320000),
          record(id="4", hnum=16, hnumchar="16", status="PREMARKET_LISTING", price_sale=0)]
    lv = [record(id="5", city_name="Voorburg", city_slug="voorburg", postcode="2273AA", lat=52.08, lon=4.35)]
    verzoeken: list[str] = []

    def haal(url: str) -> str:
        verzoeken.append(url)
        if "/koopwoningen/den-haag" in url:
            return zoekpagina(dh)
        if "/koopwoningen/leidschendam-voorburg" in url:
            return zoekpagina(lv)
        if url.endswith("/teststraat/10"):
            return DETAIL
        raise AssertionError(url)

    buurt = BuurtBepaler([{"buurt": "Leyenburg", "gemeente": "'s-Gravenhage",
                           "bbox": [4.26, 52.05, 4.28, 52.07],
                           "polygonen": [[[[4.26, 52.05], [4.28, 52.05], [4.28, 52.07], [4.26, 52.07],
                                           [4.26, 52.05]]]]}])
    z = HuispediaZoeker(prijs_bereik=(230000, 310000), haal=haal, pauze=0, buurt_bepaler=buurt)
    band1 = z.search_listing(location="genegeerd", radius_km=6, price_min=230000, price_max=290000,
                             object_type=["apartment"], area_min=55, page=0)
    band2 = z.search_listing(location="genegeerd", radius_km=6, price_min=290000, price_max=310000,
                             object_type=["apartment"], area_min=55, page=0)
    ok = check("twee zoekverzoeken voor alle banden samen", len(verzoeken) == 2, str(len(verzoeken)))
    titels = sorted(r.data["title"] for r in band1)
    ok &= check("alleen beschikbaar, binnen de band", titels == ["Teststraat 10"] * 2, str(titels))
    ok &= check("Voorburg erbij, met eigen woonplaats",
                any(r.data["city"] == "Voorburg" for r in band1))
    ok &= check("onder bod en premarket weg", all(r.data["status"] == "TE KOOP" for r in band1 + band2))
    ok &= check("te duur valt buiten alle banden", not any(r.data["price"] == 320000 for r in band1 + band2))
    ok &= check("buurt uit CBS-polygoon", band1[0].data["neighbourhood"] == "Leyenburg",
                str(band1[0].data.get("neighbourhood")))
    ok &= check("buiten polygoon = onbekend", next(r for r in band1 if r.data["city"] == "Voorburg")
                .data["neighbourhood"] is None)
    ok &= check("pagina 1+ is leeg", z.search_listing(price_min=230000, price_max=310000, page=1) == [])
    det = z.get_listing("huispedia:2547AA-10")
    ok &= check("detail aangevuld", det.data.get("gelegen_op") == "2e verdieping"
                and det.data["price"] == 280000)
    z.get_listing("huispedia:2547AA-10")
    ok &= check("detail gecachet", sum(u.endswith("/teststraat/10") for u in verzoeken) == 1)
    return ok


def test_afkappen() -> bool:
    print("test: afgekapt antwoord wordt gesplitst")
    verzoeken: list[str] = []

    def haal(url: str) -> str:
        verzoeken.append(url)
        staat = json.loads(unquote(parse_qs(urlsplit(url).query)["searchQueryState"][0]))
        lo, hi = staat["filter"]["price"]["min"], staat["filter"]["price"]["max"]
        if hi - lo > 40000:
            return zoekpagina([record()], totaal=1500)  # te veel: afgekapt
        return zoekpagina([record(id=str(lo), hnum=lo // 1000, hnumchar=str(lo // 1000), price_sale=lo + 1)])

    z = HuispediaZoeker(gemeenten=["den-haag"], prijs_bereik=(230000, 310000), haal=haal, pauze=0)
    uit = z.search_listing(price_min=230000, price_max=310000, page=0)
    return check("splitst tot het past", len(uit) >= 2 and len(verzoeken) > 2, f"{len(uit)} woningen, {len(verzoeken)} verzoeken")


def test_buurten() -> bool:
    print("test: CBS-buurten")
    geojson = {"numberReturned": 1, "features": [{
        "properties": {"buurtnaam": "Venen, Oorden en Raden", "gemeentenaam": "'s-Gravenhage"},
        "geometry": {"type": "MultiPolygon", "coordinates": [[
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],  # gat
        ]]},
    }]}
    b = BuurtBepaler(parse_buurten(geojson))
    ok = check("binnen", b(lat=2, lon=2) == "Venen, Oorden en Raden")
    ok &= check("in het gat = niet", b(lat=5, lon=5) is None)
    ok &= check("buiten", b(lat=20, lon=20) is None)
    ok &= check("geen coördinaat", b(None, None) is None)
    ok &= check("URL met CBS-gemeentenaam", "gemeentenaam=%27s-Gravenhage" in buurten_url("den-haag"))
    return ok


def test_maak_zoeker() -> bool:
    print("test: maak_zoeker (buurten uit PDOK, daarna uit de cache)")
    import tempfile

    geojson = {"numberReturned": 1, "features": [{
        "properties": {"buurtnaam": "Leyenburg", "gemeentenaam": "'s-Gravenhage"},
        "geometry": {"type": "Polygon", "coordinates": [
            [[4.26, 52.05], [4.28, 52.05], [4.28, 52.07], [4.26, 52.07], [4.26, 52.05]]]},
    }]}
    verzoeken: list[str] = []

    def haal(url: str) -> str:
        verzoeken.append(url)
        if "api.pdok.nl/cbs/" in url:
            return json.dumps(geojson)
        return zoekpagina([record()])

    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "buurten.json"
        z = maak_zoeker(prijs_bereik=(230000, 310000), gemeenten=["den-haag"], buurten_cache=cache,
                        haal=haal)
        uit = z.search_listing(price_min=230000, price_max=310000, page=0)
        ok = check("buurt ingevuld", uit and uit[0].data["neighbourhood"] == "Leyenburg")
        ok &= check("cache geschreven", cache.exists())
        pdok_voor = sum("api.pdok.nl" in u for u in verzoeken)
        maak_zoeker(prijs_bereik=(230000, 310000), gemeenten=["den-haag"], buurten_cache=cache, haal=haal)
        ok &= check("tweede keer uit cache", sum("api.pdok.nl" in u for u in verzoeken) == pdok_voor)

    meldingen: list[str] = []

    def stuk(url: str) -> str:
        if "api.pdok.nl" in url:
            raise RuntimeError("PDOK gaf status 503")
        return zoekpagina([record()])

    z = maak_zoeker(prijs_bereik=(230000, 310000), gemeenten=["den-haag"], haal=stuk, log=meldingen.append)
    uit = z.search_listing(price_min=230000, price_max=310000, page=0)
    ok &= check("zonder PDOK: woningen wel, buurt leeg", uit and "neighbourhood" not in uit[0].data)
    ok &= check("zonder PDOK: gelogd", any("CBS-buurten niet te laden" in m for m in meldingen))
    return ok


def test_detailbudget() -> bool:
    print("test: detailbudget en blijvende detailcache")
    import tempfile

    recs = [record(id=str(i), hnum=i, hnumchar=str(i)) for i in (10, 12, 14)]
    verzoeken: list[str] = []

    def haal(url: str) -> str:
        verzoeken.append(url)
        if "/koopwoningen/" in url:
            return zoekpagina(recs)
        return DETAIL.replace("2e verdieping", "Begane grond")

    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "details.json"
        z = HuispediaZoeker(gemeenten=["den-haag"], prijs_bereik=(230000, 310000), haal=haal, pauze=0,
                            max_details=2, detail_cache_pad=cache)
        ids = [r.data["global_id"] for r in z.search_listing(price_min=230000, price_max=310000)]
        uit = [z.get_listing(i) for i in ids]
        details = sum(1 for u in verzoeken if "/koopwoningen/" not in u)
        ok = check("max 2 detailverzoeken", details == 2, str(details))
        ok &= check("derde zonder detail, wel teruggegeven", "gelegen_op" not in uit[2].data)
        ok &= check("begane grond doorgegeven", uit[0].data.get("gelegen_op") == "Begane grond")

        # Volgende run: de twee bekende uit de cache, alleen de derde wordt opgehaald.
        verzoeken.clear()
        recs[0]["price_sale"] = 250000  # prijs gedaald sinds de cache
        z2 = HuispediaZoeker(gemeenten=["den-haag"], prijs_bereik=(230000, 310000), haal=haal, pauze=0,
                             max_details=2, detail_cache_pad=cache)
        ids = [r.data["global_id"] for r in z2.search_listing(price_min=230000, price_max=310000)]
        uit = [z2.get_listing(i) for i in ids]
        details = sum(1 for u in verzoeken if "/koopwoningen/" not in u)
        ok &= check("tweede run: alleen de nieuwe", details == 1, str(details))
        ok &= check("prijs uit zoekdata, niet uit cache", uit[0].data["price"] == 250000,
                    str(uit[0].data["price"]))
    return ok


def test_robots() -> bool:
    print("test: robots.txt-lezing van de probe")
    regels = parse_robots(
        "User-agent: Googlebot\nDisallow: /\n\n"
        "User-agent: *\nDisallow: /koopwoningen/*/appartement/page-*\nDisallow: */*m2*\n"
        "Disallow: /bzk/locatieserver/*\nAllow: /koopwoningen/den-haag/adres-*\n"
        "Disallow: /koopwoningen/*/adres-*\n"
    )
    ok = check("prijspad mag", robots_toegestaan(regels, "/koopwoningen/den-haag/appartement/230000-310000"))
    ok &= check("doorbladeren niet", not robots_toegestaan(regels, "/koopwoningen/den-haag/appartement/page-2"))
    ok &= check("m2-filter niet", not robots_toegestaan(regels, "/koopwoningen/den-haag/55m2"))
    ok &= check("locatieserver niet", not robots_toegestaan(regels, "/bzk/locatieserver/search/v3_1/free?q=x"))
    ok &= check("langste regel wint (Allow)", robots_toegestaan(regels, "/koopwoningen/den-haag/adres-x"))
    ok &= check("Googlebot-groep telt niet mee", robots_toegestaan(regels, "/iets"))
    return ok


def main() -> int:
    resultaten = [test_url(), test_parse(), test_detail(), test_zoeker(), test_afkappen(),
                  test_buurten(), test_maak_zoeker(), test_detailbudget(), test_robots()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
