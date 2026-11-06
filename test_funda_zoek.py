"""Offline tests voor de veiligheidschecks in funda_zoek.main(). Geen netwerk.

Deze checks bestaan omdat een stukke zoekmethode er precies hetzelfde uitziet als
een lege markt, en een lege run het gevulde rapport zou overschrijven.

Draaien: python test_funda_zoek.py
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# Deze tests gaan over de checks in main(), niet over de zoekmethode. Vastzetten
# op 'api' houdt ze offline: 'auto' zou bij een falende API de HTML-route pakken
# en dan alsnog het netwerk op willen.
os.environ["FUNDA_ZOEK_METHODE"] = "api"

SCRATCH = Path(__file__).parent / ".test_tmp"


class StubListing:
    def __init__(self, data):
        self.data = data


def maak_stub_funda(zoek_gedrag):
    """Installeer een nep-funda-module vóór funda_zoek geïmporteerd wordt."""
    mod = types.ModuleType("funda")

    class F:
        def __init__(self, *a, **k):
            self.n = 0

        def search_listing(self, *a, **k):
            self.n += 1
            return zoek_gedrag(self.n)

        def get_listing(self, ident):
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
    # Geen Nominatim in offline tests: zonder thuiscoördinaten slaat het
    # afstandsfilter over. Tests die het filter willen, zetten dit zelf.
    fz._THUIS["v"] = None
    for p in (fz.STATE_FILE, fz.TRACKING_FILE):
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


def test_auto_keten() -> bool:
    """'auto' moet api -> html -> mail aflopen, en terugschakelen zodra iets werkt."""
    print("test: auto kiest de eerste werkende zoekmethode")
    import funda_html_zoek as fhz

    fz = maak_stub_funda(lambda _n: [])
    ok = True

    class ApiOk:
        def search_listing(self, *a, **k):
            return []

    class ApiDicht:
        def search_listing(self, *a, **k):
            raise RuntimeError("Search failed (status 401)")

    class StubHtml:
        bereik = False

        def __init__(self, *a, **k):
            pass

        def bereikbaar(self):
            return StubHtml.bereik

    origineel_html = fhz.HtmlZoeker
    origineel_mail = fz._woningen_uit_mailbox
    os.environ["FUNDA_ZOEK_METHODE"] = "auto"
    try:
        fhz.HtmlZoeker = StubHtml

        # 1. API antwoordt: dan niets anders proberen.
        fz._woningen_uit_mailbox = lambda: [("/detail/koop/x/y/44500000/", "44500000")]
        _, methode = fz.kies_zoeker(ApiOk())
        ok &= check("API werkt -> api", methode == "api", methode)

        # 2. API dicht, zoekpagina laat door.
        StubHtml.bereik = True
        _, methode = fz.kies_zoeker(ApiDicht())
        ok &= check("API dicht, HTML open -> html", methode == "html", methode)

        # 3. Beide dicht, maar er zitten woningen in de mail.
        StubHtml.bereik = False
        _, methode = fz.kies_zoeker(ApiDicht())
        ok &= check("API en HTML dicht -> mail", methode == "mail", methode)

        # 4. Beide dicht en geen mailroute ingericht: dan NIET 'mail' kiezen. Een
        # lege mailbron laat de run vallen op de nul-woningen-check met een
        # melding over een stukke zoekmethode, terwijl de echte oorzaak is dat er
        # geen mailroute is. 'html' faalt op de 403, en dat is de echte oorzaak.
        fz._woningen_uit_mailbox = lambda: []
        _, methode = fz.kies_zoeker(ApiDicht())
        ok &= check("alles dicht, geen mail -> html (faalt luid)",
                    methode == "html", methode)

        # 5. Afdwingen blijft werken, ook zonder dat er iets bereikbaar is.
        for gedwongen in ("api", "html", "mail"):
            os.environ["FUNDA_ZOEK_METHODE"] = gedwongen
            _, methode = fz.kies_zoeker(ApiDicht())
            ok &= check(f"afgedwongen {gedwongen}", methode == gedwongen, methode)

        # 6. Onzin in de config mag niet crashen; dat valt terug op auto.
        os.environ["FUNDA_ZOEK_METHODE"] = "telepathie"
        StubHtml.bereik = True
        _, methode = fz.kies_zoeker(ApiDicht())
        ok &= check("onbekende methode valt terug op auto", methode == "html", methode)
    finally:
        fhz.HtmlZoeker = origineel_html
        fz._woningen_uit_mailbox = origineel_mail
        os.environ["FUNDA_ZOEK_METHODE"] = "api"
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
    resultaten = [test_alles_faalt(), test_stille_lege_oogst(), test_normale_run(),
                  test_auto_keten(), test_stadfilter(),
                  test_woningtypefilter(), test_zoekcriteria(), test_beschikbaarheid(),
                  test_pool(), test_pool_in_run()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
