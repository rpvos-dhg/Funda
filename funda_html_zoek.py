"""Zoeken via funda.nl's publieke zoekpagina in plaats van de zoek-API.

Waarom dit bestaat: sinds 18 augustus 2026 zit `listing-search-wonen.funda.io`
achter authenticatie (`401 no token provided`) en stuurt pyfunda geen token mee.
Het detail-endpoint (`listing-detail-page.funda.io`) werkt nog wél, net als de
server-rendered zoekpagina op www.funda.nl.

De aanpak: de HTML-zoekpagina levert alleen de lijst met woning-URL's. Voor elke
woning wordt daarna het detail-endpoint bevraagd, dat precies dezelfde velden
teruggeeft als de oude zoek-API (inclusief `neighbourhood`, waar de buurtfilters
op draaien). Daardoor is `HtmlZoeker` een drop-in voor het `Funda`-object: het
biedt `search_listing()` en `get_listing()` met dezelfde vorm, en de rest van
funda_zoek.py hoeft niets te weten van HTML.

Detail-calls zijn het dure deel, dus:
- een `overslaan`-callback filtert kandidaten weg vóór de detail-call (op basis
  van wat de kaart al prijsgeeft: stad, prijs, oppervlakte, adres);
- opgehaalde details worden gecachet, zodat de detail-check verderop in
  funda_zoek.py geen tweede call doet.
"""

from __future__ import annotations

import html as html_mod
import re
from typing import Any, Callable, Iterable
from urllib.parse import quote

# Eén vast profiel en één user-agent voor www.funda.nl, uit één bron: dezelfde als de sitemapzoeker.
# Geeft funda een 403 of een bot-controle, dan faalt de run luid; er wordt nooit een ander profiel geprobeerd.
from funda_sitemap_zoek import IMPERSONATE, UA, DropIn, Resultaat, publieke_log

ZOEK_URL = "https://www.funda.nl/zoeken/koop"

# Vue/Nuxt rendert elke woningkaart in een container met deze klasse.
KAART_SPLITS = '<div class="@container'

# funda's zoekpagina kent alleen deze stralen. Een andere waarde (bijv. 6km)
# geeft géén foutmelding maar gewoon een lege resultatenpagina: status 200, nul
# kaarten. Dat kostte een productierun. Daarom snappen we naar de dichtstbijzijnde
# ondersteunde waarde, precies zoals de oude zoek-API dat deed.
ONDERSTEUNDE_STRALEN = (1, 2, 5, 10, 15, 30, 50)


def snap_straal(radius_km: int | None) -> int | None:
    """Rond een straal af op de dichtstbijzijnde waarde die funda accepteert."""
    if not radius_km:
        return None
    return min(ONDERSTEUNDE_STRALEN, key=lambda kandidaat: abs(kandidaat - radius_km))

# Sorteringen van de oude API vertaald naar wat de zoekpagina verwacht.
SORT_VERTALING = {
    None: None,
    "newest": "date_down",
    "oldest": "date_up",
    "price_asc": "price_up",
    "price_desc": "price_down",
}


def _plat(fragment: str) -> str:
    """Maak van een HTML-fragment leesbare tekst met | als scheidingsteken."""
    zonder = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.DOTALL)
    tekst = re.sub(r"<[^>]+>", " | ", zonder)
    tekst = html_mod.unescape(tekst)
    tekst = re.sub(r"(\s*\|\s*)+", " | ", tekst)
    return re.sub(r"[ \t\r\n]+", " ", tekst).strip()


def _eerste_int(patroon: str, tekst: str) -> int | None:
    m = re.search(patroon, tekst)
    if not m:
        return None
    ruw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(ruw)
    except ValueError:
        return None


def bouw_zoek_url(
    *,
    gebied: str,
    radius_km: int | None = None,
    prijs_min: int | None = None,
    prijs_max: int | None = None,
    object_type: Iterable[str] | None = None,
    oppervlakte_min: int | None = None,
    beschikbaarheid: Iterable[str] | None = ("available",),
    sort: str | None = None,
    pagina: int = 1,
) -> str:
    """Bouw een funda.nl zoek-URL.

    `gebied` is een plaatsnaam of postcode zoals funda die in de URL gebruikt
    (lowercase, spaties als koppelteken). Met `radius_km` wordt dat
    `"plaats,5km"`, wat funda's straalzoekopdracht is.
    """
    plaats = gebied.strip().lower().replace(" ", "-")
    straal = snap_straal(radius_km)
    if straal:
        plaats = f"{plaats},{straal}km"

    params: dict[str, str] = {"selected_area": f'["{plaats}"]'}

    if prijs_min is not None or prijs_max is not None:
        params["price"] = f"{prijs_min or ''}-{prijs_max or ''}"
    if object_type:
        binnen = ",".join(f'"{t}"' for t in object_type)
        params["object_type"] = f"[{binnen}]"
    if oppervlakte_min:
        params["floor_area"] = f"{oppervlakte_min}-"
    if beschikbaarheid:
        binnen = ",".join(f'"{b}"' for b in beschikbaarheid)
        params["availability"] = f"[{binnen}]"
    if sort:
        params["sort"] = sort
    if pagina and pagina > 1:
        params["search_result"] = str(pagina)

    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return f"{ZOEK_URL}?{query}"


def parse_kaarten(html: str) -> list[dict[str, Any]]:
    """Haal de woningkaarten uit een zoekpagina.

    Per kaart komt eruit wat zonder detail-call te zien is. Dat is genoeg om
    goedkoop voor te filteren; de rest komt later van het detail-endpoint.
    """
    kaarten: list[dict[str, Any]] = []
    gezien: set[str] = set()

    for deel in html.split(KAART_SPLITS)[1:]:
        link_m = re.search(r'href="(/detail/koop/[^"]+)"', deel)
        if not link_m:
            continue
        pad = link_m.group(1)
        if pad in gezien:
            continue
        gezien.add(pad)

        # /detail/koop/<stad>/<type>-<straat>-<nr>/<tiny_id>/
        delen = [p for p in pad.split("/") if p]
        stad_slug = delen[2] if len(delen) > 2 else ""
        tiny_id = next((stuk for stuk in reversed(delen) if stuk.isdigit()), None)

        tekst = _plat(deel)

        pc_m = re.search(r"\b(\d{4}\s?[A-Z]{2})\b\s*\|?\s*([A-Za-zÀ-ÿ' \-]+?)\s*\|", tekst)
        postcode = pc_m.group(1).strip() if pc_m else None
        stad = (pc_m.group(2).strip() if pc_m else None) or stad_slug.replace("-", " ").title()

        # Adres staat als los tekstblok vlak voor de postcode.
        adres_m = re.search(r"\|\s*([A-ZÀ-Ý][^|]{2,60}?\s+\d+[a-zA-Z\-]*)\s*\|\s*\d{4}\s?[A-Z]{2}", tekst)
        titel = adres_m.group(1).strip() if adres_m else None
        nr_m = re.search(r"(\d+)\s*[a-zA-Z\-]*$", titel) if titel else None
        huisnummer = nr_m.group(1) if nr_m else None

        kaarten.append(
            {
                "tiny_id": tiny_id,
                "listing_id": tiny_id,
                "detail_url": pad,
                "title": titel,
                "city": stad,
                "postcode": postcode,
                "house_number": huisnummer,
                "price": _eerste_int(r"€\s*([\d.]+)", tekst),
                "living_area": _eerste_int(r"(\d+)\s*m²", tekst),
                "is_nieuw_badge": bool(re.search(r"\|\s*Nieuw\s*\|", tekst)),
            }
        )

    return kaarten


class HtmlZoeker(DropIn):
    """Drop-in vervanger voor het Funda-object zolang de zoek-API dicht zit.

    Gebruikt de meegegeven pyfunda-client alleen voor detail-calls; het zoeken
    zelf gaat via de publieke zoekpagina.
    """

    # Wat de kaart al weet en de detaildata mag aanvullen (detaildata wint).
    KAARTVELDEN = ("title", "city", "postcode", "house_number", "price", "living_area")

    def __init__(
        self,
        detail_client: Any,
        *,
        overslaan: Callable[[dict[str, Any]], bool] | None = None,
        pauze: float = 0.4,
        log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(detail_client, pauze=pauze, log=log)
        self._overslaan = overslaan
        self._sessie = None
        self._url_gelogd = False
        # Waarom bereikbaar() nee zei; kies_zoeker() zet het in de ::error als
        # geen enkele zoekbron werkt.
        self.reden: str | None = None

    # -- HTTP ---------------------------------------------------------------

    def _haal(self, url: str) -> str:
        if self._sessie is None:
            from curl_cffi import requests as curl_requests  # lokaal: alleen hier nodig

            self._sessie = curl_requests.Session(impersonate=IMPERSONATE)
        resp = self._sessie.get(
            url,
            headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Zoekpagina gaf status {resp.status_code}")
        tekst = resp.text or ""
        if "Je bent bijna op de pagina" in tekst:
            raise RuntimeError("Zoekpagina gaf een bot-controle in plaats van resultaten")
        return tekst

    def bereikbaar(self) -> bool:
        """Laat funda de zoekpagina nog door? Eén call, zonder detail-calls.

        Bedoeld om in 'auto' snel te beslissen of deze route zinvol is. Levert
        bewust alleen een ja/nee: of er resultaten in staan, is een andere vraag
        (zie de nul-woningen-check in funda_zoek.py).
        """
        try:
            self._haal(ZOEK_URL)
        except Exception as exc:
            self.reden = str(exc)
            self._log(f"Zoekpagina niet bereikbaar: {exc}")
            return False
        return True

    # -- Drop-in API --------------------------------------------------------

    def search_listing(
        self,
        location: str,
        radius_km: int | None = None,
        offering_type: str = "buy",
        price_min: int | None = None,
        price_max: int | None = None,
        object_type: Iterable[str] | None = None,
        availability: Iterable[str] | None = ("available",),
        area_min: int | None = None,
        sort: str | None = None,
        page: int = 0,
        **_genegeerd: Any,
    ) -> list[Resultaat]:
        """Zelfde aanroep als pyfunda's search_listing; `page` telt vanaf 0."""
        if offering_type != "buy":
            raise ValueError("HtmlZoeker ondersteunt alleen offering_type='buy'")

        url = bouw_zoek_url(
            gebied=location,
            radius_km=radius_km,
            prijs_min=price_min,
            prijs_max=price_max,
            object_type=object_type,
            oppervlakte_min=area_min,
            beschikbaarheid=availability,
            sort=SORT_VERTALING.get(sort, sort),
            pagina=page + 1,
        )

        if not self._url_gelogd:
            self._url_gelogd = True
            # De log van een publieke repo is voor iedereen leesbaar; de postcode
            # in selected_area en de prijs- en m2-grenzen komen uit het profiel.
            getoond = url
            if publieke_log():
                getoond = re.sub(r"\b(selected_area|price|floor_area)=[^&]*", r"\1=(verborgen)", url)
            self._log(f"Zoek-URL (eerste van deze run): {getoond}")

        kaarten = parse_kaarten(self._haal(url))
        if not kaarten:
            return []

        resultaten: list[Resultaat] = []
        for kaart in kaarten:
            if self._overslaan and self._overslaan(kaart):
                # Bewust géén detail-call, maar wél teruggeven: de aanroeper stopt
                # met pagineren zodra een pagina niets oplevert, en een pagina vol
                # overgeslagen woningen zou de rest van de resultaten afkappen.
                # De gewone filters in funda_zoek.py wijzen deze alsnog af.
                resultaten.append(Resultaat({**kaart, "_bron": "html-kaart"}))
                continue
            # Dezelfde woning komt terug in meerdere prijsbanden en sorteringen. De
            # aanroeper dedupliceert pas ná deze call; uit het geheugen kost een
            # duplicaat geen tweede detail-call. Mislukt de call, dan overslaan:
            # zonder detail missen buurt en label, en de kaartgegevens alleen
            # zijn te mager om betrouwbaar op te filteren.
            data, _fout = self._haal_detail(
                kaart["detail_url"], "html", str(kaart.get("tiny_id") or kaart["detail_url"]),
                aanvullen={v: kaart[v] for v in self.KAARTVELDEN if kaart.get(v)})
            if data:
                resultaten.append(Resultaat(data))
        return resultaten
