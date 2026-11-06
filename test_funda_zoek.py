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


def maak_stub_funda(zoek_gedrag, details=None, calls=None, faal_na=None):
    """Installeer een nep-funda-module vóór funda_zoek geïmporteerd wordt.

    Met `details` (per tiny_id) zoekt get_listing de woning op aan het nummer in
    de URL of aan het global_id, en schrijft elke aanroep in `calls`.

    Statuscodes zoals pyfunda ze ziet: een woning met `_status` in zijn details
    geeft die status, en `faal_na=(n, status)` laat elke call na de n-de falen
    (status None: een fout zonder bekende status, zoals een time-out). pyfunda
    geeft dan een LookupError; de Funda-subklasse vertaalt die op de status.
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
                if faal_na is not None and len(calls) > faal_na[0]:
                    if faal_na[1]:
                        self._statussen.append(faal_na[1])
                    raise LookupError(f"Listing {ident} not found")
                sleutel = str(ident).rstrip("/").split("/")[-1]
                if sleutel not in per_id:
                    raise LookupError(f"Listing {ident} not found")
                if per_id[sleutel].get("_status"):
                    self._statussen.append(per_id[sleutel]["_status"])
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


def test_prijs_onbekend_rapport() -> bool:
    """Geen vraagprijs: niet als € 0 bovenaan met budget PAST.

    Gezien in e2e-run 42273695515: "€ 0 | 145 m2" stond bovenaan, met budget
    PAST en de hoogste score. Dit gaat door het echte bouw_rij en de rendering,
    niet door een gestubde genereer_rapport.
    """
    print("test: prijs op aanvraag in rapport, tracking en pushmelding")
    fz = maak_stub_funda(lambda _n: [])
    import funda_rapport as fr

    basis = {"city": "Den Haag", "neighbourhood": "Bomenbuurt", "living_area": 145,
             "energy_label": "C", "detail_url": "/detail/koop/den-haag/appartement-a-1/44500001/"}

    def rij(d):
        r = fr.bouw_rij(dict(d), None, "Ruim appartement met balkon.")
        r.update(is_nieuw=True, foto_url=None, routes=[])
        return r

    onbekend = rij({**basis, "price": None, "title": "Zonder prijs", "global_id": 1})
    bekend = rij({**basis, "price": 299500, "title": "Met prijs", "global_id": 2})
    ok = check("budget PRIJS ONBEKEND in plaats van PAST",
               onbekend["budget"] == "PRIJS ONBEKEND" and not onbekend["in_max"], onbekend["budget"])
    ok &= check("score alleen uit voor- en nadelen, niets op prijs 0",
                onbekend["score"] == 2.0 * (len(onbekend["pros"]) - len(onbekend["cons"])),
                str(onbekend["score"]))
    rijen = [onbekend, bekend]
    fr.sorteer_rijen(rijen)
    ok &= check("in het rapport achteraan", [r["d"]["title"] for r in rijen] == ["Met prijs", "Zonder prijs"])
    kaart = fr._card_html(onbekend)
    ok &= check("kaart: prijs op aanvraag, geen € 0, geen maandlast",
                "Prijs op aanvraag" in kaart and "€ 0" not in kaart and "lasten-totaal" not in kaart)
    ok &= check("kaart: lege sorteerwaarden (de JS zet die achteraan)",
                'data-prijs=""' in kaart and 'data-score=""' in kaart and 'data-maandlast=""' in kaart)
    ok &= check("kaart: eigen budgetklasse", "budget-ONBEKEND" in kaart)
    md = fr.render_markdown(rijen)
    ok &= check("markdown: prijs op aanvraag, geen € 0",
                "Zonder prijs — prijs op aanvraag" in md and "| € 0 |" not in md)

    tracking = {}
    fz.update_tracking(tracking, "x", 280000, None)
    flags = fz.update_tracking(tracking, "x", 0, None)
    ok &= check("tracking: naar prijs op aanvraag is geen prijsdaling",
                not flags["gedaald"] and tracking["x"]["prices"][-1][1] == 280000, str(flags))
    flags = fz.update_tracking(tracking, "y", 0, None)
    ok &= check("tracking: nieuwe woning zonder prijs", not flags["gedaald"] and tracking["y"]["prices"] == [])

    fz.schrijf_run_summary([{**basis, "price": None, "title": "Zonder prijs"}], [], [])
    ok &= check("pushmelding: price null in plaats van 0",
                json.loads(fz.SUMMARY_FILE.read_text(encoding="utf-8"))["nieuw"][0]["price"] is None)
    return ok


def test_auto_keten() -> bool:
    """'auto' loopt api -> html -> sitemap af en neemt de eerste die werkt.

    De mailroute zit niet in 'auto' (besluit 6 nov 2026): de mailbox gaat in
    'auto' nooit open, ook niet als er mail zou zijn en alles faalt. Alleen een
    expliciete zoek_methode 'mail' leest hem nog.
    """
    print("test: auto kiest de eerste werkende zoekmethode, zonder mailroute")
    import funda_html_zoek as fhz
    import funda_mail_ophalen as fmo
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
        ophaal_fout = None
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

        def ophalen(self):
            volgorde.append("ophalen")
            if StubSitemap.ophaal_fout is not None:
                raise StubSitemap.ophaal_fout

    # De mailbox op IMAP-niveau: ingesteld en met een woning erin, zodat 'auto'
    # hem zou kunnen gebruiken. Elke opening staat in de volgorde.
    def stub_imap(**_kw):
        volgorde.append("mail")
        return ["Nieuw: https://www.funda.nl/detail/koop/den-haag/appartement-a-1/44500000/"]

    def kies(client):
        volgorde.clear()
        uit = io.StringIO()
        with contextlib.redirect_stdout(uit):
            zoeker, methode = fz.kies_zoeker(client)
        return zoeker, methode, uit.getvalue()

    origineel = (fhz.HtmlZoeker, fsz.SitemapZoeker, fmo.mail_config, fmo.haal_mail_teksten)
    os.environ["FUNDA_ZOEK_METHODE"] = "auto"
    try:
        fhz.HtmlZoeker, fsz.SitemapZoeker = StubHtml, StubSitemap
        fmo.mail_config = lambda _personal=None: {"host": "imap.example", "gebruiker": "x",
                                                  "wachtwoord": "y", "map_naam": ""}
        fmo.haal_mail_teksten = stub_imap

        # 1. API antwoordt: dan niets anders proberen.
        _, methode, _ = kies(ApiOk())
        ok &= check("API werkt -> api, verder niets geprobeerd",
                    methode == "api" and volgorde == ["api"], f"{methode} {volgorde}")

        # 2. API dicht, zoekpagina laat door.
        StubHtml.bereik = True
        _, methode, _ = kies(ApiDicht())
        ok &= check("API dicht, HTML open -> html, sitemaps niet gevraagd",
                    methode == "html" and volgorde == ["api", "html"], f"{methode} {volgorde}")

        # 3. API en zoekpagina dicht, sitemaps open: sitemap.
        StubHtml.bereik, StubSitemap.bereik = False, True
        zoeker, methode, _ = kies(ApiDicht())
        ok &= check("API en HTML dicht, sitemaps open -> sitemap (al opgehaald)",
                    methode == "sitemap" and volgorde == ["api", "html", "sitemap", "ophalen"],
                    f"{methode} {volgorde}")
        ok &= check("sitemapzoeker kent de doelmarkt",
                    zoeker is StubSitemap.laatste and zoeker.kw["prijs_max"] == fz.PRIJS_MAX
                    and zoeker.kw["m2_min"] == fz.M2_MIN
                    and zoeker.kw["overslaan"] is fz._sitemap_overslaan
                    and zoeker.kw["max_verkennen"] == fz.SITEMAP_MAX_VERKENNEN)

        # 3b. Index bereikbaar, maar een koop-sitemap geeft 403 (bereikbaar()
        # kijkt daar niet naar): geen bron, met die oorzaak in de ::error, en
        # de mailbox blijft dicht, ook al zit er een woning in.
        StubSitemap.ophaal_fout = RuntimeError("https://www.funda.nl/sitemap-detail-koop1.xml gaf status 403")
        zoeker, methode, uitvoer = kies(ApiDicht())
        ok &= check("index OK, koop-sitemap 403 -> geen, mailbox niet geopend",
                    methode == "geen" and volgorde == ["api", "html", "sitemap", "ophalen"],
                    f"{methode} {volgorde}")
        ok &= check("koop-sitemap 403: oorzaak in de ::error",
                    "::error::" in uitvoer and "sitemap-detail-koop1.xml gaf status 403" in uitvoer)

        # 3c. Het detail-endpoint is dicht: elke route heeft dat nodig, dus geen
        # terugval; de sitemapzoeker laat main() met exit 2 stoppen.
        StubSitemap.ophaal_fout = fz.DetailEndpointDicht("status 403 voor 44500000")
        _, methode, _ = kies(ApiDicht())
        ok &= check("detail-endpoint dicht -> sitemap, mailbox niet geopend",
                    methode == "sitemap" and "mail" not in volgorde, f"{methode} {volgorde}")
        StubSitemap.ophaal_fout = None

        # 4. Niets werkt: luid falen met de oorzaken van api, zoekpagina en
        # sitemaps, zonder mail-oorzaak en zonder de mailbox te openen.
        StubSitemap.bereik = False
        zoeker, methode, uitvoer = kies(ApiDicht())
        ok &= check("niets werkt -> geen, mailbox niet geopend",
                    methode == "geen" and volgorde == ["api", "html", "sitemap"],
                    f"{methode} {volgorde}")
        fout = [r for r in uitvoer.splitlines() if r.startswith("::error::")]
        ok &= check("één ::error met de oorzaken van api, zoekpagina en sitemaps",
                    len(fout) == 1 and all(w in fout[0] for w in
                                           ("401", "Zoekpagina gaf status 403", "sitemap_index")),
                    str(fout))
        ok &= check("geen mail-oorzaak in de ::error",
                    bool(fout) and "mail" not in fout[0].lower(), str(fout))
        try:
            zoeker.search_listing(location="x")
            ok &= check("GeenBron faalt bij zoeken", False)
        except RuntimeError:
            ok &= check("GeenBron faalt bij zoeken", True)

        # 5. Afdwingen blijft werken, ook zonder dat er iets bereikbaar is. Alleen
        # 'mail' opent de mailbox, en levert dan de woning uit de mail.
        for gedwongen in ("api", "html", "sitemap", "mail"):
            os.environ["FUNDA_ZOEK_METHODE"] = gedwongen
            zoeker, methode, _ = kies(ApiDicht())
            verwacht = ["mail"] if gedwongen == "mail" else []
            ok &= check(f"afgedwongen {gedwongen}", methode == gedwongen and volgorde == verwacht,
                        f"{methode} {volgorde}")
        ok &= check("afgedwongen mail: woning uit de mailbox",
                    getattr(zoeker, "_woningen", None)
                    == [("/detail/koop/den-haag/appartement-a-1/44500000/", "44500000")],
                    str(getattr(zoeker, "_woningen", None)))

        # 6. Onzin in de config mag niet crashen; dat valt terug op auto.
        os.environ["FUNDA_ZOEK_METHODE"] = "telepathie"
        StubHtml.bereik = True
        _, methode, _ = kies(ApiDicht())
        ok &= check("onbekende methode valt terug op auto", methode == "html", methode)
    finally:
        fhz.HtmlZoeker, fsz.SitemapZoeker, fmo.mail_config, fmo.haal_mail_teksten = origineel
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
    return ok


def _sitemap_met(web, **extra):
    """Echte SitemapZoeker, maar met een nep-web, zonder pauzes en met een vaste klok.

    De klok: de fixtures hebben lastmods van begin november 2026, en de
    leeftijdscheck vergelijkt met nu.
    """
    import funda_sitemap_zoek as fsz
    import test_funda_sitemap as ts

    extra.setdefault("nu", lambda: ts.NU)
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
    # 'auto' mag de mailbox niet openen; zou hij dat toch doen, dan valt het op.
    import funda_mail_ophalen as fmo

    mailbox: list[str] = []
    origineel = (fhz.HtmlZoeker, fmo.mail_config, fmo.haal_mail_teksten)
    os.environ["FUNDA_ZOEK_METHODE"] = "auto"
    fsz.SitemapZoeker, fhz.HtmlZoeker = Z, Dicht
    fmo.mail_config = lambda _personal=None: {"host": "imap.example", "gebruiker": "x",
                                              "wachtwoord": "y", "map_naam": ""}
    fmo.haal_mail_teksten = lambda **_kw: mailbox.append("geopend") or []
    try:
        with contextlib.redirect_stdout(io.StringIO()) as uit:
            code, gedraaid = draai(fz)
    finally:
        fsz.SitemapZoeker = echt
        fhz.HtmlZoeker, fmo.mail_config, fmo.haal_mail_teksten = origineel
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
    ok &= check("auto, niets werkt: exit 2 zonder rapport", code == 2 and not gedraaid, str(code))
    ok &= check("auto, niets werkt: sitemap-index één keer geprobeerd",
                web.calls.count(ts.INDEX_URL) == 1, str(web.calls))
    ok &= check("auto, niets werkt: oorzaken in de ::error",
                "::error::Geen enkele zoekbron werkt" in uit.getvalue())
    ok &= check("auto, niets werkt: mailbox niet geopend", not mailbox, str(mailbox))
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
    # Ingetrokken: het endpoint geeft een 404 (pyfunda: LookupError).
    details["44000098"] = {"global_id": 1098, "tiny_id": "44000098", "_status": 404}
    vandaag = datetime.now().strftime("%Y-%m-%d")
    url = "https://www.funda.nl/detail/koop"
    tracking = {
        # Te duur geworden: de zoeker haalt hem op (run 1) of slaat hem over (run 2).
        "1002": {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-koningin-emmakade-185/44664520/"},
        # Staat in de sitemap, maar valt buiten het verkenbudget: de pool haalt hem.
        "1003": {"last_seen": vandaag, "url": f"{url}/voorburg/appartement-rodelaan-379/44546400/"},
        # Niet meer in de sitemap, en verkocht.
        "1099": {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-weg-9/44000099/"},
        # Niet meer in de sitemap, en ingetrokken (404). De pool zelf heeft geen
        # geslaagde call vóór deze; de zoeker wel, en dat telt als bewijs.
        "1098": {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-ingetrokken-8/44000098/"},
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
    ok &= check("run 1: zoeker 2 verkend, pool 1 achterstand + 2 controle",
                sorted(per1) == ["44000098", "44000099", "44546400", "44664520", "80024814"], str(per1))
    ok &= check("run 1: rapport met de twee woningen in de doelmarkt",
                r1["titels"] == ["Draaistraat 4", "Rodelaan 379"], str(r1["titels"]))
    ok &= check("run 1: verkochte woning buiten de sitemap als weg gemarkeerd",
                bool(r1["tracking"]["1099"].get("weg")), str(r1["tracking"]["1099"]))
    ok &= check("run 1: ingetrokken woning (404) buiten de sitemap meteen weg",
                bool(r1["tracking"]["1098"].get("weg")), str(r1["tracking"]["1098"]))
    ok &= check("run 1: woning uit de achterstand vastgelegd in de sitemapcache",
                "44546400" in json.loads(r1["cache"])["woningen"])
    ok &= check("run 1: telling in de log",
                "(waarvan dezelfde woning nog eens: 0)" in r1["log"]
                and "2 niet meer in de sitemap" in r1["log"])

    per2 = Counter(woning(c) for c in r2["calls"])
    ok &= check("run 2 normaal afgerond", r2["code"] is None, str(r2["code"]))
    ok &= check("run 2: alleen de twee in de doelmarkt ververst, elk één keer",
                per2 == Counter({"80024814": 1, "44546400": 1}), str(per2))
    ok &= check("run 2: te dure woning op cache overgeslagen, ook door de pool",
                "1 op cache overgeslagen" in r2["log"])
    ok &= check("run 2: koop-sitemaps niet opnieuw opgehaald",
                "koop-sitemaps niet opnieuw opgehaald" in r2["log"])
    return ok


def _sitemaprun(details, tracking=None, *, faal_na=None, budget=2):
    """Eén volledige main()-run met de echte SitemapZoeker op de fixture."""
    import funda_sitemap_zoek as fsz
    import test_funda_sitemap as ts

    calls: list[str] = []
    fz = maak_stub_funda(lambda _n: [], details=details, calls=calls, faal_na=faal_na)
    if tracking is not None:
        fz.TRACKING_FILE.write_text(json.dumps(tracking))
    oud_budget, fz.SITEMAP_MAX_VERKENNEN = fz.SITEMAP_MAX_VERKENNEN, budget
    echt, Z = _sitemap_met(ts.StubWeb())
    oude_sleep = time.sleep
    gezien = {}

    def rapport(_client, goed, _nieuw):
        gezien["titels"] = sorted(d.get("title") for d in goed)
        return Path("rapport.html")

    fz.genereer_rapport = rapport
    os.environ["FUNDA_ZOEK_METHODE"] = "sitemap"
    fsz.SitemapZoeker = Z
    try:
        time.sleep = lambda _s: None
        with contextlib.redirect_stdout(io.StringIO()) as uit:
            try:
                fz.main()
                code = None
            except SystemExit as exc:
                code = exc.code
    finally:
        time.sleep = oude_sleep
        fsz.SitemapZoeker = echt
        fz.SITEMAP_MAX_VERKENNEN = oud_budget
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
    trk = json.loads(fz.TRACKING_FILE.read_text()) if fz.TRACKING_FILE.exists() else {}
    return {"code": code, "calls": calls, "titels": gezien.get("titels"), "log": uit.getvalue(),
            "tracking": trk, "rapport": "titels" in gezien,
            "cache": fz.SITEMAP_CACHE_FILE.read_text() if fz.SITEMAP_CACHE_FILE.exists() else ""}


def test_pool_404_bovenaan() -> bool:
    """Vijf ingetrokken woningen (404) bovenaan de pool laten de pool niet afbreken.

    Eerder telde een 404 als storing: na vijf brak de pool af ("detail-endpoint
    lijkt dicht"), en Rodelaan (achterstand, gisteren gezien) kwam niet in het
    rapport terwijl het endpoint gewoon werkte.
    """
    print("test: vijf 404's bovenaan de pool, daarna een woning uit de achterstand")
    import test_funda_sitemap as ts
    from datetime import timedelta

    details = {k: {**v, "tiny_id": k} for k, v in ts.DETAILS.items()}
    vandaag = datetime.now().strftime("%Y-%m-%d")
    gisteren = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://www.funda.nl/detail/koop"
    tracking = {"1003": {"last_seen": gisteren, "url": f"{url}/voorburg/appartement-rodelaan-379/44546400/"}}
    for i in range(5):
        details[f"4400009{i}"] = {"_status": 404}
        tracking[f"109{i}"] = {"last_seen": vandaag, "url": f"{url}/den-haag/appartement-weg-{i}/4400009{i}/"}
    r = _sitemaprun(details, tracking)
    ok = check("geen afbreking", r["code"] is None and "lijkt dicht" not in r["log"], str(r["code"]))
    ok &= check("Rodelaan uit de achterstand staat in het rapport",
                r["titels"] == ["Draaistraat 4", "Rodelaan 379"], str(r["titels"]))
    ok &= check("de vijf ingetrokken woningen zijn weg",
                all(r["tracking"][f"109{i}"].get("weg") for i in range(5)))

    # Volgende run: de vijf kosten geen call meer.
    r2 = _sitemaprun(details, r["tracking"])
    ok &= check("volgende run: geen call meer voor de ingetrokken woningen",
                not any("4400009" in c for c in r2["calls"]), str(r2["calls"]))
    return ok


def test_endpoint_halverwege_dicht() -> bool:
    """Het detail-endpoint gaat tijdens de run dicht: exit 2, geen (half) rapport.

    pyfunda maakt van een 403 halverwege een LookupError; de Funda-subklasse
    herkent de status. Bij fouten zonder status (time-outs) telt de pool door
    vanaf de zoeker, en een run die op fouten eindigt, publiceert niets.
    """
    print("test: detail-endpoint gaat halverwege de run dicht")
    import test_funda_sitemap as ts

    details = {k: {**v, "tiny_id": k} for k, v in ts.DETAILS.items()}
    ok = True
    for naam, faal_na in (("403 na één call", (1, 403)), ("429 na één call", (1, 429)),
                          ("time-outs na één call", (1, None))):
        r = _sitemaprun(details, {}, faal_na=faal_na, budget=200)
        ok &= check(f"{naam}: exit 2", r["code"] == 2, str(r["code"]))
        ok &= check(f"{naam}: geen rapport", not r["rapport"])
        ok &= check(f"{naam}: ::error in de log", "::error::" in r["log"], r["log"][-300:])
        ok &= check(f"{naam}: geslaagde verkenning bewaard",
                    "80024814" in (json.loads(r["cache"] or "{}").get("woningen") or {}))
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
    """Stap f: een lege workflow-input valt terug op de standaard van 200, en
    meer dan 600 per run gaat niet."""
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
        # Plafond uit het besluit van 6 nov 2026: hooguit 600 per run.
        with contextlib.redirect_stdout(io.StringIO()) as uit:
            begrensd = fz._begrens_verkennen(5000)
        ok &= check("boven het plafond -> 600, met waarschuwing",
                    begrensd == 600 and "plafond" in uit.getvalue(), str(begrensd))
        ok &= check("op of onder het plafond ongewijzigd",
                    fz._begrens_verkennen(600) == 600 and fz._begrens_verkennen(200) == 200)
    finally:
        fz._PERSONAL.pop("sitemap_max_verkennen", None)
        if oud is None:
            os.environ.pop("FUNDA_SITEMAP_MAX_VERKENNEN", None)
        else:
            os.environ["FUNDA_SITEMAP_MAX_VERKENNEN"] = oud
    return ok


EERLIJK_PROEF = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import funda.funda as pf
import funda_zoek as fz

uit = {"pool_lengte": len(pf.FINGERPRINT_POOL)}
getest = []
pf.Funda._test_fingerprint = lambda self, fp: getest.append(fp) or True


class Antwoord:
    def __init__(self, status):
        self.status_code = status
        self._data = ({"Identifiers": {"GlobalId": 7654321, "TinyId": "43117443"},
                       "AddressDetails": {"Title": "Teststraat 1", "City": "Den Haag"}}
                      if status == 200 else {})
        self.text = json.dumps(self._data)
        self.headers = {}

    def json(self):
        return self._data


class Sessie:
    def __init__(self, statussen):
        self.statussen = list(statussen)
        self.verzoeken = []

    def request(self, methode, url, **kw):
        self.verzoeken.append({"methode": methode, "url": url,
                               **{k: v for k, v in kw.items() if k != "json"}})
        return Antwoord(self.statussen.pop(0))


def probeer(statussen):
    f = fz.Funda()
    f._eerlijke_sessie = Sessie(statussen)
    try:
        listing = f.get_listing("https://www.funda.nl/detail/koop/den-haag/appartement-teststraat-1/43117443/")
        uitkomst = ["ok", listing.data.get("title")]
    except Exception as exc:
        uitkomst = [type(exc).__name__, [c.__name__ for c in type(exc).__mro__]]
    return uitkomst, f._eerlijke_sessie.verzoeken


uit["ok"], verzoeken = probeer([200])
uit["headers"] = verzoeken[0]["headers"]
uit["argumenten"] = sorted(verzoeken[0])
uit["host"] = verzoeken[0]["url"].split("/")[2]
for status in (403, 429, 401, 500):
    uit[str(status)], _ = probeer([status])
uit["404"], v404 = probeer([404, 404])
uit["n404"] = len(v404)
uit["getest"] = len(getest)

f = fz.Funda()
f._eerlijke_sessie = Sessie([401])
try:
    f.search_listing(location="2511cv", page=0)
except Exception as exc:
    uit["zoek_fout"] = type(exc).__name__
zoek = f._eerlijke_sessie.verzoeken[0]
uit["zoek_headers"] = zoek["headers"]
uit["zoek_template_nieuw"] = "search_result_20260227" in str(zoek.get("data", ""))
try:
    fz.Funda()._find_working_fingerprint()
    uit["zoekt_vingerafdruk"] = True
except RuntimeError:
    uit["zoekt_vingerafdruk"] = False
print(json.dumps(uit, default=str))
"""


def test_eerlijke_client() -> bool:
    """Eén gewone client: geen app-vingerafdruk, geen app-headers, eigen user-agent.

    Tegen het echte pyfunda (zonder netwerk: de sessie is nep). pyfunda doet zich
    zelf voor als funda's Android-app en wisselt bij een weigering van
    vingerafdruk; de subklasse in funda_zoek.py doet geen van beide, en vertaalt
    pyfunda's LookupError naar de status die het endpoint gaf.
    """
    print("test: eerlijke client en statuscodes (tegen het echte pyfunda)")
    hier = str(Path(__file__).parent.resolve())
    proces = subprocess.run([sys.executable, "-c", EERLIJK_PROEF, hier],
                            capture_output=True, text=True, cwd=hier, timeout=120)
    regels = [r for r in proces.stdout.splitlines() if r.startswith("{")]
    if proces.returncode != 0 or not regels:
        return check("proef draait", False, (proces.stderr or proces.stdout)[-400:])
    uit = json.loads(regels[-1])
    headers = {k.lower(): v for k, v in uit["headers"].items()}
    ok = check("detail-call slaagt", uit["ok"] == ["ok", "Teststraat 1"], str(uit["ok"]))
    ok &= check("eigen user-agent, geen app-UA",
                headers.get("user-agent", "").startswith("funda-dagelijkse-check/")
                and "dart" not in headers.get("user-agent", "").lower(), str(headers))
    ok &= check("geen app- of traceheaders",
                not any(h.startswith(("x-funda", "x-datadog", "traceparent", "tracestate"))
                        for h in headers), str(sorted(headers)))
    ok &= check("geen impersonate of JA3 bij het verzoek",
                not {"impersonate", "ja3", "akamai", "extra_fp"} & set(uit["argumenten"]),
                str(uit["argumenten"]))
    ok &= check("naar het detail-endpoint", uit["host"] == "listing-detail-page.funda.io", uit["host"])
    ok &= check("nooit een vingerafdruk getest of gezocht",
                uit["getest"] == 0 and uit["zoekt_vingerafdruk"] is False)
    for status in ("403", "429", "401"):
        ok &= check(f"{status}: DetailEndpointDicht (een RuntimeError)",
                    uit[status][0] == "DetailEndpointDicht" and "RuntimeError" in uit[status][1],
                    str(uit[status]))
    ok &= check("404: WoningNietGevonden (een LookupError), na pyfunda's tweede poging",
                uit["404"][0] == "WoningNietGevonden" and "LookupError" in uit["404"][1]
                and uit["n404"] == 2, str(uit["404"]))
    ok &= check("500: gewone LookupError (telt als storing)", uit["500"][0] == "LookupError",
                str(uit["500"]))
    zoek = {k.lower(): v for k, v in uit["zoek_headers"].items()}
    ok &= check("zoek-API: zelfde eerlijke client, met de gepatchte template",
                zoek.get("user-agent", "").startswith("funda-dagelijkse-check/")
                and "referer" not in zoek and uit["zoek_template_nieuw"], str(zoek))
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

    # Storing: alles faalt. Dan stoppen (main() maakt er exit 2 van), en mag er
    # niets als weg gemarkeerd worden, ook niet bij een woning die al twee
    # mislukkingen had.
    class Dicht:
        def __init__(self):
            self.calls = 0

        def get_listing(self, ident):
            self.calls += 1
            raise LookupError("time-out")

    tracking2 = {str(1000100 + i): {"last_seen": vandaag, "pool_fout": 2} for i in range(8)}
    dicht = Dicht()
    try:
        fz.controleer_pool(fz.DetailCacheZoeker(dicht), tracking2, set(), dagen=120, maximum=50, pauze=0)
        ok &= check("storing: DetailEndpointDicht", False)
    except fz.DetailEndpointDicht:
        ok &= check("storing: DetailEndpointDicht na vijf calls op rij", dicht.calls == 5, str(dicht.calls))
    ok &= check("storing: niets als weg gemarkeerd",
                not any(r.get("weg") for r in tracking2.values()))
    ok &= check("storing: teller niet opgehoogd",
                all(r.get("pool_fout") == 2 for r in tracking2.values()))

    # Een geweigerde client (403/429): meteen stoppen.
    class Weigert:
        def __init__(self):
            self.calls = 0

        def get_listing(self, ident):
            self.calls += 1
            raise fz.DetailEndpointDicht("status 403")

    weigert = Weigert()
    try:
        fz.controleer_pool(fz.DetailCacheZoeker(weigert), dict(tracking2), set(),
                           dagen=120, maximum=50, pauze=0)
        ok &= check("weigering: meteen stoppen", False)
    except fz.DetailEndpointDicht:
        ok &= check("weigering: meteen stoppen", weigert.calls == 1, str(weigert.calls))

    # Nette 404's (WoningNietGevonden): het endpoint werkt, dus geen storing,
    # ook niet als het er meer dan vijf op rij zijn.
    class Weg:
        def get_listing(self, ident):
            raise fz.WoningNietGevonden(f"Listing {ident} niet gevonden (status [404])")

    tracking3 = {str(1000200 + i): {"last_seen": vandaag, "pool_fout": 2} for i in range(7)}
    res3 = fz.controleer_pool(fz.DetailCacheZoeker(Weg()), tracking3, set(),
                              dagen=120, maximum=50, pauze=0)
    ok &= check("zeven 404's: geen afbreking, niets terug", res3 == [])
    ok &= check("zeven 404's: derde keer niet gevonden = weg",
                all(r.get("weg") for r in tracking3.values()))

    # De run eindigt met mislukte calls (endpoint ging net dicht): stoppen, en
    # niets als weg markeren, ook niet wat eerder in de run mislukte.
    class EindDicht:
        def __init__(self):
            self.n = 0

        def get_listing(self, ident):
            self.n += 1
            if self.n == 1:
                raise fz.WoningNietGevonden("niet gevonden")
            if self.n == 2:
                return StubListing({"global_id": ident, "status": "available"})
            raise LookupError("time-out")

    tracking4 = {str(1000300 + i): {"last_seen": vandaag, "pool_fout": 2} for i in range(4)}
    try:
        fz.controleer_pool(fz.DetailCacheZoeker(EindDicht()), tracking4, set(),
                           dagen=120, maximum=50, pauze=0)
        ok &= check("eindigt met storing: stoppen", False)
    except fz.DetailEndpointDicht as exc:
        ok &= check("eindigt met storing: stoppen", "laatste 2" in str(exc), str(exc))
    ok &= check("eindigt met storing: niets als weg gemarkeerd",
                not any(r.get("weg") for r in tracking4.values()))
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
                  test_prijs_onbekend_rapport(), test_auto_keten(), test_stadfilter(),
                  test_woningtypefilter(), test_zoekcriteria(), test_beschikbaarheid(),
                  test_pool(), test_pool_in_run(), test_sitemapbron_faalt_luid(),
                  test_geen_dubbele_detail_calls(), test_pool_404_bovenaan(),
                  test_endpoint_halverwege_dicht(), test_sitemap_overslaan(), test_instellingen(),
                  test_eerlijke_client()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
