"""
Rapport-module voor funda_zoek.py.

Analyseert woningen op betaalbaarheid en pros/cons en genereert een
markdown rapport in dezelfde map.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
import html as html_lib
from collections import Counter
from pathlib import Path
from datetime import datetime

# === Financiele profiel — laad uit gitignored config bestand ===

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

BRUTO_JAAR = _PERSONAL["bruto_jaar"]
EIGEN_INLEG = _PERSONAL["eigen_inleg"]
DUO_MAANDLAST = _PERSONAL["duo_maandlast"]
LEEFTIJD = _PERSONAL["leeftijd"]

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


def _nu_nl() -> str:
    dt = datetime.now(_TZ_NL) if _TZ_NL else datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M")

# === Hypotheek-config (handmatig updaten) ===

# NHG-toetsrente: gebruikt door banken om je MAX HYPOTHEEK te berekenen.
# Ligt hoger dan markt om buffer te creeren tegen rentestijging.
# Bron: NIBUD/Tijdelijke regeling hypothecair krediet, jaarlijks publicatie.
# Update jaarlijks in januari.
NHG_TOETSRENTE = 0.045            # 2026 schatting

# Markt-rente voor MAANDLASTEN-berekening (wat je echt betaalt).
# Bron: hypotheek-rentes.nl, ING, Rabo. Update maandelijks.
NHG_RENTE_30JR = 0.034            # mei 2026
NHG_RENTE_30JR_AB = 0.0335        # iets lager bij energiezuinig (label A/B)

NHG_PREMIE_PCT = 0.004            # eenmalig
NHG_GRENS = 470_000               # NHG 2026 grens
NHG_GRENS_ENERGIEZUINIG = 498_200 # NHG 2026 grens met energiebesparing
ENERGIE_BONUS_HYPOTHEEK = 20_000  # extra leenruimte bij label A/B (NIBUD 2026 schatting)

# NIBUD woonquote-tabel 2026 (financieringslastpercentages, vereenvoudigd).
# Bron: NIBUD jaarlijks. Voor exacte tabel zie Staatscourant.
# Tuple: (max_bruto_inkomen, woonquote als fractie van bruto).
WOONQUOTE_TABEL = [
    (40_000, 0.220),
    (50_000, 0.240),
    (60_000, 0.255),
    (70_000, 0.270),
    (80_000, 0.280),
    (100_000, 0.300),
    (float("inf"), 0.310),
]


def woonquote_voor(bruto: float) -> float:
    for max_ink, pct in WOONQUOTE_TABEL:
        if bruto <= max_ink:
            return pct
    return WOONQUOTE_TABEL[-1][1]


def max_hypotheek_nibud(
    bruto: float,
    toetsrente: float = NHG_TOETSRENTE,
    schuld_maandlast: float = 0,
    energiezuinig: bool = False,
) -> int:
    """Bereken max hypotheek volgens NIBUD-systematiek (annuiteit, 30 jaar)."""
    quote = woonquote_voor(bruto)
    max_woonlast_md = bruto * quote / 12
    # Brutering schulden (factor 1.2 ~ correctie voor netto-bruto effect)
    correctie_md = schuld_maandlast * 1.2
    netto_capaciteit = max(0.0, max_woonlast_md - correctie_md)
    r_md = toetsrente / 12
    n = 360
    annuiteit_factor = r_md / (1 - (1 + r_md) ** -n) if r_md > 0 else 1 / n
    hypotheek = netto_capaciteit / annuiteit_factor
    if energiezuinig:
        hypotheek += ENERGIE_BONUS_HYPOTHEEK
    return int(hypotheek)


# Bereken max hypotheek dynamisch op basis van NIBUD-tabel.
MAX_HYPOTHEEK = max_hypotheek_nibud(BRUTO_JAAR, NHG_TOETSRENTE, DUO_MAANDLAST, energiezuinig=False)
MAX_HYPOTHEEK_AB = max_hypotheek_nibud(BRUTO_JAAR, NHG_TOETSRENTE, DUO_MAANDLAST, energiezuinig=True)

# Schatting energiekosten per maand voor appartement, ruwe vuistregel.
# Geschaald naar 75 m2 als basis.
ENERGIE_PER_LABEL = {
    "A+++": 70, "A++": 80, "A+": 90, "A": 100, "B": 130,
    "C": 170, "D": 220, "E": 280, "F": 340, "G": 400,
    "?": 280, "unknown": 280, None: 280,
}

# Vuistregels overige kosten per maand
SERVICEKOSTEN_DEFAULT = 175       # als VvE niet uit beschrijving te halen is
WOZ_VERZEKERING = 100             # OZB + opstal/inboedel grof gemiddeld
ONDERHOUDSRESERVE = 100           # 1% per jaar / 12 op woningwaarde, ruw

# Norm: maandlasten max 35% van bruto maandinkomen voor comfort
NORM_MAANDLAST_PCT = 0.33

# Werk-postcodes (huidig en toekomstig) — uit gitignored config.
WERK_POSTCODES = [tuple(item) for item in _PERSONAL["werk_postcodes"]]
WERK_CACHE = Path(__file__).parent / "funda_werk_coords.json"
ENRICHMENT_CACHE = Path(__file__).parent / "funda_enrichment_cache.json"
USER_AGENT = "funda-tracker-remco/1.0 (persoonlijk gebruik)"


# === Geocoding en routing ===

def lookup_postcode(postcode: str) -> tuple[float, float] | None:
    """Nominatim lookup; geeft (lat, lon) of None terug."""
    q = urllib.parse.quote(f"{postcode}, Nederland")
    url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&countrycodes=nl"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    for pc, _ in WERK_POSTCODES:
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
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


def load_enrichment_cache() -> dict:
    if ENRICHMENT_CACHE.exists():
        try:
            data = json.loads(ENRICHMENT_CACHE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"price_history": {}, "market_insights": {}, "broker": {}}


def save_enrichment_cache(cache: dict) -> None:
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
    if diff_pct is None:
        market_score = None
        market_label = None
    elif diff_pct <= -10:
        market_score = 8.5
        market_label = "sterk onder wijkprijs"
    elif diff_pct <= -3:
        market_score = 7.0
        market_label = "gunstig"
    elif diff_pct < 8:
        market_score = 5.5
        market_label = "marktconform"
    elif diff_pct < 15:
        market_score = 3.5
        market_label = "duur"
    else:
        market_score = 2.0
        market_label = "zeer duur"
    return {
        "price_per_m2": ppm,
        "avg_asking_price_per_m2": avg,
        "diff_pct": diff_pct,
        "market_score": market_score,
        "market_label": market_label,
        "insights": insights or {},
    }


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
                try:
                    return f.get_price_history(listing_obj)
                except Exception:
                    if not url:
                        raise
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
        market_raw = fetch_with_cache(
            cache,
            "market_insights",
            _slug_key(city, neighbourhood),
            30,
            lambda: f.get_market_insights(city, neighbourhood),
        )
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


# === Extra signalen voor rapportkaarten ===

def _nl_getal(value: int | float | None) -> str:
    """Geheel getal met Nederlandse duizendscheiding (punt): 289000 -> '289.000'."""
    return f"{int(value or 0):,}".replace(",", ".")


def _fmt_eur(value: int | float | None) -> str:
    return f"€{_nl_getal(value)}"


def _count_value(value) -> int:
    if value in (None, False, ""):
        return 0
    if value is True:
        return 1
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _compact_value(value) -> str:
    if isinstance(value, bool):
        return "ja" if value else "nee"
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value[:2]]
        return ", ".join(parts) + (" ..." if len(value) > 2 else "")
    if isinstance(value, dict):
        parts = [f"{k}: {v}" for k, v in list(value.items())[:2]]
        return ", ".join(parts) + (" ..." if len(value) > 2 else "")
    return str(value)


def structured_signals(d: dict, details: dict | None, enrichment: dict | None) -> list[str]:
    """Compacte signalen uit pyfunda-verrijking en gestructureerde advertentievelden."""
    enrichment = enrichment or {}
    details = details or {}
    signals: list[str] = []

    market = enrichment.get("market") or {}
    ppm = market.get("price_per_m2") or (d.get("price") // d.get("living_area") if d.get("price") and d.get("living_area") else None)
    wijk_avg = market.get("avg_asking_price_per_m2")
    diff_pct = market.get("diff_pct")
    market_score = market.get("market_score")
    market_label = market.get("market_label")
    if ppm and wijk_avg and diff_pct is not None:
        prefix = f"Marktscore {market_score:.1f}/10 ({market_label}) | " if market_score is not None and market_label else ""
        signals.append(f"{prefix}Wijkprijs: {_fmt_eur(ppm)}/m2 vs {_fmt_eur(wijk_avg)}/m2 ({diff_pct:+.1f}%)")
    elif ppm:
        signals.append(f"Vraagprijs per m2: {_fmt_eur(ppm)}/m2")
    insights = market.get("insights") or {}
    if insights.get("inhabitants") or insights.get("families_with_children_pct") is not None:
        buurt_bits = []
        if insights.get("inhabitants"):
            try:
                buurt_bits.append(f"{int(insights['inhabitants']):,} inwoners")
            except (TypeError, ValueError):
                pass
        if insights.get("families_with_children_pct") is not None:
            try:
                buurt_bits.append(f"{float(insights['families_with_children_pct']):.0f}% gezinnen met kinderen")
            except (TypeError, ValueError):
                pass
        if buurt_bits:
            signals.append("Buurt: " + ", ".join(buurt_bits))

    price_history = enrichment.get("price_history") or {}
    if price_history.get("highest_asking") and price_history.get("drop_from_high"):
        signals.append(
            f"Prijsverloop: hoogste vraagprijs {_fmt_eur(price_history['highest_asking'])}, "
            f"nu -{_fmt_eur(price_history['drop_from_high'])}"
        )
    latest_woz = price_history.get("latest_woz") or {}
    if isinstance(latest_woz, dict) and latest_woz.get("price"):
        date = f" ({latest_woz.get('date')})" if latest_woz.get("date") else ""
        signals.append(f"Laatste WOZ: {_fmt_eur(latest_woz['price'])}{date}")
    latest_sold = price_history.get("latest_sold") or {}
    if isinstance(latest_sold, dict) and latest_sold.get("price"):
        date = f" ({latest_sold.get('date')})" if latest_sold.get("date") else ""
        signals.append(f"Eerder verkocht: {_fmt_eur(latest_sold['price'])}{date}")

    broker = enrichment.get("broker") or {}
    broker_bits = []
    if broker.get("name"):
        broker_bits.append(str(broker["name"]))
    if broker.get("review_average") is not None and broker.get("review_count"):
        broker_bits.append(f"{broker['review_average']:.1f}/10 uit {broker['review_count']} reviews")
    activity = []
    if broker.get("for_sale_count"):
        activity.append(f"{broker['for_sale_count']} te koop")
    if broker.get("sold_count"):
        activity.append(f"{broker['sold_count']} verkocht")
    if activity:
        broker_bits.append(", ".join(activity))
    if broker_bits:
        signals.append("Makelaar: " + " | ".join(broker_bits))

    offered_since = details.get("offered_since")
    acceptance = details.get("acceptance")
    if offered_since or acceptance:
        parts = []
        if offered_since:
            parts.append(f"sinds {_compact_value(offered_since)}")
        if acceptance:
            parts.append(f"aanvaarding {_compact_value(acceptance)}")
        signals.append("Advertentie: " + ", ".join(parts))

    views = details.get("views")
    saves = details.get("saves")
    if views or saves:
        parts = []
        if views:
            parts.append(f"{_compact_value(views)} views")
        if saves:
            parts.append(f"{_compact_value(saves)} bewaard")
        signals.append("Interesse: " + ", ".join(parts))

    media = []
    photo_count = _count_value(details.get("photo_count") or details.get("photo_urls"))
    floorplans = _count_value(details.get("floorplans") or details.get("floorplan_urls"))
    videos = _count_value(details.get("videos") or details.get("video_urls"))
    photos_360 = _count_value(details.get("photos_360"))
    if photo_count:
        media.append(f"{photo_count} foto's")
    if floorplans:
        media.append(f"{floorplans} plattegrond(en)")
    if videos:
        media.append(f"{videos} video(s)")
    if photos_360:
        media.append(f"{photos_360} 360-foto(s)")
    if media:
        signals.append("Media: " + ", ".join(media))
    if details.get("brochure_url"):
        signals.append("Brochure beschikbaar")
    if details.get("open_house"):
        signals.append(f"Open huis: {_compact_value(details.get('open_house'))}")
    if details.get("is_auction"):
        signals.append("Prijsconditie: veiling/tender")

    return signals[:12]


# === Balkon-oriëntatie ===

SUN_DIRECTIONS = {
    "zuidwest": "Zuidwest",
    "zuidoost": "Zuidoost",
    "noordwest": "Noordwest",
    "noordoost": "Noordoost",
    "zuid": "Zuid",
    "noord": "Noord",
    "west": "West",
    "oost": "Oost",
}
SUN_FAVORABLE = {"Zuid", "Zuidwest", "Zuidoost", "West"}
SUN_NEUTRAL = {"Oost"}
SUN_BAD = {"Noord", "Noordwest", "Noordoost"}


def parse_energielabel(beschrijving: str) -> str | None:
    """Vind energielabel in beschrijving als fallback wanneer Funda het veld leeg laat."""
    if not beschrijving:
        return None
    txt = beschrijving.lower()
    # Patronen: "energielabel A", "energielabel: A+", "energy label B", "label A++"
    patronen = [
        r"\benergie\s*label\s*[:\-]?\s*([a-g])(\+{0,3})\b",
        r"\benergy\s*label\s*[:\-]?\s*([a-g])(\+{0,3})\b",
        r"\benergieklasse\s*[:\-]?\s*([a-g])(\+{0,3})\b",
        r"\bdefinitief\s+energielabel\s*[:\-]?\s*([a-g])(\+{0,3})\b",
        r"\blabel\s+([a-g])(\+{0,3})\b",
    ]
    for pat in patronen:
        m = re.search(pat, txt)
        if m:
            letter = m.group(1).upper()
            plus = m.group(2) or ""
            return f"{letter}{plus}"
    return None


def parse_balkon_orientatie(beschrijving: str) -> str | None:
    """Vind richting die het dichtst bij 'balkon' staat in de tekst."""
    txt = (beschrijving or "").lower()
    if not txt:
        return None
    # Zoek vensters rond mentions van balkon/terras/loggia
    voor_keys = ["balkon", "terras", "loggia", "tuin"]
    pat_anchor = r"\b(" + "|".join(voor_keys) + r")\b"
    voor_woorden = list(re.finditer(pat_anchor, txt))
    if not voor_woorden:
        return None
    # Sorteer richtingen op lengte (langste eerst om "zuidwest" voor "zuid" te pakken)
    richtingen_sorted = sorted(SUN_DIRECTIONS.keys(), key=len, reverse=True)

    for m in voor_woorden:
        start = max(0, m.start() - 80)
        end = min(len(txt), m.end() + 80)
        window = txt[start:end]
        for richting in richtingen_sorted:
            if re.search(rf"\b{richting}(?:en)?\b", window):
                return SUN_DIRECTIONS[richting]
    return None


# === Helpers ===

def annuiteit_maand(hoofdsom: int, jaar_rente: float, jaren: int = 30) -> float:
    if jaar_rente == 0:
        return hoofdsom / (jaren * 12)
    r = jaar_rente / 12
    n = jaren * 12
    return hoofdsom * r / (1 - (1 + r) ** -n)


def energie_per_maand(label: str | None, m2: int) -> int:
    base = ENERGIE_PER_LABEL.get(label, 280)
    return int(base * (max(m2, 40) / 75))


def parse_servicekosten(beschrijving: str) -> int | None:
    """Probeer VvE/servicekosten uit beschrijving te halen."""
    if not beschrijving:
        return None
    txt = beschrijving.replace(".", "").replace(",", ".")
    patronen = [
        r"servicekosten[^0-9]{0,40}(\d{2,4})\s*(?:euro|eur|p/m|per maand|/maand|pm)?",
        r"v\.?v\.?e\.?\s*(?:bijdrage)?[^0-9]{0,40}(\d{2,4})\s*(?:euro|eur|p/m|per maand|/maand|pm)?",
        r"€\s*(\d{2,4})\s*(?:per maand|p/m|/maand|pm)\s*(?:aan)?\s*(?:service|vve)",
    ]
    for p in patronen:
        m = re.search(p, txt, re.IGNORECASE)
        if m:
            try:
                bedrag = int(float(m.group(1)))
                if 30 <= bedrag <= 800:
                    return bedrag
            except ValueError:
                continue
    return None


HUIDIG_JAAR = datetime.now().year


def parse_erfpacht(beschrijving: str) -> dict:
    """Gestructureerd erfpacht-info. Returns dict met status, label, risico, canon, eind, details."""
    info = {
        "status": "onbekend", "label": "Niet vermeld", "risico": "onbekend",
        "canon_jaar": None, "afkoop_eind": None, "type": None, "details": [],
    }
    if not beschrijving:
        return info

    txt = beschrijving.lower()

    # Eigen grond
    if re.search(r"\beigen\s+grond\b", txt):
        info.update({"status": "eigen", "label": "Eigen grond", "risico": "geen"})
        return info

    if "erfpacht" not in txt:
        return info

    # Type: particulier of gemeentelijk
    if "particulier" in txt and "erfpacht" in txt:
        info["type"] = "particulier"
        info["details"].append("Particuliere erfpacht (vaak risicovoller dan gemeentelijk)")
    elif re.search(r"gemeente\w*\s+\w*\s*erfpacht|erfpacht\s+(?:van\s+)?(?:de\s+)?gemeente", txt):
        info["type"] = "gemeentelijk"

    eeuwigdurend = "eeuwigdurend" in txt
    voortdurend = "voortdurend" in txt and "eeuwigdurend" not in txt
    afgekocht = "afgekocht" in txt or re.search(r"\bafkoop\b", txt)

    # Canon bedrag
    canon_match = re.search(r"canon[^0-9€]{0,40}€?\s*([0-9]{1,5})(?:[.,]\d{2})?", txt)
    if canon_match:
        try:
            bedrag = int(canon_match.group(1))
            if 50 <= bedrag <= 20000:
                info["canon_jaar"] = bedrag
        except ValueError:
            pass

    # Einddatum afkoop
    eind_match = re.search(r"(?:afgekocht|afkoop|tot)[^.]{0,80}?\b(20\d{2})\b", txt)
    if eind_match:
        try:
            jaar = int(eind_match.group(1))
            if jaar > HUIDIG_JAAR:
                info["afkoop_eind"] = jaar
        except ValueError:
            pass

    # Bouw status + risico
    if eeuwigdurend and afgekocht and not info["afkoop_eind"]:
        info.update({"status": "afgekocht_eeuwigdurend", "label": "Erfpacht eeuwigdurend afgekocht", "risico": "laag"})
    elif afgekocht and info["afkoop_eind"]:
        jaren = info["afkoop_eind"] - HUIDIG_JAAR
        info["status"] = "afgekocht_tijdelijk"
        info["label"] = f"Erfpacht afgekocht tot {info['afkoop_eind']} ({jaren} jaar)"
        if jaren < 10:
            info["risico"] = "hoog"
            info["details"].append("Afkoop loopt binnen 10 jaar af, herziening kan duur uitpakken")
        elif jaren < 25:
            info["risico"] = "matig"
            info["details"].append("Op middellange termijn herziening van canon")
        else:
            info["risico"] = "laag"
    elif afgekocht:
        info.update({"status": "afgekocht_onbekend", "label": "Erfpacht afgekocht (looptijd niet vermeld)", "risico": "matig"})
        info["details"].append("Vraag akte op om looptijd te checken")
    elif eeuwigdurend:
        info["status"] = "lopend_eeuwigdurend"
        info["label"] = "Eeuwigdurende erfpacht, canon NIET afgekocht"
        info["risico"] = "matig"
        if info["canon_jaar"]:
            info["details"].append(f"Canon ~€{info['canon_jaar']}/jaar (verlaagt leencapaciteit)")
        else:
            info["details"].append("Canon-bedrag niet vermeld, opvragen")
    elif voortdurend:
        info.update({"status": "voortdurend", "label": "Voortdurende erfpacht (loopt af)", "risico": "hoog"})
        info["details"].append("Bij heruitgifte kan canon flink stijgen")
    else:
        info["status"] = "lopend"
        info["label"] = "Erfpacht (looptijd en canon onbekend)"
        info["risico"] = "matig"
        if info["canon_jaar"]:
            info["details"].append(f"Canon ~€{info['canon_jaar']}/jaar")

    return info


def kosten_koper(hoofdsom: int) -> int:
    """Geen overdrachtsbelasting (starter < 35j). Schat overige kosten."""
    notaris = 1_500
    taxatie = 700
    advies = 3_000
    nhg_premie = int(hoofdsom * NHG_PREMIE_PCT)
    keuring = 450
    bankgarantie = 350
    return notaris + taxatie + advies + nhg_premie + keuring + bankgarantie


def in_max_hypotheek(prijs: int, label: str | None) -> tuple[bool, int]:
    """Past de prijs in max hypotheek? Geeft ook headroom terug."""
    cap = MAX_HYPOTHEEK_AB if label in {"A", "A+", "A++", "A+++", "B"} else MAX_HYPOTHEEK
    return (prijs <= cap, cap - prijs)


# === Pros / cons ===

def pros_cons(d: dict, details: dict | None, beschrijving: str) -> tuple[list[str], list[str]]:
    pros, cons = [], []

    enrichment = d.get("_enrichment") or {}
    market = enrichment.get("market") or {}
    price_history = enrichment.get("price_history") or {}
    broker = enrichment.get("broker") or {}

    label = d.get("energy_label") or "?"
    m2 = d.get("living_area") or 0
    prijs = d.get("price") or 0
    ppm = prijs // m2 if m2 else 0

    # Energie label
    if label in {"A", "A+", "A++", "A+++", "B"}:
        pros.append(f"Goed energielabel ({label}) → NHG-energiebonus en lage stookkosten")
    elif label in {"F", "G"}:
        cons.append(f"Slecht energielabel ({label}) → hoge stookkosten en mogelijk verduurzamen nodig")
    elif label in {"?", "unknown", None}:
        cons.append("Energielabel onbekend → onzekerheid over stookkosten")

    # Prijs per m2: wijkbenchmark wint van harde grenzen zodra beschikbaar.
    wijk_avg = market.get("avg_asking_price_per_m2")
    wijk_diff = market.get("diff_pct")
    if ppm and wijk_avg and wijk_diff is not None:
        if wijk_diff <= -8:
            pros.append(f"Scherp t.o.v. wijkgemiddelde (€{ppm}/m2 vs €{wijk_avg}/m2, {wijk_diff:+.1f}%)")
        elif wijk_diff >= 10:
            cons.append(f"Duur t.o.v. wijkgemiddelde (€{ppm}/m2 vs €{wijk_avg}/m2, {wijk_diff:+.1f}%)")
    elif ppm and ppm < 3700:
        pros.append(f"Scherpe prijs per m2 (€{ppm}/m2)")
    elif ppm and ppm > 4500:
        cons.append(f"Hoge prijs per m2 (€{ppm}/m2)")

    # Historische prijsdata via Walter Living / pyfunda.
    hist_drop = price_history.get("drop_from_high") or 0
    if hist_drop >= 5_000:
        pros.append(f"Historisch vraagprijsvoordeel: -€{hist_drop:,} vanaf hoogste vraagprijs ({price_history.get('drop_pct', 0):.1f}%)")
    latest_woz = price_history.get("latest_woz") or {}
    latest_woz_price = latest_woz.get("price") if isinstance(latest_woz, dict) else None
    if latest_woz_price and prijs:
        boven_woz = (prijs - latest_woz_price) / latest_woz_price * 100
        if boven_woz >= 20:
            cons.append(f"Vraagprijs ruim boven laatste WOZ-indicatie (+{boven_woz:.0f}%)")

    # Oppervlakte
    if m2 >= 80:
        pros.append(f"Ruim ({m2} m2)")
    elif m2 < 65:
        cons.append(f"Klein ({m2} m2)")

    # Buitenruimte: combineer details-booleans met tekstmatch
    txt_low = (beschrijving or "").lower()
    has_balkon = details and details.get("has_balcony") or any(
        w in txt_low for w in ["balkon", "loggia"]
    )
    has_tuin = details and details.get("has_garden") or any(
        w in txt_low for w in ["tuin", "voortuin", "achtertuin"]
    )
    has_dakterras = details and details.get("has_roof_terrace") or "dakterras" in txt_low
    has_terras = "terras" in txt_low or "patio" in txt_low or "veranda" in txt_low
    if has_tuin:
        pros.append("Tuin")
    if has_dakterras:
        pros.append("Dakterras")
    if has_balkon and not has_tuin:
        pros.append("Balkon")
    if has_terras and not (has_tuin or has_dakterras or has_balkon):
        pros.append("Terras")
    if not (has_balkon or has_tuin or has_dakterras or has_terras):
        cons.append("Geen buitenruimte gedetecteerd (check Funda zelf, false negatives komen voor)")
    else:
        # Balkon-orientatie zon-check
        orient = parse_balkon_orientatie(beschrijving)
        if orient in SUN_FAVORABLE:
            pros.append(f"Buitenruimte op zonkant ({orient})")
        elif orient in SUN_BAD:
            cons.append(f"Buitenruimte op schaduwkant ({orient})")
        elif orient in SUN_NEUTRAL:
            pros.append(f"Buitenruimte op {orient} (ochtendzon)")
    if details:
        if details.get("is_auction"):
            cons.append("Veiling/tender-achtige prijsconditie")
        if details.get("open_house"):
            pros.append("Open huis gepland")
        if details.get("has_solar_panels"):
            pros.append("Zonnepanelen")
        if details.get("has_heat_pump"):
            pros.append("Warmtepomp")
        if details.get("has_parking_on_site") or details.get("has_parking_enclosed"):
            pros.append("Eigen parkeerplek")
        if details.get("is_monument"):
            cons.append("Monument → onderhoud lastig en duur")
        if details.get("is_fixer_upper"):
            cons.append("Kluswoning → flink budget voor verbouwing nodig")
        bouwjaar = details.get("construction_year")
        if bouwjaar and bouwjaar < 1920:
            cons.append(f"Heel oud ({bouwjaar}) → hogere onderhoudskans, check fundering en kozijnen")
        elif bouwjaar and bouwjaar > 2000:
            pros.append(f"Modern bouwjaar ({bouwjaar})")

    # Makelaarssignalen.
    review_avg = broker.get("review_average")
    review_count = broker.get("review_count") or 0
    if review_avg is not None and review_count >= 10:
        if review_avg >= 9.0:
            pros.append(f"Makelaar goed beoordeeld ({review_avg:.1f}/10, {review_count} reviews)")
        elif review_avg < 8.3:
            cons.append(f"Makelaar relatief laag beoordeeld ({review_avg:.1f}/10, {review_count} reviews)")

    # Erfpacht (gestructureerde analyse)
    erf = parse_erfpacht(beschrijving)
    if erf["status"] == "eigen":
        pros.append("Eigen grond")
    elif erf["status"] == "afgekocht_eeuwigdurend":
        pros.append("Erfpacht eeuwigdurend afgekocht (gunstig)")
    elif erf["risico"] == "hoog":
        cons.append(f"{erf['label']} - HOOG RISICO" + (": " + "; ".join(erf["details"]) if erf["details"] else ""))
    elif erf["risico"] == "matig":
        cons.append(f"{erf['label']}" + (" - " + "; ".join(erf["details"]) if erf["details"] else ""))
    elif erf["status"] != "onbekend":
        cons.append(erf["label"])

    # Servicekosten
    sk = parse_servicekosten(beschrijving)
    if sk and sk > 250:
        cons.append(f"Hoge servicekosten (€{sk}/m)")
    elif sk and sk < 100:
        pros.append(f"Lage servicekosten (€{sk}/m)")

    return pros, cons


# === Maandlasten ===

def bereken_maandlasten(prijs: int, label: str | None, m2: int, beschrijving: str, canon_jaar: int | None = None) -> dict:
    rente = NHG_RENTE_30JR_AB if label in {"A", "B"} else NHG_RENTE_30JR
    hyp = annuiteit_maand(prijs, rente)
    sk = parse_servicekosten(beschrijving) or SERVICEKOSTEN_DEFAULT
    energie = energie_per_maand(label, m2)
    canon_maand = (canon_jaar / 12) if canon_jaar else 0
    totaal = hyp + sk + WOZ_VERZEKERING + ONDERHOUDSRESERVE + energie + canon_maand
    return {
        "hypotheek": int(hyp),
        "servicekosten": int(sk),
        "woz_verzekering": WOZ_VERZEKERING,
        "onderhoud": ONDERHOUDSRESERVE,
        "energie": int(energie),
        "canon": int(canon_maand),
        "canon_jaar": canon_jaar or 0,
        "totaal": int(totaal),
        "rente_pct": rente,
    }


# === Score voor ranking ===

def score(d: dict, lasten: dict, pros: list, cons: list, in_max: bool) -> float:
    """Hoger is beter."""
    s = 0.0
    s += 5 if in_max else -10
    s += len(pros) * 2
    s -= len(cons) * 2
    # Bonus op headroom in maandlast
    bruto_maand = BRUTO_JAAR / 12
    norm = bruto_maand * NORM_MAANDLAST_PCT
    if lasten["totaal"] < norm:
        s += (norm - lasten["totaal"]) / 50
    else:
        s -= (lasten["totaal"] - norm) / 30
    return s


# === Markdown rapport ===

def genereer_rapport(f, woningen: list[dict], nieuw_ids: set[str] | None = None) -> Path:
    """Loopt langs woningen, doet detail-call en bouwt markdown + HTML rapport."""
    nieuw_ids = nieuw_ids or set()
    werk_coords = get_werk_coords()
    enrichment_cache = load_enrichment_cache()
    print(f"\n[rapport] Detail-call voor {len(woningen)} woningen, werk-coords: {len(werk_coords)} adressen.")
    rijen = []
    for d in woningen:
        lid = d.get("global_id") or d.get("listing_id")
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        details = None
        listing_obj = None
        beschrijving = ""
        try:
            listing_obj = f.get_listing(lid)
            if hasattr(listing_obj, "data"):
                details = listing_obj.data
                beschrijving = str(details.get("description") or "")
            time.sleep(0.5)
        except Exception as exc:
            print(f"  Detail fout {lid}: {exc}")
        enrichment = verrijk_woning(f, d, listing_obj, enrichment_cache)
        d["_enrichment"] = enrichment
        rij = bouw_rij(d, details, beschrijving)
        rij["is_nieuw"] = sleutel in nieuw_ids
        rij["foto_url"] = (details.get("photo_urls") or [None])[0] if details else None

        # Route afstand naar werk-locaties.
        rij["routes"] = []
        wlat = details.get("latitude") if details else None
        wlon = details.get("longitude") if details else None
        rij["lat"] = wlat
        rij["lon"] = wlon
        if wlat and wlon and werk_coords:
            for pc, label in WERK_POSTCODES:
                if pc in werk_coords:
                    plat, plon = werk_coords[pc]
                    km, soort = afstand_km(wlat, wlon, plat, plon)
                    rij["routes"].append({"postcode": pc, "label": label, "km": km, "soort": soort})

        rijen.append(rij)

    save_enrichment_cache(enrichment_cache)

    # Sorteer op score (hoog naar laag)
    rijen.sort(key=lambda r: r["score"], reverse=True)

    # Schrijf markdown (backwards compat)
    pad_md = Path(__file__).parent / "funda_rapport.md"
    md = render_markdown(rijen)
    pad_md.write_text(md, encoding="utf-8")

    # Schrijf HTML
    pad_html = Path(__file__).parent / "funda_rapport.html"
    html = render_html(rijen, werk_coords=werk_coords)
    pad_html.write_text(html, encoding="utf-8")

    # Schrijf PWA assets (manifest, sw, icon, index.html)
    pwa_dir = schrijf_pwa_assets(rijen, werk_coords=werk_coords)

    print(f"[rapport] Geschreven: {pad_md.name}, {pad_html.name}, en {pwa_dir.name}/")
    return pad_html


def bouw_rij(d: dict, details: dict | None, beschrijving: str) -> dict:
    label = d.get("energy_label") or "?"
    # Fallback: zoek label in beschrijving als Funda het veld leeg laat.
    if label in {"?", "unknown", None, ""}:
        gevonden = parse_energielabel(beschrijving)
        if gevonden:
            label = gevonden
            d["energy_label"] = label  # zodat pros_cons ook de fallback ziet
    prijs = d.get("price") or 0
    m2 = d.get("living_area") or 0
    pros, cons = pros_cons(d, details, beschrijving)
    signals = structured_signals(d, details, d.get("_enrichment") or {})
    erf_info = parse_erfpacht(beschrijving)
    lasten = bereken_maandlasten(prijs, label, m2, beschrijving, canon_jaar=erf_info.get("canon_jaar"))
    in_max, headroom = in_max_hypotheek(prijs, label)
    kk = kosten_koper(prijs)
    inleg_tekort = max(0, kk - EIGEN_INLEG)

    # Bepaal budget-status
    norm = (BRUTO_JAAR / 12) * NORM_MAANDLAST_PCT
    if not in_max:
        budget = "BOVEN MAX HYPOTHEEK"
    elif lasten["totaal"] > norm:
        budget = f"MAANDLAST BOVEN NORM (€{int(lasten['totaal']-norm)} te hoog)"
    elif inleg_tekort > 5_000:
        budget = "EIGEN GELD TEKORT"
    elif inleg_tekort > 0:
        budget = "EIGEN GELD KRAP"
    else:
        budget = "PAST"

    # Prijs-/looptijd-tracking (aangehangen door funda_zoek.py).
    track = d.get("_track") or {}
    basis_score = score(d, lasten, pros, cons, in_max)
    if track.get("gedaald"):
        basis_score += 4  # prijsdaling = kans, hoger in lijst
    if track.get("dagen", 0) >= 90:
        basis_score += 2  # lang te koop = onderhandelruimte

    return {
        "d": d,
        "details": details,
        "label": label,
        "prijs": prijs,
        "m2": m2,
        "pros": pros,
        "cons": cons,
        "signals": signals,
        "lasten": lasten,
        "in_max": in_max,
        "headroom": headroom,
        "kk": kk,
        "inleg_tekort": inleg_tekort,
        "budget": budget,
        "track": track,
        "score": basis_score,
        "erfpacht": erf_info,
    }


def render_markdown(rijen: list[dict]) -> str:
    nu = _nu_nl()
    bruto_maand = BRUTO_JAAR / 12
    norm = int(bruto_maand * NORM_MAANDLAST_PCT)

    lines: list[str] = []
    lines.append(f"# Funda rapport — {nu}")
    lines.append("")
    lines.append("## Profiel")
    lines.append("")
    lines.append(f"- Bruto jaarinkomen: € {BRUTO_JAAR:,}")
    lines.append(f"- Eigen inleg beschikbaar: € {EIGEN_INLEG:,} (rest = buffer)")
    lines.append(f"- Max hypotheek regulier: € {MAX_HYPOTHEEK:,} (label A/B: € {MAX_HYPOTHEEK_AB:,})")
    lines.append(f"- Norm maandlast ({int(NORM_MAANDLAST_PCT*100)}% bruto maand): € {norm:,}")
    lines.append(f"- NHG: ja (premie 0,4% eenmalig, rentekorting ~0,5%-pt)")
    lines.append(f"- Startersvrijstelling overdrachtsbelasting: ja (geldig tot 1 april 2029)")
    lines.append("")

    if not rijen:
        lines.append("Geen woningen om te analyseren.")
        return "\n".join(lines)

    # Top 5
    lines.append("## Top 5")
    lines.append("")
    lines.append("| # | Adres | Prijs | m2 | Label | Maandlast | Budget |")
    lines.append("|---|-------|------:|---:|:-----:|----------:|:-------|")
    for i, r in enumerate(rijen[:5], 1):
        d = r["d"]
        lines.append(
            f"| {i} | {d.get('title')} | € {r['prijs']:,} | {r['m2']} | {r['label']} "
            f"| € {r['lasten']['totaal']:,} | {r['budget']} |"
        )
    lines.append("")

    # Per woning
    lines.append("## Detail per woning")
    lines.append("")
    for i, r in enumerate(rijen, 1):
        d = r["d"]
        url = funda_url(d)

        lines.append(f"### {i}. {d.get('title')} — € {r['prijs']:,}")
        lines.append("")
        lines.append(f"- **Locatie**: {d.get('postcode')} {d.get('city')}, {d.get('neighbourhood')}")
        lines.append(f"- **Oppervlakte**: {r['m2']} m2 ({d.get('rooms') or '?'} kamers, {d.get('bedrooms') or '?'} slaapkamers)")
        lines.append(f"- **Energielabel**: {r['label']}")
        if r['details'] and r['details'].get('construction_year'):
            lines.append(f"- **Bouwjaar**: {r['details']['construction_year']}")
        lines.append(f"- **Funda**: {url}")
        lines.append("")

        if r.get("signals"):
            lines.append("**Extra signalen**")
            for signal in r["signals"]:
                lines.append(f"- {signal}")
            lines.append("")

        # Pros / cons
        if r["pros"]:
            lines.append("**Voordelen**")
            for p in r["pros"]:
                lines.append(f"- {p}")
            lines.append("")
        if r["cons"]:
            lines.append("**Nadelen / aandachtspunten**")
            for c in r["cons"]:
                lines.append(f"- {c}")
            lines.append("")

        # Maandlasten
        l = r["lasten"]
        lines.append("**Maandlasten schatting**")
        lines.append("")
        lines.append("| Component | Bedrag |")
        lines.append("|-----------|-------:|")
        lines.append(f"| Hypotheek (annuiteit 30 jr, NHG @ {l['rente_pct']*100:.2f}%) | € {l['hypotheek']:,} |")
        lines.append(f"| Servicekosten (VvE) | € {l['servicekosten']:,} |")
        lines.append(f"| WOZ + verzekering | € {l['woz_verzekering']:,} |")
        lines.append(f"| Onderhoudsreserve | € {l['onderhoud']:,} |")
        lines.append(f"| Energie (label {r['label']}, {r['m2']} m2) | € {l['energie']:,} |")
        if l.get('canon'):
            lines.append(f"| Erfpachtcanon (€{l['canon_jaar']:,}/jaar) | € {l['canon']:,} |")
        lines.append(f"| **Totaal** | **€ {l['totaal']:,}** |")
        lines.append("")

        # Budget-fit
        lines.append("**Financierbaarheid**")
        if r["in_max"]:
            lines.append(f"- Past in max hypotheek (€ {r['headroom']:,} headroom)")
        else:
            lines.append(f"- BOVEN max hypotheek (€ {-r['headroom']:,} te kort)")
        lines.append(f"- Geschatte kosten koper: € {r['kk']:,} (geen overdrachtsbelasting, starter)")
        if r["inleg_tekort"] > 0:
            lines.append(f"- Eigen inleg tekort: € {r['inleg_tekort']:,} (sparen ~{r['inleg_tekort']//500} maanden bij €500/m)")
        else:
            lines.append(f"- Eigen inleg dekt kosten koper")
        lines.append(f"- Status: **{r['budget']}**")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Voetnoot
    lines.append("## Aannames")
    lines.append("")
    lines.append("- Hypotheek = volledige koopprijs (geen extra eigen geld in stenen).")
    lines.append("- NHG rente schatting mei 2026: 3,40% regulier, 3,35% energiezuinig (label A/B).")
    lines.append("- Servicekosten uit beschrijving geparsed; default € 175 als niet vermeld.")
    lines.append("- Energiekosten ruwe schatting per label, geschaald op m2.")
    lines.append("- Onderhoudsreserve € 100/m (1% per jaar / 12).")
    lines.append("- Geen netto correctie voor hypotheekrenteaftrek.")
    lines.append("")

    return "\n".join(lines)


# === HTML rapport ===

HTML_CSS = """
/* === Makelaarsdossier design system ============================================
   Direction: a Den Haag broker's morning property dossier. Warm sandstone paper,
   ink text, The Hague's heraldic green as the single brand accent, a disciplined
   semantic ramp (green = fits budget, amber = tight/new, brick-red = over budget).
   Depth strategy: borders-first. Shadow is reserved for true overlays only
   (sticky topbar, map popups, lock screen). Serif display + tabular euro figures.
   ============================================================================ */
:root {
  /* Surfaces -- warm off-white paper, insets slightly darker than surroundings */
  --paper: #f3efe6;
  --surface: #fbf9f3;
  --surface-2: #f0ebdf;
  --line: #e3ddcd;
  --line-strong: #d3cbb6;

  /* Ink -- four warm text levels: primary / secondary / meta / disabled */
  --ink: #22271d;
  --ink-2: #4d5244;
  --muted: #6b6b5c;
  --faint: #9d9a89;

  /* Brand -- The Hague heraldic green (identity + primary action) */
  --brand: #1f6b4a;
  --brand-deep: #154c34;
  --brand-tint: #e6efe6;

  /* Semantic status (desaturated, used ONLY for state) */
  --good: #1f6b4a;        --good-tint: #e2efe4;   --good-ink: #14512f;
  --warn: #9a5a23;        --warn-tint: #f5e9d6;   --warn-ink: #7a4413;
  --alert: #9c3724;       --alert-tint: #f5e1db;  --alert-ink: #842c1c;
  --gold: #b3842e;        --gold-tint: #f1e7cd;   --gold-ink: #6b4d12;

  /* Elevation -- overlays only */
  --shadow-overlay: 0 8px 24px rgba(34,39,29,.14);
  --shadow-pop: 0 16px 40px rgba(34,39,29,.22);

  /* Concentric radius scale */
  --r-xs: 5px;
  --r-sm: 7px;
  --r-md: 10px;
  --r-lg: 14px;

  /* Type */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  --motion-ease: cubic-bezier(0.23, 1, 0.32, 1);
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--paper); -webkit-text-size-adjust: 100%; }
body {
  min-height: 100%;
  font-family: var(--font-sans);
  margin: 0;
  padding: 0 0 calc(42px + env(safe-area-inset-bottom));
  background: var(--paper);
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  overflow-x: hidden;
}
a { color: var(--brand); }
button, input, textarea, select { font: inherit; }
:where(a, button, input, textarea, [tabindex]):focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
  border-radius: var(--r-xs);
}
.container { width: min(1160px, 100%); margin: 0 auto; padding: 22px 18px 0; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 700;
  padding-top: env(safe-area-inset-top);
  background: var(--brand-deep);
  color: #fff;
  box-shadow: var(--shadow-overlay);
}
.topbar-inner {
  width: min(1160px, 100%);
  height: 58px;
  margin: 0 auto;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
  color: #fff;
  text-decoration: none;
  font-family: var(--font-serif);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: .01em;
}
.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  background: var(--surface);
  color: var(--brand-deep);
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.5);
}
.brand-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 40px;
  padding: 0 15px;
  border-radius: var(--r-sm);
  background: rgba(255,255,255,.12);
  color: #fff;
  border: 1px solid rgba(255,255,255,.34);
  text-decoration: none;
  font-size: 14px;
  font-weight: 650;
  white-space: nowrap;
  transition: background .14s var(--motion-ease);
}
.refresh-btn:hover { background: rgba(255,255,255,.22); }
.refresh-btn:active { transform: scale(.97); }

h1, h2, h3 { font-family: var(--font-serif); letter-spacing: 0; text-wrap: balance; }
h1 { margin: 0 0 6px; font-size: clamp(26px, 3vw, 35px); line-height: 1.06; font-weight: 700; }
h2 { margin: 0; font-size: 23px; line-height: 1.18; font-weight: 700; }
.subtitle { color: var(--muted); font-size: 14px; font-family: var(--font-sans); }

.profile {
  display: grid;
  grid-template-columns: minmax(260px, .9fr) minmax(0, 1.25fr);
  gap: 20px;
  align-items: stretch;
  padding: 22px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.profile-intro {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
}
.profile-kicker {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 7px;
  padding: 5px 9px;
  border-radius: var(--r-xs);
  background: var(--brand-tint);
  color: var(--brand-deep);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
}
.profile dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--line);
}
.profile dl > div {
  min-width: 0;
  padding: 13px 14px;
  background: var(--surface);
}
.profile dt {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.profile dd {
  margin: 5px 0 0;
  color: var(--ink);
  font-size: 15px;
  line-height: 1.28;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.section-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin: 34px 0 14px;
}
.section-note { color: var(--muted); font-size: 13px; margin-top: 3px; }
.count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 9px;
  margin-left: 8px;
  border-radius: 999px;
  background: var(--brand-tint);
  color: var(--brand-deep);
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.map-section { margin-top: 18px; }
.map-wrap {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
#funda-map {
  width: 100%;
  height: min(58vh, 520px);
  min-height: 360px;
  background: #e4e0d3;
  touch-action: pan-x pan-y;
}
.map-legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 14px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  font-size: 13px;
}
.map-legend span { display: inline-flex; align-items: center; gap: 7px; }
.dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--surface); box-shadow: 0 0 0 1px var(--line-strong); }
.dot.new { background: var(--warn); }
.dot.hit { background: var(--brand); }
.dot.work { background: var(--ink-2); }
.map-empty {
  padding: 11px 14px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  font-size: 13px;
}
.notification-section { margin-top: 18px; }
.push-setup {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.push-copy { min-width: 0; display: grid; gap: 4px; font-size: 13px; line-height: 1.4; }
.push-copy strong { color: var(--ink); font-size: 14px; }
.push-copy span { color: var(--muted); }
.push-copy code {
  padding: 1px 5px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 12px;
}
.push-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.push-actions button {
  min-height: 40px;
  padding: 0 14px;
  border-radius: var(--r-sm);
  border: 1px solid var(--brand);
  background: var(--brand);
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  transition: background .14s var(--motion-ease), transform .1s var(--motion-ease);
}
.push-actions button:hover { background: var(--brand-deep); }
.push-actions button:active { transform: scale(.97); }
.push-actions button:disabled { opacity: .6; cursor: wait; }
.push-actions button:nth-child(2) { background: var(--surface); color: var(--brand-deep); border-color: var(--line-strong); }
.push-actions button:nth-child(2):hover { background: var(--surface-2); }
#push-subscription-output {
  grid-column: 1 / -1;
  width: 100%;
  min-height: 118px;
  padding: 11px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.4;
  resize: vertical;
}
.push-status {
  grid-column: 1 / -1;
  min-height: 18px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
}
.leaflet-container { font: inherit; }
.leaflet-control-attribution { font-size: 11px; }
.funda-pin, .work-pin { background: transparent; border: 0; }
.funda-pin span, .work-pin span {
  position: absolute;
  left: 2px;
  top: 0;
  width: 30px;
  height: 30px;
  border: 3px solid var(--surface);
  border-radius: 50% 50% 50% 0;
  background: var(--brand);
  box-shadow: 0 4px 12px rgba(34,39,29,.3);
  transform: rotate(-45deg);
}
.funda-pin span::after, .work-pin span::after {
  content: "";
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: var(--surface);
}
.funda-pin.is-new span { background: var(--warn); }
.work-pin span { background: var(--ink-2); width: 26px; height: 26px; left: 4px; top: 3px; }

.leaflet-popup-content-wrapper {
  border-radius: var(--r-lg);
  padding: 0;
  overflow: hidden;
  box-shadow: var(--shadow-pop);
}
.leaflet-popup-content { margin: 0; width: 272px !important; }
.mp { background: var(--surface); color: var(--ink); }
.mp img { width: 100%; height: 132px; object-fit: cover; display: block; background: var(--surface-2); }
.mp-b { padding: 13px; }
.mp-title { font-family: var(--font-serif); font-weight: 700; font-size: 16px; line-height: 1.22; color: var(--ink); }
.mp-meta { color: var(--muted); font-size: 12px; margin: 3px 0 8px; line-height: 1.4; }
.mp-row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.mp-prijs { font-family: var(--font-serif); font-weight: 700; font-size: 19px; color: var(--ink); font-variant-numeric: tabular-nums; }
.mp-lasten { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.mp-tags { margin: 9px 0; display: flex; gap: 5px; flex-wrap: wrap; }
.mp-signal {
  margin: 9px 0 0;
  padding: 9px;
  border-radius: var(--r-sm);
  background: var(--brand-tint);
  color: var(--brand-deep);
  font-size: 12px;
  line-height: 1.4;
}
.mp-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 11px; }
.mp-actions a, .mp-actions button {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  padding: 8px;
  border-radius: var(--r-sm);
  cursor: pointer;
  text-decoration: none;
  border: 1px solid var(--line-strong);
}
.mp-actions .primary { background: var(--brand); color: #fff; border-color: var(--brand); }
.mp-actions .ghost { background: var(--surface); color: var(--brand-deep); }

.cards { display: grid; gap: 18px; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); }
.card {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--line);
  border-left: 4px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  scroll-margin-top: calc(80px + env(safe-area-inset-top));
  transition: transform .14s var(--motion-ease), box-shadow .14s var(--motion-ease), border-color .14s var(--motion-ease);
}
/* Affordability spine -- the dossier's signature: instant read on whether the
   monthly cost fits the buyer's personal norm. */
.card.budget-PAST { border-left-color: var(--good); }
.card.budget-KRAP, .card.budget-NORM { border-left-color: var(--warn); }
.card.budget-MAX { border-left-color: var(--alert); }
.card:hover { transform: translateY(-2px); box-shadow: var(--shadow-overlay); }
.card.is-new { box-shadow: inset 0 2px 0 var(--warn); }
.card.flash { border-color: var(--warn); box-shadow: 0 0 0 3px var(--warn-tint), var(--shadow-overlay); }
.card-photo-wrap { position: relative; background: var(--surface-2); }
.card-photo { width: 100%; aspect-ratio: 16 / 10; object-fit: cover; display: block; background: var(--surface-2); }
.card-photo::after { content: ""; position: absolute; inset: 0; box-shadow: inset 0 0 0 1px rgba(34,39,29,.08); pointer-events: none; }
.card-photo-placeholder { display: grid; place-items: center; color: var(--faint); font-size: 14px; aspect-ratio: 16 / 10; background: var(--surface-2); }
.card-prijs {
  position: absolute;
  left: 12px;
  bottom: 12px;
  max-width: calc(100% - 24px);
  padding: 7px 11px;
  border-radius: var(--r-sm);
  background: rgba(251,249,243,.96);
  color: var(--ink);
  font-family: var(--font-serif);
  font-weight: 700;
  font-size: 21px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  box-shadow: var(--shadow-overlay);
}
.card-body { padding: 16px; flex: 1; display: flex; flex-direction: column; min-width: 0; }
.card-header { margin-bottom: 8px; min-width: 0; }
.card-title { margin: 0; font-family: var(--font-serif); font-weight: 700; font-size: 18px; line-height: 1.22; overflow-wrap: anywhere; }
.card-title a { color: var(--ink); text-decoration: none; }
.card-title a:hover { color: var(--brand); text-decoration: underline; text-underline-offset: 2px; }
.card-meta { color: var(--muted); font-size: 13px; line-height: 1.4; margin-bottom: 10px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.badge { display: inline-flex; align-items: center; min-height: 22px; padding: 3px 8px; border-radius: var(--r-xs); font-size: 11px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.badge-label { background: var(--surface-2); color: var(--ink-2); box-shadow: inset 0 0 0 1px var(--line); }
.badge-label.A, .badge-label.B { background: var(--good-tint); color: var(--good-ink); box-shadow: none; }
.badge-label.F, .badge-label.G { background: var(--alert-tint); color: var(--alert-ink); box-shadow: none; }
.badge-nhg { background: var(--gold-tint); color: var(--gold-ink); }
.badge-new { background: var(--warn); color: #fff; letter-spacing: .04em; }
.badge-drop { background: var(--warn-tint); color: var(--warn-ink); }
.badge-lang { background: var(--gold-tint); color: var(--gold-ink); }
.pricedrop { font-size: 12px; color: var(--warn-ink); font-weight: 650; margin: 0 0 8px; font-variant-numeric: tabular-nums; }
.badge-budget-PAST { background: var(--good-tint); color: var(--good-ink); }
.badge-budget-KRAP { background: var(--warn-tint); color: var(--warn-ink); }
.badge-budget-NORM { background: var(--warn-tint); color: var(--warn-ink); }
.badge-budget-MAX { background: var(--alert-tint); color: var(--alert-ink); }
.routes {
  background: var(--surface-2);
  padding: 8px 11px;
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.4;
  margin: 2px 0 10px;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}
.routes strong { color: var(--ink); }
/* Maandlast -- the card's focal data point. Big serif total, tabular figures. */
.lasten {
  background: var(--surface-2);
  border: 1px solid var(--line);
  padding: 11px 12px;
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.45;
  margin: 0 0 10px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.lasten-totaal { display: inline-block; font-family: var(--font-serif); font-weight: 700; font-size: 19px; color: var(--ink); letter-spacing: .01em; }
.insight-panel {
  display: grid;
  gap: 11px;
  margin: 0 0 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
}
.insight-group { min-width: 0; }
.insight-title {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.insight-list {
  display: grid;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.insight-item {
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.insight-item.is-primary {
  padding: 9px;
  border-radius: var(--r-xs);
  background: var(--brand-tint);
  color: var(--brand-deep);
}
.insight-score {
  display: block;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.25;
}
.insight-detail {
  display: block;
  margin-top: 2px;
  color: var(--ink-2);
  font-weight: 550;
}
.verdict {
  display: grid;
  gap: 11px;
  margin: 8px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.verdict-block {
  min-width: 0;
  padding-left: 11px;
  border-left: 3px solid var(--line-strong);
}
.verdict-block.is-pro { border-left-color: var(--good); }
.verdict-block.is-con { border-left-color: var(--alert); }
.verdict-title {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--muted);
}
.verdict ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.verdict li {
  position: relative;
  padding-left: 16px;
  font-size: 13px;
  line-height: 1.4;
  overflow-wrap: anywhere;
  text-wrap: pretty;
}
.verdict li::before {
  position: absolute;
  left: 0;
  top: 0;
  font-weight: 700;
}
.is-pro li { color: var(--good-ink); }
.is-pro li::before { content: "+"; color: var(--good); }
.is-con li { color: var(--alert-ink); }
.is-con li::before { content: "\\2013"; color: var(--alert); }
.card-footer { margin-top: auto; padding-top: 14px; }
.card-footer a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 15px;
  background: var(--brand);
  color: #fff;
  border-radius: var(--r-sm);
  text-decoration: none;
  font-size: 13px;
  font-weight: 650;
  transition: background .14s var(--motion-ease), transform .1s var(--motion-ease);
}
.card-footer a:hover { background: var(--brand-deep); }
.card-footer a:active { transform: scale(.98); }
/* Sorteer-/filtermenu -- inklapbaar (details/summary), sticky onder de topbar. */
.controls {
  position: sticky;
  top: calc(58px + env(safe-area-inset-top));
  z-index: 600;
  margin: 30px 0 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  box-shadow: var(--shadow-overlay);
  overflow: hidden;
}
.controls-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.controls-summary::-webkit-details-marker { display: none; }
.controls-summary-label { display: inline-flex; align-items: center; gap: 9px; min-width: 0; }
.controls-summary .chev {
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--muted);
  border-bottom: 2px solid var(--muted);
  transform: rotate(45deg);
  transition: transform .15s var(--motion-ease);
  flex: 0 0 auto;
}
.controls[open] .controls-summary .chev { transform: rotate(-135deg); }
.controls-badge {
  display: none;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--brand);
  color: #fff;
  font-family: var(--font-sans);
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.controls-badge.is-active { display: inline-flex; }
.controls-body {
  display: grid;
  gap: 14px;
  padding: 4px 16px 16px;
  border-top: 1px solid var(--line);
}
.controls-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.control-group { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.control-group--block { align-items: flex-start; }
.control-label {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .05em;
  text-transform: uppercase;
  white-space: nowrap;
}
.controls select,
.controls input[type="number"] {
  min-height: 38px;
  padding: 6px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--ink);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.controls input[type="number"] { width: 118px; }
.sortdir-btn {
  min-height: 38px;
  padding: 0 12px;
  cursor: pointer;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  transition: background .14s var(--motion-ease);
}
.sortdir-btn:hover { background: var(--surface-2); }
.sortdir-btn:active { transform: scale(.97); }
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 5px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  user-select: none;
}
.chip input { width: auto; margin: 0; accent-color: var(--brand); }
.chip:has(input:checked) {
  background: var(--brand-tint);
  color: var(--brand-deep);
  border-color: var(--brand);
}
.controls-toggles { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
.controls-toggles label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
}
.controls-toggles input { accent-color: var(--brand); }
.controls-result {
  margin-left: auto;
  color: var(--muted);
  font-size: 13px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.reset-btn {
  min-height: 38px;
  padding: 0 13px;
  cursor: pointer;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--brand-deep);
  font-size: 13px;
  font-weight: 650;
  transition: background .14s var(--motion-ease);
}
.reset-btn:hover { background: var(--surface-2); }
.filter-empty { margin-top: 16px; }
@media (max-width: 760px) {
  .controls { position: static; margin-top: 24px; }
  .controls-summary { padding: 12px; }
  .controls-body { padding: 4px 12px 12px; }
  .control-group { flex-wrap: wrap; }
  .controls input[type="number"] { width: 100%; flex: 1 1 96px; }
}
.empty {
  text-align: center;
  padding: 36px 18px;
  color: var(--muted);
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
}
.assumptions {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 18px 20px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--muted);
  margin-top: 34px;
}
.assumptions strong { color: var(--ink-2); font-family: var(--font-serif); font-size: 15px; }
.assumptions ul { margin: 8px 0 0; padding-left: 18px; }
.assumptions li { text-wrap: pretty; }
@media (min-width: 920px) {
  .insight-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .insight-price, .insight-broker { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  body { padding-bottom: calc(28px + env(safe-area-inset-bottom)); }
  .topbar-inner { height: 54px; padding: 0 12px; }
  .brand { font-size: 17px; gap: 9px; }
  .brand-mark { width: 32px; height: 32px; font-size: 20px; }
  .refresh-btn { min-height: 38px; padding: 0 12px; font-size: 13px; }
  .container { padding: 16px 12px 0; }
  .profile { grid-template-columns: 1fr; padding: 16px; gap: 14px; }
  .profile dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .profile dl > div { padding: 11px 12px; }
  .section-row { margin: 26px 0 12px; align-items: flex-start; flex-direction: column; }
  #funda-map { height: 380px; min-height: 340px; }
  .map-legend { gap: 12px; padding: 11px 12px; }
  .push-setup { grid-template-columns: 1fr; padding: 14px; }
  .push-actions { justify-content: stretch; }
  .push-actions button { flex: 1 1 150px; }
  .cards { grid-template-columns: 1fr; gap: 14px; }
  .card-title { font-size: 17px; }
  .card-prijs { font-size: 19px; }
  .insight-panel { padding: 10px; gap: 10px; }
  .verdict { gap: 10px; }
  .leaflet-popup-content { width: 254px !important; }
}
@media (max-width: 430px) {
  .profile dl { grid-template-columns: 1fr; }
  .brand-text { max-width: 50vw; }
  .refresh-btn { max-width: 42vw; overflow: hidden; text-overflow: ellipsis; }
  .mp-actions { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; scroll-behavior: auto !important; }
}
@media print {
  body { background: #fff; padding: 0; }
  .topbar { position: static; box-shadow: none; }
  .map-wrap, .notification-section { display: none; }
  .card { box-shadow: none; border: 1px solid #cfcabb; page-break-inside: avoid; }
  .profile, .assumptions { box-shadow: none; border: 1px solid #cfcabb; }
}
"""

# Leaflet (kaart) via CDN — komt in de <head> zodat het ook in de versleutelde
# PWA werkt (scripts in de via innerHTML geinjecteerde body draaien niet).
MAP_HEAD = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script defer src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
"""

# Init-functie voor de kaart. Idempotent + wacht desnoods op Leaflet.
MAP_JS = """
<script>
function fundaEsc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function fundaPopup(p){
  var img = p.foto ? '<img src="'+fundaEsc(p.foto)+'" alt="" loading="lazy">' : '';
  var tags = '';
  if(p.is_nieuw) tags += '<span class="badge badge-new">NIEUW</span>';
  tags += '<span class="badge badge-label '+fundaEsc(p.label)+'">Label '+fundaEsc(p.label)+'</span>';
  if(p.budget) tags += '<span class="badge badge-budget-'+fundaEsc(p.bcls)+'">'+fundaEsc(p.budget)+'</span>';
  var signal = p.signal ? '<div class="mp-signal">'+fundaEsc(p.signal)+'</div>' : '';
  var lijst = p.id ? '<button class="ghost" onclick="fundaToCard(\\''+fundaEsc(p.id)+'\\')">In lijst</button>' : '';
  var open = p.url ? '<a class="primary" href="'+fundaEsc(p.url)+'" target="_blank" rel="noopener">Funda</a>' : '';
  return '<div class="mp">'+img+'<div class="mp-b">'
    + '<div class="mp-title">'+fundaEsc(p.title)+'</div>'
    + '<div class="mp-meta">'+fundaEsc(p.meta)+'</div>'
    + '<div class="mp-row"><span class="mp-prijs">'+fundaEsc(p.prijs)+'</span>'
    + '<span class="mp-lasten">'+fundaEsc(p.m2)+' m&sup2;</span></div>'
    + '<div class="mp-lasten">Maandlast '+fundaEsc(p.maandlast)+'</div>'
    + '<div class="mp-tags">'+tags+'</div>'
    + signal
    + '<div class="mp-actions">'+open+lijst+'</div>'
    + '</div></div>';
}
function fundaToCard(id){
  var el = document.getElementById('card-'+id);
  if(!el) return;
  el.scrollIntoView({behavior:'smooth', block:'center'});
  el.classList.add('flash');
  setTimeout(function(){ el.classList.remove('flash'); }, 1800);
}
function fundaPinIcon(isNew){
  return L.divIcon({
    className: 'funda-pin' + (isNew ? ' is-new' : ''),
    html: '<span></span>',
    iconSize: [34, 40],
    iconAnchor: [17, 36],
    popupAnchor: [0, -32]
  });
}
function fundaWorkIcon(){
  return L.divIcon({
    className: 'work-pin',
    html: '<span></span>',
    iconSize: [34, 40],
    iconAnchor: [17, 34],
    popupAnchor: [0, -30]
  });
}
function fundaInitMap(tries){
  tries = tries || 0;
  var el = document.getElementById('funda-map');
  if(!el) return;
  if(el.dataset.mapInit === '1'){
    if(el._fundaMap) setTimeout(function(){ el._fundaMap.invalidateSize(); }, 100);
    return;
  }
  if(!window.L){ if(tries < 50) setTimeout(function(){ fundaInitMap(tries+1); }, 100); return; }
  var dataEl = document.getElementById('funda-map-data');
  if(!dataEl) return;
  var d; try { d = JSON.parse(dataEl.textContent); } catch(e){ return; }
  el.dataset.mapInit = '1';
  var map = L.map(el, {scrollWheelZoom:false, tap:true});
  el._fundaMap = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {maxZoom:19, attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
  var bounds = [];
  (d.hits||[]).forEach(function(p){
    if(p.lat==null||p.lon==null) return;
    var m = L.marker([p.lat,p.lon], {icon: fundaPinIcon(p.is_nieuw), title: p.title || 'Woning'});
    m.addTo(map).bindPopup(fundaPopup(p), {maxWidth:272, minWidth:254});
    bounds.push([p.lat,p.lon]);
  });
  (d.werk||[]).forEach(function(w){
    if(w.lat==null||w.lon==null) return;
    L.marker([w.lat,w.lon], {icon: fundaWorkIcon(), title: w.label || 'Werk'})
      .addTo(map).bindPopup('<div class="mp"><div class="mp-b"><div class="mp-title">Werk</div><div class="mp-meta">'+fundaEsc(w.label)+'</div></div></div>');
    bounds.push([w.lat,w.lon]);
  });
  if(bounds.length) map.fitBounds(bounds, {padding:[34,34], maxZoom:15});
  else map.setView([52.08,4.30], 11);
  setTimeout(function(){ map.invalidateSize(); }, 150);
}
window.fundaAfterReportLoad = function(){ fundaInitMap(); };
document.addEventListener('DOMContentLoaded', function(){ window.fundaAfterReportLoad(); });
window.addEventListener('pageshow', function(){ setTimeout(window.fundaAfterReportLoad, 80); });
</script>
"""

# Sorteer-/filterlogica voor de shortlist. Draait na het injecteren van de body
# (chained op fundaAfterReportLoad, net als de kaart). Volledig client-side.
CONTROLS_JS = """
<script>
(function(){
  var LABEL_ORDER = ['g','f','e','d','c','b','a','a+','a++','a+++'];
  function num(v){ if(v==null||v==='') return null; var n = parseFloat(v); return isNaN(n)?null:n; }
  function el(id){ return document.getElementById(id); }

  function cardVal(card, key){
    if(key.indexOf('afstand:') === 0){
      return num(card.getAttribute('data-afstand-' + key.slice(8)));
    }
    var map = {score:'score', prijs:'prijs', maandlast:'maandlast', m2:'m2',
      ppm:'ppm', label:'labelrank', recency:'recency'};
    return num(card.getAttribute('data-' + (map[key] || key)));
  }

  function compareCards(a, b, key, dir){
    var va = cardVal(a, key), vb = cardVal(b, key);
    if(va === null && vb === null) return 0;
    if(va === null) return 1;   // ontbrekende waarden altijd achteraan
    if(vb === null) return -1;
    return dir === 'asc' ? (va - vb) : (vb - va);
  }

  function readFilters(){
    var cityChecks = [].slice.call(document.querySelectorAll('.funda-f-city'));
    var cities = cityChecks.filter(function(c){ return c.checked; })
      .map(function(c){ return c.value; });
    return {
      erfpacht: (el('funda-f-erfpacht')||{}).value || 'alle',
      minLabel: (el('funda-f-label')||{}).value || 'alle',
      budget: (el('funda-f-budget')||{}).value || 'alle',
      maxPrijs: num((el('funda-f-maxprijs')||{}).value),
      maxLast: num((el('funda-f-maxlast')||{}).value),
      minM2: num((el('funda-f-minm2')||{}).value),
      onlyNew: !!(el('funda-f-nieuw')||{}).checked,
      onlyDrop: !!(el('funda-f-drop')||{}).checked,
      hasCityFilter: cityChecks.length > 0,
      cities: cities
    };
  }

  function passes(card, f){
    if(f.onlyNew && card.getAttribute('data-nieuw') !== '1') return false;
    if(f.onlyDrop && card.getAttribute('data-drop') !== '1') return false;
    if(f.erfpacht !== 'alle' && card.getAttribute('data-erfpacht') !== f.erfpacht) return false;
    if(f.budget === 'past' && card.getAttribute('data-budget') !== 'PAST') return false;
    if(f.budget === 'fin' && card.getAttribute('data-budget') === 'MAX') return false;
    if(f.hasCityFilter && f.cities.indexOf(card.getAttribute('data-city')) === -1) return false;
    if(f.minLabel !== 'alle'){
      var need = LABEL_ORDER.indexOf(f.minLabel.toLowerCase());
      var have = num(card.getAttribute('data-labelrank'));
      if(have === null || have < need) return false;
    }
    if(f.maxPrijs !== null && (num(card.getAttribute('data-prijs')) || 0) > f.maxPrijs) return false;
    if(f.maxLast !== null && (num(card.getAttribute('data-maandlast')) || 0) > f.maxLast) return false;
    if(f.minM2 !== null && (num(card.getAttribute('data-m2')) || 0) < f.minM2) return false;
    return true;
  }

  function apply(){
    var sortSel = el('funda-sort');
    if(!sortSel) return;
    var key = sortSel.value;
    var dirBtn = el('funda-sortdir');
    var dir = (dirBtn && dirBtn.getAttribute('data-dir')) || 'desc';
    var f = readFilters();

    var sections = document.querySelectorAll('.listing-section');
    var totalVisible = 0, totalAll = 0;
    sections.forEach(function(sec){
      var grid = sec.querySelector('.cards');
      if(!grid) return;
      var cards = [].slice.call(grid.children).filter(function(c){
        return c.classList && c.classList.contains('card');
      });
      var visible = [];
      cards.forEach(function(c){
        var ok = passes(c, f);
        c.style.display = ok ? '' : 'none';
        if(ok) visible.push(c);
      });
      visible.sort(function(a, b){ return compareCards(a, b, key, dir); });
      visible.forEach(function(c){ grid.appendChild(c); });

      totalVisible += visible.length;
      totalAll += cards.length;

      var cnt = sec.querySelector('.count');
      if(cnt) cnt.textContent = visible.length;

      var note = sec.querySelector('.filter-empty');
      if(cards.length > 0 && visible.length === 0){
        if(!note){
          note = document.createElement('div');
          note.className = 'empty filter-empty';
          note.textContent = 'Geen woningen na filteren.';
          grid.parentNode.insertBefore(note, grid.nextSibling);
        }
        note.hidden = false;
      } else if(note){
        note.hidden = true;
      }
    });

    var res = el('funda-f-result');
    if(res) res.textContent = totalVisible + ' van ' + totalAll + ' woningen';

    // Badge: aantal actieve filters (sortering telt niet mee).
    var active = 0;
    if(f.erfpacht !== 'alle') active++;
    if(f.minLabel !== 'alle') active++;
    if(f.budget !== 'alle') active++;
    if(f.maxPrijs !== null) active++;
    if(f.maxLast !== null) active++;
    if(f.minM2 !== null) active++;
    if(f.onlyNew) active++;
    if(f.onlyDrop) active++;
    var allCity = document.querySelectorAll('.funda-f-city').length;
    if(allCity > 0 && f.cities.length < allCity) active++;
    var badge = el('funda-f-active');
    if(badge){
      badge.textContent = active;
      badge.classList.toggle('is-active', active > 0);
    }
  }

  function updateDirLabel(btn){
    var asc = btn.getAttribute('data-dir') === 'asc';
    btn.textContent = asc ? '↑ Laag–hoog' : '↓ Hoog–laag';
  }

  function wireControls(){
    var bar = document.querySelector('.controls');
    if(!bar || bar.getAttribute('data-bound') === '1') return;
    bar.setAttribute('data-bound', '1');

    var sortSel = el('funda-sort');
    var dirBtn = el('funda-sortdir');

    if(sortSel){
      sortSel.addEventListener('change', function(){
        var opt = this.options[this.selectedIndex];
        var dd = (opt && opt.getAttribute('data-dir')) || 'desc';
        if(dirBtn){ dirBtn.setAttribute('data-dir', dd); updateDirLabel(dirBtn); }
        apply();
      });
    }
    if(dirBtn){
      updateDirLabel(dirBtn);
      dirBtn.addEventListener('click', function(){
        this.setAttribute('data-dir', this.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc');
        updateDirLabel(this);
        apply();
      });
    }

    ['funda-f-erfpacht','funda-f-label','funda-f-budget',
     'funda-f-maxprijs','funda-f-maxlast','funda-f-minm2',
     'funda-f-nieuw','funda-f-drop'].forEach(function(id){
      var node = el(id);
      if(node){ node.addEventListener('change', apply); node.addEventListener('input', apply); }
    });
    [].slice.call(document.querySelectorAll('.funda-f-city')).forEach(function(c){
      c.addEventListener('change', apply);
    });

    var reset = el('funda-f-reset');
    if(reset){
      reset.addEventListener('click', function(){
        if(sortSel){ sortSel.value = 'score'; }
        if(dirBtn){ dirBtn.setAttribute('data-dir', 'desc'); updateDirLabel(dirBtn); }
        ['funda-f-erfpacht','funda-f-label','funda-f-budget'].forEach(function(id){
          var n = el(id); if(n) n.value = 'alle';
        });
        ['funda-f-maxprijs','funda-f-maxlast','funda-f-minm2'].forEach(function(id){
          var n = el(id); if(n) n.value = '';
        });
        ['funda-f-nieuw','funda-f-drop'].forEach(function(id){
          var n = el(id); if(n) n.checked = false;
        });
        [].slice.call(document.querySelectorAll('.funda-f-city')).forEach(function(c){
          c.checked = true;
        });
        apply();
      });
    }

    apply();
  }

  var previous = window.fundaAfterReportLoad;
  window.fundaAfterReportLoad = function(){
    if(previous) previous();
    wireControls();
  };
  document.addEventListener('DOMContentLoaded', wireControls);
})();
</script>
"""

def pwa_push_js() -> str:
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
    el.style.color = isError ? '#b42318' : '';
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
    btn.addEventListener('click', async function(){{
      btn.disabled = true;
      pushStatus('Subscription maken...');
      try {{
        var sub = await ensurePushSubscription();
        output.value = JSON.stringify(sub.toJSON(), null, 2);
        output.hidden = false;
        if(copy) copy.hidden = false;
        pushStatus('Kopieer deze JSON naar GitHub secret WEB_PUSH_SUBSCRIPTION.');
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
          pushStatus('Subscription gekopieerd.');
        }} catch(err) {{
          output.focus();
          output.select();
          pushStatus('Kopieer de geselecteerde JSON handmatig.', true);
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


def _budget_class(status: str) -> str:
    if "BOVEN MAX" in status:
        return "MAX"
    if "BOVEN NORM" in status:
        return "NORM"
    if "KRAP" in status or "TEKORT" in status:
        return "KRAP"
    return "PAST"


def _h(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def _detail_url(d: dict) -> str:
    return funda_url(d)


def _listing_key(r: dict) -> str:
    d = r.get("d") or {}
    return str(
        d.get("global_id")
        or d.get("listing_id")
        or d.get("detail_url")
        or d.get("title")
        or "woning"
    )


def _card_id(r: dict) -> str:
    cid = re.sub(r"[^A-Za-z0-9_-]+", "-", _listing_key(r)).strip("-")
    return cid or "woning"


def _money(value: int | float | None) -> str:
    return f"€ {_nl_getal(value)}"


def _clean_signal(signal: str) -> str:
    for prefix in (
        "Buurt: ",
        "Makelaar: ",
        "Advertentie: ",
        "Interesse: ",
        "Media: ",
    ):
        if signal.startswith(prefix):
            return signal[len(prefix):]
    return signal


def _signal_group_name(signal: str) -> str:
    if signal.startswith(("Marktscore", "Vraagprijs per m2", "Prijsverloop", "Laatste WOZ", "Eerder verkocht")):
        return "Prijs"
    if signal.startswith("Buurt:"):
        return "Buurt"
    if signal.startswith("Makelaar:"):
        return "Makelaar"
    return "Advertentie"


def _signal_item_html(signal: str) -> str:
    clean = _clean_signal(signal)
    if signal.startswith("Marktscore") and " | Wijkprijs: " in signal:
        score, detail = signal.split(" | Wijkprijs: ", 1)
        return (
            '<li class="insight-item is-primary">'
            f'<span class="insight-score">{_h(score)}</span>'
            f'<span class="insight-detail">{_h(detail)}</span>'
            "</li>"
        )
    if signal.startswith("Vraagprijs per m2"):
        return f'<li class="insight-item is-primary"><span class="insight-score">{_h(clean)}</span></li>'
    return f'<li class="insight-item">{_h(clean)}</li>'


def _signals_html(signals: list[str]) -> str:
    if not signals:
        return ""
    groups = {
        "Prijs": [],
        "Buurt": [],
        "Makelaar": [],
        "Advertentie": [],
    }
    for signal in signals:
        groups.setdefault(_signal_group_name(signal), []).append(signal)

    chunks = []
    class_map = {
        "Prijs": "price",
        "Buurt": "area",
        "Makelaar": "broker",
        "Advertentie": "listing",
    }
    for title in ("Prijs", "Buurt", "Makelaar", "Advertentie"):
        items = groups.get(title) or []
        if not items:
            continue
        chunks.append(
            f'<section class="insight-group insight-{class_map.get(title, "misc")}">'
            f'<div class="insight-title">{_h(title)}</div>'
            f'<ul class="insight-list">{"".join(_signal_item_html(item) for item in items)}</ul>'
            "</section>"
        )
    return '<div class="insight-panel">' + "".join(chunks) + "</div>" if chunks else ""


def _verdict_html(pros: list[str], cons: list[str]) -> str:
    if not pros and not cons:
        return ""

    def block(title: str, cls: str, items: list[str]) -> str:
        if not items:
            return ""
        return (
            f'<section class="verdict-block {cls}">'
            f'<div class="verdict-title">{_h(title)}</div>'
            '<ul>'
            + "".join(f'<li>{_h(item)}</li>' for item in items)
            + '</ul></section>'
        )

    return (
        '<div class="verdict">'
        + block("Plus", "is-pro", pros)
        + block("Let op", "is-con", cons)
        + "</div>"
    )


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None


def _map_data(rijen: list[dict], werk_coords: dict[str, tuple[float, float]] | None = None) -> dict:
    hits = []
    for r in rijen:
        d = r["d"]
        lat = _to_float(r.get("lat") or ((r.get("details") or {}).get("latitude")))
        lon = _to_float(r.get("lon") or ((r.get("details") or {}).get("longitude")))
        if lat is None or lon is None:
            continue

        plaats = " ".join(str(x) for x in (d.get("postcode"), d.get("city")) if x).strip()
        buurt = d.get("neighbourhood")
        meta = f"{plaats} | {buurt}" if plaats and buurt else plaats or str(buurt or "")
        hits.append({
            "id": _card_id(r),
            "title": d.get("title") or "Woning",
            "meta": meta,
            "prijs": _money(r.get("prijs")),
            "m2": r.get("m2") or "?",
            "maandlast": _money((r.get("lasten") or {}).get("totaal")),
            "label": r.get("label") or "?",
            "budget": r.get("budget") or "",
            "bcls": _budget_class(r.get("budget") or ""),
            "foto": r.get("foto_url") or "",
            "url": _detail_url(d),
            "signal": (r.get("signals") or [""])[0],
            "lat": lat,
            "lon": lon,
            "is_nieuw": bool(r.get("is_nieuw")),
        })

    werk = []
    if werk_coords:
        for pc, label in WERK_POSTCODES:
            coords = werk_coords.get(pc)
            if not coords:
                continue
            werk.append({
                "label": f"{label} ({pc})",
                "lat": float(coords[0]),
                "lon": float(coords[1]),
            })

    return {"hits": hits, "werk": werk}


def _json_script(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _map_html(rijen: list[dict], werk_coords: dict[str, tuple[float, float]] | None = None) -> str:
    data = _map_data(rijen, werk_coords)
    pins = len(data["hits"])
    pin_label = "1 woning" if pins == 1 else f"{pins} woningen"
    empty = (
        '<div class="map-empty">Geen coordinaten gevonden voor de huidige shortlist.</div>'
        if pins == 0 else ""
    )
    werk_legend = '<span><i class="dot work"></i>Werk</span>' if data["werk"] else ""
    return f"""
    <section class="map-section" aria-label="Woningen op OpenStreetMap">
      <div class="section-row">
        <div>
          <h2>Kaart</h2>
          <div class="section-note">Woningen op OpenStreetMap</div>
        </div>
        <span class="count">{pin_label}</span>
      </div>
      <div class="map-wrap">
        <div id="funda-map"></div>
        <div class="map-legend">
          <span><i class="dot hit"></i>Woning</span>
          <span><i class="dot new"></i>Nieuw</span>
          {werk_legend}
        </div>
        {empty}
      </div>
      <script id="funda-map-data" type="application/json">{_json_script(data)}</script>
    </section>
    """


def _push_setup_html() -> str:
    if not WEB_PUSH_PUBLIC_KEY:
        return ""
    return """
    <section class="notification-section" aria-label="Push notificaties">
      <div class="section-row">
        <div>
          <h2>Notificaties</h2>
          <div class="section-note">iOS web push via GitHub Actions</div>
        </div>
      </div>
      <div class="push-setup" data-push-ready="0">
        <div class="push-copy">
          <strong>Nieuwe woningen direct melden</strong>
          <span>Activeer dit vanuit de iOS beginscherm-app. Plak de subscription daarna als GitHub secret <code>WEB_PUSH_SUBSCRIPTION</code>.</span>
        </div>
        <div class="push-actions">
          <button type="button" id="push-subscribe-btn">Activeer push</button>
          <button type="button" id="push-copy-btn" hidden>Kopieer secret</button>
        </div>
        <textarea id="push-subscription-output" readonly hidden spellcheck="false" aria-label="Web Push subscription"></textarea>
        <div id="push-status" class="push-status"></div>
      </div>
    </section>
    """


# Energielabel-ranking voor sorteren/filteren (hoger = beter).
LABEL_RANK = {
    "G": 0, "F": 1, "E": 2, "D": 3, "C": 4, "B": 5,
    "A": 6, "A+": 7, "A++": 8, "A+++": 9,
}


def _werk_slug(label: str | None) -> str:
    """Stabiele slug voor een werk-locatie, gebruikt in data-attributen."""
    return re.sub(r"[^a-z0-9]+", "-", str(label or "").lower()).strip("-") or "werk"


def _card_data_attrs(r: dict) -> str:
    """Bouw de data-* attributen waarop client-side gesorteerd/gefilterd wordt."""
    d = r["d"]
    l = r["lasten"]
    prijs = r.get("prijs") or 0
    m2 = r.get("m2") or 0
    ppm = (prijs // m2) if (prijs and m2) else 0

    label = str(r.get("label") or "?").upper()
    labelrank = LABEL_RANK.get(label, -1)

    # Recency: lager = recenter. Dagen-te-koop indien bekend, anders nieuw vooraan.
    tr = r.get("track") or {}
    dagen = tr.get("dagen")
    if dagen is None:
        recency = 0 if r.get("is_nieuw") else 99999
    else:
        recency = dagen

    erf = r.get("erfpacht") or {}
    erf_status = erf.get("status") or "onbekend"
    if erf_status == "eigen":
        erfpacht_val = "geen"
    elif erf_status == "onbekend":
        erfpacht_val = "onbekend"
    else:
        erfpacht_val = "wel"

    city = (d.get("city") or "").strip().lower()
    bcls = _budget_class(r.get("budget") or "")

    attrs = (
        f' data-score="{float(r.get("score") or 0):.3f}"'
        f' data-prijs="{prijs}"'
        f' data-maandlast="{l.get("totaal") or 0}"'
        f' data-m2="{m2}"'
        f' data-ppm="{ppm}"'
        f' data-labelrank="{labelrank}"'
        f' data-recency="{recency}"'
        f' data-nieuw="{1 if r.get("is_nieuw") else 0}"'
        f' data-drop="{1 if tr.get("gedaald") else 0}"'
        f' data-erfpacht="{erfpacht_val}"'
        f' data-city="{_h(city)}"'
        f' data-budget="{bcls}"'
    )
    for rt in r.get("routes") or []:
        attrs += f' data-afstand-{_werk_slug(rt.get("label"))}="{rt.get("km", 0):.2f}"'
    return attrs


def _card_html(r: dict) -> str:
    d = r["d"]
    url = _detail_url(d)

    foto = r.get("foto_url")
    foto_alt = _h(f"Foto van {d.get('title') or 'woning'}")
    foto_html = (
        f'<img class="card-photo" src="{_h(foto)}" alt="{foto_alt}" loading="lazy">'
        if foto else '<div class="card-photo-placeholder">Geen foto beschikbaar</div>'
    )

    tr = r.get("track") or {}
    badges = []
    if r["is_nieuw"]:
        badges.append('<span class="badge badge-new">NIEUW</span>')
    if tr.get("gedaald"):
        badges.append(
            f'<span class="badge badge-drop">PRIJS -€{_nl_getal(tr["drop_bedrag"])} ({_h(tr["drop_pct"])}%)</span>'
        )
    if tr.get("dagen", 0) >= 90:
        suffix = "" if tr.get("dagen_bron") == "funda" else "+"
        badges.append(f'<span class="badge badge-lang">{_h(tr["dagen"])}{suffix} dagen te koop</span>')
    label = r.get("label") or "?"
    label_class = re.sub(r"[^A-Za-z0-9_-]+", "-", str(label)).strip("-") or "unknown"
    badges.append(f'<span class="badge badge-label {label_class}">Label {_h(label)}</span>')
    if r["label"] in {"A", "B"}:
        badges.append('<span class="badge badge-nhg">NHG-bonus</span>')
    bcls = _budget_class(r["budget"])
    badges.append(f'<span class="badge badge-budget-{bcls}">{_h(r["budget"])}</span>')

    signals_html = _signals_html(r.get("signals") or [])
    verdict_html = _verdict_html(r.get("pros") or [], r.get("cons") or [])

    bouwjaar = ""
    if r["details"] and r["details"].get("construction_year"):
        bouwjaar = f' | bouwjaar {_h(r["details"]["construction_year"])}'

    l = r["lasten"]
    rooms = _h(d.get("rooms") or "?")
    bedrooms = _h(d.get("bedrooms") or "?")

    nieuw_class = " is-new" if r["is_nieuw"] else ""
    card_id = _card_id(r)
    title = _h(d.get("title") or "Woning")
    title_html = (
        f'<a href="{_h(url)}" target="_blank" rel="noopener">{title}</a>'
        if url else title
    )
    footer_html = (
        f'<div class="card-footer"><a href="{_h(url)}" target="_blank" rel="noopener">Bekijk op Funda</a></div>'
        if url else ""
    )

    # Routes naar werk
    routes_html = ""
    if r.get("routes"):
        chunks = []
        for rt in r["routes"]:
            kmtxt = f'{rt["km"]:.1f} km'
            soort = "" if rt["soort"] == "weg" else " (~)"
            chunks.append(
                f'<span title="{_h(rt["postcode"])}">{_h(rt["label"])}: '
                f'<strong>{_h(kmtxt)}</strong>{soort}</span>'
            )
        routes_html = '<div class="routes">Naar werk: ' + ' &middot; '.join(chunks) + '</div>'

    pricedrop_html = ""
    if tr.get("gedaald") and tr.get("eerdere_prijs"):
        wijziging = f" (wijziging {_h(tr['laatste_wijziging'])})" if tr.get("laatste_wijziging") else ""
        pricedrop_html = (
            f'<div class="pricedrop">Was {_money(tr["eerdere_prijs"])}, '
            f'nu {_money(r["prijs"])}{wijziging}</div>'
        )

    return f"""
    <article id="card-{card_id}" class="card budget-{bcls}{nieuw_class}"{_card_data_attrs(r)}>
      <div class="card-photo-wrap">
        {foto_html}
        <div class="card-prijs">{_money(r['prijs'])}</div>
      </div>
      <div class="card-body">
        <div class="card-header">
          <h3 class="card-title">{title_html}</h3>
          <div class="card-meta">{_h(d.get('postcode'))} {_h(d.get('city'))} | {_h(d.get('neighbourhood'))}</div>
        </div>
        <div class="card-meta">{_h(r['m2'])} m2 | {rooms} kamers, {bedrooms} slpk{bouwjaar}</div>
        <div class="badges">{''.join(badges)}</div>
        {pricedrop_html}
        {routes_html}
        <div class="lasten">
          Maandlast: <span class="lasten-totaal">{_money(l['totaal'])}</span>
          (hyp {_money(l['hypotheek'])} + VvE {_money(l['servicekosten'])} + energie {_money(l['energie'])}{' + erfpacht ' + _money(l['canon']) if l.get('canon') else ''} + overig {_money(l['woz_verzekering']+l['onderhoud'])})
        </div>
        {signals_html}
        {verdict_html}
        {footer_html}
      </div>
    </article>
    """


def _controls_html(rijen: list[dict]) -> str:
    """Sorteer- en filterbalk. Werkt volledig client-side (zie CONTROLS_JS)."""
    if not rijen:
        return ""

    # Sorteeropties: vaste set + per werk-locatie een afstandsoptie.
    sort_opts = [
        ("score", "Geschiktheid", "desc"),
        ("prijs", "Prijs", "asc"),
        ("maandlast", "Maandlast", "asc"),
        ("m2", "Oppervlakte", "desc"),
        ("ppm", "Prijs per m²", "asc"),
        ("label", "Energielabel", "desc"),
        ("recency", "Laatst toegevoegd", "asc"),
    ]
    for _pc, label in WERK_POSTCODES:
        sort_opts.append((f"afstand:{_werk_slug(label)}", f"Afstand: {label}", "asc"))

    options_html = "".join(
        f'<option value="{_h(value)}" data-dir="{direction}"'
        f'{" selected" if value == "score" else ""}>{_h(text)}</option>'
        for value, text, direction in sort_opts
    )

    # Steden uit de huidige shortlist (voor stad-filter).
    cities = sorted(
        {(r["d"].get("city") or "").strip() for r in rijen if (r["d"].get("city") or "").strip()},
        key=str.lower,
    )
    city_html = "".join(
        f'<label class="chip"><input type="checkbox" class="funda-f-city" '
        f'value="{_h(c.lower())}" checked>{_h(c)}</label>'
        for c in cities
    )
    city_group = (
        f'<div class="control-group control-group--block">'
        f'<span class="control-label">Stad</span>'
        f'<div class="chip-row">{city_html}</div></div>'
        if city_html else ""
    )

    label_opts = "".join(
        f'<option value="{x}">{x} of beter</option>' for x in ["A", "B", "C", "D", "E", "F"]
    )

    return f"""
    <details class="controls" data-bound="0" aria-label="Sorteren en filteren">
      <summary class="controls-summary">
        <span class="controls-summary-label">
          <span class="chev" aria-hidden="true"></span>
          Sorteer &amp; filter
          <span id="funda-f-active" class="controls-badge" aria-label="actieve filters">0</span>
        </span>
        <span id="funda-f-result" class="controls-result" aria-live="polite"></span>
      </summary>
      <div class="controls-body">
        <div class="controls-row">
          <div class="control-group">
            <span class="control-label">Sorteer</span>
            <select id="funda-sort">{options_html}</select>
            <button type="button" id="funda-sortdir" class="sortdir-btn"
              data-dir="desc" title="Sorteervolgorde omdraaien" aria-label="Sorteervolgorde omdraaien">
              ↓ Hoog&ndash;laag
            </button>
          </div>
        </div>
        <div class="controls-row filters">
          {city_group}
          <div class="control-group">
            <span class="control-label">Erfpacht</span>
            <select id="funda-f-erfpacht">
              <option value="alle">Alle</option>
              <option value="geen">Eigen grond</option>
              <option value="wel">Wel erfpacht</option>
              <option value="onbekend">Onbekend</option>
            </select>
          </div>
          <div class="control-group">
            <span class="control-label">Min. label</span>
            <select id="funda-f-label">
              <option value="alle">Alle</option>
              {label_opts}
            </select>
          </div>
          <div class="control-group">
            <span class="control-label">Financiering</span>
            <select id="funda-f-budget">
              <option value="alle">Alle</option>
              <option value="past">Past (binnen norm)</option>
              <option value="fin">Financierbaar</option>
            </select>
          </div>
          <div class="control-group">
            <span class="control-label">Max prijs</span>
            <input type="number" id="funda-f-maxprijs" inputmode="numeric" min="0" step="10000" placeholder="–">
          </div>
          <div class="control-group">
            <span class="control-label">Max maandlast</span>
            <input type="number" id="funda-f-maxlast" inputmode="numeric" min="0" step="50" placeholder="–">
          </div>
          <div class="control-group">
            <span class="control-label">Min m²</span>
            <input type="number" id="funda-f-minm2" inputmode="numeric" min="0" step="5" placeholder="–">
          </div>
        </div>
        <div class="controls-row">
          <div class="controls-toggles">
            <label><input type="checkbox" id="funda-f-nieuw"> Alleen nieuw</label>
            <label><input type="checkbox" id="funda-f-drop"> Alleen prijsdaling</label>
          </div>
          <button type="button" id="funda-f-reset" class="reset-btn">Reset filters</button>
        </div>
      </div>
    </details>
    """


def render_report_body(
    rijen: list[dict],
    werk_coords: dict[str, tuple[float, float]] | None = None,
) -> str:
    nu = _nu_nl()
    norm = int((BRUTO_JAAR / 12) * NORM_MAANDLAST_PCT)
    nieuwe = [r for r in rijen if r["is_nieuw"]]
    rest = [r for r in rijen if not r["is_nieuw"]]

    # Helper: render een lijst kaarten
    def section(titel: str, ws: list[dict], leeg_msg: str) -> str:
        aantal = len(ws)
        if not ws:
            inhoud = f"<div class='empty'>{_h(leeg_msg)}</div>"
        else:
            inhoud = f"<div class='cards'>{''.join(_card_html(r) for r in ws)}</div>"
        return f"""
        <section class="listing-section">
          <div class="section-row">
            <h2>{_h(titel)}</h2>
            <span class="count">{aantal}</span>
          </div>
          {inhoud}
        </section>
        """

    ververs_knop = (
        f'<a class="refresh-btn" href="{_h(ACTIONS_URL)}" target="_blank" rel="noopener">'
        f'Nieuwe run</a>'
        if ACTIONS_URL else ""
    )
    topbar = f"""
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand" aria-label="Funda shortlist">
          <span class="brand-mark">f</span>
          <span class="brand-text">funda shortlist</span>
        </div>
        {ververs_knop}
      </div>
    </header>
    """

    profiel = f"""
    <div class="profile">
      <div class="profile-intro">
        <div>
          <div class="profile-kicker">Rapport</div>
          <h1>Funda shortlist</h1>
          <div class="subtitle">Gegenereerd {nu}</div>
        </div>
      </div>
      <dl>
        <div><dt>Bruto jaarinkomen</dt><dd>€ {_nl_getal(BRUTO_JAAR)}</dd></div>
        <div><dt>Eigen inleg beschikbaar</dt><dd>€ {_nl_getal(EIGEN_INLEG)} (rest = buffer)</dd></div>
        <div><dt>Max hypotheek regulier</dt><dd>€ {_nl_getal(MAX_HYPOTHEEK)} (label A/B: € {_nl_getal(MAX_HYPOTHEEK_AB)})</dd></div>
        <div><dt>Norm maandlast</dt><dd>€ {_nl_getal(norm)} ({int(NORM_MAANDLAST_PCT*100)}% bruto/m)</dd></div>
        <div><dt>NHG</dt><dd>Ja, premie 0,4% eenmalig, ~0,5%-pt rentekorting</dd></div>
        <div><dt>Startersregeling</dt><dd>Geen overdrachtsbelasting (geldig tot 1 april 2029)</dd></div>
      </dl>
    </div>
    """

    assumpties = """
    <div class="assumptions">
      <strong>Aannames</strong>
      <ul>
        <li>Hypotheek = volledige koopprijs (geen extra eigen geld in stenen).</li>
        <li>NHG rente schatting mei 2026: 3,40% regulier, 3,35% energiezuinig (label A/B).</li>
        <li>Servicekosten uit beschrijving geparsed; default € 175 als niet vermeld.</li>
        <li>Energiekosten ruwe schatting per label, geschaald op m2.</li>
        <li>Onderhoudsreserve € 100/m (1% per jaar / 12).</li>
        <li>Geen netto correctie voor hypotheekrenteaftrek.</li>
      </ul>
    </div>
    """

    nieuw_titel = "Nieuw vandaag"
    nieuw_leeg = "Geen nieuwe matches sinds vorige run."
    rest_titel = "Volledige shortlist"
    rest_leeg = "Geen overige woningen op de shortlist."

    return f"""
    {topbar}
    <main class="container">
    {profiel}
    {_map_html(rijen, werk_coords)}
    {_push_setup_html()}
    {_controls_html(rijen)}
    {section(nieuw_titel, nieuwe, nieuw_leeg)}
    {section(rest_titel, rest, rest_leeg)}
    {assumpties}
    </main>
    """


def render_html(
    rijen: list[dict],
    is_pwa: bool = False,
    werk_coords: dict[str, tuple[float, float]] | None = None,
) -> str:
    nu = _nu_nl()
    body = render_report_body(rijen, werk_coords=werk_coords)
    asset_prefix = "" if is_pwa else "docs/"

    pwa_head = ""
    pwa_script = ""
    if is_pwa:
        pwa_head = """
<link rel="manifest" href="manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Funda">
"""
        pwa_script = """
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js', {scope:'./'}).catch(()=>{}));
}
</script>
"""

    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#154c34">
<title>Funda shortlist {nu}</title>
<link rel="icon" href="{asset_prefix}favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" sizes="180x180" href="{asset_prefix}apple-touch-icon.png">
{pwa_head}
{MAP_HEAD}
<style>{HTML_CSS}</style>
</head>
<body>
{body}
{MAP_JS}
{CONTROLS_JS}
{pwa_push_js() if is_pwa else ""}
{pwa_script}
</body>
</html>"""


# === PWA assets ===

PWA_DIR_NAAM = "docs"  # GitHub Pages staat alleen / of /docs toe
PWA_PASSWORD_FILE = Path(__file__).parent / "funda_pwa_password.txt"

PWA_MANIFEST = """{
  "name": "Funda Shortlist Remco",
  "short_name": "Funda",
  "id": "./",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#f3efe6",
  "theme_color": "#154c34",
  "icons": [
    { "src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "any" },
    { "src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" },
    { "src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ]
}
"""

PWA_SERVICE_WORKER = """// Funda PWA service worker
const CACHE = 'funda-shortlist-v4';
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
    data = { title: 'Nieuwe Funda woningen', body: e.data ? e.data.text() : '' };
  }
  const title = data.title || 'Nieuwe Funda woningen';
  const options = {
    body: data.body || 'Open de shortlist voor de nieuwste matches.',
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

PWA_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#154c34"/>
  <path d="M256 64c-82 0-148 66-148 148 0 104 148 236 148 236s148-132 148-236c0-82-66-148-148-148Z" fill="#c9a23c"/>
  <circle cx="256" cy="210" r="78" fill="#fbf9f3"/>
  <path d="M199 218 256 169l57 49v71h-37v-43h-40v43h-37v-71Z" fill="#154c34"/>
  <path d="M231 314c16 0 25 15 25 15s9-15 25-15c16 0 28 13 28 29 0 30-53 58-53 58s-53-28-53-58c0-16 12-29 28-29Z" fill="#fbf9f3"/>
</svg>
"""

PWA_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#154c34"/>
  <path d="M32 7c-11 0-20 9-20 20 0 14 20 32 20 32s20-18 20-32C52 16 43 7 32 7Z" fill="#c9a23c"/>
  <circle cx="32" cy="27" r="10" fill="#fbf9f3"/>
  <path d="M24 29 32 22l8 7v9h-5v-5h-6v5h-5v-9Z" fill="#154c34"/>
</svg>
"""


def _write_png_icon(path: Path, size: int) -> None:
    """Schrijf een simpele PNG zonder externe dependencies."""
    import struct
    import zlib

    target_size = size
    scale = 3 if target_size <= 256 else 2
    size = target_size * scale

    bg = (31, 107, 74, 255)
    bg2 = (21, 76, 52, 255)
    orange = (201, 162, 60, 255)
    white = (251, 249, 243, 255)
    blue = (21, 76, 52, 255)

    buf = bytearray(size * size * 4)

    def put(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            i = (y * size + x) * 4
            buf[i:i+4] = bytes(color)

    for y in range(size):
        mix = y / max(1, size - 1)
        color = tuple(int(bg[i] * (1 - mix) + bg2[i] * mix) for i in range(4))
        for x in range(size):
            put(x, y, color)

    def circle(cx: int, cy: int, r: int, color: tuple[int, int, int, int]) -> None:
        rr = r * r
        for yy in range(max(0, cy - r), min(size, cy + r + 1)):
            dy = yy - cy
            for xx in range(max(0, cx - r), min(size, cx + r + 1)):
                dx = xx - cx
                if dx * dx + dy * dy <= rr:
                    put(xx, yy, color)

    def poly(points: list[tuple[int, int]], color: tuple[int, int, int, int]) -> None:
        min_x = max(0, min(p[0] for p in points))
        max_x = min(size - 1, max(p[0] for p in points))
        min_y = max(0, min(p[1] for p in points))
        max_y = min(size - 1, max(p[1] for p in points))
        for yy in range(min_y, max_y + 1):
            for xx in range(min_x, max_x + 1):
                inside = False
                j = len(points) - 1
                for i, (xi, yi) in enumerate(points):
                    xj, yj = points[j]
                    if ((yi > yy) != (yj > yy)) and (xx < (xj - xi) * (yy - yi) / (yj - yi) + xi):
                        inside = not inside
                    j = i
                if inside:
                    put(xx, yy, color)

    def rect(x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int, int]) -> None:
        for yy in range(max(0, y1), min(size, y2)):
            for xx in range(max(0, x1), min(size, x2)):
                put(xx, yy, color)

    cx = size // 2
    cy = int(size * .40)
    circle(cx, cy, int(size * .23), orange)
    poly([
        (int(size * .31), int(size * .46)),
        (int(size * .69), int(size * .46)),
        (cx, int(size * .86)),
    ], orange)
    circle(cx, cy, int(size * .14), white)
    poly([
        (int(size * .38), int(size * .40)),
        (cx, int(size * .30)),
        (int(size * .62), int(size * .40)),
    ], blue)
    rect(int(size * .41), int(size * .40), int(size * .59), int(size * .53), blue)
    rect(int(size * .48), int(size * .46), int(size * .53), int(size * .53), orange)
    circle(int(size * .47), int(size * .64), int(size * .035), white)
    circle(int(size * .53), int(size * .64), int(size * .035), white)
    poly([
        (int(size * .43), int(size * .65)),
        (int(size * .57), int(size * .65)),
        (cx, int(size * .75)),
    ], white)

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
                small[o:o+4] = bytes(int(v / block) for v in sums)
        buf = small
        size = target_size

    stride = size * 4
    raw = b"".join(b"\x00" + bytes(buf[y*stride:(y+1)*stride]) for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def beveilig_html(html: str, password: str) -> str:
    """Versleutel HTML body met AES-256-GCM en wikkel in een password-prompt template."""
    import base64
    import os
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = os.urandom(16)
    iv = os.urandom(12)
    iters = 100_000  # snel genoeg op mobiel, sterk genoeg met goed wachtwoord
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    key = kdf.derive(password.encode("utf-8"))
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(iv, html.encode("utf-8"), None)

    salt_b64 = base64.b64encode(salt).decode()
    iv_b64 = base64.b64encode(iv).decode()
    ct_b64 = base64.b64encode(ciphertext).decode()

    return (
        PWA_PASSWORD_WRAPPER
        .replace("__APP_CSS__", HTML_CSS)
        .replace("__MAP_HEAD__", MAP_HEAD)
        .replace("__MAP_JS__", MAP_JS)
        .replace("__CONTROLS_JS__", CONTROLS_JS)
        .replace("__PWA_PUSH_JS__", pwa_push_js())
        .replace("__SALT__", salt_b64)
        .replace("__IV__", iv_b64)
        .replace("__CT__", ct_b64)
        .replace("__ITERS__", str(iters))
    )


PWA_PASSWORD_WRAPPER = """<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Funda</title>
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#154c34">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Funda">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
__MAP_HEAD__
<style>
__APP_CSS__
#content[hidden]{display:none}
.lock{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:calc(24px + env(safe-area-inset-top)) 24px calc(24px + env(safe-area-inset-bottom));text-align:center;background:var(--paper);z-index:9999}
.lock-card{width:min(360px,100%);padding:28px 24px;border-radius:var(--r-lg);background:var(--surface);border:1px solid var(--line);box-shadow:var(--shadow-pop)}
.lock-mark{width:52px;height:52px;margin:0 auto 16px;border-radius:13px;display:grid;place-items:center;background:var(--brand-deep);color:var(--surface);font-family:var(--font-serif);font-size:31px;font-weight:700}
.lock h1{margin:0 0 8px;font-family:var(--font-serif);font-size:23px;letter-spacing:0}
.lock p{color:var(--muted);margin:0 0 22px;line-height:1.45}
.lock input{width:100%;padding:13px 13px;font-size:16px;border:1px solid var(--line-strong);border-radius:var(--r-sm);margin-bottom:12px;background:var(--surface);color:var(--ink)}
.lock input:focus-visible{outline:2px solid var(--brand);outline-offset:1px;border-color:var(--brand)}
.lock button{width:100%;min-height:48px;padding:12px;font-size:16px;background:var(--brand);color:#fff;border:none;border-radius:var(--r-sm);cursor:pointer;font-weight:650;transition:background .14s var(--motion-ease)}
.lock button:hover{background:var(--brand-deep)}
.remember{display:flex;align-items:center;gap:9px;margin:0 0 14px;color:var(--muted);font-size:14px;text-align:left}
.remember input{width:auto;margin:0;accent-color:var(--brand)}
.lock button:disabled{opacity:0.6;cursor:wait}
.err{color:var(--alert);margin-top:10px;font-size:14px;min-height:20px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:s 0.8s linear infinite;margin-right:7px;vertical-align:middle}
@keyframes s{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion: reduce){.spinner{animation-duration:1.5s}}
</style>
__MAP_JS__
__CONTROLS_JS__
__PWA_PUSH_JS__
</head>
<body>
<div id="lock" class="lock">
  <div class="lock-card">
    <div class="lock-mark">f</div>
    <h1>Funda Shortlist</h1>
    <p>Voer wachtwoord in om de inhoud te ontgrendelen.</p>
    <form onsubmit="return unlock(event)">
      <input id="pw" type="password" autocomplete="current-password" placeholder="Wachtwoord" autofocus>
<label class="remember">
  <input id="remember" type="checkbox">
  <span>Onthoud op dit apparaat</span>
</label>
<button id="btn" type="submit">Ontgrendelen</button>
    </form>
    <div id="err" class="err"></div>
  </div>
</div>
<div id="content" hidden></div>
<script>
const SALT = "__SALT__";
const IV   = "__IV__";
const CT   = "__CT__";
const ITERS = __ITERS__;
const REMEMBER_KEY = "funda_pw_persist_v1";
const REMEMBER_DAYS = 30;

function saveRememberedPassword(pw){
  const expires = Date.now() + REMEMBER_DAYS * 24 * 60 * 60 * 1000;
  localStorage.setItem(REMEMBER_KEY, JSON.stringify({ pw, expires }));
}

function getRememberedPassword(){
  try {
    const raw = localStorage.getItem(REMEMBER_KEY);
    if(!raw) return "";
    const data = JSON.parse(raw);
    if(!data || !data.pw || !data.expires || Date.now() > data.expires){
      localStorage.removeItem(REMEMBER_KEY);
      return "";
    }
    return data.pw;
  } catch(_) {
    localStorage.removeItem(REMEMBER_KEY);
    return "";
  }
}

function b64ToBytes(s){const bin=atob(s);const a=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)a[i]=bin.charCodeAt(i);return a;}

async function decrypt(password){
  const salt = b64ToBytes(SALT);
  const iv = b64ToBytes(IV);
  const ct = b64ToBytes(CT);
  const km = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), {name:"PBKDF2"}, false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey({name:"PBKDF2", salt, iterations: ITERS, hash:"SHA-256"}, km, {name:"AES-GCM", length:256}, false, ["decrypt"]);
  const pt = await crypto.subtle.decrypt({name:"AES-GCM", iv}, key, ct);
  return new TextDecoder().decode(pt);
}

async function unlock(e){
  if(e) e.preventDefault();
  const pw = document.getElementById("pw").value;
  const btn = document.getElementById("btn");
  const err = document.getElementById("err");
  err.textContent = "";
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Ontgrendelen...';
  try {
    // Geef browser kans de spinner te tonen voor PBKDF2 blokkeert
    await new Promise(r => setTimeout(r, 50));
    const html = await decrypt(pw);
    const c = document.getElementById("content");
    c.hidden = false;
    c.innerHTML = html;
    // Verberg lock screen pas NA injectie zodat geen flash van lege body
    document.getElementById("lock").style.display = "none";
    if(window.fundaAfterReportLoad) window.fundaAfterReportLoad();
    sessionStorage.setItem("funda_pw", pw);
    if(document.getElementById("remember").checked){
      saveRememberedPassword(pw);
    }
  } catch(ex){
    err.textContent = "Fout wachtwoord";
    btn.disabled = false;
    btn.textContent = "Ontgrendelen";
  }
  return false;
}

// Auto-unlock indien sessie nog actief
(async () => {
  const saved = sessionStorage.getItem("funda_pw") || getRememberedPassword();
  if(saved){
    try{
      const html = await decrypt(saved);
      const c = document.getElementById("content");
      c.hidden = false;
      c.innerHTML = html;
      document.getElementById("lock").style.display = "none";
      if(window.fundaAfterReportLoad) window.fundaAfterReportLoad();
    }catch(_){
      sessionStorage.removeItem("funda_pw");
    }
  }
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js', {scope:'./'}).catch(()=>{}));
}
</script>
</body>
</html>"""


def schrijf_pwa_assets(
    rijen: list[dict],
    werk_coords: dict[str, tuple[float, float]] | None = None,
) -> Path:
    """Genereer alle PWA bestanden in pwa/ subfolder."""
    pwa_dir = Path(__file__).parent / PWA_DIR_NAAM
    pwa_dir.mkdir(exist_ok=True)
    (pwa_dir / "manifest.json").write_text(PWA_MANIFEST, encoding="utf-8")
    (pwa_dir / "service-worker.js").write_text(PWA_SERVICE_WORKER, encoding="utf-8")
    (pwa_dir / "icon.svg").write_text(PWA_ICON_SVG, encoding="utf-8")
    (pwa_dir / "favicon.svg").write_text(PWA_FAVICON_SVG, encoding="utf-8")
    _write_png_icon(pwa_dir / "apple-touch-icon.png", 180)
    _write_png_icon(pwa_dir / "icon-512.png", 512)

    # Lees password en versleutel als beschikbaar.
    inner_html = render_report_body(rijen, werk_coords=werk_coords)
    if PWA_PASSWORD_FILE.exists():
        password = PWA_PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if password:
            beveiligd = beveilig_html(inner_html, password)
            (pwa_dir / "index.html").write_text(beveiligd, encoding="utf-8")
            return pwa_dir

    # Vangrail: in CI (publieke repo) NOOIT onversleuteld publiceren.
    import os
    if os.environ.get("FUNDA_REQUIRE_ENCRYPTION") == "1":
        raise RuntimeError(
            "FUNDA_REQUIRE_ENCRYPTION=1 maar geen wachtwoord gevonden; "
            "weiger om een onversleuteld rapport te schrijven."
        )

    # Fallback (lokaal): onbeveiligd, zelfde tags als eerder.
    print("[rapport] WAARSCHUWING: geen funda_pwa_password.txt gevonden, PWA wordt onversleuteld geschreven!")
    (pwa_dir / "index.html").write_text(
        render_html(rijen, is_pwa=True, werk_coords=werk_coords),
        encoding="utf-8",
    )
    return pwa_dir
