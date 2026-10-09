"""Offline tests voor de mailbron. Geen netwerk nodig.

Let op de grens: het URL-patroon en de detail-verrijking rusten op meting, de
exacte opmaak van funda's notificatiemail niet (die mail bestond nog niet toen
dit werd geschreven). De fixtures hieronder dekken de vormen die redelijkerwijs
voorkomen; `scripts/funda_mail_validatie.py` controleert tegen een echte mail.

Draaien: python test_funda_mail.py
"""

from __future__ import annotations

import sys

from funda_mail_bron import MailBron, vind_woning_links

# Directe links, zoals funda ze in de mail zou kunnen zetten.
MAIL_DIRECT = """
<html><body>
<p>Nieuw aanbod voor je zoekopdracht</p>
<a href="https://www.funda.nl/detail/koop/den-haag/appartement-jonckbloetplein-30/44576894/">
  Jonckbloetplein 30</a>
<a href="https://www.funda.nl/detail/koop/voorburg/appartement-rodelaan-139/44564274/">
  Rodelaan 139</a>
<a href="https://www.funda.nl/mijn-funda/zoekopdrachten/">Beheer je zoekopdrachten</a>
</body></html>
"""

# Tracking-redirect met de echte URL url-encoded in een parameter.
MAIL_TRACKING = """
<html><body>
<a href="https://click.funda.nl/f/a/abc123/?url=https%3A%2F%2Fwww.funda.nl%2Fdetail%2Fkoop%2Fden-haag%2Fappartement-margarethaland-189%2F44575523%2F&amp;t=1">
  Margarethaland 189</a>
<a href="https://click.funda.nl/f/a/def456/?url=https%3A%2F%2Fwww.funda.nl%2Fdetail%2Fkoop%2Frijswijk%2Fappartement-generaal-spoorlaan-12%2F44511111%2F">
  Generaal Spoorlaan 12</a>
</body></html>
"""

# Plattetekstversie van dezelfde mail.
MAIL_PLAT = """
Nieuw aanbod:
Jonckbloetplein 30, Den Haag
https://www.funda.nl/detail/koop/den-haag/appartement-jonckbloetplein-30/44576894/
"""

MAIL_ZONDER = "<html><body><p>Geen nieuwe woningen deze week.</p></body></html>"


class StubListing:
    def __init__(self, data):
        self.data = data


class StubClient:
    def __init__(self, faal_op: set[str] | None = None):
        self.calls: list[str] = []
        self.faal_op = faal_op or set()

    def get_listing(self, ident):
        self.calls.append(str(ident))
        for stuk in self.faal_op:
            if stuk in str(ident):
                raise RuntimeError("detail stuk")
        tiny = "".join(c for c in str(ident).split("/")[-2] if c.isdigit())
        return StubListing({
            "global_id": f"g{tiny}", "tiny_id": tiny, "city": "Den Haag",
            "neighbourhood": "Bomenbuurt", "price": 299000, "living_area": 73,
            "energy_label": "C", "title": "Teststraat 1",
            "description": "Licht appartement met balkon op de derde verdieping.",
        })


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return voorwaarde


def test_links_direct() -> bool:
    print("test: directe links uit de mail")
    ok = True
    links = vind_woning_links(MAIL_DIRECT)
    ok &= check("twee woningen", len(links) == 2, str(len(links)))
    if len(links) == 2:
        ok &= check("tiny_ids", [t for _, t in links] == ["44576894", "44564274"],
                    str([t for _, t in links]))
        ok &= check("pad eindigt op slash", all(p.endswith("/") for p, _ in links))
    ok &= check("beheerlink niet meegerekend",
                all("zoekopdrachten" not in p for p, _ in links))
    return ok


def test_links_tracking() -> bool:
    print("test: links in een tracking-redirect")
    ok = True
    links = vind_woning_links(MAIL_TRACKING)
    ok &= check("twee woningen uit redirects", len(links) == 2, str(len(links)))
    if len(links) == 2:
        ok &= check("tiny_ids", [t for _, t in links] == ["44575523", "44511111"],
                    str([t for _, t in links]))
        ok &= check("pad is schoon, geen %2F", all("%2F" not in p for p, _ in links),
                    str(links[0][0]))
    return ok


def test_links_overig() -> bool:
    print("test: platte tekst, leeg, en dedup")
    ok = True
    ok &= check("plattetekstmail", len(vind_woning_links(MAIL_PLAT)) == 1)
    ok &= check("mail zonder woningen", vind_woning_links(MAIL_ZONDER) == [])
    ok &= check("leeg invoer", vind_woning_links("") == [])
    # Zelfde woning twee keer (HTML-link plus plattetekst) mag één keer tellen.
    dubbel = MAIL_DIRECT + MAIL_PLAT
    links = vind_woning_links(dubbel)
    ok &= check("dedup op tiny_id", len(links) == 2, str(len(links)))
    return ok


def test_bron() -> bool:
    print("test: MailBron als drop-in")
    ok = True
    client = StubClient()
    bron = MailBron(client, vind_woning_links(MAIL_DIRECT), pauze=0, log=lambda b: None)

    res = bron.search_listing(location="genegeerd", price_min=1, page=0)
    ok &= check("twee resultaten", len(res) == 2, str(len(res)))
    ok &= check("data-vorm", all(hasattr(r, "data") for r in res))
    eerste = res[0].data
    ok &= check("buurt uit detail", eerste.get("neighbourhood") == "Bomenbuurt")
    ok &= check("bron gemarkeerd", eerste.get("_bron") == "mail")

    # Tweede aanroep (andere prijsband/sortering) moet leeg zijn, anders blijft
    # de pagineerlus in funda_zoek.py doorgaan.
    ok &= check("tweede aanroep leeg", bron.search_listing(page=0) == [])
    ok &= check("pagina 1 leeg", bron.search_listing(page=1) == [])

    voor = len(client.calls)
    bron.get_listing(eerste["global_id"])
    ok &= check("get_listing uit cache", len(client.calls) == voor,
                f"{voor} -> {len(client.calls)}")

    # Mislukte detail-call: woning overslaan, niet half gevuld doorlaten.
    client2 = StubClient(faal_op={"44564274"})
    bron2 = MailBron(client2, vind_woning_links(MAIL_DIRECT), pauze=0)
    ok &= check("kapotte detail overgeslagen", len(bron2.search_listing()) == 1)

    # Lege maillijst mag geen resultaten geven; de nul-woningen-check in
    # funda_zoek.py laat de run dan falen in plaats van leeg te publiceren.
    bron3 = MailBron(StubClient(), [], pauze=0)
    ok &= check("lege maillijst geeft niets", bron3.search_listing() == [])
    return ok


def test_delegatie() -> bool:
    print("test: onbekende methodes vallen door naar de client")
    class Rijk(StubClient):
        def get_price_history(self, ident):
            return [{"prijs": 1}]

    bron = MailBron(Rijk(), [], pauze=0)
    ok = check("get_price_history bereikbaar", bron.get_price_history("x") == [{"prijs": 1}])
    try:
        bron.bestaat_niet()
        ok &= check("onbekend geeft AttributeError", False)
    except AttributeError:
        ok &= check("onbekend geeft AttributeError", True)
    return ok


def main() -> int:
    resultaten = [
        test_links_direct(), test_links_tracking(), test_links_overig(),
        test_bron(), test_delegatie(),
    ]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
