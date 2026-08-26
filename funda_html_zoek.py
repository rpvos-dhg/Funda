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
import time
from typing import Any, Callable, Iterable
from urllib.parse import quote

ZOEK_URL = "https://www.funda.nl/zoeken/koop"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Vue/Nuxt rendert elke woningkaart in een container met deze klasse.
KAART_SPLITS = '<div class="@container'

# funda.nl toont 15 resultaten per pagina.
PER_PAGINA = 15

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


class HtmlResultaat:
    """Zelfde vorm als pyfunda's Listing: een `.data`-dict."""

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


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
        tiny_id = None
        for stuk in reversed(delen):
            if stuk.isdigit():
                tiny_id = stuk
                break

        tekst = _plat(deel)

        postcode = None
        stad = None
        pc_m = re.search(r"\b(\d{4}\s?[A-Z]{2})\b\s*\|?\s*([A-Za-zÀ-ÿ' \-]+?)\s*\|", tekst)
        if pc_m:
            postcode = pc_m.group(1).strip()
            stad = pc_m.group(2).strip()
        if not stad:
            stad = stad_slug.replace("-", " ").title()

        # Adres staat als los tekstblok vlak voor de postcode.
        titel = None
        adres_m = re.search(r"\|\s*([A-ZÀ-Ý][^|]{2,60}?\s+\d+[a-zA-Z\-]*)\s*\|\s*\d{4}\s?[A-Z]{2}", tekst)
        if adres_m:
            titel = adres_m.group(1).strip()

        huisnummer = None
        if titel:
            nr_m = re.search(r"(\d+)\s*[a-zA-Z\-]*$", titel)
            if nr_m:
                huisnummer = nr_m.group(1)

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


class HtmlZoeker:
    """Drop-in vervanger voor het Funda-object zolang de zoek-API dicht zit.

    Gebruikt de meegegeven pyfunda-client alleen voor detail-calls; het zoeken
    zelf gaat via de publieke zoekpagina.
    """

    def __init__(
        self,
        detail_client: Any,
        *,
        overslaan: Callable[[dict[str, Any]], bool] | None = None,
        pauze: float = 0.4,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._client = detail_client
        self._overslaan = overslaan
        self._pauze = pauze
        self._log = log or (lambda _bericht: None)
        self._cache: dict[str, Any] = {}
        self._sessie = None
        self._url_gelogd = False

    # -- HTTP ---------------------------------------------------------------

    def _haal(self, url: str) -> str:
        if self._sessie is None:
            from curl_cffi import requests as curl_requests  # lokaal: alleen hier nodig

            self._sessie = curl_requests.Session(impersonate="safari15_5")
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
    ) -> list[HtmlResultaat]:
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
            self._log(f"Zoek-URL (eerste van deze run): {url}")

        kaarten = parse_kaarten(self._haal(url))
        if not kaarten:
            return []

        resultaten: list[HtmlResultaat] = []
        for kaart in kaarten:
            if self._overslaan and self._overslaan(kaart):
                # Bewust géén detail-call, maar wél teruggeven: de aanroeper stopt
                # met pagineren zodra een pagina niets oplevert, en een pagina vol
                # overgeslagen woningen zou de rest van de resultaten afkappen.
                # De gewone filters in funda_zoek.py wijzen deze alsnog af.
                resultaten.append(HtmlResultaat({**kaart, "_bron": "html-kaart"}))
                continue
            data = self._detail_data(kaart)
            if data:
                resultaten.append(HtmlResultaat(data))
        return resultaten

    def get_listing(self, listing_id: Any) -> Any:
        """Detail-call, maar bij voorkeur uit de cache van het zoeken."""
        sleutel = str(listing_id)
        if sleutel in self._cache:
            return self._cache[sleutel]
        return self._client.get_listing(listing_id)

    def __getattr__(self, naam: str) -> Any:
        """Alles wat deze klasse niet zelf doet, gaat naar de pyfunda-client.

        Het rapport gebruikt bijvoorbeeld get_price_history en
        get_market_insights; die endpoints werken nog gewoon. Zo blijft de
        zoeker een volwaardige vervanger van het Funda-object.
        """
        if naam.startswith("_"):
            raise AttributeError(naam)
        return getattr(self._client, naam)

    # -- Intern -------------------------------------------------------------

    def _detail_data(self, kaart: dict[str, Any]) -> dict[str, Any] | None:
        """Haal detaildata op en vul aan met wat de kaart al wist."""
        sleutel = kaart.get("tiny_id") or kaart.get("detail_url")

        # Dezelfde woning komt terug in meerdere prijsbanden en sorteringen. De
        # aanroeper dedupliceert pas ná deze call, dus zonder deze check betalen
        # we voor elk duplicaat opnieuw een detail-call.
        gecacht = self._cache.get(str(sleutel)) if sleutel else None
        if gecacht is not None:
            listing = gecacht
        else:
            try:
                listing = self._client.get_listing(
                    f"https://www.funda.nl{kaart['detail_url']}"
                )
            except Exception as exc:
                self._log(f"Detail mislukt voor {kaart.get('detail_url')}: {exc}")
                # Zonder detail missen we buurt/label; de kaartgegevens alleen zijn
                # te mager om betrouwbaar op te filteren, dus overslaan.
                return None
            finally:
                time.sleep(self._pauze)

        data = dict(getattr(listing, "data", None) or {})
        if not data:
            return None

        # Detaildata wint; kaartvelden vullen alleen gaten.
        for veld in ("title", "city", "postcode", "house_number", "price", "living_area"):
            if not data.get(veld) and kaart.get(veld):
                data[veld] = kaart[veld]
        data.setdefault("detail_url", kaart["detail_url"])
        data["_bron"] = "html"

        for id_veld in ("global_id", "listing_id", "tiny_id"):
            waarde = data.get(id_veld)
            if waarde:
                self._cache[str(waarde)] = listing
        if sleutel:
            self._cache[str(sleutel)] = listing

        return data
