"""Zoeken via huispedia.nl: een bron naast (of in plaats van) funda.

Waarom dit bestaat: funda's zoek-API eist sinds 18 aug 2026 een token, en de
zoekpagina geeft sinds 8 okt 2026 een 403 vanaf GitHub Actions. De mailroute
werkt, maar hangt aan een Gmail-koppeling en een bewaarde zoekopdracht. Huispedia
toont het Nederlandse koopaanbod (ook funda-aanbod, via makelaars en openbare
bronnen) en is vanaf Actions gewoon bereikbaar.

Hoe het werkt: huispedia.nl is een Inertia/Vue-app. De zoekpagina levert de
complete resultatenset als JSON mee in het `data-page`-attribuut, onder
`props.searchData.mapProperties` (tot 999 woningen per antwoord). Filters gaan
mee als `?searchQueryState=<json>` - prijs, oppervlak en type worden server-side
toegepast. Eén verzoek per gemeente levert zo alle woningen met adres, postcode,
huisnummer, prijs, m2, energielabel, bouwjaar, status, makelaar en lat/lon.
Doorbladeren is niet nodig.

De detailpagina heeft JSON-LD (schema.org RealEstateListing) met buurt,
"Gelegen op" (verdieping), VvE-bijdrage, soort appartement en publicatiedatum.
Die wordt alleen opgehaald voor woningen die de goedkope filters overleven.

Wat er NIET is: een funda-id of funda-link. Een woning uit deze bron kan dus niet
via funda's detail-endpoint worden aangevuld. De omschrijving op huispedia is
door huispedia zelf gegenereerd (niet de makelaarstekst): goed voor "Gelegen op
2e verdieping", niet betrouwbaar voor de beleggingswoorden uit funda_zoek.

robots.txt (gemeten 6 nov 2026): `/koopwoningen/...` en de detailpagina's zijn
toegestaan voor `*`; alleen `/api/` en account-paden zijn verboden. Deze module
gebruikt geen `/api/`.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
from typing import Any, Callable, Iterable
from urllib.parse import quote

BASIS = "https://huispedia.nl"

# Zelfde client-instellingen als funda_html_zoek.py: één vaste vingerafdruk.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Funda's "available" komt overeen met deze statussen. "ONDER BOD KOOP" en
# "PREMARKET_LISTING" (nog niet te koop) laten we standaard weg.
BESCHIKBAAR = ("TE KOOP", "OP TERMIJN BESCHIKBAAR", "OPEN VOOR BOD")

# Huispedia levert maximaal zoveel woningen per antwoord. Meer resultaten dan
# dit = het antwoord is afgekapt en de prijsrange moet gesplitst worden.
MAX_PER_ANTWOORD = 999

# Gemeenten zoals huispedia ze in de URL gebruikt. "den-haag" is de gemeente
# 's-Gravenhage; "leidschendam-voorburg" geeft per woning de woonplaats terug
# (Voorburg of Leidschendam), dus geen "stad onduidelijk"-gevallen.
STANDAARD_GEMEENTEN = ("den-haag", "leidschendam-voorburg")

TYPE_VERTALING = {"apartment": "appartement", "house": "woonhuis"}


class HuispediaResultaat:
    """Zelfde vorm als pyfunda's Listing: een `.data`-dict."""

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


# ---------------------------------------------------------------------------
# URL's
# ---------------------------------------------------------------------------

def bouw_zoek_url(
    gemeente: str,
    *,
    prijs_min: int | None = None,
    prijs_max: int | None = None,
    m2_min: int | None = None,
    object_type: str | None = "appartement",
) -> str:
    """Zoek-URL met de filters in `searchQueryState`, zoals de site die zelf maakt."""
    slug = gemeente.strip().lower().replace(" ", "-")
    filt: dict[str, Any] = {}
    if prijs_min is not None or prijs_max is not None:
        filt["price"] = {"min": prijs_min, "max": prijs_max}
    if object_type:
        filt["object_type"] = object_type
    if m2_min:
        filt["surface"] = {"min": m2_min, "max": None}
    staat = {
        "searchQuery": slug,
        "pagination": {"currentPage": 0, "skip": 0, "take": 10},
        "options": {"view": "list"},
        "map": {},
        "filter": filt,
    }
    pad = f"/koopwoningen/{slug}" + (f"/{object_type}" if object_type in ("appartement", "woonhuis") else "")
    return f"{BASIS}{pad}?searchQueryState={quote(json.dumps(staat, separators=(',', ':')), safe='')}"


def detail_url(rec: dict[str, Any]) -> str:
    """`/den-haag/2547cb/volendamlaan/811` (toevoeging hoort er niet in)."""
    return (f"{BASIS}/{rec.get('city_slug')}/{str(rec.get('postcode') or '').lower()}/"
            f"{rec.get('street_slug')}/{rec.get('hnum')}")


# ---------------------------------------------------------------------------
# Parsen
# ---------------------------------------------------------------------------

def lees_data_page(html: str) -> dict[str, Any] | None:
    """Het Inertia-pagina-object uit het `data-page`-attribuut."""
    m = re.search(r'data-page="([^"]+)"', html)
    if not m:
        return None
    try:
        return json.loads(html_mod.unescape(m.group(1)))
    except json.JSONDecodeError:
        return None


def parse_zoekpagina(html: str) -> tuple[int | None, list[dict[str, Any]]]:
    """(total_results, ruwe woningrecords) uit een zoekpagina.

    Gooit ValueError als de pagina geen herkenbare zoekdata heeft: gewijzigde
    markup mag niet stil op "nul woningen" uitkomen.
    """
    data = lees_data_page(html)
    if not data or "searchData" not in (data.get("props") or {}):
        raise ValueError("Huispedia-zoekpagina zonder data-page/searchData (markup veranderd?)")
    sd = data["props"]["searchData"] or {}
    recs = sd.get("mapProperties")
    if recs is None:
        recs = sd.get("properties") or []
    return sd.get("total_results"), list(recs)


def adres_sleutel(postcode: str | None, huisnummer: Any, toevoeging: str | None = None) -> str:
    """Bron-onafhankelijke sleutel: `2547CB-811` of `2544CA-906-C`."""
    pc = re.sub(r"\s+", "", str(postcode or "")).upper()
    sleutel = f"{pc}-{huisnummer}"
    if toevoeging:
        sleutel += f"-{str(toevoeging).strip().upper()}"
    return sleutel


def naar_listing(rec: dict[str, Any]) -> dict[str, Any]:
    """Huispedia-record -> dict met de veldnamen die funda_zoek.py gebruikt."""
    nummer = rec.get("hnumchar") or rec.get("hnum")
    titel = f"{rec.get('street') or ''} {nummer}".strip()
    sleutel = "huispedia:" + adres_sleutel(rec.get("postcode"), rec.get("hnum"), rec.get("hchar"))
    soort = rec.get("object_type")
    return {
        "global_id": sleutel,
        "listing_id": sleutel,
        "huispedia_id": rec.get("id"),
        "title": titel,
        "street": rec.get("street"),
        "house_number": rec.get("hnum"),
        "house_number_ext": rec.get("hchar"),
        "postcode": rec.get("postcode"),
        "city": rec.get("city_name"),
        "price": rec.get("price_sale") or rec.get("price_search"),
        "living_area": rec.get("woonoppervlakte"),
        "plot_area": rec.get("perceeloppervlakte"),
        "rooms": rec.get("aantal_kamers"),
        "construction_year": rec.get("bouwjaar"),
        "energy_label": rec.get("energie_label"),
        "object_type": soort,
        # Alleen voor niet-appartementen invullen: is_geen_appartement() wijst
        # dan af. Bij een appartement laten we het leeg (onbekend = doorlaten).
        "house_type": soort if soort and soort != "appartement" else None,
        "latitude": rec.get("lat"),
        "longitude": rec.get("lon"),
        "status": rec.get("status"),
        "broker": rec.get("office_name"),
        "market_label": rec.get("market_label"),
        "detail_url": detail_url(rec),
        "photo_urls": _foto_urls(rec),
        "_bron": "huispedia",
    }


def _foto_urls(rec: dict[str, Any]) -> list[str]:
    img = rec.get("img_src")
    # 'aws' en 'huispedia_server' staan allebei achter dezelfde CDN (gemeten);
    # 'cloud_storage' en leeg niet, die laten we weg.
    if not img or rec.get("img_storage_location") not in ("aws", "huispedia_server"):
        return []
    pc = str(rec.get("postcode") or "").lower()
    return [f"https://d36jewe1e30sna.cloudfront.net/properties/{pc[:4]}/{pc[4:]}/"
            f"{rec.get('hnum')}/{img}"]


def parse_detail(html: str) -> dict[str, Any]:
    """Velden uit de JSON-LD van een detailpagina, in funda-namen waar het kan."""
    uit: dict[str, Any] = {}
    kenmerken: dict[str, str] = {}
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            blok = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for node in blok.get("@graph", []) if isinstance(blok, dict) else []:
            soort = node.get("@type")
            soorten = soort if isinstance(soort, list) else [soort]
            if "RealEstateListing" in soorten:
                uit["description"] = node.get("description") or ""
                uit["publication_date"] = node.get("datePosted")
            if "Offer" in soorten and node.get("price"):
                uit["price"] = node.get("price")
            if "Place" in soorten and "/buurt/" in str(node.get("@id")):
                uit["neighbourhood"] = node.get("name")
            if any(s in soorten for s in ("Apartment", "House", "SingleFamilyResidence", "Residence")):
                geo = node.get("geo") or {}
                uit["latitude"] = geo.get("latitude")
                uit["longitude"] = geo.get("longitude")
                uit["house_type"] = node.get("accommodationCategory")
                for prop in node.get("additionalProperty") or []:
                    if prop.get("name") and prop.get("value") is not None:
                        kenmerken[str(prop["name"])] = str(prop["value"])
    if kenmerken:
        uit["kenmerken"] = kenmerken
        # is_begane_grond() leest dit veld; huispedia schrijft "2e verdieping",
        # "Begane grond", ...
        if kenmerken.get("Gelegen op"):
            uit["gelegen_op"] = kenmerken["Gelegen op"]
        # Tekstparsers in funda_rapport.py (servicekosten, balkon) lezen de
        # omschrijving; zet de kenmerken er leesbaar achter.
        regels = "\n".join(f"{k}: {v}" for k, v in kenmerken.items())
        uit["description"] = (uit.get("description") or "") + "\n\nKenmerken:\n" + regels
    return uit


# ---------------------------------------------------------------------------
# Drop-in zoeker
# ---------------------------------------------------------------------------

class HuispediaZoeker:
    """Drop-in voor het Funda-object, zoals HtmlZoeker en MailBron.

    `search_listing()` negeert postcode en straal: huispedia zoekt per gemeente.
    De eerste aanroep haalt per gemeente in één verzoek de hele prijsrange op
    (`prijs_bereik`), latere aanroepen per prijsband komen uit de cache. De
    gewone filters in funda_zoek.py (stad, buurt, straat) doen de rest.
    """

    def __init__(
        self,
        *,
        gemeenten: Iterable[str] = STANDAARD_GEMEENTEN,
        prijs_bereik: tuple[int, int] | None = None,
        statussen: Iterable[str] = BESCHIKBAAR,
        buurt_bepaler: Callable[[float | None, float | None], str | None] | None = None,
        haal: Callable[[str], str] | None = None,
        pauze: float = 1.0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._gemeenten = tuple(gemeenten)
        self._prijs_bereik = prijs_bereik
        self._statussen = {s.upper() for s in statussen}
        self._buurt = buurt_bepaler
        self._haal_extern = haal
        self._pauze = pauze
        self._log = log or (lambda _b: None)
        self._sessie = None
        self._zoek_cache: dict[tuple, list[dict[str, Any]]] = {}
        self._detail_cache: dict[str, HuispediaResultaat] = {}
        self._per_id: dict[str, dict[str, Any]] = {}
        self._verzoeken = 0

    # -- HTTP ---------------------------------------------------------------

    def _haal(self, url: str) -> str:
        if self._verzoeken:
            time.sleep(self._pauze)
        self._verzoeken += 1
        if self._haal_extern:
            return self._haal_extern(url)
        if self._sessie is None:
            from curl_cffi import requests as curl_requests  # alleen hier nodig

            self._sessie = curl_requests.Session(impersonate="safari15_5")
        resp = self._sessie.get(
            url, headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"}, timeout=30
        )
        if resp.status_code != 200:
            # Geen nieuwe poging met andere instellingen: een blokkade is een
            # signaal om te stoppen, niet om omheen te werken.
            raise RuntimeError(f"Huispedia gaf status {resp.status_code}")
        return resp.text or ""

    def bereikbaar(self) -> bool:
        try:
            self._ophalen(self._gemeenten[0], *(self._prijs_bereik or (None, None)), None, "appartement")
        except Exception as exc:
            self._log(f"Huispedia niet bereikbaar: {exc}")
            return False
        return True

    def _ophalen(self, gemeente: str, lo: int | None, hi: int | None,
                 m2_min: int | None, soort: str | None, diepte: int = 0) -> list[dict[str, Any]]:
        sleutel = (gemeente, lo, hi, m2_min, soort)
        if sleutel in self._zoek_cache:
            return self._zoek_cache[sleutel]
        url = bouw_zoek_url(gemeente, prijs_min=lo, prijs_max=hi, m2_min=m2_min, object_type=soort)
        totaal, recs = parse_zoekpagina(self._haal(url))
        if totaal is not None and totaal > len(recs) and lo is not None and hi is not None and diepte < 4:
            # Afgekapt (meer dan ~999): splits de prijsrange en haal beide helften.
            midden = (lo + hi) // 2
            self._log(f"Huispedia {gemeente} {lo}-{hi}: {totaal} resultaten, {len(recs)} geleverd; splitsen.")
            recs = (self._ophalen(gemeente, lo, midden, m2_min, soort, diepte + 1)
                    + self._ophalen(gemeente, midden, hi, m2_min, soort, diepte + 1))
        elif totaal is not None and totaal > len(recs):
            self._log(f"Let op: huispedia {gemeente} gaf {len(recs)} van {totaal} resultaten.")
        self._zoek_cache[sleutel] = recs
        return recs

    # -- Drop-in API ----------------------------------------------------------

    def search_listing(
        self,
        location: str | None = None,
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
    ) -> list[HuispediaResultaat]:
        if offering_type != "buy":
            raise ValueError("HuispediaZoeker ondersteunt alleen offering_type='buy'")
        if page:
            return []  # alles zit in het eerste antwoord
        types = [TYPE_VERTALING.get(t, t) for t in (object_type or [])]
        soort = types[0] if len(types) == 1 else None
        lo, hi = self._prijs_bereik or (price_min, price_max)

        uit: list[HuispediaResultaat] = []
        gezien: set[str] = set()
        for gemeente in self._gemeenten:
            for rec in self._ophalen(gemeente, lo, hi, area_min, soort):
                if self._statussen and str(rec.get("status") or "").upper() not in self._statussen:
                    continue
                prijs = rec.get("price_sale") or rec.get("price_search") or 0
                if price_min is not None and prijs < price_min:
                    continue
                if price_max is not None and prijs > price_max:
                    continue
                if area_min and (rec.get("woonoppervlakte") or 0) < area_min:
                    continue
                data = naar_listing(rec)
                if self._buurt is not None:
                    # Zonder buurtnaam lopen de buurtfilters in funda_zoek.py
                    # leeg en komt alles door; de CBS-buurt is wat funda toont.
                    data["neighbourhood"] = self._buurt(data["latitude"], data["longitude"])
                if data["global_id"] in gezien:
                    continue
                gezien.add(data["global_id"])
                self._per_id[data["global_id"]] = data
                uit.append(HuispediaResultaat(data))
        return uit

    def get_listing(self, listing_id: Any) -> HuispediaResultaat:
        """Zoekdata aangevuld met de detailpagina (JSON-LD). Gecachet."""
        sleutel = str(listing_id)
        if sleutel in self._detail_cache:
            return self._detail_cache[sleutel]
        basis = self._per_id.get(sleutel)
        if basis is None:
            raise KeyError(f"Onbekende huispedia-woning {sleutel}; eerst search_listing()")
        data = dict(basis)
        try:
            detail = parse_detail(self._haal(basis["detail_url"]))
        except Exception as exc:
            self._log(f"Huispedia-detail mislukt voor {basis['title']}: {exc}")
            detail = {}
        for veld, waarde in detail.items():
            if waarde not in (None, "", []):
                data[veld] = waarde
        # Een appartement-subtype ("Galerijflat") mag niet als huis gelden; een
        # echt huistype ("Tussenwoning") wel. is_geen_appartement() regelt dat.
        resultaat = HuispediaResultaat(data)
        self._detail_cache[sleutel] = resultaat
        return resultaat
