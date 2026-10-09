"""Offline tests voor het IMAP-transport van de mailroute. Geen mailbox nodig.

Het zwaartepunt ligt op `tekst_uit_mail()`: een echte funda-mail is multipart met
quoted-printable of base64 gecodeerde delen, en daar gaan URL's stuk als je de
ruwe bytes leest. Deze tests bouwen zulke mails met de stdlib na, dus de codering
is echt en niet nagedaan.

Draaien: python test_funda_mail_ophalen.py
"""

from __future__ import annotations

import sys
from email.message import EmailMessage

from funda_mail_bron import vind_woning_links
from funda_mail_ophalen import (
    _eerste_payload,
    _imap_datum,
    haal_mail_teksten,
    kies_map,
    mail_config,
    tekst_uit_mail,
)

WONING = "https://www.funda.nl/detail/koop/den-haag/appartement-teststraat-1/44576894/"


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return voorwaarde


def bouw_mail(*, plat: str | None, html: str | None, charset: str = "utf-8") -> bytes:
    """Een multipart/alternative mail, door de stdlib echt gecodeerd."""
    bericht = EmailMessage()
    bericht["From"] = "notificaties@service.funda.nl"
    bericht["To"] = "iemand@example.com"
    bericht["Subject"] = "Nieuw aanbod voor je zoekopdracht"
    bericht.set_content(plat or "", charset=charset)
    if html is not None:
        bericht.add_alternative(html, subtype="html", charset=charset)
    return bericht.as_bytes()


def test_decoderen() -> bool:
    print("test: mailtekst decoderen")
    ok = True

    # Lange regel met een URL erin: quoted-printable breekt die op met '=' aan
    # het eind. Komt de URL er heel uit, dan werkt de decodering.
    lang = ("Nieuw aanbod in jouw zoekopdracht, bekijk het hier: "
            f"{WONING} en nog veel meer tekst om de regel over de 76 tekens "
            "heen te duwen zodat er echt gecodeerd moet worden.")
    ruw = bouw_mail(plat=lang, html=f'<a href="{WONING}">Teststraat 1</a>')

    # Zonder echte codering test de rest hieronder niets, dus dit eerst vastpinnen.
    # Welke codering de stdlib kiest hangt af van de inhoud: quoted-printable
    # breekt regels af met '=' aan het eind, base64 herkodeert alles.
    ok &= check("ruwe bytes zijn gecodeerd",
                b"=\n" in ruw or b"=\r\n" in ruw or b"base64" in ruw.lower(),
                "anders test deze test niets")
    # Dit is de kern: op de ruwe bytes vindt de parser de woning niet.
    rauw_gevonden = vind_woning_links(ruw.decode("utf-8", errors="replace"))
    tekst = tekst_uit_mail(ruw)
    ok &= check("gedecodeerd vindt de parser de woning",
                len(vind_woning_links(tekst)) == 1,
                str(vind_woning_links(tekst)))
    if not rauw_gevonden:
        print("       (en op de ruwe bytes niet - precies waarom dit nodig is)")

    ok &= check("zowel plat als html erin",
                "Nieuw aanbod" in tekst and "<a href" in tekst)

    # Andere charset mag niet omvallen. Geen euroteken: dat zit niet in
    # iso-8859-1, dus daar struikelt het bouwen al over.
    tekst_latin = tekst_uit_mail(bouw_mail(plat="Ruime woning bij een café",
                                           html=None, charset="iso-8859-1"))
    ok &= check("iso-8859-1 blijft leesbaar", "café" in tekst_latin, tekst_latin.strip())

    ok &= check("lege input", tekst_uit_mail(b"") == "")
    # Losse tekst zonder mailheaders mag niet leiden tot verlies van de inhoud.
    ok &= check("niet-mail valt terug op ruwe tekst",
                WONING in tekst_uit_mail(WONING.encode()))
    return ok


def test_imap_datum() -> bool:
    print("test: IMAP-datumnotatie")
    datum = _imap_datum(3)
    ok = check("vorm dd-Mon-jjjj", len(datum.split("-")) == 3, datum)
    maand = datum.split("-")[1]
    ok &= check("Engelse maandafkorting",
                maand in ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), maand)
    ok &= check("negatieve dagen geven geen fout", bool(_imap_datum(-5)))
    return ok


def test_payload_vissen() -> bool:
    print("test: payload uit een imaplib-antwoord vissen")
    ok = True
    ok &= check("tuple-vorm", _eerste_payload([(b"1 (RFC822 {5}", b"hallo")]) == b"hallo")
    ok &= check("losse bytes", _eerste_payload([b"flags", b"langere inhoud"]) is not None)
    ok &= check("leeg antwoord", _eerste_payload([]) is None)
    ok &= check("None", _eerste_payload(None) is None)
    return ok


class StubImap:
    """Genoeg imaplib om haal_mail_teksten te laten draaien."""

    # Zoals Gmail het teruggeeft: de "alle mail"-map heet hier Nederlands, zodat
    # de test aantoont dat er op de vlag en niet op de naam gezocht wordt.
    LIST_GMAIL = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
        b'(\\All \\HasNoChildren) "/" "[Gmail]/Alle berichten"',
        b'(\\Trash \\HasNoChildren) "/" "[Gmail]/Prullenbak"',
    ]

    def __init__(self, ids: bytes = b"1 2", *, zoek_status: str = "OK",
                 fetch_status: str = "OK", faal_op_sluiten: bool = False,
                 lijst: list[bytes] | None = None, lijst_status: str = "OK",
                 select_status: str = "OK"):
        self.ids = ids
        self.zoek_status = zoek_status
        self.fetch_status = fetch_status
        self.faal_op_sluiten = faal_op_sluiten
        self.lijst = self.LIST_GMAIL if lijst is None else lijst
        self.lijst_status = lijst_status
        self.select_status = select_status
        self.acties: list[str] = []
        self.criterium = ""
        self.gekozen_map = ""

    def login(self, gebruiker, wachtwoord):
        self.acties.append(f"login:{gebruiker}")

    def list(self, *_a, **_k):
        self.acties.append("list")
        return self.lijst_status, self.lijst

    def select(self, map_naam):
        self.acties.append(f"select:{map_naam}")
        self.gekozen_map = map_naam
        return self.select_status, [b"42"]

    def search(self, charset, criterium):
        self.criterium = criterium
        self.acties.append("search")
        return self.zoek_status, [self.ids]

    def fetch(self, mail_id, spec):
        self.acties.append(f"fetch:{mail_id.decode()}")
        mail = bouw_mail(plat=f"Woning {mail_id.decode()}: {WONING}", html=None)
        return self.fetch_status, [(b"x", mail)]

    def close(self):
        if self.faal_op_sluiten:
            raise RuntimeError("close stuk")
        self.acties.append("close")

    def logout(self):
        if self.faal_op_sluiten:
            raise RuntimeError("logout stuk")
        self.acties.append("logout")


def test_ophalen() -> bool:
    print("test: haal_mail_teksten tegen een stub-mailbox")
    ok = True
    stub = StubImap(ids=b"1 2")
    teksten = haal_mail_teksten(host="imap.example.com", gebruiker="ik@example.com",
                                wachtwoord="geheim", verbinden=lambda _h: stub)
    ok &= check("twee mails", len(teksten) == 2, str(len(teksten)))
    ok &= check("inhoud gedecodeerd", all(WONING in t for t in teksten))
    ok &= check("nieuwste eerst", teksten and "Woning 2" in teksten[0],
                teksten[0][:40] if teksten else "")
    ok &= check("afzenderfilter in criterium", 'FROM "funda.nl"' in stub.criterium,
                stub.criterium)
    ok &= check("SINCE in criterium", "SINCE" in stub.criterium)
    ok &= check("netjes afgesloten", "logout" in stub.acties, str(stub.acties))

    # Lege mailbox: geen fout, geen woningen.
    leeg = StubImap(ids=b"")
    ok &= check("lege mailbox", haal_mail_teksten(
        host="h", gebruiker="g", wachtwoord="w", verbinden=lambda _h: leeg) == [])

    # Mislukte zoekopdracht hoort te knallen, niet stil leeg te zijn: anders
    # lijkt een kapotte mailbox op een week zonder nieuw aanbod.
    stuk = StubImap(zoek_status="NO")
    try:
        haal_mail_teksten(host="h", gebruiker="g", wachtwoord="w",
                          verbinden=lambda _h: stuk)
        ok &= check("mislukte zoekopdracht geeft RuntimeError", False)
    except RuntimeError:
        ok &= check("mislukte zoekopdracht geeft RuntimeError", True)

    # Een mail die niet op te halen is, slaat de rest niet plat.
    half = StubImap(ids=b"1 2", fetch_status="NO")
    ok &= check("onophaalbare mails overgeslagen", haal_mail_teksten(
        host="h", gebruiker="g", wachtwoord="w", verbinden=lambda _h: half) == [])

    # Falen bij opruimen mag de al binnengehaalde mails niet weggooien.
    knorrig = StubImap(ids=b"1", faal_op_sluiten=True)
    ok &= check("fout bij afsluiten verliest de mails niet", len(haal_mail_teksten(
        host="h", gebruiker="g", wachtwoord="w", verbinden=lambda _h: knorrig)) == 1)

    # max_mails begrenst het aantal fetches.
    veel = StubImap(ids=b"1 2 3 4 5")
    haal_mail_teksten(host="h", gebruiker="g", wachtwoord="w", max_mails=2,
                      verbinden=lambda _h: veel)
    ok &= check("max_mails begrenst fetches",
                len([a for a in veel.acties if a.startswith("fetch")]) == 2,
                str(veel.acties))
    return ok


def test_mapkeuze() -> bool:
    """INBOX is de verkeerde standaard: een gearchiveerde mail zit daar niet in."""
    print("test: welke map wordt doorzocht")
    ok = True

    # Zonder opgave: de map met de \All-vlag, ook al heet die Nederlands.
    stub = StubImap()
    ok &= check("\\All-map gekozen op vlag, niet op naam",
                kies_map(stub) == "[Gmail]/Alle berichten", kies_map(stub))

    # Expliciete opgave gaat voor, en vraagt de mappenlijst niet eens op.
    stub2 = StubImap()
    ok &= check("expliciete map wint", kies_map(stub2, "INBOX") == "INBOX")
    ok &= check("geen LIST bij expliciete map", "list" not in stub2.acties,
                str(stub2.acties))

    # Server zonder \All-vlag: terugvallen op INBOX, maar wel melden.
    meldingen: list[str] = []
    geen_vlag = StubImap(lijst=[b'(\\HasNoChildren) "/" "INBOX"'])
    ok &= check("zonder \\All-vlag terug naar INBOX",
                kies_map(geen_vlag, log=meldingen.append) == "INBOX")
    ok &= check("en dat wordt gemeld", any("INBOX" in m for m in meldingen))

    # LIST die faalt of knalt mag de run niet slopen.
    ok &= check("LIST-status NO geeft INBOX",
                kies_map(StubImap(lijst_status="NO")) == "INBOX")

    class BoosOpList(StubImap):
        def list(self, *_a, **_k):
            raise RuntimeError("list stuk")

    ok &= check("exception op LIST geeft INBOX", kies_map(BoosOpList()) == "INBOX")

    # Naam met aanhalingstekens en spaties moet heel blijven.
    raar = StubImap(lijst=[b'(\\All) "/" "Archief/Alle mail"'])
    ok &= check("naam met slash en spatie", kies_map(raar) == "Archief/Alle mail",
                kies_map(raar))

    # En het geheel: haal_mail_teksten kiest die map ook echt.
    heel = StubImap(ids=b"1")
    haal_mail_teksten(host="h", gebruiker="g", wachtwoord="w",
                      verbinden=lambda _h: heel)
    ok &= check("haal_mail_teksten opent de \\All-map",
                heel.gekozen_map == "[Gmail]/Alle berichten", heel.gekozen_map)

    # Een map die niet te openen is, hoort te knallen in plaats van stil leeg.
    stuk = StubImap(select_status="NO")
    try:
        haal_mail_teksten(host="h", gebruiker="g", wachtwoord="w",
                          verbinden=lambda _h: stuk)
        ok &= check("onopenbare map geeft RuntimeError", False)
    except RuntimeError:
        ok &= check("onopenbare map geeft RuntimeError", True)
    return ok


def test_config(monkey: dict[str, str]) -> bool:
    print("test: mail_config uit omgeving en personal")
    import os

    ok = True
    for sleutel in ("FUNDA_MAIL_USER", "FUNDA_MAIL_PASSWORD",
                    "FUNDA_MAIL_HOST", "FUNDA_MAIL_MAP"):
        os.environ.pop(sleutel, None)

    ok &= check("zonder instellingen None", mail_config({}) is None)
    ok &= check("alleen gebruiker is niet genoeg",
                mail_config({"mail_gebruiker": "ik@example.com"}) is None)

    os.environ["FUNDA_MAIL_PASSWORD"] = "app-wachtwoord"
    config = mail_config({"mail_gebruiker": "ik@example.com"})
    ok &= check("gebruiker uit personal, wachtwoord uit env", config is not None)
    if config:
        ok &= check("standaardhost gmail", config["host"] == "imap.gmail.com",
                    config["host"])
        # Leeg betekent "zoek de \All-map zelf op", niet INBOX: zie test_mapkeuze.
        ok &= check("standaardmap is leeg (automatisch)", config["map_naam"] == "",
                    repr(config["map_naam"]))

    os.environ["FUNDA_MAIL_USER"] = "env@example.com"
    os.environ["FUNDA_MAIL_HOST"] = "imap.example.com"
    config = mail_config({"mail_gebruiker": "ik@example.com",
                          "mail_host": "imap.personal.com"})
    ok &= check("omgeving wint van personal",
                config is not None and config["gebruiker"] == "env@example.com"
                and config["host"] == "imap.example.com", str(config))

    # Een wachtwoord in personal.json mag NIET gebruikt worden; het hoort een
    # secret te zijn. Zonder env-wachtwoord dus geen config.
    os.environ.pop("FUNDA_MAIL_PASSWORD")
    ok &= check("wachtwoord uit personal wordt genegeerd",
                mail_config({"mail_gebruiker": "ik@example.com",
                             "mail_wachtwoord": "staat-in-bestand"}) is None)

    for sleutel in ("FUNDA_MAIL_USER", "FUNDA_MAIL_HOST"):
        os.environ.pop(sleutel, None)
    for sleutel, waarde in monkey.items():
        os.environ[sleutel] = waarde
    return ok


def main() -> int:
    import os

    bewaard = {s: os.environ[s] for s in list(os.environ)
               if s.startswith("FUNDA_MAIL_")}
    resultaten = [
        test_decoderen(), test_imap_datum(), test_payload_vissen(),
        test_mapkeuze(), test_ophalen(), test_config(bewaard),
    ]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
