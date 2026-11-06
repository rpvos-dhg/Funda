"""Offline tests voor de sitemaproute. Geen netwerk nodig.

De fixtures volgen de vorm die op 6 nov 2026 vanaf Actions is gemeten
(scripts/funda_sitemap_probe.py): robots.txt met één Sitemap:-regel, een index
met koop1..4 plus huur/nieuwbouw/recreatie/europe, en urlsets met per woning een
<lastmod>. `scripts/funda_sitemap_validatie.py` controleert tegen de echte site.

Draaien: python test_funda_sitemap.py
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
from pathlib import Path

from funda_sitemap_zoek import (
    SitemapZoeker,
    detail_verboden,
    in_doelmarkt,
    kandidaten_uit,
    ontleed_sitemap,
    sitemap_uit_robots,
    woning_uit_url,
)

ROBOTS = """User-agent: *

# Miscellaneous
Allow: /zoeken/
Allow: /detail/
Disallow: /account/
Disallow: /zoeken/koop/*,*

# Sitemap
Sitemap: https://www.funda.nl/sitemap_index.xml/
"""

INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.funda.nl/sitemap-detail-koop1.xml</loc><lastmod>2026-11-06T04:59:19+01:00</lastmod></sitemap>
<sitemap><loc>https://www.funda.nl/sitemap-detail-koop2.xml</loc><lastmod>2026-11-06T04:59:23+01:00</lastmod></sitemap>
<sitemap><loc>https://www.funda.nl/sitemap-detail-huur.xml</loc><lastmod>2026-11-06T04:59:29+01:00</lastmod></sitemap>
<sitemap><loc>https://www.funda.nl/sitemap-detail-nieuwbouw.xml</loc><lastmod>2026-11-06T04:59:29+01:00</lastmod></sitemap>
</sitemapindex>
"""


def index_met(datum: str) -> str:
    """De index met een andere lastmod voor alle kinderen (een nieuwe snapshot)."""
    return INDEX.replace("2026-11-06T04:59", datum)


def urlset(*rijen: tuple[str, str]) -> str:
    binnen = "".join(f"<url><loc>{u}</loc><lastmod>{lm}</lastmod></url>\n" for u, lm in rijen)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{binnen}</urlset>\n")


B = "https://www.funda.nl/detail/koop"
KOOP1 = urlset(
    (f"{B}/den-haag/appartement-draaistraat-4/80024814/", "2026-11-06T01:00:09+01:00"),
    (f"{B}/den-haag/huis-boeistraat-29/44663175/", "2026-11-06T04:00:04+01:00"),
    (f"{B}/amsterdam/appartement-galjootstraat-148/80028270/", "2026-11-06T04:26:37+01:00"),
    (f"{B}/voorburg/appartement-rodelaan-379/44546400/", "2026-10-17T10:00:00+02:00"),
)
KOOP2 = urlset(
    (f"{B}/den-haag/appartement-koningin-emmakade-185/44664520/", "2026-11-06T00:00:15+01:00"),
    (f"{B}/den-haag/parkeergelegenheid-x-1/44664999/", "2026-11-05T10:00:00+01:00"),
    (f"{B}/rijswijk/appartement-y-2/44660000/", "2026-11-05T10:00:00+01:00"),
)

# Wat het detail-endpoint per woning teruggeeft (alleen de velden die tellen).
DETAILS = {
    "80024814": {"global_id": 1001, "title": "Draaistraat 4", "city": "Den Haag",
                 "price": 299500, "living_area": 77, "status": "available"},
    "44664520": {"global_id": 1002, "title": "Koningin Emmakade 185", "city": "Den Haag",
                 "price": 950000, "living_area": 179, "status": "available"},
    "44546400": {"global_id": 1003, "title": "Rodelaan 379", "city": "Voorburg",
                 "price": 269500, "living_area": 58, "status": "available"},
}


class Listing:
    def __init__(self, data):
        self.data = data


class StubClient:
    def __init__(self, details=None):
        self.details = dict(details or DETAILS)
        self.calls: list[str] = []

    def get_listing(self, ident):
        self.calls.append(str(ident))
        sleutel = str(ident).rstrip("/").split("/")[-1]
        if sleutel not in self.details:
            raise LookupError(f"Listing {sleutel} not found")
        return Listing(dict(self.details[sleutel]))

    def get_price_history(self, ident):
        return [{"prijs": 1}]


class StubWeb:
    def __init__(self, pagina=None):
        self.pagina = dict(pagina or {
            "https://www.funda.nl/robots.txt": ROBOTS,
            "https://www.funda.nl/sitemap_index.xml/": INDEX,
            "https://www.funda.nl/sitemap-detail-koop1.xml": KOOP1,
            "https://www.funda.nl/sitemap-detail-koop2.xml": KOOP2,
        })
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        waarde = self.pagina.get(url)
        if isinstance(waarde, Exception):
            raise waarde
        if waarde is None:
            raise RuntimeError(f"{url} gaf status 404")
        return waarde


def check(naam: str, ok: bool) -> bool:
    print(f"  {'OK  ' if ok else 'FOUT'} {naam}")
    return ok


def zoeker(web=None, client=None, **kw):
    kw.setdefault("prijs_min", 230_000)
    kw.setdefault("prijs_max", 310_000)
    kw.setdefault("m2_min", 55)
    return SitemapZoeker(client or StubClient(), haal=web or StubWeb(), pauze=0, **kw)


ROBOTS_URL = "https://www.funda.nl/robots.txt"
INDEX_URL = "https://www.funda.nl/sitemap_index.xml/"
KOOP1_URL = "https://www.funda.nl/sitemap-detail-koop1.xml"
KOOP2_URL = "https://www.funda.nl/sitemap-detail-koop2.xml"


def tijdelijk(naam: str) -> Path:
    tmp = Path(f".test_tmp_sitemap_{naam}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    return tmp


def test_ontleden() -> bool:
    print("ontleden")
    soort, items = ontleed_sitemap(INDEX)
    ok = check("index herkend", soort == "index" and len(items) == 4)
    ok &= check("lastmod per kind", items[0][1] == "2026-11-06T04:59:19+01:00")
    soort, items = ontleed_sitemap(KOOP1)
    ok &= check("urlset herkend", soort == "urlset" and len(items) == 4)
    ok &= check("sitemap uit robots", sitemap_uit_robots(ROBOTS) == "https://www.funda.nl/sitemap_index.xml/")
    ok &= check("robots staat /detail/ toe", not detail_verboden(ROBOTS))
    ok &= check("robots Disallow / telt", detail_verboden("User-agent: *\nDisallow: /\n"))
    ok &= check("Disallow voor andere bot telt niet",
                not detail_verboden("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /detail/\n"))
    w = woning_uit_url(f"{B}/den-haag/appartement-draaistraat-4/80024814/")
    ok &= check("woning uit URL", w == {"pad": "/detail/koop/den-haag/appartement-draaistraat-4/80024814/",
                                        "stad": "den-haag", "slug": "appartement-draaistraat-4",
                                        "type": "appartement", "url_id": "80024814"})
    ok &= check("huur-URL is geen koopwoning", woning_uit_url("https://www.funda.nl/detail/huur/x/y/12345678/") is None)
    return ok


def test_kandidaten() -> bool:
    print("kandidaten")
    _s, items1 = ontleed_sitemap(KOOP1)
    _s, items2 = ontleed_sitemap(KOOP2)
    k = kandidaten_uit(items1 + items2, ["den-haag", "voorburg"])
    ids = [x["url_id"] for x in k]
    ok = check("alleen doelsteden, geen huis/parkeren", sorted(ids) == ["44546400", "44664520", "80024814"])
    ok &= check("nieuwste lastmod eerst", ids == ["80024814", "44664520", "44546400"])
    # Onbekend type gaat door (afwijslijst, geen toestaanlijst).
    _s, items = ontleed_sitemap(urlset((f"{B}/den-haag/maisonnette-z-3/44000001/", "2026-11-01")))
    ok &= check("onbekend type doorgelaten", len(kandidaten_uit(items, ["den-haag"])) == 1)
    # Dubbel in twee sitemaps: de nieuwste lastmod wint.
    dubbel = [(f"{B}/den-haag/appartement-a-1/44000002/", "2026-11-01"),
              (f"{B}/den-haag/appartement-a-1/44000002/", "2026-11-03")]
    k = kandidaten_uit(dubbel, ["den-haag"])
    ok &= check("dubbel: één kandidaat, nieuwste lastmod", len(k) == 1 and k[0]["lastmod"] == "2026-11-03")
    return ok


def test_doelmarkt() -> bool:
    print("doelmarkt")
    ok = check("binnen", in_doelmarkt({"price": 299500, "living_area": 77, "status": "available"}, 230_000, 310_000, 55))
    ok &= check("te duur", not in_doelmarkt({"price": 950000, "living_area": 77}, 230_000, 310_000, 55))
    ok &= check("te klein", not in_doelmarkt({"price": 250000, "living_area": 40}, 230_000, 310_000, 55))
    ok &= check("verkocht", not in_doelmarkt({"price": 250000, "living_area": 60, "status": "sold"}, 230_000, 310_000, 55))
    ok &= check("prijs onbekend: doorlaten", in_doelmarkt({"price": None, "living_area": 60}, 230_000, 310_000, 55))
    return ok


def test_dropin() -> bool:
    print("drop-in")
    web, client = StubWeb(), StubClient()
    z = zoeker(web, client)
    alles = z.search_listing(location="x", price_min=230_000, price_max=310_000, area_min=55)
    titels = sorted(r.data["title"] for r in alles)
    ok = check("in doelmarkt teruggegeven", titels == ["Draaistraat 4", "Rodelaan 379"])
    ok &= check("sitemaps één keer opgehaald (robots, index, 2 koop)", len(web.calls) == 4)
    ok &= check("huur/nieuwbouw niet opgehaald", not any("huur" in u or "nieuwbouw" in u for u in web.calls))
    ok &= check("3 detail-calls (te dure woning kostte er ook één)", len(client.calls) == 3)
    band = z.search_listing(price_min=290_000, price_max=310_000, area_min=55)
    ok &= check("prijsband filtert", [r.data["title"] for r in band] == ["Draaistraat 4"])
    ok &= check("geen nieuwe calls voor tweede band", len(web.calls) == 4 and len(client.calls) == 3)
    ok &= check("pagina 1 is leeg", z.search_listing(page=1) == [])
    ok &= check("bron gemarkeerd", all(r.data["_bron"] == "sitemap" for r in alles))
    ok &= check("get_listing uit cache", z.get_listing(1001).data["title"] == "Draaistraat 4"
                and len(client.calls) == 3)
    ok &= check("onbekende methode naar client", z.get_price_history("x") == [{"prijs": 1}])
    try:
        z.search_listing(offering_type="rent")
        ok &= check("huur geweigerd", False)
    except ValueError:
        ok &= check("huur geweigerd", True)
    return ok


def test_cache() -> bool:
    print("cache over runs")
    tmp = Path(".test_tmp_sitemap")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    pad = tmp / "cache.json"
    try:
        c1 = StubClient()
        zoeker(client=c1, cache_pad=pad).search_listing()
        opgeslagen = json.loads(pad.read_text(encoding="utf-8"))["woningen"]
        ok = check("cache bevat alle verrijkte woningen", sorted(opgeslagen) == ["44546400", "44664520", "80024814"])
        ok &= check("cache bewaart de filtervelden, niet de uitkomst",
                    opgeslagen["44664520"]["velden"]["price"] == 950000
                    and "doel" not in opgeslagen["44664520"])

        # Run 2, zelfde sitemaps: de te dure woning kost geen call meer, de twee
        # in de doelmarkt worden vers opgehaald.
        c2 = StubClient()
        z2 = zoeker(client=c2, cache_pad=pad)
        r2 = z2.search_listing()
        ok &= check("run 2: alleen doelmarkt ververst", len(c2.calls) == 2 and len(r2) == 2)
        ok &= check("run 2: statistiek klopt", z2.statistiek["uit_cache_buiten_doel"] == 1
                    and z2.statistiek["ververst"] == 2 and z2.statistiek["verkend"] == 0)

        # Run 2b: ruimere prijsgrens. Geen nieuwe verkenning nodig: de cache weet
        # de prijs al, dus de dure woning gaat meteen mee in de verversing.
        c2b = StubClient()
        r2b = zoeker(client=c2b, cache_pad=pad, prijs_max=1_000_000).search_listing()
        ok &= check("run 2b: gewijzigde grens geldt meteen voor de cache",
                    len(c2b.calls) == 3 and len(r2b) == 3)

        # Run 2c: buurtfilter van de aanroeper wijst een woning af. Die kost dan
        # geen verversing meer, en komt niet in de resultaten.
        details = {k: {**v, "neighbourhood": "Moerwijk" if k == "44546400" else "Centrum"}
                   for k, v in DETAILS.items()}
        zoeker(client=StubClient(details), cache_pad=pad.with_name("c2.json")).search_listing()
        c2c = StubClient(details)
        r2c = zoeker(client=c2c, cache_pad=pad.with_name("c2.json"),
                     overslaan=lambda d: d.get("neighbourhood") == "Moerwijk").search_listing()
        ok &= check("run 2c: afgewezen buurt niet ververst en niet teruggegeven",
                    len(c2c.calls) == 1 and [x.data["title"] for x in r2c] == ["Draaistraat 4"])

        # Run 3: prijsdaling op de dure woning -> nieuwe lastmod -> opnieuw bekeken.
        nieuw_koop2 = KOOP2.replace("2026-11-06T00:00:15+01:00", "2026-11-07T09:00:00+01:00")
        details = dict(DETAILS)
        details["44664520"] = {**DETAILS["44664520"], "price": 300000, "living_area": 80}
        # Funda zet dan ook een nieuwe lastmod in de index; anders zou de vorige
        # kandidatenlijst uit de cache worden hergebruikt (zie test_index_cache).
        web3 = StubWeb()
        web3.pagina["https://www.funda.nl/sitemap_index.xml/"] = index_met("2026-11-07T04:59")
        web3.pagina["https://www.funda.nl/sitemap-detail-koop2.xml"] = nieuw_koop2
        c3 = StubClient(details)
        r3 = zoeker(web3, c3, cache_pad=pad).search_listing()
        ok &= check("run 3: gewijzigde lastmod opnieuw verrijkt en nu in doelmarkt",
                    len(c3.calls) == 3 and len(r3) == 3)

        # Run 4: woning uit de sitemap verdwenen -> uit de cache gesnoeid.
        web4 = StubWeb()
        web4.pagina["https://www.funda.nl/sitemap_index.xml/"] = index_met("2026-11-08T04:59")
        web4.pagina["https://www.funda.nl/sitemap-detail-koop1.xml"] = urlset(
            (f"{B}/den-haag/appartement-draaistraat-4/80024814/", "2026-11-06T01:00:09+01:00"))
        web4.pagina["https://www.funda.nl/sitemap-detail-koop2.xml"] = nieuw_koop2
        zoeker(web4, StubClient(details), cache_pad=pad).search_listing()
        opgeslagen = json.loads(pad.read_text(encoding="utf-8"))["woningen"]
        ok &= check("run 4: verdwenen woning gesnoeid", "44546400" not in opgeslagen)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def test_budget() -> bool:
    print("budget en achterstand")
    c = StubClient()
    z = zoeker(client=c, max_verkennen=1)
    r = z.search_listing()
    ok = check("maar één verkennende call", len(c.calls) == 1)
    ok &= check("nieuwste eerst verkend", r and r[0].data["title"] == "Draaistraat 4")
    ok &= check("achterstand gemeld", z.statistiek["achterstand"] == 2)
    return ok


def test_fouten() -> bool:
    print("fouten")
    # Index geeft 403: luid falen, en niet per prijsband opnieuw proberen.
    web = StubWeb()
    web.pagina["https://www.funda.nl/sitemap_index.xml/"] = RuntimeError("status 403")
    z = zoeker(web)
    fouten = 0
    for _ in range(3):
        try:
            z.search_listing()
        except RuntimeError:
            fouten += 1
    ok = check("fout bij elke aanroep", fouten == 3)
    ok &= check("index maar één keer geprobeerd",
                web.calls.count("https://www.funda.nl/sitemap_index.xml/") == 1)

    # Bot-controle in plaats van XML.
    web = StubWeb()
    web.pagina["https://www.funda.nl/sitemap-detail-koop1.xml"] = (
        "<!doctype html><html><title>Je bent bijna op de pagina die je zoekt [funda]</title></html>")
    try:
        zoeker(web).search_listing()
        ok &= check("HTML i.p.v. XML is een fout", False)
    except RuntimeError:
        ok &= check("HTML i.p.v. XML is een fout", True)

    # robots.txt kapot: val terug op de bekende index-URL.
    web = StubWeb()
    web.pagina["https://www.funda.nl/robots.txt"] = RuntimeError("status 403")
    ok &= check("robots kapot: terugval werkt", len(zoeker(web).search_listing()) == 2)

    # robots.txt verbiedt /detail/: niet meedoen.
    web = StubWeb()
    web.pagina["https://www.funda.nl/robots.txt"] = "User-agent: *\nDisallow: /detail/\n"
    try:
        zoeker(web).search_listing()
        ok &= check("robots-verbod respecteren", False)
    except RuntimeError:
        ok &= check("robots-verbod respecteren", True)

    # Geen woningen in de doelsteden: dat is een kapotte bron, geen lege markt.
    web = StubWeb()
    web.pagina["https://www.funda.nl/sitemap-detail-koop1.xml"] = urlset(
        (f"{B}/amsterdam/appartement-a-1/44000003/", "2026-11-01"))
    web.pagina["https://www.funda.nl/sitemap-detail-koop2.xml"] = urlset(
        (f"{B}/utrecht/appartement-b-2/44000004/", "2026-11-01"))
    try:
        zoeker(web).search_listing()
        ok &= check("nul kandidaten is een fout", False)
    except RuntimeError:
        ok &= check("nul kandidaten is een fout", True)

    # Eén detail-call mislukt: die woning valt weg, de rest komt door.
    client = StubClient()
    del client.details["44546400"]
    r = zoeker(client=client).search_listing()
    ok &= check("mislukte detail-call slaat alleen die woning over",
                [x.data["title"] for x in r] == ["Draaistraat 4"])

    # bereikbaar(): index met koop-sitemaps.
    ok &= check("bereikbaar bij werkende index", zoeker().bereikbaar())
    web = StubWeb()
    web.pagina["https://www.funda.nl/sitemap_index.xml/"] = RuntimeError("status 403")
    ok &= check("niet bereikbaar bij 403", not zoeker(web).bereikbaar())
    return ok


def test_index_cache() -> bool:
    """Stap e: de koop-sitemaps alleen opnieuw ophalen als de index dat zegt."""
    print("index ongewijzigd: koop-sitemaps niet opnieuw ophalen")
    tmp = tijdelijk("index")
    pad = tmp / "cache.json"
    try:
        web1 = StubWeb()
        z1 = zoeker(web1, cache_pad=pad)
        r1 = z1.search_listing()
        ok = check("run 1: robots, index en twee koop-sitemaps", len(web1.calls) == 4)
        ok &= check("run 1: statistiek zegt opgehaald",
                    z1.statistiek["index_ongewijzigd"] is False
                    and z1.statistiek["koop_sitemaps_opgehaald"] == 2)
        index = json.loads(pad.read_text(encoding="utf-8"))["index"]
        ok &= check("cache bewaart index-kenmerk en kandidaten",
                    bool((index.get("kenmerk") or {}).get("lastmod"))
                    and len(index.get("kandidaten") or []) == 3)

        web2 = StubWeb()
        z2 = zoeker(web2, cache_pad=pad)
        r2 = z2.search_listing()
        ok &= check("run 2: alleen robots en index", web2.calls == [ROBOTS_URL, INDEX_URL])
        ok &= check("run 2: zelfde woningen",
                    sorted(x.data["title"] for x in r2) == sorted(x.data["title"] for x in r1))
        ok &= check("run 2: kandidaten uit de cache, zelfde volgorde",
                    [k["url_id"] for k in z2.kandidaten] == [k["url_id"] for k in z1.kandidaten])
        ok &= check("run 2: statistiek", z2.statistiek["index_ongewijzigd"] is True
                    and z2.statistiek["sitemap_verzoeken"] == 2
                    and z2.statistiek["urls"] == z1.statistiek["urls"])

        # Gemeten op 6 nov 2026: de index geeft per verzoek soms een seconde
        # verschil in de lastmod van een kind (koop3 04:59:26 en 04:59:27, zelfde
        # ETag). Dat is dezelfde snapshot en mag dus niet tot ophalen leiden.
        jitter = StubWeb()
        jitter.pagina[INDEX_URL] = INDEX.replace("04:59:23", "04:59:24")
        zj = zoeker(jitter, cache_pad=pad)
        zj.search_listing()
        ok &= check("een seconde verschil in de index: zelfde snapshot",
                    jitter.calls == [ROBOTS_URL, INDEX_URL] and zj.statistiek["index_ongewijzigd"])
        bewaard = json.loads(pad.read_text(encoding="utf-8"))["index"]["kenmerk"]["lastmod"]
        ok &= check("opgeslagen kenmerk blijft staan (speling stapelt niet op)",
                    bewaard.get(KOOP2_URL) == "2026-11-06T04:59:23+01:00")

        web2b = StubWeb()
        z2b = zoeker(web2b, cache_pad=pad)
        ok &= check("bereikbaar() en zoeken delen robots en index",
                    z2b.bereikbaar() and z2b.search_listing() is not None and len(web2b.calls) == 2)

        web3 = StubWeb()
        web3.pagina[INDEX_URL] = index_met("2026-11-07T04:59")
        zoeker(web3, cache_pad=pad).search_listing()
        ok &= check("nieuwe index-lastmod: koop-sitemaps opnieuw", len(web3.calls) == 4)

        web4 = StubWeb()
        web4.pagina[INDEX_URL] = index_met("2026-11-07T04:59")
        zoeker(web4, cache_pad=pad, steden=["den-haag"]).search_listing()
        ok &= check("andere steden: kandidatenlijst geldt niet meer", len(web4.calls) == 4)

        # Index zonder <lastmod>: dan telt de Last-Modified-header.
        zonder = re.sub(r"<lastmod>[^<]*</lastmod>", "", INDEX)

        def web_lm(waarde):
            w = StubWeb()
            w.pagina[INDEX_URL] = (zonder, {"Last-Modified": waarde} if waarde else {})
            return w

        pad2 = tmp / "c2.json"
        w5, w6 = web_lm("Fri, 06 Nov 2026 03:59:30 GMT"), web_lm("Fri, 06 Nov 2026 03:59:30 GMT")
        zoeker(w5, cache_pad=pad2).search_listing()
        zoeker(w6, cache_pad=pad2).search_listing()
        ok &= check("zonder lastmod telt Last-Modified", len(w5.calls) == 4 and len(w6.calls) == 2)
        w7 = web_lm("Sat, 07 Nov 2026 03:59:30 GMT")
        zoeker(w7, cache_pad=pad2).search_listing()
        ok &= check("andere Last-Modified: opnieuw", len(w7.calls) == 4)

        # Geen van beide: niet te bepalen of er iets veranderde, dus ophalen.
        pad3 = tmp / "c3.json"
        w8, w9 = web_lm(None), web_lm(None)
        zoeker(w8, cache_pad=pad3).search_listing()
        zoeker(w9, cache_pad=pad3).search_listing()
        ok &= check("geen lastmod en geen header: altijd ophalen",
                    len(w8.calls) == 4 and len(w9.calls) == 4)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def test_straal_in_cache() -> bool:
    """Stap c: coördinaten in de cache, zodat een verre woning maar één call kost."""
    print("coördinaten in de cache en afstand via overslaan")
    tmp = tijdelijk("straal")
    pad = tmp / "cache.json"
    try:
        details = {k: dict(v) for k, v in DETAILS.items()}
        details["80024814"].update(latitude=52.080, longitude=4.310)   # dichtbij
        details["44546400"].update(latitude=52.070, longitude=4.450)   # ver weg

        def ver_weg(d):
            # Onbekend = doorlaten: zonder coördinaten geen reden om af te wijzen.
            return d.get("longitude") is not None and d["longitude"] > 4.40

        c1 = StubClient(details)
        r1 = zoeker(client=c1, cache_pad=pad, overslaan=ver_weg).search_listing()
        ok = check("run 1: verre woning opgehaald maar niet teruggegeven",
                   len(c1.calls) == 3 and [x.data["title"] for x in r1] == ["Draaistraat 4"])
        velden = json.loads(pad.read_text(encoding="utf-8"))["woningen"]["44546400"]["velden"]
        ok &= check("coördinaten in de cache",
                    velden.get("latitude") == 52.070 and velden.get("longitude") == 4.450)
        c2 = StubClient(details)
        z2 = zoeker(client=c2, cache_pad=pad, overslaan=ver_weg)
        z2.search_listing()
        ok &= check("run 2: verre woning kost geen call meer",
                    len(c2.calls) == 1 and "44546400" not in " ".join(c2.calls)
                    and z2.statistiek["uit_cache_buiten_doel"] == 2)

        # Zonder coördinaten: doorlaten en dus elke run vers ophalen.
        zonder = {k: dict(v) for k, v in DETAILS.items()}
        pad2 = tmp / "c2.json"
        zoeker(client=StubClient(zonder), cache_pad=pad2, overslaan=ver_weg).search_listing()
        c3 = StubClient(zonder)
        r3 = zoeker(client=c3, cache_pad=pad2, overslaan=ver_weg).search_listing()
        ok &= check("onbekende coördinaten: doorgelaten",
                    sorted(x.data["title"] for x in r3) == ["Draaistraat 4", "Rodelaan 379"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def test_pool_oordeel() -> bool:
    """Stap b: wat de zoeker deze run met een woning deed, voor de pool."""
    print("pool-oordeel per woning")
    tmp = tijdelijk("pool")
    pad = tmp / "cache.json"
    try:
        zoeker(cache_pad=pad).search_listing()   # run 1 vult de cache

        nieuw = (f"{B}/den-haag/appartement-nieuwstraat-1/44000010/", "2026-11-06T22:00:00+01:00")
        web = StubWeb()
        web.pagina[INDEX_URL] = index_met("2026-11-07T04:59")
        web.pagina[KOOP1_URL] = KOOP1.replace(
            "</urlset>", f"<url><loc>{nieuw[0]}</loc><lastmod>{nieuw[1]}</lastmod></url>\n</urlset>")
        client = StubClient()
        del client.details["44546400"]   # deze run onbereikbaar
        client.details["44000010"] = {"global_id": 1010, "tiny_id": "44000010", "title": "Nieuwstraat 1",
                                      "city": "Den Haag", "price": 280000, "living_area": 60,
                                      "status": "available"}
        z = zoeker(web, client, cache_pad=pad, max_verkennen=0)
        z.search_listing()
        oordeel = z.pool_oordeel
        ok = check("ververst = opgehaald",
                   oordeel(f"{B}/den-haag/appartement-draaistraat-4/80024814/") == "opgehaald")
        ok &= check("pad zonder slash werkt ook",
                    oordeel("/detail/koop/den-haag/appartement-draaistraat-4/80024814") == "opgehaald")
        ok &= check("global_id werkt ook", oordeel("1001") == "opgehaald")
        ok &= check("op cache overgeslagen",
                    oordeel(f"{B}/den-haag/appartement-koningin-emmakade-185/44664520/") == "overgeslagen")
        ok &= check("mislukt deze run",
                    oordeel(f"{B}/voorburg/appartement-rodelaan-379/44546400/") == "mislukt")
        ok &= check("nog niet verkend = achterstand", oordeel(nieuw[0]) == "achterstand")
        ok &= check("niet (meer) in de sitemap",
                    oordeel(f"{B}/den-haag/appartement-weg-9/44000099/") == "niet_in_sitemap")
        ok &= check("andere stad: onbekend", oordeel(f"{B}/rijswijk/appartement-y-2/44660000/") == "onbekend")
        ok &= check("huis valt niet onder de kandidaten: onbekend",
                    oordeel(f"{B}/den-haag/huis-x-1/44000098/") == "onbekend")
        ok &= check("global_id zonder URL: onbekend", oordeel("1234567") == "onbekend")
        ok &= check("vóór het zoeken: onbekend", zoeker().pool_oordeel(nieuw[0]) == "onbekend")

        n = len(client.calls)
        z.get_listing("https://www.funda.nl/detail/koop/den-haag/appartement-draaistraat-4/80024814/")
        ok &= check("get_listing op URL komt uit wat het zoeken ophaalde", len(client.calls) == n)

        # De pool haalt de woning uit de achterstand zelf op en legt hem vast.
        listing = client.get_listing(nieuw[0])
        ok &= check("neem_op legt vast", z.neem_op(listing) and oordeel(nieuw[0]) == "opgehaald")
        ok &= check("niet dubbel vastleggen", not z.neem_op(listing))
        z.bewaar_cache()
        opgeslagen = json.loads(pad.read_text(encoding="utf-8"))["woningen"]
        ok &= check("in de cache met de lastmod uit de sitemap",
                    opgeslagen.get("44000010", {}).get("lastmod") == nieuw[1])
        web3 = StubWeb(dict(web.pagina))
        z3 = zoeker(web3, StubClient(client.details), cache_pad=pad, max_verkennen=0)
        z3.search_listing()
        ok &= check("volgende run: niets meer te verkennen",
                    z3.statistiek["achterstand"] == 0 and z3.statistiek["verkend"] == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def test_meting() -> bool:
    """Stap g: tellen of een gewijzigde lastmod iets zegt over prijs of status."""
    print("meting lastmod")
    tmp = tijdelijk("meting")
    pad = tmp / "cache.json"
    try:
        zoeker(cache_pad=pad).search_listing()
        # Nieuwe snapshot: Emmakade heeft een nieuwe lastmod en een andere prijs,
        # Rodelaan is uit de sitemap verdwenen, en Draaistraat staat onder bod
        # zonder dat zijn lastmod veranderde.
        web = StubWeb()
        web.pagina[INDEX_URL] = index_met("2026-11-07T04:59")
        web.pagina[KOOP1_URL] = urlset(
            (f"{B}/den-haag/appartement-draaistraat-4/80024814/", "2026-11-06T01:00:09+01:00"))
        web.pagina[KOOP2_URL] = KOOP2.replace("2026-11-06T00:00:15+01:00", "2026-11-07T09:00:00+01:00")
        details = {k: dict(v) for k, v in DETAILS.items()}
        details["44664520"]["price"] = 899000
        details["80024814"]["characteristics"] = {"Status": "Onder bod"}
        z = zoeker(web, StubClient(details), cache_pad=pad)
        z.search_listing()
        m = z.meting
        ok = check("gewijzigde lastmod geteld", m["lastmod_gewijzigd"] == 1
                   and m["lastmod_gewijzigd_opgehaald"] == 1 and m["lastmod_gewijzigd_andere_prijs"] == 1)
        # Run 1 had nog geen statuskenmerk; een cache zonder kenmerk telt alleen
        # op `status`, dus dit is nog geen statuswijziging.
        ok &= check("oude cache zonder kenmerk: geen valse statuswijziging",
                    m["lastmod_gelijk_opgehaald"] == 1 and m["lastmod_gelijk_andere_status"] == 0)
        ok &= check("verdwenen woning geteld", z.statistiek["uit_sitemap_gesnoeid"] == 1)
        details["80024814"]["characteristics"] = {"Status": "Beschikbaar"}
        z2 = zoeker(web, StubClient(details), cache_pad=pad)
        z2.search_listing()
        ok &= check("statuswijziging bij ongewijzigde lastmod geteld",
                    z2.meting["lastmod_gelijk_andere_status"] == 1
                    and z2.meting["lastmod_gelijk_andere_prijs"] == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def test_detail_dicht() -> bool:
    print("detail-endpoint dicht")
    rijen = [(f"{B}/den-haag/appartement-straat-{i}/4400010{i}/", f"2026-11-0{i}T10:00:00+01:00")
             for i in range(1, 9)]
    web = StubWeb()
    web.pagina[KOOP1_URL] = urlset(*rijen)
    web.pagina[KOOP2_URL] = urlset(rijen[0])

    class Dicht(StubClient):
        def get_listing(self, ident):
            self.calls.append(str(ident))
            raise RuntimeError("geen werkende vingerafdruk")

    client = Dicht()
    z = zoeker(web, client)
    try:
        z.search_listing()
        ok = check("vijf mislukkingen zonder succes is een fout", False)
    except RuntimeError as exc:
        ok = check("vijf mislukkingen zonder succes is een fout",
                   "Detail-endpoint werkt niet" in str(exc) and "vingerafdruk" in str(exc))
    ok &= check("gestopt na vijf calls", len(client.calls) == 5)
    try:
        z.search_listing(price_min=1)
    except RuntimeError:
        pass
    ok &= check("tweede aanroep doet geen nieuwe calls", len(client.calls) == 5)

    # bereikbaar() onthoudt de oorzaak en zoekt daarna niet opnieuw.
    web = StubWeb()
    web.pagina[INDEX_URL] = RuntimeError("status 403")
    z = zoeker(web)
    ok &= check("niet bereikbaar, met reden", not z.bereikbaar() and "403" in (z.reden or ""))
    n = len(web.calls)
    try:
        z.search_listing()
        ok &= check("zoeken na onbereikbaar faalt", False)
    except RuntimeError:
        ok &= check("zoeken na onbereikbaar faalt zonder nieuw verzoek", len(web.calls) == n)
    return ok


def test_gzip() -> bool:
    print("gzip")
    # .xml.gz zonder content-encoding: de body zelf is gzip.
    ruw = gzip.compress(KOOP1.encode("utf-8"))

    class Resp:
        status_code = 200
        content = ruw

    class Sessie:
        def get(self, *_a, **_k):
            return Resp()

    z = SitemapZoeker(StubClient(), pauze=0)
    z._sessie = Sessie()
    return check("gzip-body uitgepakt", "<urlset" in z._haal("https://example.invalid/x.xml.gz"))


def main() -> int:
    resultaten = [
        test_ontleden(), test_kandidaten(), test_doelmarkt(), test_dropin(),
        test_cache(), test_budget(), test_fouten(), test_gzip(),
        test_index_cache(), test_straal_in_cache(), test_pool_oordeel(), test_meting(),
        test_detail_dicht(),
    ]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
