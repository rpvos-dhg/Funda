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
- `FUNDA_MAIL_MAP` / `mail_map` - optioneel, standaard INBOX.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

IMAP_HOST_STANDAARD = "imap.gmail.com"
MAP_STANDAARD = "INBOX"
AFZENDER_STANDAARD = "funda.nl"


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
                     or personal.get("mail_map") or MAP_STANDAARD).strip(),
    }


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
    map_naam: str = MAP_STANDAARD,
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
        verbinding.select(map_naam)

        criterium = f'(FROM "{afzender}" SINCE "{_imap_datum(sinds_dagen)}")'
        status, antwoord = verbinding.search(None, criterium)
        if status != "OK":
            raise RuntimeError(f"IMAP-zoekopdracht gaf {status}: {antwoord!r}")

        ids = (antwoord[0].split() if antwoord and antwoord[0] else [])
        zeg(f"Mailbox: {len(ids)} mail(s) van {afzender} in de laatste "
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
