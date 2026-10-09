"""Woningen uit funda's eigen notificatiemails halen.

Waarom: sinds 8 oktober 2026 is `www.funda.nl` dicht voor de Actions-runner (403
op de zoekpagina én op detailpagina's) en de zoek-API geeft 401. Zie CLAUDE.md.
Wat nog wél werkt is de aparte API-host `listing-detail-page.funda.io`.

Daarom deze bron: een bewaarde zoekopdracht in je funda-account mailt nieuw
aanbod naar je toe. Uit die mail halen we de woning-URL's, en het detail-endpoint
vult alle velden aan die de filters en het rapport nodig hebben. Geen scrapen van
de zoekpagina, en funda stuurt de data zelf.

`MailBron` is net als `HtmlZoeker` een drop-in voor het `Funda`-object, zodat
`main()` en het rapport ongewijzigd blijven.

LET OP - wat hier wél en niet op meting rust:
- Het URL-patroon van woningen (`/detail/koop/<stad>/<slug>/<tiny_id>/`) is
  honderden keren waargenomen en stabiel.
- Dat `get_listing()` op zo'n URL alle benodigde velden teruggeeft, is gemeten.
- Hoe funda's notificatiemail er precies uitziet is NIET gemeten: er stond ten
  tijde van schrijven geen bewaarde zoekopdracht aan, dus was er geen echte mail.
  `vind_woning_links()` dekt daarom de vormen die redelijkerwijs voorkomen
  (directe links, pad-only, en links die in een tracking-redirect zijn verpakt),
  en logt wat het vond. Valideer tegen de eerste echte mail voordat je hierop
  vertrouwt; `scripts/funda_mail_validatie.py` doet dat.
"""

from __future__ import annotations

import html as html_mod
import re
import time
from typing import Any, Callable, Iterable
from urllib.parse import unquote

# /detail/koop/<stad>/<type-straat-nr>/<tiny_id>/
WONING_PAD = re.compile(
    r"/detail/(?:koop|huur)/[a-z0-9\-]+/[a-z0-9\-\.]+/(\d{7,9})/?",
    re.IGNORECASE,
)


class MailResultaat:
    """Zelfde vorm als pyfunda's Listing: een `.data`-dict."""

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


def vind_woning_links(tekst: str) -> list[tuple[str, str]]:
    """Haal (pad, tiny_id) uit een mailtekst, in volgorde en zonder dubbelen.

    Werkt op zowel de HTML- als de plattetekstversie van een mail. Tracking-
    links verpakken de echte URL vaak url-encoded in een query-parameter, dus
    we scannen ook de gedecodeerde tekst.
    """
    if not tekst:
        return []

    # Eerst ruwe tekst, dan gedecodeerd: zo vinden we zowel directe links als
    # links die in een redirect zijn verpakt. &amp; en %2F komen beide voor.
    varianten = [tekst]
    ontsnapt = html_mod.unescape(tekst)
    if ontsnapt != tekst:
        varianten.append(ontsnapt)
    gedecodeerd = unquote(ontsnapt)
    if gedecodeerd != ontsnapt:
        varianten.append(gedecodeerd)

    gevonden: list[tuple[str, str]] = []
    gezien: set[str] = set()
    for variant in varianten:
        for m in WONING_PAD.finditer(variant):
            tiny_id = m.group(1)
            if tiny_id in gezien:
                continue
            gezien.add(tiny_id)
            pad = m.group(0)
            if not pad.endswith("/"):
                pad += "/"
            gevonden.append((pad, tiny_id))
    return gevonden


class MailBron:
    """Drop-in vervanger voor het Funda-object, met mails als bron.

    De mail heeft het filterwerk al gedaan (de bewaarde zoekopdracht staat in je
    funda-account), dus de filterargumenten van `search_listing` worden genegeerd.
    De gewone filters in funda_zoek.py draaien daarna nog wél over de resultaten,
    zodat buurt-, stad- en straatregels blijven gelden.
    """

    def __init__(
        self,
        detail_client: Any,
        woningen: Iterable[tuple[str, str]],
        *,
        pauze: float = 0.4,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._client = detail_client
        self._woningen = list(woningen)
        self._pauze = pauze
        self._log = log or (lambda _b: None)
        self._cache: dict[str, Any] = {}
        self._uitgeleverd = False

    # -- Drop-in API --------------------------------------------------------

    def search_listing(self, *_args: Any, page: int = 0, **_kwargs: Any) -> list[MailResultaat]:
        """Levert alle woningen uit de mails bij de eerste aanroep.

        funda_zoek.py zoekt per prijsband en sortering; dat is hier zinloos, want
        de mail is één vaste lijst. Daarom: eerste aanroep alles, daarna leeg,
        zodat de pagineerlus netjes stopt en dedup de rest doet.
        """
        if self._uitgeleverd or page:
            return []
        self._uitgeleverd = True

        self._log(f"Mailbron: {len(self._woningen)} woning(en) uit notificatiemails.")
        resultaten: list[MailResultaat] = []
        for pad, tiny_id in self._woningen:
            data = self._detail_data(pad, tiny_id)
            if data:
                resultaten.append(MailResultaat(data))
        self._log(f"Mailbron: {len(resultaten)} verrijkt via het detail-endpoint.")
        return resultaten

    def get_listing(self, listing_id: Any) -> Any:
        sleutel = str(listing_id)
        if sleutel in self._cache:
            return self._cache[sleutel]
        return self._client.get_listing(listing_id)

    def __getattr__(self, naam: str) -> Any:
        """Onbekende aanroepen (prijshistorie, marktdata) naar de client."""
        if naam.startswith("_"):
            raise AttributeError(naam)
        return getattr(self._client, naam)

    # -- Intern -------------------------------------------------------------

    def _detail_data(self, pad: str, tiny_id: str) -> dict[str, Any] | None:
        gecacht = self._cache.get(tiny_id)
        if gecacht is not None:
            listing = gecacht
        else:
            try:
                listing = self._client.get_listing(f"https://www.funda.nl{pad}")
            except Exception as exc:
                self._log(f"Detail mislukt voor {pad}: {exc}")
                return None
            finally:
                time.sleep(self._pauze)

        data = dict(getattr(listing, "data", None) or {})
        if not data:
            return None
        data.setdefault("detail_url", pad)
        data["_bron"] = "mail"

        for id_veld in ("global_id", "listing_id", "tiny_id"):
            waarde = data.get(id_veld)
            if waarde:
                self._cache[str(waarde)] = listing
        self._cache[tiny_id] = listing
        return data
