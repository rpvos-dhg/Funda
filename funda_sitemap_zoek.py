"""Zoeken via funda's eigen sitemaps in plaats van de zoek-API of zoekpagina.

Waarom dit bestaat: de zoek-API geeft sinds 18 aug 2026 een 401 en de zoekpagina
sinds 8 okt 2026 een 403 vanaf GitHub Actions (zie CLAUDE.md). Funda publiceert
wel sitemaps, en die zijn juist bedoeld voor geautomatiseerde lezers:
robots.txt van www.funda.nl noemt ze zelf
(`Sitemap: https://www.funda.nl/sitemap_index.xml/`).

Let op wat robots.txt hier wél en níet dekt. Die van www.funda.nl gaat over de
sitemaps en de webpagina's. De detail-calls gaan via pyfunda naar een andere
host, `listing-detail-page.funda.io`, en die heeft `Disallow: /`. De check in
`detail_verboden()` kan die calls dus niet tegenhouden. Of deze route dat
waard is, is een besluit van de gebruiker; zie "robots.txt van de API-hosts" in
CLAUDE.md, met het volume.

Gemeten vanaf Actions op 6 nov 2026 (scripts/funda_sitemap_probe.py en
scripts/funda_sitemap_validatie.py; runs 42260153909, 42261516145, 42262032618):
- robots.txt, de sitemap-index en de vier koop-sitemaps geven 200 met XML.
- De index wijst naar `sitemap-detail-koop1..4.xml` (plus huur, nieuwbouw,
  recreatie, europe). Samen 102.365 koop-URL's, ELK met een <lastmod>.
- Den Haag 3.695 URL's, Voorburg 262; 3.103 na de slug-afwijslijst.
- Alle 35 woningen die de mailroute tussen 17 okt en 4 nov toonde, staan erin.
- De index had lastmod 04:59 NL; om 18:17 en 18:29 NL was dat nog de nieuwste
  versie. Dagelijks verversen is dus vermoed (één dag gemeten). Reken op
  ongeveer een dag vertraging voor nieuw aanbod.

De aanpak: de sitemaps leveren alleen URL + lastmod. Alles daarbuiten (prijs,
oppervlak, buurt, status, coördinaten) komt van het detail-endpoint, dat vanaf
Actions wél werkt. Dat maakt detail-calls het dure deel, daarom:
- alleen URL's in de gekozen steden, en alleen appartementen volgens de URL-slug
  (afwijslijst: een onbekend type gaat gewoon door);
- een persistente cache per woning met lastmod en de velden waarop de doelmarkt
  wordt bepaald (prijs, m2, status, stad, buurt, coördinaten). Is de lastmod niet
  veranderd en viel de woning buiten de doelmarkt, dan kost hij geen call meer.
  Woningen bínnen de doelmarkt worden elke run vers opgehaald, zodat status en
  prijs in het rapport kloppen;
- een maximum aantal verkennende calls per run, nieuwste lastmod eerst, en een
  tijdsbudget. Wat dan nog openstaat (de eerste runs: het oude aanbod), komt de
  volgende run aan bod;
- de ~23 MB koop-sitemaps worden alleen opnieuw opgehaald als de index zegt dat
  ze veranderd zijn. robots.txt en de index zelf gaan elke run (2 verzoeken);
  is de index-lastmod gelijk aan die van de vorige run, dan komt de
  kandidatenlijst uit de cache (hooguit MAX_HERGEBRUIK_UUR oud).

Luid falen in plaats van een half of verouderd rapport (RuntimeError, en dus
exit 2 in main()):
- het detail-endpoint weigert (401/403/429), of DICHT_NA detail-calls op rij
  mislukken, ook als er eerder in de run calls slaagden (`DetailEndpointDicht`);
- een geconfigureerde stad heeft nul URL's in de sitemaps (typfout of andere
  slug bij funda);
- de nieuwste lastmod onder de kandidaten is ouder dan MAX_LEEFTIJD_DAGEN, of
  er staat geen lastmod in (bevroren of kapotte sitemap).

`SitemapZoeker` is net als `HtmlZoeker` en `MailBron` een drop-in voor het
`Funda`-object. Anders dan de mailroute filtert hij zelf op prijs, oppervlak en
beschikbaarheid, net zoals de oude zoek-API dat server-side deed: de argumenten
van `search_listing` worden dus gewoon gerespecteerd.

Samenwerking met de pool in funda_zoek.py (`controleer_pool`): `pool_oordeel()`
vertelt per getrackte woning wat deze zoeker er deze run mee deed, zodat de pool
geen tweede detail-call doet voor een woning die hier al is opgehaald, mislukt of
op grond van de cache bewust is overgeslagen. Zie `pool_oordeel()`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROBOTS_URL = "https://www.funda.nl/robots.txt"
# Wat robots.txt op 6 nov 2026 noemde. Alleen als terugval: de echte waarde
# komt elke run uit robots.txt, zodat een verhuizing vanzelf wordt opgepikt.
SITEMAP_INDEX_URL = "https://www.funda.nl/sitemap_index.xml/"

# Zelfde client-instellingen als HtmlZoeker. Bewust één vast profiel: geeft funda
# een 403 of een bot-controle, dan faalt de run luid in plaats van dat er een
# ander profiel geprobeerd wordt.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
IMPERSONATE = "safari15_5"

KOOP_KIND = re.compile(r"/sitemap-detail-koop\d*\.xml/?$", re.IGNORECASE)
WONING_URL = re.compile(
    r"^https?://www\.funda\.nl(/detail/koop/([a-z0-9\-]+)/([a-z0-9\-\.]+)/(\d{7,9})/)$",
    re.IGNORECASE,
)
TINY_IN_URL = re.compile(r"/(\d{7,9})/?(?:[?#]|$)")
BLOK = re.compile(r"<(url|sitemap)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.IGNORECASE)

# Eerste slug-segment dat zeker geen appartement is. Afwijslijst en geen
# toestaanlijst, om dezelfde reden als GEEN_APPARTEMENT in funda_zoek.py: een
# onbekend type doorlaten kost hooguit een detail-call, een gemist type kost
# stil een woning.
GEEN_APPARTEMENT_SLUG = {
    "huis", "woonhuis", "parkeergelegenheid", "parkeerplaats", "garagebox",
    "garage", "bouwgrond", "berging", "woonwagenstandplaats", "ligplaats",
    "standplaats", "kavel",
}

STANDAARD_STEDEN = ("den-haag", "voorburg")
# Versie 2: plus het index-kenmerk met de kandidatenlijst, en coördinaten en
# het statuskenmerk per woning. Een versie-1-cache (alleen woningen) is nog
# bruikbaar: ontbrekende coördinaten betekenen alleen "onbekend = doorlaten".
CACHE_VERSIE = 2

# Velden die per woning in de cache gaan: genoeg om elke run opnieuw te bepalen
# of hij in de doelmarkt valt en of de type-, stad-, buurt-, straat- en
# afstandsfilters hem afwijzen, zonder detail-call. Bewust de velden en niet de
# uitkomst: verandert een filter of de prijsgrens, dan geldt dat meteen ook voor
# de woningen in de cache.
CACHE_VELDEN = (
    "price", "living_area", "status", "city", "neighbourhood", "title",
    "house_number", "house_number_ext", "postcode", "house_type", "object_type",
    "detail_url", "latitude", "longitude",
)

# Mislukken zoveel detail-calls op rij, dan is het detail-endpoint dicht en niet
# een paar woningen weg. Dan luid falen in plaats van een lege of halve oogst
# door te geven. Ook halverwege de run: een geslaagde call eerder bewijst niet dat
# het endpoint nu nog werkt. Een nette 404 (`WoningNietGevonden`) telt niet: dat
# is een antwoord van een werkend endpoint (de e2e zag er 1 per 200 calls). Wel:
# time-outs, 5xx en fouten zonder bekende status. De pool in funda_zoek.py telt
# door vanaf de laatste calls hier.
DICHT_NA = 5

# Is de nieuwste lastmod onder de kandidaten ouder dan dit, dan ververst funda de
# sitemap niet meer (of is hij bevroren). Den Haag en Voorburg hebben elke dag
# wijzigingen; gemeten lag de nieuwste lastmod binnen een dag van de snapshot.
# Zonder deze check blijft de run groen terwijl er nooit meer iets nieuws komt.
MAX_LEEFTIJD_DAGEN = 3

# Hoe lang de kandidatenlijst uit de cache hergebruikt mag worden zolang de index
# "ongewijzigd" zegt. Daarna toch opnieuw downloaden: een index-lastmod die blijft
# hangen terwijl de koop-sitemaps wel veranderen, mag niet stil nieuw aanbod
# kosten. Een snapshot is er dagelijks, dus 36 uur mist er hooguit één.
MAX_HERGEBRUIK_UUR = 36

# Tijdsbudget voor de verkennende detail-calls per run. Normaal kost een call
# ~0,8 s (e2e: 200 calls in 167 s), dus dit raakt alleen een traag endpoint. Wat
# niet verkend is, blijft achterstand voor de volgende run.
MAX_SECONDEN = 900


class DetailEndpointDicht(RuntimeError):
    """Het detail-endpoint weigert de client of valt herhaaldelijk uit.

    Een bronprobleem, geen woningprobleem: de run moet stoppen (exit 2) voordat
    er een half rapport wordt geschreven. De Funda-subklasse in funda_zoek.py
    gooit hem bij status 401, 403 of 429; deze zoeker en de pool bij DICHT_NA
    mislukte calls op rij.
    """


class WoningNietGevonden(LookupError):
    """Het detail-endpoint antwoordde netjes 404 of 410: deze woning is er niet (meer).

    Dat is een antwoord van een werkend endpoint en dus geen teken van een
    storing. pyfunda geeft voor elke status behalve 200 een LookupError; de
    Funda-subklasse in funda_zoek.py maakt er op grond van de status deze van.
    """

# Wat deze zoeker deze run met een woning deed; zie pool_oordeel().
OPGEHAALD = "opgehaald"
MISLUKT = "mislukt"
OVERGESLAGEN = "overgeslagen"
ACHTERSTAND = "achterstand"
NIET_IN_SITEMAP = "niet_in_sitemap"
ONBEKEND = "onbekend"


class SitemapResultaat:
    """Zelfde vorm als pyfunda's Listing: een `.data`-dict."""

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


# -- Ontleden (puur, zonder netwerk) ------------------------------------------

def ontleed_sitemap(xml: str) -> tuple[str, list[tuple[str, str | None]]]:
    """('index' | 'urlset' | 'onbekend', [(loc, lastmod), ...])."""
    if re.search(r"<sitemapindex[\s>]", xml, re.IGNORECASE):
        soort = "index"
    elif re.search(r"<urlset[\s>]", xml, re.IGNORECASE):
        soort = "urlset"
    else:
        soort = "onbekend"
    items: list[tuple[str, str | None]] = []
    for _tag, blok in BLOK.findall(xml):
        loc = LOC.search(blok)
        if not loc:
            continue
        lm = LASTMOD.search(blok)
        items.append((loc.group(1).replace("&amp;", "&"), lm.group(1) if lm else None))
    return soort, items


def sitemap_uit_robots(robots: str) -> str | None:
    for regel in robots.splitlines():
        sleutel, _, waarde = regel.partition(":")
        if sleutel.strip().lower() == "sitemap" and waarde.strip():
            return waarde.strip()
    return None


def detail_verboden(robots: str) -> bool:
    """Sluit de robots.txt van www.funda.nl /detail/ uit voor alle bots? Dan stoppen we.

    Dit is een signaal over www.funda.nl, niet meer. Het dekt de detail-calls
    zelf níet: die gaan via pyfunda naar listing-detail-page.funda.io, en daar
    staat `Disallow: /` (zie CLAUDE.md). Deze check kan die calls dus nooit
    tegenhouden.

    Eenvoudige lezing, bewust aan de voorzichtige kant: een Disallow voor `*`
    die /detail/koop/ raakt, telt, tenzij een langere Allow hem opheft.
    """
    pad = "/detail/koop/x/y/1/"
    in_ster = False
    beste: tuple[int, bool] | None = None
    for ruw in robots.splitlines():
        regel = ruw.split("#", 1)[0].strip()
        sleutel, _, waarde = regel.partition(":")
        sleutel, waarde = sleutel.strip().lower(), waarde.strip()
        if sleutel == "user-agent":
            in_ster = waarde == "*"
            continue
        if not in_ster or sleutel not in ("allow", "disallow") or not waarde:
            continue
        patroon = "^" + "".join(".*" if c == "*" else re.escape(c) for c in waarde.rstrip("$"))
        if re.match(patroon, pad):
            kandidaat = (len(waarde), sleutel == "allow")
            if beste is None or kandidaat[0] > beste[0] or (kandidaat[0] == beste[0] and kandidaat[1]):
                beste = kandidaat
    return beste is not None and not beste[1]


def parse_datum(waarde: str | None) -> datetime | None:
    if not waarde:
        return None
    w = waarde.strip().replace("Z", "+00:00")
    for poging in (w, w[:10]):
        try:
            d = datetime.fromisoformat(poging)
        except ValueError:
            continue
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def woning_uit_url(url: str) -> dict[str, str] | None:
    """{'pad', 'stad', 'slug', 'type', 'url_id'} of None als het geen koopwoning is.

    Accepteert ook een pad (`/detail/koop/...`) en een URL zonder slash aan het
    eind of met een query; zo staan ze soms in de tracking.
    """
    u = str(url or "").strip().split("#", 1)[0].split("?", 1)[0]
    if u.startswith("/detail/"):
        u = "https://www.funda.nl" + u
    if u and not u.endswith("/"):
        u += "/"
    m = WONING_URL.match(u)
    if not m:
        return None
    pad, stad, slug, url_id = m.groups()
    return {"pad": pad, "stad": stad.lower(), "slug": slug.lower(),
            "type": slug.lower().split("-", 1)[0], "url_id": url_id}


def stad_slug(stad: Any) -> str:
    """Een stad zoals funda hem in de URL zet: kleine letters, spaties als koppelteken.

    "Den Haag" en " den haag" worden zo allebei "den-haag". Zonder dit viel een
    stad met een spatie in de config stil weg: nul URL's, en geen foutmelding.
    """
    return re.sub(r"\s+", "-", str(stad or "").strip().lower())


def kandidaten_uit(
    items: Iterable[tuple[str, str | None]],
    steden: Iterable[str],
    *,
    alleen_appartement: bool = True,
) -> list[dict[str, Any]]:
    """Woningen in de gekozen steden, nieuwste lastmod eerst."""
    stadset = {stad_slug(s) for s in steden}
    uit: dict[str, dict[str, Any]] = {}
    for loc, lastmod in items:
        w = woning_uit_url(loc)
        if not w or w["stad"] not in stadset:
            continue
        if alleen_appartement and w["type"] in GEEN_APPARTEMENT_SLUG:
            continue
        w["lastmod"] = lastmod
        vorige = uit.get(w["url_id"])
        if vorige is None or (lastmod or "") > (vorige.get("lastmod") or ""):
            uit[w["url_id"]] = w
    return sorteer_nieuwste_eerst(uit.values())


def sorteer_nieuwste_eerst(kandidaten: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(kandidaten, key=lambda k: parse_datum(k["lastmod"]) or minimum, reverse=True)


def in_doelmarkt(
    data: dict[str, Any],
    prijs_min: int | None,
    prijs_max: int | None,
    m2_min: int | None,
) -> bool:
    """Zelfde criteria als de oude zoekopdracht: beschikbaar, prijs, oppervlak.

    Ontbreekt prijs of oppervlak, dan doorlaten (stil verliezen is erger).
    """
    if (data.get("status") or "available") != "available":
        return False
    prijs = data.get("price")
    if isinstance(prijs, (int, float)) and prijs:
        if prijs_min is not None and prijs < prijs_min:
            return False
        if prijs_max is not None and prijs > prijs_max:
            return False
    m2 = data.get("living_area")
    if m2_min and isinstance(m2, (int, float)) and m2 and m2 < m2_min:
        return False
    return True


def velden_uit(data: dict[str, Any]) -> dict[str, Any]:
    """De cachevelden van een detail-antwoord, plus het statuskenmerk.

    `status` (pyfunda: IsSoldOrRented) kent alleen sold/available. Het kenmerk
    "Status" uit de Overdracht-sectie zegt ook "Onder bod" of "Verkocht onder
    voorbehoud"; dat gaat mee voor de meting of een gewijzigde lastmod iets zegt.
    """
    velden = {v: data.get(v) for v in CACHE_VELDEN if data.get(v) is not None}
    kenmerk = (data.get("characteristics") or {}).get("Status")
    if kenmerk:
        velden["status_kenmerk"] = kenmerk
    return velden


# Speling bij het vergelijken van de lastmod per koop-sitemap. Gemeten op 6 nov
# 2026: twee verzoeken vlak na elkaar gaven voor koop3 04:59:26 en 04:59:27 (met
# dezelfde ETag en Last-Modified); de index wordt kennelijk per verzoek opgebouwd.
# Een exacte vergelijking zag daardoor elke run een "gewijzigde" index. Een
# nieuwe snapshot ligt ~24 uur verder, dus 10 minuten speling mist er geen.
INDEX_SPELING_SECONDEN = 600


def index_kenmerk(
    koop: Iterable[tuple[str, str | None]],
    last_modified: str | None,
    steden: Iterable[str],
) -> dict[str, Any] | None:
    """Wat van de index bepaalt of de vorige kandidatenlijst nog geldt, of None.

    Liefst de <lastmod> per koop-sitemap uit de index. Ontbreekt er één, dan de
    Last-Modified-header van de index. Ontbreekt die ook, dan None: niet te
    bepalen of er iets veranderd is, dus elke run opnieuw ophalen.
    De steden en de slug-afwijslijst tellen mee (`regels`), want de
    kandidatenlijst hangt daarvan af: verandert een van beide, dan opnieuw.
    """
    regels = json.dumps({"steden": sorted(stad_slug(s) for s in steden),
                         "afwijzen": sorted(GEEN_APPARTEMENT_SLUG), "versie": CACHE_VERSIE},
                        sort_keys=True).encode("utf-8")
    kenmerk: dict[str, Any] = {"regels": hashlib.sha256(regels).hexdigest()[:16]}
    koop = sorted((u, lm) for u, lm in koop)
    if koop and all(parse_datum(lm) for _u, lm in koop):
        kenmerk["lastmod"] = {u: lm for u, lm in koop}
    elif last_modified:
        kenmerk["last_modified"] = last_modified
        kenmerk["kinderen"] = [u for u, _lm in koop]
    else:
        return None
    return kenmerk


def index_ongewijzigd(oud: dict[str, Any] | None, nieuw: dict[str, Any] | None) -> bool:
    """Wijst de index nog naar dezelfde snapshot als de vorige run?

    Per koop-sitemap dezelfde URL en een lastmod binnen INDEX_SPELING_SECONDEN;
    zonder lastmod exact dezelfde Last-Modified. Bij twijfel False: dan worden de
    sitemaps opnieuw opgehaald, en dat kost alleen bandbreedte.
    """
    if not oud or not nieuw or oud.get("regels") != nieuw.get("regels"):
        return False
    if "lastmod" in nieuw:
        vorig, nu = oud.get("lastmod") or {}, nieuw["lastmod"]
        if set(vorig) != set(nu):
            return False
        for url, lm in nu.items():
            a, b = parse_datum(vorig[url]), parse_datum(lm)
            if a is None or b is None or abs((a - b).total_seconds()) > INDEX_SPELING_SECONDEN:
                return False
        return True
    return (bool(nieuw.get("last_modified")) and oud.get("last_modified") == nieuw["last_modified"]
            and oud.get("kinderen") == nieuw.get("kinderen"))


# -- Drop-in --------------------------------------------------------------------

class SitemapZoeker:
    """Drop-in vervanger voor het Funda-object, met funda's sitemaps als bron.

    Gebruikt de meegegeven pyfunda-client alleen voor detail-calls (en stuurt
    alles wat hij zelf niet kent naar die client door, zoals de prijshistorie
    die het rapport opvraagt).
    """

    def __init__(
        self,
        detail_client: Any,
        *,
        steden: Iterable[str] = STANDAARD_STEDEN,
        prijs_min: int | None = None,
        prijs_max: int | None = None,
        m2_min: int | None = None,
        max_verkennen: int = 200,
        max_seconden: float = MAX_SECONDEN,
        overslaan: Callable[[dict[str, Any]], bool] | None = None,
        cache_pad: Path | str | None = None,
        haal: Callable[[str], Any] | None = None,
        pauze: float = 0.4,
        log: Callable[[str], None] | None = None,
        nu: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = detail_client
        self._steden = tuple(dict.fromkeys(stad_slug(s) for s in steden if stad_slug(s)))
        self._max_seconden = float(max_seconden)
        # Klok, te vervangen in tests: de leeftijdscheck vergelijkt met nu.
        self._nu = nu or (lambda: datetime.now(timezone.utc))
        self._prijs_min = prijs_min
        self._prijs_max = prijs_max
        self._m2_min = m2_min
        self._max_verkennen = max(0, int(max_verkennen))
        self._overslaan = overslaan
        self._cache_pad = Path(cache_pad) if cache_pad else None
        self._haal_extern = haal
        self._pauze = pauze
        self._log = log or (lambda _b: None)
        self._sessie = None
        self._laatste_verzoek = 0.0
        self._laatste_headers: dict[str, str] = {}
        self._index: tuple[str, str, list[tuple[str, str | None]], str | None] | None = None
        self._listings: dict[str, Any] = {}
        self._resultaten: list[dict[str, Any]] | None = None
        self._fout: Exception | None = None
        self._woningen: dict[str, dict[str, Any]] | None = None
        self._index_info: dict[str, Any] | None = None
        self._vuil = False
        self._afgehandeld: dict[str, str] = {}
        self._kandidaat_per_id: dict[str, dict[str, Any]] = {}
        self.verzoeken = 0
        self.reden: str | None = None
        self.statistiek: dict[str, Any] = {}
        self.meting: Counter[str] = Counter()
        self.kandidaten: list[dict[str, Any]] = []

    # -- HTTP ---------------------------------------------------------------

    def _haal(self, url: str) -> str:
        # Minstens `pauze` tussen twee verzoeken aan www.funda.nl.
        wacht = self._pauze - (time.monotonic() - self._laatste_verzoek)
        if wacht > 0:
            time.sleep(wacht)
        self.verzoeken += 1
        try:
            tekst, headers = self._haal_http(url)
        finally:
            self._laatste_verzoek = time.monotonic()
        self._laatste_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        return tekst

    def _haal_http(self, url: str) -> tuple[str, dict[str, str]]:
        if self._haal_extern is not None:
            antwoord = self._haal_extern(url)
            if isinstance(antwoord, tuple):
                return antwoord[0], dict(antwoord[1] or {})
            return antwoord, {}
        if self._sessie is None:
            from curl_cffi import requests as curl_requests  # lokaal: alleen hier nodig

            self._sessie = curl_requests.Session(impersonate=IMPERSONATE)
        resp = self._sessie.get(
            url,
            headers={"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"{url} gaf status {resp.status_code}")
        ruw = resp.content or b""
        if ruw[:2] == b"\x1f\x8b":  # .xml.gz zonder content-encoding
            ruw = gzip.decompress(ruw)
        headers = getattr(resp, "headers", None) or {}
        return ruw.decode("utf-8", errors="replace"), {k: v for k, v in headers.items()}

    def _haal_xml(self, url: str) -> str:
        tekst = self._haal(url)
        if "Je bent bijna op de pagina" in tekst or "<html" in tekst[:500].lower():
            raise RuntimeError(f"{url} gaf HTML (bot-controle of foutpagina) in plaats van XML")
        return tekst

    def _index_url(self) -> str:
        try:
            robots = self._haal(ROBOTS_URL)
        except Exception as exc:  # noqa: BLE001
            self._log(f"robots.txt niet te lezen ({exc}); gebruik {SITEMAP_INDEX_URL}.")
            return SITEMAP_INDEX_URL
        if "<html" in robots[:500].lower():
            self._log(f"robots.txt gaf HTML; gebruik {SITEMAP_INDEX_URL}.")
            return SITEMAP_INDEX_URL
        if detail_verboden(robots):
            raise RuntimeError("robots.txt van www.funda.nl sluit /detail/ uit; "
                               "sitemaproute staat uit.")
        return sitemap_uit_robots(robots) or SITEMAP_INDEX_URL

    def _lees_index(self) -> tuple[str, str, list[tuple[str, str | None]], str | None]:
        """robots.txt en de index: één keer per run, ook als bereikbaar() al keek."""
        if self._index is None:
            index_url = self._index_url()
            tekst = self._haal_xml(index_url)
            last_modified = self._laatste_headers.get("last-modified")
            soort, kinderen = ontleed_sitemap(tekst)
            self._index = (index_url, soort, kinderen, last_modified)
        return self._index

    def bereikbaar(self) -> bool:
        """Is de sitemap-index te lezen en noemt hij koop-sitemaps? Twee verzoeken.

        Die twee worden onthouden: de zoekronde daarna haalt robots.txt en de
        index niet nog eens op. Lukt het niet, dan staat de oorzaak in `reden`
        en geeft elke zoekaanroep daarna dezelfde fout, zonder nieuw verzoek.
        """
        try:
            index_url, soort, kinderen, _lm = self._lees_index()
            if soort != "index" or not any(KOOP_KIND.search(u) for u, _ in kinderen):
                raise RuntimeError(f"Sitemap-index {index_url} noemt geen koop-sitemaps "
                                   f"(soort {soort}, {len(kinderen)} items).")
        except Exception as exc:  # noqa: BLE001
            self.reden = str(exc)
            self._fout = exc
            self._log(f"Sitemaps niet bereikbaar: {exc}")
            return False
        return True

    def ophalen(self) -> None:
        """Het zoekwerk nu doen in plaats van bij de eerste search_listing().

        bereikbaar() kijkt alleen naar robots.txt en de index; dit haalt ook de
        koop-sitemaps op en doet de detail-calls. Zo komt in 'auto' een fout
        daarbij in de ::error van kies_zoeker(). Gooit dezelfde fout als zoeken
        zou gooien; het resultaat wordt onthouden, dus het kost niets extra.
        """
        self._bouw()

    # -- Drop-in API --------------------------------------------------------

    def search_listing(
        self,
        location: Any = None,
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
    ) -> list[SitemapResultaat]:
        """Zelfde aanroep als pyfunda's search_listing.

        De sitemaps zijn één vaste lijst, dus alles staat op pagina 0; elke
        volgende pagina is leeg, zodat de pagineerlus in funda_zoek.py stopt.
        Prijs, oppervlak en beschikbaarheid worden hier gefilterd, zoals de oude
        API dat deed. Locatie en straal niet: daarvoor zijn de steden en de
        stad-/buurt-/afstandsfilters in funda_zoek.py.
        """
        if offering_type != "buy":
            raise ValueError("SitemapZoeker ondersteunt alleen offering_type='buy'")
        if page:
            return []
        resultaten = self._bouw()
        alleen_beschikbaar = availability is None or "available" in list(availability)
        uit: list[SitemapResultaat] = []
        for data in resultaten:
            prijs = data.get("price") or 0
            if price_min is not None and prijs and prijs < price_min:
                continue
            if price_max is not None and prijs and prijs > price_max:
                continue
            m2 = data.get("living_area") or 0
            if area_min and m2 and m2 < area_min:
                continue
            if alleen_beschikbaar and (data.get("status") or "available") != "available":
                continue
            uit.append(SitemapResultaat(dict(data)))
        return uit

    def get_listing(self, listing_id: Any) -> Any:
        """Detail-call, maar bij voorkeur uit wat het zoeken al ophaalde.

        Herkent ook een woning-URL (zo vraagt de pool erom): het nummer aan het
        eind is het tiny_id waaronder de woning hier is onthouden.
        """
        sleutel = str(listing_id)
        if sleutel in self._listings:
            return self._listings[sleutel]
        if "/detail/" in sleutel:
            m = TINY_IN_URL.search(sleutel)
            if m and m.group(1) in self._listings:
                return self._listings[m.group(1)]
        return self._client.get_listing(listing_id)

    def __getattr__(self, naam: str) -> Any:
        if naam.startswith("_"):
            raise AttributeError(naam)
        return getattr(self._client, naam)

    # -- Samenwerking met de pool ------------------------------------------

    def pool_oordeel(self, ident: Any) -> str:
        """Wat deed deze zoeker deze run met de woning achter `ident`?

        `ident` is een woning-URL of -pad (zoals in de tracking), of een tiny_id
        of global_id. Antwoorden:
        - OPGEHAALD: deze run opgehaald; get_listing() geeft hem zonder call.
        - MISLUKT: deze run geprobeerd en mislukt; niet nog eens proberen.
        - OVERGESLAGEN: lastmod ongewijzigd en de cache zegt buiten de doelmarkt
          of afgewezen door een filter; er is niets veranderd, dus geen call.
        - ACHTERSTAND: staat in de sitemap maar is deze run nog niet verkend.
        - NIET_IN_SITEMAP: stad en type vallen onder deze sitemaps, maar de
          woning staat er niet (meer) in; waarschijnlijk verkocht of ingetrokken.
        - ONBEKEND: niet te zeggen (geen URL, andere stad, of nog niet gezocht).
        """
        if self._resultaten is None:
            return ONBEKEND
        tekst = str(ident or "").strip()
        if tekst in self._listings:
            return OPGEHAALD
        w = woning_uit_url(tekst) if "/detail/" in tekst else None
        url_id = w["url_id"] if w else (tekst if re.fullmatch(r"\d{8,9}", tekst) else None)
        if url_id:
            if url_id in self._afgehandeld:
                return self._afgehandeld[url_id]
            if url_id in self._kandidaat_per_id:
                return ACHTERSTAND
        if w and w["stad"] in self._steden and w["type"] not in GEEN_APPARTEMENT_SLUG:
            return NIET_IN_SITEMAP
        return ONBEKEND

    def neem_op(self, listing: Any) -> bool:
        """Leg een elders (door de pool) opgehaalde woning vast in de cache.

        Alleen voor een kandidaat die deze run nog niet is opgehaald: dan hoeft
        de volgende run hem niet opnieuw te verkennen. Geeft True als dat zo is.
        Roep daarna bewaar_cache() aan.
        """
        if self._woningen is None:
            return False
        data = dict(getattr(listing, "data", None) or {})
        url_id = str(data.get("tiny_id") or "")
        if not url_id:
            w = woning_uit_url(str(data.get("detail_url") or data.get("url") or ""))
            url_id = w["url_id"] if w else ""
        k = self._kandidaat_per_id.get(url_id)
        if not k or self._afgehandeld.get(url_id) == OPGEHAALD:
            return False
        data.setdefault("detail_url", k["pad"])
        self._woningen[url_id] = {"lastmod": k["lastmod"], "velden": velden_uit(data)}
        self._afgehandeld[url_id] = OPGEHAALD
        self._onthoud(listing, data, url_id)
        self._vuil = True
        return True

    def bewaar_cache(self) -> None:
        if not self._vuil or not self._cache_pad or self._woningen is None:
            return
        self._cache_pad.write_text(
            json.dumps({"versie": CACHE_VERSIE, "index": self._index_info or {},
                        "woningen": self._woningen}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._vuil = False

    # -- Intern -------------------------------------------------------------

    def _laad_cache(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """(woningen, index-info) uit de cache; leeg als er niets bruikbaars is."""
        if not self._cache_pad or not self._cache_pad.exists():
            return {}, {}
        try:
            ruw = json.loads(self._cache_pad.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._log(f"Sitemap-cache onleesbaar ({exc}); begin leeg.")
            return {}, {}
        versie = ruw.get("versie")
        if versie not in (1, CACHE_VERSIE):
            return {}, {}
        index = dict(ruw.get("index") or {}) if versie == CACHE_VERSIE else {}
        return dict(ruw.get("woningen") or {}), index

    def _is_doel(self, velden: dict[str, Any]) -> bool:
        """Doelmarkt én niet afgewezen door de filters van de aanroeper."""
        if not in_doelmarkt(velden, self._prijs_min, self._prijs_max, self._m2_min):
            return False
        return not (self._overslaan and self._overslaan(velden))

    def _bouw(self) -> list[dict[str, Any]]:
        """Eén keer per run: ontdekken, verrijken, filteren. Fouten blijven staan.

        Een fout wordt onthouden en bij elke volgende aanroep opnieuw gegooid, in
        plaats van per prijsband en sortering alles nog eens op te halen.
        """
        if self._fout is not None:
            raise self._fout
        if self._resultaten is not None:
            return self._resultaten
        try:
            self._resultaten = self._ontdek_en_verrijk()
        except Exception as exc:
            self._fout = exc
            raise
        return self._resultaten

    def _kandidaten_ophalen(
        self, koop: list[tuple[str, str | None]],
    ) -> tuple[list[dict[str, Any]], int, Counter[str], Counter[str]]:
        """Alle koop-sitemaps downloaden en de kandidaten eruit halen.

        Geeft (kandidaten, aantal URL's, types in de steden, URL's per stad).
        """
        items: list[tuple[str, str | None]] = []
        for url, _lm in koop:
            _s, deel = ontleed_sitemap(self._haal_xml(url))
            if not deel:
                raise RuntimeError(f"{url} bevat geen URL's.")
            items.extend(deel)
        types: Counter[str] = Counter()
        per_stad: Counter[str] = Counter()
        for loc, _lm in items:
            w = woning_uit_url(loc)
            if w and w["stad"] in self._steden:
                types[w["type"]] += 1
                per_stad[w["stad"]] += 1
        return kandidaten_uit(items, self._steden), len(items), types, per_stad

    def _ontdek_en_verrijk(self) -> list[dict[str, Any]]:
        start = time.monotonic()
        nu = self._nu()
        index_url, soort, kinderen, last_modified = self._lees_index()
        koop = [(u, lm) for u, lm in kinderen if KOOP_KIND.search(u)]
        if soort != "index" or not koop:
            raise RuntimeError(f"Sitemap-index {index_url} noemt geen koop-sitemaps "
                               f"(soort {soort}, {len(kinderen)} items).")
        index_lastmod = max((lm for _u, lm in koop if lm), default=None) or last_modified

        cache, vorige_index = self._laad_cache()
        kenmerk = index_kenmerk(koop, last_modified, self._steden)
        ongewijzigd = bool(index_ongewijzigd(vorige_index.get("kenmerk"), kenmerk)
                           and vorige_index.get("kandidaten"))
        # Hoe oud de bewaarde kandidatenlijst is. Zonder tijdstip (cache van vóór
        # deze regel): onbekend, dus opnieuw ophalen.
        opgehaald_op = parse_datum(vorige_index.get("opgehaald_op"))
        vers_genoeg = bool(opgehaald_op
                           and nu - opgehaald_op <= timedelta(hours=MAX_HERGEBRUIK_UUR))
        hergebruikt = ongewijzigd and vers_genoeg
        if hergebruikt:
            # Het opgeslagen kenmerk blijft staan, niet het nieuwe: zo kan de
            # speling van een seconde per run zich niet opstapelen.
            kenmerk = vorige_index["kenmerk"]
            index_lastmod = vorige_index.get("index_lastmod") or index_lastmod
            kandidaten = []
            for pad, lastmod in vorige_index["kandidaten"]:
                w = woning_uit_url(pad)
                if w:
                    w["lastmod"] = lastmod
                    kandidaten.append(w)
            kandidaten = sorteer_nieuwste_eerst(kandidaten)
            n_urls = int(vorige_index.get("urls") or 0)
            types: Counter[str] = Counter(vorige_index.get("types_in_steden") or {})
            # Een cache zonder telling per stad: dan tellen de kandidaten.
            per_stad: Counter[str] = (Counter(vorige_index.get("per_stad") or {})
                                      or Counter(k["stad"] for k in kandidaten))
            self._log(f"Sitemaps: index ongewijzigd sinds de vorige run (lastmod {index_lastmod}); "
                      f"de {len(koop)} koop-sitemaps niet opnieuw opgehaald, "
                      f"{len(kandidaten)} kandidaten uit de cache "
                      f"(lijst van {vorige_index.get('opgehaald_op')}).")
        else:
            if not kenmerk:
                waarom = "index geeft geen lastmod en geen Last-Modified"
            elif ongewijzigd:
                waarom = (f"index ongewijzigd, maar de kandidatenlijst is ouder dan "
                          f"{MAX_HERGEBRUIK_UUR} uur (van {vorige_index.get('opgehaald_op') or 'onbekend'})")
            elif vorige_index.get("kenmerk"):
                waarom = (f"index gewijzigd (nieuwste lastmod {index_lastmod}, "
                          f"was {vorige_index.get('index_lastmod')})")
            else:
                waarom = "geen eerdere index in de cache"
            self._log(f"Sitemaps: {waarom}; {len(koop)} koop-sitemaps ophalen.")
            kandidaten, n_urls, types, per_stad = self._kandidaten_ophalen(koop)
            opgehaald_op = nu
        self.kandidaten = kandidaten
        # Per stad, niet alleen samen: een typfout of een andere slug bij funda
        # liet anders één stad stil wegvallen terwijl de rest gewoon doorliep.
        zonder = [s for s in self._steden if not per_stad.get(s)]
        if zonder:
            wel = [s for s in self._steden if per_stad.get(s)]
            raise RuntimeError(
                f"Geen enkele sitemap-URL voor {', '.join(zonder)} in {n_urls} URL's "
                f"(wel voor: {', '.join(wel) or 'geen'}). Typfout in sitemap_steden, "
                f"of gebruikt funda een andere slug voor die stad?")
        if not kandidaten:
            raise RuntimeError(f"Geen woningen in {', '.join(self._steden)} in "
                               f"{n_urls} sitemap-URL's; markup of URL-vorm gewijzigd?")
        nieuwste = parse_datum(kandidaten[0]["lastmod"])
        # Bevroren sitemap: de run zou groen blijven terwijl er nooit meer iets
        # nieuws binnenkomt. Zonder lastmod werkt ook de cache niet (alles zou
        # "ongewijzigd" lijken), dus dat telt net zo.
        if nieuwste is None:
            raise RuntimeError(f"Geen leesbare <lastmod> bij de {len(kandidaten)} kandidaten; "
                               f"sitemap-vorm gewijzigd?")
        if nu - nieuwste > timedelta(days=MAX_LEEFTIJD_DAGEN):
            raise RuntimeError(
                f"Sitemaps lijken bevroren: de nieuwste lastmod onder {len(kandidaten)} "
                f"kandidaten is {nieuwste.isoformat()}, {(nu - nieuwste).days} dagen oud "
                f"(max {MAX_LEEFTIJD_DAGEN}). Zo zou er stil geen nieuw aanbod meer binnenkomen.")
        self._log(f"Sitemaps: {len(koop)} koop-sitemaps, {n_urls} URL's, "
                  f"{len(kandidaten)} kandidaten in {', '.join(self._steden)} "
                  f"({', '.join(f'{s} {per_stad.get(s, 0)}' for s in self._steden)} URL's); "
                  f"nieuwste lastmod {nieuwste.isoformat()}.")
        self._kandidaat_per_id = {k["url_id"]: k for k in kandidaten}
        self._index_info = {
            "kenmerk": kenmerk,
            "index_lastmod": index_lastmod,
            "urls": n_urls,
            "types_in_steden": dict(types.most_common()),
            "per_stad": dict(per_stad),
            "opgehaald_op": opgehaald_op.isoformat() if opgehaald_op else None,
            "kandidaten": [[k["pad"], k["lastmod"]] for k in kandidaten],
        }

        # Weg uit de sitemap = weg van funda. Snoeien houdt de cache klein.
        voor_snoeien = len(cache)
        cache = {k: v for k, v in cache.items() if k in self._kandidaat_per_id}
        gesnoeid = voor_snoeien - len(cache)

        verversen: list[dict[str, Any]] = []   # bekend en in doelmarkt: altijd vers
        verkennen: list[dict[str, Any]] = []   # nieuw of gewijzigd: nieuwste eerst
        buiten = gewijzigd = 0
        for k in kandidaten:
            c = cache.get(k["url_id"])
            if c and c.get("lastmod") == k["lastmod"]:
                if self._is_doel(c.get("velden") or {}):
                    verversen.append(k)
                else:
                    buiten += 1
                    self._afgehandeld[k["url_id"]] = OVERGESLAGEN
            else:
                verkennen.append(k)
                gewijzigd += 1 if c else 0

        te_doen = verversen + verkennen[: self._max_verkennen]
        ververs_ids = {k["url_id"] for k in verversen}
        meting = self.meting
        meting["lastmod_gewijzigd"] = gewijzigd
        resultaten: list[dict[str, Any]] = []
        calls = fouten = geslaagd = op_rij = n_verkend = 0
        budget_op = False
        t0 = time.monotonic()
        for k in te_doen:
            verkennend = k["url_id"] not in ververs_ids
            if verkennend:
                # Tijdsbudget alleen voor het verkennen: de rest is achterstand.
                if time.monotonic() - t0 > self._max_seconden:
                    budget_op = True
                    break
                n_verkend += 1
            calls += 1
            oud = cache.get(k["url_id"])
            data, exc = self._detail(k)
            if data is None:
                fouten += 1
                self._afgehandeld[k["url_id"]] = MISLUKT
                if isinstance(exc, WoningNietGevonden):
                    # Een nette 404: het endpoint werkt, deze woning is weg. Geen
                    # storing. Geeft het endpoint voor álles een 404, dan komt er
                    # niets in de doelmarkt en stopt main() op "nul woningen".
                    # Een 404 is een antwoord, dus de reeks storingen is voorbij:
                    # anders telden time-outs met 404's ertussen door tot DICHT_NA,
                    # en liet één time-out vóór een laatste 404 de run falen.
                    op_rij = 0
                    continue
                op_rij += 1
                fout = f"{type(exc).__name__}: {exc}" if exc else "leeg antwoord"
                if isinstance(exc, DetailEndpointDicht) or op_rij >= DICHT_NA:
                    # Eerst bewaren wat wél lukte, zodat de verkenning van deze
                    # run niet verloren gaat. Daarna stoppen: verder ophalen geeft
                    # een half rapport (verversen-woningen weg) dat de volgende
                    # run, die al bij het opzetten faalt, laat staan.
                    self._woningen = cache
                    self._vuil = True
                    self.bewaar_cache()
                    if isinstance(exc, DetailEndpointDicht):
                        raise DetailEndpointDicht(f"Detail-endpoint werkt niet: {exc}") from exc
                    raise DetailEndpointDicht(
                        f"Detail-endpoint werkt niet: {op_rij} detail-calls op rij mislukt, "
                        f"na {geslaagd} geslaagde deze run (laatste: {fout}).")
                continue
            op_rij = 0
            geslaagd += 1
            self._afgehandeld[k["url_id"]] = OPGEHAALD
            velden = velden_uit(data)
            if oud:
                self._meet(oud.get("velden") or {}, velden,
                           "lastmod_gelijk" if k["url_id"] in ververs_ids else "lastmod_gewijzigd")
            cache[k["url_id"]] = {"lastmod": k["lastmod"], "velden": velden}
            if self._is_doel(velden):
                resultaten.append(data)

        achterstand = len(verkennen) - n_verkend
        self._woningen = cache
        self._vuil = True
        self.bewaar_cache()
        self.statistiek = {
            "koop_sitemaps": len(koop), "urls": n_urls, "kandidaten": len(kandidaten),
            "index_ongewijzigd": hergebruikt, "index_lastmod": index_lastmod,
            "koop_sitemaps_opgehaald": 0 if hergebruikt else len(koop),
            "nieuwste_lastmod": nieuwste.isoformat() if nieuwste else None,
            "uit_cache_buiten_doel": buiten, "ververst": len(verversen),
            "verkend": n_verkend, "achterstand": achterstand,
            "detail_calls": calls, "detail_fouten": fouten, "in_doelmarkt": len(resultaten),
            # Voor de pool: bewijs dat het endpoint deze run werkte, en hoeveel
            # calls aan het eind op rij mislukten (de pool telt daar verder mee).
            "detail_geslaagd": geslaagd, "detail_op_rij_mislukt": op_rij,
            "tijdsbudget_op": budget_op,
            "uit_sitemap_gesnoeid": gesnoeid, "sitemap_verzoeken": self.verzoeken,
            "seconden": round(time.monotonic() - start, 1),
            "types_in_steden": dict(types.most_common()),
        }
        self._log(
            f"Sitemaps: {calls} detail-calls ({len(verversen)} ververst, "
            f"{n_verkend} verkend, {fouten} mislukt), "
            f"{buiten} uit cache overgeslagen, {len(resultaten)} in doelmarkt; "
            f"{self.verzoeken} sitemap-verzoeken."
            + (f" Tijdsbudget van {self._max_seconden:.0f} s op." if budget_op else "")
            + (f" Achterstand: {achterstand} nog niet verkend, volgt volgende run."
               if achterstand else "")
        )
        # Meting voor de eerste week, alleen getallen: zegt een gewijzigde
        # lastmod iets over prijs of status, en mist een ongewijzigde lastmod
        # wijzigingen? Dat tweede bepaalt of het overslaan op cache veilig is.
        self._log(
            f"Meting lastmod: {gewijzigd} gecachte woning(en) met gewijzigde lastmod, "
            f"{meting['lastmod_gewijzigd_opgehaald']} opgehaald: "
            f"{meting['lastmod_gewijzigd_andere_prijs']} andere prijs, "
            f"{meting['lastmod_gewijzigd_andere_status']} andere status "
            f"({gewijzigd - meting['lastmod_gewijzigd_opgehaald']} nog niet opgehaald). "
            f"Ververst met ongewijzigde lastmod: {meting['lastmod_gelijk_opgehaald']}, "
            f"waarvan {meting['lastmod_gelijk_andere_prijs']} andere prijs en "
            f"{meting['lastmod_gelijk_andere_status']} andere status. "
            f"Sinds de vorige run uit de sitemap verdwenen: {gesnoeid}."
        )
        return resultaten

    def _meet(self, oud: dict[str, Any], nieuw: dict[str, Any], soort: str) -> None:
        self.meting[f"{soort}_opgehaald"] += 1
        if oud.get("price") != nieuw.get("price"):
            self.meting[f"{soort}_andere_prijs"] += 1
        # Een cache van vóór het statuskenmerk telt alleen op `status`.
        andere_status = oud.get("status") != nieuw.get("status") or (
            "status_kenmerk" in oud and oud.get("status_kenmerk") != nieuw.get("status_kenmerk"))
        if andere_status:
            self.meting[f"{soort}_andere_status"] += 1

    def _onthoud(self, listing: Any, data: dict[str, Any], url_id: str) -> None:
        for id_veld in ("global_id", "listing_id", "tiny_id"):
            waarde = data.get(id_veld)
            if waarde:
                self._listings[str(waarde)] = listing
        self._listings[url_id] = listing

    def _detail(self, k: dict[str, Any]) -> tuple[dict[str, Any] | None, Exception | None]:
        """(data, None) bij succes; (None, fout) of (None, None) bij een leeg antwoord."""
        try:
            listing = self._client.get_listing(f"https://www.funda.nl{k['pad']}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Detail mislukt voor {k['pad']}: {type(exc).__name__}: {exc}")
            return None, exc
        finally:
            time.sleep(self._pauze)
        data = dict(getattr(listing, "data", None) or {})
        if not data:
            return None, None
        data.setdefault("detail_url", k["pad"])
        data["_bron"] = "sitemap"
        data["_sitemap_lastmod"] = k["lastmod"]
        self._onthoud(listing, data, k["url_id"])
        return data, None
