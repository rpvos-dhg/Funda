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
import html as html_lib
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
        rij["lat"] = wlat
        rij["lon"] = wlon
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
        "lasten": lasten,
        "in_max": in_max,
        "headroom": headroom,
        "kk": kk,
        "inleg_tekort": inleg_tekort,
        "budget": budget,
        "track": track,
        "score": basis_score,
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
:root {
  --funda-blue: #0a5f8f;
  --funda-blue-dark: #06446b;
  --funda-orange: #f47b20;
  --funda-orange-dark: #cf5f0d;
  --ink: #1f2a37;
  --muted: #617082;
  --line: #d9e1e8;
  --bg: #eef3f6;
  --surface: #ffffff;
  --green: #0e9f6e;
  --red: #b42318;
  --yellow: #f6c54f;
  --card-shadow: 0 1px 2px rgba(16,24,40,.06), 0 8px 22px rgba(16,24,40,.08);
  --radius: 8px;
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); -webkit-text-size-adjust: 100%; }
body {
  min-height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  margin: 0;
  padding: 0 0 calc(42px + env(safe-area-inset-bottom));
  background: linear-gradient(#dfeaf0 0, #eef3f6 280px, #eef3f6 100%);
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
a { color: var(--funda-blue); }
button, input, textarea, select { font: inherit; }
.container { width: min(1160px, 100%); margin: 0 auto; padding: 18px 18px 0; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 700;
  padding-top: env(safe-area-inset-top);
  background: var(--funda-blue);
  color: #fff;
  box-shadow: 0 1px 0 rgba(255,255,255,.12) inset, 0 8px 22px rgba(10,95,143,.18);
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
  gap: 10px;
  min-width: 0;
  color: #fff;
  text-decoration: none;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0;
}
.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  background: var(--funda-orange);
  color: #fff;
  font-size: 22px;
  font-weight: 900;
  box-shadow: 0 0 0 2px rgba(255,255,255,.22);
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
  min-height: 40px;
  padding: 0 14px;
  border-radius: 8px;
  background: var(--funda-orange);
  color: #fff;
  border: 1px solid rgba(255,255,255,.22);
  text-decoration: none;
  font-size: 14px;
  font-weight: 750;
  white-space: nowrap;
}
.refresh-btn:hover { background: var(--funda-orange-dark); }
h1, h2, h3 { letter-spacing: 0; }
h1 { margin: 0 0 6px; font-size: clamp(24px, 3vw, 34px); line-height: 1.08; }
h2 { margin: 0; font-size: 21px; line-height: 1.2; }
.subtitle { color: var(--muted); font-size: 14px; }

.profile {
  display: grid;
  grid-template-columns: minmax(260px, .9fr) minmax(0, 1.25fr);
  gap: 18px;
  align-items: stretch;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: rgba(255,255,255,.96);
  box-shadow: var(--card-shadow);
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
  padding: 5px 8px;
  border-radius: 6px;
  background: #e8f3f9;
  color: var(--funda-blue-dark);
  font-size: 12px;
  font-weight: 750;
}
.profile dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}
.profile dl > div {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: #f8fafb;
}
.profile dt {
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0;
  text-transform: uppercase;
}
.profile dd {
  margin: 4px 0 0;
  color: var(--ink);
  font-size: 15px;
  line-height: 1.25;
  font-weight: 750;
}

.section-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin: 28px 0 12px;
}
.section-note { color: var(--muted); font-size: 13px; }
.count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 8px;
  margin-left: 8px;
  border-radius: 6px;
  background: #e8f3f9;
  color: var(--funda-blue-dark);
  font-size: 13px;
  font-weight: 800;
}

.map-section { margin-top: 18px; }
.map-wrap {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--card-shadow);
}
#funda-map {
  width: 100%;
  height: min(58vh, 520px);
  min-height: 360px;
  background: #dce7ec;
  touch-action: pan-x pan-y;
}
.map-legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  padding: 11px 14px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  font-size: 13px;
}
.map-legend span { display: inline-flex; align-items: center; gap: 7px; }
.dot { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px rgba(31,42,55,.22); }
.dot.new { background: var(--green); }
.dot.hit { background: var(--funda-orange); }
.dot.work { background: var(--funda-blue); }
.map-empty {
  padding: 10px 14px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  font-size: 13px;
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
  border: 3px solid #fff;
  border-radius: 50% 50% 50% 0;
  background: var(--funda-orange);
  box-shadow: 0 4px 12px rgba(31,42,55,.28);
  transform: rotate(-45deg);
}
.funda-pin span::after, .work-pin span::after {
  content: "";
  position: absolute;
  inset: 8px;
  border-radius: 50%;
  background: #fff;
}
.funda-pin.is-new span { background: var(--green); }
.work-pin span { background: var(--funda-blue); width: 26px; height: 26px; left: 4px; top: 3px; }

.leaflet-popup-content-wrapper {
  border-radius: 8px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 14px 34px rgba(31,42,55,.24);
}
.leaflet-popup-content { margin: 0; width: 272px !important; }
.mp { background: #fff; color: var(--ink); }
.mp img { width: 100%; height: 132px; object-fit: cover; display: block; background: #dde4eb; }
.mp-b { padding: 12px; }
.mp-title { font-weight: 800; font-size: 15px; line-height: 1.25; color: var(--ink); }
.mp-meta { color: var(--muted); font-size: 12px; margin: 3px 0 8px; line-height: 1.35; }
.mp-row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.mp-prijs { font-weight: 900; font-size: 17px; color: var(--ink); }
.mp-lasten { font-size: 12px; color: var(--muted); }
.mp-tags { margin: 8px 0; display: flex; gap: 5px; flex-wrap: wrap; }
.mp-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.mp-actions a, .mp-actions button {
  min-height: 34px;
  text-align: center;
  font: inherit;
  font-size: 12px;
  font-weight: 800;
  padding: 8px;
  border-radius: 7px;
  cursor: pointer;
  text-decoration: none;
  border: 1px solid var(--line);
}
.mp-actions .primary { background: var(--funda-orange); color: #fff; border-color: var(--funda-orange); }
.mp-actions .ghost { background: #fff; color: var(--funda-blue-dark); }

.cards { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); }
.card {
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--card-shadow);
  scroll-margin-top: calc(76px + env(safe-area-inset-top));
  transition: transform .12s ease, box-shadow .12s ease, border-color .12s ease;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 10px 28px rgba(16,24,40,.14); }
.card.is-new { border-color: rgba(14,159,110,.65); box-shadow: 0 0 0 2px rgba(14,159,110,.18), var(--card-shadow); }
.card.flash { border-color: var(--funda-orange); box-shadow: 0 0 0 3px rgba(244,123,32,.34), var(--card-shadow); }
.card-photo-wrap { position: relative; background: #dce4ea; }
.card-photo { width: 100%; aspect-ratio: 16 / 10; object-fit: cover; display: block; background: #dce4ea; }
.card-photo-placeholder { display: grid; place-items: center; color: var(--muted); font-size: 14px; aspect-ratio: 16 / 10; background: #dce4ea; }
.card-prijs {
  position: absolute;
  left: 12px;
  bottom: 12px;
  max-width: calc(100% - 24px);
  padding: 8px 10px;
  border-radius: 7px;
  background: rgba(255,255,255,.96);
  color: var(--ink);
  font-weight: 900;
  font-size: 20px;
  line-height: 1;
  box-shadow: 0 8px 20px rgba(31,42,55,.18);
}
.card-body { padding: 14px; flex: 1; display: flex; flex-direction: column; min-width: 0; }
.card-header { margin-bottom: 8px; min-width: 0; }
.card-title { margin: 0; font-weight: 850; font-size: 17px; line-height: 1.25; overflow-wrap: anywhere; }
.card-title a { color: var(--ink); text-decoration: none; }
.card-title a:hover { color: var(--funda-blue); }
.card-meta { color: var(--muted); font-size: 13px; line-height: 1.35; margin-bottom: 10px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.badge { display: inline-flex; align-items: center; min-height: 22px; padding: 3px 7px; border-radius: 6px; font-size: 11px; font-weight: 800; line-height: 1.1; }
.badge-label { background: #e7edf3; color: #31465b; }
.badge-label.A, .badge-label.B { background: #d9f3e7; color: #046c4e; }
.badge-label.F, .badge-label.G { background: #fde2df; color: var(--red); }
.badge-nhg { background: #fff2d1; color: #7c4b00; }
.badge-new { background: var(--green); color: #fff; }
.badge-drop { background: #ffd7d2; color: var(--red); }
.badge-lang { background: #ffefbd; color: #775300; }
.pricedrop { font-size: 12px; color: var(--red); font-weight: 750; margin: 0 0 8px; }
.badge-budget-PAST { background: #d9f3e7; color: #046c4e; }
.badge-budget-KRAP { background: #fff2d1; color: #7c4b00; }
.badge-budget-NORM { background: #ffe4c7; color: #91410a; }
.badge-budget-MAX { background: #fde2df; color: var(--red); }
.routes {
  background: #e8f3f9;
  padding: 8px 10px;
  border-radius: 7px;
  font-size: 12px;
  line-height: 1.35;
  margin: 2px 0 8px;
  color: var(--funda-blue-dark);
}
.lasten {
  background: #f7f9fb;
  border: 1px solid #edf1f5;
  padding: 9px 10px;
  border-radius: 7px;
  font-size: 13px;
  line-height: 1.35;
  margin: 0 0 8px;
}
.lasten-totaal { font-weight: 900; color: var(--ink); }
.proscons { font-size: 13px; line-height: 1.35; margin: 6px 0; }
.proscons div { margin: 5px 0; }
.pros { color: #047857; }
.cons { color: var(--red); }
.card-footer { margin-top: auto; padding-top: 12px; }
.card-footer a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 13px;
  background: var(--funda-blue);
  color: #fff;
  border-radius: 7px;
  text-decoration: none;
  font-size: 13px;
  font-weight: 850;
}
.card-footer a:hover { background: var(--funda-blue-dark); }
.empty {
  text-align: center;
  padding: 34px 18px;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.assumptions {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  font-size: 13px;
  line-height: 1.45;
  color: var(--muted);
  margin-top: 30px;
  box-shadow: var(--card-shadow);
}
.assumptions ul { margin: 8px 0 0; padding-left: 18px; }
@media (max-width: 760px) {
  body { padding-bottom: calc(28px + env(safe-area-inset-bottom)); }
  .topbar-inner { height: 54px; padding: 0 12px; }
  .brand { font-size: 16px; gap: 8px; }
  .brand-mark { width: 32px; height: 32px; font-size: 20px; }
  .refresh-btn { min-height: 38px; padding: 0 10px; font-size: 13px; }
  .container { padding: 14px 12px 0; }
  .profile { grid-template-columns: 1fr; padding: 14px; gap: 12px; }
  .profile dl { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .profile dl > div { padding: 10px; }
  .section-row { margin: 22px 0 10px; align-items: flex-start; flex-direction: column; }
  #funda-map { height: 380px; min-height: 340px; }
  .map-legend { gap: 10px; padding: 10px 12px; }
  .cards { grid-template-columns: 1fr; gap: 14px; }
  .card-title { font-size: 16px; }
  .card-prijs { font-size: 18px; }
  .leaflet-popup-content { width: 254px !important; }
}
@media (max-width: 430px) {
  .profile dl { grid-template-columns: 1fr; }
  .brand-text { max-width: 50vw; }
  .refresh-btn { max-width: 40vw; overflow: hidden; text-overflow: ellipsis; }
  .mp-actions { grid-template-columns: 1fr; }
}
@media print {
  body { background: #fff; padding: 0; }
  .topbar { position: static; box-shadow: none; }
  .map-wrap { display: none; }
  .card { box-shadow: none; border: 1px solid #d1d5db; page-break-inside: avoid; }
  .profile, .assumptions { box-shadow: none; border: 1px solid #d1d5db; }
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
  var lijst = p.id ? '<button class="ghost" onclick="fundaToCard(\\''+fundaEsc(p.id)+'\\')">In lijst</button>' : '';
  var open = p.url ? '<a class="primary" href="'+fundaEsc(p.url)+'" target="_blank" rel="noopener">Funda</a>' : '';
  return '<div class="mp">'+img+'<div class="mp-b">'
    + '<div class="mp-title">'+fundaEsc(p.title)+'</div>'
    + '<div class="mp-meta">'+fundaEsc(p.meta)+'</div>'
    + '<div class="mp-row"><span class="mp-prijs">'+fundaEsc(p.prijs)+'</span>'
    + '<span class="mp-lasten">'+fundaEsc(p.m2)+' m&sup2;</span></div>'
    + '<div class="mp-lasten">Maandlast '+fundaEsc(p.maandlast)+'</div>'
    + '<div class="mp-tags">'+tags+'</div>'
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
    url = d.get("detail_url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    return url


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
    return f"€ {int(value or 0):,}"


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


def _card_html(r: dict) -> str:
    d = r["d"]
    url = _detail_url(d)

    foto = r.get("foto_url")
    foto_html = (
        f'<img class="card-photo" src="{_h(foto)}" alt="" loading="lazy">'
        if foto else '<div class="card-photo-placeholder">Geen foto beschikbaar</div>'
    )

    tr = r.get("track") or {}
    badges = []
    if r["is_nieuw"]:
        badges.append('<span class="badge badge-new">NIEUW</span>')
    if tr.get("gedaald"):
        badges.append(
            f'<span class="badge badge-drop">PRIJS -€{int(tr["drop_bedrag"]):,} ({_h(tr["drop_pct"])}%)</span>'
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

    pros_html = "".join(f'<div class="pros">+ {_h(p)}</div>' for p in r["pros"])
    cons_html = "".join(f'<div class="cons">- {_h(c)}</div>' for c in r["cons"])

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
    <article id="card-{card_id}" class="card{nieuw_class}">
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
        <div class="proscons">{pros_html}{cons_html}</div>
        {footer_html}
      </div>
    </article>
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
        <div><dt>Bruto jaarinkomen</dt><dd>€ {BRUTO_JAAR:,}</dd></div>
        <div><dt>Eigen inleg beschikbaar</dt><dd>€ {EIGEN_INLEG:,} (rest = buffer)</dd></div>
        <div><dt>Max hypotheek regulier</dt><dd>€ {MAX_HYPOTHEEK:,} (label A/B: € {MAX_HYPOTHEEK_AB:,})</dd></div>
        <div><dt>Norm maandlast</dt><dd>€ {norm:,} ({int(NORM_MAANDLAST_PCT*100)}% bruto/m)</dd></div>
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
<meta name="theme-color" content="#0a5f8f">
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
  "background_color": "#eef3f6",
  "theme_color": "#0a5f8f",
  "icons": [
    { "src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "any" },
    { "src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" },
    { "src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" }
  ]
}
"""

PWA_SERVICE_WORKER = """// Funda PWA service worker
const CACHE = 'funda-shortlist-v3';
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
"""

PWA_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0a5f8f"/>
  <path d="M256 64c-82 0-148 66-148 148 0 104 148 236 148 236s148-132 148-236c0-82-66-148-148-148Z" fill="#f47b20"/>
  <circle cx="256" cy="210" r="78" fill="#fff"/>
  <path d="M199 218 256 169l57 49v71h-37v-43h-40v43h-37v-71Z" fill="#0a5f8f"/>
  <path d="M231 314c16 0 25 15 25 15s9-15 25-15c16 0 28 13 28 29 0 30-53 58-53 58s-53-28-53-58c0-16 12-29 28-29Z" fill="#fff"/>
</svg>
"""

PWA_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#0a5f8f"/>
  <path d="M32 7c-11 0-20 9-20 20 0 14 20 32 20 32s20-18 20-32C52 16 43 7 32 7Z" fill="#f47b20"/>
  <circle cx="32" cy="27" r="10" fill="#fff"/>
  <path d="M24 29 32 22l8 7v9h-5v-5h-6v5h-5v-9Z" fill="#0a5f8f"/>
</svg>
"""


def _write_png_icon(path: Path, size: int) -> None:
    """Schrijf een simpele PNG zonder externe dependencies."""
    import struct
    import zlib

    target_size = size
    scale = 3 if target_size <= 256 else 2
    size = target_size * scale

    bg = (10, 95, 143, 255)
    bg2 = (8, 74, 112, 255)
    orange = (244, 123, 32, 255)
    white = (255, 255, 255, 255)
    blue = (10, 95, 143, 255)

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
<meta name="theme-color" content="#0a5f8f">
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
.lock{position:fixed;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:calc(24px + env(safe-area-inset-top)) 24px calc(24px + env(safe-area-inset-bottom));text-align:center;background:#eef3f6;z-index:9999}
.lock-card{width:min(360px,100%);padding:24px;border-radius:8px;background:#fff;border:1px solid #d9e1e8;box-shadow:0 12px 34px rgba(16,24,40,.14)}
.lock-mark{width:48px;height:48px;margin:0 auto 14px;border-radius:10px;display:grid;place-items:center;background:#f47b20;color:#fff;font-size:31px;font-weight:900}
.lock h1{margin:0 0 8px;font-size:22px;letter-spacing:0}
.lock p{color:#617082;margin:0 0 22px;line-height:1.4}
.lock input{width:100%;padding:13px 12px;font-size:16px;border:1px solid #d9e1e8;border-radius:8px;margin-bottom:12px;background:#fff;color:#1f2a37}
.lock button{width:100%;min-height:44px;padding:12px;font-size:16px;background:#f47b20;color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:800}
.lock button:disabled{opacity:0.6;cursor:wait}
.err{color:#b91c1c;margin-top:8px;font-size:14px;min-height:20px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:s 0.8s linear infinite;margin-right:6px;vertical-align:middle}
@keyframes s{to{transform:rotate(360deg)}}
</style>
__MAP_JS__
</head>
<body>
<div id="lock" class="lock">
  <div class="lock-card">
    <div class="lock-mark">f</div>
    <h1>Funda Shortlist</h1>
    <p>Voer wachtwoord in om de inhoud te ontgrendelen.</p>
    <form onsubmit="return unlock(event)">
      <input id="pw" type="password" autocomplete="current-password" placeholder="Wachtwoord" autofocus>
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
