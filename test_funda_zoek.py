"""Offline tests voor de veiligheidschecks in funda_zoek.main(). Geen netwerk.

Deze checks bestaan omdat een stukke zoekmethode er precies hetzelfde uitziet als
een lege markt, en een lege run het gevulde rapport zou overschrijven.

Draaien: python test_funda_zoek.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import types
from collections import Counter
from datetime import datetime
from pathlib import Path

# Deze tests gaan over de checks in main(), niet over de zoekmethode. Vastzetten
# op 'api' houdt ze offline: 'auto' zou bij een falende API de HTML-route pakken
# en dan alsnog het netwerk op willen.
os.environ["FUNDA_ZOEK_METHODE"] = "api"

SCRATCH = Path(__file__).parent / ".test_tmp"


class StubListing:
    def __init__(self, data):
        self.data = data


def maak_stub_funda(zoek_gedrag, details=None, calls=None):
    """Installeer een nep-funda-module vóór funda_zoek geïmporteerd wordt.

    Met `details` (per tiny_id) zoekt get_listing de woning op aan het nummer in
    de URL of aan het global_id, en schrijft elke aanroep in `calls`.
    """
    mod = types.ModuleType("funda")
    per_id = {}
    for tiny, d in (details or {}).items():
        per_id[str(tiny)] = d
        if d.get("global_id"):
            per_id[str(d["global_id"])] = d

    class F:
        def __init__(self, *a, **k):
            self.n = 0

        def search_listing(self, *a, **k):
            self.n += 1
            return zoek_gedrag(self.n)

        def get_listing(self, ident):
            if details is not None:
                if calls is not None:
                    calls.append(str(ident))
                sleutel = str(ident).rstrip("/").split("/")[-1]
                if sleutel not in per_id:
                    raise LookupError(f"Listing {ident} not found")
                return StubListing(dict(per_id[sleutel]))
            return StubListing({
                "global_id": "g1", "city": "Den Haag", "neighbourhood": "Bomenbuurt",
                "price": 250000, "living_area": 60, "title": "Teststraat 1",
                "description": "Licht appartement op de derde verdieping.",
            })

    mod.Funda = F
    sys.modules["funda"] = mod
    sys.modules.pop("funda_zoek", None)

    import funda_zoek as fz

    SCRATCH.mkdir(exist_ok=True)
    fz.STATE_FILE = SCRATCH / "seen.json"
    fz.LOG_FILE = SCRATCH / "log.txt"
    fz.TRACKING_FILE = SCRATCH / "tracking.json"
    fz.SUMMARY_FILE = SCRATCH / "summary.json"
    fz.BLACKLIST_FILE = SCRATCH / "blacklist.json"
    fz.THUIS_CACHE = SCRATCH / "thuis.json"
    fz.SITEMAP_CACHE_FILE = SCRATCH / "sitemap.json"
    # main() eindigt met auto_push(): git add/commit/push. In een werkkopie met
    # gestagede wijzigingen commit dat die wijzigingen (de check kijkt naar alles
    # wat gestaged is, niet alleen docs/). Tests mogen nooit committen of pushen.
    fz.auto_push = lambda: None
    # Geen Nominatim in offline tests: zonder thuiscoördinaten slaat het
    # afstandsfilter over. Tests die het filter willen, zetten dit zelf.
    fz._THUIS["v"] = None
    for p in (fz.STATE_FILE, fz.TRACKING_FILE, fz.SITEMAP_CACHE_FILE):
        p.unlink(missing_ok=True)
    return fz


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return voorwaarde


def draai(fz) -> tuple[int | None, bool]:
    """Draai main() met een rapport-spion. Geeft (exitcode of None, rapport_gedraaid)."""
    gedraaid = {"v": False}

    def rapport(_client, _goed, _nieuw):
        gedraaid["v"] = True
        return Path("rapport.html")

    fz.genereer_rapport = rapport
    try:
        fz.main()
        return None, gedraaid["v"]
    except SystemExit as exc:
        return exc.code, gedraaid["v"]


def test_alles_faalt() -> bool:
    print("test: elke zoek-call faalt (API dicht)")

    def gedrag(_n):
        raise RuntimeError("Search failed (status 401)")

    fz = maak_stub_funda(gedrag)
    code, gedraaid = draai(fz)
    ok = check("stopt met exit 2", code == 2, str(code))
    ok &= check("rapport niet overschreven", not gedraaid)
    return ok


def test_stille_lege_oogst() -> bool:
    print("test: alle calls slagen maar leveren niets op (stukke parser)")
    # Dit is de faalmodus van de HTML-route: funda wijzigt de markup, de pagina
    # geeft netjes 200 terug en de parser vindt nul kaarten. Geen exception, dus
    # de 'alles mislukt'-check grijpt hier niet.
    fz = maak_stub_funda(lambda _n: [])
    code, gedraaid = draai(fz)
    ok = check("stopt met exit 2", code == 2, str(code))
    ok &= check("rapport niet overschreven", not gedraaid)
    return ok


def test_normale_run() -> bool:
    print("test: gewone run met resultaten")

    def gedrag(n):
        if n == 1:
            return [StubListing({
                "global_id": "g1", "city": "Den Haag", "neighbourhood": "Bomenbuurt",
                "price": 250000, "living_area": 60, "title": "Teststraat 1",
            })]
        return []

    fz = maak_stub_funda(gedrag)
    code, gedraaid = draai(fz)
    ok = check("geen afbreking", code is None, str(code))
    ok &= check("rapport gegenereerd", gedraaid)
    return ok


def test_prijs_onbekend() -> bool:
    """Een woning zonder vraagprijs mag de run niet laten crashen.

    Gevonden in de e2e-run van de sitemaproute (run 42271742515): de sitemap- en
    mailroute laten een onbekende prijs bewust door, en sort() kreeg toen None
    naast een getal (TypeError). Het rapport bleef daardoor ongeschreven.
    """
    print("test: woning met prijs op aanvraag (price=None)")

    def gedrag(n):
        if n == 1:
            return [
                StubListing({"global_id": "g1", "city": "Den Haag", "neighbourhood": "Bomenbuurt",
                             "price": 250000, "living_area": 60, "title": "Teststraat 1"}),
                StubListing({"global_id": "g2", "city": "Den Haag", "neighbourhood": "Bomenbuurt",
                             "price": None, "living_area": 70, "title": "Teststraat 2"}),
            ]
        return []

    fz = maak_stub_funda(gedrag)
    gezien = {}

    def rapport(_client, goed, _nieuw):
        gezien["titels"] = sorted(d.get("title") for d in goed)
        return Path("rapport.html")

    fz.genereer_rapport = rapport
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fz.main()
        code = None
    except SystemExit as exc:
        code = exc.code
    ok = check("geen afbreking", code is None, str(code))
    ok &= check("beide woningen in het rapport",
                gezien.get("titels") == ["Teststraat 1", "Teststraat 2"], str(gezien.get("titels")))
    return ok


def test_auto_keten() -> bool:
    """'auto' loopt api -> html -> sitemap -> mail af en neemt de eerste die werkt."""
    print("test: auto kiest de eerste werkende zoekmethode")
    import funda_html_zoek as fhz
    import funda_sitemap_zoek as fsz

    fz = maak_stub_funda(lambda _n: [])
    ok = True
    volgorde: list[str] = []

    class ApiOk:
        def search_listing(self, *a, **k):
            volgorde.append("api")
            return []

    class ApiDicht:
        def search_listing(self, *a, **k):
            volgorde.append("api")
            raise RuntimeError("Search failed (status 401)")

    class StubHtml:
        bereik = False

        def __init__(self, *a, **k):
            self.reden = None

        def bereikbaar(self):
            volgorde.append("html")
            if not StubHtml.bereik:
                self.reden = "Zoekpagina gaf status 403"
            return StubHtml.bereik

    class StubSitemap:
        bereik = False
        laatste = None

        def __init__(self, client, **kw):
            self.kw = kw
            self.reden = None
            StubSitemap.laatste = self

        def bereikbaar(self):
            volgorde.append("sitemap")
            if not StubSitemap.bereik:
                self.reden = "https://www.funda.nl/sitemap_index.xml/ gaf status 403"
            return StubSitemap.bereik

    mail = {"woningen": []}

    def stub_mail():
        volgorde.append("mail")
        if not mail["woningen"]:
            fz._MAIL_REDEN["v"] = "Gmail weigert de login (AUTHENTICATIONFAILED)"
        return list(mail["woningen"])

    def kies(client):
        volgorde.clear()
        uit = io.StringIO()
        with contextlib.redirect_stdout(uit):
            zoeker, methode = fz.kies_zoeker(client)
        return zoeker, methode, uit.getvalue()

    origineel = (fhz.HtmlZoeker, fsz.SitemapZoeker, fz._woningen_uit_mailbox)
    os.environ["FUNDA_ZOEK_METHODE"] = "auto"
    try:
        fhz.HtmlZoeker, fsz.SitemapZoeker = StubHtml, StubSitemap
        fz._woningen_uit_mailbox = stub_mail
        mail["woningen"] = [("/detail/koop/x/y/44500000/", "44500000")]

        # 1. API antwoordt: dan niets anders proberen.
        _, methode, _ = kies(ApiOk())
        ok &= check("API werkt -> api, verder niets geprobeerd",
                    methode == "api" and volgorde == ["api"], f"{methode} {volgorde}")

        # 2. API dicht, zoekpagina laat door.
        StubHtml.bereik = True
        _, methode, _ = kies(ApiDicht())
        ok &= check("API dicht, HTML open -> html, sitemaps niet gevraagd",
                    methode == "html" and volgorde == ["api", "html"], f"{methode} {volgorde}")

        # 3. API en zoekpagina dicht, sitemaps open: sitemap, en de mail blijft
        # ongemoeid (terugval, geen extra IMAP-login).
        StubHtml.bereik, StubSitemap.bereik = False, True
        zoeker, methode, _ = kies(ApiDicht())
        ok &= check("API en HTML dicht, sitemaps open -> sitemap, mail niet gevraagd",
                    methode == "sitemap" and volgorde == ["api", "html", "sitemap"],
                    f"{methode} {volgorde}")
        ok &= check("sitemapzoeker kent de doelmarkt",
                    zoeker is StubSitemap.laatste and zoeker.kw["prijs_max"] == fz.PRIJS_MAX
                    and zoeker.kw["m2_min"] == fz.M2_MIN
                    and zoeker.kw["overslaan"] is fz._sitemap_overslaan
                    and zoeker.kw["max_verkennen"] == fz.SITEMAP_MAX_VERKENNEN)

        # 4. Ook de sitemaps dicht, maar er zitten woningen in de mail.
        StubSitemap.bereik = False
        _, methode, _ = kies(ApiDicht())
        ok &= check("alles behalve mail dicht -> mail",
                    methode == "mail" and volgorde == ["api", "html", "sitemap", "mail"],
                    f"{methode} {volgorde}")

        # 5. Niets werkt: luid falen met alle oorzaken, zonder nog iets op te halen.
        mail["woningen"] = []
        zoeker, methode, uitvoer = kies(ApiDicht())
        ok &= check("niets werkt -> geen", methode == "geen", methode)
        fout = [r for r in uitvoer.splitlines() if r.startswith("::error::")]
        ok &= check("één ::error met alle oorzaken",
                    len(fout) == 1 and all(w in fout[0] for w in
                                           ("401", "Zoekpagina gaf status 403", "sitemap_index",
                                            "AUTHENTICATIONFAILED")), str(fout))
        try:
            zoeker.search_listing(location="x")
            ok &= check("GeenBron faalt bij zoeken", False)
        except RuntimeError:
            ok &= check("GeenBron faalt bij zoeken", True)

        # 6. Afdwingen blijft werken, ook zonder dat er iets bereikbaar is.
        for gedwongen in ("api", "html", "sitemap", "mail"):
            os.environ["FUNDA_ZOEK_METHODE"] = gedwongen
            _, methode, _ = kies(ApiDicht())
            ok &= check(f"afgedwongen {gedwongen}", methode == gedwongen
                        and "api" not in volgorde and "html" not in volgorde
                        and "sitemap" not in volgorde, f"{methode} {volgorde}")

        # 7. Onzin in de config mag niet crashen; dat valt terug op auto.
        os.environ["FUNDA_ZOEK_METHODE"] = "telepathie"
        StubHtml.bereik = True
        _, methode, _ = kies(ApiDicht())
        ok &= check("onbekende methode valt terug op auto", methode == "html", methode)
    finally:
        fhz.HtmlZoeker, fsz.SitemapZoeker, fz._woningen_uit_mailbox = origineel
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
    return ok


def _sitemap_met(web, **extra):
    """Echte SitemapZoeker, maar met een nep-web en zonder pauzes."""
    import funda_sitemap_zoek as fsz

    echt = fsz.SitemapZoeker

    class Z(echt):
        def __init__(self, client, **kw):
            kw.update(haal=web, pauze=0, **extra)
            super().__init__(client, **kw)

    return echt, Z


def test_sitemapbron_faalt_luid() -> bool:
    """Exit 2 blijft gelden voor de sitemapbron: fout in de bron, nul kandidaten, niets werkt."""
    print("test: sitemapbron kapot = exit 2, rapport blijft staan")
    import funda_sitemap_zoek as fsz
    import test_funda_sitemap as ts

    ok = True
    gevallen = {
        "index geeft 403": {ts.INDEX_URL: RuntimeError("status 403")},
        "nul kandidaten": {ts.KOOP1_URL: ts.urlset((f"{ts.B}/utrecht/appartement-a-1/44000003/", "2026-11-01")),
                           ts.KOOP2_URL: ts.urlset((f"{ts.B}/utrecht/appartement-b-2/44000004/", "2026-11-01"))},
        "bot-controle i.p.v. XML": {ts.KOOP1_URL: "<!doctype html><html>Je bent bijna op de pagina</html>"},
    }
    for naam, afwijking in gevallen.items():
        fz = maak_stub_funda(lambda _n: [], details={}, calls=[])
        web = ts.StubWeb()
        web.pagina.update(afwijking)
        echt, Z = _sitemap_met(web)
        os.environ["FUNDA_ZOEK_METHODE"] = "sitemap"
        fsz.SitemapZoeker = Z
        try:
            with contextlib.redirect_stdout(io.StringIO()) as uit:
                code, gedraaid = draai(fz)
        finally:
            fsz.SitemapZoeker = echt
            os.environ["FUNDA_ZOEK_METHODE"] = "api"
        ok &= check(f"{naam}: exit 2 zonder rapport", code == 2 and not gedraaid, str(code))
        ok &= check(f"{naam}: ::error in de log", "::error::Alle" in uit.getvalue())

    # Niets werkt in auto: ook exit 2, en de oorzaken staan in de log.
    import funda_html_zoek as fhz

    class Dicht:
        reden = "Zoekpagina gaf status 403"

        def __init__(self, *a, **k):
            pass

        def bereikbaar(self):
            return False

    fz = maak_stub_funda(lambda _n: (_ for _ in ()).throw(RuntimeError("Search failed (status 401)")))
    web = ts.StubWeb()
    web.pagina[ts.INDEX_URL] = RuntimeError("status 403")
    echt, Z = _sitemap_met(web)
    origineel = (fhz.HtmlZoeker, fz._woningen_uit_mailbox)
    os.environ["FUNDA_ZOEK_METHODE"] = "auto"
    fsz.SitemapZoeker, fhz.HtmlZoeker = Z, Dicht
    fz._woningen_uit_mailbox = lambda: []
    try:
        with contextlib.redirect_stdout(io.StringIO()) as uit:
            code, gedraaid = draai(fz)
    finally:
        fsz.SitemapZoeker = echt
        fhz.HtmlZoeker, fz._woningen_uit_mailbox = origineel
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
    ok &= check("auto, niets werkt: exit 2 zonder rapport", code == 2 and not gedraaid, str(code))
    ok &= check("auto, niets werkt: sitemap-index één keer geprobeerd",
                web.calls.count(ts.INDEX_URL) == 1, str(web.calls))
    ok &= check("auto, niets werkt: oorzaken in de ::error",
                "::error::Geen enkele zoekbron werkt" in uit.getvalue())
    return ok


def test_geen_dubbele_detail_calls() -> bool:
    """Stap b door main(): sitemapzoeker, pool, detail-check en rapport samen.

    Elke woning hooguit één detail-call per run. De pool haalt niet opnieuw op
    wat de zoeker al ophaalde of op de cache oversloeg; een getrackte woning die
    niet meer in de sitemap staat krijgt één controle-call en wordt bij
    'verkocht' als weg gemarkeerd; een woning uit de achterstand haalt de pool
    zelf op en legt hem vast, zodat de zoeker hem niet nog eens verkent.
    """
    print("test: geen dubbele detail-calls tussen sitemapzoeker en pool")
    import funda_sitemap_zoek as fsz
    import test_funda_sitemap as ts

    details = {k: {**v, "tiny_id": k} for k, v in ts.DETAILS.items()}
    details["44000099"] = {"global_id": 1099, "tiny_id": "44000099", "title": "Wegstraat 9",
                           "city": "Den Haag", "price": 260000, "living_area": 60, "status": "sold"}
    vandaag = datetime.now().strftime("%Y-%m-%d")
    url = "https://www.funda.nl/detail/koop"
    tracking = {
        # Te duur geworden: de zoeker haalt hem op (run 1) of slaat hem over (run 2).
        "1002": {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-koningin-emmakade-185/44664520/"},
        # Staat in de sitemap, maar valt buiten het verkenbudget: de pool haalt hem.
        "1003": {"last_seen": vandaag, "url": f"{url}/voorburg/appartement-rodelaan-379/44546400/"},
        # Niet meer in de sitemap, en verkocht.
        "1099": {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-weg-9/44000099/"},
    }
    per_woning = {k: k for k in details} | {str(v["global_id"]): k for k, v in details.items()}

    def woning(ident: str) -> str:
        return per_woning.get(ident.rstrip("/").split("/")[-1], ident)

    ok = True
    echt = fsz.SitemapZoeker
    oude_sleep, oud_budget = time.sleep, None
    os.environ["FUNDA_ZOEK_METHODE"] = "sitemap"
    try:
        time.sleep = lambda _s: None
        uitkomsten = []
        for run in (1, 2):
            calls: list[str] = []
            fz = maak_stub_funda(lambda _n: [], details=details, calls=calls)
            if run == 1:
                fz.TRACKING_FILE.write_text(json.dumps(tracking))
            else:
                fz.TRACKING_FILE.write_text(json.dumps(uitkomsten[0]["tracking"]))
                fz.SITEMAP_CACHE_FILE.write_text(uitkomsten[0]["cache"])
                fz.STATE_FILE.write_text(uitkomsten[0]["seen"])
            oud_budget = fz.SITEMAP_MAX_VERKENNEN
            fz.SITEMAP_MAX_VERKENNEN = 2   # Rodelaan (oudste lastmod) blijft in de achterstand
            _echt, Z = _sitemap_met(ts.StubWeb())
            fsz.SitemapZoeker = Z
            gezien = {}

            def rapport(_client, goed, _nieuw):
                gezien["titels"] = sorted(d.get("title") for d in goed)
                return Path("rapport.html")

            fz.genereer_rapport = rapport
            with contextlib.redirect_stdout(io.StringIO()) as uit:
                try:
                    fz.main()
                    code = None
                except SystemExit as exc:
                    code = exc.code
            uitkomsten.append({
                "code": code, "calls": calls, "titels": gezien.get("titels"), "log": uit.getvalue(),
                "tracking": json.loads(fz.TRACKING_FILE.read_text()),
                "cache": fz.SITEMAP_CACHE_FILE.read_text(), "seen": fz.STATE_FILE.read_text(),
            })
            fz.SITEMAP_MAX_VERKENNEN = oud_budget
    finally:
        time.sleep = oude_sleep
        fsz.SitemapZoeker = echt
        os.environ["FUNDA_ZOEK_METHODE"] = "api"

    r1, r2 = uitkomsten
    per1 = Counter(woning(c) for c in r1["calls"])
    ok &= check("run 1 normaal afgerond", r1["code"] is None, str(r1["code"]))
    ok &= check("run 1: elke woning hooguit één call", max(per1.values()) == 1, str(per1))
    ok &= check("run 1: zoeker 2 verkend, pool 1 achterstand + 1 controle",
                sorted(per1) == ["44000099", "44546400", "44664520", "80024814"], str(per1))
    ok &= check("run 1: rapport met de twee woningen in de doelmarkt",
                r1["titels"] == ["Draaistraat 4", "Rodelaan 379"], str(r1["titels"]))
    ok &= check("run 1: verkochte woning buiten de sitemap als weg gemarkeerd",
                bool(r1["tracking"]["1099"].get("weg")), str(r1["tracking"]["1099"]))
    ok &= check("run 1: woning uit de achterstand vastgelegd in de sitemapcache",
                "44546400" in json.loads(r1["cache"])["woningen"])
    ok &= check("run 1: telling in de log",
                "(waarvan dezelfde woning nog eens: 0)" in r1["log"]
                and "1 niet meer in de sitemap" in r1["log"])

    per2 = Counter(woning(c) for c in r2["calls"])
    ok &= check("run 2 normaal afgerond", r2["code"] is None, str(r2["code"]))
    ok &= check("run 2: alleen de twee in de doelmarkt ververst, elk één keer",
                per2 == Counter({"80024814": 1, "44546400": 1}), str(per2))
    ok &= check("run 2: te dure woning op cache overgeslagen, ook door de pool",
                "1 op cache overgeslagen" in r2["log"])
    ok &= check("run 2: koop-sitemaps niet opnieuw opgehaald",
                "koop-sitemaps niet opnieuw opgehaald" in r2["log"])
    return ok


def test_sitemap_overslaan() -> bool:
    """Stap c: de filter van de sitemapzoeker gebruikt ook prijs, m2 en straal."""
    print("test: _sitemap_overslaan met straal, prijs en m2")
    import funda_sitemap_zoek as fsz

    fz = maak_stub_funda(lambda _n: [])
    fz.PRIJS_MIN, fz.PRIJS_MAX, fz.M2_MIN = 230_000, 310_000, 55
    fz.STRAAL_NAFILTER_KM = 5
    fz._THUIS["v"] = (52.0800, 4.3000)
    basis = {"city": "Den Haag", "price": 280_000, "living_area": 70,
             "detail_url": "/detail/koop/den-haag/appartement-a-1/44500000/"}
    ok = check("coördinaten gaan mee in de cache",
               {"latitude", "longitude"} <= set(fsz.CACHE_VELDEN))
    ok &= check("dichtbij komt door",
                fz._sitemap_overslaan({**basis, "latitude": 52.09, "longitude": 4.30}) is False)
    ok &= check("ver weg valt af",
                fz._sitemap_overslaan({**basis, "latitude": 51.98, "longitude": 4.30}) is True)
    ok &= check("zonder coördinaten: doorlaten", fz._sitemap_overslaan(basis) is False)
    ok &= check("te duur valt af", fz._sitemap_overslaan({**basis, "price": 325_000}) is True)
    ok &= check("te klein valt af", fz._sitemap_overslaan({**basis, "living_area": 40}) is True)
    ok &= check("uitgesloten buurt valt af",
                fz._sitemap_overslaan({**basis, "neighbourhood": "Moerwijk-Oost"}) is True)
    fz._THUIS["v"] = None
    ok &= check("zonder thuiscoördinaten geen afstandsfilter",
                fz._sitemap_overslaan({**basis, "latitude": 51.0, "longitude": 4.0}) is False)
    return ok


def test_instellingen() -> bool:
    """Stap f: een lege workflow-input valt terug op de standaard van 200."""
    print("test: sitemap_max_verkennen uit omgeving en config")
    fz = maak_stub_funda(lambda _n: [])
    ok = True
    oud = os.environ.get("FUNDA_SITEMAP_MAX_VERKENNEN")
    try:
        for waarde, verwacht in (("", 200), ("   ", 200), ("600", 600), ("zeshonderd", 200)):
            os.environ["FUNDA_SITEMAP_MAX_VERKENNEN"] = waarde
            with contextlib.redirect_stdout(io.StringIO()):
                uit = fz._int_instelling("FUNDA_SITEMAP_MAX_VERKENNEN", "sitemap_max_verkennen", 200)
            ok &= check(f"omgeving {waarde!r} -> {verwacht}", uit == verwacht, str(uit))
        os.environ.pop("FUNDA_SITEMAP_MAX_VERKENNEN")
        fz._PERSONAL["sitemap_max_verkennen"] = 350
        ok &= check("config als de omgeving leeg is",
                    fz._int_instelling("FUNDA_SITEMAP_MAX_VERKENNEN", "sitemap_max_verkennen", 200) == 350)
        os.environ["FUNDA_SITEMAP_MAX_VERKENNEN"] = "600"
        ok &= check("omgeving gaat voor op config",
                    fz._int_instelling("FUNDA_SITEMAP_MAX_VERKENNEN", "sitemap_max_verkennen", 200) == 600)
    finally:
        fz._PERSONAL.pop("sitemap_max_verkennen", None)
        if oud is None:
            os.environ.pop("FUNDA_SITEMAP_MAX_VERKENNEN", None)
        else:
            os.environ["FUNDA_SITEMAP_MAX_VERKENNEN"] = oud
    return ok


VINGERAFDRUK_PROEF = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import funda.funda as pf
import funda_zoek as fz

uit = {"pool_lengte": len(pf.FINGERPRINT_POOL)}
getest = []

def nep_test(self, fp):
    getest.append(pf.FINGERPRINT_POOL.index(fp))
    return MODUS["eerste_werkt"] or getest[-1] > 0

MODUS = {"eerste_werkt": False}
pf.Funda._test_fingerprint = nep_test

# Ongepatcht pyfunda: wisselt stil door naar de volgende vingerafdruk.
gewoon = pf.Funda()
uit["ongepatcht"] = pf.FINGERPRINT_POOL.index(gewoon._find_working_fingerprint())
getest.clear()

# Gepatcht: alleen de eerste, en bij weigering een duidelijke fout.
f = fz.Funda()
try:
    f.get_listing(43117443)
    uit["fout"] = None
except Exception as exc:
    uit["fout"] = [type(exc).__name__, str(exc)]
uit["getest_na_eerste"] = list(getest)
try:
    f.get_listing(43117443)
except Exception as exc:
    uit["tweede_fout"] = type(exc).__name__
uit["getest_na_tweede"] = list(getest)

MODUS["eerste_werkt"] = True
getest.clear()
g = fz.Funda()
g._ensure_session()
uit["werkend"] = pf.FINGERPRINT_POOL.index(g._fingerprint)
uit["getest_werkend"] = list(getest)
print(json.dumps(uit))
"""


def test_vaste_vingerafdruk() -> bool:
    """Stap d: alleen FINGERPRINT_POOL[0], tegen het echte pyfunda (zonder netwerk)."""
    print("test: vaste pyfunda-vingerafdruk")
    hier = str(Path(__file__).parent.resolve())
    proces = subprocess.run([sys.executable, "-c", VINGERAFDRUK_PROEF, hier],
                            capture_output=True, text=True, cwd=hier, timeout=120)
    regels = [r for r in proces.stdout.splitlines() if r.startswith("{")]
    if proces.returncode != 0 or not regels:
        return check("proef draait", False, (proces.stderr or proces.stdout)[-400:])
    uit = json.loads(regels[-1])
    ok = check("pyfunda heeft meerdere vingerafdrukken", uit["pool_lengte"] > 1)
    ok &= check("ongepatcht pyfunda wisselt stil door", uit["ongepatcht"] == 1, str(uit["ongepatcht"]))
    fout = uit.get("fout") or ["", ""]
    ok &= check("gepatcht: RuntimeError met uitleg",
                fout[0] == "RuntimeError" and "vaste vingerafdruk" in fout[1]
                and "omzeilen" in fout[1], str(fout))
    ok &= check("gepatcht: alleen de eerste geprobeerd", uit["getest_na_eerste"] == [0],
                str(uit["getest_na_eerste"]))
    ok &= check("tweede call probeert niet opnieuw",
                uit.get("tweede_fout") == "RuntimeError" and uit["getest_na_tweede"] == [0],
                str(uit["getest_na_tweede"]))
    ok &= check("werkt de eerste, dan die", uit["werkend"] == 0 and uit["getest_werkend"] == [0])
    return ok


def test_stadfilter() -> bool:
    """Voorburg mag niet sneuvelen op de gemeentenaam Leidschendam-Voorburg."""
    print("test: stadfilter, Voorburg versus Leidschendam")
    fz = maak_stub_funda(lambda _n: [])
    ok = True

    # De kern: zonder de WENS_STEDEN-voorrang matcht "Leidschendam" als substring
    # op "Leidschendam-Voorburg" en valt al het Voorburg-aanbod stil weg.
    ok &= check("Voorburg komt door", fz.is_uitgesloten_stad("Voorburg") is None)
    ok &= check("gemeente Leidschendam-Voorburg komt door",
                fz.is_uitgesloten_stad("Leidschendam-Voorburg") is None,
                str(fz.is_uitgesloten_stad("Leidschendam-Voorburg")))
    ok &= check("Leidschendam zelf valt af",
                fz.is_uitgesloten_stad("Leidschendam") == "Leidschendam")
    ok &= check("Rijswijk valt af", fz.is_uitgesloten_stad("Rijswijk") == "Rijswijk")
    ok &= check("Rijswijk (ZH) valt ook af",
                fz.is_uitgesloten_stad("Rijswijk (ZH)") == "Rijswijk")
    ok &= check("Den Haag komt door", fz.is_uitgesloten_stad("Den Haag") is None)

    # De dubbelzinnige gemeentenaam hoort een waarschuwing te krijgen, zodat
    # zichtbaar is dat het ook Leidschendam kan zijn.
    ok &= check("gemeentenaam geeft waarschuwing",
                fz.is_twijfelstad("Leidschendam-Voorburg") is not None)
    ok &= check("alleen Voorburg geeft geen waarschuwing",
                fz.is_twijfelstad("Voorburg") is None)
    ok &= check("Den Haag geeft geen waarschuwing",
                fz.is_twijfelstad("Den Haag") is None)

    # En het mag de detail-call niet overslaan: dat voorfilter gebruikt dezelfde
    # functie, dus een Voorburg-woning zou anders nooit verrijkt worden.
    kaart = {"city": "Leidschendam-Voorburg", "title": "Teststraat 1"}
    ok &= check("detail-call niet overgeslagen",
                fz._mag_detail_call_overslaan(kaart) is False)
    return ok


def test_woningtypefilter() -> bool:
    """Woonhuizen eruit, appartement-subtypes erin, onbekend doorlaten."""
    print("test: nafilter op woningtype")
    fz = maak_stub_funda(lambda _n: [])
    ok = True

    def af(soort=None, url=None):
        return fz.is_geen_appartement({"house_type": soort, "detail_url": url})

    # Huizen eruit, op het veld uit de detail-API.
    for soort in ("Eengezinswoning", "Woonhuis", "Herenhuis", "Tussenwoning",
                  "Hoekwoning", "Vrijstaande woning", "2-onder-1-kapwoning",
                  "Villa", "Bungalow"):
        ok &= check(f"{soort} valt af", af(soort) is not None, str(af(soort)))

    # Appartement-subtypes moeten er WEL doorheen. Dit is precies waarom het een
    # afwijslijst is en geen toestaanlijst: deze zouden anders stuk voor stuk
    # sneuvelen zodra er eentje niet op de lijst stond.
    for soort in ("Appartement", "Bovenwoning", "Portiekflat", "Maisonnette",
                  "Galerijflat", "Penthouse", "Studio", "Benedenwoning",
                  "Dubbel benedenhuis"):
        ok &= check(f"{soort} komt door", af(soort) is None, str(af(soort)))

    # Onbekend of leeg: doorlaten, niet weggooien.
    ok &= check("leeg type komt door", af(None) is None)
    ok &= check("onbekend type komt door", af("Iets nieuws van funda") is None)

    # URL-slug als tweede signaal, als het veld ontbreekt.
    ok &= check("slug huis- valt af",
                af(None, "/detail/koop/den-haag/huis-teststraat-12/44500000/") is not None)
    ok &= check("slug appartement- komt door",
                af(None, "/detail/koop/den-haag/appartement-teststraat-12/44500000/") is None)
    # Alleen het eerste slug-segment telt, anders sneuvelt een straatnaam.
    ok &= check("Huisduinenstraat is geen huis",
                af("Appartement",
                   "/detail/koop/den-haag/appartement-huisduinenstraat-5/44500000/") is None)
    ok &= check("volledige URL werkt ook",
                af(None, "https://www.funda.nl/detail/koop/den-haag/huis-a-1/44500000/")
                is not None)

    # Het veld gaat voor op de slug.
    ok &= check("veld wint van slug",
                af("Woonhuis",
                   "/detail/koop/den-haag/appartement-teststraat-1/44500000/") is not None)
    return ok


def test_zoekcriteria() -> bool:
    """Prijs, m2 en straal als nafilter: wat funda vroeger in de zoekopdracht deed."""
    print("test: nafilter op prijs, oppervlak en straal")
    fz = maak_stub_funda(lambda _n: [])
    fz.PRIJS_MIN, fz.PRIJS_MAX, fz.M2_MIN = 230_000, 310_000, 55
    thuis = (52.0800, 4.3000)
    ok = True

    def reden(**velden):
        return fz.buiten_zoekcriteria(velden, thuis, 5.0)

    ok &= check("binnen alles komt door",
                reden(price=280_000, living_area=70, latitude=52.09, longitude=4.30) is None)
    ok &= check("te duur valt af", reden(price=325_000) is not None)
    ok &= check("te goedkoop valt af", reden(price=199_000) is not None)
    ok &= check("te klein valt af", reden(price=280_000, living_area=48) is not None)
    # ~11 km naar het zuiden: buiten 5 km.
    ok &= check("ver weg valt af",
                reden(price=280_000, latitude=51.98, longitude=4.30) is not None,
                str(reden(price=280_000, latitude=51.98, longitude=4.30)))
    # Onbekend is geen reden om weg te gooien.
    ok &= check("zonder prijs/m2/coördinaten komt door", reden() is None)
    ok &= check("zonder thuiscoördinaten geen afstandsfilter",
                fz.buiten_zoekcriteria({"latitude": 51.0, "longitude": 4.0}, None, 5.0) is None)
    ok &= check("straal uit = geen afstandsfilter",
                fz.buiten_zoekcriteria({"latitude": 51.0, "longitude": 4.0}, thuis, None) is None)

    # Standaardstraal: de ingestelde afgerond zoals funda dat deed (6 -> 5).
    fz.STRAAL_NAFILTER_KM, fz.RADIUS_KM = None, 6
    ok &= check("standaardstraal 6 wordt 5", fz.nafilter_straal_km() == 5.0,
                str(fz.nafilter_straal_km()))
    fz.STRAAL_NAFILTER_KM = 0
    ok &= check("straal_nafilter_km 0 zet hem uit", fz.nafilter_straal_km() is None)
    fz.STRAAL_NAFILTER_KM = 7
    ok &= check("expliciete straal wint", fz.nafilter_straal_km() == 7.0)
    return ok


def test_beschikbaarheid() -> bool:
    print("test: beschikbaarheid uit de detail-API")
    fz = maak_stub_funda(lambda _n: [])
    ok = True

    def oordeel(status=None, kenmerk=None):
        d = {"status": status}
        if kenmerk is not None:
            d["characteristics"] = {"Status": kenmerk}
        return fz.beschikbaarheid(d)[0]

    ok &= check("niets bekend = beschikbaar", oordeel() == "ja")
    ok &= check("Beschikbaar", oordeel("available", "Beschikbaar") == "ja")
    ok &= check("sold = weg", oordeel("sold") == "weg")
    ok &= check("Verkocht onder voorbehoud = weg",
                oordeel("available", "Verkocht onder voorbehoud") == "weg")
    ok &= check("Onder bod = tijdelijk", oordeel("available", "Onder bod") == "tijdelijk")
    ok &= check("Onder optie = tijdelijk", oordeel("available", "Onder optie") == "tijdelijk")
    ok &= check("onbekende statustekst = beschikbaar",
                oordeel("available", "Iets nieuws") == "ja")
    return ok


def test_pool() -> bool:
    """Bekende woningen blijven in beeld zolang ze te koop staan."""
    print("test: pool met bekende woningen")
    fz = maak_stub_funda(lambda _n: [])
    from datetime import datetime, timedelta

    vandaag = datetime.now().strftime("%Y-%m-%d")
    oud = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

    antwoorden = {
        1000001: {"global_id": 1000001, "status": "available",
                  "characteristics": {"Status": "Beschikbaar"}, "url": "https://www.funda.nl/a/"},
        1000002: {"global_id": 1000002, "status": "sold"},
        1000003: {"global_id": 1000003, "status": "available",
                  "characteristics": {"Status": "Onder bod"}},
    }

    class Client:
        def __init__(self):
            self.calls = []

        def get_listing(self, ident):
            self.calls.append(ident)
            if ident in antwoorden:
                return StubListing(dict(antwoorden[ident]))
            raise LookupError(f"Listing {ident} not found")

    tracking = {
        "1000001": {"last_seen": vandaag},
        "1000002": {"last_seen": vandaag},
        "1000003": {"last_seen": vandaag},
        "1000004": {"last_seen": vandaag, "pool_fout": 2},   # derde mislukking
        "1000005": {"last_seen": oud},                       # buiten het venster
        "1000006": {"last_seen": vandaag},                   # al binnen via mail
        "1000007": {"last_seen": vandaag, "weg": {"datum": oud}},
    }
    client = Client()
    zoeker = fz.DetailCacheZoeker(client)
    res = fz.controleer_pool(zoeker, tracking, {"1000006"}, dagen=120, maximum=50, pauze=0)
    ids = [r.data.get("global_id") for r in res]
    ok = check("alleen de beschikbare komt terug", ids == [1000001], str(ids))
    ok &= check("bron is pool", res and res[0].data.get("_bron") == "pool")
    ok &= check("verkocht wordt gemarkeerd", bool(tracking["1000002"].get("weg")))
    ok &= check("onder bod blijft gevolgd", not tracking["1000003"].get("weg"))
    ok &= check("derde mislukking = weg", bool(tracking["1000004"].get("weg")))
    ok &= check("buiten venster niet opgevraagd", 1000005 not in client.calls)
    ok &= check("al binnen niet opgevraagd", 1000006 not in client.calls)
    ok &= check("al weg niet opgevraagd", 1000007 not in client.calls)
    ok &= check("detail-call gecacht voor de rest van de run",
                zoeker.get_listing(1000001) is not None and client.calls.count(1000001) == 1)

    # Storing: alles faalt. Dan mag er niets als weg gemarkeerd worden, ook niet
    # bij een woning die al twee mislukkingen had.
    class Dicht:
        def get_listing(self, ident):
            raise LookupError("403")

    tracking2 = {str(1000100 + i): {"last_seen": vandaag, "pool_fout": 2} for i in range(8)}
    res2 = fz.controleer_pool(fz.DetailCacheZoeker(Dicht()), tracking2, set(),
                              dagen=120, maximum=50, pauze=0)
    ok &= check("storing: niets terug", res2 == [])
    ok &= check("storing: niets als weg gemarkeerd",
                not any(r.get("weg") for r in tracking2.values()))
    ok &= check("storing: teller niet opgehoogd",
                all(r.get("pool_fout") == 2 for r in tracking2.values()))
    return ok


def test_pool_in_run() -> bool:
    """Een bekende woning die niet in de mail zit, staat toch in het rapport."""
    print("test: pool in een volledige run")

    def gedrag(n):
        if n == 1:
            return [StubListing({
                "global_id": "g1", "city": "Den Haag", "neighbourhood": "Bomenbuurt",
                "price": 250000, "living_area": 60, "title": "Teststraat 1",
                "detail_url": "/detail/koop/den-haag/appartement-teststraat-1/44500001/",
            })]
        return []

    fz = maak_stub_funda(gedrag)
    import json
    fz.TRACKING_FILE.write_text(json.dumps({
        "g1": {"last_seen": "2026-01-01", "first_seen": "2026-01-01", "prices": []},
        "1234567": {"last_seen": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
                    "first_seen": "2026-01-01", "prices": [["2026-01-01", 260000]]},
    }))
    gezien = {}

    def rapport(_client, goed, _nieuw):
        gezien["ids"] = sorted(str(d.get("global_id")) for d in goed)
        return Path("rapport.html")

    fz.genereer_rapport = rapport
    try:
        fz.main()
        code = None
    except SystemExit as exc:
        code = exc.code
    ok = check("geen afbreking", code is None, str(code))
    # De stub-client geeft voor elke get_listing dezelfde woning (g1) terug, dus
    # de pool-woning komt binnen als g1 en wordt ontdubbeld. Wat hier telt: de
    # pool draaide en het rapport kreeg een gevulde lijst.
    ok &= check("rapport kreeg woningen", bool(gezien.get("ids")), str(gezien.get("ids")))
    ok &= check("pool-woning met bekend id niet dubbel", gezien.get("ids") == ["g1"],
                str(gezien.get("ids")))
    tracking = json.loads(fz.TRACKING_FILE.read_text())
    ok &= check("url wordt in tracking bewaard", "url" in tracking.get("g1", {}),
                str(tracking.get("g1")))
    return ok


def main() -> int:
    resultaten = [test_alles_faalt(), test_stille_lege_oogst(), test_normale_run(), test_prijs_onbekend(),
                  test_auto_keten(), test_stadfilter(),
                  test_woningtypefilter(), test_zoekcriteria(), test_beschikbaarheid(),
                  test_pool(), test_pool_in_run(), test_sitemapbron_faalt_luid(),
                  test_geen_dubbele_detail_calls(), test_sitemap_overslaan(), test_instellingen(),
                  test_vaste_vingerafdruk()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
