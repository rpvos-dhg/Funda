"""
Rapport-module voor funda_zoek.py.

Analyseert woningen op betaalbaarheid en pros/cons en genereert een
markdown rapport in dezelfde map.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

# === Financiele profiel Remco (mei 2026) ===

BRUTO_JAAR = 67_865               # bruto jaarinkomen incl vakantie- en eindejaarsuitkering
EIGEN_INLEG = 5_000               # vrij beschikbaar zonder buffer aan te tasten
DUO_MAANDLAST = 55                # studielast verlaagt leencapaciteit ~14k
LEEFTIJD = 32                     # startersvrijstelling overdrachtsbelasting tot april 2029

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

# Werk-postcodes (huidig en toekomstig).
WERK_POSTCODES = [
    ("2596EC", "huidig"),
    ("2595AL", "vanaf Q1 2027"),
]
WERK_CACHE = Path(__file__).parent / "funda_werk_coords.json"
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


def parse_erfpacht(beschrijving: str) -> tuple[str, str]:
    """Geeft (status, detail) terug. Status: 'eigen', 'afgekocht', 'lopend', 'onbekend'."""
    if not beschrijving:
        return ("onbekend", "geen beschrijving")
    txt = beschrijving.lower()
    if "erfpacht" not in txt and "eigen grond" not in txt:
        return ("onbekend", "niet expliciet vermeld")
    if "eigen grond" in txt:
        return ("eigen", "eigen grond")
    if "afgekocht" in txt and "erfpacht" in txt:
        return ("afgekocht", "erfpacht eeuwigdurend afgekocht")
    if "erfpacht" in txt:
        return ("lopend", "lopende erfpacht (canon nog te checken)")
    return ("onbekend", "")


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

    # Prijs per m2
    if ppm and ppm < 3700:
        pros.append(f"Scherpe prijs per m2 (€{ppm}/m2)")
    elif ppm and ppm > 4500:
        cons.append(f"Hoge prijs per m2 (€{ppm}/m2)")

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

    # Erfpacht
    erf_status, erf_detail = parse_erfpacht(beschrijving)
    if erf_status == "afgekocht":
        pros.append("Erfpacht eeuwigdurend afgekocht")
    elif erf_status == "lopend":
        cons.append("Lopende erfpacht (canon kan flink oplopen)")
    elif erf_status == "eigen":
        pros.append("Eigen grond")

    # Servicekosten
    sk = parse_servicekosten(beschrijving)
    if sk and sk > 250:
        cons.append(f"Hoge servicekosten (€{sk}/m)")
    elif sk and sk < 100:
        pros.append(f"Lage servicekosten (€{sk}/m)")

    return pros, cons


# === Maandlasten ===

def bereken_maandlasten(prijs: int, label: str | None, m2: int, beschrijving: str) -> dict:
    rente = NHG_RENTE_30JR_AB if label in {"A", "B"} else NHG_RENTE_30JR
    hyp = annuiteit_maand(prijs, rente)
    sk = parse_servicekosten(beschrijving) or SERVICEKOSTEN_DEFAULT
    energie = energie_per_maand(label, m2)
    totaal = hyp + sk + WOZ_VERZEKERING + ONDERHOUDSRESERVE + energie
    return {
        "hypotheek": int(hyp),
        "servicekosten": int(sk),
        "woz_verzekering": WOZ_VERZEKERING,
        "onderhoud": ONDERHOUDSRESERVE,
        "energie": int(energie),
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
    print(f"\n[rapport] Detail-call voor {len(woningen)} woningen, werk-coords: {len(werk_coords)} adressen.")
    rijen = []
    for d in woningen:
        lid = d.get("global_id") or d.get("listing_id")
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        details = None
        beschrijving = ""
        try:
            obj = f.get_listing(lid)
            if hasattr(obj, "data"):
                details = obj.data
                beschrijving = str(details.get("description") or "")
            time.sleep(0.5)
        except Exception as exc:
            print(f"  Detail fout {lid}: {exc}")
        rij = bouw_rij(d, details, beschrijving)
        rij["is_nieuw"] = sleutel in nieuw_ids
        rij["foto_url"] = (details.get("photo_urls") or [None])[0] if details else None

        # Route afstand naar werk-locaties.
        rij["routes"] = []
        wlat = details.get("latitude") if details else None
        wlon = details.get("longitude") if details else None
        if wlat and wlon and werk_coords:
            for pc, label in WERK_POSTCODES:
                if pc in werk_coords:
                    plat, plon = werk_coords[pc]
                    km, soort = afstand_km(wlat, wlon, plat, plon)
                    rij["routes"].append({"postcode": pc, "label": label, "km": km, "soort": soort})

        rijen.append(rij)

    # Sorteer op score (hoog naar laag)
    rijen.sort(key=lambda r: r["score"], reverse=True)

    # Schrijf markdown (backwards compat)
    pad_md = Path(__file__).parent / "funda_rapport.md"
    md = render_markdown(rijen)
    pad_md.write_text(md, encoding="utf-8")

    # Schrijf HTML
    pad_html = Path(__file__).parent / "funda_rapport.html"
    html = render_html(rijen)
    pad_html.write_text(html, encoding="utf-8")

    # Schrijf PWA assets (manifest, sw, icon, index.html)
    pwa_dir = schrijf_pwa_assets(rijen)

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
    lasten = bereken_maandlasten(prijs, label, m2, beschrijving)
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

    return {
        "d": d,
        "details": details,
        "label": label,
        "prijs": prijs,
        "m2": m2,
        "pros": pros,
        "cons": cons,
        "lasten": lasten,
        "in_max": in_max,
        "headroom": headroom,
        "kk": kk,
        "inleg_tekort": inleg_tekort,
        "budget": budget,
        "score": score(d, lasten, pros, cons, in_max),
    }


def render_markdown(rijen: list[dict]) -> str:
    nu = datetime.now().strftime("%Y-%m-%d %H:%M")
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
        url = d.get("detail_url") or ""
        if url and not url.startswith("http"):
            url = f"https://www.funda.nl{url}"

        lines.append(f"### {i}. {d.get('title')} — € {r['prijs']:,}")
        lines.append("")
        lines.append(f"- **Locatie**: {d.get('postcode')} {d.get('city')}, {d.get('neighbourhood')}")
        lines.append(f"- **Oppervlakte**: {r['m2']} m2 ({d.get('rooms') or '?'} kamers, {d.get('bedrooms') or '?'} slaapkamers)")
        lines.append(f"- **Energielabel**: {r['label']}")
        if r['details'] and r['details'].get('construction_year'):
            lines.append(f"- **Bouwjaar**: {r['details']['construction_year']}")
        lines.append(f"- **Funda**: {url}")
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
* { box-sizing: border-box; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px; background: #f4f5f7; color: #1f2937; }
.container { max-width: 1100px; margin: 0 auto; }
h1 { margin: 0 0 8px; font-size: 28px; }
h2 { margin: 32px 0 16px; font-size: 20px; border-bottom: 2px solid #d1d5db; padding-bottom: 8px; }
.subtitle { color: #6b7280; margin-bottom: 24px; }
.profile { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.profile dl { display: grid; grid-template-columns: 220px 1fr; gap: 8px 16px; margin: 0; }
.profile dt { font-weight: 600; color: #4b5563; }
.profile dd { margin: 0; color: #1f2937; }
.cards { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); }
.card { background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; }
.card.is-new { border: 2px solid #10b981; }
.card-photo { background: #e5e7eb; aspect-ratio: 16/9; object-fit: cover; width: 100%; }
.card-photo-placeholder { display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 14px; aspect-ratio: 16/9; background: #e5e7eb; }
.card-body { padding: 16px; flex: 1; display: flex; flex-direction: column; }
.card-header { display: flex; justify-content: space-between; align-items: start; gap: 8px; margin-bottom: 8px; }
.card-title { font-weight: 600; font-size: 15px; line-height: 1.3; margin: 0; }
.card-prijs { font-weight: 700; font-size: 17px; white-space: nowrap; }
.card-meta { color: #6b7280; font-size: 13px; margin-bottom: 12px; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-label { background: #dbeafe; color: #1e40af; }
.badge-label.A, .badge-label.B { background: #d1fae5; color: #065f46; }
.badge-label.F, .badge-label.G { background: #fee2e2; color: #991b1b; }
.badge-nhg { background: #fef3c7; color: #92400e; }
.badge-new { background: #10b981; color: #fff; }
.badge-budget-PAST { background: #d1fae5; color: #065f46; }
.badge-budget-KRAP { background: #fef3c7; color: #92400e; }
.badge-budget-NORM { background: #fed7aa; color: #9a3412; }
.badge-budget-MAX { background: #fee2e2; color: #991b1b; }
.routes { background: #eef2ff; padding: 6px 12px; border-radius: 6px; font-size: 12px; margin: 6px 0; color: #3730a3; }
.lasten { background: #f9fafb; padding: 8px 12px; border-radius: 6px; font-size: 13px; margin: 8px 0; }
.lasten-totaal { font-weight: 700; }
.proscons { font-size: 13px; margin: 8px 0; }
.proscons div { margin: 4px 0; }
.pros { color: #047857; }
.cons { color: #b91c1c; }
.card-footer { margin-top: auto; padding-top: 12px; }
.card-footer a { display: inline-block; padding: 6px 12px; background: #2563eb; color: #fff; text-decoration: none; border-radius: 4px; font-size: 13px; }
.card-footer a:hover { background: #1d4ed8; }
.empty { text-align: center; padding: 40px; color: #6b7280; background: #fff; border-radius: 8px; }
.assumptions { background: #fff; border-radius: 8px; padding: 16px 20px; font-size: 13px; color: #6b7280; margin-top: 32px; }
.assumptions ul { margin: 8px 0 0; padding-left: 18px; }
@media print {
  body { background: #fff; padding: 0; }
  .card { box-shadow: none; border: 1px solid #d1d5db; page-break-inside: avoid; }
  .profile, .assumptions { box-shadow: none; border: 1px solid #d1d5db; }
}
"""


def _budget_class(status: str) -> str:
    if "BOVEN MAX" in status:
        return "MAX"
    if "BOVEN NORM" in status:
        return "NORM"
    if "KRAP" in status or "TEKORT" in status:
        return "KRAP"
    return "PAST"


def _card_html(r: dict) -> str:
    d = r["d"]
    url = d.get("detail_url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"

    foto = r.get("foto_url")
    foto_html = (
        f'<img class="card-photo" src="{foto}" alt="" loading="lazy">'
        if foto else '<div class="card-photo-placeholder">Geen foto beschikbaar</div>'
    )

    badges = []
    if r["is_nieuw"]:
        badges.append('<span class="badge badge-new">NIEUW</span>')
    badges.append(f'<span class="badge badge-label {r["label"]}">Label {r["label"]}</span>')
    if r["label"] in {"A", "B"}:
        badges.append('<span class="badge badge-nhg">NHG-bonus</span>')
    bcls = _budget_class(r["budget"])
    badges.append(f'<span class="badge badge-budget-{bcls}">{r["budget"]}</span>')

    pros_html = "".join(f'<div class="pros">+ {p}</div>' for p in r["pros"])
    cons_html = "".join(f'<div class="cons">- {c}</div>' for c in r["cons"])

    bouwjaar = ""
    if r["details"] and r["details"].get("construction_year"):
        bouwjaar = f' | bouwjaar {r["details"]["construction_year"]}'

    l = r["lasten"]
    rooms = d.get("rooms") or "?"
    bedrooms = d.get("bedrooms") or "?"

    nieuw_class = " is-new" if r["is_nieuw"] else ""

    # Routes naar werk
    routes_html = ""
    if r.get("routes"):
        chunks = []
        for rt in r["routes"]:
            kmtxt = f'{rt["km"]:.1f} km'
            soort = "" if rt["soort"] == "weg" else " (~)"
            chunks.append(f'<span title="{rt["postcode"]}">{rt["label"]}: <strong>{kmtxt}</strong>{soort}</span>')
        routes_html = '<div class="routes">Naar werk: ' + ' &middot; '.join(chunks) + '</div>'

    return f"""
    <div class="card{nieuw_class}">
      {foto_html}
      <div class="card-body">
        <div class="card-header">
          <div>
            <div class="card-title">{d.get('title')}</div>
            <div class="card-meta">{d.get('postcode')} {d.get('city')} | {d.get('neighbourhood')}</div>
          </div>
          <div class="card-prijs">€ {r['prijs']:,}</div>
        </div>
        <div class="card-meta">{r['m2']} m2 | {rooms} kamers, {bedrooms} slpk{bouwjaar}</div>
        <div class="badges">{''.join(badges)}</div>
        {routes_html}
        <div class="lasten">
          Maandlast: <span class="lasten-totaal">€ {l['totaal']:,}</span>
          (hyp €{l['hypotheek']:,} + VvE €{l['servicekosten']} + energie €{l['energie']} + overig €{l['woz_verzekering']+l['onderhoud']})
        </div>
        <div class="proscons">{pros_html}{cons_html}</div>
        <div class="card-footer">
          <a href="{url}" target="_blank">Bekijk op Funda</a>
        </div>
      </div>
    </div>
    """


def render_html(rijen: list[dict], is_pwa: bool = False) -> str:
    nu = datetime.now().strftime("%Y-%m-%d %H:%M")
    norm = int((BRUTO_JAAR / 12) * NORM_MAANDLAST_PCT)
    nieuwe = [r for r in rijen if r["is_nieuw"]]
    rest = [r for r in rijen if not r["is_nieuw"]]

    # Helper: render een lijst kaarten
    def section(titel: str, ws: list[dict], leeg_msg: str) -> str:
        if not ws:
            return f"<h2>{titel}</h2><div class='empty'>{leeg_msg}</div>"
        cards = "".join(_card_html(r) for r in ws)
        return f"<h2>{titel}</h2><div class='cards'>{cards}</div>"

    profiel = f"""
    <div class="profile">
      <h1>Funda shortlist</h1>
      <div class="subtitle">Gegenereerd {nu}</div>
      <dl>
        <dt>Bruto jaarinkomen</dt><dd>€ {BRUTO_JAAR:,}</dd>
        <dt>Eigen inleg beschikbaar</dt><dd>€ {EIGEN_INLEG:,} (rest = buffer)</dd>
        <dt>Max hypotheek regulier</dt><dd>€ {MAX_HYPOTHEEK:,} (label A/B: € {MAX_HYPOTHEEK_AB:,})</dd>
        <dt>Norm maandlast</dt><dd>€ {norm:,} ({int(NORM_MAANDLAST_PCT*100)}% bruto/m)</dd>
        <dt>NHG</dt><dd>Ja, premie 0,4% eenmalig, ~0,5%-pt rentekorting</dd>
        <dt>Startersregeling</dt><dd>Geen overdrachtsbelasting (geldig tot 1 april 2029)</dd>
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

    nieuw_titel = f"Nieuw vandaag ({len(nieuwe)})"
    nieuw_leeg = "Geen nieuwe matches sinds vorige run."
    rest_titel = f"Volledige shortlist ({len(rest)})"
    rest_leeg = "Geen overige woningen op de shortlist."

    body = f"""
    {profiel}
    {section(nieuw_titel, nieuwe, nieuw_leeg)}
    {section(rest_titel, rest, rest_leeg)}
    {assumpties}
    """

    pwa_head = ""
    pwa_script = ""
    if is_pwa:
        pwa_head = """
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#2563eb">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Funda">
<link rel="apple-touch-icon" href="icon.svg">
"""
        pwa_script = """
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js').catch(()=>{}));
}
</script>
"""

    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Funda shortlist {nu}</title>
{pwa_head}
<style>{HTML_CSS}</style>
</head>
<body>
<div class="container">
{body}
</div>
{pwa_script}
</body>
</html>"""


# === PWA assets ===

PWA_DIR_NAAM = "pwa"
PWA_PASSWORD_FILE = Path(__file__).parent / "funda_pwa_password.txt"

PWA_MANIFEST = """{
  "name": "Funda Shortlist Remco",
  "short_name": "Funda",
  "start_url": "./",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#f4f5f7",
  "theme_color": "#2563eb",
  "icons": [
    { "src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" },
    { "src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "maskable" }
  ]
}
"""

PWA_SERVICE_WORKER = """// Funda PWA service worker
const CACHE = 'funda-shortlist-v1';
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['./', 'index.html', 'manifest.json', 'icon.svg'])));
});
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone)).catch(()=>{});
      }
      return resp;
    }).catch(() => caches.match(e.request))
  );
});
"""

PWA_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" fill="#2563eb" rx="32"/>
  <path d="M40 100 L96 52 L152 100 L152 156 L40 156 Z" fill="#ffffff"/>
  <rect x="80" y="118" width="32" height="38" fill="#2563eb"/>
  <rect x="58" y="116" width="20" height="20" fill="#dbeafe"/>
  <rect x="114" y="116" width="20" height="20" fill="#dbeafe"/>
</svg>
"""


def beveilig_html(html: str, password: str) -> str:
    """Versleutel HTML body met AES-256-GCM en wikkel in een password-prompt template."""
    import base64
    import os
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = os.urandom(16)
    iv = os.urandom(12)
    iters = 200_000
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    key = kdf.derive(password.encode("utf-8"))
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(iv, html.encode("utf-8"), None)

    salt_b64 = base64.b64encode(salt).decode()
    iv_b64 = base64.b64encode(iv).decode()
    ct_b64 = base64.b64encode(ciphertext).decode()

    return (
        PWA_PASSWORD_WRAPPER
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
<meta name="theme-color" content="#2563eb">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Funda">
<link rel="apple-touch-icon" href="icon.svg">
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1f2937}
.lock{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:24px;text-align:center}
.lock h1{margin:0 0 8px;font-size:22px}
.lock p{color:#6b7280;margin:0 0 24px}
.lock input{width:100%;max-width:300px;padding:12px;font-size:16px;border:1px solid #d1d5db;border-radius:8px;margin-bottom:12px}
.lock button{width:100%;max-width:300px;padding:12px;font-size:16px;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600}
.lock button:disabled{opacity:0.6;cursor:wait}
.err{color:#b91c1c;margin-top:8px;font-size:14px;min-height:20px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:s 0.8s linear infinite;margin-right:6px;vertical-align:middle}
@keyframes s{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div id="lock" class="lock">
  <h1>Funda Shortlist</h1>
  <p>Voer wachtwoord in om de inhoud te ontgrendelen.</p>
  <form onsubmit="return unlock(event)">
    <input id="pw" type="password" autocomplete="current-password" placeholder="Wachtwoord" autofocus>
    <button id="btn" type="submit">Ontgrendelen</button>
  </form>
  <div id="err" class="err"></div>
</div>
<div id="content" hidden></div>
<script>
const SALT = "__SALT__";
const IV   = "__IV__";
const CT   = "__CT__";
const ITERS = __ITERS__;

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
    const html = await decrypt(pw);
    document.getElementById("lock").hidden = true;
    const c = document.getElementById("content");
    c.hidden = false;
    c.innerHTML = html;
    // Onthoud password binnen sessie
    sessionStorage.setItem("funda_pw", pw);
  } catch(ex){
    err.textContent = "Fout wachtwoord";
    btn.disabled = false;
    btn.textContent = "Ontgrendelen";
  }
  return false;
}

// Auto-unlock indien sessie nog actief
(async () => {
  const saved = sessionStorage.getItem("funda_pw");
  if(saved){
    try{
      const html = await decrypt(saved);
      document.getElementById("lock").hidden = true;
      const c = document.getElementById("content");
      c.hidden = false;
      c.innerHTML = html;
    }catch(_){
      sessionStorage.removeItem("funda_pw");
    }
  }
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js').catch(()=>{}));
}
</script>
</body>
</html>"""


def schrijf_pwa_assets(rijen: list[dict]) -> Path:
    """Genereer alle PWA bestanden in pwa/ subfolder."""
    pwa_dir = Path(__file__).parent / PWA_DIR_NAAM
    pwa_dir.mkdir(exist_ok=True)
    (pwa_dir / "manifest.json").write_text(PWA_MANIFEST, encoding="utf-8")
    (pwa_dir / "service-worker.js").write_text(PWA_SERVICE_WORKER, encoding="utf-8")
    (pwa_dir / "icon.svg").write_text(PWA_ICON_SVG, encoding="utf-8")

    # Lees password en versleutel als beschikbaar.
    inner_html = render_html(rijen, is_pwa=False)  # standalone body
    if PWA_PASSWORD_FILE.exists():
        password = PWA_PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if password:
            beveiligd = beveilig_html(inner_html, password)
            (pwa_dir / "index.html").write_text(beveiligd, encoding="utf-8")
            return pwa_dir

    # Fallback: onbeveiligd, zelfde tags als eerder.
    print("[rapport] WAARSCHUWING: geen funda_pwa_password.txt gevonden, PWA wordt onversleuteld geschreven!")
    (pwa_dir / "index.html").write_text(render_html(rijen, is_pwa=True), encoding="utf-8")
    return pwa_dir
