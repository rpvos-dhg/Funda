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
wordt eerst met gzip ingepakt en daarna versleuteld (AES-256-GCM, PBKDF2-SHA256 100.000x).
Met FUNDA_REQUIRE_ENCRYPTION=1 (CI) komt er nooit een onversleuteld rapport in docs/.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import funda_beoordeling
import funda_rente
import funda_ui
import funda_verrijking

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

# Tijd in Nederlandse tijdzone tonen (GitHub-runners draaien in UTC).
try:
    from zoneinfo import ZoneInfo
    _TZ_NL = ZoneInfo("Europe/Amsterdam")
except Exception:
    _TZ_NL = None

_NL_MAANDEN = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def _nu() -> datetime:
    return datetime.now(_TZ_NL) if _TZ_NL else datetime.now()


def _nu_nl(dt: datetime | None = None) -> str:
    """Moment als leesbare NL-datum, bv. '9 juli 2026 om 10:34'."""
    dt = dt or _nu()
    return f"{dt.day} {_NL_MAANDEN[dt.month - 1]} {dt.year} om {dt:%H:%M}"


def _werk_postcodes() -> list[tuple[str, str]]:
    """Werkadressen (postcode, label) uit de config. Op het moment van aanroepen gelezen."""
    return [tuple(item) for item in (_PERSONAL.get("werk_postcodes") or [])]


WERK_CACHE = Path(__file__).parent / "funda_werk_coords.json"
ENRICHMENT_CACHE = Path(__file__).parent / "funda_enrichment_cache.json"
# Nominatim en OSRM: dezelfde eerlijke user-agent als de rest (EERLIJKE_UA uit funda_zoek, met repo-link),
# zonder naam. Op het moment van aanroepen gelezen, zodat er geen kringimport ontstaat.
USER_AGENT_TERUGVAL = "funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)"


# === Geocoding en routing ===

def lookup_postcode(postcode: str) -> tuple[float, float] | None:
    """Nominatim lookup; geeft (lat, lon) of None terug."""
    q = urllib.parse.quote(f"{postcode}, Nederland")
    url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&countrycodes=nl"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _eerlijke_ua() or USER_AGENT_TERUGVAL})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if data:
            return (float(data[0]["lat"]), float(data[0]["lon"]))
    except Exception:
        return None
    return None


def get_werk_coords() -> dict[str, tuple[float, float]]:
    """Lees gecachte coordinates of doe nieuwe lookups."""
    if WERK_CACHE.exists():
        try:
            d = json.loads(WERK_CACHE.read_text())
            return {k: tuple(v) for k, v in d.items()}
        except Exception:
            pass
    coords: dict[str, tuple[float, float]] = {}
    for pc, _ in _werk_postcodes():
        c = lookup_postcode(pc)
        if c:
            coords[pc] = c
        time.sleep(1.1)  # nominatim policy: max 1 req/s
    if coords:
        WERK_CACHE.write_text(json.dumps({k: list(v) for k, v in coords.items()}, indent=2))
    return coords


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def osrm_route_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    """Roep OSRM publieke router aan. Retourneer afstand in km of None."""
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=false"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _eerlijke_ua() or USER_AGENT_TERUGVAL})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read())
        if data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]["distance"] / 1000
    except Exception:
        return None
    return None


def afstand_km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, str]:
    """Bereken afstand. OSRM eerst, fallback haversine x 1.3."""
    km = osrm_route_km(lat1, lon1, lat2, lon2)
    if km is not None:
        return (km, "weg")
    km = haversine_km(lat1, lon1, lat2, lon2) * 1.3
    return (km, "schatting")


# === Verrijking via extra pyfunda endpoints ===

def woning_sleutel(d: dict) -> str:
    return str(d.get("global_id") or d.get("listing_id") or d.get("detail_url") or d.get("title") or "")


def funda_url(d: dict) -> str:
    url = d.get("detail_url") or d.get("url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    return url


def _schoon_markt_cache(cache: dict) -> dict:
    """Alle buurtcijfers in de cache door de allowlist, ook die van buurten die deze run niet langskomen
    (elementen van voor de allowlist hielden inwonertal en gezinnen met kinderen)."""
    markt = cache.get("market_insights")
    if isinstance(markt, dict):
        for entry in markt.values():
            if isinstance(entry, dict) and isinstance(entry.get("data"), dict):
                entry["data"] = _markt_allowlist(entry["data"])
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


def _cache_fresh(entry: dict | None, max_age_days: int) -> bool:
    if not isinstance(entry, dict) or not entry.get("fetched"):
        return False
    try:
        fetched = datetime.strptime(entry["fetched"], "%Y-%m-%d")
    except Exception:
        return False
    return (datetime.now() - fetched).days <= max_age_days


def _cache_get(cache: dict, section: str, key: str, max_age_days: int):
    entry = cache.setdefault(section, {}).get(key)
    if _cache_fresh(entry, max_age_days):
        return entry.get("data")
    return None


def _cache_put(cache: dict, section: str, key: str, data) -> None:
    cache.setdefault(section, {})[key] = {
        "fetched": datetime.now().strftime("%Y-%m-%d"),
        "data": data,
    }


def _slug_key(*parts: str | None) -> str:
    return "|".join((p or "").strip().lower() for p in parts)


def _parse_history_price(change: dict) -> int | None:
    value = change.get("price")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def analyse_price_history(changes: list[dict], current_price: int) -> dict:
    asking = []
    woz = []
    sold = []
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        status = str(change.get("status") or "").lower()
        price = _parse_history_price(change)
        item = {
            "price": price,
            "date": change.get("date") or change.get("timestamp"),
            "timestamp": change.get("timestamp"),   # ISO, voor de peildatum in het rapport
            "source": change.get("source"),
            "status": status,
            "human_price": change.get("human_price"),
        }
        if status == "asking_price":
            asking.append(item)
        elif status == "woz":
            woz.append(item)
        elif status == "sold":
            sold.append(item)

    asking_prices = [x["price"] for x in asking if x.get("price")]
    highest = max(asking_prices) if asking_prices else None
    lowest = min(asking_prices) if asking_prices else None
    drop = max(0, highest - current_price) if highest and current_price else 0
    drop_pct = round(drop / highest * 100, 1) if drop and highest else 0.0
    latest_woz = next((x for x in woz if x.get("price")), None)
    latest_sold = next((x for x in sold if x.get("price")), None)

    return {
        "asking_count": len(asking),
        "highest_asking": highest,
        "lowest_asking": lowest,
        "drop_from_high": drop,
        "drop_pct": drop_pct,
        "latest_woz": latest_woz,
        "latest_sold": latest_sold,
        "changes": changes or [],
    }


def analyse_market(d: dict, insights: dict | None) -> dict:
    """Vraagprijs per m² tegenover het buurtgemiddelde van funda (voor het onderdeel markt)."""
    price = d.get("price") or 0
    m2 = d.get("living_area") or 0
    ppm = int(price / m2) if price and m2 else 0
    avg = None
    if isinstance(insights, dict):
        try:
            avg = int(insights.get("avg_asking_price_per_m2") or 0) or None
        except (TypeError, ValueError):
            avg = None
    diff_pct = round((ppm - avg) / avg * 100, 1) if ppm and avg else None
    return {
        "price_per_m2": ppm,
        "avg_asking_price_per_m2": avg,
        "diff_pct": diff_pct,
    }


# Van funda's buurtcijfers alleen de gemiddelde vraagprijs per m². Inwoners, gezinnen met
# kinderen en andere bevolkingskenmerken worden niet bewaard of getoond (beoordeling.md 1.6).
MARKT_VELDEN = ("avg_asking_price_per_m2",)


def _markt_allowlist(insights) -> dict | None:
    if not isinstance(insights, dict):
        return None
    if insights.get("_error"):
        return {"_error": str(insights["_error"])}
    return {k: insights[k] for k in MARKT_VELDEN if k in insights}


def analyse_broker(info: dict | None, reviews: dict | None, listings: list[dict] | None) -> dict:
    listings = listings or []
    status_counts = Counter(str(item.get("status") or "unknown") for item in listings if isinstance(item, dict))
    average = reviews.get("average") if isinstance(reviews, dict) else None
    review_count = reviews.get("number_of_reviews") if isinstance(reviews, dict) else None
    try:
        average = float(average) if average is not None else None
    except (TypeError, ValueError):
        average = None
    try:
        review_count = int(review_count) if review_count is not None else None
    except (TypeError, ValueError):
        review_count = None
    return {
        "name": (info or {}).get("name"),
        "affiliation": (info or {}).get("affiliation"),
        "phone": (info or {}).get("phone"),
        "email": (info or {}).get("email"),
        "website": (info or {}).get("website"),
        "review_average": average,
        "review_count": review_count,
        "sold_count": status_counts.get("sold", 0),
        "for_sale_count": status_counts.get("for_sale", 0),
        "purchased_count": status_counts.get("purchased", 0),
        "info": info or {},
        "reviews": reviews or {},
        "listings": listings,
    }


def fetch_with_cache(cache: dict, section: str, key: str, max_age_days: int, fetcher):
    cached = _cache_get(cache, section, key, max_age_days)
    if cached is not None:
        return cached
    try:
        data = fetcher()
    except Exception as exc:
        data = {"_error": str(exc)}
    _cache_put(cache, section, key, data)
    return data


def verrijk_woning(f, d: dict, listing_obj, cache: dict) -> dict:
    """Haal extra data op uit pyfunda v2.9 endpoints. Alle failures zijn non-fatal."""
    sleutel = woning_sleutel(d)
    price = d.get("price") or 0
    city = d.get("city") or ""
    neighbourhood = d.get("neighbourhood") or ""
    listing_data = getattr(listing_obj, "data", None)
    if not isinstance(listing_data, dict) and isinstance(listing_obj, dict):
        listing_data = listing_obj
    broker_id = d.get("broker_id")
    if isinstance(listing_data, dict):
        broker_id = broker_id or listing_data.get("broker_id")

    url = funda_url(d)
    price_history_raw = []
    if hasattr(f, "get_price_history") and (listing_obj is not None or url):
        def fetch_price_history():
            if listing_obj is not None:
                # Geen terugval op de URL: pyfunda haalt de woning dan nog eens op
                # via het detail-endpoint (een dubbele detail-call in dezelfde run)
                # en stuurt daarna precies hetzelfde verzoek naar de prijsbron.
                return f.get_price_history(listing_obj)
            return f.get_price_history(url)

        price_history_raw = fetch_with_cache(
            cache,
            "price_history",
            sleutel,
            7,
            fetch_price_history,
        )
        if isinstance(price_history_raw, dict) and price_history_raw.get("_error"):
            price_history_raw = []

    market_raw = None
    if hasattr(f, "get_market_insights") and city and neighbourhood:
        sleutel_markt = _slug_key(city, neighbourhood)
        market_raw = _markt_allowlist(fetch_with_cache(
            cache,
            "market_insights",
            sleutel_markt,
            30,
            lambda: _markt_allowlist(f.get_market_insights(city, neighbourhood)),
        ))
        if isinstance(market_raw, dict) and market_raw.get("_error"):
            market_raw = None

    broker_raw = {"info": None, "reviews": None, "listings": []}
    if broker_id and hasattr(f, "get_broker_info"):
        bid = str(broker_id)

        def fetch_broker_bundle():
            bundle = {"info": None, "reviews": None, "listings": []}
            for name, method in (
                ("info", "get_broker_info"),
                ("reviews", "get_broker_reviews"),
                ("listings", "get_broker_listings"),
            ):
                if not hasattr(f, method):
                    continue
                try:
                    bundle[name] = getattr(f, method)(int(bid))
                    time.sleep(0.2)
                except Exception as exc:
                    bundle[name] = {"_error": str(exc)}
            return bundle

        broker_raw = fetch_with_cache(cache, "broker", bid, 30, fetch_broker_bundle)
        if not isinstance(broker_raw, dict):
            broker_raw = {"info": None, "reviews": None, "listings": []}

    return {
        "price_history": analyse_price_history(price_history_raw if isinstance(price_history_raw, list) else [], price),
        "market": analyse_market(d, market_raw if isinstance(market_raw, dict) else None),
        "broker": analyse_broker(
            broker_raw.get("info") if isinstance(broker_raw.get("info"), dict) and not broker_raw.get("info", {}).get("_error") else None,
            broker_raw.get("reviews") if isinstance(broker_raw.get("reviews"), dict) and not broker_raw.get("reviews", {}).get("_error") else None,
            broker_raw.get("listings") if isinstance(broker_raw.get("listings"), list) else [],
        ),
    }


# === Beoordeling: poort, score en uitleg uit funda_beoordeling ===

PRIJS_ONBEKEND = "PRIJS ONBEKEND"
# Pauze na elke detail-call van het rapport. In funda_zoek zit een cache voor (DetailCacheZoeker),
# dus meestal geen echt verzoek; de pauze blijft als vangnet. Tests zetten hem op 0.
DETAIL_PAUZE_S = 0.5


def laad_config() -> dict:
    """De beoordelingsconfig: standaardwaarden plus de sleutels beoordeling en financien uit de config."""
    return funda_beoordeling.laad_config(_PERSONAL)


def _getal(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


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
    """Eén rapportrij met de beoordeling volgens het contract (beoordeling.md par. 9).

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


def sorteer_rijen(rijen: list[dict]) -> list[dict]:
    """(geen vraagprijs, poort, twijfel, -score), in place: zelfde sleutel als 'Aanbevolen' in de UI."""
    return funda_beoordeling.sorteer(rijen)


# === Rente en verrijking: fail-soft ===

def _eerlijke_ua() -> str | None:
    """EERLIJKE_UA uit funda_zoek. Draait funda_zoek.py als script, dan staat die in __main__;
    zo wordt dat script niet nog een keer als module geladen."""
    for naam in ("funda_zoek", "__main__"):
        ua = getattr(sys.modules.get(naam), "EERLIJKE_UA", None)
        if isinstance(ua, str) and ua:
            return ua
    try:
        from funda_zoek import EERLIJKE_UA  # noqa: PLC0415
        return EERLIJKE_UA
    except Exception:  # noqa: BLE001
        return None


def _rente_cfg(cfg: dict) -> dict:
    """financien.rente zoals funda_rente hem leest, met de aliassen die funda_beoordeling ook kent.

    rente.handmatig = rente.pct, rente.rentevast_jaar = rente.rentevast_jaren, rente.max_dagen, en
    als terugval de oude plek beoordeling.financiering (rente met rente_datum, rentevast_jaren,
    rente_max_dagen). Die oude sleutels hebben geen standaardwaarde, dus staan ze er alleen als je
    ze zelf zet. Een handmatige rente gaat altijd voor."""
    fin = dict(cfg.get("financien") or {}) if isinstance(cfg.get("financien"), dict) else {}
    r = dict(fin.get("rente")) if isinstance(fin.get("rente"), dict) else {}
    if r.get("pct") is None and r.get("handmatig") is not None:
        r["pct"] = r["handmatig"]
    if r.get("rentevast_jaren") is None and r.get("rentevast_jaar") is not None:
        r["rentevast_jaren"] = r["rentevast_jaar"]
    oud = cfg.get("financiering") or {}
    if r.get("pct") is None and oud.get("rente") is not None:
        r["pct"] = oud["rente"]
        if r.get("datum") is None:   # ook als financien.rente.datum expliciet null is
            r["datum"] = oud.get("rente_datum")
    if r.get("rentevast_jaren") is None and oud.get("rentevast_jaren") is not None:
        r["rentevast_jaren"] = oud["rentevast_jaren"]
    if r.get("max_dagen") is None and oud.get("rente_max_dagen") is not None:
        r["max_dagen"] = oud["rente_max_dagen"]
    fin["rente"] = r
    return {"financien": fin}


def haal_rente(cfg: dict, cache: dict, vandaag, http=None, ua: str | None = None) -> dict:
    """De rente voor de beoordeling en de UI: {"pct", "bron", "datum", "oud", "melding", "rentevast_jaren"}.

    Gooit nooit: lukt funda_rente niet, dan de rente uit de config (of de standaard uit het model)."""
    rcfg = _rente_cfg(cfg)
    try:
        r = funda_rente.huidige_rente(rcfg, cache, vandaag, http=http, ua=ua)
        if not (isinstance(r, dict) and _getal(r.get("pct"))):
            raise ValueError("geen rente")
        r = dict(r)
        if r.get("bron") == "standaard":
            r.setdefault("rentevast_jaren", funda_beoordeling.STANDAARD_RENTE["rentevast_jaren"])
        else:
            r.setdefault("rentevast_jaren", funda_rente.instellingen(rcfg).get("rentevast_jaren"))
        return r
    except Exception as exc:  # noqa: BLE001  de rente mag een run nooit laten falen
        print(f"[rapport] Rente niet opgehaald ({type(exc).__name__}); gerekend met de rente uit de config.")
        try:
            return funda_beoordeling.rente_uit_config(cfg, vandaag)
        except Exception:  # noqa: BLE001
            return dict(funda_beoordeling.STANDAARD_RENTE, bron="standaard", oud=True, melding=None)


def verrijk_rijen(rijen: list[dict], cache: dict, cfg: dict, vandaag, http=None,
                  ua: str | None = None) -> dict[str, dict]:
    """funda_verrijking.verrijk() op de rijen (voorlopige beoordeling bepaalt de volgorde). Gooit nooit."""
    if not rijen:
        return {}
    try:
        return funda_verrijking.verrijk(rijen, cache, cfg, vandaag, http=http, ua=ua) or {}
    except Exception as exc:  # noqa: BLE001  verrijking is fail-soft: nooit exit 2, nooit een woning minder
        print(f"[rapport] Verrijking overgeslagen ({type(exc).__name__}); {len(rijen)} woningen zonder.")
        return {}


def log_aantallen(rijen: list[dict]) -> None:
    """Voor de publieke log: alleen labelnamen van funda's kenmerken en aantallen. Geen adressen of waarden."""
    details = [r.get("details") or r.get("d") or {} for r in rijen]
    labels = funda_beoordeling.log_kenmerk_labels(details)
    n_met = sum(1 for det in details if isinstance(det.get("characteristics"), dict))
    print(f"[rapport] Kenmerklabels uit {n_met} van {len(rijen)} woningen ({len(labels)} soorten): "
          + ("; ".join(f"{k} {n}" for k, n in labels.items()) or "geen"))
    tel = Counter((r.get("beoordeling") or {}).get("poort") for r in rijen)
    twijfel = sum(1 for r in rijen if (r.get("beoordeling") or {}).get("twijfel"))
    print("[rapport] Per poort: " + ", ".join(f"{naam} {tel.get(p, 0)}"
                                             for p, naam in funda_beoordeling.POORT_NAAM.items())
          + f"; met twijfel {twijfel}.")


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
        "eigen_geld_tekort_past_niet": fin.get("eigen_geld_tekort_past_niet"),
        "lang_op_funda_dagen": cfg.get("lang_op_funda_dagen"),
    }
    try:
        meta["leentoets_jaar"] = funda_beoordeling.tabel().get("jaar")
    except Exception:  # noqa: BLE001
        pass
    # "Jouw budget" leidt de max. koopsom per scenario af uit de rijen (met de spreiding door label
    # en erfpacht). Zonder rijen met scenario's: het overzicht zonder woning.
    if not any(((r.get("beoordeling") or {}).get("financiering") or {}).get("scenarios") for r in rijen or []):
        try:
            sc = funda_beoordeling.scenario_overzicht(cfg, _PERSONAL, rente, vandaag)
            if sc:
                meta["scenarios"] = [{"id": s["id"], "label": s["label"], "max_koopsom": s["max_koopsom"]} for s in sc]
        except Exception:  # noqa: BLE001
            pass
    return {k: v for k, v in meta.items() if v is not None}


# === Rapport ===

def genereer_rapport(f, woningen: list[dict], nieuw_ids: set[str] | None = None, *, http=None,
                     ua: str | None = None, vandaag: date | None = None) -> Path:
    """Detail-call, routes, beoordeling en verrijking per woning; schrijft markdown, HTML en de PWA.

    http en ua gaan naar de rente en de verrijking (tests geven een nep-functie mee); standaard het
    gewone netwerk met EERLIJKE_UA. De woningen zijn de dicts uit funda_zoek; elke dict krijgt
    _enrichment en _beoordeling erbij."""
    nieuw_ids = nieuw_ids or set()
    nu = _nu()
    vandaag = vandaag or nu.date()
    ua = ua or _eerlijke_ua()
    werk_coords = get_werk_coords()
    cache = load_enrichment_cache()
    cfg = laad_config()
    rente = haal_rente(cfg, cache, vandaag, http=http, ua=ua)
    print(f"\n[rapport] Detail-call voor {len(woningen)} woningen, werk-coords: {len(werk_coords)} adressen.")

    rijen = []
    for d in woningen:
        lid = d.get("global_id") or d.get("listing_id")
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        details = None
        listing_obj = None
        try:
            listing_obj = f.get_listing(lid)
            if isinstance(getattr(listing_obj, "data", None), dict):
                details = listing_obj.data
            if DETAIL_PAUZE_S:
                time.sleep(DETAIL_PAUZE_S)
        except Exception as exc:
            print(f"  Detail fout {lid}: {exc}")
        d["_enrichment"] = verrijk_woning(f, d, listing_obj, cache)
        lat, lon = _coords(d, details)
        rij = bouw_rij(d, details, bereken_routes(lat, lon, werk_coords), cfg=cfg, rente=rente, vandaag=vandaag)
        rij["is_nieuw"] = sleutel in nieuw_ids
        rijen.append(rij)

    # Verrijking na de voorlopige beoordeling (Past en Krap eerst), daarna definitief beoordelen.
    verrijking = verrijk_rijen(rijen, cache, cfg, vandaag, http=http, ua=ua)
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
    meta = rapport_meta(cfg, rente, nu, rijen, vandaag)

    UITVOER_DIR.mkdir(parents=True, exist_ok=True)
    pad_md = UITVOER_DIR / "funda_rapport.md"
    pad_md.write_text(render_markdown(rijen, meta), encoding="utf-8")
    pad_html = UITVOER_DIR / "funda_rapport.html"
    pad_html.write_text(render_html(rijen, meta), encoding="utf-8")
    pwa_dir = schrijf_pwa_assets(rijen, meta)

    print(f"[rapport] Geschreven: {pad_md.name}, {pad_html.name}, en {pwa_dir.name}/")
    return pad_html


# === Markdown (lokaal, gitignored) ===

def _md(tekst) -> str:
    """Tekst voor in een markdown-tabelcel of -regel."""
    return str(tekst if tekst is not None else "").replace("|", "/").replace("\n", " ").strip()


def _prijs_tekst(r: dict) -> str:
    prijs = (r.get("d") or {}).get("price")
    return "prijs op aanvraag" if r.get("prijs_onbekend") or not prijs else funda_ui.eur_tekst(prijs)


def _punten_md(items: list[dict]) -> str:
    return "; ".join(_md(f"{it.get('label')}: {it.get('waarde')}"
                         + (f" ({it['bron']})" if it.get("bron") else "")) for it in items)


def _rente_md(r: dict) -> str:
    pct = _getal(r.get("pct"))
    if pct is None:
        return ""
    pct = pct * 100 if pct < 1 else pct
    bron = funda_ui.RENTE_BRON.get(str(r.get("bron")), str(r.get("bron") or "onbekend"))
    vast = f", {r['rentevast_jaren']} jaar vast" if r.get("rentevast_jaren") else ""
    try:
        peil = f", peildatum {funda_ui.datum_lang(date.fromisoformat(str(r.get('datum'))))}"
    except ValueError:
        peil = ""
    return f"{funda_ui.komma(pct, 2)}%{vast} ({bron}{peil}{', oud' if r.get('oud') else ''})"


def _scenarios_md(rijen: list[dict], meta: dict) -> list[str]:
    per: dict[str, list] = {}
    volg: list[str] = []
    labels: dict[str, str] = {}
    planning = None
    bron = [((r.get("beoordeling") or {}).get("financiering") or {}) for r in rijen]
    for f in bron:
        planning = planning or f.get("planning")
        for s in f.get("scenarios") or []:
            if s.get("id") not in per:
                volg.append(s.get("id"))
                per[s.get("id")] = []
                labels[s.get("id")] = s.get("label") or s.get("id")
            per[s.get("id")].append(s.get("max_koopsom"))
    if not volg:
        for s in meta.get("scenarios") or []:
            volg.append(s.get("id"))
            per[s.get("id")] = [s.get("max_koopsom")]
            labels[s.get("id")] = s.get("label") or s.get("id")
    regels = []
    for sid in volg:
        w = [x for x in per[sid] if _getal(x)]
        if not w:
            continue
        lo, hi = min(w), max(w)
        tekst = funda_ui.eur_tekst(lo) if lo == hi else f"{funda_ui.eur_tekst(lo)} tot {funda_ui.eur_tekst(hi)}"
        regels.append(f"  - {_md(labels[sid])}{' (planning)' if sid == planning else ''}: {tekst}")
    return regels


def render_markdown(rijen: list[dict], meta: dict | None = None) -> str:
    """Per woning '### <adres>' met '<status_kort> · score x,x' en de uitleg_regel uit het model.

    Geen inkomen en nooit "€ 0": zonder vraagprijs staat er "prijs op aanvraag"."""
    meta = meta or {}
    nu = meta.get("tijdstip") if isinstance(meta.get("tijdstip"), datetime) else _nu()
    k = funda_ui.komma
    lines = [f"# Woningrapport, {_nu_nl(nu)}", "", "## Jouw budget en aannames", ""]
    f0 = next((((r.get("beoordeling") or {}).get("financiering") or {}) for r in rijen
               if ((r.get("beoordeling") or {}).get("financiering") or {}).get("grens") is not None), {})
    if f0:
        soort = "bruto per maand (norm uit de leentoets)" if f0.get("grens_soort") == "bruto norm" else "netto per maand"
        lines.append(f"- Je grens: {funda_ui.eur_tekst(f0['grens'])} {soort}")
    r = meta.get("rente") or {}
    if _rente_md(r):
        lines.append(f"- Rente: {_rente_md(r)}")
    if r.get("melding"):
        lines.append(f"- Let op de rente: {_md(r['melding'])}")
    sc = _scenarios_md(rijen, meta)
    if sc:
        lines.append("- Max. koopsom per scenario:")
        lines.extend(sc)
    lines += ["- Woonlasten zijn netto, jaar 1. Een bedrag met ≈ is een schatting.",
              "- Score 0 tot 10. 5 betekent: voldoet aan je eisen. Onbekend en kansen tellen niet mee.", ""]

    if not rijen:
        lines.append("Geen woningen om te beoordelen.")
        return "\n".join(lines)

    lines += ["## Overzicht", "", "| # | Woning | Vraagprijs | Status | Score |",
              "|---|--------|-----------:|--------|------:|"]
    for i, rij in enumerate(rijen, 1):
        d, b = rij["d"], rij.get("beoordeling") or {}
        lines.append(f"| {i} | {_md(d.get('title'))}, {_md(d.get('city'))} | {_prijs_tekst(rij)} "
                     f"| {_md(b.get('status_kort'))} | {k(b.get('score') or 0)} |")
    lines += ["", "## Per woning", ""]

    for i, rij in enumerate(rijen, 1):
        d, b = rij["d"], rij.get("beoordeling") or {}
        fin = b.get("financiering") or {}
        det = rij.get("details") or {}
        lines.append(f"### {i}. {_md(d.get('title'))}, {_md(d.get('city'))}{' (nieuw)' if rij.get('is_nieuw') else ''}")
        lines.append("")
        lines.append(f"- **{_md(b.get('status_kort'))} · score {k(b.get('score') or 0)}**")
        if b.get("uitleg_regel"):
            lines.append(f"- {_md(b['uitleg_regel'])}")
        if fin.get("scenario_tekst"):
            lines.append(f"- Scenario: {_md(fin['scenario_tekst'])}")
        for t in b.get("twijfel") or []:
            lines.append(f"- Twijfel: {_md(t)} Onderaan gezet.")
        m2 = d.get("living_area") or det.get("living_area")
        prijs = _prijs_tekst(rij)
        if not rij.get("prijs_onbekend") and m2:
            prijs += f" ({funda_ui.eur_tekst(d['price'] / m2)} per m²)"
        netto = fin.get("netto")
        lasten = f"{funda_ui.eur_tekst(netto)} netto per maand" if netto is not None else "onbekend"
        lines.append(f"- Vraagprijs: {prijs} · Woonlasten: {lasten}")
        feit = [f"{m2} m²" if m2 else None, f"{d.get('rooms')} kamers" if d.get("rooms") else None,
                f"label {d.get('energy_label') or det.get('energy_label') or 'onbekend'}",
                _md(d.get("neighbourhood")) or None]
        lines.append("- Woning: " + ", ".join(x for x in feit if x))
        tr = rij.get("track") or {}
        if tr.get("gedaald") and tr.get("eerdere_prijs"):
            lines.append(f"- Prijs gedaald: was {funda_ui.eur_tekst(tr['eerdere_prijs'])}")
        for kop, sleutel in (("Let op", "let_op"), ("Pluspunten", "pluspunten"), ("Onbekend", "onbekend"),
                             ("Kansen", "kansen")):
            if b.get(sleutel):
                lines.append(f"- {kop}: {_punten_md(b[sleutel])}")
        if b.get("zelf_nagaan"):
            lines.append("- Zelf nagaan:")
            lines.extend(f"  {n}. {_md(v)}" for n, v in enumerate(b["zelf_nagaan"], 1))
        url = funda_url(d)
        if url:
            lines.append(f"- Funda: {url}")
        lines += ["", "---", ""]
    return "\n".join(lines)


# === HTML (lokaal) en PWA ===

# Leaflet (kaart) via CDN, in de <head>: scripts in de via innerHTML gezette body draaien niet.
MAP_HEAD = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script defer src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
"""


def pwa_push_js() -> str:
    """Web Push in de PWA: abonnement maken en tonen voor de secret WEB_PUSH_SUBSCRIPTION.

    Hoort bij het blok "Meldingen op deze iPhone" (funda_ui, ids push-*). Heeft dit toestel al een
    abonnement, dan verbergt de JS dat blok. Leeg zonder WEB_PUSH_PUBLIC_KEY."""
    if not WEB_PUSH_PUBLIC_KEY:
        return ""
    key = json.dumps(WEB_PUSH_PUBLIC_KEY)
    return f"""
<script>
(function(){{
  var WEB_PUSH_PUBLIC_KEY = {key};
  function pushStatus(msg, isError){{
    var el = document.getElementById('push-status');
    if(!el) return;
    el.textContent = msg || '';
    el.classList.toggle('is-fout', !!isError);
  }}
  function verbergAlsIngesteld(){{
    var blok = document.getElementById('meldingen');
    if(!blok || !('serviceWorker' in navigator) || !('PushManager' in window)) return;
    navigator.serviceWorker.ready.then(function(reg){{ return reg.pushManager.getSubscription(); }})
      .then(function(sub){{ if(sub && blok.dataset.net !== '1') blok.hidden = true; }})
      .catch(function(){{}});
  }}
  function b64ToUint8Array(base64){{
    var padding = '='.repeat((4 - base64.length % 4) % 4);
    var b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(b64);
    var out = new Uint8Array(raw.length);
    for(var i=0;i<raw.length;i++) out[i] = raw.charCodeAt(i);
    return out;
  }}
  async function ensurePushSubscription(){{
    if(!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)){{
      throw new Error('Web Push wordt niet ondersteund in deze browser.');
    }}
    var permission = await Notification.requestPermission();
    if(permission !== 'granted') throw new Error('Notificaties zijn niet toegestaan.');
    var reg = await navigator.serviceWorker.ready;
    var sub = await reg.pushManager.getSubscription();
    if(!sub){{
      sub = await reg.pushManager.subscribe({{
        userVisibleOnly: true,
        applicationServerKey: b64ToUint8Array(WEB_PUSH_PUBLIC_KEY)
      }});
    }}
    return sub;
  }}
  function wirePushSetup(){{
    var btn = document.getElementById('push-subscribe-btn');
    var copy = document.getElementById('push-copy-btn');
    var output = document.getElementById('push-subscription-output');
    if(!btn || !output || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    verbergAlsIngesteld();
    btn.addEventListener('click', async function(){{
      btn.disabled = true;
      var blok = document.getElementById('meldingen');
      if(blok) blok.dataset.net = '1';
      pushStatus('Abonnement maken...');
      try {{
        var sub = await ensurePushSubscription();
        output.value = JSON.stringify(sub.toJSON(), null, 2);
        output.hidden = false;
        if(copy) copy.hidden = false;
        pushStatus('Kopieer dit abonnement naar de GitHub-secret WEB_PUSH_SUBSCRIPTION.');
      }} catch(err) {{
        pushStatus(err && err.message ? err.message : String(err), true);
      }} finally {{
        btn.disabled = false;
      }}
    }});
    if(copy){{
      copy.addEventListener('click', async function(){{
        try {{
          await navigator.clipboard.writeText(output.value || '');
          pushStatus('Abonnement gekopieerd.');
        }} catch(err) {{
          output.focus();
          output.select();
          pushStatus('Kopieer de geselecteerde tekst zelf.', true);
        }}
      }});
    }}
  }}
  var previous = window.fundaAfterReportLoad;
  window.fundaAfterReportLoad = function(){{
    if(previous) previous();
    wirePushSetup();
  }};
  document.addEventListener('DOMContentLoaded', wirePushSetup);
}})();
</script>
"""


def _scripts(is_pwa: bool) -> str:
    """Complete <script>-blokken: eerst de UI (zet fundaAfterReportLoad), dan de push-JS die erop aanhaakt."""
    return f"<script>{funda_ui.UI_JS}</script>" + (pwa_push_js() if is_pwa else "")


def _body(rijen: list[dict], meta: dict | None, is_pwa: bool) -> str:
    m = dict(meta or {})
    m["push_beschikbaar"] = bool(is_pwa and WEB_PUSH_PUBLIC_KEY)
    return funda_ui.render_report_body(rijen, m)


def render_html(rijen: list[dict], meta: dict | None = None, is_pwa: bool = False) -> str:
    """Het onversleutelde rapport: lokaal funda_rapport.html, of de PWA als er geen wachtwoord is."""
    meta = meta or {}
    nu = meta.get("tijdstip") if isinstance(meta.get("tijdstip"), datetime) else _nu()
    asset_prefix = "" if is_pwa else "docs/"
    pwa_head = ""
    pwa_script = ""
    if is_pwa:
        pwa_head = """
<link rel="manifest" href="manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Woningen">
"""
        pwa_script = """
<script>
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js', {scope:'./'}).catch(()=>{}));
}
</script>
"""
    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="{funda_ui.THEME_COLOR_DONKER}">
<meta name="theme-color" content="{funda_ui.THEME_COLOR}">
<title>Woningrapport, {nu.day} {_NL_MAANDEN[nu.month - 1]} {nu.year}</title>
<link rel="icon" href="{asset_prefix}favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" sizes="180x180" href="{asset_prefix}apple-touch-icon.png">
{pwa_head}
{MAP_HEAD}
<style>{funda_ui.UI_CSS}</style>
</head>
<body>
{_body(rijen, meta, is_pwa)}
{_scripts(is_pwa)}
{pwa_script}
</body>
</html>"""


PWA_DIR_NAAM = "docs"  # GitHub Pages staat alleen / of /docs toe
PWA_PASSWORD_FILE = Path(__file__).parent / "funda_pwa_password.txt"
# Map voor funda_rapport.md, funda_rapport.html en docs/. Tests zetten hier een tijdelijke map.
UITVOER_DIR = Path(__file__).parent

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

# Cache ophogen is verplicht bij een nieuwe wrapper: anders blijft een geïnstalleerde PWA de oude tonen.
PWA_SERVICE_WORKER = """// Woningrapport: service worker (network-first, cache als terugval)
const CACHE = 'funda-shortlist-v5';
const ASSETS = ['./', 'index.html', 'manifest.json', 'icon.svg', 'favicon.svg', 'apple-touch-icon.png', 'icon-512.png'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone)).catch(()=>{});
      }
      return resp;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('index.html')))
  );
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


def _rgba(hex_kleur: str) -> tuple[int, int, int, int]:
    h = hex_kleur.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255


def _write_png_icon(path: Path, size: int) -> None:
    """Schrijf het icoon als PNG zonder externe dependencies (zelfde huis als PWA_ICON_SVG).

    Getekend op 3x (of 2x) de doelmaat en daarna verkleind, voor zachte randen."""
    import struct
    import zlib

    target_size = size
    scale = 3 if target_size <= 256 else 2
    size = target_size * scale
    f = size / 512

    achtergrond = _rgba(ICOON_ACHTERGROND)
    huis = _rgba(ICOON_HUIS)
    accent = _rgba(ICOON_ACCENT)
    buf = bytearray(bytes(achtergrond) * (size * size))

    def put(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            buf[i:i + 4] = bytes(color)

    def rect(r: tuple[int, int, int, int], color: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = (int(round(v * f)) for v in r)
        for yy in range(max(0, y1), min(size, y2)):
            for xx in range(max(0, x1), min(size, x2)):
                put(xx, yy, color)

    def poly(points: list[tuple[int, int]], color: tuple[int, int, int, int]) -> None:
        pts = [(x * f, y * f) for x, y in points]
        min_y = max(0, int(min(p[1] for p in pts)))
        max_y = min(size - 1, int(max(p[1] for p in pts)) + 1)
        min_x = max(0, int(min(p[0] for p in pts)))
        max_x = min(size - 1, int(max(p[0] for p in pts)) + 1)
        for yy in range(min_y, max_y + 1):
            for xx in range(min_x, max_x + 1):
                inside = False
                j = len(pts) - 1
                for i, (xi, yi) in enumerate(pts):
                    xj, yj = pts[j]
                    if ((yi > yy) != (yj > yy)) and (xx < (xj - xi) * (yy - yi) / (yj - yi) + xi):
                        inside = not inside
                    j = i
                if inside:
                    put(xx, yy, color)

    poly(_HUIS_DAK, huis)
    rect(_HUIS_ROMP, huis)
    rect(_HUIS_DEUR, achtergrond)
    rect(_HUIS_RAAM, accent)

    if scale > 1:
        small = bytearray(target_size * target_size * 4)
        block = scale * scale
        for y in range(target_size):
            for x in range(target_size):
                sums = [0, 0, 0, 0]
                for yy in range(scale):
                    for xx in range(scale):
                        i = ((y * scale + yy) * size + (x * scale + xx)) * 4
                        sums[0] += buf[i]
                        sums[1] += buf[i + 1]
                        sums[2] += buf[i + 2]
                        sums[3] += buf[i + 3]
                o = (y * target_size + x) * 4
                small[o:o + 4] = bytes(int(v / block) for v in sums)
        buf = small
        size = target_size

    stride = size * 4
    raw = b"".join(b"\x00" + bytes(buf[y * stride:(y + 1) * stride]) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def beveilig_html(html: str, password: str, css: str | None = None, scripts: str | None = None,
                  gz: bool = True) -> str:
    """Versleutel de body en wikkel hem in het slotscherm (ui/slot.html).

    Eerst gzip (niveau 9, mtime 0, dus reproduceerbaar), dan AES-256-GCM met een sleutel uit
    PBKDF2-SHA256 (100.000 iteraties, 16 byte zout, 12 byte IV). Comprimeren moet vóór het
    versleutelen: ciphertext comprimeert niet, dus Pages kan hem over de lijn niet kleiner maken.
    `gz=False` is de terugval (het slotscherm kent dan GZ 0 en pakt niets uit).

    css: CSS in het slotscherm (standaard funda_ui.UI_CSS; het slotscherm gebruikt die klassen ook).
    scripts: complete <script>-blokken buiten de versleuteling (standaard de UI-JS en pwa_push_js()),
    want scripts in de via innerHTML gezette body draaien niet.
    """
    import base64
    import gzip
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    css = funda_ui.UI_CSS if css is None else css
    scripts = _scripts(True) if scripts is None else scripts
    data = html.encode("utf-8")
    if gz:
        data = gzip.compress(data, compresslevel=9, mtime=0)

    salt = os.urandom(16)
    iv = os.urandom(12)
    iters = 100_000  # snel genoeg op mobiel, sterk genoeg met goed wachtwoord
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    key = kdf.derive(password.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, data, None)

    return funda_ui.vul_slot({
        "__APP_CSS__": css,
        "__MAP_HEAD__": MAP_HEAD,
        "__APP_SCRIPTS__": scripts,
        "__GZ__": "1" if gz else "0",
        "__SALT__": base64.b64encode(salt).decode(),
        "__IV__": base64.b64encode(iv).decode(),
        "__CT__": base64.b64encode(ciphertext).decode(),
        "__ITERS__": str(iters),
    })


def _pwa_wachtwoord() -> str:
    """Het PWA-wachtwoord, of "" als er geen is."""
    if PWA_PASSWORD_FILE.exists():
        return PWA_PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return ""


def schrijf_pwa_assets(rijen: list[dict], meta: dict | None = None) -> Path:
    """Manifest, service worker, iconen en index.html in docs/ (onder UITVOER_DIR)."""
    password = _pwa_wachtwoord()
    # Vangrail: in CI (publieke repo) NOOIT onversleuteld publiceren. Vóór het schrijven, zodat
    # er dan ook niets anders in docs/ verandert.
    if not password and os.environ.get("FUNDA_REQUIRE_ENCRYPTION") == "1":
        raise RuntimeError(
            "FUNDA_REQUIRE_ENCRYPTION=1 maar geen wachtwoord gevonden; "
            "weiger om een onversleuteld rapport te schrijven."
        )

    pwa_dir = UITVOER_DIR / PWA_DIR_NAAM
    pwa_dir.mkdir(parents=True, exist_ok=True)
    (pwa_dir / "manifest.json").write_text(PWA_MANIFEST, encoding="utf-8")
    (pwa_dir / "service-worker.js").write_text(PWA_SERVICE_WORKER, encoding="utf-8")
    (pwa_dir / "icon.svg").write_text(PWA_ICON_SVG, encoding="utf-8")
    (pwa_dir / "favicon.svg").write_text(PWA_FAVICON_SVG, encoding="utf-8")
    _write_png_icon(pwa_dir / "apple-touch-icon.png", 180)
    _write_png_icon(pwa_dir / "icon-512.png", 512)

    if password:
        beveiligd = beveilig_html(_body(rijen, meta, True), password)
        (pwa_dir / "index.html").write_text(beveiligd, encoding="utf-8")
        return pwa_dir

    # Terugval (lokaal, zonder wachtwoord): onversleuteld.
    print("[rapport] WAARSCHUWING: geen funda_pwa_password.txt gevonden, PWA wordt onversleuteld geschreven!")
    (pwa_dir / "index.html").write_text(render_html(rijen, meta, is_pwa=True), encoding="utf-8")
    return pwa_dir
