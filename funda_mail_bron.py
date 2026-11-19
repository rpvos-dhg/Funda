"""Woningen uit funda's eigen notificatiemails halen.

Waarom: sinds 8 oktober 2026 is `www.funda.nl` dicht voor de Actions-runner (403
op de zoekpagina én op detailpagina's) en de zoek-API geeft 401. Zie CLAUDE.md.
Wat nog wél werkt is de aparte API-host `listing-detail-page.funda.io`.

Daarom deze bron: een bewaarde zoekopdracht in je funda-account mailt nieuw
aanbod naar je toe. Uit die mail halen we de woning-URL's, en het detail-endpoint
vult alle velden aan die de filters en het rapport nodig hebben. Geen scrapen van
de zoekpagina, en funda stuurt de data zelf. Sinds 6 nov 2026 alleen nog met
zoek_methode 'mail', niet in 'auto': op Actions is de sitemaproute de bron (zie
"Mailroute (alleen lokaal)" in CLAUDE.md).

`MailBron` is net als `HtmlZoeker` een drop-in voor het `Funda`-object, zodat
`main()` en het rapport ongewijzigd blijven.

Wat hier op meting rust:
- Het URL-patroon van woningen (`/detail/koop/<stad>/<slug>/<tiny_id>/`) is
  honderden keren waargenomen en stabiel.
- Dat `get_listing()` op zo'n URL alle benodigde velden teruggeeft, is gemeten.
- Twee transactionele funda-mails, bekeken op 9 okt 2026 (één uit 2022, één uit
  2026):
  * In het text/plain-deel staan inhoudelijke links onverpakt:
    `https://www.funda.nl/makelaar/<id>`, `.../account/email-instellingen`,
    `.../meer-weten/...`. Die vindt `vind_woning_links()` direct.
  * Het html-deel gebruikt funda's tracker ruim: één mail, plat en html volledig
    uitgelezen, had 9 tracking-links. Een woninglink kan dus verpakt zijn.
    Daarom plakt `tekst_uit_mail()` (funda_mail_ophalen.py) plat en html achter
    elkaar: de parser krijgt beide kansen.
  * De verpakte links zijn ONDOORZICHTIG: `links.funda.nl/s/vb/<token>/<token>/23`
    (2026) en `links.funda.nl/e/evib?_t=..&_m=..&_e=..` (2022). Er zit GEEN
    `?url=` met de echte URL in. De `?url=`-variant in `vind_woning_links()`
    blijft staan voor andere mailers, maar op funda's eigen links werkt die niet.
  * `links.funda.nl` geeft vanaf Actions een 403 (gemeten 9 okt 2026). Een
    verpakte link volgen kan dus alleen lokaal of op een eigen netwerk.
- De alert-mails van een bewaarde zoekopdracht werkten in de praktijk: van 17 okt
  t/m 4 nov 2026 leverde de mailroute op Actions 35 woningen. Daar kan
  `los_tracking_link_op()` niets volgen (403), dus de parser vond die
  woninglinks direct in de mail. De opmaak zelf staat niet als fixture in de
  repo: echte mailinhoud en tracking-tokens horen bij een persoonlijke mailbox.
- Daarom:
  * `woningen_uit_mail()` is de hoofdingang. Vindt die geen directe woninglinks,
    dan meldt hij hoeveel ondoorzichtige tracking-links er wél stonden. Dat
    scheidt "mail zonder nieuw aanbod" van "woninglink zit in een redirect".
  * `los_tracking_link_op()` volgt zo'n redirect alleen bij nul directe links en
    alleen met `volg_redirects=True`, want elke call is een echte klik in
    funda's tracker. De mailroute in funda_zoek.py zet dat nooit aan; alleen
    `scripts/funda_mail_validatie.py --volg-redirects` doet het, op verzoek.
  `scripts/funda_mail_validatie.py` valideert dit tegen een echte mail.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any, Callable, Iterable
from urllib.parse import unquote

from funda_sitemap_zoek import IMPERSONATE, UA, DropIn, Resultaat

# /detail/koop/<stad>/<type-straat-nr>/<tiny_id>/
WONING_PAD = re.compile(
    r"/detail/(?:koop|huur)/[a-z0-9\-]+/[a-z0-9\-\.]+/(\d{7,9})/?",
    re.IGNORECASE,
)

# funda's eigen click-tracker. Beide vormen zijn in echte mails gezien:
# /s/vb/<token>/<token>/23 en /e/evib?_t=..&_m=..&_e=.. - allebei ondoorzichtig.
TRACKING_LINK = re.compile(r"https?://links\.funda\.nl/[^\s\"'<>)\]]+", re.IGNORECASE)

MAX_REDIRECT_HOPS = 5

# Client voor links.funda.nl: hetzelfde vaste profiel als de zoekers voor
# www.funda.nl, uit dezelfde bron. Eén profiel, nooit wisselen;
# test_funda_mail.py pint vast dat ze gelijk blijven.
TRACKER_UA = UA
TRACKER_IMPERSONATE = IMPERSONATE


def _zonder_dubbelen(items: Iterable[Any], sleutel: Callable[[Any], Any] = lambda item: item) -> list[Any]:
    """De items in volgorde, per sleutel alleen het eerste."""
    uit: dict[Any, Any] = {}
    for item in items:
        uit.setdefault(sleutel(item), item)
    return list(uit.values())


def _varianten(tekst: str) -> list[str]:
    """Ruwe tekst, html-unescaped en url-gedecodeerd. &amp; en %2F komen beide voor."""
    varianten = [tekst]
    ontsnapt = html_mod.unescape(tekst)
    if ontsnapt != tekst:
        varianten.append(ontsnapt)
    gedecodeerd = unquote(ontsnapt)
    if gedecodeerd != ontsnapt:
        varianten.append(gedecodeerd)
    return varianten


def vind_woning_links(tekst: str) -> list[tuple[str, str]]:
    """Haal (pad, tiny_id) uit een mailtekst, in volgorde en zonder dubbelen.

    Werkt op zowel de HTML- als de plattetekstversie van een mail. Sommige
    mailers verpakken de echte URL url-encoded in een query-parameter, dus we
    scannen ook de gedecodeerde tekst. Funda's eigen tracker doet dat NIET
    (gemeten, zie de moduledocstring); daarvoor is `los_tracking_link_op()`.
    """
    if not tekst:
        return []
    treffers = ((m.group(0) if m.group(0).endswith("/") else m.group(0) + "/", m.group(1))
                for variant in _varianten(tekst) for m in WONING_PAD.finditer(variant))
    return _zonder_dubbelen(treffers, lambda treffer: treffer[1])


def vind_tracking_links(tekst: str) -> list[str]:
    """Ondoorzichtige `links.funda.nl`-redirects uit een mailtekst, zonder dubbelen.

    Deze bestaan los van `vind_woning_links()`: er zit geen woning-URL in het
    adres, dus ze zijn alleen te volgen. Nut: vindt de parser nul woningen maar
    staan hier wel links, dan verpakt funda de woninglink en is het volgen van
    de redirect de oplossing - geen reden om de parser te verbouwen.
    """
    if not tekst:
        return []
    # Alleen html-unescaped scannen, niet url-gedecodeerd: `&amp;` moet weg (anders
    # is de link onbruikbaar), maar %-escapes in het token horen te blijven staan,
    # want met die URL moet straks echt een call gedaan worden. Eén variant houdt
    # bovendien de dedup kloppend; op twee varianten telt dezelfde link dubbel.
    return _zonder_dubbelen(m.group(0).rstrip(".,;") for m in TRACKING_LINK.finditer(html_mod.unescape(tekst)))


def _haal_locatie(url: str) -> str | None:
    """Eén redirect-hop: geef de Location-header, zonder hem te volgen."""
    try:
        from curl_cffi import requests as crequests
    except Exception:
        crequests = None

    if crequests is not None:
        resp = crequests.get(url, headers={"user-agent": TRACKER_UA}, impersonate=TRACKER_IMPERSONATE,
                             allow_redirects=False, timeout=20)
        return resp.headers.get("location") or resp.headers.get("Location")

    # Zonder curl_cffi: stdlib, met een redirect-handler die niets volgt.
    import urllib.error
    import urllib.request

    class _GeenRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a: Any, **_k: Any) -> None:
            return None

    opener = urllib.request.build_opener(_GeenRedirect)
    try:
        with opener.open(url, timeout=20) as resp:
            return resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("Location")


def los_tracking_link_op(
    url: str,
    *,
    haal: Callable[[str], str | None] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[str, str] | None:
    """Volg een ondoorzichtige redirect tot er een woning-URL uit komt.

    WERKT NIET VANAF GITHUB ACTIONS. Gemeten op 9 okt 2026: `links.funda.nl`
    geeft daar een **403**, net als `www.funda.nl`. Vanaf een runner is een
    verpakte woninglink dus niet te volgen. Lokaal of op een eigen netwerk wel,
    en daarvoor staat dit er.

    Gevolg voor de mailroute: die hangt ervan af dat de alert-mail de woninglink
    érgens onverpakt heeft - in de plattetekstversie bijvoorbeeld, waar funda in
    de gemeten mails gewone `www.funda.nl`-URL's zet. Staat de link in beide
    delen alleen verpakt, dan komt de mailroute op Actions niet verder dan de
    melding dat er tracking-links waren.

    Alleen aanroepen als er geen directe links zijn: zo'n call is een klik in
    funda's tracker, en die tokens zijn eenmalig.
    """
    haal = haal or _haal_locatie
    zeg = log or (lambda _b: None)

    huidig = url
    for hop in range(MAX_REDIRECT_HOPS):
        treffers = vind_woning_links(huidig)
        if treffers:
            return treffers[0]
        try:
            volgende = haal(huidig)
        except Exception as exc:
            zeg(f"Redirect volgen mislukt op hop {hop + 1}: {exc}")
            return None
        if not volgende:
            zeg(f"Geen Location-header op hop {hop + 1}; spoor loopt dood.")
            return None
        huidig = volgende

    # De URL van de laatste hop is hierboven nog niet bekeken; anders zou de
    # hoplimiet er effectief één lager liggen dan hij zegt.
    treffers = vind_woning_links(huidig)
    if treffers:
        return treffers[0]

    zeg(f"Meer dan {MAX_REDIRECT_HOPS} redirects; opgegeven.")
    return None


def woningen_uit_mail(
    tekst: str,
    *,
    volg_redirects: bool = False,
    haal: Callable[[str], str | None] | None = None,
    log: Callable[[str], None] | None = None,
) -> list[tuple[str, str]]:
    """Hoofdingang: woningen uit een mailtekst, met de tracking-val erbij.

    Directe links zijn het normale geval (gemeten op twee echte funda-mails).
    Staan die er niet, dan zegt deze functie hoeveel ondoorzichtige tracking-
    links er wél stonden - dat is het verschil tussen "mail zonder woningen" en
    "woninglink zit in een redirect". Met `volg_redirects=True` wordt dat tweede
    geval ook echt opgelost.
    """
    zeg = log or (lambda _b: None)

    direct = vind_woning_links(tekst)
    if direct:
        return direct

    tracking = vind_tracking_links(tekst)
    if not tracking:
        return []

    if not volg_redirects:
        zeg(f"Geen directe woninglinks, maar wel {len(tracking)} tracking-link(s). "
            f"Funda verpakt de woninglink mogelijk; draai met volg_redirects=True.")
        return []

    zeg(f"Geen directe woninglinks; {len(tracking)} tracking-link(s) volgen.")
    treffers = [los_tracking_link_op(link, haal=haal, log=zeg) for link in tracking]
    gevonden = _zonder_dubbelen((treffer for treffer in treffers if treffer), lambda treffer: treffer[1])
    zeg(f"{len(gevonden)} woning(en) uit redirects gehaald.")
    return gevonden


class MailBron(DropIn):
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
        super().__init__(detail_client, pauze=pauze, log=log)
        self._woningen = list(woningen)
        self._uitgeleverd = False

    # -- Drop-in API --------------------------------------------------------

    def search_listing(self, *_args: Any, page: int = 0, **_kwargs: Any) -> list[Resultaat]:
        """Levert alle woningen uit de mails bij de eerste aanroep.

        funda_zoek.py zoekt per prijsband en sortering; dat is hier zinloos, want
        de mail is één vaste lijst. Daarom: eerste aanroep alles, daarna leeg,
        zodat de pagineerlus netjes stopt en dedup de rest doet.
        """
        if self._uitgeleverd or page:
            return []
        self._uitgeleverd = True

        self._log(f"Mailbron: {len(self._woningen)} woning(en) uit notificatiemails.")
        resultaten: list[Resultaat] = []
        for pad, tiny_id in self._woningen:
            data, _fout = self._haal_detail(pad, "mail", tiny_id)
            if data:
                resultaten.append(Resultaat(data))
        self._log(f"Mailbron: {len(resultaten)} verrijkt via het detail-endpoint.")
        return resultaten

    def _fout_regel(self, pad: str, exc: Exception) -> str:
        return f"Detail mislukt voor {pad}: {exc}"
