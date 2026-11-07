"""Beoordelingsmodel voor het woningrapport: poort, score, uitleg en sortering.

Pure functies: geen netwerk, geen bestanden behalve de tabel in data/, geen import van
funda_rapport of funda_zoek. Importeren kan zonder funda_personal.json. Ontwerp:
beoordeling.md (model v3) met de 23 auditfixes uit paragraaf 12 en de besluiten van de
eigenaar van 7 november 2026.

Drie lagen
==========
A. Filters (funda_zoek.py, ongewijzigd): komt een woning in het rapport?
B. Poort: Past, Krap, Past niet of Prijs onbekend. Kun je het lenen (leentoets 2026 en
   eigen geld) en wil je het elke maand betalen (netto woonlasten tegenover je grens)?
C. Score van 0 tot 10 binnen de groep. 5 betekent: voldoet aan je eisen. Elk onderdeel
   is begrensd, heeft een gewicht en een korte tekst. Onbekend telt nooit als minpunt.

Publieke functies
=================
laad_config(personal) -> dict
    Standaardwaarden (STANDAARD) samengevoegd met personal["beoordeling"]; het blok
    personal["financien"] komt ongewijzigd mee als cfg["financien"].
beoordeel(d, details, routes, twijfel, profiel, config, verrijking=None, *, rente=None, vandaag=None) -> dict
    De beoordeling van één woning volgens het datacontract (beoordeling.md par. 9).
poort(woning, cfg, fin) -> dict
    Harde eisen plus de financiële uitkomst: {"poort", "redenen", "harde"}.
poort_financieel(tekort, over, cfg) -> str
    Alleen de drempels: PAST, KRAP of PAST NIET.
status_kort(poort, fin, harde, cfg) -> str     'Past · € 196 onder je grens' (spec.md 4.2)
uitleg_regel(score, onderdelen, n_onbekend, max_len=96, begrensd=False) -> str
financiering(woning, cfg, profiel, rente=None, vandaag=None) -> dict
    Leentoets per scenario, kosten koper, tekort, woonlasten en de financiële poort.
    woning = {"prijs", "label", "canon_jaar", "vve", "vve_bron", "energie", "stook_in_vve", "woz"}.
financien_invoer(cfg, profiel, vandaag=None) -> dict
    Het financien-blok (of het oude profiel) in één vaste vorm.
leentoets(toetsinkomen, rente, rentevast_jaren=30, label=None, canon_jaar=0,
          studieschuld_maand=0, bkr_maand=0, alleenstaand=False) -> dict
max_hypotheek(...) -> int                      zelfde invoer als leentoets()
max_koopsom(max_hyp, eigen_geld, starter=True, kk_vast=..., nhg_pct=..., jaar=2026) -> int
kosten_koper(koopsom, hypotheek, starter, kk_vast=..., nhg_pct=..., jaar=2026) -> (int, str)
tabel() -> dict                                data/trhk_2026_tabel1.json (jaar, tabel, labelbedragen)
label_bedrag(label) -> int                     bedrag per energielabel (art. 4 lid 3)
fl_pct(toetsinkomen, toetsrente) -> float      financieringslastpercentage als fractie
toetsrente(rente, rentevast_jaren) -> float
studieschuld_weging(toetsrente) -> float
annuiteit(hoofdsom, rente, maanden=360) -> float
rente_uit_config(cfg, vandaag=None) -> dict    zelfde vorm als funda_rente.huidige_rente()
scenario_overzicht(cfg, profiel, rente=None, vandaag=None, label=None, canon_jaar=0) -> list
    Max. hypotheek en max. koopsom per scenario zonder een specifieke woning (voor de voet).
POORT_RANG, sorteer_sleutel(rij), sorteer(rijen) -> rijen
log_kenmerk_labels(details_lijst) -> dict[str, int]
Parsers (kenmerken eerst, tekst als terugval): energielabel, vve_maand, stookkosten_in_vve,
erfpacht, buitenruimte, woonlaag, vve_status, lees_advertentie, prijshistorie.

Wat beoordeel() leest
=====================
d (zoekresultaat, zelfde vorm als pyfunda Listing.data) en details (Listing.data van de
detail-call; mag None zijn). Uit beide samen: price (eerst uit d), living_area,
energy_label, title, city, neighbourhood, construction_year, description,
characteristics, is_auction, is_fixer_upper, is_monument, has_balcony, has_roof_terrace,
has_garden, has_parking_on_site, has_parking_enclosed, open_house.
Uit d alleen: _track (eigen tracking: gedaald, drop_bedrag, eerdere_prijs, dagen),
_enrichment (price_history met changes of een lijst, market met
avg_asking_price_per_m2, broker met name, review_average, review_count) en _twijfel
(als twijfel None is).
routes: [{"label", "km", "soort": "weg"|"schatting"}]. twijfel: korte zinnen uit
funda_zoek (bijv. "Twijfelbuurt Leyenburg (jouw lijst)."). verrijking: per bron
{"status": "ok"|"onbekend"|"budget"|"uit"|"niet_nodig", "data": {...}, "reden": str}
of direct de data (vorm van verrijking_stub.json). rente: dict uit
funda_rente.huidige_rente(): {"pct", "bron", "datum", "oud", "melding"}. Zonder rente:
de rente uit de config (financien.rente, dan beoordeling.financiering.rente), anders
STANDAARD_RENTE (4,11%, 6 juli 2026).

Uitvoer (naast beoordeling.md par. 9)
=====================================
financiering["scenarios"]: [{"id", "label", "max_hypotheek", "max_koopsom", "past"}], alleen
voor de scenario's uit financien.scenarios, met het energielabel en de erfpachtcanon van deze
woning. past = tekort aan eigen geld (na buffer) hooguit kk_onzekerheid; de woonlasten tellen
daar niet in mee, die bepalen de poort. Leeg zonder financien-blok en bij Prijs onbekend.
financiering["planning"]: id van het planningsscenario (de poort volgt dat scenario), of None.
financiering["scenario_tekst"]: "Past nu", "Past vanaf jan 2027", "Alleen met cao-verhoging"
of "Past in geen scenario"; nooit een inkomensbedrag. None zonder scenario's.

Config
======
Sleutel "beoordeling" in funda_personal.json (in Actions: secret FUNDA_PERSONAL_JSON).
Alles is optioneel; de standaard staat in STANDAARD hieronder.

    "beoordeling": {
      "score_basis": 5, "m2_wens": 70, "max_woonlaag_zonder_lift": 2,
      "fiets_kmu": 15, "lang_op_funda_dagen": 90,
      "max_woonlasten_netto": null,   jouw grens voor netto woonlasten per maand;
                                      null = bruto norm (33% van het bruto maandinkomen)
      "krap_marge": 150,              Krap tot zoveel euro boven je grens, daarboven Past niet
      "financiering": {"alleenstaand": true, "overbod_pct": 0.0,
                       "kk_onzekerheid": 1500, "eigen_geld_tekort_past_niet": 5000,
                       "starter_tot": null},
      "harde_eisen": {"veiling": true, "kluswoning": false, "slapende_vve": false,
                      "max_woonlaag_zonder_lift": null},
      "werk": {"gewicht": null, "km_goed": 4, "km_slecht": 10},
      "gewichten": {"woonlasten": 1, ..., "parkeren": 0},
      "drempels": {...}, "verrijking": {...}     (zie STANDAARD)
    }

Sleutel "financien" in funda_personal.json (naast "beoordeling"; persoonlijke cijfers,
alleen in de secret, nooit in de repo):

    "financien": {
      "alleenstaand": true,
      "starter_tot": "JJJJ-MM-DD",       startersvrijstelling tot deze datum; leeg = leeftijd < 35
      "planning": "2027_01",             scenario voor de poort; standaard 2027_01, anders het eerste
      "scenarios": {
        "nu":              {"bruto_jaar": 0, "label": "Nu"},
        "2027_01":         {"bruto_jaar": 0, "label": "Vanaf jan 2027"},
        "2027_01_met_cao": {"bruto_jaar": 0, "label": "Met cao-verhoging"}
      },                                 bruto_jaar = toetsinkomen; een kaal getal mag ook.
                                         Optioneel per scenario: "datum" (anders uit de id:
                                         2027_01 = 1 januari 2027, nu = vandaag) en "eigen_geld".
      "studieschuld": {"maandlast": 0},  werkelijke maandlast DUO
      "bkr": [{"limiet": 0, "opgezegd": true}],   doorlopend krediet; aflopend: {"maandlast": 0}
      "eigen_geld": {"nu": 0, "datum": "JJJJ-MM-DD", "per_maand": 0, "buffer": 0},
                                         eigen geld op een scenariodatum = nu + per_maand x hele
                                         maanden sinds "datum" (leeg = vandaag); buffer gaat eraf
      "kosten_koper": {"vast": 6000, "nhg_pct": 0.4},   vaste posten in euro; NHG in procent
      "rente": {"pct": 4.11, "datum": "JJJJ-MM-DD", "rentevast_jaren": 10}
    }

Ook geaccepteerd (zelfde betekenis): "toetsinkomen": {id: bedrag} in plaats van
"scenarios", "startersvrijstelling_tot", "verplichtingen_maand": {"duo": x},
"bkr_limieten": x (som van niet opgezegde limieten), "buffer" op het hoogste niveau,
"eigen_geld": {id: bedrag} als vaste waarde per scenario, "rente": {"handmatig": x,
"rentevast_jaar": n}. Als terugval, alleen als je ze zelf zet: beoordeling.financiering.rente,
rente_datum, rentevast_jaren en rente_max_dagen (financien.rente gaat voor).

Zonder "financien" valt alles terug op de bestaande sleutels van het profiel:
bruto_jaar, eigen_inleg, duo_maandlast en leeftijd. Dan zijn er geen scenario's
(financiering.scenarios is leeg) en volgt de poort het profiel.

Bevolkingskenmerken (herkomst, nationaliteit, migratieachtergrond, inkomen of
opleiding van een buurt, huishoudsamenstelling, uitkeringen, leeftijdsopbouw) worden
nergens gelezen, bewaard of getoond.
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

TABEL_PAD = Path(__file__).resolve().parent / "data" / "trhk_2026_tabel1.json"

# ---------------------------------------------------------------------------------------
# Rekenregels en aannames, met bron en status (beoordeling.md par. 8). Eén blok.
# ---------------------------------------------------------------------------------------
# Uit de Staatscourant (data/trhk_2026_tabel1.json, gecontroleerd 6 nov 2026): tabel 1,
# bedragen per energielabel, alleenstaandenbedrag.
#
# Niet in die Staatscourant, wel in de Tijdelijke regeling hypothecair krediet zelf of in
# de gedragscode; niet opnieuw nagelezen in de lokale bronnen:
TOETSRENTE_KORT = 0.05          # rentevast korter dan 10 jaar: AFM-toetsrente 5% (AFM, Q2/Q3 2026; Q4 aangenomen)
RENTEVAST_MIN_JAREN = 10        # vanaf 10 jaar vast toetsen op de werkelijke rente
# Studieschuld: de werkelijke maandlast keer een wegingsfactor per kolom van tabel 1
# (regeling sinds 2024). Kolommen 3,501 tot 4,000% (1,20) en 4,001 tot 4,500% (1,25) zijn
# bevestigd met een tweede bron (de berekening van een adviseur, 7 nov 2026); de overige
# factoren komen uit de regeling van 2024 en zijn niet opnieuw nagelezen.
STUDIESCHULD_WEGING = [1.05, 1.05, 1.10, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.45, 1.50]
BKR_PCT_LIMIET = 0.02           # Gedragscode Hypothecaire Financieringen 2020, art. 4 lid 5: 2% van de limiet per maand
LOOPTIJD_MAANDEN = 360          # annuïteit, 30 jaar
# Fiscaal 2026 (audit, secundaire bronnen HomeFinance en ABN AMRO):
HRA_TARIEF_2026 = 0.3756        # maximaal aftrektarief
EWF_2026 = 0.0035               # eigenwoningforfait
# Kosten koper (NHG: Volkshuisvesting Nederland 8 okt 2025; startersvrijstelling: SRA, jan 2026):
NHG_GRENS = {2026: 470_000}                     # met energiebesparing 498.200 (niet gebruikt)
NHG_PREMIE = 0.004
STARTERS_GRENS = {2026: 555_000, 2027: 615_000}  # woningwaardegrens startersvrijstelling
STARTER_LEEFTIJD_TOT = 35
OVB_EIGEN_WONING = 0.02
KK_VAST_STANDAARD = 6_000       # notaris 1.500, taxatie 700, advies 3.000, bank 450, overig 350 (aanname)
# Woonlasten (aannames, niet gemeten):
VVE_GESCHAT = 175               # VvE-bijdrage als die nergens staat
OVERIG_MAAND = 160              # gemeente, water, inboedel; opstal zit bij een appartement in de VvE
STOOK_IN_VVE_FACTOR = 0.4       # stookkosten in de VvE-bijdrage: alleen elektra over
ENERGIE_PER_LABEL = {"A++++": 60, "A+++": 70, "A++": 80, "A+": 90, "A": 100, "B": 130, "C": 170,
                     "D": 220, "E": 280, "F": 340, "G": 400}   # per maand per 75 m² (CBS-gemiddelde, secundair)
ENERGIE_ONBEKEND = 280
WOZ_TERUGVAL = 0.9              # geen WOZ bekend: 90% van de koopsom voor het eigenwoningforfait
NORM_BRUTO_PCT = 0.33           # terugval zonder eigen netto grens (oude norm uit funda_rapport)
# Standaardrente als er geen rente-parameter en geen rente in de config is:
STANDAARD_RENTE = {"pct": 4.11, "datum": "2026-07-06", "rentevast_jaren": 30,
                   "omschrijving": "NHG, 30 jaar vast, laagste aanbieder (Van Bruggen, 6 juli 2026)"}

POORT_RANG = {"PAST": 0, "KRAP": 1, "PAST NIET": 2, "PRIJS ONBEKEND": 3}
POORT_NAAM = {"PAST": "Past", "KRAP": "Krap", "PAST NIET": "Past niet", "PRIJS ONBEKEND": "Prijs onbekend"}

STANDAARD: dict = {
    "score_basis": 5,
    "m2_wens": 70,
    "max_woonlaag_zonder_lift": 2,
    "fiets_kmu": 15,
    "lang_op_funda_dagen": 90,
    "max_woonlasten_netto": None,
    "krap_marge": 150,
    "financiering": {
        "alleenstaand": True,
        # Rente, rentevast en de leeftijdsgrens staan in financien.rente (één plek). De oude sleutels
        # rente, rente_datum, rentevast_jaren en rente_max_dagen hier werken nog als terugval
        # (funda_rapport._rente_cfg), maar alleen als je ze zelf zet; daarom geen standaardwaarde.
        "rente": None,
        "overbod_pct": 0.0,
        "kk_onzekerheid": 1500,
        "eigen_geld_tekort_past_niet": 5000,
        "starter_tot": None,
    },
    "harde_eisen": {"veiling": True, "kluswoning": False, "slapende_vve": False,
                    "max_woonlaag_zonder_lift": None},
    "werk": {"gewicht": None, "km_goed": 4, "km_slecht": 10},
    "gewichten": {
        "woonlasten": 1, "buitenruimte": 1, "oppervlak": 1, "woonlaag_lift": 1, "reisafstand": 1,
        "energielabel": 1, "erfpacht": 1, "vve": 1, "fundering": 1, "geluid": 1, "buurt": 1,
        "staat": 1, "clausules": 1, "markt": 1, "parkeren": 0,
        "_bereik": {
            "woonlasten": [-1.5, 1.5], "buitenruimte": [-1.5, 1.5], "oppervlak": [-1.0, 1.0],
            "woonlaag_lift": [-1.5, 0.0], "reisafstand": [-1.0, 1.0], "energielabel": [-1.0, 0.0],
            "erfpacht": [-2.0, 0.0], "vve": [-1.5, 0.5], "fundering": [-2.0, 0.5], "geluid": [-1.5, 0.0],
            "buurt": [-1.0, 0.5], "staat": [-1.5, 0.0], "clausules": [-1.0, 0.0], "markt": [-0.5, 0.5],
            "parkeren": [0.0, 0.5],
        },
    },
    "drempels": {
        "woonlasten_ruim_onder_grens": 100,
        "buitenruimte_balkon_min_m2": 4,
        "oppervlak_stap_m2": 20,
        "erfpacht_afkoop_kort_jaren": 10,
        "erfpacht_afkoop_middel_jaren": 25,
        "energielabel_slecht": ["F", "G"],
        "energielabel_goed": ["A", "A+", "A++", "A+++", "A++++", "B"],
        "vve_klein_max_woningen": 4,
        "vve_bijdrage_laag_per_m2": 1.0,
        "vve_bijdrage_hoog_per_m2": 3.0,
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
        "markt_afwijking_pct": 10,
        "inhoud_per_m2_hoog": 3.3,
        "bouwjaar_verschil_bag_funda": 5,
    },
    "verrijking": {
        "aan": True,
        "bronnen": {"bag": True, "fundering": True, "geluid": True, "buurt": True, "tevredenheid": True},
        "max_calls_per_run": 60, "timeout_s": 10, "pauze_s": 0.25, "fout_opnieuw_na_dagen": 1,
        "bewaar_dagen": {"bag": 180, "fundering": 365, "geluid": 365, "buurtcode": 365,
                         "leefbaarometer": 30, "tevredenheid": 90},
    },
}

OORDEEL_GROEP = {"sterk": "let_op", "let_op": "let_op", "goed": "plus", "neutraal": "info",
                 "onbekend": "onbekend", "kans": "kans"}
LBM_KLASSE = {1: "zeer onvoldoende", 2: "ruim onvoldoende", 3: "onvoldoende", 4: "zwak", 5: "voldoende",
              6: "ruim voldoende", 7: "goed", 8: "zeer goed", 9: "uitstekend"}
FUND_KLASSE = ["zeer laag", "laag", "matig", "hoog", "zeer hoog"]
VRAGEN_ALTIJD = ["Vraag de VvE-stukken: notulen van 2 jaar, MJOP, reservefonds en begroting.",
                 "Zoek op officielebekendmakingen.nl naar vergunningen op dit adres."]
_MAANDEN_KORT = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
_MAANDEN_NL = {m: i + 1 for i, m in enumerate(_MAANDEN_KORT)} | {"mar": 3, "may": 5, "oct": 10, "maa": 3}


# ---------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------
def _merge(basis: dict, extra: dict) -> dict:
    uit = copy.deepcopy(basis)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(uit.get(k), dict):
            uit[k] = _merge(uit[k], v)
        else:
            uit[k] = copy.deepcopy(v)
    return uit


def laad_config(personal: dict | None) -> dict:
    """personal["beoordeling"] over STANDAARD heen; ontbrekend = standaard.

    Oude plekken uit beoordeling.md par. 10 werken ook: financiering.max_woonlasten_netto
    en financiering.woonlasten_marge_past_niet. De nieuwe plek gaat voor. Het blok
    personal["financien"] komt mee als cfg["financien"] (of None).
    """
    personal = personal if isinstance(personal, dict) else {}
    eigen = personal.get("beoordeling") if isinstance(personal.get("beoordeling"), dict) else {}
    cfg = _merge(STANDAARD, eigen)
    fin_eigen = eigen.get("financiering") if isinstance(eigen.get("financiering"), dict) else {}
    if eigen.get("max_woonlasten_netto") is None and fin_eigen.get("max_woonlasten_netto") is not None:
        cfg["max_woonlasten_netto"] = fin_eigen["max_woonlasten_netto"]
    if "krap_marge" not in eigen and fin_eigen.get("woonlasten_marge_past_niet") is not None:
        cfg["krap_marge"] = fin_eigen["woonlasten_marge_past_niet"]
    if "lang_op_funda_dagen" not in eigen and personal.get("lang_op_funda_dagen") is not None:
        cfg["lang_op_funda_dagen"] = personal["lang_op_funda_dagen"]
    fin = personal.get("financien")
    if not isinstance(fin, dict):
        fin = eigen.get("financien") if isinstance(eigen.get("financien"), dict) else None
    cfg["financien"] = copy.deepcopy(fin)
    return cfg


# ---------------------------------------------------------------------------------------
# Opmaak: één formatter (P3 notatie)
# ---------------------------------------------------------------------------------------
MIN = "\u2212"   # minteken (U+2212), geen streepje


def eur(x) -> str:
    """'€ 1.250', negatief '−€ 1.250'."""
    n = int(round(float(x or 0)))
    return (MIN if n < 0 else "") + "€ " + f"{abs(n):,}".replace(",", ".")


def nl(x: float, d: int = 1) -> str:
    s = f"{abs(float(x)):.{d}f}".replace(".", ",")
    return (MIN if float(x) < 0 and s.strip("0,") else "") + s


def teken(p: float) -> str:
    return ("+" if p >= 0 else MIN) + nl(abs(p))


def _kap(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _rond1(x: float) -> float:
    return math.floor(x * 10 + 0.5) / 10


def _datum(x, standaard: date | None = None) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str) and x.strip():
        try:
            return date.fromisoformat(x.strip()[:10])
        except ValueError:
            return standaard
    return standaard


def _getal(s) -> int | None:
    """'€ 1.250,-' -> 1250, '€ 95,50' -> 95, '18 m²' -> 18."""
    if isinstance(s, (int, float)):
        return int(s)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2}|,-)?", str(s or ""))
    return int(m.group(1).replace(".", "")) if m else None


def _als_fractie(x, grens: float) -> float | None:
    """Percentage of fractie: waarden vanaf `grens` zijn procenten (4.2 -> 0.042)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v / 100, 8) if v >= grens else v


# ---------------------------------------------------------------------------------------
# Leentoets 2026
# ---------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def tabel() -> dict:
    """data/trhk_2026_tabel1.json, met de rijen als {int: [percentages]}."""
    t = json.loads(TABEL_PAD.read_text(encoding="utf-8"))
    t["_rijen"] = {int(k): v for k, v in t["tabel"].items()}
    return t


def _kolom(toetsrente: float) -> int:
    pct = round(float(toetsrente) * 100, 3)
    for i, grens in enumerate(tabel()["rente_bovengrens_pct"]):
        if grens is None or pct <= grens + 1e-9:
            return i
    return len(tabel()["rente_bovengrens_pct"]) - 1


def fl_pct(toetsinkomen: float, toetsrente: float) -> float:
    """Financieringslastpercentage uit tabel 1 als fractie (62.000 en 4,11% -> 0.236)."""
    rijen = tabel()["_rijen"]
    rij = max((k for k in rijen if k <= (toetsinkomen or 0)), default=min(rijen))
    return rijen[rij][_kolom(toetsrente)] / 100


def toetsrente(rente: float, rentevast_jaren: int | None) -> float:
    """Werkelijke rente bij 10 jaar of langer vast, anders minstens de AFM-toetsrente."""
    r = _als_fractie(rente, 0.2) or 0.0
    if rentevast_jaren is not None and rentevast_jaren < RENTEVAST_MIN_JAREN:
        return max(TOETSRENTE_KORT, r)
    return r


def studieschuld_weging(toetsrente_: float) -> float:
    return STUDIESCHULD_WEGING[_kolom(toetsrente_)]


def annuiteit(hoofdsom: float, rente: float, maanden: int = LOOPTIJD_MAANDEN) -> float:
    r = (_als_fractie(rente, 0.2) or 0.0) / 12
    if r <= 0:
        return hoofdsom / maanden
    return hoofdsom * r / (1 - (1 + r) ** -maanden)


def _label_sleutel(label: str | None) -> str | None:
    if not label:
        return None
    m = re.match(r"\s*([A-G])(\+{0,4})", str(label).upper())
    return (m.group(1) + m.group(2)) if m else None


def label_bedrag(label: str | None) -> int:
    """Bedrag dat buiten beschouwing blijft per energielabel (art. 4 lid 3). Onbekend = 0."""
    k = _label_sleutel(label)
    v = tabel()["label_bedragen"].get(k) if k else None
    return int(v) if isinstance(v, (int, float)) else 0


def leentoets(toetsinkomen: float, rente: float, rentevast_jaren: int | None = 30, label: str | None = None,
              canon_jaar: float | None = 0, studieschuld_maand: float = 0, bkr_maand: float = 0,
              alleenstaand: bool = False) -> dict:
    """Maximale hypotheek volgens de regeling 2026, met de tussenstappen.

    toegestane last = toetsinkomen x percentage(tabel 1) / 12
                      min erfpachtcanon / 12 (aanname, secundaire bron)
                      min studieschuld x wegingsfactor
                      min 2% van elke niet opgezegde kredietlimiet
    max hypotheek   = last / annuïteit(1 euro, toetsrente, 30 jaar)
                      + bedrag per energielabel + 17.000 als alleenstaand en toetsinkomen > 30.000
    """
    ink = float(toetsinkomen or 0)
    toets = toetsrente(rente, rentevast_jaren)
    pct = fl_pct(ink, toets)
    weging = studieschuld_weging(toets)
    last = ink * pct / 12
    aftrek_canon = float(canon_jaar or 0) / 12
    aftrek_studie = float(studieschuld_maand or 0) * weging
    aftrek_bkr = float(bkr_maand or 0)
    netto_last = max(0.0, last - aftrek_canon - aftrek_studie - aftrek_bkr)
    basis = netto_last / annuiteit(1, toets)
    t_al = tabel()["alleenstaand"]
    extra_al = int(t_al["bedrag"]) if alleenstaand and ink > t_al["toetsinkomen_hoger_dan"] else 0
    extra_label = label_bedrag(label)
    return {
        "toetsinkomen": ink, "toetsrente": toets, "fl_pct": pct, "toegestane_last": round(last, 2),
        "aftrek_canon": round(aftrek_canon, 2), "aftrek_studieschuld": round(aftrek_studie, 2),
        "studieschuld_weging": weging, "aftrek_bkr": round(aftrek_bkr, 2),
        "basis": int(basis), "label_bedrag": extra_label, "alleenstaand_bedrag": extra_al,
        "max_hypotheek": int(basis + extra_label + extra_al),
    }


def max_hypotheek(toetsinkomen: float, rente: float, rentevast_jaren: int | None = 30, label: str | None = None,
                  canon_jaar: float | None = 0, studieschuld_maand: float = 0, bkr_maand: float = 0,
                  alleenstaand: bool = False) -> int:
    return leentoets(toetsinkomen, rente, rentevast_jaren, label, canon_jaar, studieschuld_maand,
                     bkr_maand, alleenstaand)["max_hypotheek"]


def _per_jaar(tabel_: dict, jaar: int) -> int:
    """Waarde voor dat jaar, anders die van het laatste bekende jaar ervoor (of het eerste)."""
    eerder = [k for k in tabel_ if k <= jaar]
    return tabel_[max(eerder)] if eerder else tabel_[min(tabel_)]


def kosten_koper(koopsom: float, hypotheek: float, starter: bool, kk_vast: float = KK_VAST_STANDAARD,
                 nhg_pct: float = NHG_PREMIE, jaar: int = 2026) -> tuple[int, str]:
    """Vaste posten + NHG-premie over de hypotheek (tot de NHG-grens) + overdrachtsbelasting.

    Startersvrijstelling alleen tot de woningwaardegrens van dat jaar, anders 2%."""
    nhg = (_als_fractie(nhg_pct, 0.05) or 0.0) * hypotheek if hypotheek <= _per_jaar(NHG_GRENS, jaar) else 0.0
    vrij = starter and koopsom <= _per_jaar(STARTERS_GRENS, jaar)
    ovb = 0.0 if vrij else OVB_EIGEN_WONING * koopsom
    soort = "startersvrijstelling" if vrij else "2% overdrachtsbelasting"
    return int(round(float(kk_vast) + nhg + ovb)), soort


def max_koopsom(max_hyp: float, eigen_geld: float, starter: bool = True, kk_vast: float = KK_VAST_STANDAARD,
                nhg_pct: float = NHG_PREMIE, jaar: int = 2026) -> int:
    """Hoogste koopsom waarbij koopsom min hypotheek plus kosten koper uit eigen geld past.

    Lenen gaat tot de koopsom (100% van de waarde); kosten koper komen uit eigen geld."""
    nhg = _als_fractie(nhg_pct, 0.05) or 0.0
    vast = float(kk_vast)

    def past(k: float) -> bool:
        hyp = min(k, max_hyp)
        kk, _ = kosten_koper(k, hyp, starter, vast, nhg, jaar)
        return k - hyp + kk <= eigen_geld + 0.5

    # Boven de max. hypotheek: k - max_hyp + vast + premie + ovb(k) <= eigen geld.
    premie = nhg * max_hyp if max_hyp <= _per_jaar(NHG_GRENS, jaar) else 0.0
    kandidaten = [max_hyp + eigen_geld - vast - premie,
                  (max_hyp + eigen_geld - vast - premie) / (1 + OVB_EIGEN_WONING),
                  float(_per_jaar(STARTERS_GRENS, jaar))]
    # Onder de max. hypotheek (eigen geld dekt niet eens de kosten koper): vast + nhg x k + ovb(k) <= eigen geld.
    for tarief in (nhg, nhg + OVB_EIGEN_WONING):
        if tarief > 0:
            kandidaten.append((eigen_geld - vast) / tarief)
    beste = 0
    for k in kandidaten:
        k = int(math.floor(k))
        if k > beste and past(k):
            beste = k
    return beste


# ---------------------------------------------------------------------------------------
# Rente
# ---------------------------------------------------------------------------------------
def rente_uit_config(cfg: dict, vandaag=None) -> dict:
    """Rente-dict in de vorm van funda_rente.huidige_rente(), zonder netwerk.

    Volgorde: financien.rente, dan beoordeling.financiering.rente, dan STANDAARD_RENTE."""
    vandaag = _datum(vandaag, date.today())
    fin = (cfg or {}).get("financien") or {}
    r = fin.get("rente") if isinstance(fin.get("rente"), dict) else {}
    f = (cfg or {}).get("financiering") or {}
    pct = r.get("pct") if r.get("pct") is not None else r.get("handmatig")
    if pct is not None:
        bron, datum = "handmatig", r.get("datum")
    elif f.get("rente") is not None:
        pct, bron, datum = f["rente"], "handmatig", f.get("rente_datum")
    else:
        pct, bron, datum = STANDAARD_RENTE["pct"], "standaard", STANDAARD_RENTE["datum"]
    frac = _als_fractie(pct, 0.2)
    d = _datum(datum)
    max_dagen = int(r.get("max_dagen") or f.get("rente_max_dagen") or 30)   # zelfde grens als funda_rente
    dagen = (vandaag - d).days if d else None
    oud = dagen is None or dagen > max_dagen
    melding = None
    if oud:
        melding = (f"Rente is {dagen} dagen oud: woonlasten kunnen afwijken." if dagen is not None
                   else "Rente zonder datum: woonlasten kunnen afwijken.")
    return {"pct": round(frac * 100, 3), "bron": bron, "datum": d.isoformat() if d else None,
            "oud": oud, "melding": melding}


def _rentevast(rente: dict | None, cfg: dict) -> int:
    for bron in ((rente or {}), ((cfg.get("financien") or {}).get("rente") or {})):
        for k in ("rentevast_jaren", "rentevast_jaar"):
            if isinstance(bron, dict) and bron.get(k) is not None:
                return int(bron[k])
    if (rente or {}).get("bron") == "standaard":
        return STANDAARD_RENTE["rentevast_jaren"]
    return int((cfg.get("financiering") or {}).get("rentevast_jaren") or 30)


# ---------------------------------------------------------------------------------------
# Financien: scenario's, eigen geld, verplichtingen
# ---------------------------------------------------------------------------------------
def _scenario_datum(sid: str, vandaag: date) -> date:
    m = re.match(r"^(\d{4})[_-](\d{1,2})", str(sid))
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return vandaag
    return vandaag


def _scenario_label(sid: str) -> str:
    if sid == "nu":
        return "Nu"
    m = re.match(r"^(\d{4})[_-](\d{1,2})", sid)
    if m and 1 <= int(m.group(2)) <= 12:
        tekst = f"Vanaf {_MAANDEN_KORT[int(m.group(2)) - 1]} {m.group(1)}"
        return tekst + (" met cao" if "cao" in sid else "")
    return sid.replace("_", " ")


def _maanden_tussen(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


def financien_invoer(cfg: dict, profiel: dict | None, vandaag=None) -> dict:
    """Normaliseer cfg["financien"] (of het oude profiel) tot één vaste vorm."""
    vandaag = _datum(vandaag, date.today())
    profiel = profiel or {}
    f_cfg = cfg.get("financiering") or {}
    raw = cfg.get("financien") if isinstance(cfg.get("financien"), dict) else None
    leeftijd = profiel.get("leeftijd")
    if raw is None:
        return {
            "bron": "profiel",
            "alleenstaand": bool(f_cfg.get("alleenstaand", True)),
            "starter_tot": _datum(f_cfg.get("starter_tot")),
            "leeftijd": leeftijd,
            "scenarios": [{"id": "profiel", "label": "Profiel", "bruto_jaar": float(profiel.get("bruto_jaar") or 0),
                           "datum": vandaag, "eigen_geld": float(profiel.get("eigen_inleg") or 0)}],
            "planning": "profiel",
            "studieschuld_maand": float(profiel.get("duo_maandlast") or 0),
            "bkr_maand": 0.0,
            "eigen_geld": {"nu": float(profiel.get("eigen_inleg") or 0), "datum": vandaag, "per_maand": 0.0, "vast": {}},
            "buffer": 0.0,
            "kk_vast": float(KK_VAST_STANDAARD),
            "nhg_pct": NHG_PREMIE,
        }

    # scenario's
    sc_raw = raw.get("scenarios")
    if sc_raw is None and isinstance(raw.get("toetsinkomen"), dict):
        sc_raw = raw["toetsinkomen"]
    lijst = []
    if isinstance(sc_raw, dict):
        items = list(sc_raw.items())
    elif isinstance(sc_raw, list):
        items = [(s.get("id"), s) for s in sc_raw if isinstance(s, dict) and s.get("id")]
    else:
        items = []
    for sid, v in items:
        if str(sid).startswith("_"):
            continue
        sid = str(sid)
        v = v if isinstance(v, dict) else {"bruto_jaar": v}
        ink = v.get("bruto_jaar", v.get("toetsinkomen"))
        if ink is None:
            continue
        datum = _datum(v.get("datum")) or _scenario_datum(sid, vandaag)
        lijst.append({"id": sid, "label": str(v.get("label") or _scenario_label(sid)),
                      "bruto_jaar": float(ink), "datum": max(datum, vandaag),
                      "eigen_geld": float(v["eigen_geld"]) if v.get("eigen_geld") is not None else None,
                      "_cao": "cao" in sid})
    lijst.sort(key=lambda s: (s["datum"], s["_cao"]))
    for s in lijst:
        s.pop("_cao", None)
    if not lijst:
        lijst = [{"id": "profiel", "label": "Profiel", "bruto_jaar": float(profiel.get("bruto_jaar") or 0),
                  "datum": vandaag, "eigen_geld": None}]
    ids = [s["id"] for s in lijst]
    planning = raw.get("planning")
    if planning not in ids:
        planning = "2027_01" if "2027_01" in ids else ids[0]

    # verplichtingen
    st = raw.get("studieschuld")
    if isinstance(st, dict):
        studie = st.get("maandlast", 0)
    elif isinstance(st, (int, float)):
        studie = st
    elif isinstance(raw.get("verplichtingen_maand"), dict):
        studie = raw["verplichtingen_maand"].get("duo", raw["verplichtingen_maand"].get("studieschuld", 0))
    else:
        studie = profiel.get("duo_maandlast", 0)
    bkr = raw.get("bkr", raw.get("bkr_limieten"))
    bkr_maand = 0.0
    if isinstance(bkr, (int, float)):
        bkr_maand = BKR_PCT_LIMIET * float(bkr)
    elif isinstance(bkr, list):
        for k in bkr:
            if not isinstance(k, dict) or k.get("opgezegd"):
                continue
            if k.get("maandlast") is not None:
                bkr_maand += float(k["maandlast"])
            else:
                bkr_maand += BKR_PCT_LIMIET * float(k.get("limiet") or 0)

    # eigen geld
    eg = raw.get("eigen_geld")
    if isinstance(eg, (int, float)):
        eg = {"nu": eg}
    eg = eg if isinstance(eg, dict) else {}
    nu = eg.get("nu", profiel.get("eigen_inleg", 0))
    vast_per_id = {k: float(v) for k, v in eg.items() if k in ids and k != "nu" and isinstance(v, (int, float))}
    buffer = eg.get("buffer", raw.get("buffer", 0))
    kk = raw.get("kosten_koper") if isinstance(raw.get("kosten_koper"), dict) else {}
    starter_tot = _datum(raw.get("starter_tot", raw.get("startersvrijstelling_tot"))) or _datum(f_cfg.get("starter_tot"))
    return {
        "bron": "financien",
        "alleenstaand": bool(raw.get("alleenstaand", f_cfg.get("alleenstaand", True))),
        "starter_tot": starter_tot,
        "leeftijd": leeftijd,
        "scenarios": lijst,
        "planning": planning,
        "studieschuld_maand": float(studie or 0),
        "bkr_maand": bkr_maand,
        "eigen_geld": {"nu": float(nu or 0), "datum": _datum(eg.get("datum"), vandaag),
                       "per_maand": float(eg.get("per_maand") or 0), "vast": vast_per_id},
        "buffer": float(buffer or 0),
        "kk_vast": float(kk.get("vast", KK_VAST_STANDAARD)),
        "nhg_pct": _als_fractie(kk.get("nhg_pct", NHG_PREMIE * 100), 0.05),
    }


def _eigen_geld_op(inv: dict, scenario: dict) -> float:
    """Eigen geld op de scenariodatum, zonder buffer."""
    if scenario.get("eigen_geld") is not None:
        return float(scenario["eigen_geld"])
    eg = inv["eigen_geld"]
    if scenario["id"] in eg["vast"]:
        return eg["vast"][scenario["id"]]
    return eg["nu"] + eg["per_maand"] * _maanden_tussen(eg["datum"], scenario["datum"])


def _is_starter(inv: dict, datum: date) -> bool:
    if inv.get("starter_tot"):
        return datum < inv["starter_tot"]
    if inv.get("leeftijd") is not None:
        try:
            return int(inv["leeftijd"]) < STARTER_LEEFTIJD_TOT
        except (TypeError, ValueError):
            return False
    return False


def _scenario_reken(inv: dict, s: dict, rente_frac: float, rentevast: int, label, canon_jaar) -> dict:
    lt = leentoets(s["bruto_jaar"], rente_frac, rentevast, label, canon_jaar, inv["studieschuld_maand"],
                   inv["bkr_maand"], inv["alleenstaand"])
    eigen = _eigen_geld_op(inv, s) - inv["buffer"]
    starter = _is_starter(inv, s["datum"])
    mk = max_koopsom(lt["max_hypotheek"], eigen, starter, inv["kk_vast"], inv["nhg_pct"], s["datum"].year)
    return {"leentoets": lt, "eigen_geld": eigen, "starter": starter, "max_koopsom": mk}


def scenario_overzicht(cfg: dict, profiel: dict | None, rente: dict | None = None, vandaag=None,
                       label: str | None = None, canon_jaar: float = 0) -> list[dict]:
    """Per scenario uit financien: {id, label, max_hypotheek, max_koopsom}, zonder woning.

    Zonder label (standaard) telt geen energielabelbedrag mee: het bedrag hoort bij een woning."""
    vandaag = _datum(vandaag, date.today())
    rente = rente or rente_uit_config(cfg, vandaag)
    inv = financien_invoer(cfg, profiel, vandaag)
    if inv["bron"] != "financien" or inv["scenarios"][0]["id"] == "profiel":
        return []
    frac = _als_fractie(rente.get("pct"), 0.2)
    uit = []
    for s in inv["scenarios"]:
        r = _scenario_reken(inv, s, frac, _rentevast(rente, cfg), label, canon_jaar)
        uit.append({"id": s["id"], "label": s["label"], "max_hypotheek": r["leentoets"]["max_hypotheek"],
                    "max_koopsom": r["max_koopsom"]})
    return uit


def _scenario_tekst(scenarios: list[dict]) -> str:
    """Korte zin zonder bedragen: het eerste scenario (op datum) waarin de woning past."""
    eerste_cao = next((s["id"] for s in scenarios if "cao" in s["id"]), None)
    for s in scenarios:
        if s["past"]:
            if s["id"] == "nu":
                return "Past nu"
            if s["id"] == eerste_cao:
                return "Alleen met cao-verhoging"
            lab = s["label"]
            return "Past " + (lab[:1].lower() + lab[1:] if lab else s["id"])
    return "Past in geen scenario"


# ---------------------------------------------------------------------------------------
# Financiering en poort (laag B)
# ---------------------------------------------------------------------------------------
def poort_financieel(tekort: float, over: float, cfg: dict) -> str:
    """Tekort aan eigen geld en woonlasten boven de grens -> PAST, KRAP of PAST NIET."""
    f = cfg["financiering"]
    if tekort > f["eigen_geld_tekort_past_niet"] or over > cfg["krap_marge"]:
        return "PAST NIET"
    if tekort > f["kk_onzekerheid"] or over > 0:
        return "KRAP"
    return "PAST"


def _geen_prijs_fin(rente: dict, rentevast: int, planning) -> dict:
    return {"max_hypotheek": None, "marge_lenen": None, "kosten_koper": None, "kk_soort": None,
            "tekort": None, "netto": None, "bruto": None, "grens": None, "grens_soort": None,
            "opbouw": None, "koopsom": None, "hypotheek": None, "over": None,
            "rente": _als_fractie(rente.get("pct"), 0.2), "rente_datum": rente.get("datum"),
            "rente_bron": rente.get("bron"), "rentevast_jaren": rentevast,
            "scenarios": [], "planning": planning, "scenario_tekst": None}


def financiering(woning: dict, cfg: dict, profiel: dict | None, rente: dict | None = None, vandaag=None) -> dict:
    """woning: {"prijs", "label", "canon_jaar", "vve", "vve_bron", "energie", "stook_in_vve", "woz"}.

    Geeft het financieringsdeel van het contract plus "poort" (zonder harde eisen) en "redenen"."""
    vandaag = _datum(vandaag, date.today())
    rente = rente or rente_uit_config(cfg, vandaag)
    frac = _als_fractie(rente.get("pct"), 0.2) or 0.0
    rentevast = _rentevast(rente, cfg)
    f = cfg["financiering"]
    inv = financien_invoer(cfg, profiel, vandaag)
    met_scenarios = inv["bron"] == "financien" and inv["scenarios"][0]["id"] != "profiel"
    planning = inv["planning"] if met_scenarios else None
    prijs = woning.get("prijs")
    if not (isinstance(prijs, (int, float)) and prijs > 0):
        uit = _geen_prijs_fin(rente, rentevast, planning)
        uit["poort"], uit["redenen"] = "PRIJS ONBEKEND", ["Geen vraagprijs: geen leentoets en geen woonlasten."]
        return uit

    koop = int(prijs * (1 + float(f.get("overbod_pct") or 0)))
    label, canon = woning.get("label"), woning.get("canon_jaar") or 0
    scenarios, plan = [], None
    for s in inv["scenarios"]:
        r = _scenario_reken(inv, s, frac, rentevast, label, canon)
        max_hyp = r["leentoets"]["max_hypotheek"]
        hyp = min(koop, max_hyp)
        kk, kk_soort = kosten_koper(koop, hyp, r["starter"], inv["kk_vast"], inv["nhg_pct"], s["datum"].year)
        tekort = int(round(kk + koop - hyp - r["eigen_geld"]))
        rij = {"id": s["id"], "label": s["label"], "max_hypotheek": max_hyp, "max_koopsom": r["max_koopsom"],
               "past": tekort <= f["kk_onzekerheid"],
               "_hyp": hyp, "_kk": kk, "_kk_soort": kk_soort, "_tekort": tekort, "_bruto_jaar": s["bruto_jaar"]}
        scenarios.append(rij)
        if s["id"] == inv["planning"]:
            plan = rij
    plan = plan or scenarios[0]

    hyp, max_hyp = plan["_hyp"], plan["max_hypotheek"]
    woz = woning.get("woz") or koop * WOZ_TERUGVAL
    bruto_hyp = annuiteit(hyp, frac)
    voordeel = hyp * frac / 12 * HRA_TARIEF_2026 - woz * EWF_2026 / 12 * HRA_TARIEF_2026
    vve = woning.get("vve")
    vve_geschat = vve is None
    vve_r = VVE_GESCHAT if vve_geschat else vve
    energie = float(woning.get("energie") or 0)
    canon_maand = float(canon) / 12
    vaste = vve_r + energie + OVERIG_MAAND + canon_maand
    netto = int(round(bruto_hyp - voordeel + vaste))
    bruto = int(round(bruto_hyp + vaste))
    grens_netto = cfg.get("max_woonlasten_netto")
    if grens_netto:
        grens, grens_soort, over = int(grens_netto), "netto", netto - int(grens_netto)
    else:
        grens = int(round(plan["_bruto_jaar"] / 12 * NORM_BRUTO_PCT))
        grens_soort, over = "bruto norm", bruto - grens
    tekort = plan["_tekort"]
    status = poort_financieel(tekort, over, cfg)

    redenen = []
    if koop > max_hyp:
        redenen.append(f"Max. hypotheek {eur(max_hyp)}: {eur(koop - max_hyp)} uit eigen geld.")
    if tekort > f["kk_onzekerheid"]:
        redenen.append(f"Eigen geld: {eur(tekort)} tekort.")
    if over > 0:
        redenen.append(f"Woonlasten {eur(over)} boven " + ("je grens." if grens_soort == "netto" else "de norm (bruto)."))

    uit_sc = [{k: v for k, v in s.items() if not k.startswith("_")} for s in scenarios] if met_scenarios else []
    return {
        "max_hypotheek": max_hyp, "marge_lenen": max_hyp - koop, "kosten_koper": plan["_kk"],
        "kk_soort": plan["_kk_soort"], "tekort": tekort, "netto": netto, "bruto": bruto,
        "grens": grens, "grens_soort": grens_soort,
        "opbouw": {"bruto_hyp": int(round(bruto_hyp)), "belastingvoordeel": int(round(voordeel)),
                   "vve": int(round(vve_r)), "vve_bron": woning.get("vve_bron") if not vve_geschat else "niet gevonden, geschat",
                   "vve_geschat": vve_geschat, "energie": int(round(energie)),
                   "stook_in_vve": bool(woning.get("stook_in_vve")), "overig": OVERIG_MAAND,
                   "canon_maand": int(round(canon_maand)), "woz": int(round(woz)),
                   "woz_geschat": not woning.get("woz")},
        "koopsom": koop, "hypotheek": hyp, "over": over,
        "rente": frac, "rente_datum": rente.get("datum"), "rente_bron": rente.get("bron"),
        "rentevast_jaren": rentevast,
        "scenarios": uit_sc, "planning": planning,
        "scenario_tekst": _scenario_tekst(uit_sc) if uit_sc else None,
        "poort": status, "redenen": redenen,
    }


def poort(woning: dict, cfg: dict, fin: dict) -> dict:
    """Harde eisen (beoordeling.md 3.2) boven op de financiële poort. Nooit onzichtbaar.

    woning: samengevoegde listing met characteristics, description en de vlaggen."""
    ch = woning.get("characteristics") or {}
    tekst = woning.get("description") or ""
    he = cfg["harde_eisen"]
    harde = []
    gelegen = (ch.get("Gelegen op") or "").lower()
    if "begane grond" in gelegen or "souterrain" in gelegen:
        harde.append(("Begane grond: hoort al door het filter te vallen.", "begane grond"))
    if he.get("veiling") and woning.get("is_auction"):
        harde.append(("Veiling: geen financieringsvoorbehoud mogelijk.", "veiling, geen financieringsvoorbehoud"))
    if he.get("kluswoning") and (woning.get("is_fixer_upper") or any(s[0] == "opknapper" for s in lees_advertentie(tekst))):
        harde.append(("Kluswoning.", "kluswoning"))
    if he.get("slapende_vve") and vve_status(ch, tekst) == "slapend":
        harde.append(("VvE niet actief.", "VvE niet actief"))
    laag, lift, _ = woonlaag(ch, tekst)
    mx = he.get("max_woonlaag_zonder_lift")
    if mx and laag and lift is False and laag > mx:
        harde.append((f"{laag}e woonlaag zonder lift.", f"{laag}e woonlaag zonder lift"))
    status = "PAST NIET" if harde else fin["poort"]
    return {"poort": status, "redenen": [h[0] for h in harde] + list(fin.get("redenen") or []),
            "harde": [h[1] for h in harde]}


def status_kort(poort_: str, fin: dict, harde: list[str], cfg: dict) -> str:
    """'Past · € 196 onder je grens' (spec.md 4.2)."""
    naam = POORT_NAAM[poort_]
    if poort_ == "PRIJS ONBEKEND" and not harde:
        return f"{naam} · geen vraagprijs, dus geen leentoets"
    if harde:
        return f"{naam} · {harde[0]}"
    f = cfg["financiering"]
    tekort, netto, grens = fin.get("tekort"), fin.get("netto"), fin.get("grens")
    woord = "je grens" if fin.get("grens_soort") == "netto" else "de norm (bruto)"
    waarde = netto if fin.get("grens_soort") == "netto" else fin.get("bruto")
    if (poort_ == "PAST NIET" and tekort > f["eigen_geld_tekort_past_niet"]) or \
            (poort_ == "KRAP" and tekort > f["kk_onzekerheid"] and waarde <= grens):
        return f"{naam} · {eur(tekort)} eigen geld te weinig"
    if waarde == grens:   # geen "€ 0 onder je grens"
        return f"{naam} · precies op {woord}"
    if waarde < grens:
        return f"{naam} · {eur(grens - waarde)} onder {woord}"
    return f"{naam} · {eur(waarde - grens)} boven {woord}"


# ---------------------------------------------------------------------------------------
# Parsers: kenmerken eerst, tekst als terugval
# ---------------------------------------------------------------------------------------
PER = {"maand": 1, "mnd": 1, "jaar": 1 / 12, "jr": 1 / 12, "kwartaal": 1 / 3, "halfjaar": 1 / 6}


def vve_maand(ch: dict, tekst: str) -> tuple[int | None, str]:
    """VvE-bijdrage per maand: kenmerken 'Bijdrage VvE', 'Periodieke bijdrage', 'Servicekosten',
    dan een zin met trefwoord en €-teken. Jaar en kwartaal worden omgerekend."""
    for sleutel in ("Bijdrage VvE", "Periodieke bijdrage", "Servicekosten"):
        v = ch.get(sleutel)
        if v and "€" in str(v):
            m = re.search(r"€\s*([\d.,\-]+)\s*(?:per\s+)?(maand|mnd|jaar|jr|kwartaal|halfjaar)?", str(v))
            if m and _getal(m.group(1)) is not None:
                return int(round(_getal(m.group(1)) * PER.get(m.group(2) or "maand", 1))), f"kenmerk '{sleutel}'"
    zin = re.search(r"(?:servicekosten|bijdrage(?:\s+aan\s+de)?\s+v\.?v\.?e\.?|v\.?v\.?e\.?[- ]bijdrage|maandelijkse bijdrage)"
                    r"[^€.;]{0,40}€\s*([\d.,\-]+)\s*(?:,-)?\s*(?:per\s+|p/)?(maand|mnd|m\b|jaar|jr|kwartaal)?",
                    tekst or "", re.I)
    if zin and _getal(zin.group(1)) is not None:
        per = (zin.group(2) or "maand").lower()
        per = "maand" if per == "m" else per
        return int(round(_getal(zin.group(1)) * PER.get(per, 1))), "advertentietekst"
    return None, "niet gevonden"


def stookkosten_in_vve(ch: dict, tekst: str) -> bool:
    verw = (ch.get("Verwarming") or "").lower()
    return ("blokverwarming" in verw or "collectie" in verw
            or bool(re.search(r"inclusief\s+(?:het\s+)?voorschot\s+(?:stook|energie|warmte)", tekst or "", re.I)))


_MAANDNAAM = (r"(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december"
              r"|jan|feb|mrt|apr|jun|jul|aug|sep|sept|okt|nov|dec)\.?")
# Een mogelijkheid is geen feit: "kan worden afgekocht", "afkopen is mogelijk", "omzetten naar eeuwigdurend".
_MODAAL_VOOR = re.compile(r"\b(?:kan|kunnen|kunt|zou|zouden|wil|mogelijk|mogelijkheid|omzetten|omzetting|overstappen"
                          r"|optie|desgewenst|afkopen|afkoopsom)\b")
_MODAAL_NA = re.compile(r"\s*(?:kan\b|kunnen\b|worden\b|te\s+worden\b|is\s+mogelijk\b|mogelijk\b)")
_ERFPACHT_EIND = re.compile(r"(?:afgekocht|vooruitbetaald|afkoop)\s+tot\s+(?:en\s+met\s+)?"
                            r"(?:\d{1,2}[-./]\d{1,2}[-./]|\d{1,2}\s+" + _MAANDNAAM + r"\s+|(?:eind|einde|begin|medio|ultimo)\s+)?"
                            r"((?:20|21)\d{2})\b")


def _zinsdeel_voor(t: str, i: int, venster: int = 60) -> str:
    """De tekst vóór positie i in dezelfde zin, hooguit `venster` tekens (een punt in 1.250 telt niet)."""
    voor = t[max(0, i - venster):i]
    grens = max((m.end() for m in re.finditer(r"[.;!?](?:\s|$)", voor)), default=0)
    return voor[grens:]


def _feitelijk(t: str, patroon: str) -> bool:
    """Komt het patroon voor zonder modale vorm ervoor of erna ("kan worden afgekocht", "is mogelijk")?"""
    for m in re.finditer(patroon, t):
        if _MODAAL_VOOR.search(_zinsdeel_voor(t, m.start())) or _MODAAL_NA.match(t[m.end():m.end() + 20]):
            continue
        return True
    return False


# Een ontkenning hoort alleen bij 'erfpacht' als hij er direct vóór staat, hooguit met een lidwoord
# of 'belast met', 'in', 'op', 'sprake van' ertussen: 'geen erfpacht', 'zonder erfpacht', 'niet belast
# met (de) erfpacht', 'niet in erfpacht', 'geen sprake van erfpacht'. Niet: 'niet in eigendom maar in
# erfpacht', 'Geen VvE-bijdrage, wel erfpacht', 'Niet afgekocht: erfpacht loopt tot 2045'.
_ERFPACHT_ONTKEND = re.compile(r"\b(?:geen|niet|zonder)\s+(?:(?:belast\s+met|in|op|sprake\s+van)\s+)?"
                               r"(?:(?:de|het|een)\s+)?$")


def _erfpacht_genoemd(t: str) -> bool:
    """'erfpacht' in de tekst, maar niet direct ontkend ('geen erfpacht', 'niet belast met erfpacht')."""
    for m in re.finditer(r"erfpacht", t):
        if not _ERFPACHT_ONTKEND.search(t[max(0, m.start() - 40):m.start()]):
            return True
    return False


def erfpacht(ch: dict, tekst: str) -> dict:
    """{"status", "canon_jaar", "eind", "bron"}. Status: eigen, eeuwig_afgekocht, afgekocht_tot,
    afgekocht_looptijd_onbekend, eeuwig_canon, voortdurend, erfpacht_onduidelijk, onbekend.

    Kenmerken 'Eigendomssituatie' en 'Lasten' eerst. In tekst: €-teken, NL-duizendtallen,
    eenheid, ontkenning ('niet afgekocht', 'geen erfpacht'); alleen een feitelijke afkoop telt
    ('is afgekocht', niet 'kan worden afgekocht' of 'afkopen is mogelijk'); een einddatum alleen na
    'afgekocht/vooruitbetaald tot', ook met een maandnaam ('tot 1 januari 2035')."""
    eig = (ch.get("Eigendomssituatie") or "").lower()
    lasten = (ch.get("Lasten") or "").lower()
    t = (tekst or "").lower()
    info = {"status": "onbekend", "canon_jaar": None, "eind": None, "bron": "niet vermeld"}
    erfpacht_in_tekst = _erfpacht_genoemd(t)
    if eig:
        info["bron"] = "kenmerk 'Eigendomssituatie'"
        if "volle eigendom" in eig:
            info["status"] = "eigen"
            return info
    elif not erfpacht_in_tekst and (re.search(r"(?<!geen )(?<!niet op )\beigen grond\b", t) or "erfpacht" in t):
        # 'eigen grond', of alleen een ontkende erfpacht ('geen erfpacht'): eigen grond.
        return {"status": "eigen", "canon_jaar": None, "eind": None, "bron": "advertentietekst"}
    if not (eig or erfpacht_in_tekst):
        return info
    if info["bron"] == "niet vermeld":
        info["bron"] = "advertentietekst"
    voortdurend = "voortdurend" in eig or re.search(r"voortdurende\s+erfpacht", t)
    eeuwig = "eeuwigdurend" in eig or _feitelijk(t, r"eeuwigdurend")
    niet_afgekocht = re.search(r"niet\s+(?:is\s+)?afgekocht|canon\s+niet\s+afgekocht", t + " " + lasten)
    afgekocht = (("afgekocht" in lasten and not re.search(r"niet\s+afgekocht", lasten))
                 or (not niet_afgekocht and _feitelijk(t, r"\b(?:afgekocht|vooruitbetaald|afkoop\s+tot)\b")))
    jaar = _ERFPACHT_EIND.search(lasten + " " + t)
    if jaar:
        info["eind"] = int(jaar.group(1))
    # 'afgekocht tot ...' zonder leesbaar jaar is geen eeuwigdurende afkoop.
    tot_zonder_jaar = not jaar and re.search(r"(?:afgekocht|vooruitbetaald)\s+tot\b", lasten + " " + t)
    canon_txt = lasten if "€" in lasten else ""
    if not canon_txt:
        # De eerste zin met 'canon' en een bedrag, tot het einde van de zin (niet tot de punt in 1.250).
        canon_txt = next((z.group(0) for z in re.finditer(r"canon.*?(?:\.\s|;|$)", t) if "€" in z.group(0)), "")
    canon = re.search(r"€\s*([\d.,\-]+)\s*(?:per\s+)?(jaar|maand|halfjaar|kwartaal)?", canon_txt)
    if canon and not afgekocht:
        bedrag = _getal(canon.group(1))
        per = canon.group(2) or "jaar"
        info["canon_jaar"] = int(round(bedrag * {"jaar": 1, "maand": 12, "halfjaar": 2, "kwartaal": 4}[per])) if bedrag else None
    if afgekocht and info["eind"]:
        info["status"] = "afgekocht_tot"
    elif afgekocht and eeuwig and not tot_zonder_jaar:
        info["status"] = "eeuwig_afgekocht"
    elif afgekocht:
        info["status"] = "afgekocht_looptijd_onbekend"
    elif voortdurend:
        info["status"] = "voortdurend"
    elif eeuwig:
        info["status"] = "eeuwig_canon"
    else:
        info["status"] = "erfpacht_onduidelijk"
    return info


def buitenruimte(d: dict, ch: dict, tekst: str) -> dict:
    """{"soort": None|"frans balkon"|"balkon"|"dakterras"|"tuin", "m2", "richting", "bron", "zeker"}.

    Kenmerken eerst; in tekst woordgrenzen en ontkenning; een frans balkon is geen buitenruimte.
    Zonligging: de richting na balkon/terras/tuin, niet de eerste richting in de tekst.
    zeker=False: niets gevonden, dus onbekend (geen minpunt)."""
    kenm = (ch.get("Balkon/dakterras") or "").lower()
    m2 = _getal(ch.get("Gebouwgebonden buitenruimte")) if ch.get("Gebouwgebonden buitenruimte") else None
    tuin_k = (ch.get("Tuin") or "").lower()
    t = (tekst or "").lower()
    soort, zeker = None, True
    zonder_frans = kenm.replace("frans balkon", "")
    if "dakterras" in kenm or d.get("has_roof_terrace"):
        soort = "dakterras"
    elif "balkon" in zonder_frans:
        soort = "balkon"
    elif "frans balkon" in kenm:
        soort = "frans balkon"
    elif d.get("has_balcony"):
        soort = "balkon"
    elif "niet aanwezig" in kenm:
        soort = None
    elif not kenm:
        if re.search(r"(?<!geen )\b(?:eigen\s+)?dakterras\b(?![^.]{0,25}\bniet\s+mogelijk)", t) and not re.search(r"geen\s+dakterras", t):
            soort = "dakterras"
        elif re.search(r"(?<!geen )(?<!frans )(?<!franse )\b(?:balkon|loggia)\b", t):
            soort = "balkon"
        elif re.search(r"(?<!geen )\beigen\s+(?:voor|achter)?tuin\b|\b(?:voor|achter)tuin\b", t):
            soort = "tuin"
        elif re.search(r"\bfrans(?:e)?\s+balkon", t):
            soort = "frans balkon"
        elif not re.search(r"\bgeen\s+(?:balkon|buitenruimte|tuin)\b", t):
            zeker = False
    if (d.get("has_garden") or (tuin_k and "niet" not in tuin_k)) and soort in (None, "frans balkon"):
        soort, zeker = "tuin", True
    richting = None
    if soort and soort != "frans balkon":
        for anker in re.finditer(r"\b(balkon|loggia|dakterras|terras|tuin)\b", t):
            na = t[anker.end(): anker.end() + 60]
            m = re.search(r"\b(?:op|aan)\s+(?:het\s+|de\s+)?(zuid[- ]?west|zuid[- ]?oost|noord[- ]?west|noord[- ]?oost|zuid|noord|west|oost)"
                          r"(?:en|zijde|kant)?\b", na)
            if m:
                richting = m.group(1).replace("-", "").replace(" ", "").capitalize()
                break
        if richting is None and soort == "tuin" and ch.get("Ligging tuin"):
            m = re.search(r"(zuid[- ]?west|zuid[- ]?oost|noord[- ]?west|noord[- ]?oost|zuid|noord|west|oost)",
                          ch["Ligging tuin"].lower())
            if m:
                richting = m.group(1).replace("-", "").replace(" ", "").capitalize()
    bron = "kenmerk 'Balkon/dakterras'" if kenm else ("kenmerk 'Tuin'" if tuin_k else "advertentietekst")
    return {"soort": soort, "m2": m2, "richting": richting, "bron": bron, "zeker": zeker}


def energielabel(d: dict, ch: dict, tekst: str) -> tuple[str, str]:
    """Veld, dan kenmerk, dan tekst. In tekst: plussen meenemen, 'haalbaar/na renovatie' overslaan.
    Onbekend = '?'."""
    for waarde, bron in ((d.get("energy_label"), "funda"), (ch.get("Energielabel"), "kenmerk 'Energielabel'")):
        if waarde and str(waarde).strip().lower() not in ("?", "unknown", "onbekend", "niet beschikbaar"):
            m = re.match(r"\s*([A-G])(\+{0,4})(?![\w+])", str(waarde).upper())
            if m:
                return m.group(1) + m.group(2), bron
    t = (tekst or "").lower()
    for m in re.finditer(r"\b(?:energie\s*label|energieklasse|label)\s*(?:is\s+|:\s*)?([a-g])(\+{0,4})(?![\w+])", t):
        na = t[m.end(): m.end() + 30]
        if re.search(r"haalbaar|mogelijk|verwacht|na\s+(?:renovatie|isolatie|verduurzaming)", na):
            continue
        return m.group(1).upper() + m.group(2), "advertentietekst"
    return "?", "niet vermeld"


_RANGTELWOORD = {"eerste": 1, "tweede": 2, "derde": 3, "vierde": 4, "vijfde": 5, "zesde": 6, "zevende": 7,
                 "achtste": 8, "negende": 9, "tiende": 10}


def woonlaag(ch: dict, tekst: str = "") -> tuple[int | None, bool | None, str]:
    """(woonlaag, lift, bron). Lift: True, False of None (onbekend).

    Kenmerk 'Gelegen op' ('3e woonlaag') en 'Voorzieningen' eerst. Tekst als terugval:
    'op de derde woonlaag' of '2e verdieping' (verdieping + 1 = woonlaag)."""
    t = (tekst or "").lower()
    laag, bron = None, "niet vermeld"
    m = re.search(r"(\d+)e\s+woonlaag", ch.get("Gelegen op") or "")
    if m:
        laag, bron = int(m.group(1)), "kenmerk 'Gelegen op'"
    elif not ch.get("Gelegen op"):
        m = re.search(r"\bop\s+de\s+(\d+)e\s+woonlaag|\bop\s+de\s+(" + "|".join(_RANGTELWOORD) + r")\s+woonlaag", t)
        if m:
            laag = int(m.group(1)) if m.group(1) else _RANGTELWOORD[m.group(2)]
            bron = "advertentietekst"
        else:
            m = re.search(r"\b(?:op\s+de\s+)?(\d+)e\s+(?:verdieping|etage)\b|\bop\s+de\s+(" + "|".join(_RANGTELWOORD)
                          + r")\s+(?:verdieping|etage)\b", t)
            if m:
                laag = (int(m.group(1)) if m.group(1) else _RANGTELWOORD[m.group(2)]) + 1
                bron = "advertentietekst"
    voorz = ch.get("Voorzieningen")
    if voorz:
        lift = "lift" in voorz.lower()
    elif re.search(r"\b(?:geen|zonder)\s+lift\b", t):
        lift = False
    elif re.search(r"\b(?:met|eigen)\s+lift\b|\blift\s+aanwezig\b|\bliftinstallatie\b", t):
        lift = True
    else:
        lift = None
    return laag, lift, bron


def vve_status(ch: dict, tekst: str) -> str:
    """'actief', 'slapend' of 'onbekend' (kenmerken KvK, ALV, reservefonds, MJOP; tekst)."""
    t = (tekst or "").lower()
    if re.search(r"(?:vve|vereniging)[^.]{0,40}\b(?:niet actief|slapend)|slapende\s+vve", t):
        return "slapend"
    sleutels = ("Inschrijving KvK", "Jaarlijkse vergadering", "Reservefonds aanwezig", "Onderhoudsplan")
    ja = [k for k in sleutels if (ch.get(k) or "").lower().startswith("ja")]
    nee = [k for k in sleutels if (ch.get(k) or "").lower().startswith("nee")]
    if len(nee) >= 3:
        return "slapend"
    if len(ja) >= 3:
        return "actief"
    return "onbekend"


# Advertentielezer: (id, patroon, ontkenning_controleren, onderdeel, oordeel, label, waarde,
# punten, kort, vraag). Ontkenning: 'geen/niet/zonder' in de 25 tekens ervoor = niet tellen.
SIGNALEN = [
    ("ouderdomsclausule", r"ouderdomsclausule", True, "clausules", "let_op", "Ouderdomsclausule", "in advertentie", 0.0,
     "ouderdomsclausule", "Laat een bouwkundige keuring doen: de clausule beperkt wat je later kunt claimen."),
    ("asbest", r"asbest(?:clausule)?", True, "clausules", "let_op", "Asbest", "genoemd in advertentie", 0.0,
     "asbest genoemd", "Vraag of er een asbestinventarisatie is."),
    ("niet_zelfbewoning", r"niet[- ]?zelfbewoning", False, "clausules", "neutraal", "Niet-zelfbewoning",
     "verkoper woonde er niet", 0.0, "niet-zelfbewoning",
     "Vraag naar bekende gebreken: de verkoper kent de woning minder goed."),
    ("dakterras_zonder_vergunning", r"dakterras[^.]{0,60}(?:(?:zonder|geen)\s+(?:omgevings)?vergunning|gedoogd)", False,
     "clausules", "let_op", "Dakterras", "geen vergunning genoemd", -0.5, "dakterras zonder vergunning",
     "Vraag naar de vergunning en de toestemming van de VvE."),
    ("in_splitsing", r"nog\s+(?:te\s+)?splitsen|in\s+splitsing|wordt\s+(?:nog\s+)?gesplitst", False, "vve", "let_op",
     "Splitsing", "pand nog niet gesplitst", -0.5, "nog niet gesplitst",
     "Vraag de (concept-)splitsingsakte en wanneer de VvE start."),
    ("extra_bijdrage", r"(?:bijzondere|extra|eenmalige)\s+(?:bijdrage|heffing)|groot\s+onderhoud\s+(?:is\s+)?gepland", True,
     "vve", "let_op", "Extra VvE-bijdrage", "aangekondigd", -0.5, "extra VvE-bijdrage",
     "Vraag de notulen van de laatste twee ALV's en het bedrag."),
    ("funderingsherstel", r"fundering\s+(?:is\s+)?(?:hersteld|vernieuwd)|funderingsherstel\s+(?:is\s+)?(?:uitgevoerd|gereed)", True,
     "fundering", "goed", "Funderingsherstel", "uitgevoerd (advertentie)", 0.0, "fundering hersteld",
     "Vraag het rapport en de garantie van het herstel."),
    ("opknapper", r"\b(?:opknapper|kluswoning|complete\s+renovatie|achterstallig\s+onderhoud)\b", True, "staat", "sterk",
     "Staat", "opknapper", -1.5, "opknapper", "Laat een verbouwbegroting maken voor je bod."),
    ("vocht", r"\b(?:lekkage|vochtprobleem|vochtplekken|schimmel|scheurvorming)\b", True, "staat", "let_op",
     "Vocht of scheuren", "genoemd in advertentie", -0.5, "vocht of scheuren", "Vraag naar de oorzaak en of die is opgelost."),
    ("erfdienstbaarheid", r"recht\s+van\s+overpad|erfdienstbaarheid|kettingbeding", False, "clausules", "neutraal",
     "Erfdienstbaarheid", "genoemd", 0.0, "erfdienstbaarheid", "Vraag de akte: wat mag een ander op of over jouw deel?"),
    ("huisdieren", r"huisdieren\s+(?:zijn\s+)?niet\s+toegestaan", False, "clausules", "neutraal", "Huisdieren",
     "niet toegestaan", 0.0, "geen huisdieren", None),
]


def lees_advertentie(tekst: str) -> list[tuple]:
    """De signalen uit SIGNALEN die in de tekst staan (elk hooguit één keer)."""
    t = (tekst or "").lower()
    gevonden = []
    for regel in SIGNALEN:
        patroon, ontkenning = regel[1], regel[2]
        for m in re.finditer(patroon, t):
            if ontkenning and re.search(r"\b(?:geen|niet|zonder)\b[^.]{0,25}$", t[max(0, m.start() - 25):m.start()]):
                continue
            gevonden.append(regel)
            break
    return gevonden


def _tijd(change: dict) -> str:
    ts = str(change.get("timestamp") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", ts):
        return ts[:10]
    m = re.match(r"\s*(\d{1,2})\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", str(change.get("date") or "").lower())
    if m and m.group(2) in _MAANDEN_NL:
        return f"{m.group(3)}-{_MAANDEN_NL[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return ""


def _prijs_van(change: dict) -> int | None:
    v = change.get("price")
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[^\d]", "", str(v or ""))
    return int(digits) if digits else None


def prijshistorie(changes) -> dict:
    """Vraagprijzen na de laatste verkoop (op tijd gesorteerd), de hoogste daarvan en de nieuwste WOZ.

    Een piek uit een eerdere verkoopperiode telt niet als prijsdaling (auditfix)."""
    rijen = [c for c in (changes or []) if isinstance(c, dict)]
    rijen.sort(key=_tijd)
    verkocht = [c for c in rijen if str(c.get("status") or "").lower() == "sold"]
    na = _tijd(verkocht[-1]) if verkocht else ""
    vraag = [c for c in rijen if str(c.get("status") or "").lower() == "asking_price" and _tijd(c) > na and _prijs_van(c)]
    woz = [c for c in rijen if str(c.get("status") or "").lower() == "woz" and _prijs_van(c)]
    w = woz[-1] if woz else None
    return {
        "vraagprijzen": [{"prijs": _prijs_van(c), "datum": _tijd(c)} for c in vraag],
        "hoogste": max((_prijs_van(c) for c in vraag), default=None),
        "woz": {"bedrag": _prijs_van(w), "jaar": int(_tijd(w)[:4]) if _tijd(w) else None} if w else None,
    }


# ---------------------------------------------------------------------------------------
# Verrijking (alleen lezen; ophalen gebeurt in funda_verrijking.py)
# ---------------------------------------------------------------------------------------
def _bron(verrijking: dict | None, naam: str) -> tuple[str, dict | None, str | None]:
    """(status, data, reden) voor één bron; accepteert {"status", "data"} en kale data."""
    if not isinstance(verrijking, dict):
        return "uit", None, None
    e = verrijking.get(naam)
    if e is None:
        return "uit", None, None
    if e == "fout":
        return "onbekend", None, "bron gaf geen antwoord"
    if e == "niet_nodig":
        return "niet_nodig", None, None
    if isinstance(e, dict) and "status" in e:
        st = str(e.get("status") or "onbekend")
        data = e.get("data") if isinstance(e.get("data"), dict) else None
        if st == "ok" and data is None:
            st = "onbekend"
        return st, data, e.get("reden")
    if isinstance(e, dict):
        return "ok", e, None
    return "onbekend", None, None


# ---------------------------------------------------------------------------------------
# Items en beoordeling (laag C)
# ---------------------------------------------------------------------------------------
def _item(onderdeel, oordeel, label, waarde, bron, punten=0.0, kort=None, vraag=None, uitleg=None) -> dict:
    """Eén regel in Let op, Pluspunten, Info, Onbekend of Kansen. Label <= 24, waarde <= 32 tekens."""
    label = _kap(label, 24)
    waarde = _kap(waarde, 32)
    kort = kort or label.lower()
    if kort.strip().lower() in (onderdeel.replace("_", " "), onderdeel):
        kort = f"{label.lower()} {waarde}".strip()
    return {"onderdeel": onderdeel, "groep": OORDEEL_GROEP[oordeel], "oordeel": oordeel, "label": label,
            "waarde": waarde, "bron": bron, "punten": round(float(punten), 2), "kort": kort,
            "vraag": vraag, "uitleg": uitleg}


def _woning(d: dict, details: dict | None) -> dict:
    """Zoekresultaat en detail samen; detail vult aan en gaat voor, behalve de vraagprijs."""
    w = dict(d or {})
    for k, v in (details or {}).items():
        if v is not None and v != "" and v != {} and v != []:
            w[k] = v
    if isinstance((d or {}).get("price"), (int, float)):
        w["price"] = d["price"]
    return w


def _twijfel_zinnen(twijfel) -> list[str]:
    uit = []
    for t in twijfel or []:
        s = re.sub(r"\s*Onderaan gezet\.?\s*$", "", str(t or "").strip())
        if not s:
            continue
        s = s[:1].upper() + s[1:]
        if not s.endswith((".", "?", "!")):
            s += "."
        if s not in uit:
            uit.append(s)
    return uit


def _twijfel_item(zin: str) -> dict:
    m = re.match(r"Twijfelbuurt\s+(.+?)\s*\(", zin)
    if m:
        return _item("buurt", "let_op", "Twijfelbuurt", m.group(1), "jouw lijst", kort=f"twijfelbuurt {m.group(1)}")
    if zin.lower().startswith("stad onduidelijk"):
        lv = "leidschendam" in zin.lower()
        return _item("buurt", "let_op", "Stad onduidelijk", "Leidschendam of Voorburg?" if lv else "plaats onduidelijk",
                     "funda", kort="stad onduidelijk",
                     vraag="Controleer de plaats: Leidschendam staat op je uitsluitlijst." if lv else None)
    if zin.lower().startswith("leefbaarometer"):
        return None
    return _item("buurt", "let_op", "Twijfel", zin.rstrip("."), "jouw lijst", kort="twijfel")


def beoordeel(d: dict, details: dict | None, routes: list | None, twijfel: list | None, profiel: dict | None,
              config: dict | None, verrijking: dict | None = None, *, rente: dict | None = None,
              vandaag=None) -> dict:
    """Beoordeling van één woning volgens het datacontract (beoordeling.md par. 9)."""
    vandaag = _datum(vandaag, date.today())
    profiel = profiel or {}
    cfg = config if isinstance(config, dict) and "gewichten" in config else laad_config(profiel)
    rente = rente or rente_uit_config(cfg, vandaag)
    w = _woning(d, details)
    ch = w.get("characteristics") if isinstance(w.get("characteristics"), dict) else {}
    tekst = str(w.get("description") or "")
    dr = cfg["drempels"]
    m2 = w.get("living_area") or 0
    try:
        m2 = int(m2)
    except (TypeError, ValueError):
        m2 = _getal(m2) or 0
    items: list[dict] = []
    add = items.append
    if twijfel is None:
        twijfel = (d or {}).get("_twijfel")
    twijfel_z = _twijfel_zinnen(twijfel)
    enr = (d or {}).get("_enrichment") if isinstance((d or {}).get("_enrichment"), dict) else {}

    # --- invoer voor de financiering
    label, label_bron = energielabel(w, ch, tekst)
    erf = erfpacht(ch, tekst)
    vve, vve_bron = vve_maand(ch, tekst)
    stook = stookkosten_in_vve(ch, tekst)
    energie = ENERGIE_PER_LABEL.get(label, ENERGIE_ONBEKEND) * max(m2, 40) / 75 * (STOOK_IN_VVE_FACTOR if stook else 1)
    ph_raw = enr.get("price_history")
    changes = ph_raw.get("changes") if isinstance(ph_raw, dict) else ph_raw if isinstance(ph_raw, list) else []
    hist = prijshistorie(changes)
    prijs = w.get("price") if isinstance(w.get("price"), (int, float)) and w.get("price") > 0 else None
    fin = financiering({"prijs": prijs, "label": None if label == "?" else label, "canon_jaar": erf["canon_jaar"],
                        "vve": vve, "vve_bron": vve_bron, "energie": energie, "stook_in_vve": stook,
                        "woz": (hist["woz"] or {}).get("bedrag")}, cfg, profiel, rente, vandaag)
    gate = poort(w, cfg, fin)
    signalen = lees_advertentie(tekst)
    sig_ids = {s[0] for s in signalen}
    kk_onz = cfg["financiering"]["kk_onzekerheid"]

    # --- woonlasten en geld (de financiering zelf is de poort; hier de maandlast als onderdeel)
    if fin["netto"] is not None:
        netto_grens = fin["grens_soort"] == "netto"
        waarde_lasten = fin["netto"] if netto_grens else fin["bruto"]
        ruimte = fin["grens"] - waarde_lasten
        oord = "goed" if ruimte >= dr["woonlasten_ruim_onder_grens"] else ("let_op" if ruimte < 0 else "neutraal")
        add(_item("woonlasten", oord, "Woonlasten", f"{eur(waarde_lasten)} {'netto' if netto_grens else 'bruto'} per maand",
                  "berekening", max(-1.5, min(1.5, ruimte / 100)), kort=f"woonlasten {eur(waarde_lasten)}",
                  uitleg=(f"Netto, jaar 1. Je grens: {eur(fin['grens'])}." if netto_grens else
                          f"Bruto. Zonder eigen grens geldt de norm van 33% van je bruto inkomen ({eur(fin['grens'])}).")))
        if fin["tekort"] > kk_onz:
            add(_item("financiering", "let_op", "Eigen geld", f"{eur(fin['tekort'])} tekort", "berekening, kosten koper ≈"))
        elif fin["tekort"] > 0:
            add(_item("financiering", "neutraal", "Eigen geld", "net genoeg (schatting)", "berekening, kosten koper ≈",
                      vraag="Laat je kosten koper narekenen door een adviseur.",
                      uitleg=f"Tekort {eur(fin['tekort'])} valt binnen de onzekerheid van de kosten koper."))
        else:
            add(_item("financiering", "neutraal", "Eigen geld", f"genoeg, {eur(-fin['tekort'])} over", "berekening, kosten koper ≈"))
        marge = fin["marge_lenen"]
        if marge >= 0:
            add(_item("financiering", "neutraal", "Leenruimte", f"{eur(marge)} over", "leentoets 2026"))
        else:
            add(_item("financiering", "sterk" if fin["tekort"] > kk_onz else "neutraal", "Leenruimte",
                      f"{eur(-marge)} boven max. hypotheek", "leentoets 2026", kort="leenruimte te klein"))
        if fin["scenario_tekst"]:
            add(_item("financiering", "neutraal", "Leentoets", fin["scenario_tekst"], "leentoets 2026, jouw scenario's",
                      kort=fin["scenario_tekst"].lower()))
    else:
        add(_item("woonlasten", "onbekend", "Woonlasten", "prijs onbekend", "funda", kort="woonlasten onbekend",
                  vraag="Vraag de vraagprijs of een richtprijs."))

    # --- buitenruimte
    br = buitenruimte(w, ch, tekst)
    if br["soort"] is None and br["zeker"]:
        add(_item("buitenruimte", "sterk", "Buitenruimte", "geen", br["bron"], -1.5, kort="geen buitenruimte"))
    elif br["soort"] is None:
        add(_item("buitenruimte", "onbekend", "Buitenruimte", "niet vermeld", "funda", kort="buitenruimte onbekend",
                  vraag="Vraag of er een balkon of andere buitenruimte is."))
    elif br["soort"] == "frans balkon":
        add(_item("buitenruimte", "let_op", "Buitenruimte", "alleen frans balkon", br["bron"], -1.0, kort="alleen frans balkon"))
    else:
        maat = f"{br['m2']} m²" if br["m2"] else "maat onbekend"
        groot = br["soort"] in ("dakterras", "tuin")
        p = 1.0 if groot else (0.5 if (br["m2"] or 0) >= dr["buitenruimte_balkon_min_m2"] else 0.0)
        add(_item("buitenruimte", "goed" if p > 0 else "neutraal", br["soort"].capitalize(), maat, br["bron"], p,
                  kort=f"{br['soort']} {maat if br['m2'] else ''}".strip() + (f" {br['richting'].lower()}" if br["richting"] else ""),
                  vraag="Is er een vergunning voor het dakterras en staat het in de splitsingsakte?" if br["soort"] == "dakterras" else None))
        r = br["richting"]
        if r in ("Zuid", "Zuidwest", "Zuidoost", "West"):
            add(_item("buitenruimte", "goed", "Zon op buitenruimte", r.lower(), "advertentietekst", 0.5, kort=f"zon {r.lower()}"))
        elif r and r.startswith("Noord"):
            add(_item("buitenruimte", "let_op", "Zon op buitenruimte", r.lower(), "advertentietekst", -0.5, kort=f"zon {r.lower()}"))
        elif r:
            add(_item("buitenruimte", "neutraal", "Zon op buitenruimte", r.lower(), "advertentietekst", kort=f"zon {r.lower()}"))

    # --- oppervlak
    wens = cfg["m2_wens"]
    if m2:
        oord = "goed" if m2 >= wens + 10 else ("let_op" if m2 < wens - 10 else "neutraal")
        add(_item("oppervlak", oord, "Woonoppervlak", f"{m2} m² (wens {wens})", "funda",
                  max(-1.0, min(1.0, (m2 - wens) / dr["oppervlak_stap_m2"])), kort=f"{m2} m²"))
    else:
        add(_item("oppervlak", "onbekend", "Woonoppervlak", "onbekend", "funda", kort="oppervlak onbekend"))

    # --- woonlaag en lift
    laag, lift, laag_bron = woonlaag(ch, tekst)
    mx = cfg["max_woonlaag_zonder_lift"]
    if laag and lift is False and laag > mx:
        add(_item("woonlaag_lift", "sterk" if laag >= mx + 2 else "let_op", "Trappen", f"{laag}e woonlaag, geen lift",
                  laag_bron, max(-1.5, -0.5 * (laag - mx)), kort=f"{laag}e zonder lift"))
    elif laag and lift is None and laag > mx:
        add(_item("woonlaag_lift", "onbekend", "Lift", "niet vermeld", "funda", kort="lift onbekend",
                  vraag=f"Is er een lift? De woning ligt op de {laag}e woonlaag."))
    elif laag and lift and laag >= 3:
        add(_item("woonlaag_lift", "goed", "Lift", f"{laag}e woonlaag", "kenmerk 'Voorzieningen'", kort=f"lift, {laag}e woonlaag"))

    # --- reisafstand
    routes = [r for r in (routes or []) if isinstance(r, dict) and isinstance(r.get("km"), (int, float))]
    if routes:
        gw_cfg = cfg["werk"].get("gewicht") or {}
        goed_km, slecht_km = cfg["werk"]["km_goed"], cfg["werk"]["km_slecht"]
        for rt in routes:
            g = float(gw_cfg.get(rt.get("label"), 0)) if gw_cfg else 1 / len(routes)
            km = float(rt["km"])
            f_ = max(-1.0, min(1.0, ((goed_km + slecht_km) / 2 - km) / ((slecht_km - goed_km) / 2)))
            oord = "goed" if km <= goed_km else ("let_op" if km >= slecht_km else "neutraal")
            bron = "route" if rt.get("soort") == "weg" else "schatting (hemelsbreed x 1,3)"
            add(_item("reisafstand", oord, f"Werk {rt.get('label') or ''}".strip(), f"≈ {nl(km)} km", bron, g * f_,
                      kort=f"werk {nl(km)} km"))
    elif profiel.get("werk_postcodes"):
        add(_item("reisafstand", "onbekend", "Reisafstand", "onbekend", "route", kort="reisafstand onbekend"))

    # --- energielabel: kosten zitten in de woonlasten, leenruimte in de poort; hier alleen het verbouwrisico
    if label in dr["energielabel_slecht"]:
        extra = tabel()["label_verduurzamen"].get(label)
        add(_item("energielabel", "let_op", "Energielabel", label, label_bron, -1.0, kort=f"label {label}",
                  vraag="Vraag naar verduurzamingsplannen van de VvE.",
                  uitleg=(f"Voor energiebesparende maatregelen mag je tot {eur(extra)} extra lenen." if extra else None)))
    elif label == "?":
        add(_item("energielabel", "onbekend", "Energielabel", "onbekend", label_bron, kort="label onbekend",
                  vraag="Vraag het energielabel op."))
    elif label in dr["energielabel_goed"]:
        add(_item("energielabel", "goed", "Energielabel", label, label_bron, kort=f"label {label}",
                  uitleg="Lagere stookkosten en meer leenruimte; dat zit al in woonlasten en leentoets."))

    # --- erfpacht
    st = erf["status"]
    jaren = (erf["eind"] - vandaag.year) if erf["eind"] else None
    if st == "eigen":
        add(_item("erfpacht", "goed", "Grond", "eigen grond", erf["bron"], kort="eigen grond"))
    elif st == "eeuwig_afgekocht":
        add(_item("erfpacht", "goed", "Erfpacht", "eeuwigdurend afgekocht", erf["bron"], kort="erfpacht afgekocht"))
    elif st == "afgekocht_tot":
        p = 0.0 if jaren >= dr["erfpacht_afkoop_middel_jaren"] else (-1.0 if jaren >= dr["erfpacht_afkoop_kort_jaren"] else -2.0)
        oord = "sterk" if p <= -2.0 else ("let_op" if p < 0 else "neutraal")
        waarde = f"afgekocht tot {erf['eind']} ({jaren} jaar)" if jaren >= 0 else f"afkoop verlopen in {erf['eind']}"
        add(_item("erfpacht", oord, "Erfpacht", waarde, erf["bron"], p, kort=f"afkoop tot {erf['eind']}",
                  vraag=f"Vraag wat de canon na {erf['eind']} wordt."))
    elif st == "eeuwig_canon":
        add(_item("erfpacht", "let_op", "Erfpachtcanon", f"{eur(erf['canon_jaar'])} per jaar" if erf["canon_jaar"] else "bedrag onbekend",
                  erf["bron"], -0.5, kort="erfpachtcanon", vraag="Vraag de erfpachtakte en de datum van de volgende herziening.",
                  uitleg="De canon zit in je woonlasten en in de leentoets." if erf["canon_jaar"] else None))
    elif st == "voortdurend":
        add(_item("erfpacht", "sterk", "Erfpacht", "voortdurend, canon herzien", erf["bron"], -1.5, kort="voortdurende erfpacht",
                  vraag="Vraag wanneer het tijdvak afloopt en wat de nieuwe canon wordt."))
    elif st in ("afgekocht_looptijd_onbekend", "erfpacht_onduidelijk"):
        add(_item("erfpacht", "let_op", "Erfpacht", "voorwaarden onbekend", erf["bron"], -0.5, kort="erfpacht onduidelijk",
                  vraag="Vraag de erfpachtakte: canon, afkoop en einddatum."))
    else:
        add(_item("erfpacht", "onbekend", "Eigendom", "niet vermeld", erf["bron"], kort="eigendom onbekend",
                  vraag="Vraag of het eigen grond of erfpacht is."))

    # --- VvE (kenmerken, tekst en BAG)
    vs = vve_status(ch, tekst)
    if vve is not None:
        per_m2 = vve / max(m2, 1)
        if stook:
            add(_item("vve", "neutraal", "VvE-bijdrage", f"{eur(vve)} p/m incl. stookkosten", vve_bron, kort=f"VvE {eur(vve)}"))
        elif per_m2 < dr["vve_bijdrage_laag_per_m2"]:
            add(_item("vve", "let_op", "VvE-bijdrage", f"{eur(vve)} p/m, laag", vve_bron, kort=f"VvE {eur(vve)} laag",
                      vraag="Lage bijdrage: vraag de stand van het reservefonds en het MJOP."))
        elif per_m2 > dr["vve_bijdrage_hoog_per_m2"]:
            add(_item("vve", "let_op", "VvE-bijdrage", f"{eur(vve)} p/m, hoog", vve_bron, kort=f"VvE {eur(vve)} hoog",
                      uitleg="Zit al in je woonlasten."))
        else:
            add(_item("vve", "neutraal", "VvE-bijdrage", f"{eur(vve)} p/m", vve_bron, kort=f"VvE {eur(vve)}"))
    else:
        add(_item("vve", "onbekend", "VvE-bijdrage", f"onbekend, gerekend met {eur(VVE_GESCHAT)}", "aanname",
                  kort="VvE-bijdrage onbekend", vraag="Vraag de maandelijkse VvE-bijdrage op."))
    sleutels = ("Inschrijving KvK", "Jaarlijkse vergadering", "Reservefonds aanwezig", "Onderhoudsplan")
    ja = {k: (ch.get(k) or "").lower().startswith("ja") for k in sleutels}
    nee = {k: (ch.get(k) or "").lower().startswith("nee") for k in sleutels}
    if vs == "slapend":
        add(_item("vve", "sterk", "VvE", "niet actief", "kenmerken en tekst", -1.0, kort="VvE niet actief",
                  vraag="Vraag of de VvE een rekening, verzekering en vergadering heeft."))
    if nee["Reservefonds aanwezig"]:
        add(_item("vve", "let_op", "Reservefonds", "nee", "kenmerk 'Reservefonds aanwezig'", -0.5, kort="geen reservefonds"))
    if nee["Onderhoudsplan"]:
        add(_item("vve", "let_op", "Onderhoudsplan", "nee", "kenmerk 'Onderhoudsplan'", -0.5, kort="geen MJOP"))
    if all(ja.values()) and vs != "slapend":
        add(_item("vve", "goed", "VvE op orde", "KvK, ALV, reservefonds, MJOP", "kenmerken", 0.5, kort="VvE op orde"))
    bag_st, bag, bag_reden = _bron(verrijking, "bag")
    n_vbo = _getal((bag or {}).get("aantal_vbo_pand")) if bag_st == "ok" else None
    klein = n_vbo is not None and n_vbo <= dr["vve_klein_max_woningen"]
    if n_vbo is not None:
        if klein:
            add(_item("vve", "let_op", "Kleine VvE", f"{n_vbo} adressen in het pand", "BAG", -0.5, kort=f"VvE van {n_vbo}",
                      vraag="Kleine VvE: vraag notulen, MJOP en stand reservefonds.",
                      uitleg="Grote kosten (dak, fundering) deel je met weinig eigenaren."))
        else:
            add(_item("vve", "neutraal", "Pand", f"{n_vbo} adressen", "BAG", kort=f"pand met {n_vbo} adressen"))
    elif bag_st in ("onbekend", "budget"):
        add(_item("vve", "onbekend", "VvE-grootte", "onbekend", "BAG", kort="VvE-grootte onbekend",
                  uitleg=bag_reden or ("budget van deze run op, volgende run verder" if bag_st == "budget" else None)))

    # --- fundering (alleen bij een bouwjaar voor 1970)
    bj_funda = _getal(w.get("construction_year")) or _getal(ch.get("Bouwjaar"))
    bj_bag = _getal((bag or {}).get("bouwjaar")) if bag_st == "ok" else None
    bj = bj_bag or bj_funda
    fu_st, fu, fu_reden = _bron(verrijking, "fundering")
    herstel = "funderingsherstel" in sig_ids
    if bj and bj >= dr["fundering_bouwjaar_voor"] and fu_st in ("ok", "niet_nodig", "onbekend", "budget"):
        add(_item("fundering", "neutraal", "Fundering", f"bouwjaar {bj}, na {dr['fundering_bouwjaar_voor']}", "BAG" if bj_bag else "funda",
                  kort="fundering geen risico"))
    elif fu_st in ("onbekend", "budget"):
        add(_item("fundering", "onbekend", "Funderingsrisico buurt", "onbekend", "Klimaateffectatlas", kort="fundering onbekend",
                  uitleg=fu_reden or ("budget van deze run op" if fu_st == "budget" else None),
                  vraag="Vraag de VvE of er funderingsonderzoek is gedaan."))
    elif fu_st == "ok" and fu:
        klassen = [(k, v) for k, v in fu.items() if v in FUND_KLASSE]
        if klassen:
            soort, klasse = max(klassen, key=lambda kv: FUND_KLASSE.index(kv[1]))
            rang = FUND_KLASSE.index(klasse)
            if rang >= FUND_KLASSE.index(dr["fundering_klasse_let_op"]) and not herstel:
                p = {2: -0.5, 3: -1.0, 4: -1.5}[rang] + (-0.5 if klein else 0.0)
                add(_item("fundering", "sterk" if rang >= 3 else "let_op", "Funderingsrisico buurt", f"{soort} {klasse} (2050)",
                          "Klimaateffectatlas, buurtniveau", p, kort=f"fundering {klasse}",
                          vraag="Vraag de VvE naar funderingsonderzoek en of ze ervoor reserveert.",
                          uitleg=f"Pand uit {bj}. Kaart op buurtniveau: geen oordeel over dit pand."))
            else:
                add(_item("fundering", "goed", "Funderingsrisico buurt", klasse, "Klimaateffectatlas, buurtniveau",
                          0.5 if herstel and rang >= 2 else 0.0, kort=f"fundering {klasse}"))
    if herstel:
        add(_item("fundering", "goed", "Funderingsherstel", "uitgevoerd (advertentie)", "advertentietekst", kort="fundering hersteld",
                  vraag="Vraag het rapport en de garantie van het herstel."))

    # --- geluid aan de gevel
    ge_st, ge, ge_reden = _bron(verrijking, "geluid")
    if ge_st == "ok" and ge:
        stap = 0
        for veld in ("lden_weg", "lnight_weg", "lden_trein", "lnight_trein"):
            v = ge.get(veld)
            if isinstance(v, (int, float)) and v > -9000:
                stap = max(stap, sum(v >= grens for grens in dr[f"geluid_{veld}"]))
        lden_w = ge.get("lden_weg") if isinstance(ge.get("lden_weg"), (int, float)) and ge.get("lden_weg") > -9000 else None
        lden_t = ge.get("lden_trein") if isinstance(ge.get("lden_trein"), (int, float)) and ge.get("lden_trein") > -9000 else None
        if lden_w is None and lden_t is None:
            add(_item("geluid", "goed", "Geluid aan de gevel", "rustig, onder de kaartgrens", "RIVM 2022/2023", kort="rustige gevel"))
        else:
            bron_txt = "trein" if (lden_t or 0) > (lden_w or 0) else "weg"
            lden = lden_t if bron_txt == "trein" else lden_w
            nacht = ge.get(f"lnight_{bron_txt}")
            waarde = f"{nl(lden, 0)} dB" + (f", nacht {nl(nacht, 0)} dB" if isinstance(nacht, (int, float)) and nacht > -9000 else "") + f" ({bron_txt})"
            oord = ["neutraal", "let_op", "sterk", "sterk"][min(stap, 3)]
            if stap == 0 and lden < dr["geluid_rustig_lden"]:
                oord, waarde = "goed", f"rustig, {nl(lden, 0)} dB"
            add(_item("geluid", oord, "Geluid aan de gevel", waarde, "RIVM 2022/2023", -0.5 * min(stap, 3),
                      kort=f"geluid {nl(lden, 0)} dB", uitleg="Rekenwaarde op het adrespunt. De achtergevel kan stiller zijn.",
                      vraag="Vraag aan welke kant de slaapkamer ligt en hoe de ramen zijn." if stap else None))
    elif ge_st in ("onbekend", "budget"):
        add(_item("geluid", "onbekend", "Geluid aan de gevel", "onbekend", "RIVM", kort="geluid onbekend", uitleg=ge_reden))

    # --- buurt: jouw lijst blijft leidend, data vult aan (nooit bevolkingskenmerken)
    for zin in twijfel_z:
        it = _twijfel_item(zin)
        if it:
            add(it)
    bu_st, bu, bu_reden = _bron(verrijking, "buurt")
    tv_st, tv_data, _ = _bron(verrijking, "tevredenheid")
    if bu_st == "ok" and bu:
        k = bu.get("kscore")
        if isinstance(k, (int, float)) and int(k) in LBM_KLASSE:
            k = int(k)
            jaar = bu.get("jaar") or 2024
            if k <= dr["leefbaarometer_twijfel_max"]:
                if not any(z.lower().startswith("twijfelbuurt") for z in twijfel_z):
                    twijfel_z.append(f"Leefbaarometer {LBM_KLASSE[k]} ({jaar}). Buurt staat niet op jouw lijst.")
                add(_item("buurt", "sterk", "Leefbaarometer", f"{LBM_KLASSE[k]} ({jaar})", "Leefbaarometer 3.0", kort="buurt zwak",
                          uitleg="Staat niet op je uitsluitlijst. Zelf bekijken en eventueel toevoegen."))
            elif k >= dr["leefbaarometer_goed_min"]:
                add(_item("buurt", "goed", "Leefbaarometer", f"{LBM_KLASSE[k]} ({jaar})", "Leefbaarometer 3.0", 0.5,
                          kort=f"buurt {LBM_KLASSE[k]}"))
            else:
                add(_item("buurt", "neutraal", "Leefbaarometer", f"{LBM_KLASSE[k]} ({jaar})", "Leefbaarometer 3.0",
                          kort=f"buurt {LBM_KLASSE[k]}"))
        onv = bu.get("onv")
        if isinstance(onv, (int, float)) and onv <= dr["leefbaarometer_onv_let_op"]:
            add(_item("buurt", "let_op", "Overlast en onveiligheid", f"{nl(onv, 2)} t.o.v. NL", "Leefbaarometer 3.0", -0.5,
                      kort="overlast buurt"))
    elif bu_st in ("onbekend", "budget"):
        add(_item("buurt", "onbekend", "Buurtdata", "onbekend", "Leefbaarometer", kort="buurtdata onbekend", uitleg=bu_reden))
    tv = (bu or {}).get("tevreden_woonomgeving") if bu_st == "ok" else None
    if tv is None and tv_st == "ok" and tv_data:
        tv = tv_data.get("tevreden_woonomgeving", tv_data.get("tevreden"))
    if isinstance(tv, (int, float)):
        if tv < dr["tevreden_woonomgeving_let_op"]:
            add(_item("buurt", "let_op", "Tevreden met buurt", f"{nl(tv, 0)}% (2024)", "RIVM-gezondheidsmonitor", -0.5,
                      kort=f"tevreden {nl(tv, 0)}%", uitleg="Modelschatting met onzekerheidsmarge."))
        elif tv >= dr["tevreden_woonomgeving_goed"]:
            add(_item("buurt", "goed", "Tevreden met buurt", f"{nl(tv, 0)}% (2024)", "RIVM-gezondheidsmonitor",
                      kort=f"tevreden {nl(tv, 0)}%"))

    # --- staat en clausules uit de advertentie
    kluswoning = bool(w.get("is_fixer_upper")) or "opknapper" in sig_ids
    for sid, _, _, onderdeel, oord, lab, waarde, p, kort, vraag in signalen:
        if sid == "funderingsherstel":
            continue
        add(_item(onderdeel, oord, lab, waarde, "advertentietekst", p, kort=kort, vraag=vraag))
    if w.get("is_fixer_upper") and "opknapper" not in sig_ids:
        add(_item("staat", "sterk", "Staat", "kluswoning", "funda", -1.5, kort="kluswoning",
                  vraag="Laat een verbouwbegroting maken voor je bod."))
    if w.get("is_monument"):
        add(_item("staat", "neutraal", "Monument", "ja", "funda", kort="monument",
                  vraag="Vraag welke verbouwingen een vergunning nodig hebben."))
    if (ch.get("Aanvaarding") or w.get("acceptance") or "").lower().startswith("in overleg"):
        add(_item("clausules", "neutraal", "Oplevering", "in overleg", "kenmerk 'Aanvaarding'", kort="oplevering in overleg"))
    inhoud = _getal(ch.get("Inhoud")) if ch.get("Inhoud") else None
    if inhoud and m2 and inhoud / m2 >= dr["inhoud_per_m2_hoog"]:
        add(_item("staat", "neutraal", "Hoge ruimtes", f"{nl(inhoud / m2)} m³ per m²", "kenmerk 'Inhoud'", kort="hoge ruimtes",
                  uitleg="Sfeer, maar ook meer stookkosten."))
    if bj_bag and bj_funda and abs(bj_bag - bj_funda) >= dr["bouwjaar_verschil_bag_funda"]:
        add(_item("staat", "neutraal", "Bouwjaar", f"funda {bj_funda}, BAG {bj_bag}", "BAG", kort="bouwjaar wijkt af"))

    # --- markt (alleen als de lage prijs niet al door staat of label verklaard wordt)
    mk = enr.get("market") if isinstance(enr.get("market"), dict) else {}
    gem = mk.get("avg_asking_price_per_m2")
    if prijs and isinstance(gem, (int, float)) and gem > 0 and m2:
        diff = (prijs / m2 - gem) / gem * 100
        verklaard = kluswoning or label in dr["energielabel_slecht"]
        uitleg = "Vergeleken met alle te koop staande woningen in de buurt."
        if diff <= -dr["markt_afwijking_pct"] and not verklaard:
            add(_item("markt", "goed", "Prijs per m²", f"{nl(abs(diff), 0)}% onder de buurt", "funda-buurtcijfer", 0.5,
                      kort=f"m²-prijs {nl(abs(diff), 0)}% onder buurt", uitleg=uitleg))
        elif diff >= dr["markt_afwijking_pct"]:
            add(_item("markt", "let_op", "Prijs per m²", f"{nl(diff, 0)}% boven de buurt", "funda-buurtcijfer", -0.5,
                      kort=f"m²-prijs {nl(diff, 0)}% boven buurt", uitleg=uitleg))

    # --- parkeren (standaard gewicht 0: zichtbaar, telt niet mee)
    if w.get("has_parking_on_site") or w.get("has_parking_enclosed"):
        add(_item("parkeren", "goed", "Parkeerplek", "eigen plek", "funda", 0.5, kort="eigen parkeerplek"))

    # --- informatief: WOZ, makelaar, open huis (0 punten)
    if hist["woz"] and hist["woz"]["bedrag"]:
        jr = hist["woz"]["jaar"]
        add(_item("info", "neutraal", "WOZ-waarde", f"{eur(hist['woz']['bedrag'])}" + (f" (WOZ {jr})" if jr else ""),
                  "funda prijshistorie", kort="WOZ-waarde",
                  uitleg=f"Waardepeildatum 1 januari {jr - 1}: de WOZ loopt achter op de markt." if jr else None))
    br_info = enr.get("broker") if isinstance(enr.get("broker"), dict) else {}
    if isinstance(br_info.get("review_average"), (int, float)):
        n = br_info.get("review_count")
        add(_item("info", "neutraal", "Makelaar", f"{nl(br_info['review_average'])} uit {n} reviews" if n else nl(br_info["review_average"]),
                  "funda" + (f", {br_info['name']}" if br_info.get("name") else ""), kort="makelaar"))
    if w.get("open_house"):
        add(_item("info", "neutraal", "Open huis", "gepland", "funda", kort="open huis"))

    # --- kansen bij bieden: tellen niet mee, elke oorzaak één keer
    tr = (d or {}).get("_track") if isinstance((d or {}).get("_track"), dict) else {}
    if tr.get("gedaald") and tr.get("drop_bedrag"):
        add(_item("kans", "kans", "Prijs verlaagd", f"{eur(tr['drop_bedrag'])} lager", "eigen tracking", kort="prijs verlaagd",
                  uitleg=f"Was {eur(tr['eerdere_prijs'])}." if tr.get("eerdere_prijs") else None))
    elif prijs and hist["hoogste"] and hist["hoogste"] > prijs:
        add(_item("kans", "kans", "Prijs verlaagd", f"{eur(hist['hoogste'] - prijs)} lager", "funda prijshistorie",
                  kort="prijs verlaagd", uitleg=f"Hoogste vraagprijs sinds de laatste verkoop: {eur(hist['hoogste'])}."))
    dagen = tr.get("dagen") or 0
    if isinstance(dagen, (int, float)) and dagen >= cfg["lang_op_funda_dagen"]:
        add(_item("kans", "kans", "Lang te koop", f"{int(dagen)} dagen", "eigen tracking", kort="lang te koop"))

    return _samenvatten(cfg, items, gate, twijfel_z, fin, verrijking)


def _samenvatten(cfg: dict, items: list[dict], gate: dict, twijfel: list[str], fin: dict, verrijking) -> dict:
    gw, bereik = cfg["gewichten"], cfg["gewichten"]["_bereik"]
    per: dict[str, dict] = {}
    for it in items:
        o = it["onderdeel"]
        if o not in bereik:
            it["punten"] = 0.0
            continue
        try:
            g = float(gw.get(o, 1))
        except (TypeError, ValueError):
            g = 1.0
        it["punten"] = round(it["punten"] * g, 2) + 0.0
        if it["oordeel"] == "onbekend":
            it["punten"] = 0.0
        per.setdefault(o, {"ruw": 0.0, "items": [], "g": g})
        per[o]["ruw"] += it["punten"]
        per[o]["items"].append(it)
    onderdelen = {}
    for o, v in per.items():
        lo, hi = sorted((bereik[o][0] * v["g"], bereik[o][1] * v["g"]))
        p = round(max(lo, min(hi, v["ruw"])), 2) + 0.0
        if abs(p) >= 0.05:
            hoofd = max(v["items"], key=lambda i: abs(i["punten"]))
            onderdelen[o] = {"punten": p, "kort": hoofd["kort"]}
    ruw = float(cfg["score_basis"]) + sum(o["punten"] for o in onderdelen.values())
    score = _rond1(max(0.0, min(10.0, ruw)))
    onbekend = [i for i in items if i["oordeel"] == "onbekend"]
    regel = uitleg_regel(score, onderdelen, len(onbekend), begrensd=(ruw < 0 or ruw > 10))
    volg = {"sterk": 0, "let_op": 1}
    let_op = sorted([i for i in items if i["groep"] == "let_op"], key=lambda i: (volg[i["oordeel"]], i["punten"]))
    plus = sorted([i for i in items if i["groep"] == "plus"], key=lambda i: -i["punten"])
    info = [i for i in items if i["groep"] == "info"]
    vragen: list[str] = []
    for i in let_op + onbekend + plus + info:
        if i.get("vraag") and i["vraag"] not in vragen:
            vragen.append(i["vraag"])
    for v in VRAGEN_ALTIJD:
        if v not in vragen:
            vragen.append(v)
    fin_uit = {k: v for k, v in fin.items() if k not in ("poort", "redenen")}
    namen = ["bag", "fundering", "geluid", "buurt"]
    if isinstance(verrijking, dict):
        namen += [k for k in verrijking if k not in namen and k in ("tevredenheid",)]
    poort_ = gate["poort"]
    return {
        "poort": poort_,
        "poort_redenen": gate["redenen"],
        "status_kort": status_kort(poort_, fin, gate["harde"], cfg),
        "twijfel": twijfel,
        "score": score,
        "onderdelen": onderdelen,
        "uitleg_regel": regel,
        "let_op": let_op,
        "pluspunten": plus,
        "onbekend": onbekend,
        "info": info,
        "kansen": [i for i in items if i["groep"] == "kans"],
        "zelf_nagaan": vragen[:6],
        "financiering": fin_uit,
        "verrijking": {n: _bron(verrijking, n)[0] for n in namen},
    }


def uitleg_regel(score: float, onderdelen: dict, n_onbekend: int, max_len: int = 96, begrensd: bool = False) -> str:
    """'8,3 · woonlasten € 1.254 +1,5 · balkon 6 m² zuid +1,0 · 3e zonder lift −0,5 · overig +1,3 · 1 onbekend'.

    De basis staat niet in de regel: de legenda zegt één keer '5 = voldoet aan je eisen'."""
    rij = sorted(onderdelen.values(), key=lambda o: -abs(o["punten"]))
    kop = nl(score) + (" (grens)" if begrensd else "")
    staart = [f"{n_onbekend} onbekend"] if n_onbekend else []
    for n in (3, 2, 1, 0):
        top, rest = rij[:n], rij[n:]
        delen = [kop] + [f"{o['kort']} {teken(o['punten'])}" for o in top]
        r = sum(o["punten"] for o in rest)
        if rest and abs(r) >= 0.05:
            delen.append(f"{'overig' if top else 'onderdelen'} {teken(r)}")
        regel = " · ".join(delen + staart)
        if len(regel) <= max_len:
            return regel
    return _kap(regel, max_len)


# ---------------------------------------------------------------------------------------
# Sortering en logging
# ---------------------------------------------------------------------------------------
def _geen_vraagprijs(rij: dict, b: dict) -> bool:
    """Geen vraagprijs: 'prijs_onbekend' van de rapportrij, anders financiering.koopsom None, anders de poort."""
    if "prijs_onbekend" in rij:
        return bool(rij["prijs_onbekend"])
    fin = b.get("financiering")
    if isinstance(fin, dict) and "koopsom" in fin:
        return fin.get("koopsom") is None
    return b.get("poort") == "PRIJS ONBEKEND"


def sorteer_sleutel(rij: dict) -> tuple:
    """(geen vraagprijs, poort_rang, twijfel, -score). Werkt op een rapportrij (met 'beoordeling') of op
    de beoordeling zelf. Zonder vraagprijs altijd achteraan, ook als een harde eis (veiling) de woning
    op PAST NIET zet."""
    b = rij.get("beoordeling") if isinstance(rij.get("beoordeling"), dict) else rij
    return (_geen_vraagprijs(rij, b), POORT_RANG.get(b.get("poort"), len(POORT_RANG)), bool(b.get("twijfel")),
            -float(b.get("score") or 0))


def sorteer(rijen: list[dict]) -> list[dict]:
    """Zonder vraagprijs achteraan, dan poort, twijfel onderaan binnen de poort, score aflopend. In place."""
    rijen.sort(key=sorteer_sleutel)
    return rijen


def log_kenmerk_labels(details_lijst) -> dict[str, int]:
    """Welke kenmerklabels funda gaf en hoe vaak: alleen namen en aantallen, geen waarden of adressen."""
    teller: dict[str, int] = {}
    for det in details_lijst or []:
        if not isinstance(det, dict):
            continue
        ch = det.get("characteristics") if isinstance(det.get("characteristics"), dict) else None
        if ch is None:
            continue
        for k in ch:
            if isinstance(k, str) and k.strip():
                teller[k.strip()] = teller.get(k.strip(), 0) + 1
    return dict(sorted(teller.items(), key=lambda kv: (-kv[1], kv[0])))
