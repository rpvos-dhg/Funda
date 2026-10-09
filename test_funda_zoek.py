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


def main() -> int:
    resultaten = [test_alles_faalt(), test_stille_lege_oogst(), test_normale_run(),
                  test_auto_keten()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
