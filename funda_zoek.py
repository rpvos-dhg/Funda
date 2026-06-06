"""
Dagelijkse Funda check voor Remco.

Zoekt koopappartementen binnen 7 km fietsen vanaf postcode 2596EC,
prijs € 230-310k, min 55 m2. Filtert beleggingsobjecten weg, sluit
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
import re
import subprocess
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
    return {"postcode_huidig": "1011AB", "radius_km": 5, "prijs_min": 200_000, "prijs_max": 350_000, "m2_min": 52}


_PERSONAL = _laad_personal()

POSTCODE = _PERSONAL["postcode_huidig"]
RADIUS_KM = _PERSONAL["radius_km"]
PRIJS_MIN = _PERSONAL["prijs_min"]
PRIJS_MAX = _PERSONAL["prijs_max"]
M2_MIN = _PERSONAL.get("m2_min", 52)
PAGINAS = 25  # ruim genoeg; loop stopt zelf zodra een band leeg is
NHG_LABELS = {"A", "A+", "A++", "A+++", "B"}

# Funda kapt een zoekopdracht af op ~140 resultaten. Daardoor verdwijnen
# woningen die al lang te koop staan (ze zakken achter die grens). Door per
# prijsband apart te zoeken blijft elke deel-query onder de kap, en pakken we
# samen veel meer van de markt, inclusief de oudgedienden.
PRIJS_BAND_STAP = _PERSONAL.get("prijs_band_stap", 20_000)

# Drempel waarboven een woning als "lang op funda" geldt (handig voor onderhandelen).
LANG_OP_FUNDA_DAGEN = _PERSONAL.get("lang_op_funda_dagen", 90)

# Zoek dezelfde prijsband ook met sorteringen die andere delen van Funda's
# resultaatkap raken. Vooral "oldest" haalt lang-te-koop woningen naar voren.
ZOEK_SORTS = _PERSONAL.get("zoek_sorts", [None, "oldest"])


def maak_prijs_banden(prijs_min: int, prijs_max: int, stap: int) -> list[tuple[int, int]]:
    """Splits prijsrange in banden. Laatste band loopt door tot prijs_max."""
    if stap <= 0 or prijs_max - prijs_min <= stap:
        return [(prijs_min, prijs_max)]
    banden: list[tuple[int, int]] = []
    lo = prijs_min
    while lo < prijs_max:
        hi = min(lo + stap, prijs_max)
        banden.append((lo, hi))
        lo = hi  # grenzen overlappen 1 prijspunt; dedup op id vangt dubbelen op
    return banden

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
    "woning op de begane grond", "appartement op de begane grond",
    "gelegen op de begane grond", "ligt op de begane grond",
    "begane-grondappartement", "beganegrondappartement",
    "gelijkvloers appartement", "parterre appartement", "parterrewoning",
    "souterrainwoning", "souterrainappartement",
    "benedenwoning", "benedenappartement",
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
# Prijs- en datumgeschiedenis die we zelf bijhouden. Onafhankelijk van wat
# Funda wel/niet teruggeeft, dus betrouwbaar voor prijsdaling-detectie.
TRACKING_FILE = Path(__file__).parent / "funda_tracking.json"
SUMMARY_FILE = Path(__file__).parent / "funda_run_summary.json"


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


def _detail_url(d: dict) -> str:
    url = d.get("detail_url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    return url


def schrijf_run_summary(nieuw: list[dict], bekend: list[dict], afgewezen: list[tuple[dict, list[str]]]) -> None:
    """Schrijf compacte run-uitkomst voor GitHub Actions notificaties."""
    def item(d: dict) -> dict:
        prijs = int(d.get("price") or 0)
        m2 = int(d.get("living_area") or 0)
        return {
            "id": str(d.get("global_id") or d.get("listing_id") or d.get("detail_url") or ""),
            "title": d.get("title") or "Woning",
            "city": d.get("city") or "",
            "neighbourhood": d.get("neighbourhood") or "",
            "price": prijs,
            "living_area": m2,
            "energy_label": d.get("energy_label") or "?",
            "url": _detail_url(d),
        }

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "nieuw_count": len(nieuw),
        "bekend_count": len(bekend),
        "afgewezen_count": len(afgewezen),
        "nieuw": [item(d) for d in nieuw],
    }
    SUMMARY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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


def is_begane_grond(tekst: str, details_data: dict | None = None) -> list[str]:
    # 1) Structured data wint: Funda's "Gelegen op" / floor-veld is betrouwbaarder dan tekst.
    if details_data:
        for sleutel in ("floor_level", "floor", "located_on", "gelegen_op"):
            waarde = details_data.get(sleutel)
            if not waarde:
                continue
            w = str(waarde).lower().strip()
            if any(m in w for m in ("begane grond", "souterrain", "parterre", "gelijkvloers")):
                return [f"{sleutel}: {w}"]
            # Hoger dan begane grond gevonden via structured veld -> niet begane grond.
            for cijfer in ("1e", "2e", "3e", "4e", "5e", "6e", "7e", "8e", "9e"):
                if cijfer in w:
                    return []
    # 2) Fallback: tekstmatch op specifieke trefwoorden (geen bare "souterrain", dat triggert op bergingen).
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


def auto_push() -> None:
    """Add, commit en push docs/ naar GitHub. Skip als geen wijzigingen of bij --no-push."""
    if "--no-push" in sys.argv:
        log("Auto-push overgeslagen (--no-push).")
        return
    folder = Path(__file__).parent
    docs_dir = folder / "docs"
    if not docs_dir.exists():
        log("Geen docs/ folder, push overgeslagen.")
        return
    try:
        subprocess.run(["git", "-C", str(folder), "add", "docs/"], capture_output=True, timeout=10)
        diff = subprocess.run(
            ["git", "-C", str(folder), "diff", "--cached", "--quiet"],
            capture_output=True, timeout=10,
        )
        if diff.returncode == 0:
            log("Geen docs-wijzigingen, push overgeslagen.")
            return
        msg = f"auto: rapport {datetime.now():%Y-%m-%d %H:%M}"
        subprocess.run(
            ["git", "-C", str(folder), "commit", "-m", msg],
            capture_output=True, timeout=10,
        )
        push = subprocess.run(
            ["git", "-C", str(folder), "push"],
            capture_output=True, timeout=60,
        )
        if push.returncode == 0:
            log("Gepusht naar GitHub.")
        else:
            err = push.stderr.decode("utf-8", errors="ignore")[:300]
            log(f"Push fout: {err}")
    except subprocess.TimeoutExpired:
        log("Git push timeout (>60s).")
    except FileNotFoundError:
        log("Git niet gevonden in PATH, push overgeslagen.")
    except Exception as exc:
        log(f"Auto-push fout: {exc}")


def laad_blacklist() -> set[str]:
    if BLACKLIST_FILE.exists():
        try:
            return set(json.loads(BLACKLIST_FILE.read_text()))
        except Exception:
            return set()
    return set()


# === Prijs- en looptijd-tracking ===

def laad_tracking() -> dict:
    if TRACKING_FILE.exists():
        try:
            return json.loads(TRACKING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def bewaar_tracking(tracking: dict) -> None:
    TRACKING_FILE.write_text(json.dumps(tracking, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_pub_datum(details_data: dict | None) -> str | None:
    """Haal publicatiedatum (aangeboden sinds) uit detaildata. ISO-datum of None."""
    if not details_data:
        return None
    for sleutel in ("publication_date", "listed_since", "offered_since",
                    "aangeboden_sinds", "date_published", "publish_date"):
        waarde = details_data.get(sleutel)
        if not waarde:
            continue
        s = str(waarde).strip()
        # Pak de eerste YYYY-MM-DD die we tegenkomen.
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return m.group(0)
        # Of een NL-datum dd-mm-yyyy.
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def update_tracking(tracking: dict, sleutel: str, prijs: int, pub_datum: str | None) -> dict:
    """Werk tracking bij voor een woning. Geeft afgeleide flags terug."""
    vandaag = datetime.now().strftime("%Y-%m-%d")
    rec = tracking.get(sleutel)
    if rec is None:
        rec = {"first_seen": vandaag, "last_seen": vandaag,
               "prices": [[vandaag, prijs]], "pub_datum": pub_datum}
        tracking[sleutel] = rec
    else:
        rec["last_seen"] = vandaag
        if pub_datum and not rec.get("pub_datum"):
            rec["pub_datum"] = pub_datum
        prijzen = rec.get("prices") or []
        if not prijzen or prijzen[-1][1] != prijs:
            prijzen.append([vandaag, prijs])
        rec["prices"] = prijzen

    # Afgeleide flags.
    prijzen = rec.get("prices") or [[vandaag, prijs]]
    eerste_prijs = prijzen[0][1]
    top_prijs = max(p for _, p in prijzen)
    gedaald = prijs < top_prijs
    drop_bedrag = top_prijs - prijs if gedaald else 0
    drop_pct = round(drop_bedrag / top_prijs * 100, 1) if (gedaald and top_prijs) else 0.0
    laatste_wijziging = prijzen[-1][0] if len(prijzen) > 1 else None

    # Dagen op funda: liefst echte publicatiedatum, anders sinds wij volgen.
    bron_datum = rec.get("pub_datum") or rec.get("first_seen")
    dagen_bron = "funda" if rec.get("pub_datum") else "gevolgd"
    try:
        d0 = datetime.strptime(bron_datum, "%Y-%m-%d")
        dagen = (datetime.now() - d0).days
    except Exception:
        dagen, dagen_bron = 0, "onbekend"

    return {
        "dagen": dagen,
        "dagen_bron": dagen_bron,
        "gedaald": gedaald,
        "drop_bedrag": drop_bedrag,
        "drop_pct": drop_pct,
        "eerdere_prijs": top_prijs if gedaald else None,
        "eerste_prijs": eerste_prijs,
        "laatste_wijziging": laatste_wijziging,
    }


# === Hoofdroutine ===

def main() -> None:
    debug_wijken = "--debug-wijken" in sys.argv
    f = Funda()
    seen = laad_state()
    mode = " (debug-wijken)" if debug_wijken else ""
    log(f"Start{mode}. Postcode {POSTCODE}, radius {RADIUS_KM}km. Reeds gezien: {len(seen)}.")

    # Zoek per prijsband los, zodat we onder Funda's resultaatkap (~140) blijven
    # en ook woningen vinden die al lang te koop staan. Dedup op id.
    banden = maak_prijs_banden(PRIJS_MIN, PRIJS_MAX, PRIJS_BAND_STAP)
    rauwe = []
    gezien_ids: set[str] = set()
    for band_min, band_max in banden:
        band_n = 0
        for sort in ZOEK_SORTS:
            sort_n = 0
            sort_label = sort or "standaard"
            for pagina in range(PAGINAS):
                try:
                    results = f.search_listing(
                        location=POSTCODE,
                        radius_km=RADIUS_KM,
                        offering_type="buy",
                        price_min=band_min,
                        price_max=band_max,
                        object_type=["apartment"],
                        availability=["available"],
                        area_min=M2_MIN,
                        sort=sort,
                        page=pagina,
                    )
                except Exception as exc:
                    log(f"Fout band {band_min}-{band_max} sort {sort_label} pagina {pagina}: {exc}")
                    break
                if not results:
                    break
                for r in results:
                    d = r.data
                    lid = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
                    if lid in gezien_ids:
                        continue
                    gezien_ids.add(lid)
                    rauwe.append(r)
                    sort_n += 1
                    band_n += 1
                time.sleep(0.4)
            log(f"Band € {band_min:,}-{band_max:,} ({sort_label}): {sort_n} nieuw.")
        log(f"Band € {band_min:,}-{band_max:,}: {band_n} uniek na alle sorteringen.")

    log(f"Totaal opgehaald (na dedup): {len(rauwe)}.")

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
    pub_data: dict[str, str | None] = {}  # publicatiedatum per woning (indien gevonden)
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

            bg = is_begane_grond(tekst, details_data)
            if bg:
                redenen.append(f"begane grond ({bg[0]})")

            if EIS_BUITENRUIMTE and not heeft_buitenruimte(details_data, tekst):
                redenen.append("geen buitenruimte")

            if redenen:
                afgewezen.append((d, redenen))
            else:
                pub_data[sleutel] = _parse_pub_datum(details_data)
                goed.append(d)
            time.sleep(0.5)
        except Exception as exc:
            log(f"Detail fout {lid}: {exc} - tonen by default.")
            goed.append(d)

    # Werk prijs-/looptijd-tracking bij en hang afgeleide flags aan elke woning.
    tracking = laad_tracking()
    n_gedaald = n_lang = 0
    for d in goed:
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        prijs = int(d.get("price") or 0)
        flags = update_tracking(tracking, sleutel, prijs, pub_data.get(sleutel))
        d["_track"] = flags
        if flags["gedaald"]:
            n_gedaald += 1
        if flags["dagen"] >= LANG_OP_FUNDA_DAGEN:
            n_lang += 1
    bewaar_tracking(tracking)
    log(f"Prijsdaling: {n_gedaald}. Lang op funda (>={LANG_OP_FUNDA_DAGEN}d): {n_lang}.")

    # Splits in nieuw vs eerder gezien.
    nieuw, bekend = [], []
    for d in goed:
        lid = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        (nieuw if lid not in seen else bekend).append(d)

    # Sorteer: prijsdalers eerst, dan lang-op-funda (onderhandelkansen),
    # twijfelbuurten naar onderen, daarna op prijs.
    def sort_key(d: dict):
        buurt = (d.get("neighbourhood") or "")
        twijfel = is_twijfelbuurt(buurt) is not None
        tr = d.get("_track") or {}
        gedaald = bool(tr.get("gedaald"))
        lang = tr.get("dagen", 0) >= LANG_OP_FUNDA_DAGEN
        return (not gedaald, not lang, twijfel, d.get("price", 0))

    nieuw.sort(key=sort_key)
    bekend.sort(key=sort_key)
    schrijf_run_summary(nieuw, bekend, afgewezen)

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

            # Open HTML rapport in browser bij interactieve run.
            # Niet bij Task Scheduler (sys.stdout.isatty() is dan False).
            wil_open = "--open" in sys.argv or (
                "--no-open" not in sys.argv and sys.stdout.isatty()
            )
            if wil_open:
                import webbrowser
                lokaal = Path(__file__).parent / "funda_rapport.html"
                if lokaal.exists():
                    webbrowser.open(lokaal.as_uri())
        except Exception as exc:
            log(f"Rapport-fout: {exc}")

    # Auto-push docs/ naar GitHub (skipt zelf als er geen wijzigingen zijn).
    auto_push()


def toon(d: dict, prefix: str = "") -> None:
    prijs = d.get("price", 0)
    m2 = d.get("living_area", 0) or 0
    ppm = prijs // m2 if m2 else 0
    label = d.get("energy_label", "?")
    nhg = " | NHG-label" if label in NHG_LABELS else ""
    buurt = d.get("neighbourhood", "")
    twijfel = is_twijfelbuurt(buurt)
    flag = f" /!\\ TWIJFELBUURT ({twijfel})" if twijfel else ""

    tr = d.get("_track") or {}
    if tr.get("gedaald"):
        flag += f" /!\\ PRIJS GEDAALD -€{tr['drop_bedrag']:,} ({tr['drop_pct']}%)"
    if tr.get("dagen", 0) >= LANG_OP_FUNDA_DAGEN:
        bron = "" if tr.get("dagen_bron") == "funda" else "+"
        flag += f" /!\\ LANG OP FUNDA ({tr['dagen']}{bron}d)"

    url = d.get("detail_url", "")
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    print(f"\n[{prefix}] € {prijs:,} | {m2} m2 (€{ppm}/m2) | label {label}{nhg}{flag}")
    print(f"  {d.get('title')}, {d.get('postcode')} {d.get('city')}")
    print(f"  Wijk: {buurt}")
    print(f"  {d.get('bedrooms')} slpk | {d.get('rooms')} kamers")
    if tr.get("gedaald") and tr.get("eerdere_prijs"):
        print(f"  Was € {tr['eerdere_prijs']:,}, nu € {prijs:,} (wijziging {tr.get('laatste_wijziging')})")
    print(f"  {url}")


if __name__ == "__main__":
    main()
