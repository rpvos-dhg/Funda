"""
Dagelijkse Funda check voor Remco.

Zoekt koopappartementen binnen 7 km fietsen vanaf postcode 2596EC,
prijs € 250-310k, min 60 m2. Filtert beleggingsobjecten weg, sluit
ongewenste buurten uit en markeert twijfelbuurten met een waarschuwing.

Eerste run: toont alle matches.
Volgende runs: toont alleen NIEUWE woningen sinds vorige run.

Vereisten:
    pip install git+https://github.com/0xMH/pyfunda.git

Gebruik:
    python funda_zoek.py
    python funda_zoek.py --debug-wijken
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from datetime import datetime

from funda import Funda

try:
    from funda_rapport import genereer_rapport
except ImportError:
    genereer_rapport = None


# === Configuratie — laad uit gitignored config bestand ===

PERSONAL_CONFIG_FILE = Path(__file__).parent / "funda_personal.json"


def _laad_personal() -> dict:
    if PERSONAL_CONFIG_FILE.exists():
        try:
            return json.loads(PERSONAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    print(f"WAARSCHUWING: {PERSONAL_CONFIG_FILE.name} ontbreekt, gebruik dummy defaults!")
    return {"postcode_huidig": "1011AB", "radius_km": 5, "prijs_min": 200_000, "prijs_max": 350_000, "m2_min": 60}


_PERSONAL = _laad_personal()

POSTCODE = _PERSONAL["postcode_huidig"]
RADIUS_KM = _PERSONAL["radius_km"]
PRIJS_MIN = _PERSONAL["prijs_min"]
PRIJS_MAX = _PERSONAL["prijs_max"]
M2_MIN = _PERSONAL.get("m2_min", 60)
PAGINAS = 5
NHG_LABELS = {"A", "A+", "A++", "A+++", "B"}

# Buurten die je niet wil zien (substring match, case-insensitive).
UITSLUIT_BUURTEN = [
    "Schildersbuurt",
    "Transvaalkwartier",
    "Moerwijk",
    "Laakkwartier",
    "Spoorwijk",
    "Morgenstond",
    "Dreven en Gaarden",
    "Rustenburg",
    "Heesterbuurt",
    "Groente- en Fruitmarkt",
    "Noordpolderbuurt",
    "Kampen",
    "Landen",
    "Burgen en Horsten",
    "Oostbroek",
]

# Steden die je niet wil zien (substring match op city-veld, case-insensitive).
# Funda gebruikt soms varianten als "Rijswijk (ZH)", dus geen exact match.
UITSLUIT_STEDEN = ["Rijswijk", "Leidschendam"]

# Buurten waar je twijfels over hebt: tonen, maar markeren met waarschuwing.
TWIJFEL_BUURTEN = [
    "Mariahoeve",
    "Houtwijk",
    "Leyenburg",
]

# Tekst-trefwoorden die op beleggingsobject of verhuurde staat wijzen.
BLOKKEER_WOORDEN = [
    "beleggingsobject", "investment object", "verhuurde staat",
    "in verhuur", "rented condition", "belegging",
    "zittende huurder", "huurder aanwezig", "wordt verhuurd",
]

# Tekst-trefwoorden die op begane grond / souterrain wijzen.
# Worden afgewezen want Remco wil hoger wonen ivm rust en inbraakrisico.
BG_WOORDEN = [
    "op de begane grond", "begane-grondappartement", "beganegrondappartement",
    "gelijkvloers appartement", "parterre appartement", "parterrewoning",
    "souterrain", "benedenwoning", "benedenappartement",
]

# Buitenruimte: GEEN harde filter want Funda's boolean is onbetrouwbaar
# (Busken Huet 66 had een balkon maar werd als False gemarkeerd).
# Wel als waarschuwing in het rapport tonen.
EIS_BUITENRUIMTE = False

# Straat-segmenten: voor straten waarvan slechts een deel acceptabel is.
# Sleutel = lowercased straatnaam, value = (min_huisnummer, max_huisnummer of None, stad).
STRAAT_SEGMENTEN = {
    "beeklaan": (320, None, "Den Haag"),  # alleen nummers >= 320 (Bomenbuurt/Duinoord-kant)
}

# Trefwoorden voor buitenruimte (gebruikt door rapport voor pros/cons detectie).
BUITEN_WOORDEN = [
    "balkon", "tuin", "dakterras", "loggia", "patio", "terras",
    "buitenruimte", "veranda", "zonneterras", "voortuin", "achtertuin",
    "frans balkon",
]

# State naast het script.
STATE_FILE = Path(__file__).parent / "funda_seen_ids.json"
LOG_FILE = Path(__file__).parent / "funda_log.txt"
BLACKLIST_FILE = Path(__file__).parent / "funda_blacklist.json"


# === Helpers ===

def laad_state() -> set[str]:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            return set()
    return set()


def bewaar_state(ids: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(ids), indent=2))


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")


def is_uitgesloten_buurt(buurt: str) -> str | None:
    s = buurt.lower()
    for u in UITSLUIT_BUURTEN:
        if u.lower() in s:
            return u
    return None


def is_uitgesloten_stad(stad: str) -> str | None:
    s = stad.lower()
    for u in UITSLUIT_STEDEN:
        if u.lower() in s:
            return u
    return None


def is_twijfelbuurt(buurt: str) -> str | None:
    s = buurt.lower()
    for t in TWIJFEL_BUURTEN:
        if t.lower() in s:
            return t
    return None


def is_belegging(tekst: str) -> list[str]:
    s = tekst.lower()
    return [w for w in BLOKKEER_WOORDEN if w in s]


def is_begane_grond(tekst: str) -> list[str]:
    s = tekst.lower()
    return [w for w in BG_WOORDEN if w in s]


def heeft_buitenruimte(details_data: dict | None, tekst: str) -> bool:
    if details_data:
        if details_data.get("has_balcony") or details_data.get("has_garden") or details_data.get("has_roof_terrace"):
            return True
    s = (tekst or "").lower()
    return any(w in s for w in BUITEN_WOORDEN)


def is_uitgesloten_straat_nr(d: dict) -> str | None:
    """Check straat-segment regel. Geeft reden terug als out-of-range."""
    titel = (d.get("title") or "").lower()
    stad = (d.get("city") or "").strip()
    huisnr = d.get("house_number")
    for straat, (min_nr, max_nr, regel_stad) in STRAAT_SEGMENTEN.items():
        if straat in titel and (not regel_stad or stad == regel_stad):
            try:
                nr = int(huisnr) if huisnr is not None else None
            except (TypeError, ValueError):
                nr = None
            if nr is None:
                return None  # geen nummer = niet kunnen beoordelen
            if min_nr is not None and nr < min_nr:
                return f"{straat.title()} {nr} ligt onder geliefd segment ({min_nr}+)"
            if max_nr is not None and nr > max_nr:
                return f"{straat.title()} {nr} ligt boven segment (max {max_nr})"
    return None


def laad_blacklist() -> set[str]:
    if BLACKLIST_FILE.exists():
        try:
            return set(json.loads(BLACKLIST_FILE.read_text()))
        except Exception:
            return set()
    return set()


# === Hoofdroutine ===

def main() -> None:
    debug_wijken = "--debug-wijken" in sys.argv
    f = Funda()
    seen = laad_state()
    mode = " (debug-wijken)" if debug_wijken else ""
    log(f"Start{mode}. Postcode {POSTCODE}, radius {RADIUS_KM}km. Reeds gezien: {len(seen)}.")

    # Eén query met radius, dat dekt Den Haag, Voorburg en omliggende plaatsen.
    rauwe = []
    for pagina in range(PAGINAS):
        try:
            results = f.search_listing(
                location=POSTCODE,
                radius_km=RADIUS_KM,
                offering_type="buy",
                price_min=PRIJS_MIN,
                price_max=PRIJS_MAX,
                object_type=["apartment"],
                availability=["available"],
                area_min=M2_MIN,
                page=pagina,
            )
        except Exception as exc:
            log(f"Fout pagina {pagina}: {exc}")
            break
        if not results:
            break
        rauwe.extend(results)
        time.sleep(0.4)

    log(f"Totaal opgehaald: {len(rauwe)}.")

    # Debug: alle binnenkomende wijken inventariseren.
    if debug_wijken:
        wijk_counts: Counter[str] = Counter()
        for r in rauwe:
            buurt = (r.data.get("neighbourhood") or "").strip() or "(leeg)"
            stad = (r.data.get("city") or "").strip()
            sleutel = f"{stad} - {buurt}" if stad else buurt
            wijk_counts[sleutel] += 1

        print("\n--- DEBUG: alle wijken in resultaten ---")
        for naam, n in wijk_counts.most_common():
            buurt = naam.split(" - ")[-1]
            stad = naam.split(" - ")[0] if " - " in naam else ""
            if is_uitgesloten_stad(stad):
                tag = "STAD-UIT"
            elif is_uitgesloten_buurt(buurt):
                tag = "UIT     "
            elif is_twijfelbuurt(buurt):
                tag = "TWIJFEL "
            else:
                tag = "OK      "
            print(f"  [{tag}] {n:>2}x  {naam}")
        print()

    # Filter op stad, buurt en straat-segment.
    voor: list = []
    weg_stad = weg_buurt = weg_straat = 0
    for r in rauwe:
        d = r.data
        stad = (d.get("city") or "").strip()
        buurt = (d.get("neighbourhood") or "").strip()
        if is_uitgesloten_stad(stad):
            weg_stad += 1
            continue
        if is_uitgesloten_buurt(buurt):
            weg_buurt += 1
            continue
        straat_reden = is_uitgesloten_straat_nr(d)
        if straat_reden:
            weg_straat += 1
            continue
        voor.append(r)

    log(f"Na filter: {len(voor)} (weg: {weg_stad} stad, {weg_buurt} buurt, {weg_straat} straat-segment).")

    # Detail-check op beleggingsobject, begane grond, buitenruimte en blacklist.
    blacklist = laad_blacklist()
    goed: list[dict] = []
    afgewezen: list[tuple[dict, list[str]]] = []
    for r in voor:
        d = r.data
        lid = d.get("global_id") or d.get("listing_id")
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))

        # Blacklist-check eerst (geen detail-call nodig).
        if sleutel in blacklist:
            afgewezen.append((d, ["blacklist"]))
            continue

        try:
            details = f.get_listing(lid)
            details_data = details.data if hasattr(details, "data") else None
            tekst = ""
            if details_data:
                tekst = str(details_data.get("description", ""))
                tekst += " " + str(details_data.get("title", ""))

            redenen: list[str] = []

            woorden = is_belegging(tekst)
            if woorden:
                redenen.extend(woorden)

            bg = is_begane_grond(tekst)
            if bg:
                redenen.append(f"begane grond ({bg[0]})")

            if EIS_BUITENRUIMTE and not heeft_buitenruimte(details_data, tekst):
                redenen.append("geen buitenruimte")

            if redenen:
                afgewezen.append((d, redenen))
            else:
                goed.append(d)
            time.sleep(0.5)
        except Exception as exc:
            log(f"Detail fout {lid}: {exc} - tonen by default.")
            goed.append(d)

    # Splits in nieuw vs eerder gezien.
    nieuw, bekend = [], []
    for d in goed:
        lid = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        (nieuw if lid not in seen else bekend).append(d)

    # Sorteer twijfelbuurten naar onderen binnen elke groep.
    def sort_key(d: dict):
        buurt = (d.get("neighbourhood") or "")
        twijfel = is_twijfelbuurt(buurt) is not None
        return (twijfel, d.get("price", 0))

    nieuw.sort(key=sort_key)
    bekend.sort(key=sort_key)

    # Output.
    print("\n" + "=" * 78)
    print(f"NIEUW: {len(nieuw)}    Eerder gezien: {len(bekend)}    Afgewezen: {len(afgewezen)}")
    print("=" * 78)

    for d in nieuw:
        toon(d, prefix="NIEUW")

    if bekend:
        print("\n--- Eerder gezien, nog steeds beschikbaar ---")
        for d in bekend:
            toon(d, prefix="     ")

    if afgewezen:
        print("\n--- Afgewezen (belegging/bg/buitenruimte/blacklist) ---")
        for d, w in afgewezen:
            print(f"  {d.get('title')}: {', '.join(w)}")

    # State updaten.
    nieuwe_set = {str(d.get("global_id") or d.get("listing_id") or d.get("detail_url")) for d in goed}
    bewaar_state(seen | nieuwe_set)
    log(f"Klaar. Nieuw vandaag: {len(nieuw)}. State bevat nu {len(seen | nieuwe_set)} id's.")

    # Rapport genereren over alle goedgekeurde woningen, met markering nieuw vs eerder.
    if genereer_rapport and goed:
        try:
            nieuw_ids = {str(d.get("global_id") or d.get("listing_id") or d.get("detail_url")) for d in nieuw}
            pad = genereer_rapport(f, goed, nieuw_ids)
            log(f"Rapport: {pad.name}")
        except Exception as exc:
            log(f"Rapport-fout: {exc}")


def toon(d: dict, prefix: str = "") -> None:
    prijs = d.get("price", 0)
    m2 = d.get("living_area", 0) or 0
    ppm = prijs // m2 if m2 else 0
    label = d.get("energy_label", "?")
    nhg = " | NHG-label" if label in NHG_LABELS else ""
    buurt = d.get("neighbourhood", "")
    twijfel = is_twijfelbuurt(buurt)
    flag = f" /!\\ TWIJFELBUURT ({twijfel})" if twijfel else ""
    url = d.get("detail_url", "")
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    print(f"\n[{prefix}] € {prijs:,} | {m2} m2 (€{ppm}/m2) | label {label}{nhg}{flag}")
    print(f"  {d.get('title')}, {d.get('postcode')} {d.get('city')}")
    print(f"  Wijk: {buurt}")
    print(f"  {d.get('bedrooms')} slpk | {d.get('rooms')} kamers")
    print(f"  {url}")


if __name__ == "__main__":
    main()
