"""
Rapport-module voor funda_zoek.py: het woningrapport (markdown, HTML en de versleutelde PWA).

Per woning, in deze volgorde:
1. detail-call en de pyfunda-verrijking (prijshistorie, buurtcijfer, makelaar), gecacht;
2. de reisafstand naar werk (routes), want die telt mee in de score;
3. een voorlopige beoordeling uit funda_beoordeling (poort, score, uitleg);
4. de verrijking uit open bronnen (funda_verrijking: BAG, Klimaateffectatlas, RIVM-geluid,
   Leefbaarometer, RIVM-gezondheidsmonitor), Past en Krap eerst, binnen een budget;
5. de definitieve beoordeling met die verrijking, gesorteerd op (geen vraagprijs, poort, twijfel, -score).

De rente komt uit funda_rente (handmatig in de config, anders ASN, anders DNB, anders een
standaardwaarde). Rente en verrijking zijn fail-soft: een fout daar geeft "onbekend" of de
rente uit de config, en laat de run nooit falen. De funda-checks die een run met exit 2 stoppen,
zitten in funda_zoek.main() en veranderen hier niet.

De UI (lijst, kaart, sheets) staat in funda_ui.py en ui/; het slotscherm is ui/slot.html. De body
wordt eerst met gzip ingepakt, opgevuld en daarna versleuteld (AES-256-GCM; sleutel via PBKDF2-SHA256
600.000x en HKDF, zie beveilig_html).
Met FUNDA_REQUIRE_ENCRYPTION=1 (CI) komt er nooit een onversleuteld rapport in docs/.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import os
import re
import struct
import time
import urllib.request
import zlib
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import funda_beoordeling
import funda_rente
import funda_ui
import funda_verrijking
from funda_sitemap_zoek import log_tekst, publieke_log
from funda_verrijking import EERLIJKE_UA  # ook voor PDOK (geocoding) en OSRM (routes), zonder naam

# === Persoonlijke config: uit het gitignored bestand (in Actions: secret FUNDA_PERSONAL_JSON) ===

PERSONAL_CONFIG_FILE = Path(__file__).parent / "funda_personal.json"


def _laad_personal() -> dict:
    """Lees PII uit gitignored config. Geeft generieke defaults bij ontbreken."""
    if PERSONAL_CONFIG_FILE.exists():
        try:
            return json.loads(PERSONAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"WAARSCHUWING: kon {PERSONAL_CONFIG_FILE.name} niet lezen: {exc}")
    print(f"WAARSCHUWING: {PERSONAL_CONFIG_FILE.name} ontbreekt, gebruik dummy defaults!")
    return {
        "bruto_jaar": 50_000, "eigen_inleg": 0, "duo_maandlast": 0, "leeftijd": 30,
        "postcode_huidig": "1011AB",
        "werk_postcodes": [["1011AB", "voorbeeld"]],
        "prijs_min": 200_000, "prijs_max": 350_000, "m2_min": 52, "radius_km": 5,
    }


_PERSONAL = _laad_personal()

# Link naar de GitHub Actions "Run workflow"-pagina, zodat je vanuit het rapport
# een verse run kunt starten. Geen token nodig, dus veilig. Override eventueel
# via funda_personal.json: "actions_url": "https://github.com/<user>/<repo>/actions/workflows/funda-daily.yml"
ACTIONS_URL = _PERSONAL.get(
    "actions_url",
    "https://github.com/rpvos-dhg/Funda/actions/workflows/funda-daily.yml",
)
WEB_PUSH_PUBLIC_KEY = (
    _PERSONAL.get("web_push_public_key")
    or os.environ.get("WEB_PUSH_PUBLIC_KEY")
    or ""
).strip()


def _nu() -> datetime:
    """Nu in Nederlandse tijd (de runners van GitHub draaien in UTC)."""
    return datetime.now(funda_ui.AMS)


def _nu_nl(dt: datetime | None = None) -> str:
    """Moment als leesbare NL-datum, bv. '9 juli 2026 om 10:34'."""
    dt = dt or _nu()
    return f"{funda_ui.datum_lang(dt)} om {dt:%H:%M}"


def _werk_postcodes() -> list[tuple[str, str]]:
    """Werkadressen (postcode, label) uit de config. Op het moment van aanroepen gelezen."""
    return [tuple(item) for item in (_PERSONAL.get("werk_postcodes") or [])]


WERK_CACHE = Path(__file__).parent / "funda_werk_coords.json"
ENRICHMENT_CACHE = Path(__file__).parent / "funda_enrichment_cache.json"
PWA_PASSWORD_FILE = Path(__file__).parent / "funda_pwa_password.txt"
# Map voor funda_rapport.md, funda_rapport.html en docs/. Tests zetten hier een tijdelijke map.
UITVOER_DIR = Path(__file__).parent
PWA_DIR_NAAM = "docs"  # GitHub Pages staat alleen / of /docs toe


# === Geocoding en routing ===

# Eén Geocoder per run, gedeeld met funda_zoek.thuis_coords(): robots.txt één keer, één poging per
# postcode. Hij leest funda_enrichment_cache.json (een weigering van api.pdok.nl geldt een dag), en
# genereer_rapport() geeft zijn stand door aan de verrijking. Tests zetten hier een Geocoder met een
# nep-HTTP-functie.
GEOCODER: funda_verrijking.Geocoder | None = None


def geocodeer_postcode(postcode: str) -> tuple[tuple[float, float] | None, str | None]:
    """(lat, lon) van een postcode via de BAG op api.pdok.nl, of (None, reden). Gooit nooit.

    Geen Nominatim: de robots.txt daar verbiedt /search."""
    global GEOCODER
    try:
        if GEOCODER is None:
            GEOCODER = funda_verrijking.Geocoder(ua=EERLIJKE_UA, cache=load_enrichment_cache())
        return GEOCODER.punt(postcode)
    except Exception as exc:  # noqa: BLE001
        return None, f"interne fout ({type(exc).__name__})"


def get_werk_coords() -> dict[str, tuple[float, float]]:
    """Punt per werkpostcode uit de config: {postcode: (lat, lon)}.

    Per postcode: `werk_coords` in de config gaat voor, dan funda_werk_coords.json ({hash van de
    postcode: [lat, lon]}, funda_verrijking.postcode_sleutel), dan één poging via PDOK; een gevonden punt komt voorgoed in dat bestand.
    Lukt het niet, dan een ::warning:: met alleen aantallen en geen route naar dat adres: de
    reisafstand is dan onbekend (geen minpunt)."""
    vast = _PERSONAL.get("werk_coords")
    vast = vast if isinstance(vast, dict) else {}
    # De sleutels in het bestand zijn gehasht; een oude leesbare postcode wordt bij het laden omgezet.
    cache, nieuw = funda_verrijking.coords_cache_lees(WERK_CACHE)
    postcodes = _werk_postcodes()
    coords: dict[str, tuple[float, float]] = {}
    redenen: Counter[str] = Counter()
    for pc, _ in postcodes:
        sleutel = funda_verrijking.postcode_sleutel(pc)
        punt = funda_verrijking.coord_paar(vast.get(pc)) or funda_verrijking.coord_paar(cache.get(sleutel))
        if punt is None:
            punt, reden = geocodeer_postcode(pc)
            if punt and sleutel:
                cache[sleutel] = list(punt)
                nieuw = True
            else:
                redenen[reden or "onbekend"] += 1
        if punt:
            coords[pc] = punt
    if nieuw:
        try:
            funda_verrijking.coords_cache_schrijf(WERK_CACHE, cache)
        except Exception as exc:  # noqa: BLE001
            print(f"[rapport] Werkcoördinaten niet bewaard ({type(exc).__name__}).")
    if redenen:
        waarom = "; ".join(f"{n}x {r}" for r, n in sorted(redenen.items()))
        print(log_tekst(f"::warning::Reisafstand: {sum(redenen.values())} van {len(postcodes)} werkadressen niet "
                        f"te geocoderen via PDOK ({waarom}). De reisafstand naar dat adres is onbekend; "
                        "zet werk_coords in de config om dit over te slaan."))
    return coords


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def osrm_route_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    """Afstand over de weg in km via de publieke OSRM-router, of None."""
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": EERLIJKE_UA})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
        if data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]["distance"] / 1000
    except Exception:
        pass
    return None


def afstand_km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, str]:
    """(km, soort): OSRM ("weg"), anders hemelsbreed x 1,3 ("schatting")."""
    km = osrm_route_km(lat1, lon1, lat2, lon2)
    if km is not None:
        return km, "weg"
    return haversine_km(lat1, lon1, lat2, lon2) * 1.3, "schatting"


# === Verrijking via extra pyfunda endpoints ===

# Sleutel en link van een woning komen uit funda_ui (één bron). woning_sleutel is ook de cachesleutel van
# price_history: verander hem niet, anders haalt de volgende run alle prijshistorie opnieuw op.
woning_sleutel = funda_ui.woning_sleutel
funda_url = funda_ui.funda_url


# Van funda's buurtcijfers alleen de gemiddelde vraagprijs per m². Inwoners, gezinnen met
# kinderen en andere bevolkingskenmerken worden niet bewaard of getoond (CLAUDE.md, "Verrijking").
MARKT_VELDEN = ("avg_asking_price_per_m2",)


def _markt_allowlist(insights) -> dict | None:
    if not isinstance(insights, dict):
        return None
    if insights.get("_error"):
        return {"_error": str(insights["_error"])}
    return {k: insights[k] for k in MARKT_VELDEN if k in insights}


def _schoon_markt_cache(cache: dict) -> dict:
    """Alle buurtcijfers in de cache door de allowlist, ook die van buurten die deze run niet langskomen
    (elementen van voor de allowlist hielden inwonertal en gezinnen met kinderen). Uit de makelaars
    gaat het aanbod eruit: dat werd vroeger opgehaald en hield adressen van andere woningen."""
    def elementen(sectie: str) -> list[dict]:
        inhoud = cache.get(sectie)
        return [e for e in (inhoud.values() if isinstance(inhoud, dict) else [])
                if isinstance(e, dict) and isinstance(e.get("data"), dict)]

    for entry in elementen("market_insights"):
        entry["data"] = _markt_allowlist(entry["data"])
    for entry in elementen("broker"):
        entry["data"].pop("listings", None)
    return cache


def load_enrichment_cache() -> dict:
    if ENRICHMENT_CACHE.exists():
        try:
            data = json.loads(ENRICHMENT_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _schoon_markt_cache(data)
        except Exception:
            pass
    return {"price_history": {}, "market_insights": {}, "broker": {}}


def save_enrichment_cache(cache: dict) -> None:
    _schoon_markt_cache(cache)
    ENRICHMENT_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def fetch_with_cache(cache: dict, section: str, key: str, max_age_days: int, fetcher):
    """De waarde uit cache[section][key] als die hooguit max_age_days oud is, anders fetcher().

    Een element is {"fetched": "JJJJ-MM-DD", "data": ...}. Een fout van de fetcher komt als
    {"_error": tekst} in de cache: de volgende poging komt dan pas als het element verlopen is."""
    sectie = cache.setdefault(section, {})
    entry = sectie.get(key)
    if isinstance(entry, dict) and entry.get("fetched") and entry.get("data") is not None:
        try:
            if (datetime.now() - datetime.strptime(entry["fetched"], "%Y-%m-%d")).days <= max_age_days:
                return entry["data"]
        except Exception:
            pass
    try:
        data = fetcher()
    except Exception as exc:
        data = {"_error": str(exc)}
    sectie[key] = {"fetched": datetime.now().strftime("%Y-%m-%d"), "data": data}
    return data


def verrijk_woning(f, d: dict, listing_obj, cache: dict) -> dict:
    """Prijshistorie, buurtcijfer en makelaar uit pyfunda v2.9, gecacht. Een fout is nooit fataal.

    Geeft alleen de ruwe velden die funda_beoordeling en funda_ui lezen; het model rekent zelf
    (prijshistorie(), de markt en de makelaar in beoordeel())."""
    listing_data = getattr(listing_obj, "data", None)
    if not isinstance(listing_data, dict):
        listing_data = listing_obj if isinstance(listing_obj, dict) else {}
    city, buurt = d.get("city") or "", d.get("neighbourhood") or ""
    broker_id = d.get("broker_id") or listing_data.get("broker_id")
    url = funda_url(d)

    changes = None
    if hasattr(f, "get_price_history") and (listing_obj is not None or url):
        # Met een listing geen terugval op de URL: pyfunda haalt de woning dan nog eens op via het
        # detail-endpoint (een dubbele detail-call in dezelfde run) en stuurt daarna precies hetzelfde
        # verzoek naar de prijsbron.
        changes = fetch_with_cache(cache, "price_history", woning_sleutel(d), 7,
                                   lambda: f.get_price_history(listing_obj if listing_obj is not None else url))

    markt = None
    if hasattr(f, "get_market_insights") and city and buurt:
        sleutel = "|".join(x.strip().lower() for x in (city, buurt))
        markt = _markt_allowlist(fetch_with_cache(cache, "market_insights", sleutel, 30,
                                                  lambda: _markt_allowlist(f.get_market_insights(city, buurt))))

    # Alleen naam en reviews van de makelaar. Zijn aanbod (get_broker_listings) wordt niet
    # opgehaald: een extra verzoek naar funda voor velden die niemand leest.
    makelaar = None
    if broker_id and hasattr(f, "get_broker_info"):
        bid = str(broker_id)

        def haal_makelaar() -> dict:
            bundel = {"info": None, "reviews": None}
            for naam, methode in (("info", "get_broker_info"), ("reviews", "get_broker_reviews")):
                if not hasattr(f, methode):
                    continue
                try:
                    bundel[naam] = getattr(f, methode)(int(bid))
                    time.sleep(0.2)
                except Exception as exc:
                    bundel[naam] = {"_error": str(exc)}
            return bundel

        makelaar = fetch_with_cache(cache, "broker", bid, 30, haal_makelaar)
    if not isinstance(makelaar, dict):
        makelaar = {}

    info, reviews = ({} if not isinstance(x, dict) or x.get("_error") else x
                     for x in (makelaar.get("info"), makelaar.get("reviews")))
    gem_m2 = _getal((markt or {}).get("avg_asking_price_per_m2"))
    n_reviews = _getal(reviews.get("number_of_reviews"))
    return {
        "price_history": {"changes": changes if isinstance(changes, list) else []},
        "market": {"avg_asking_price_per_m2": int(gem_m2) if gem_m2 else None},
        "broker": {"name": info.get("name"), "review_average": _getal(reviews.get("average")),
                   "review_count": int(n_reviews) if n_reviews is not None else None},
    }


# === Beoordeling: poort, score en uitleg uit funda_beoordeling ===

# Pauze na elke detail-call van het rapport. In funda_zoek zit een cache voor (DetailCacheZoeker),
# dus meestal geen echt verzoek; de pauze blijft als vangnet. Tests zetten hem op 0.
DETAIL_PAUZE_S = 0.5


def laad_config() -> dict:
    """De beoordelingsconfig: standaardwaarden plus de sleutels beoordeling en financien uit de config.

    Staan er nog oude aliassen in (die niet meer gelezen worden), dan een waarschuwing met alleen de
    sleutelnamen, nooit de waarden: anders rekent het rapport stil met de standaard."""
    oud = funda_beoordeling.oude_sleutels(_PERSONAL)
    if oud:
        print(f"::warning::Config: {len(oud)} oude sleutel(s) worden niet meer gelezen, zet ze op de plek uit "
              f"CLAUDE.md (Config): {', '.join(oud)}")
    return funda_beoordeling.laad_config(_PERSONAL)


def _getal(x) -> float | None:
    """Een eindig getal of None. NaN en oneindig (json.loads accepteert NaN en Infinity) worden None,
    zodat int() verderop nooit gooit."""
    if isinstance(x, bool):
        return None
    try:
        g = float(x) if isinstance(x, (int, float)) else float(str(x).replace(",", "."))
    except (TypeError, ValueError, OverflowError):
        return None
    return g if math.isfinite(g) else None


def _coords(d: dict, details: dict | None) -> tuple[float | None, float | None]:
    """Coördinaten uit het detail-antwoord, anders uit het zoekresultaat (de sitemaproute heeft ze daar)."""
    for bron in (details or {}, d or {}):
        lat, lon = _getal(bron.get("latitude")), _getal(bron.get("longitude"))
        if lat is not None and lon is not None:
            return lat, lon
    return None, None


def bereken_routes(lat: float | None, lon: float | None,
                   werk_coords: dict[str, tuple[float, float]] | None) -> list[dict]:
    """Afstand naar elk werkadres: [{"label", "km", "soort": "weg"|"schatting"}]. Zonder postcode erin."""
    routes: list[dict] = []
    if lat is None or lon is None or not werk_coords:
        return routes
    for pc, label in _werk_postcodes():
        if pc in werk_coords:
            plat, plon = werk_coords[pc]
            km, soort = afstand_km(lat, lon, plat, plon)
            routes.append({"label": label, "km": km, "soort": soort})
    return routes


def beoordeel_rij(rij: dict, cfg: dict, *, rente: dict | None = None, vandaag=None,
                  verrijking: dict | None = None) -> dict:
    """(Her)beoordeel één rij. De twijfel komt uit d["_twijfel"] (funda_zoek)."""
    d = rij["d"]
    b = funda_beoordeling.beoordeel(d, rij.get("details"), rij.get("routes") or [], None, _PERSONAL, cfg,
                                    verrijking, rente=rente, vandaag=vandaag)
    rij["beoordeling"] = b
    d["_beoordeling"] = b   # dezelfde dict als in funda_zoek: de pushmelding leest hem daar
    return b


def bouw_rij(d: dict, details: dict | None, routes: list[dict] | None = None, *, cfg: dict | None = None,
             rente: dict | None = None, vandaag=None, verrijking: dict | None = None) -> dict:
    """Eén rapportrij met de beoordeling volgens het contract (docstring van funda_beoordeling.py).

    De routes moeten er al zijn: de reisafstand telt mee in de score. De beoordeling komt in
    rij["beoordeling"] en in d["_beoordeling"]."""
    det = details if isinstance(details, dict) else None
    lat, lon = _coords(d, det)
    fotos = (det or {}).get("photo_urls") or d.get("photo_urls") or []
    prijs = d.get("price")
    rij = {
        "d": d,
        "details": det,
        "routes": list(routes or []),
        "lat": lat,
        "lon": lon,
        "foto_url": fotos[0] if fotos else None,
        "is_nieuw": False,
        "track": d.get("_track") or {},
        # "Prijs op aanvraag": geen leentoets, geen woonlasten, altijd achteraan. Nooit rekenen met 0.
        "prijs_onbekend": not (isinstance(prijs, (int, float)) and not isinstance(prijs, bool) and prijs > 0),
    }
    beoordeel_rij(rij, cfg or laad_config(), rente=rente, vandaag=vandaag, verrijking=verrijking)
    return rij


def _fin(rij: dict) -> dict:
    """De financiering uit de beoordeling van een rij, of {}."""
    return (rij.get("beoordeling") or {}).get("financiering") or {}


def sorteer_rijen(rijen: list[dict]) -> list[dict]:
    """(geen vraagprijs, poort, twijfel, -score), in place: zelfde sleutel als 'Aanbevolen' in de UI."""
    return funda_beoordeling.sorteer(rijen)


# === Rente en verrijking: fail-soft ===

def haal_rente(cfg: dict, cache: dict, vandaag, http=None, ua: str | None = None) -> dict:
    """De rente voor de beoordeling en de UI: {"pct", "bron", "datum", "oud", "melding", "rentevast_jaren"}.

    Gooit nooit: lukt funda_rente niet, dan de rente uit de config (of de standaard uit het model)."""
    try:
        r = funda_rente.huidige_rente(cfg, cache, vandaag, http=http, ua=ua)   # leest cfg["financien"]["rente"]
        if not (isinstance(r, dict) and _getal(r.get("pct"))):
            raise ValueError("geen rente")
        r = dict(r)
        if r.get("bron") == "standaard":
            r.setdefault("rentevast_jaren", funda_beoordeling.STANDAARD_RENTE["rentevast_jaren"])
        else:
            r.setdefault("rentevast_jaren", funda_rente.instellingen(cfg).get("rentevast_jaren"))
        return r
    except Exception as exc:  # noqa: BLE001  de rente mag een run nooit laten falen
        print(f"[rapport] Rente niet opgehaald ({type(exc).__name__}); gerekend met de rente uit de config.")
        try:
            return funda_beoordeling.rente_uit_config(cfg, vandaag)
        except Exception:  # noqa: BLE001
            return dict(funda_beoordeling.STANDAARD_RENTE, bron="standaard", oud=True, melding=None)


def verrijk_rijen(rijen: list[dict], cache: dict, cfg: dict, vandaag, http=None,
                  ua: str | None = None, vooraf=None) -> dict[str, dict]:
    """funda_verrijking.verrijk() op de rijen (voorlopige beoordeling bepaalt de volgorde). Gooit nooit.

    vooraf: de Sessie van de Geocoder in deze run, zodat api.pdok.nl één stand heeft."""
    if not rijen:
        return {}
    try:
        return funda_verrijking.verrijk(rijen, cache, cfg, vandaag, http=http, ua=ua, vooraf=vooraf) or {}
    except Exception as exc:  # noqa: BLE001  verrijking is fail-soft: nooit exit 2, nooit een woning minder
        print(f"[rapport] Verrijking overgeslagen ({type(exc).__name__}); {len(rijen)} woningen zonder.")
        return {}


def log_aantallen(rijen: list[dict]) -> None:
    """Voor de publieke log: labelnamen van funda's kenmerken met aantallen, en van een vaste lijst kenmerken
    (funda_beoordeling.LOG_WAARDEN_KENMERKEN) de genormaliseerde waarden. Geen adressen of bedragen."""
    details = [r.get("details") or r.get("d") or {} for r in rijen]
    labels = funda_beoordeling.log_kenmerk_labels(details)
    n_met = sum(1 for det in details if isinstance(det.get("characteristics"), dict))
    print(f"[rapport] Kenmerklabels uit {n_met} van {len(rijen)} woningen ({len(labels)} soorten): "
          + ("; ".join(f"{k} {n}" for k, n in labels.items()) or "geen"))
    for naam, w in funda_beoordeling.log_kenmerk_waarden(details).items():
        print(f"[rapport] Kenmerkwaarden {naam}: "
              + "; ".join([f"{k} {n}" for k, n in w["waarden"].items()] + [f"andere waarden {w['meer']}"] * bool(w["meer"])))
    tel = Counter((r.get("beoordeling") or {}).get("poort") for r in rijen)
    twijfel = sum(1 for r in rijen if (r.get("beoordeling") or {}).get("twijfel"))
    print("[rapport] Per poort: " + ", ".join(f"{naam} {tel.get(p, 0)}"
                                             for p, naam in funda_beoordeling.POORT_NAAM.items())
          + f"; met twijfel {twijfel}.")
    # Meting voor "eerder zonder prijs aangeboden": welke statuswaarden funda's prijshistorie geeft en
    # hoeveel regels geen bedrag hebben. Alleen aantallen.
    ph = funda_beoordeling.log_prijshistorie([r.get("d") for r in rijen])
    zonder = sum(ph["zonder_bedrag"].values())
    print(f"[rapport] Prijshistorie: {ph['regels']} regels bij {ph['woningen']} van {len(rijen)} woningen; status "
          + (", ".join(f"{k} {n}" for k, n in ph["status"].items()) or "geen")
          + f"; zonder bedrag {zonder}"
          + (" (" + ", ".join(f"{k} {n}" for k, n in ph["zonder_bedrag"].items()) + ")" if zonder else "")
          + f"; eerder zonder prijs gezien {sum(1 for r in rijen if (r.get('d') or {}).get('_zonder_prijs_gezien'))}.")
    # De CSP van de PWA laat alleen foto's van FOTO_HOST door. Die host is niet gemeten; komt funda
    # met een andere, dan blijven de foto's leeg en zegt deze regel waarom (alleen een aantal).
    fotos = [u for r in rijen for u in ((r.get("details") or {}).get("photo_urls") or [])
             if isinstance(u, str) and re.match(r"(?i)[a-z][a-z0-9+.-]*:|//", u)]
    buiten = sum(1 for u in fotos if not u.startswith(f"https://{FOTO_HOST}/"))
    if buiten:
        print(f"::warning::{buiten} van {len(fotos)} foto's komen niet van {FOTO_HOST}: de CSP van de PWA "
              "houdt ze tegen (funda_rapport.FOTO_HOST en CSP bijwerken).")


def rapport_meta(cfg: dict, rente: dict, nu: datetime, rijen: list[dict] | None = None,
                 vandaag=None) -> dict:
    """Wat funda_ui naast de rijen nodig heeft. Nooit inkomen of eigen geld."""
    fin = cfg.get("financiering") or {}
    meta = {
        "tijdstip": nu,
        "actions_url": ACTIONS_URL,
        "rente": rente,
        "fiets_kmu": cfg.get("fiets_kmu"),
        "kk_onzekerheid": fin.get("kk_onzekerheid"),
        "lang_op_funda_dagen": cfg.get("lang_op_funda_dagen"),
    }
    try:
        meta["leentoets_jaar"] = funda_beoordeling.tabel().get("jaar")
    except Exception:  # noqa: BLE001
        pass
    # "Jouw budget" leidt de max. koopsom per scenario af uit de rijen (met de spreiding door label
    # en erfpacht). Zonder rijen met scenario's: het overzicht zonder woning.
    if not any(_fin(r).get("scenarios") for r in rijen or []):
        try:
            sc = funda_beoordeling.scenario_overzicht(cfg, _PERSONAL, rente, vandaag)
            if sc:
                meta["scenarios"] = [{"id": s["id"], "label": s["label"], "max_koopsom": s["max_koopsom"]} for s in sc]
        except Exception:  # noqa: BLE001
            pass
    return {k: v for k, v in meta.items() if v is not None}


# === Rapport ===

def _detail(f, d: dict) -> tuple[object, dict | None]:
    """(listing, detail-dict) van één woning. Een mislukte call geeft een logregel en geen details."""
    lid = d.get("global_id") or d.get("listing_id")
    listing, details = None, None
    try:
        listing = f.get_listing(lid)
        if isinstance(getattr(listing, "data", None), dict):
            details = listing.data
        if DETAIL_PAUZE_S:
            time.sleep(DETAIL_PAUZE_S)
    except Exception as exc:
        # Op Actions zonder woningnummer of URL: de log van de publieke repo is voor iedereen leesbaar.
        print(log_tekst(f"  Detail fout {'voor een woning' if publieke_log() else lid}: {exc}"))
    return listing, details


def _voorlopige_rij(f, d: dict, cache: dict, werk_coords: dict, cfg: dict, rente: dict, vandaag: date) -> dict:
    """Stap 1 tot 3 voor één woning: detail-call, pyfunda-verrijking, routes, voorlopige beoordeling."""
    listing, details = _detail(f, d)
    d["_enrichment"] = verrijk_woning(f, d, listing, cache)
    routes = bereken_routes(*_coords(d, details), werk_coords)
    return bouw_rij(d, details, routes, cfg=cfg, rente=rente, vandaag=vandaag)


def _schrijf_rapport(rijen: list[dict], meta: dict) -> Path:
    """Markdown en HTML in UITVOER_DIR, de PWA in docs/ daaronder. Geeft het pad van de lokale HTML."""
    UITVOER_DIR.mkdir(parents=True, exist_ok=True)
    pad_md = UITVOER_DIR / "funda_rapport.md"
    pad_md.write_text(render_markdown(rijen, meta), encoding="utf-8")
    pad_html = UITVOER_DIR / "funda_rapport.html"
    pad_html.write_text(render_html(rijen, meta), encoding="utf-8")
    pwa_dir = schrijf_pwa_assets(rijen, meta)
    print(f"[rapport] Geschreven: {pad_md.name}, {pad_html.name}, en {pwa_dir.name}/")
    return pad_html


def genereer_rapport(f, woningen: list[dict], nieuw_ids: set[str] | None = None, *, http=None,
                     ua: str | None = None, vandaag: date | None = None) -> Path:
    """Detail-call, routes, beoordeling en verrijking per woning; schrijft markdown, HTML en de PWA.

    http en ua gaan naar de rente en de verrijking (tests geven een nep-functie mee); standaard het
    gewone netwerk met EERLIJKE_UA. De woningen zijn de dicts uit funda_zoek; elke dict krijgt
    _enrichment en _beoordeling erbij."""
    nieuw_ids = nieuw_ids or set()
    nu = _nu()
    vandaag = vandaag or nu.date()
    ua = ua or EERLIJKE_UA
    werk_coords = get_werk_coords()
    cache = load_enrichment_cache()
    # De geocoding (zoek- en werkpostcode) sprak api.pdok.nl al aan: zijn weigering en robots.txt in
    # deze cache, en zijn stand naar de verrijking (CLAUDE.md, "Geocoding en routes").
    geo = GEOCODER.sessie if GEOCODER is not None else None
    funda_verrijking.neem_cache_over(cache, geo)
    cfg = laad_config()
    rente = haal_rente(cfg, cache, vandaag, http=http, ua=ua)
    print(f"\n[rapport] Detail-call voor {len(woningen)} woningen, werk-coords: {len(werk_coords)} adressen.")

    rijen = []
    for d in woningen:
        rij = _voorlopige_rij(f, d, cache, werk_coords, cfg, rente, vandaag)
        rij["is_nieuw"] = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url")) in nieuw_ids
        rijen.append(rij)

    # Verrijking na de voorlopige beoordeling (Past en Krap eerst), daarna definitief beoordelen.
    verrijking = verrijk_rijen(rijen, cache, cfg, vandaag, http=http, ua=ua, vooraf=geo)
    for rij in rijen:
        v = verrijking.get(funda_verrijking.woning_sleutel(rij))
        if v:
            beoordeel_rij(rij, cfg, rente=rente, vandaag=vandaag, verrijking=v)
    try:
        save_enrichment_cache(cache)
    except Exception as exc:  # noqa: BLE001
        print(f"[rapport] Verrijkingscache niet bewaard ({type(exc).__name__}).")

    sorteer_rijen(rijen)
    log_aantallen(rijen)
    return _schrijf_rapport(rijen, rapport_meta(cfg, rente, nu, rijen, vandaag))


# === Markdown (lokaal, gitignored) ===

def _md(tekst) -> str:
    """Tekst voor in een markdown-tabelcel of -regel."""
    return str(tekst if tekst is not None else "").replace("|", "/").replace("\n", " ").strip()


def _prijs_tekst(r: dict) -> str:
    prijs = (r.get("d") or {}).get("price")
    return "prijs op aanvraag" if r.get("prijs_onbekend") or not prijs else funda_ui.eur_tekst(prijs)


def _punten_md(items: list[dict]) -> str:
    return "; ".join(_md(f"{it.get('label')}: {it.get('waarde')}"
                         + (f" ({funda_ui.bron_tekst(it['bron'])})" if it.get("bron") else "")) for it in items)


def _md_budget(rijen: list[dict], meta: dict, nu: datetime) -> list[str]:
    """"Jouw budget en aannames": dezelfde gegevens als in de voet van de HTML (funda_ui), in het kort."""
    fins = [_fin(r) for r in rijen]
    regels = ["## Jouw budget en aannames", ""]
    f0 = next((f for f in fins if f.get("grens") is not None), None)
    if f0:
        regels.append(f"- Je grens: {funda_ui.grens_tekst(f0)}")
    r = funda_ui.rente_gegevens(meta, [], nu)
    if r["pct"] is not None:
        vast = f", {r['rentevast_jaren']} jaar vast" if r.get("rentevast_jaren") else ""
        peil = f", peildatum {funda_ui.datum_lang(r['peildatum'])}" if r["peildatum"] else ""
        regels.append(f"- Rente: {funda_ui.komma(r['pct'], 2)}%{vast} ({r['bron_tekst']}{peil}{', oud' if r['oud'] else ''})")
    melding = (meta.get("rente") or {}).get("melding")
    if melding:
        regels.append(f"- Let op de rente: {_md(melding)}")
    sc = funda_ui.scenario_koopsommen(fins, meta.get("scenarios"), meta_eerst=False)
    if sc:
        regels.append("- Hoogste koopsom per scenario:")
        regels += [f"  - {_md(label)}{' (planning)' if plan else ''}: {tekst}" for label, tekst, plan in sc]
    return regels + ["- Woonlasten zijn netto, jaar 1. Een bedrag met ≈ is een schatting.",
                     "- Score 0 tot 10. 5 betekent: voldoet aan je eisen. Onbekend en kansen tellen niet mee.", ""]


def _md_woning(i: int, rij: dict) -> list[str]:
    d, b, fin = rij["d"], rij.get("beoordeling") or {}, _fin(rij)
    det = rij.get("details") or {}
    eur = funda_ui.eur_tekst
    regels = [f"### {i}. {_md(d.get('title'))}, {_md(d.get('city'))}{' (nieuw)' if rij.get('is_nieuw') else ''}", "",
              f"- **{_md(b.get('status_kort'))} · score {funda_ui.komma(b.get('score') or 0)}**"]
    if b.get("uitleg_regel"):
        regels.append(f"- {_md(b['uitleg_regel'])}")
    if fin.get("scenario_tekst"):
        regels.append(f"- {_md(funda_ui.scenario_regel(fin['scenario_tekst']))}")   # zelfde woord als op de kaart
    regels += [f"- Twijfel: {_md(t)} Onderaan gezet." for t in b.get("twijfel") or []]
    m2 = d.get("living_area") or det.get("living_area")
    m2_getal, vraagprijs = _getal(m2), _getal(d.get("price"))   # funda geeft soms tekst ("ca. 60 m²")
    prijs = _prijs_tekst(rij)
    if not rij.get("prijs_onbekend") and m2_getal and m2_getal > 0 and vraagprijs:
        prijs += f" ({eur(vraagprijs / m2_getal)} per m²)"
    netto = fin.get("netto")
    lasten = f"{eur(netto)} netto per maand" if netto is not None else "onbekend"
    regels.append(f"- Vraagprijs: {prijs} · Woonlasten: {lasten}")
    feit = [f"{_md(m2)} m²" if m2 else None, f"{d.get('rooms')} kamers" if d.get("rooms") else None,
            f"label {d.get('energy_label') or det.get('energy_label') or 'onbekend'}",
            _md(d.get("neighbourhood")) or None]
    regels.append("- Woning: " + ", ".join(x for x in feit if x))
    tr = rij.get("track") or {}
    if tr.get("gedaald") and tr.get("eerdere_prijs"):
        regels.append(f"- Prijs gedaald: was {eur(tr['eerdere_prijs'])}")
    # Dezelfde indeling als op de kaart: de informatieve items staan in een eigen regel.
    for kop, items in (("Let op", b.get("let_op")), ("Pluspunten", b.get("pluspunten")), ("Onbekend", b.get("onbekend")),
                       ("Kansen", b.get("kansen")),
                       ("Buurt en omgeving (telt niet mee in de score)", funda_ui.info_items(b, funda_beoordeling.INFO_TONEN)),
                       ("Over de woning (telt niet mee in de score)", funda_ui.info_items(b, funda_beoordeling.INFO_WONING))):
        if items:
            regels.append(f"- {kop}: {_punten_md(items)}")
    # Zomer en winter: een indicatie, geen meting; de aanwijzingen staan in de uitleg.
    regels += [f"- {_md(it.get('label'))} (indicatie): {_md(it.get('waarde'))}. {_md(it.get('uitleg') or '')}"
               for it in funda_ui.info_items(b, (funda_beoordeling.BINNENKLIMAAT,))]
    if b.get("zelf_nagaan"):
        regels.append("- Zelf nagaan:")
        regels += [f"  {n}. {_md(v)}" for n, v in enumerate(b["zelf_nagaan"], 1)]
    url = funda_url(d)
    if url:
        regels.append(f"- Funda: {url}")
    return regels + ["", "---", ""]


def render_markdown(rijen: list[dict], meta: dict | None = None) -> str:
    """Per woning '### <adres>' met '<status_kort> · score x,x' en de uitleg_regel uit het model.

    Geen inkomen en nooit "€ 0": zonder vraagprijs staat er "prijs op aanvraag"."""
    meta = meta or {}
    nu = meta.get("tijdstip") if isinstance(meta.get("tijdstip"), datetime) else _nu()
    regels = [f"# Woningrapport, {_nu_nl(nu)}", "", *_md_budget(rijen, meta, nu)]
    if not rijen:
        return "\n".join(regels + ["Geen woningen om te beoordelen."])
    regels += ["## Overzicht", "", "| # | Woning | Vraagprijs | Status | Score |",
               "|---|--------|-----------:|--------|------:|"]
    for i, rij in enumerate(rijen, 1):
        d, b = rij["d"], rij.get("beoordeling") or {}
        regels.append(f"| {i} | {_md(d.get('title'))}, {_md(d.get('city'))} | {_prijs_tekst(rij)} "
                      f"| {_md(b.get('status_kort'))} | {funda_ui.komma(b.get('score') or 0)} |")
    regels += ["", "## Per woning", ""]
    for i, rij in enumerate(rijen, 1):
        regels += _md_woning(i, rij)
    return "\n".join(regels)


# === HTML (lokaal) ===

# Leaflet 1.9.4 (kaart), zelf gehost: ui/leaflet/ gaat mee naar docs/leaflet/ (schrijf_statisch). In de
# <head>: scripts in de via innerHTML gezette body draaien niet.
LEAFLET_VERSIE = "1.9.4"


def map_head(prefix: str = "", versies: dict | None = None) -> str:
    """Leaflet in de <head>. Met versies (de PWA) krijgt elk bestand zijn `?v=`, net als in de wrapper."""
    def url(naam: str) -> str:
        return prefix + naam + (f"?v={versies[naam]}" if versies else "")
    return (f'<link rel="stylesheet" href="{url("leaflet/leaflet.css")}">\n'
            f'<script defer src="{url("leaflet/leaflet.js")}"></script>')


def push_head() -> str:
    """De publieke Web Push-sleutel als meta-tag; ui/push.js leest hem. Leeg zonder WEB_PUSH_PUBLIC_KEY."""
    if not WEB_PUSH_PUBLIC_KEY:
        return ""
    return f'<meta name="funda-push-key" content="{funda_ui.h(WEB_PUSH_PUBLIC_KEY)}">'


def _body(rijen: list[dict], meta: dict | None, is_pwa: bool) -> str:
    m = dict(meta or {})
    m["push_beschikbaar"] = bool(is_pwa and WEB_PUSH_PUBLIC_KEY)
    return funda_ui.render_report_body(rijen, m)


# Alleen voor de onversleutelde PWA (lokaal, zonder wachtwoord); de versleutelde heeft ui/slot.html.
_PWA_HEAD = """
<link rel="manifest" href="manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Woningen">
"""
_PWA_SCRIPT = """
<script>
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js', {scope:'./'}).catch(()=>{}));
}
</script>
"""


def render_html(rijen: list[dict], meta: dict | None = None, is_pwa: bool = False) -> str:
    """Het onversleutelde rapport: lokaal funda_rapport.html, of de PWA als er geen wachtwoord is.

    CSS en JavaScript staan inline: eerst de UI (zet fundaAfterReportLoad), dan in de PWA de push-JS
    die erop aanhaakt. De versleutelde PWA laadt dezelfde bestanden uit docs/ (geen inline script, zie CSP)."""
    meta = meta or {}
    nu = meta.get("tijdstip") if isinstance(meta.get("tijdstip"), datetime) else _nu()
    prefix = "" if is_pwa else "docs/"
    pwa_head = _PWA_HEAD + push_head() + "\n" if is_pwa else ""
    scripts = f"<script>{funda_ui.UI_JS}</script>" + (f"<script>{funda_ui.PUSH_JS}</script>" if is_pwa else "")
    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="{funda_ui.THEME_COLOR_DONKER}">
<meta name="theme-color" content="{funda_ui.THEME_COLOR}">
<title>Woningrapport, {funda_ui.datum_lang(nu)}</title>
<link rel="icon" href="{prefix}favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" sizes="180x180" href="{prefix}apple-touch-icon.png">
<meta name="referrer" content="no-referrer">
{pwa_head}
{map_head(prefix, VERSIES if is_pwa else None)}
<style>{funda_ui.UI_CSS}</style>
</head>
<body>
{_body(rijen, meta, is_pwa)}
{scripts}
{_PWA_SCRIPT if is_pwa else ""}
</body>
</html>"""


# === PWA: vaste bestanden in docs/ (manifest, service worker, iconen, CSS, JavaScript, Leaflet) ===

# Geen voornaam en geen merknaam: het manifest staat publiek op GitHub Pages.
PWA_MANIFEST = json.dumps({
    "name": "Woningrapport",
    "short_name": "Woningen",
    "id": "./",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": funda_ui.ACHTERGROND,
    "theme_color": funda_ui.THEME_COLOR,
    "icons": [
        {"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
    ],
}, indent=2, ensure_ascii=False) + "\n"

# De service worker wordt afgeleid uit de bestanden (service_worker(), verderop): de lijst met versies
# uit STATISCH en de cachenaam uit de gezamenlijke hash. Niets met de hand ophogen.
# Alleen same-origin GET's komen in de cache; foto's en kaarttegels van buiten gaan er ongemoeid langs.
# Geen ignoreSearch: een bestand met `?v=` komt alleen uit de cache als de versie de huidige is en de
# inhoud bij het bewaren die hash had. Elke andere vraag naar zo'n bestand (zonder `?v=`, of met een
# oudere: een index.html van vóór de laatste update) gaat naar het netwerk en komt niet in de cache;
# zonder netwerk krijgt hij de huidige versie, hetzelfde als wat het netwerk zou geven.
_SW_SJABLOON = """// Woningrapport: service worker. Afgeleid uit de bestanden door funda_rapport.py; niet met de hand wijzigen.
const CACHE = '__CACHE__';
// Statische bestanden met hun versie: de eerste __LENGTE__ hextekens van de sha256 van de inhoud.
const VERSIES = __VERSIES__;
const LOS = __LOS__;
const BASIS = new URL('./', self.location).pathname;
const sleutel = p => p + '?v=' + VERSIES[p];
async function klopt(resp, versie) {
  const som = new Uint8Array(await crypto.subtle.digest('SHA-256', await resp.clone().arrayBuffer()));
  return Array.from(som.slice(0, versie.length / 2), b => b.toString(16).padStart(2, '0')).join('') === versie;
}
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(async c => {
    await c.addAll(LOS);
    // Een bestand waarvan de inhoud niet bij de versie past (update nog onderweg) blijft uit de cache.
    await Promise.all(Object.keys(VERSIES).map(async p => {
      const resp = await fetch(sleutel(p));
      if (resp.ok && await klopt(resp, VERSIES[p])) await c.put(sleutel(p), resp);
    }));
  }));
});
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
async function antwoord(req, url) {
  const c = await caches.open(CACHE);
  const p = url.pathname.startsWith(BASIS) ? url.pathname.slice(BASIS.length) : '';
  const vast = Object.prototype.hasOwnProperty.call(VERSIES, p);
  const huidig = vast && url.searchParams.get('v') === VERSIES[p];
  if (huidig) {
    const r = await c.match(sleutel(p));
    if (r) return r;
  }
  try {
    const resp = await fetch(req);
    if (resp.ok && resp.type === 'basic') {
      if (!vast) c.put(req, resp.clone()).catch(()=>{});
      else if (huidig && await klopt(resp, VERSIES[p])) c.put(sleutel(p), resp.clone()).catch(()=>{});
    }
    return resp;
  } catch (_) {
    const r = await c.match(vast ? sleutel(p) : req) || (req.mode === 'navigate' ? await c.match('index.html') : null);
    return r || Response.error();
  }
}
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  e.respondWith(antwoord(e.request, url));
});
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch(_) {
    data = { title: 'Nieuwe woningen', body: e.data ? e.data.text() : '' };
  }
  const title = data.title || 'Nieuwe woningen';
  const options = {
    body: data.body || 'Open het rapport voor de nieuwste woningen.',
    icon: 'icon-512.png',
    badge: 'apple-touch-icon.png',
    data: { url: data.url || './' },
    tag: data.tag || 'funda-new-listings',
    renotify: true
  };
  e.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = e.notification.data && e.notification.data.url ? e.notification.data.url : './';
  e.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      if ('focus' in client) return client.focus();
    }
    if (clients.openWindow) return clients.openWindow(target);
  })());
});
"""

# Icoon in het eigen palet (ui/app.css): het inktblauw van de topbalk, een wit huis en een lichtblauw
# raam. Geen geel, geen groen of goud. De PNG vult het hele vlak (ook geschikt als maskable).
ICOON_ACHTERGROND = funda_ui.THEME_COLOR
ICOON_HUIS = "#ffffff"
ICOON_ACCENT = "#93b4fd"   # lichtblauw, --background-color-interactive-strong in donker

# Huis op een raster van 512: dak (top, links, rechts), romp, deur en raam.
_HUIS_DAK = [(256, 116), (88, 262), (424, 262)]
_HUIS_ROMP = (146, 232, 366, 404)
_HUIS_DEUR = (226, 314, 286, 404)
_HUIS_RAAM = (304, 272, 344, 312)


def _icoon_svg(grootte: int, radius: int) -> str:
    s = grootte / 512

    def p(x):
        return f"{x * s:g}"

    dak = " ".join(f"{p(x)},{p(y)}" for x, y in _HUIS_DAK)

    def rect(r, kleur):
        x1, y1, x2, y2 = r
        return f'<rect x="{p(x1)}" y="{p(y1)}" width="{p(x2 - x1)}" height="{p(y2 - y1)}" fill="{kleur}"/>'

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grootte} {grootte}">\n'
            f'  <rect width="{grootte}" height="{grootte}" rx="{radius}" fill="{ICOON_ACHTERGROND}"/>\n'
            f'  <polygon points="{dak}" fill="{ICOON_HUIS}"/>\n'
            f'  {rect(_HUIS_ROMP, ICOON_HUIS)}\n'
            f'  {rect(_HUIS_DEUR, ICOON_ACHTERGROND)}\n'
            f'  {rect(_HUIS_RAAM, ICOON_ACCENT)}\n'
            f'</svg>\n')


PWA_ICON_SVG = _icoon_svg(512, 112)
PWA_FAVICON_SVG = _icoon_svg(64, 14)


def _rgba(hex_kleur: str) -> bytes:
    return bytes.fromhex(hex_kleur.lstrip("#")) + b"\xff"


def _write_png_icon(path: Path, size: int) -> None:
    """Schrijf het icoon als PNG zonder externe dependencies (zelfde huis als PWA_ICON_SVG).

    Getekend op 3x (of 2x) de doelmaat en daarna verkleind, voor zachte randen."""
    schaal = 3 if size <= 256 else 2
    n = size * schaal
    f = n / 512
    achtergrond, huis, accent = _rgba(ICOON_ACHTERGROND), _rgba(ICOON_HUIS), _rgba(ICOON_ACCENT)
    buf = bytearray(achtergrond * (n * n))

    def rect(r: tuple[int, int, int, int], kleur: bytes) -> None:
        x1, y1, x2, y2 = (min(n, max(0, int(round(v * f)))) for v in r)
        for y in range(y1, y2):
            buf[(y * n + x1) * 4:(y * n + x2) * 4] = kleur * (x2 - x1)

    def poly(punten: list[tuple[int, int]], kleur: bytes) -> None:
        pts = [(x * f, y * f) for x, y in punten]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        for y in range(max(0, int(min(ys))), min(n - 1, int(max(ys)) + 1) + 1):
            for x in range(max(0, int(min(xs))), min(n - 1, int(max(xs)) + 1) + 1):
                binnen = False
                for (xi, yi), (xj, yj) in zip(pts, pts[-1:] + pts[:-1]):
                    if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                        binnen = not binnen
                if binnen:
                    buf[(y * n + x) * 4:(y * n + x) * 4 + 4] = kleur

    poly(_HUIS_DAK, huis)
    rect(_HUIS_ROMP, huis)
    rect(_HUIS_DEUR, achtergrond)
    rect(_HUIS_RAAM, accent)

    # Verkleinen: elk doelpixel is het gemiddelde van schaal x schaal getekende pixels.
    rijen = bytearray()
    for y in range(size):
        rijen.append(0)   # PNG-filter 0 per rij
        for x in range(size):
            som = [0, 0, 0, 0]
            for yy in range(schaal):
                i = ((y * schaal + yy) * n + x * schaal) * 4
                for k, v in enumerate(buf[i:i + schaal * 4]):
                    som[k % 4] += v
            rijen += bytes(v // (schaal * schaal) for v in som)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(rijen), 9))
                     + chunk(b"IEND", b""))


# Statische bestanden van de PWA: pad in docs/ -> bron in ui/. De service worker bewaart ze ook.
STATISCH = {
    "app.css": "app.css", "slot.css": "slot.css", "app.js": "app.js", "slot.js": "slot.js", "push.js": "push.js",
    "leaflet/leaflet.js": "leaflet/leaflet.js", "leaflet/leaflet.css": "leaflet/leaflet.css",
    "leaflet/LICENSE": "leaflet/LICENSE",
}
ZONDER_VERSIE = ("leaflet/LICENSE",)   # geen pagina verwijst ernaar, dus niet in de service worker
VERSIE_LENGTE = 10                     # hextekens van de sha256; even, want de service worker rekent in bytes
# Wat de service worker bij het installeren zonder versie ophaalt: de pagina zelf en wat schrijf_statisch maakt.
SW_LOS = ("./", "index.html", "manifest.json", "icon.svg", "favicon.svg", "apple-touch-icon.png", "icon-512.png")


def statisch_versies(ui_dir: Path | None = None) -> dict[str, str]:
    """Per statisch bestand een korte hash van de inhoud: de `?v=` in de wrapper en in de service worker.

    De markup zit in index.html, de code in losse bestanden. Met de hash in de URL hoort bij nieuwe
    markup altijd de code van dezelfde versie, ook als de browser of GitHub Pages het oude bestand nog
    tien minuten bewaart."""
    ui_dir = ui_dir or funda_ui.UI_DIR
    return {doel: hashlib.sha256((ui_dir / bron).read_bytes()).hexdigest()[:VERSIE_LENGTE]
            for doel, bron in STATISCH.items() if doel not in ZONDER_VERSIE}


def cache_naam(versies: dict[str, str]) -> str:
    """De cachenaam uit alles wat de service worker bewaart of zelf is. Een gewijzigd bestand geeft zo
    vanzelf een nieuwe cache; de oude ruimt de service worker op bij activate."""
    h = hashlib.sha256()
    for deel in (json.dumps(versies, sort_keys=True), PWA_MANIFEST, PWA_ICON_SVG, PWA_FAVICON_SVG, _SW_SJABLOON):
        h.update(deel.encode("utf-8") + b"\0")
    return "funda-shortlist-" + h.hexdigest()[:VERSIE_LENGTE]


def service_worker(versies: dict[str, str]) -> str:
    """De service worker met de versies en de cachenaam ingevuld."""
    js = json.dumps(versies, indent=2, sort_keys=True).replace('"', "'")
    return (_SW_SJABLOON.replace("__CACHE__", cache_naam(versies)).replace("__LENGTE__", str(VERSIE_LENGTE))
            .replace("__VERSIES__", js).replace("__LOS__", json.dumps(list(SW_LOS)).replace('"', "'")))


VERSIES = statisch_versies()
PWA_SERVICE_WORKER = service_worker(VERSIES)


def schrijf_statisch(pwa_dir: Path) -> None:
    """Alles in docs/ behalve index.html: manifest, service worker, iconen, CSS, JavaScript en Leaflet.

    Hangt niet van de woningen of het wachtwoord af. Een oude index.html (zonder `?v=` in de URL's)
    blijft naast deze bestanden gewoon werken. De kopieën in de repo (docs/) horen gelijk te zijn aan
    wat hier geschreven wordt: test_funda_pwa.py vergelijkt ze, zodat een wijziging in ui/ niet zonder
    kopie en nieuwe versie blijft."""
    pwa_dir.mkdir(parents=True, exist_ok=True)
    (pwa_dir / "manifest.json").write_text(PWA_MANIFEST, encoding="utf-8")
    (pwa_dir / "service-worker.js").write_text(PWA_SERVICE_WORKER, encoding="utf-8")
    (pwa_dir / "icon.svg").write_text(PWA_ICON_SVG, encoding="utf-8")
    (pwa_dir / "favicon.svg").write_text(PWA_FAVICON_SVG, encoding="utf-8")
    _write_png_icon(pwa_dir / "apple-touch-icon.png", 180)
    _write_png_icon(pwa_dir / "icon-512.png", 512)
    for doel, bron in STATISCH.items():
        pad = pwa_dir / doel
        pad.parent.mkdir(parents=True, exist_ok=True)
        pad.write_bytes((funda_ui.UI_DIR / bron).read_bytes())



# === Versleuteling van de PWA ===
# Alles hieronder is publiek (het staat ook in docs/index.html); geheim is alleen het wachtwoord.
KDF_ITERS = 600_000   # OWASP-advies voor PBKDF2-SHA256
# Vast zout van deze app, voor de hoofdsleutel. Publiek, willekeurig, en bewust niet per run: de
# browser bewaart de hoofdsleutel en die moet de volgende run nog passen. Wijzigen = iedereen vult
# één keer het wachtwoord opnieuw in.
APP_ZOUT = bytes.fromhex("1f017e8c08649ec54f34bcfdcc10e776")
KDF_INFO = "woningrapport/v2 hkdf-sha256 aes-256-gcm"   # versiestring; ophogen bij een andere opbouw
PAKKET_VERSIE = 2
BLOK = 8192           # de ciphertext (met de tag van 16 bytes) is altijd een veelvoud hiervan
_TAG = 16

# Content-Security-Policy van de wrapper (meta-tag). Geen inline script en geen inline style: alle
# code staat als bestand in docs/. Afbeeldingen: eigen iconen, funda's foto's, OSM-tegels, en data:
# omdat Leaflet een afgebroken tegel op een lege GIF als data-URI zet. frame-ancestors werkt niet in
# een meta-tag; daarvoor weigert ui/slot.js te ontgrendelen in een frame.
FOTO_HOST = "cloud.funda.nl"
TEGEL_HOST = "tile.openstreetmap.org"   # dezelfde als in ui/app.js (test_funda_pwa)
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       f"img-src 'self' https://{FOTO_HOST} https://{TEGEL_HOST} data:; "
       "connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; form-action 'none'")


def hoofdsleutel(password: str) -> bytes:
    """PBKDF2-SHA256(wachtwoord, APP_ZOUT, KDF_ITERS): de trage stap, één keer per wachtwoord."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=APP_ZOUT,
                      iterations=KDF_ITERS).derive(password.encode("utf-8"))


def runsleutel(hoofd: bytes, zout: bytes, info: str = KDF_INFO) -> bytes:
    """HKDF-SHA256(hoofdsleutel, salt = run-zout, info = versiestring): de AES-256-sleutel van één run."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=zout, info=info.encode("utf-8")).derive(hoofd)


def vul_op(data: bytes) -> bytes:
    """Lengte (4 bytes, big-endian) + data + nullen, zo lang dat de ciphertext met tag een veelvoud van BLOK is."""
    kaal = 4 + len(data) + _TAG
    return len(data).to_bytes(4, "big") + data + bytes(-kaal % BLOK)


def versleutel(html: str, password: str, gz: bool = True) -> dict:
    """Het pakket voor #slot-data: alles wat de browser nodig heeft behalve het wachtwoord.

    ui/slot.js doet het omgekeerde; test_funda_pwa.py ook, in Python en met het echte slot.js in node."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data = html.encode("utf-8")
    if gz:
        data = gzip.compress(data, compresslevel=9, mtime=0)
    zout = os.urandom(16)
    iv = os.urandom(12)
    ciphertext = AESGCM(runsleutel(hoofdsleutel(password), zout)).encrypt(iv, vul_op(data), None)

    def b64(b: bytes) -> str:
        return base64.b64encode(b).decode()

    return {"v": PAKKET_VERSIE, "gz": 1 if gz else 0, "iters": KDF_ITERS, "app_zout": b64(APP_ZOUT),
            "info": KDF_INFO, "zout": b64(zout), "iv": b64(iv), "ct": b64(ciphertext)}


def beveilig_html(html: str, password: str, gz: bool = True) -> str:
    """Versleutel de body en wikkel hem in het slotscherm (ui/slot.html).

    Opbouw:
      hoofdsleutel = PBKDF2-SHA256(wachtwoord, APP_ZOUT, 600.000 iteraties)
      runsleutel   = HKDF-SHA256(hoofdsleutel, salt = run-zout van 16 bytes, info = KDF_INFO)
      ciphertext   = AES-256-GCM(runsleutel, IV van 12 bytes, lengte + gzip(body) + opvulling)
    Zout en IV zijn elke run nieuw.

    Waarom zo (dreigingsmodel): "Onthoud op dit apparaat" bewaart de hoofdsleutel, en wie de opslag
    van het apparaat leest mag daarmee niet sneller naar het wachtwoord kunnen raden dan iemand met
    alleen de publieke ciphertext. De oude opbouw bewaarde de PBKDF2-basissleutel; daaruit was een
    afleiding met 1 iteratie te halen, dus raden zonder de trage stap. De HKDF-hoofdsleutel is niet
    exporteerbaar en zit ná de 600.000 iteraties.

    Eerst gzip (niveau 9, mtime 0, dus reproduceerbaar), dan opvullen, dan versleutelen. Comprimeren
    moet vóór het versleutelen: ciphertext comprimeert niet, dus Pages kan hem over de lijn niet
    kleiner maken. De opvulling (vul_op) maakt de ciphertext een veelvoud van 8 kB, zodat de
    bestandsgrootte het aanbod niet meer per woning volgt. `gz=False` is de terugval (het slotscherm
    pakt dan niets uit).

    De wrapper bevat geen CSS of JavaScript meer: die staan als bestanden in docs/ (schrijf_statisch),
    en de CSP in de wrapper staat alleen die toe. Elk van die bestanden krijgt zijn versie als `?v=`
    in de URL (statisch_versies). Het pakket staat als JSON in #slot-data.
    """
    pakket = json.dumps(versleutel(html, password, gz), separators=(",", ":"))
    return funda_ui.vul_slot({
        "__CSP__": funda_ui.h(CSP),
        "__PUSH_META__": push_head(),
        "__PAKKET__": pakket,
    }, versies=VERSIES)


def _pwa_wachtwoord() -> str:
    """Het PWA-wachtwoord, of "" als er geen is."""
    if PWA_PASSWORD_FILE.exists():
        return PWA_PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return ""


def schrijf_pwa_assets(rijen: list[dict], meta: dict | None = None) -> Path:
    """Manifest, service worker, iconen, CSS, JavaScript en index.html in docs/ (onder UITVOER_DIR)."""
    password = _pwa_wachtwoord()
    # Vangrail: in CI (publieke repo) NOOIT onversleuteld publiceren. Vóór het schrijven, zodat
    # er dan ook niets anders in docs/ verandert.
    if not password and os.environ.get("FUNDA_REQUIRE_ENCRYPTION") == "1":
        raise RuntimeError(
            "FUNDA_REQUIRE_ENCRYPTION=1 maar geen wachtwoord gevonden; "
            "weiger om een onversleuteld rapport te schrijven."
        )

    pwa_dir = UITVOER_DIR / PWA_DIR_NAAM
    schrijf_statisch(pwa_dir)

    if password:
        index = beveilig_html(_body(rijen, meta, True), password)
    else:   # terugval (lokaal, zonder wachtwoord): onversleuteld
        print("[rapport] WAARSCHUWING: geen funda_pwa_password.txt gevonden, PWA wordt onversleuteld geschreven!")
        index = render_html(rijen, meta, is_pwa=True)
    (pwa_dir / "index.html").write_text(index, encoding="utf-8")
    return pwa_dir
