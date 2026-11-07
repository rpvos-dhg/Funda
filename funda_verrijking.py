"""Verrijking per woning uit open bronnen (CLAUDE.md, "Verrijking").

Vier bronnen, elk fail-soft: een kapotte bron geeft "onbekend" en de run gaat door.

- bag:       PDOK BAG OGC API v2. Bouwjaar en aantal verblijfsobjecten van het pand
             (benadering van de VvE-grootte), gebruiksdoel van het verblijfsobject.
- fundering: Klimaateffectatlas, risicokaarten fundering 2050 hoog (Deltares 2021),
             verschilzetting en paalrot op buurtniveau. Alleen bij een pand van voor 1970.
- geluid:    RIVM-geluidkaarten aan de gevel: Lden en Lnight, wegverkeer 2022 en trein 2023.
- buurt:     buurtcode via PDOK CBS-buurten 2024, Leefbaarometer 3.0 (2024) en de
             RIVM-gezondheidsmonitor 2024 (tevredenheid, via CBS dataderden 50150NED).

Laag- en veldnamen zijn gemeten op 7 nov 2026 (ingekorte antwoorden in
testdata/verrijking/). Gemeten op openbare plekken (het Plein en het stadhuis in Den
Haag), nooit op een woonadres.

Regels (CLAUDE.md):
- Al het netwerk loopt via één injecteerbare functie `http(url, timeout=, headers=)`
  die `(status, body_bytes)` teruggeeft; de tests geven een nep-functie mee.
- Eerlijke user-agent (`EERLIJKE_UA` uit funda_zoek, of als parameter), time-outs,
  sequentieel met een pauze, robots.txt per host eerst. Vers op de dag van ophalen (RFC 9309
  par. 2.4: hooguit 24 uur); de laatste goede versie (hooguit 30 dagen) alleen als terugval
  wanneer robots.txt onbereikbaar is (time-out of 5xx).
- Per host stoppen bij 401/403/429/5xx. Een weigering wordt nooit omzeild: geen andere
  user-agent, host of client. Na een weigering blijft de host een dag dicht.
- Budget per run (standaard 60 verzoeken). Past en Krap eerst, daarna op score.
- Cache in het bestaande funda_enrichment_cache.json, als eigen secties (zie CACHE_SECTIES).
  Een antwoord blijft `bewaar_dagen` geldig, een fout wordt na `fout_opnieuw_na_dagen`
  (1) opnieuw geprobeerd.
- Allowlist van velden: alleen de velden in VELDEN komen in de cache. Herkomst,
  nationaliteit, inkomen en andere bevolkingskenmerken worden nooit gelezen of bewaard.
- Logregels tonen alleen aantallen per bron en status, nooit adressen, postcodes of
  coördinaten.

Daarnaast de geocoding van postcodes (werkadressen en de zoekpostcode, `Geocoder`): de
BAG-collectie adres op api.pdok.nl, met een eigen Sessie op dezelfde cache. De verrijking neemt de
stand daarvan over (Sessie.neem_over, neem_cache_over): robots.txt één keer per run, en een
weigering of serverfout van api.pdok.nl geldt voor beide.

Niet gebruikt: het WOZ-waardeloket, de KOOP SRU-dienst (robots.txt Disallow), de
PDOK Locatieserver (robots.txt Disallow) en Nominatim (robots.txt Disallow /search).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime

# ---------------------------------------------------------------- bronnen (gemeten 7 nov 2026)

BAG_BASIS = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections"
BAG_PAND_PREFIX = BAG_BASIS + "/pand/items/"
# Geocoding van een postcode: de collectie adres met een filter op postcode. Gemeten op 7 nov 2026 op
# de postcode van het stadhuis (4 adressen; testdata/verrijking/meting.json): limit=1 in 7,7 s en 11,3 s,
# limit=10 in 36,6 s, limit=50 in 24,4 s. Met minder treffers dan de limit zoekt de server de hele
# postcode af, en met limit=1 heeft een bestaande postcode er altijd genoeg. Daarom limit=1 (één
# adrespunt ligt binnen de postcode, genoeg voor straal en reisafstand), een time-out van 60 s (ruim
# vijf keer de gemeten 11,3 s), één poging per postcode per run, en de aanroeper bewaart een gevonden
# punt voorgoed.
BAG_ADRES = BAG_BASIS + "/adres/items"
GEOCODE_LIMIET = 1
GEOCODE_TIMEOUT_S = 60
GEOCODE_MAX_VERZOEKEN = 10        # robots.txt plus een handvol postcodes
NL_KADER = (50.7, 53.7, 3.2, 7.3)  # lat_min, lat_max, lon_min, lon_max: ruim om Nederland
PDOK_BUURTEN = "https://api.pdok.nl/cbs/wijken-en-buurten-2024/ogc/v1/collections/buurten/items"

KEA_WMS = "https://cas.cloud.sogelink.com/public/data/org/gws/YWFMLMWERURF/kea_public/wms"
KEA_LAGEN = {"verschilzetting": "risicoverschilzetting_2050hoog", "paalrot": "risicopaalrot_2050hoog"}
# Klassegrenzen uit de legenda van de WMS (GetLegendGraphic, format=application/json).
# Het kaartveld is sterke_c_1 (verschilzetting) of sterke_c_2 (paalrot); bovengrens inclusief.
KEA_KLASSEN = {
    "verschilzetting": ((1.0, "zeer laag"), (5.0, "laag"), (10.0, "matig"), (25.0, "hoog"), (math.inf, "zeer hoog")),
    "paalrot": ((0.8, "zeer laag"), (3.0, "laag"), (6.0, "matig"), (15.0, "hoog"), (math.inf, "zeer hoog")),
}
FUND_KLASSE = ["zeer laag", "laag", "matig", "hoog", "zeer hoog"]

RIVM_WMS = "https://data.rivm.nl/geo/alo/wms"
# Volgorde telt: de GetFeatureInfo-features hebben geen id en komen in deze volgorde terug.
RIVM_LAGEN = (
    ("lden_weg", "rivm_20250101_Geluid_lden_wegverkeer_2022"),
    ("lnight_weg", "rivm_20250101_Geluid_lnight_wegverkeer_2022"),
    ("lden_trein", "rivm_20250101_Geluid_lden_treinverkeer_2023"),
    ("lnight_trein", "rivm_20250101_Geluid_lnight_treinverkeer_2023"),
)

LBM_WFS = "https://geo.leefbaarometer.nl/lbm3/ows"
LBM_LAAG = "lbm3:buurtscore24"
LBM_JAAR = 2024
LBM_KLASSE = {1: "zeer onvoldoende", 2: "ruim onvoldoende", 3: "onvoldoende", 4: "zwak", 5: "voldoende",
              6: "ruim voldoende", 7: "goed", 8: "zeer goed", 9: "uitstekend"}

CBS_50150 = "https://dataderden.cbs.nl/ODataApi/odata/50150NED/TypedDataSet"
CBS_PERIODE = "2024JJ00"
CBS_LEEFTIJD_18PLUS = "20300"          # "18 jaar of ouder" (dimensie Leeftijd, gemeten)
CBS_MARGES = {"MW00000": "waarde", "MOG0095": "min", "MBG0095": "max"}

BRONNEN = ("bag", "fundering", "geluid", "buurt")

# ---------------------------------------------------------------- allowlist

# Alleen deze velden komen in de cache. cache_schrijf() weigert alles daarbuiten.
VELDEN = {
    "bag": ("bouwjaar", "aantal_vbo_pand", "gebruiksdoel", "gebruiksdoel_pand"),
    "fundering": ("verschilzetting", "paalrot"),
    "geluid": ("lden_weg", "lnight_weg", "lden_trein", "lnight_trein"),
    "buurtcode": ("buurtcode", "buurtnaam", "gemeentenaam"),
    "leefbaarometer": ("kscore", "lbm", "afw", "fys", "onv", "soc", "vrz", "won"),
    "tevredenheid": ("tevreden_woonomgeving", "tevreden_woonomgeving_min", "tevreden_woonomgeving_max",
                     "tevreden_woning"),
    "robots": ("regels",),
}
# De gemeentemarkering in de sectie leefbaarometer ("gemeente|<naam>") bewaart alleen een aantal.
LBM_GEMEENTE_VELDEN = ("buurten",)
CACHE_SECTIES = ("bag", "fundering", "geluid", "buurtcode", "leefbaarometer", "tevredenheid", "robots",
                 "verrijking_weigering")
# Velden die per bron in de uitvoer mogen staan (cache-velden plus wat hier wordt afgeleid).
UITVOER_VELDEN = {
    "bag": VELDEN["bag"],
    "fundering": VELDEN["fundering"] + ("bouwjaar",),
    "geluid": VELDEN["geluid"],
    "buurt": VELDEN["buurtcode"] + VELDEN["leefbaarometer"] + VELDEN["tevredenheid"],
}

# ---------------------------------------------------------------- instellingen

STANDAARD = {
    "aan": True,
    "bronnen": {"bag": True, "fundering": True, "geluid": True, "buurt": True, "tevredenheid": True},
    "max_calls_per_run": 60,
    "timeout_s": 10,
    "pauze_s": 0.25,
    "fout_opnieuw_na_dagen": 1,
    "fouten_op_rij_stop": 3,
    "bewaar_dagen": {"bag": 180, "fundering": 365, "geluid": 365, "buurtcode": 365, "leefbaarometer": 30,
                     "tevredenheid": 90, "robots": 1},
}
# RFC 9309 par. 2.4: een gecachete robots.txt niet langer dan 24 uur gebruiken, tenzij hij onbereikbaar
# is. Vers = opgehaald op dezelfde dag (twee runs per dag: hooguit één verzoek per host per dag).
# Onbereikbaar (time-out, 5xx): de laatste goede versie, hooguit ROBOTS_TERUGVAL_DAGEN oud.
ROBOTS_DAGEN = 1
ROBOTS_TERUGVAL_DAGEN = 30
# Zelfde waarden als funda_beoordeling.STANDAARD["drempels"] (dat blok is ruimer); de config kan ze overschrijven.
DREMPELS = {
    "vve_klein_max_woningen": 4,
    "fundering_bouwjaar_voor": 1970,
    "fundering_klasse_let_op": "matig",
    "geluid_lden_weg": [55, 60, 65],
    "geluid_lnight_weg": [47, 52, 57],
    "geluid_lden_trein": [54, 59, 64],
    "geluid_lnight_trein": [46, 51, 56],
    "geluid_rustig_lden": 50,
    "leefbaarometer_twijfel_max": 4,
    "leefbaarometer_goed_min": 7,
    "leefbaarometer_onv_let_op": -0.15,
    "tevreden_woonomgeving_let_op": 80,
    "tevreden_woonomgeving_goed": 90,
}
POORT_RANG = {"PAST": 0, "KRAP": 1, "PAST NIET": 3, "PRIJS ONBEKEND": 4}
POORT_ONBEKEND_RANG = 2


def _samenvoegen(basis: dict, extra: dict) -> dict:
    uit = copy.deepcopy(basis)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(uit.get(k), dict):
            uit[k] = _samenvoegen(uit[k], v)
        else:
            uit[k] = v
    return uit


def instellingen(cfg: dict | None) -> tuple[dict, dict]:
    """(verrijking, drempels) met de standaardwaarden aangevuld.

    `cfg` mag de beoordelingsconfig zijn (met "verrijking" en "drempels") of de hele
    persoonlijke config (met "beoordeling"). Ontbreekt iets, dan geldt de standaard."""
    cfg = cfg or {}
    if isinstance(cfg.get("beoordeling"), dict):
        cfg = cfg["beoordeling"]
    v = _samenvoegen(STANDAARD, cfg.get("verrijking") or {})
    dr = cfg.get("drempels") if isinstance(cfg.get("drempels"), dict) else {}
    return v, _samenvoegen(DREMPELS, {k: dr[k] for k in DREMPELS if k in dr})


# ---------------------------------------------------------------- datums en opmaak

def _datum(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _dagen(van: str, tot: str) -> int:
    return (_datum(tot) - _datum(van)).days


def _nl(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _teken(x: float, d: int = 2) -> str:
    return ("−" if x < 0 else "+") + _nl(abs(x), d)


# ---------------------------------------------------------------- cache

def cache_lees(cache: dict, sectie: str, sleutel: str, vcfg: dict, vandaag) -> tuple[object, str | None]:
    """-> (data, status). Status "vers" (gebruiken), "fout_vers" (niet opnieuw proberen)
    of None (ophalen)."""
    e = (cache.get(sectie) or {}).get(sleutel)
    if not isinstance(e, dict) or not e.get("fetched"):
        return None, None
    try:
        dagen = _dagen(e["fetched"], vandaag)
    except ValueError:
        return None, None
    if e.get("fout"):
        return (None, "fout_vers") if dagen < vcfg["fout_opnieuw_na_dagen"] else (None, None)
    if dagen <= vcfg["bewaar_dagen"].get(sectie, 30):
        return e.get("data"), "vers"
    return None, None


def _controleer_velden(sectie: str, sleutel: str, data) -> None:
    if not isinstance(data, dict):
        return
    if sectie == "leefbaarometer" and sleutel.startswith("gemeente|"):
        toegestaan = LBM_GEMEENTE_VELDEN
    else:
        toegestaan = VELDEN.get(sectie)
    if toegestaan is None:
        return
    extra = sorted(set(data) - set(toegestaan))
    if extra:
        raise ValueError(f"veld buiten de allowlist voor {sectie}: {', '.join(extra)}")


def cache_schrijf(cache: dict, sectie: str, sleutel: str, vandaag, data=None, fout: str | None = None) -> None:
    _controleer_velden(sectie, sleutel, data)
    e = {"fetched": _datum(vandaag).isoformat(), "data": data}
    if fout:
        e["fout"] = fout
    cache.setdefault(sectie, {})[sleutel] = e


def opruimen(cache: dict, vcfg: dict, vandaag) -> int:
    """Haalt verlopen elementen uit de eigen secties, zodat het bestand niet blijft groeien."""
    weg = 0
    for sectie in CACHE_SECTIES:
        s = cache.get(sectie)
        if not isinstance(s, dict):
            continue
        grens = vcfg["bewaar_dagen"].get(sectie, 30) + 30
        for k in list(s):
            e = s[k]
            datum = (e or {}).get("fetched") or (e or {}).get("datum") if isinstance(e, dict) else None
            try:
                oud = datum is None or _dagen(datum, vandaag) > grens
            except ValueError:
                oud = True
            if oud:
                del s[k]
                weg += 1
    return weg


def _hash_sleutel(soort: str, *delen) -> str:
    """Cachesleutel zonder leesbaar adres of coördinaat erin."""
    ruw = "|".join(str(d) for d in delen)
    return f"{soort}:" + hashlib.sha256(ruw.encode("utf-8")).hexdigest()[:20]


def punt_sleutel(lat: float, lon: float) -> str:
    return _hash_sleutel("pt", f"{lat:.4f}", f"{lon:.4f}")      # ~10 m


# ---------------------------------------------------------------- robots.txt

def robots_regels(tekst: str, agent: str = "funda-dagelijkse-check") -> list[list[str]]:
    """De regels uit de groep voor onze user-agent, anders de groep voor '*'."""
    groepen: list[tuple[list[str], list[list[str]]]] = []
    agents: list[str] = []
    regels: list[list[str]] = []
    in_regels = False
    for ruw in (tekst or "").splitlines():
        regel = ruw.split("#", 1)[0].strip()
        if ":" not in regel:
            continue
        veld, waarde = (x.strip() for x in regel.split(":", 1))
        veld = veld.lower()
        if veld == "user-agent":
            if in_regels:
                groepen.append((agents, regels))
                agents, regels, in_regels = [], [], False
            agents.append(waarde.lower())
        elif veld in ("allow", "disallow"):
            in_regels = True
            if agents:
                regels.append([veld, waarde])
    if agents:
        groepen.append((agents, regels))
    eigen = [r for a, r in groepen if agent.lower() in a]
    if eigen:
        return [x for r in eigen for x in r]
    return [x for a, r in groepen if "*" in a for x in r]


def _robots_patroon(p: str) -> re.Pattern:
    eind = p.endswith("$")
    kern = re.escape(p[:-1] if eind else p).replace(r"\*", ".*")
    return re.compile(kern + ("$" if eind else ""))


def robots_mag(regels: list[list[str]], pad: str) -> bool:
    """Langste overeenkomst wint; bij gelijke lengte wint allow. Lege disallow = alles mag."""
    beste_len, beste = -1, True
    for soort, patroon in regels:
        if not patroon:
            continue
        if _robots_patroon(patroon).match(pad):
            lengte = len(patroon)
            if lengte > beste_len or (lengte == beste_len and soort == "allow"):
                beste_len, beste = lengte, soort == "allow"
    return beste


# ---------------------------------------------------------------- netwerk

class BronFout(Exception):
    """Een bron gaf geen bruikbaar antwoord. Wordt "onbekend" in het rapport."""


class HostGestopt(BronFout):
    """De host is deze run dicht (weigering, 5xx, time-outs of robots.txt)."""


class GeenBudget(Exception):
    """Het budget aan verzoeken voor deze run is op."""


class _ZelfdeHost(urllib.request.HTTPRedirectHandler):
    """Volgt een doorverwijzing alleen naar dezelfde host via https; nooit naar een andere.

    Uitzondering: robots.txt naar robots.txt, zoals RFC 9309 vraagt (gemeten 7 nov 2026:
    data-api.ecb.europa.eu/robots.txt verwijst naar data.ecb.europa.eu/robots.txt)."""

    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        oud, nieuw = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(newurl)
        robots = oud.path == "/robots.txt" and nieuw.path == "/robots.txt"
        if nieuw.scheme != "https" or (nieuw.hostname != oud.hostname and not robots):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


MAX_BYTES = 5_000_000


def standaard_http(url: str, timeout: float = 10, headers: dict | None = None) -> tuple[int, bytes]:
    """urllib, met time-out en een bovengrens aan de grootte. Geeft (status, body)."""
    opener = urllib.request.build_opener(_ZelfdeHost())
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(MAX_BYTES + 1)
            status = r.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES + 1)
        except Exception:  # noqa: BLE001
            body = b""
        return e.code, body
    if len(body) > MAX_BYTES:
        raise BronFout("antwoord te groot")
    return status, body


def _eerlijke_ua() -> str | None:
    try:
        from funda_zoek import EERLIJKE_UA  # noqa: PLC0415
        return EERLIJKE_UA
    except Exception:  # noqa: BLE001
        return None


class Sessie:
    """Eén run: budget, pauze, robots per host en een stroomonderbreker per host."""

    def __init__(self, cache: dict, vandaag, http=None, ua: str | None = None, max_verzoeken: int = 60,
                 timeout_s: float = 10, pauze_s: float = 0.25, fout_opnieuw_na_dagen: int = 1,
                 fouten_op_rij_stop: int = 3, robots_dagen: int = ROBOTS_DAGEN,
                 robots_terugval_dagen: int = ROBOTS_TERUGVAL_DAGEN, slaap=time.sleep):
        self.cache = cache
        self.vandaag = _datum(vandaag).isoformat()
        self.http = http or standaard_http
        self.ua = ua or _eerlijke_ua()
        self.over = max_verzoeken
        self.max_verzoeken = max_verzoeken
        self.timeout_s = timeout_s
        self.pauze_s = pauze_s
        self.fout_opnieuw_na_dagen = fout_opnieuw_na_dagen
        self.fouten_op_rij_stop = fouten_op_rij_stop
        # Nooit langer dan een dag, ook niet met een oude config (bewaar_dagen.robots 30); 0 = elke run.
        self.robots_dagen = max(0, min(int(robots_dagen), ROBOTS_DAGEN))
        self.robots_terugval_dagen = int(robots_terugval_dagen)
        self.robots_run: dict[str, list] = {}       # host -> regels, deze run (één robots-verzoek per host)
        self.slaap = slaap
        self.gedaan = 0
        self.per_host: Counter = Counter()          # (host, status) -> aantal
        self.dicht: dict[str, str] = {}             # host -> reden
        # Hosts die weigerden (401/403/429) of een serverfout gaven, ook op robots.txt: die gaan met
        # neem_over() mee naar een volgende Sessie in dezelfde run. Een time-out niet.
        self.geweigerd: dict[str, str] = {}
        self.op_rij: Counter = Counter()

    def neem_over(self, vorige: "Sessie | None") -> None:
        """De stand per host van een eerdere Sessie in dezelfde run (de Geocoder op api.pdok.nl).

        robots.txt van deze run wordt niet opnieuw gevraagd, en een host die weigerde of een
        serverfout gaf, blijft dicht. Een time-out gaat niet mee: één zwaar postcodeverzoek dat te
        lang duurt, zegt niets over de lichte verzoeken van de verrijking, en die stopt zelf na
        fouten_op_rij_stop time-outs op rij. De weigering in de cache (verrijking_weigering, een
        dag) zet neem_cache_over() over."""
        if vorige is None or vorige is self:
            return
        for host, regels in vorige.robots_run.items():
            self.robots_run.setdefault(host, regels)
        for host, reden in vorige.geweigerd.items():
            self.geweigerd.setdefault(host, reden)
            self.dicht.setdefault(host, reden)

    # -- intern
    def _verzoek(self, url: str, accept: str) -> tuple[int, bytes]:
        if not self.ua:
            raise BronFout("geen user-agent beschikbaar")
        if self.over <= 0:
            raise GeenBudget()
        if self.gedaan and self.pauze_s:
            self.slaap(self.pauze_s)
        host = urllib.parse.urlparse(url).hostname or ""
        self.over -= 1
        self.gedaan += 1
        try:
            status, body = self.http(url, timeout=self.timeout_s,
                                     headers={"User-Agent": self.ua, "Accept": accept})
        except BronFout:
            self.per_host[(host, "fout")] += 1
            raise
        except Exception as exc:  # noqa: BLE001  time-out, verbinding, DNS
            self.per_host[(host, "fout")] += 1
            self.op_rij[host] += 1
            if self.op_rij[host] >= self.fouten_op_rij_stop:
                self.dicht[host] = f"{self.op_rij[host]} keer geen antwoord op rij"
            raise BronFout(f"geen antwoord ({type(exc).__name__})") from None
        self.per_host[(host, status)] += 1
        return status, body or b""

    def _robots_regels(self, host: str) -> list:
        """De regels voor host: uit deze run, vers uit de cache (zelfde dag) of opnieuw opgehaald.

        Onbereikbaar (time-out of 5xx) met een goede versie van hooguit robots_terugval_dagen oud:
        die versie, en de cache blijft zoals hij was (de volgende run probeert het opnieuw). Een
        weigering (401/403/429) is geen onbereikbaarheid: de host stopt, zonder terugval."""
        if host in self.robots_run:
            return self.robots_run[host]
        e = (self.cache.get("robots") or {}).get(host)
        dagen, oud = None, None
        if isinstance(e, dict) and e.get("fetched"):
            try:
                dagen = _dagen(e["fetched"], self.vandaag)
            except ValueError:
                dagen = None
        if dagen is not None and e.get("fout"):
            if dagen < self.fout_opnieuw_na_dagen:
                raise HostGestopt("robots.txt was niet te lezen")
        elif dagen is not None and isinstance(e.get("data"), dict):
            regels = e["data"].get("regels") or []
            if 0 <= dagen < self.robots_dagen:
                self.robots_run[host] = regels
                return regels
            if 0 <= dagen <= self.robots_terugval_dagen:
                oud = regels
        try:
            status, body = self._verzoek(f"https://{host}/robots.txt", "text/plain")
        except HostGestopt:
            raise
        except BronFout:
            if oud is None:
                raise
            self.robots_run[host] = oud              # onbereikbaar: de laatste goede versie
            return oud
        if status == 200:
            regels = robots_regels(body.decode("utf-8", "replace"))
        elif 400 <= status < 500 and status not in (401, 403, 429):
            regels = []                       # geen robots.txt: alles toegestaan
        elif status >= 500 and oud is not None:
            self.robots_run[host] = oud              # onbereikbaar: de laatste goede versie
            return oud
        else:
            cache_schrijf(self.cache, "robots", host, self.vandaag, fout=f"status {status}")
            self.dicht[host] = self.geweigerd[host] = f"robots.txt gaf status {status}"
            raise HostGestopt(self.dicht[host])
        cache_schrijf(self.cache, "robots", host, self.vandaag, data={"regels": regels})
        self.robots_run[host] = regels
        return regels

    def _robots_ok(self, host: str, pad: str) -> None:
        if not robots_mag(self._robots_regels(host), pad):
            self.dicht[host] = "robots.txt staat dit pad niet toe"
            raise HostGestopt(self.dicht[host])

    # -- publiek
    def haal(self, url: str, accept: str = "application/json") -> bytes:
        deel = urllib.parse.urlparse(url)
        host = deel.hostname or ""
        if deel.scheme != "https" or not host:
            raise BronFout("alleen https")
        if host in self.dicht:
            raise HostGestopt(self.dicht[host])
        w = (self.cache.get("verrijking_weigering") or {}).get(host)
        if isinstance(w, dict) and w.get("datum"):
            try:
                if _dagen(w["datum"], self.vandaag) < self.fout_opnieuw_na_dagen:
                    self.dicht[host] = f"weigerde eerder (status {w.get('status')})"
                    raise HostGestopt(self.dicht[host])
            except ValueError:
                pass
        pad = deel.path + (f"?{deel.query}" if deel.query else "")
        self._robots_ok(host, pad)
        status, body = self._verzoek(url, accept)
        if status in (401, 403, 429):
            self.dicht[host] = self.geweigerd[host] = f"geweigerd (status {status})"
            self.cache.setdefault("verrijking_weigering", {})[host] = {"datum": self.vandaag, "status": status}
            raise HostGestopt(self.dicht[host])
        if status >= 500:
            self.dicht[host] = self.geweigerd[host] = f"serverfout (status {status})"
            raise HostGestopt(self.dicht[host])
        if status != 200:
            raise BronFout(f"status {status}")
        self.op_rij[host] = 0
        return body

    def haal_json(self, url: str):
        body = self.haal(url, "application/json")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BronFout("geen geldige JSON") from None


# ---------------------------------------------------------------- woningvelden

def _bronnen_van(w: dict) -> list[dict]:
    uit = [w]
    for k in ("d", "listing", "details"):
        if isinstance(w.get(k), dict):
            uit.append(w[k])
    return uit


def _veld(w: dict, *namen):
    for bron in _bronnen_van(w):
        for n in namen:
            v = bron.get(n)
            if v not in (None, ""):
                return v
    return None


def woning_sleutel(w: dict) -> str:
    """Zelfde sleutel als funda_rapport (global_id, anders listing_id of url)."""
    return str(_veld(w, "global_id", "listing_id", "detail_url", "url"))


def _coords(w: dict) -> tuple[float, float] | None:
    lat, lon = _veld(w, "latitude", "lat"), _veld(w, "longitude", "lon")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (50.0 < lat < 54.0 and 3.0 < lon < 8.0):
        return None
    return lat, lon


def _postcode(w: dict) -> str | None:
    pc = re.sub(r"\s+", "", str(_veld(w, "postcode", "zip_code") or "")).upper()
    return pc if re.fullmatch(r"\d{4}[A-Z]{2}", pc) else None


def _huisnummer(w: dict) -> str | None:
    m = re.match(r"\s*(\d+)", str(_veld(w, "house_number", "huisnummer") or ""))
    return m.group(1) if m else None


def _norm_toevoeging(s) -> str:
    return re.sub(r"[^0-9a-z]", "", str(s or "").lower())


def _bouwjaar_funda(w: dict) -> int | None:
    try:
        bj = int(str(_veld(w, "construction_year", "bouwjaar") or "")[:4])
    except ValueError:
        return None
    return bj if 1200 <= bj <= date.today().year + 5 else None


def _poort(w: dict) -> str | None:
    for b in (w.get("beoordeling"), w.get("_beoordeling"), (w.get("d") or {}).get("_beoordeling")):
        if isinstance(b, dict):
            p = b.get("poort")
            if isinstance(p, str):
                return p.upper()
    return None


def _score(w: dict) -> float:
    for b in (w.get("beoordeling"), w.get("_beoordeling"), (w.get("d") or {}).get("_beoordeling")):
        if isinstance(b, dict) and isinstance(b.get("score"), (int, float)):
            return float(b["score"])
    return 0.0


def prioriteit(w: dict) -> tuple[int, float]:
    """Past en Krap eerst, daarna op score (hoog eerst). Zonder beoordeling ertussenin."""
    return POORT_RANG.get(_poort(w) or "", POORT_ONBEKEND_RANG), -_score(w)


# ---------------------------------------------------------------- parsers (op de gemeten antwoorden)

def bag_kies(antwoord: dict, postcode: str, huisnummer: str, toevoeging: str) -> tuple[dict | None, list[str]]:
    """Uit een verblijfsobject-antwoord: (verblijfsobject of None, pand-links).

    Een exacte toevoeging gaat voor. Zonder exacte treffer telt het pand alleen als alle
    verblijfsobjecten met dit nummer in hetzelfde pand liggen."""
    treffers = []
    for f in antwoord.get("features") or []:
        p = f.get("properties") or {}
        if (p.get("postcode") or "").replace(" ", "").upper() != postcode:
            continue
        if str(p.get("huisnummer")) != str(huisnummer):
            continue
        treffers.append(p)
    if not treffers:
        return None, []
    gewenst = _norm_toevoeging(toevoeging)
    exact = [p for p in treffers
             if _norm_toevoeging((p.get("huisletter") or "") + (p.get("toevoeging") or "")) == gewenst]
    if len(exact) == 1:
        return exact[0], [h for h in exact[0].get("pand.href") or [] if isinstance(h, str)]
    panden = sorted({h for p in treffers for h in (p.get("pand.href") or []) if isinstance(h, str)})
    if len(panden) == 1:
        return None, panden            # pand zeker, het precieze verblijfsobject niet
    return None, []


def bag_pand_velden(pand: dict, vbo: dict | None) -> dict:
    p = pand.get("properties") or {}
    try:
        bj = int(p.get("bouwjaar"))
        bj = bj if 1200 <= bj <= date.today().year + 5 else None   # 1005 en 9999 zijn plaatshouders
    except (TypeError, ValueError):
        bj = None
    try:
        n = int(p.get("aantal_verblijfsobjecten"))
    except (TypeError, ValueError):
        n = None
    return {"bouwjaar": bj, "aantal_vbo_pand": n,
            "gebruiksdoel": (vbo or {}).get("gebruiksdoel") if vbo else None,
            "gebruiksdoel_pand": p.get("gebruiksdoel")}


def kea_klasse(soort: str, waarde) -> str | None:
    try:
        v = float(waarde)
    except (TypeError, ValueError):
        return None
    if v < 0 or math.isnan(v):
        return None
    for grens, naam in KEA_KLASSEN[soort]:
        if v <= grens:
            return naam
    return None


def kea_parse(antwoord: dict) -> dict:
    uit = {"verschilzetting": None, "paalrot": None}
    laag_naar_soort = {v: k for k, v in KEA_LAGEN.items()}
    for f in antwoord.get("features") or []:
        laag = str(f.get("id") or "").split(".", 1)[0]
        soort = laag_naar_soort.get(laag)
        if not soort:
            continue
        props = f.get("properties") or {}
        waarde = next((v for k, v in props.items() if k.startswith("sterke_c")), None)
        uit[soort] = kea_klasse(soort, waarde)
    if uit["verschilzetting"] is None and uit["paalrot"] is None:
        raise BronFout("geen kaartwaarde op dit punt")
    return uit


def _raster(v) -> int | None:
    """GRAY_INDEX: -9999 (of negatief) = onder de kaartgrens, geen fout."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x < 0 or math.isnan(x):
        return None
    return int(round(x))


def rivm_parse(antwoord: dict) -> dict:
    fs = antwoord.get("features") or []
    if len(fs) != len(RIVM_LAGEN):
        raise BronFout(f"{len(fs)} van {len(RIVM_LAGEN)} geluidlagen in het antwoord")
    return {veld: _raster((f.get("properties") or {}).get("GRAY_INDEX")) for (veld, _), f in zip(RIVM_LAGEN, fs)}


def pdok_buurt_parse(antwoord: dict) -> dict:
    fs = antwoord.get("features") or []
    if not fs:
        raise BronFout("geen CBS-buurt op dit punt")
    p = fs[0].get("properties") or {}
    uit = {k: p.get(k) for k in VELDEN["buurtcode"]}          # allowlist: niets anders lezen
    if not uit["buurtcode"]:
        raise BronFout("buurt zonder buurtcode")
    return uit


def lbm_parse(antwoord: dict) -> dict[str, dict]:
    uit = {}
    for f in antwoord.get("features") or []:
        p = f.get("properties") or {}
        code = p.get("id")
        if not code:
            continue
        uit[str(code).strip()] = {k: p.get(k) for k in VELDEN["leefbaarometer"]}
    return uit


def cbs_tevreden_parse(antwoord: dict) -> dict:
    uit = {k: None for k in VELDEN["tevredenheid"]}
    for r in antwoord.get("value") or []:
        marge = CBS_MARGES.get(str(r.get("Marges") or "").strip())
        v = r.get("TevredenMetDeWoonomgeving_57")
        if marge == "waarde":
            uit["tevreden_woonomgeving"] = v
            uit["tevreden_woning"] = r.get("TevredenMetDeWoning_56")
        elif marge == "min":
            uit["tevreden_woonomgeving_min"] = v
        elif marge == "max":
            uit["tevreden_woonomgeving_max"] = v
    if uit["tevreden_woonomgeving"] is None and uit["tevreden_woning"] is None:
        raise BronFout("geen tevredenheidscijfer voor deze buurt")
    return uit


# ---------------------------------------------------------------- URL's

def _getfeatureinfo_url(wms: str, lagen: list[str], lat: float, lon: float) -> str:
    """WMS 1.3.0 met CRS:84 (lon,lat), bbox van ~100 x 100 m, pixel in het midden."""
    dlat, dlon = 0.00045, 0.00073
    q = ",".join(lagen)
    par = {"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo", "layers": q,
           "query_layers": q, "styles": "", "crs": "CRS:84",
           "bbox": f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}",
           "width": 101, "height": 101, "i": 50, "j": 50, "info_format": "application/json",
           "feature_count": 10}
    return wms + "?" + urllib.parse.urlencode(par, safe=",:")


def _bag_bbox_url(lat: float, lon: float, dlat: float, dlon: float, limit: int) -> str:
    bbox = f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"
    return f"{BAG_BASIS}/verblijfsobject/items?bbox={bbox}&limit={limit}&f=json"


def _pdok_buurt_url(lat: float, lon: float) -> str:
    d = 0.00001                                            # PDOK weigert een bbox zonder oppervlak
    return f"{PDOK_BUURTEN}?bbox={lon - d:.6f},{lat - d:.6f},{lon + d:.6f},{lat + d:.6f}&f=json"


def _lbm_url(gemeente: str) -> str:
    par = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": LBM_LAAG,
           "outputFormat": "application/json", "propertyName": "id," + ",".join(VELDEN["leefbaarometer"]),
           "cql_filter": "gemeente='" + gemeente.replace("'", "''") + "'"}
    return LBM_WFS + "?" + urllib.parse.urlencode(par)


def _cbs_url(buurtcode: str) -> str:
    filt = (f"WijkenEnBuurten eq '{buurtcode}' and Perioden eq '{CBS_PERIODE}' "
            f"and Leeftijd eq '{CBS_LEEFTIJD_18PLUS}'")
    sel = "Marges,WijkenEnBuurten,TevredenMetDeWoning_56,TevredenMetDeWoonomgeving_57"
    return CBS_50150 + "?" + urllib.parse.urlencode({"$filter": filt, "$select": sel, "$format": "json"},
                                                    quote_via=urllib.parse.quote)


# ---------------------------------------------------------------- ophalen per bron

def bag_ophalen(sessie: Sessie, w: dict) -> dict:
    pc, nr = _postcode(w), _huisnummer(w)
    ext = _veld(w, "house_number_ext", "toevoeging") or ""
    punt = _coords(w)
    if not pc or not nr:
        raise BronFout("geen postcode of huisnummer")
    if not punt:
        raise BronFout("geen coördinaten")
    if sessie.over < 2:                                    # adres en pand: niet half beginnen
        raise GeenBudget()
    lat, lon = punt
    vbo, panden = bag_kies(sessie.haal_json(_bag_bbox_url(lat, lon, 0.00014, 0.00022, 200)), pc, nr, ext)
    if not panden:                                         # punt iets verder van het adres: één ruimere poging
        vbo, panden = bag_kies(sessie.haal_json(_bag_bbox_url(lat, lon, 0.0007, 0.0011, 1000)), pc, nr, ext)
    if not panden:
        raise BronFout("adres niet gevonden in de BAG rond het punt")
    href = panden[0]
    if not href.startswith(BAG_PAND_PREFIX):
        raise BronFout("onverwachte pand-link")
    pand = sessie.haal_json(href + ("&" if "?" in href else "?") + "f=json")
    return bag_pand_velden(pand, vbo)


def fundering_ophalen(sessie: Sessie, lat: float, lon: float) -> dict:
    return kea_parse(sessie.haal_json(_getfeatureinfo_url(KEA_WMS, list(KEA_LAGEN.values()), lat, lon)))


def geluid_ophalen(sessie: Sessie, lat: float, lon: float) -> dict:
    return rivm_parse(sessie.haal_json(_getfeatureinfo_url(RIVM_WMS, [n for _, n in RIVM_LAGEN], lat, lon)))


def _met_cache(sessie: Sessie, cache: dict, sectie: str, sleutel: str, vcfg: dict, ophalen) -> dict:
    """Eén bron met cache. -> {"status", "data", "reden", "uit_cache"}."""
    data, st = cache_lees(cache, sectie, sleutel, vcfg, sessie.vandaag)
    if st == "vers":
        return {"status": "ok", "data": data, "reden": None, "uit_cache": True}
    if st == "fout_vers":
        fout = (cache.get(sectie) or {}).get(sleutel, {}).get("fout")
        return {"status": "onbekend", "data": None, "uit_cache": True,
                "reden": f"vorige poging mislukt ({fout}); na een dag opnieuw"}
    try:
        data = ophalen()
    except GeenBudget:
        return {"status": "budget", "data": None, "reden": "budget voor deze run op", "uit_cache": False}
    except HostGestopt as exc:
        return {"status": "onbekend", "data": None, "reden": f"bron gestopt: {exc}", "uit_cache": False}
    except BronFout as exc:
        cache_schrijf(cache, sectie, sleutel, sessie.vandaag, fout=str(exc))
        return {"status": "onbekend", "data": None, "reden": str(exc), "uit_cache": False}
    except Exception as exc:  # noqa: BLE001  onverwacht antwoord: nooit de run laten vallen
        cache_schrijf(cache, sectie, sleutel, sessie.vandaag, fout=f"onverwacht antwoord ({type(exc).__name__})")
        return {"status": "onbekend", "data": None, "reden": "onverwacht antwoord", "uit_cache": False}
    cache_schrijf(cache, sectie, sleutel, sessie.vandaag, data=data)
    return {"status": "ok", "data": data, "reden": None, "uit_cache": False}


def _leefbaarometer(sessie: Sessie, cache: dict, vcfg: dict, buurtcode: str, gemeente: str | None) -> dict:
    """Eén WFS-verzoek per gemeente (30 dagen), daarna per buurtcode uit de cache."""
    data, st = cache_lees(cache, "leefbaarometer", buurtcode, vcfg, sessie.vandaag)
    if st == "vers":
        return {"status": "ok", "data": data, "reden": None, "uit_cache": True}
    if not gemeente:
        return {"status": "onbekend", "data": None, "reden": "gemeente onbekend", "uit_cache": False}
    marker = "gemeente|" + gemeente
    _, mst = cache_lees(cache, "leefbaarometer", marker, vcfg, sessie.vandaag)
    if mst == "vers":
        return {"status": "onbekend", "data": None, "reden": "buurt niet in de Leefbaarometer", "uit_cache": True}
    if mst == "fout_vers":
        return {"status": "onbekend", "data": None, "reden": "vorige poging mislukt; na een dag opnieuw",
                "uit_cache": True}
    try:
        buurten = lbm_parse(sessie.haal_json(_lbm_url(gemeente)))
    except GeenBudget:
        return {"status": "budget", "data": None, "reden": "budget voor deze run op", "uit_cache": False}
    except HostGestopt as exc:
        return {"status": "onbekend", "data": None, "reden": f"bron gestopt: {exc}", "uit_cache": False}
    except BronFout as exc:
        cache_schrijf(cache, "leefbaarometer", marker, sessie.vandaag, fout=str(exc))
        return {"status": "onbekend", "data": None, "reden": str(exc), "uit_cache": False}
    for code, velden in buurten.items():
        cache_schrijf(cache, "leefbaarometer", code, sessie.vandaag, data=velden)
    cache_schrijf(cache, "leefbaarometer", marker, sessie.vandaag, data={"buurten": len(buurten)})
    if buurtcode in buurten:
        return {"status": "ok", "data": buurten[buurtcode], "reden": None, "uit_cache": False}
    return {"status": "onbekend", "data": None, "reden": "buurt niet in de Leefbaarometer", "uit_cache": False}


# ---------------------------------------------------------------- signalen

def _signaal(niveau: str, tekst: str) -> dict:
    return {"niveau": niveau, "tekst": tekst}


def signalen_bag(data: dict, dr: dict) -> list[dict]:
    uit = []
    n, bj = data.get("aantal_vbo_pand"), data.get("bouwjaar")
    bj_tekst = f", bouwjaar {bj}" if bj else ""
    if n is not None and n <= dr["vve_klein_max_woningen"]:
        uit.append(_signaal("let_op", f"Kleine VvE: {n} adressen in het pand (BAG{bj_tekst}). "
                                      "Vraag notulen, het onderhoudsplan en de stand van het reservefonds."))
    elif n is not None:
        uit.append(_signaal("info", f"{n} adressen in het pand (BAG{bj_tekst})."))
    doel = data.get("gebruiksdoel")
    if doel and "woonfunctie" not in doel:
        uit.append(_signaal("let_op", f"Gebruiksdoel volgens de BAG: {doel}. Vraag na of je er mag wonen."))
    return uit


def signalen_fundering(status: str, data: dict | None, bouwjaar: int | None, n_vbo: int | None,
                       dr: dict) -> list[dict]:
    if status == "niet_nodig":
        return [_signaal("info", f"Pand van {bouwjaar}: na {dr['fundering_bouwjaar_voor']}, "
                                 "funderingskaart niet nodig.")]
    if status != "ok" or not data:
        return []
    soorten = [(k, data.get(k)) for k in ("verschilzetting", "paalrot") if data.get(k) in FUND_KLASSE]
    if not soorten:
        return []
    soort, klasse = max(soorten, key=lambda kv: FUND_KLASSE.index(kv[1]))
    rang = FUND_KLASSE.index(klasse)
    bron = "Klimaateffectatlas, buurtniveau"
    if rang < FUND_KLASSE.index(dr["fundering_klasse_let_op"]):
        return [_signaal("goed", f"Funderingsrisico buurt: {klasse} ({bron}).")]
    if not bouwjaar:
        return [_signaal("info", f"Funderingsrisico buurt: {soort} 2050 {klasse} ({bron}). "
                                 "Bouwjaar onbekend, dus geen oordeel.")]
    if bouwjaar >= dr["fundering_bouwjaar_voor"]:
        return [_signaal("info", f"Funderingsrisico buurt: {soort} 2050 {klasse}, maar het pand is van "
                                 f"{bouwjaar}.")]
    vve = f", {n_vbo} adressen in de VvE" if n_vbo is not None else ""
    return [_signaal("sterk" if rang >= 3 else "let_op",
                     f"Funderingsrisico buurt: {soort} 2050 {klasse} ({bron}). Pand {bouwjaar} (BAG){vve}: "
                     "vraag naar funderingsonderzoek en of de VvE ervoor reserveert. Geen oordeel over dit pand.")]


def geluid_stap(data: dict, dr: dict) -> int:
    stap = 0
    for veld in ("lden_weg", "lnight_weg", "lden_trein", "lnight_trein"):
        v = data.get(veld)
        if v is not None:
            stap = max(stap, sum(v >= g for g in dr[f"geluid_{veld}"]))
    return stap


def signalen_geluid(data: dict, dr: dict) -> list[dict]:
    def deel(naam, lden, lnight):
        if lden is None:
            return f"{naam} onder de kaartgrens"
        nacht = f", {lnight} dB 's nachts" if lnight is not None else ""
        return f"{naam} {lden} dB Lden{nacht}"
    stap = geluid_stap(data, dr)
    tekst = ("Geluid aan de gevel: " + deel("wegverkeer", data.get("lden_weg"), data.get("lnight_weg")) + "; "
             + deel("trein", data.get("lden_trein"), data.get("lnight_trein")) + " (RIVM 2022 en 2023).")
    ldens = [x for x in (data.get("lden_weg"), data.get("lden_trein")) if x is not None]
    if stap == 0:
        niveau = "goed" if (not ldens or max(ldens) < dr["geluid_rustig_lden"]) else "info"
    else:
        niveau = "let_op" if stap == 1 else "sterk"
    return [_signaal(niveau, tekst)]


def signalen_buurt(data: dict, dr: dict) -> tuple[list[dict], bool]:
    uit, twijfel = [], False
    naam = data.get("buurtnaam") or "deze buurt"
    k = data.get("kscore")
    if isinstance(k, int) and k in LBM_KLASSE:
        klasse = LBM_KLASSE[k]
        if k <= dr["leefbaarometer_twijfel_max"]:
            twijfel = True
            uit.append(_signaal("sterk", f"Leefbaarometer {klasse} ({LBM_JAAR}) in {naam}. "
                                         "Staat de buurt niet op jouw lijst? Bekijk hem zelf."))
        elif k >= dr["leefbaarometer_goed_min"]:
            uit.append(_signaal("goed", f"Leefbaarometer {klasse} ({LBM_JAAR}) in {naam}."))
        else:
            uit.append(_signaal("info", f"Leefbaarometer {klasse} ({LBM_JAAR}) in {naam}."))
    onv = data.get("onv")
    if isinstance(onv, (int, float)) and onv <= dr["leefbaarometer_onv_let_op"]:
        uit.append(_signaal("let_op", f"Overlast en onveiligheid {_teken(onv)} ten opzichte van Nederland "
                                      f"(Leefbaarometer {LBM_JAAR})."))
    tv = data.get("tevreden_woonomgeving")
    if isinstance(tv, (int, float)):
        lo, hi = data.get("tevreden_woonomgeving_min"), data.get("tevreden_woonomgeving_max")
        marge = f", marge {_nl(lo, 0)} tot {_nl(hi, 0)}%" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
        tekst = f"Tevreden met de woonomgeving: {_nl(tv, 0)}% (RIVM 2024, modelschatting{marge})."
        if tv < dr["tevreden_woonomgeving_let_op"]:
            uit.append(_signaal("let_op", tekst))
        elif tv >= dr["tevreden_woonomgeving_goed"]:
            uit.append(_signaal("goed", tekst))
        else:
            uit.append(_signaal("info", tekst))
    return uit, twijfel


# ---------------------------------------------------------------- één woning

def _uit(reden: str = "staat uit in de config") -> dict:
    return {"status": "uit", "data": None, "reden": reden, "uit_cache": False, "signalen": []}


def _verrijk_een(w: dict, sessie: Sessie, cache: dict, vcfg: dict, dr: dict) -> dict:
    aan = vcfg.get("bronnen") or {}
    punt = _coords(w)
    res: dict[str, dict] = {}

    # 1. BAG
    if not aan.get("bag", True):
        res["bag"] = _uit()
    else:
        pc, nr = _postcode(w), _huisnummer(w)
        ext = _norm_toevoeging(_veld(w, "house_number_ext", "toevoeging"))
        if not pc or not nr or not punt:               # niets te vragen: geen verzoek en geen cache
            res["bag"] = {"status": "onbekend", "data": None, "uit_cache": False,
                          "reden": "geen coördinaten" if pc and nr else "geen postcode of huisnummer"}
        else:
            res["bag"] = _met_cache(sessie, cache, "bag", _hash_sleutel("adres", pc, nr, ext), vcfg,
                                    lambda: bag_ophalen(sessie, w))
        res["bag"]["signalen"] = signalen_bag(res["bag"]["data"], dr) if res["bag"]["status"] == "ok" else []

    bag_data = res["bag"].get("data") or {}
    bouwjaar = bag_data.get("bouwjaar") or _bouwjaar_funda(w)
    n_vbo = bag_data.get("aantal_vbo_pand")

    # 2. Fundering: alleen bij een pand van voor 1970 (of een onbekend bouwjaar)
    if not aan.get("fundering", True):
        res["fundering"] = _uit()
    elif bouwjaar and bouwjaar >= dr["fundering_bouwjaar_voor"]:
        res["fundering"] = {"status": "niet_nodig", "data": {"bouwjaar": bouwjaar}, "reden": None,
                            "uit_cache": False}
    elif not punt:
        res["fundering"] = {"status": "onbekend", "data": None, "reden": "geen coördinaten", "uit_cache": False}
    else:
        res["fundering"] = _met_cache(sessie, cache, "fundering", punt_sleutel(*punt), vcfg,
                                      lambda: fundering_ophalen(sessie, *punt))
    f = res["fundering"]
    f["signalen"] = signalen_fundering(f["status"], f.get("data"), bouwjaar, n_vbo, dr)

    # 3. Geluid aan de gevel
    if not aan.get("geluid", True):
        res["geluid"] = _uit()
    elif not punt:
        res["geluid"] = {"status": "onbekend", "data": None, "reden": "geen coördinaten", "uit_cache": False}
    else:
        res["geluid"] = _met_cache(sessie, cache, "geluid", punt_sleutel(*punt), vcfg,
                                   lambda: geluid_ophalen(sessie, *punt))
    g = res["geluid"]
    g["signalen"] = signalen_geluid(g["data"], dr) if g["status"] == "ok" else []

    # 4. Buurt: buurtcode, Leefbaarometer, tevredenheid
    if not aan.get("buurt", True):
        res["buurt"] = _uit()
        res["buurt"]["twijfel"] = False
        return res
    if not punt:
        res["buurt"] = {"status": "onbekend", "data": None, "reden": "geen coördinaten", "uit_cache": False,
                        "signalen": [], "twijfel": False, "delen": {}}
        return res
    bc = _met_cache(sessie, cache, "buurtcode", punt_sleutel(*punt), vcfg,
                    lambda: pdok_buurt_parse(sessie.haal_json(_pdok_buurt_url(*punt))))
    delen = {"buurtcode": bc["status"]}
    if bc["status"] != "ok":
        res["buurt"] = {"status": bc["status"], "data": None, "reden": bc["reden"], "uit_cache": bc["uit_cache"],
                        "signalen": [], "twijfel": False, "delen": delen}
        return res
    code = bc["data"]["buurtcode"]
    lbm = _leefbaarometer(sessie, cache, vcfg, code, bc["data"].get("gemeentenaam"))
    delen["leefbaarometer"] = lbm["status"]
    if aan.get("tevredenheid", True):
        tv = _met_cache(sessie, cache, "tevredenheid", code, vcfg,
                        lambda: cbs_tevreden_parse(sessie.haal_json(_cbs_url(code))))
    else:
        tv = _uit()
    delen["tevredenheid"] = tv["status"]
    data = dict(bc["data"])
    for k in VELDEN["leefbaarometer"]:
        data[k] = (lbm.get("data") or {}).get(k)
    for k in VELDEN["tevredenheid"]:
        data[k] = (tv.get("data") or {}).get(k)
    redenen = [f"{naam}: {x['reden']}" for naam, x in (("Leefbaarometer", lbm), ("tevredenheid", tv))
               if x["status"] not in ("ok", "uit") and x.get("reden")]
    if lbm["status"] == "ok" or tv["status"] == "ok":
        sig, twijfel = signalen_buurt(data, dr)
        res["buurt"] = {"status": "ok", "data": data, "reden": "; ".join(redenen) or None,
                        "uit_cache": all(x.get("uit_cache") for x in (bc, lbm, tv) if x["status"] != "uit"),
                        "signalen": sig, "twijfel": twijfel, "delen": delen}
    else:
        status = "budget" if "budget" in (lbm["status"], tv["status"]) else "onbekend"
        res["buurt"] = {"status": status, "data": None, "reden": "; ".join(redenen) or None,
                        "uit_cache": False, "signalen": [], "twijfel": False, "delen": delen}
    return res


# ---------------------------------------------------------------- geocoding van postcodes

_POSTCODE = re.compile(r"^\s*(\d{4})\s*([A-Za-z]{2})\s*$")
BAG_UITGEGEVEN = "Naamgeving uitgegeven"


def postcode_norm(postcode) -> str | None:
    """'1234 ab' -> '1234AB'; geen geldige Nederlandse postcode -> None."""
    m = _POSTCODE.match(str(postcode or ""))
    return m.group(1) + m.group(2).upper() if m else None


def coord_paar(waarde) -> tuple[float, float] | None:
    """[lat, lon] uit de config of een cachebestand als (lat, lon), anders None."""
    if isinstance(waarde, (list, tuple)) and len(waarde) == 2:
        try:
            return float(waarde[0]), float(waarde[1])
        except (TypeError, ValueError):
            return None
    return None


def postcode_url(postcode: str) -> str:
    return f"{BAG_ADRES}?postcode={postcode}&limit={GEOCODE_LIMIET}&f=json"


def postcode_punt_parse(antwoord: dict, postcode: str) -> tuple[float, float] | None:
    """(lat, lon) van een postcode uit een adres-antwoord: het gemiddelde van de adrespunten.

    Alleen features met precies deze postcode en een punt in Nederland. Adressen met status
    "Naamgeving uitgegeven" gaan voor; een ingetrokken adres telt alleen als er geen ander is."""
    uitgegeven, alle = [], []
    for f in (antwoord or {}).get("features") or []:
        p = f.get("properties") or {}
        if postcode_norm(p.get("postcode")) != postcode:
            continue
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if g.get("type") != "Point" or not isinstance(c, list) or len(c) < 2:
            continue
        try:
            lon, lat = float(c[0]), float(c[1])           # GeoJSON: lon, lat (CRS84)
        except (TypeError, ValueError):
            continue
        if not (NL_KADER[0] <= lat <= NL_KADER[1] and NL_KADER[2] <= lon <= NL_KADER[3]):
            continue
        alle.append((lat, lon))
        if p.get("status") == BAG_UITGEGEVEN:
            uitgegeven.append((lat, lon))
    punten = uitgegeven or alle
    if not punten:
        return None
    return (round(sum(la for la, _ in punten) / len(punten), 6),
            round(sum(lo for _, lo in punten) / len(punten), 6))


class Geocoder:
    """Postcode naar punt via de BAG op api.pdok.nl (CLAUDE.md, "Geocoding en routes"). Eén per run.

    Eén Sessie: robots.txt van api.pdok.nl eerst (één keer per run), de eerlijke user-agent, een
    ruime time-out, en na een time-out, weigering of 5xx is de host deze run dicht
    (fouten_op_rij_stop=1). Eén poging per postcode per run. De aanroeper bewaart een gevonden punt
    voorgoed (funda_werk_coords.json, funda_thuis_coords.json), dus er gaat alleen een verzoek uit
    bij een lege cache of een nieuwe postcode. punt() gooit nooit en de reden noemt nooit de postcode.

    cache: het geladen funda_enrichment_cache.json (funda_rapport geeft het mee). Dan geldt een
    weigering die de verrijking eerder gaf (verrijking_weigering, een dag) ook hier, en komen een
    weigering en robots.txt van hier in die cache; neem_cache_over() en Sessie.neem_over() geven
    ze door aan de verrijking in dezelfde run. Zonder cache een lege, alleen voor deze Geocoder."""

    def __init__(self, http=None, ua: str | None = None, timeout_s: float = GEOCODE_TIMEOUT_S,
                 max_verzoeken: int = GEOCODE_MAX_VERZOEKEN, vandaag=None, slaap=time.sleep,
                 cache: dict | None = None):
        self.sessie = Sessie(cache if isinstance(cache, dict) else {}, vandaag or date.today(), http=http, ua=ua,
                             max_verzoeken=max_verzoeken, timeout_s=timeout_s, fouten_op_rij_stop=1, slaap=slaap)
        self.gedaan: dict[str, tuple] = {}

    def punt(self, postcode) -> tuple[tuple[float, float] | None, str | None]:
        """-> ((lat, lon), None) of (None, reden)."""
        pc = postcode_norm(postcode)
        if not pc:
            return None, "geen geldige postcode"
        if pc not in self.gedaan:
            self.gedaan[pc] = self._zoek(pc)
        return self.gedaan[pc]

    def _zoek(self, pc: str) -> tuple[tuple[float, float] | None, str | None]:
        try:
            punt = postcode_punt_parse(self.sessie.haal_json(postcode_url(pc)), pc)
        except GeenBudget:
            return None, "budget voor deze run op"
        except BronFout as exc:                           # ook HostGestopt
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001  onverwacht antwoord: nooit de run laten vallen
            return None, f"onverwacht antwoord ({type(exc).__name__})"
        return (punt, None) if punt else (None, "postcode niet gevonden in de BAG")


def neem_cache_over(cache: dict, vorige: Sessie | None) -> None:
    """Zet robots.txt en weigeringen uit de cache van een eerdere Sessie (de Geocoder) in deze cache.

    Per host de nieuwste (een datum JJJJ-MM-DD); bij gelijke datum die van de eerdere Sessie, want die
    is van deze run. Zo komt een weigering van de geocoding in funda_enrichment_cache.json en geldt
    hij een dag, ook als de Geocoder de cache eerder in de run los had geladen."""
    andere = getattr(vorige, "cache", None)
    if not isinstance(cache, dict) or not isinstance(andere, dict) or andere is cache:
        return
    for sectie, datumveld in (("robots", "fetched"), ("verrijking_weigering", "datum")):
        bron = andere.get(sectie)
        if not isinstance(bron, dict):
            continue
        if not isinstance(cache.get(sectie), dict):
            cache[sectie] = {}
        doel = cache[sectie]
        for host, e in bron.items():
            if not isinstance(e, dict) or not e.get(datumveld):
                continue
            oud = doel.get(host)
            if not isinstance(oud, dict) or str(e[datumveld]) >= str(oud.get(datumveld) or ""):
                doel[host] = copy.deepcopy(e)


# ---------------------------------------------------------------- publiek

def verrijk(woningen: list[dict], cache: dict, cfg: dict | None, vandaag, http=None, ua: str | None = None,
            log=print, slaap=time.sleep, vooraf: Sessie | None = None) -> dict[str, dict]:
    """Verrijk de woningen die door alle filters kwamen. Fail-soft: gooit nooit.

    woningen: rijen of funda-dicts. Velden worden gezocht in de rij zelf en in
        rij["d"], rij["listing"] en rij["details"]: global_id, latitude/longitude (of
        lat/lon), postcode, house_number, house_number_ext, construction_year. Een
        voorlopige beoordeling (rij["beoordeling"] of d["_beoordeling"] met "poort" en
        "score") bepaalt de volgorde: Past en Krap eerst.
    cache: het geladen funda_enrichment_cache.json; wordt in place bijgewerkt.
    cfg: beoordelingsconfig of hele persoonlijke config (sleutel verrijking, drempels).
    vandaag: date of "JJJJ-MM-DD".
    vooraf: de Sessie van de Geocoder in dezelfde run (of None). Zijn robots.txt en weigeringen
        gelden hier ook (neem_cache_over en Sessie.neem_over): geen tweede robots.txt, en een host
        die daar weigerde of een serverfout gaf, krijgt deze run geen verzoek meer.

    -> {woning_sleutel: {bron: {"status": "ok"|"onbekend"|"budget"|"uit"|"niet_nodig",
                                "data": dict|None, "reden": str|None, "uit_cache": bool,
                                "signalen": [{"niveau", "tekst"}], ...}}}
       voor bron in bag, fundering, geluid, buurt. Bij buurt ook "twijfel" (Leefbaarometer
       zwak) en "delen" (status van buurtcode, leefbaarometer, tevredenheid). De data is
       wat funda_beoordeling._bron() leest (test_funda_verrijking.py, test_vorm).
    """
    vcfg, dr = instellingen(cfg)
    dag = _datum(vandaag).isoformat()
    sleutels = [woning_sleutel(w) for w in woningen]
    try:
        neem_cache_over(cache, vooraf)                  # ook als de verrijking uit staat: de weigering blijft
    except Exception:  # noqa: BLE001
        pass
    if not vcfg.get("aan", True):
        log(f"[verrijking] staat uit; {len(woningen)} woningen, 0 verzoeken.")
        return {s: {b: _uit() for b in BRONNEN} for s in sleutels}
    try:
        opruimen(cache, vcfg, dag)
    except Exception:  # noqa: BLE001
        pass
    sessie = Sessie(cache, dag, http=http, ua=ua, max_verzoeken=int(vcfg["max_calls_per_run"]),
                    timeout_s=float(vcfg["timeout_s"]), pauze_s=float(vcfg["pauze_s"]),
                    fout_opnieuw_na_dagen=int(vcfg["fout_opnieuw_na_dagen"]),
                    fouten_op_rij_stop=int(vcfg.get("fouten_op_rij_stop", 3)),
                    robots_dagen=int(vcfg["bewaar_dagen"].get("robots", ROBOTS_DAGEN)), slaap=slaap)
    sessie.neem_over(vooraf)
    uit: dict[str, dict] = {}
    for i in sorted(range(len(woningen)), key=lambda j: prioriteit(woningen[j])):
        try:
            uit[sleutels[i]] = _verrijk_een(woningen[i], sessie, cache, vcfg, dr)
        except Exception as exc:  # noqa: BLE001  vangnet: nooit een woning minder
            uit[sleutels[i]] = {b: {"status": "onbekend", "data": None, "uit_cache": False, "signalen": [],
                                    "reden": f"interne fout ({type(exc).__name__})"} for b in BRONNEN}
    uit = {s: uit[s] for s in sleutels if s in uit}
    for regel in logregels(uit, sessie):
        log(regel)
    return uit


def logregels(uitvoer: dict, sessie: Sessie | None = None) -> list[str]:
    """Alleen aantallen: per bron per status, verzoeken per host en status."""
    tel: dict[str, Counter] = {b: Counter() for b in BRONNEN}
    for w in uitvoer.values():
        for b in BRONNEN:
            tel[b][(w.get(b) or {}).get("status", "uit")] += 1
    delen = [f"{b} " + ", ".join(f"{n} {s}" for s, n in sorted(c.items())) for b, c in tel.items()]
    regels = [f"[verrijking] {len(uitvoer)} woningen; " + "; ".join(delen)]
    if sessie is not None:
        hosts = ", ".join(f"{h} {s}x{n}" for (h, s), n in sorted(sessie.per_host.items(), key=lambda x: str(x)))
        regels.append(f"[verrijking] {sessie.gedaan} verzoeken van {sessie.max_verzoeken}"
                      + (f": {hosts}" if hosts else ""))
        for host, reden in sorted(sessie.dicht.items()):
            regels.append(f"[verrijking] {host} deze run gestopt: {reden}")
    n_zwak = sum(1 for w in uitvoer.values() if (w.get("buurt") or {}).get("twijfel"))
    if n_zwak:
        regels.append(f"[verrijking] {n_zwak} woningen in een buurt met Leefbaarometer zwak of slechter")
    return regels
