"""Funda-mails uit een IMAP-mailbox halen.

Dit is het transport van de mailroute: het haalt de mailtekst op, en
`funda_mail_bron.woningen_uit_mail()` haalt daar de woningen uit. Bewust
gescheiden, want het transport is te testen zonder mailbox en de parser zonder
netwerk.

Waarom IMAP: één secret erbij (een app-wachtwoord) en `imaplib` zit in Python,
dus geen OAuth-dans en geen extra dependency in de workflow. Gmail vereist voor
een app-wachtwoord wel tweestapsverificatie op het account.

Benodigde instellingen, uit omgeving of uit funda_personal.json:
- `FUNDA_MAIL_USER` / `mail_gebruiker` - het mailadres.
- `FUNDA_MAIL_PASSWORD` - het app-wachtwoord. **Alleen uit de omgeving**, zodat
  het in Actions uit een Secret komt en nooit in een configbestand belandt.
- `FUNDA_MAIL_HOST` / `mail_host` - optioneel, standaard imap.gmail.com.
- `FUNDA_MAIL_MAP` / `mail_map` - optioneel. Leeg laten is het beste: dan zoekt
  `kies_map()` zelf de map met de `\All`-vlag op ("alle mail"). **Niet INBOX**:
  een gearchiveerde mail zit daar niet meer in. Dat is geen theorie - op 9 okt
  2026 gaf INBOX nul funda-mails terwijl er diezelfde dag een funda-mail was,
  zonder INBOX-label. En de naam van die map is taalafhankelijk
  (`[Gmail]/All Mail` versus `[Gmail]/Alle berichten`), de vlag niet.

Het decoderen is hier het echte werk: een funda-mail is multipart met
quoted-printable of base64 gecodeerde delen, en in de ruwe bytes staan URL's
dan met `=` en regelafbrekingen door de tekst heen. `tekst_uit_mail()` laat de
stdlib dat netjes uitpakken, zodat de parser hele URL's ziet.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

IMAP_HOST_STANDAARD = "imap.gmail.com"
AFZENDER_STANDAARD = "funda.nl"

# Welke map: leeg betekent zelf uitzoeken, zie kies_map(). Niet INBOX, want een
# gearchiveerde mail zit daar niet meer in - gemeten, zie de moduledocstring.
MAP_AUTO = ""

# Eén LIST-regel: (vlaggen) "scheidingsteken" "naam"
LIST_REGEL = re.compile(
    r'\((?P<vlaggen>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+'
    r'(?P<naam>"(?:[^"\\]|\\.)*"|\S+)\s*$'
)


def mail_config(personal: dict[str, Any] | None = None) -> dict[str, str] | None:
    """Verzamel de IMAP-instellingen. None als het niet compleet is.

    Het wachtwoord komt uitsluitend uit de omgeving: in Actions is dat een
    Secret, en zo kan het niet per ongeluk in funda_personal.json terechtkomen.
    """
    personal = personal or {}
    gebruiker = (os.environ.get("FUNDA_MAIL_USER")
                 or personal.get("mail_gebruiker") or "").strip()
    wachtwoord = os.environ.get("FUNDA_MAIL_PASSWORD") or ""
    if not gebruiker or not wachtwoord:
        return None
    return {
        "host": (os.environ.get("FUNDA_MAIL_HOST")
                 or personal.get("mail_host") or IMAP_HOST_STANDAARD).strip(),
        "gebruiker": gebruiker,
        "wachtwoord": wachtwoord,
        "map_naam": (os.environ.get("FUNDA_MAIL_MAP")
                     or personal.get("mail_map") or MAP_AUTO).strip(),
    }


def _naam_uit_listregel(regel: str) -> str | None:
    treffer = LIST_REGEL.search(regel.strip())
    if not treffer:
        return None
    naam = treffer.group("naam")
    if naam.startswith('"') and naam.endswith('"'):
        naam = naam[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return naam or None


def kies_map(verbinding: Any, gewenst: str = MAP_AUTO,
             log: Callable[[str], None] | None = None) -> str:
    """Welke map doorzoeken: de opgegeven, of zelf de "alle mail"-map vinden.

    INBOX is hier de verkeerde standaard: een gearchiveerde mail zit daar niet
    meer in, en dan vindt de zoekopdracht niets terwijl de mail er wél is. Dat
    is echt gebeurd - gemeten op 9 okt 2026 tegen de eigen mailbox: nul mails in
    INBOX, terwijl Gmail een funda-mail van diezelfde dag liet zien zonder
    INBOX-label.

    Daarom zoeken we de map met de speciale vlag `\\All` op in plaats van een
    naam te hardcoden. Die naam is namelijk taalafhankelijk: bij Gmail
    `[Gmail]/All Mail`, maar op een Nederlandstalig account
    `[Gmail]/Alle berichten`. De vlag is dat niet.
    """
    zeg = log or (lambda _b: None)
    if gewenst:
        return gewenst

    try:
        status, regels = verbinding.list()
    except Exception as exc:
        zeg(f"Mappen niet op te vragen ({exc}); val terug op INBOX.")
        return "INBOX"

    if status == "OK" and regels:
        for regel in regels:
            tekst = (regel.decode("utf-8", errors="replace")
                     if isinstance(regel, (bytes, bytearray)) else str(regel))
            if "\\All" not in tekst:
                continue
            naam = _naam_uit_listregel(tekst)
            if naam:
                zeg(f"Map met de \\All-vlag gevonden: {naam!r}.")
                return naam

    zeg("Geen map met de \\All-vlag; val terug op INBOX. Een gearchiveerde mail "
        "wordt dan niet gevonden; zet desnoods FUNDA_MAIL_MAP.")
    return "INBOX"


def _decodeer(deel: email.message.Message) -> str:
    """Eén mailonderdeel naar tekst, met zijn eigen charset."""
    ruw = deel.get_payload(decode=True)
    if ruw is None:
        return ""
    charset = deel.get_content_charset() or "utf-8"
    try:
        return ruw.decode(charset, errors="replace")
    except LookupError:
        # Onbekende charset in de header; utf-8 met vervangingen is beter dan niets.
        return ruw.decode("utf-8", errors="replace")


def tekst_uit_mail(ruwe_bytes: bytes) -> str:
    """Alle tekstdelen van een mail, gedecodeerd en achter elkaar geplakt.

    Zowel text/plain als text/html, want welke van de twee de woninglinks bevat
    staat niet vast. Dubbele woningen vallen later weg op tiny_id.
    """
    if not ruwe_bytes:
        return ""
    bericht = email.message_from_bytes(ruwe_bytes, policy=email.policy.default)
    stukken: list[str] = []
    for deel in bericht.walk():
        if deel.get_content_maintype() != "text":
            continue
        if deel.get_content_subtype() not in ("plain", "html"):
            continue
        tekst = _decodeer(deel)
        if tekst:
            stukken.append(tekst)
    if not stukken:
        # Niet-multipart mail zonder bruikbare delen: val terug op de ruwe bytes.
        return ruwe_bytes.decode("utf-8", errors="replace")
    return "\n".join(stukken)


def _imap_datum(dagen_terug: int) -> str:
    """IMAP wil een datum als 09-Oct-2026, in Engelse maandafkorting."""
    moment = datetime.now(timezone.utc) - timedelta(days=max(0, dagen_terug))
    maanden = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{moment.day:02d}-{maanden[moment.month - 1]}-{moment.year}"


def haal_mail_teksten(
    *,
    host: str,
    gebruiker: str,
    wachtwoord: str,
    map_naam: str = MAP_AUTO,
    afzender: str = AFZENDER_STANDAARD,
    sinds_dagen: int = 3,
    max_mails: int = 25,
    log: Callable[[str], None] | None = None,
    verbinden: Callable[[str], Any] | None = None,
) -> list[str]:
    """Haal de tekst van recente funda-mails op, nieuwste eerst.

    Geen filter op onderwerp: een wachtwoordmail levert simpelweg nul woningen
    op, en zo blijft dit werken als funda zijn onderwerpregels wijzigt.
    """
    zeg = log or (lambda _b: None)
    maak = verbinden or (lambda h: imaplib.IMAP4_SSL(h))

    verbinding = maak(host)
    try:
        verbinding.login(gebruiker, wachtwoord)
        gekozen = kies_map(verbinding, map_naam, zeg)
        status, antwoord = verbinding.select(gekozen)
        if status != "OK":
            raise RuntimeError(f"Map {gekozen!r} niet te openen: {status} {antwoord!r}")

        criterium = f'(FROM "{afzender}" SINCE "{_imap_datum(sinds_dagen)}")'
        status, antwoord = verbinding.search(None, criterium)
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht gaf {status}: {antwoord!r}")

        ids = (antwoord[0].split() if antwoord and antwoord[0] else [])
        zeg(f"Map {gekozen!r}: {len(ids)} mail(s) van {afzender} in de laatste "
            f"{sinds_dagen} dag(en).")
        if not ids:
            return []

        # Nieuwste eerst, en niet meer dan nodig: nieuw aanbod staat vooraan.
        teksten: list[str] = []
        for mail_id in list(reversed(ids))[:max_mails]:
            status, brokken = verbinding.fetch(mail_id, "(RFC822)")
            if status != "OK":
                zeg(f"Mail {mail_id!r} niet op te halen ({status}); overgeslagen.")
                continue
            ruw = _eerste_payload(brokken)
            if not ruw:
                zeg(f"Mail {mail_id!r} had geen leesbare inhoud; overgeslagen.")
                continue
            teksten.append(tekst_uit_mail(ruw))
        return teksten
    finally:
        # Opruimen mag de run niet laten vallen; de mails zijn dan al binnen.
        for stap in ("close", "logout"):
            try:
                getattr(verbinding, stap)()
            except Exception:
                pass


def _eerste_payload(brokken: Any) -> bytes | None:
    """De ruwe mailbytes uit een IMAP-fetch-antwoord vissen.

    imaplib geeft een lijst met tuples en losse bytes door elkaar; welke vorm
    precies, verschilt per server. Daarom hier zoeken in plaats van indexeren.
    """
    if not brokken:
        return None
    for brok in brokken:
        if isinstance(brok, tuple) and len(brok) >= 2 and isinstance(brok[1], bytes):
            return brok[1]
    for brok in brokken:
        if isinstance(brok, (bytes, bytearray)) and len(brok) > 2:
            return bytes(brok)
    return None
