"""Beoordelingsmodel voor het woningrapport: poort, score, uitleg en sortering.

Pure functies: geen netwerk, geen bestanden behalve de tabel in data/, geen import van
funda_rapport of funda_zoek. Importeren kan zonder funda_personal.json. Ontwerp en
besluiten: CLAUDE.md, sectie "Rapport, beoordeling en PWA".

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
oude_sleutels(personal) -> list[str]
    Namen van oude aliassen in de config die niet meer gelezen worden (voor een waarschuwing).
beoordeel(d, details, routes, twijfel, profiel, config, verrijking=None, *, rente=None, vandaag=None) -> dict
    De beoordeling van één woning volgens het datacontract (zie "Uitvoer" hieronder).
poort(woning, cfg, fin) -> dict
    Harde eisen plus de financiële uitkomst: {"poort", "redenen", "harde"}.
poort_financieel(tekort, over, cfg) -> str
    Alleen de drempels: PAST, KRAP of PAST NIET.
status_kort(poort, fin, harde, cfg) -> str     'Past · € 196 onder je grens'
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
prijswijzigingen(d) -> list                    de ruwe prijshistorie uit d["_enrichment"]
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
avg_asking_price_per_m2, broker met name, review_average, review_count), _twijfel
(als twijfel None is) en _zonder_prijs_gezien (JJJJ-MM-DD uit de sitemapcache: de woning
stond eerder zonder vraagprijs te koop; "onbekend" als de dag niet is bijgehouden).
routes: [{"label", "km", "soort": "weg"|"schatting"}]. twijfel: korte zinnen uit
funda_zoek (bijv. "Twijfelbuurt Leyenburg (jouw lijst)."). verrijking: per bron
{"status": "ok"|"onbekend"|"budget"|"uit"|"niet_nodig", "data": {...}, "reden": str}
of direct de data (kaal, zonder status). Bronnen: bag, fundering, geluid, buurt en, zonder
scoregewicht, kerncijfers, veiligheid, lucht, klimaat en erfgoed (omgeving_items()). rente: dict uit
funda_rente.huidige_rente(): {"pct", "bron", "datum", "oud", "melding"}. Zonder rente:
financien.rente.pct uit de config, anders STANDAARD_RENTE (4,11%, 6 juli 2026).

Uitvoer (het datacontract)
==========================
beoordeel() geeft precies deze sleutels (vastgepind in test_funda_beoordeling.py,
test_contract): poort, poort_redenen, status_kort, twijfel, score (0 tot 10, één
decimaal), onderdelen, uitleg_regel (hooguit 96 tekens), let_op, pluspunten, onbekend,
info, kansen, zelf_nagaan (hooguit 6), financiering en verrijking (status per bron).
Een item in let_op, pluspunten, onbekend, info of kansen heeft onderdeel, groep, oordeel,
label (hooguit 24 tekens), waarde (hooguit 32), bron, punten, kort, vraag en uitleg.
financiering heeft max_hypotheek, marge_lenen, kosten_koper, kk_soort, tekort, netto,
bruto, grens, grens_soort, opbouw (None bij Prijs onbekend), rente, rente_datum,
rentevast_jaren, en daarnaast:
financiering["scenarios"]: [{"id", "label", "max_hypotheek", "max_koopsom", "past"}], alleen
voor de scenario's uit financien.scenarios, met het energielabel en de erfpachtcanon van deze
woning. past = tekort aan eigen geld (na buffer) hooguit kk_onzekerheid; de woonlasten tellen
daar niet in mee, die bepalen de poort. Leeg zonder financien-blok en bij Prijs onbekend.
financiering["planning"]: id van het planningsscenario (de poort volgt dat scenario), of None.
financiering["scenario_tekst"]: "Past " + het label van het eerste scenario (op datum) waarin de
woning past, met een kleine eerste letter ("Past nu", "Past later"); bij een voorwaardelijk
scenario "Past alleen " + het label ("Past alleen met bonus"); anders "Past in geen
scenario". Nooit een inkomensbedrag. None zonder scenario's.

Config
======
Sleutel "beoordeling" in funda_personal.json (in Actions: secret FUNDA_PERSONAL_JSON).
Alles is optioneel; de standaard staat in STANDAARD hieronder, die van "verrijking" in
funda_verrijking.STANDAARD (de enige plek).

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
      "drempels": {...},                       (zie STANDAARD)
      "verrijking": {...}                      (zie funda_verrijking.STANDAARD)
    }

Sleutel "financien" in funda_personal.json (naast "beoordeling"; persoonlijke cijfers,
alleen in de secret, nooit in de repo):

    "financien": {
      "alleenstaand": true,
      "starter_tot": "JJJJ-MM-DD",       startersvrijstelling tot deze datum; leeg = leeftijd < 35
      "planning": "later",               scenario voor de poort; standaard het eerste na "nu" op
                                         datum (een voorwaardelijk alleen als er geen ander is)
      "scenarios": {
        "nu":          {"bruto_jaar": 0, "label": "Nu"},
        "later":       {"bruto_jaar": 0, "datum": "JJJJ-MM-DD", "label": "Later"},
        "later_extra": {"bruto_jaar": 0, "datum": "JJJJ-MM-DD", "label": "Met bonus",
                        "voorwaardelijk": true}
      },                                 bruto_jaar = toetsinkomen; een kaal getal mag ook.
                                         Optioneel per scenario: "datum" (anders uit het id:
                                         JJJJ_MM = de eerste van die maand, anders vandaag),
                                         "eigen_geld" en "voorwaardelijk" (true = nog onzeker:
                                         tekst "Past alleen ...", op dezelfde datum na het
                                         gewone scenario).
                                         Zonder label: "Nu", "Vanaf <maand jaar>" of het id.
      "studieschuld": {"maandlast": 0},  werkelijke maandlast DUO
      "bkr": [{"limiet": 0, "opgezegd": true}],   doorlopend krediet; aflopend: {"maandlast": 0}
      "eigen_geld": {"nu": 0, "datum": "JJJJ-MM-DD", "per_maand": 0, "buffer": 0},
                                         eigen geld op een scenariodatum = nu + per_maand x hele
                                         maanden sinds "datum" (leeg = vandaag); buffer gaat eraf
      "kosten_koper": {"vast": 6000, "nhg_pct": 0.4},   vaste posten in euro; NHG in procent
      "rente": {"pct": 4.11, "datum": "JJJJ-MM-DD", "rentevast_jaren": 10}
    }                                    rente: de enige plek voor rente en rentevast; funda_rente
                                         leest daar ook "bron", "nhg", "ltv" en "max_dagen"

Alleen deze sleutels gelden. De oude aliassen en plekken (financien.toetsinkomen, ook per
scenario, startersvrijstelling_tot, verplichtingen_maand, bkr_limieten, buffer op het hoogste niveau,
eigen_geld per scenario-id, rente.handmatig en rente.rentevast_jaar; beoordeling.financien;
beoordeling.financiering.max_woonlasten_netto, woonlasten_marge_past_niet, rente, rente_datum,
rentevast_jaren en rente_max_dagen) worden sinds nov 2026 niet meer gelezen. oude_sleutels()
noemt ze, zodat funda_rapport waarschuwt in plaats van stil de standaard te nemen.

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
# Rekenregels en aannames, met bron en status. Eén blok.
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
# Geen energielabel bekend: reken de energiekosten met een aangenomen label. Standaard het
# slechtste (G), tenzij het bouwjaar een ondergrens geeft: de isolatie-eisen uit de bouwregels
# van dat jaar. Eigen, voorzichtige indeling (geen officiele tabel); alleen voor de energiekosten,
# niet voor de leentoets en niet voor de score. (vanaf bouwjaar, label), nieuwste eerst.
LABEL_AANNAME_ZONDER = "G"
LABEL_AANNAME_BOUWJAAR = ((2006, "A"), (2000, "B"), (1992, "C"), (1975, "E"))
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
        # Rente, rentevast en de leeftijdsgrens staan in financien.rente (één plek).
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
        "staat": 1, "clausules": 1, "markt": 1, "parkeren": 0, "schuin_dak": 1,
        "_bereik": {
            "woonlasten": [-1.5, 1.5], "buitenruimte": [-1.5, 1.5], "oppervlak": [-1.0, 1.0],
            "woonlaag_lift": [-1.5, 0.0], "reisafstand": [-1.0, 1.0], "energielabel": [-1.0, 0.0],
            "erfpacht": [-2.0, 0.0], "vve": [-1.5, 0.5], "fundering": [-2.0, 0.5], "geluid": [-1.5, 0.0],
            "buurt": [-1.0, 0.5], "staat": [-1.5, 0.0], "clausules": [-1.0, 0.0], "markt": [-0.5, 0.5],
            "parkeren": [0.0, 0.5], "schuin_dak": [-1.0, 0.0],
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
        "schuin_dak_punten": -0.5,              # woonruimte onder een schuin dak (zeker); 0 = alleen melden
        # Open bronnen van 18 nov 2026: alleen voor "let op" zonder punten (gewichten volgen later).
        "no2_eu_2030": 20, "no2_who": 10, "no2_eu_grens": 40,
        "pm25_eu_2030": 10, "pm25_who": 5, "pm25_eu_grens": 25,
    },
    # Geen "verrijking": de standaard daarvan staat alleen in funda_verrijking.STANDAARD. Een blok
    # beoordeling.verrijking uit de config komt via _merge ongewijzigd in cfg["verrijking"], en
    # funda_verrijking.instellingen() legt het over die standaard heen.
}

OORDEEL_GROEP = {"sterk": "let_op", "let_op": "let_op", "goed": "plus", "neutraal": "info",
                 "onbekend": "onbekend", "kans": "kans"}
# Klassen van de Leefbaarometer en van de funderingsrisico's (Klimaateffectatlas). Eén bron:
# funda_verrijking importeert ze hier vandaan, niet andersom (deze module importeert geen projectmodules).
LBM_KLASSE = {1: "zeer onvoldoende", 2: "ruim onvoldoende", 3: "onvoldoende", 4: "zwak", 5: "voldoende",
              6: "ruim voldoende", 7: "goed", 8: "zeer goed", 9: "uitstekend"}
FUND_KLASSE = ["zeer laag", "laag", "matig", "hoog", "zeer hoog"]
VRAGEN_ALTIJD = ["Vraag de VvE-stukken: notulen van 2 jaar, onderhoudsplan (MJOP), reservefonds en begroting.",
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

    lang_op_funda_dagen op het hoogste niveau (die leest funda_zoek ook) geldt als
    beoordeling.lang_op_funda_dagen ontbreekt. Het blok personal["financien"] komt mee als
    cfg["financien"] (of None). Oude aliassen worden niet gelezen (zie oude_sleutels()).
    """
    personal = personal if isinstance(personal, dict) else {}
    eigen = _blok(personal, "beoordeling")
    cfg = _merge(STANDAARD, eigen)
    if "lang_op_funda_dagen" not in eigen and personal.get("lang_op_funda_dagen") is not None:
        cfg["lang_op_funda_dagen"] = personal["lang_op_funda_dagen"]
    fin = personal.get("financien")
    cfg["financien"] = copy.deepcopy(fin) if isinstance(fin, dict) else None
    return cfg


# Sleutels die tot nov 2026 als alias golden en nu niet meer gelezen worden (CLAUDE.md, "Config").
OUDE_SLEUTELS = {
    "beoordeling": ("financien",),
    "beoordeling.financiering": ("max_woonlasten_netto", "woonlasten_marge_past_niet", "rente", "rente_datum",
                                 "rentevast_jaren", "rente_max_dagen"),
    "financien": ("toetsinkomen", "startersvrijstelling_tot", "verplichtingen_maand", "bkr_limieten", "buffer"),
    "financien.rente": ("handmatig", "rentevast_jaar"),
}
EIGEN_GELD_SLEUTELS = ("nu", "datum", "per_maand", "buffer")


def oude_sleutels(personal: dict | None) -> list[str]:
    """Vaste paden (nooit waarden) van oude aliassen in de config, bijv. "financien.toetsinkomen".
    Die worden niet meer gelezen; funda_rapport waarschuwt ermee in plaats van stil de standaard te nemen.

    De uitvoer komt in de publieke Actions-log, dus alleen namen uit de code: een scenario-id of een
    andere sleutel die de gebruiker zelf koos wordt "<scenario>", en elk pad staat er hooguit één keer."""
    personal = personal if isinstance(personal, dict) else {}
    uit = []
    for pad, namen in OUDE_SLEUTELS.items():
        blok = personal
        for deel in pad.split("."):
            blok = blok.get(deel) if isinstance(blok, dict) else None
        if isinstance(blok, dict):
            uit += [f"{pad}.{n}" for n in namen if n in blok]
    fin = _blok(personal, "financien")
    if any(k not in EIGEN_GELD_SLEUTELS and not str(k).startswith("_") for k in _blok(fin, "eigen_geld")):
        uit.append("financien.eigen_geld.<scenario>")
    if any(isinstance(v, dict) and "toetsinkomen" in v for v in _blok(fin, "scenarios").values()):
        uit.append("financien.scenarios.<scenario>.toetsinkomen")
    return uit


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


def _begrens(x: float, laag: float, hoog: float) -> float:
    return max(laag, min(hoog, x))


def _blok(d: dict, sleutel: str) -> dict:
    """d[sleutel] als dat een dict is, anders een lege dict."""
    v = d.get(sleutel)
    return v if isinstance(v, dict) else {}


def _is_getal(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


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

    Volgorde: financien.rente.pct (met financien.rente.datum), dan STANDAARD_RENTE."""
    vandaag = _datum(vandaag, date.today())
    r = _blok((cfg or {}).get("financien") or {}, "rente")
    if r.get("pct") is not None:
        pct, bron, datum = r["pct"], "handmatig", r.get("datum")
    else:
        pct, bron, datum = STANDAARD_RENTE["pct"], "standaard", STANDAARD_RENTE["datum"]
    d = _datum(datum)
    max_dagen = int(r.get("max_dagen") or 30)   # zelfde grens als funda_rente
    dagen = (vandaag - d).days if d else None
    oud = dagen is None or dagen > max_dagen
    melding = None
    if oud:
        melding = (f"Rente is {dagen} dagen oud: woonlasten kunnen afwijken." if dagen is not None
                   else "Rente zonder datum: woonlasten kunnen afwijken.")
    return {"pct": round(_als_fractie(pct, 0.2) * 100, 3), "bron": bron, "datum": d.isoformat() if d else None,
            "oud": oud, "melding": melding}


def _rentevast(rente: dict | None, cfg: dict) -> int:
    for bron in ((rente or {}), ((cfg.get("financien") or {}).get("rente") or {})):
        if isinstance(bron, dict) and bron.get("rentevast_jaren") is not None:
            return int(bron["rentevast_jaren"])
    return STANDAARD_RENTE["rentevast_jaren"]   # niets ingesteld: 30 jaar, zoals tot nu toe


# ---------------------------------------------------------------------------------------
# Financien: scenario's, eigen geld, verplichtingen
# ---------------------------------------------------------------------------------------
def _scenario_datum(sid: str, vandaag: date) -> date:
    m = re.match(r"^(\d{4})[_-](\d{1,2})", str(sid))
    try:
        return date(int(m.group(1)), int(m.group(2)), 1) if m else vandaag
    except ValueError:
        return vandaag


def _scenario_label(sid: str) -> str:
    """Label als de config er geen geeft: "nu" wordt "Nu", een id JJJJ_MM wordt "Vanaf <maand jaar>"
    (wat erna in het id staat komt er met spaties achter), anders het id met spaties.

    De rest van het id blijft bewust staan: zonder die rest krijgen twee scenario's in dezelfde maand
    (een gewoon en een voorwaardelijk) hetzelfde label, ook in de budgettabel van het rapport. Het is
    tekst uit de config, geen naam in de code."""
    if sid == "nu":
        return "Nu"
    m = re.match(r"^(\d{4})[_-](\d{1,2})(?:[_-](.*))?$", sid)
    if m and 1 <= int(m.group(2)) <= 12:
        tekst = f"Vanaf {_MAANDEN_KORT[int(m.group(2)) - 1]} {m.group(1)}"
        return tekst + (" " + m.group(3).replace("_", " ") if m.group(3) else "")
    tekst = sid.replace("_", " ")
    return tekst[:1].upper() + tekst[1:]


def _standaard_planning(lijst: list[dict]) -> str:
    """Zonder (geldige) planning: het eerste scenario na "nu" op datum, of het enige.

    Een voorwaardelijk scenario alleen als er geen gewoon scenario na "nu" is: de poort rust niet op een
    onzeker scenario zolang er een zeker is (zo deed de vaste standaard het ook: het gewone scenario, niet
    het voorwaardelijke). Het verschil met "het eerste op datum" telt alleen als het voorwaardelijke eerder
    valt. lijst staat al op datum."""
    na_nu = [s for s in lijst if s["id"] != "nu"]
    gewoon = [s for s in na_nu if not s.get("voorwaardelijk")]
    return (gewoon or na_nu or lijst)[0]["id"]


def _maanden_tussen(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month))


def financien_invoer(cfg: dict, profiel: dict | None, vandaag=None) -> dict:
    """Normaliseer cfg["financien"] tot één vaste vorm. Zonder dat blok (bron "profiel") komt alles uit
    het oude profiel: bruto_jaar, eigen_inleg en duo_maandlast, als één scenario "profiel"."""
    vandaag = _datum(vandaag, date.today())
    profiel = profiel or {}
    f_cfg = cfg.get("financiering") or {}
    uit_profiel = not isinstance(cfg.get("financien"), dict)
    raw = {} if uit_profiel else cfg["financien"]

    sc_raw = raw.get("scenarios")
    if isinstance(sc_raw, dict):
        paren = list(sc_raw.items())
    else:
        paren = [(s.get("id"), s) for s in sc_raw if isinstance(s, dict) and s.get("id")] if isinstance(sc_raw, list) else []
    lijst = []
    for sid, v in paren:
        sid = str(sid)
        v = v if isinstance(v, dict) else {"bruto_jaar": v}
        if sid.startswith("_") or v.get("bruto_jaar") is None:
            continue
        datum = _datum(v.get("datum")) or _scenario_datum(sid, vandaag)
        lijst.append({"id": sid, "label": str(v.get("label") or _scenario_label(sid)),
                      "bruto_jaar": float(v["bruto_jaar"]), "datum": max(datum, vandaag),
                      "eigen_geld": float(v["eigen_geld"]) if v.get("eigen_geld") is not None else None,
                      "voorwaardelijk": v.get("voorwaardelijk") is True})
    # Op datum; op dezelfde datum een voorwaardelijk scenario na het gewone (sort is stabiel).
    lijst.sort(key=lambda s: (s["datum"], s["voorwaardelijk"]))
    if not lijst:
        lijst = [{"id": "profiel", "label": "Profiel", "bruto_jaar": float(profiel.get("bruto_jaar") or 0), "datum": vandaag,
                  "eigen_geld": float(profiel.get("eigen_inleg") or 0) if uit_profiel else None, "voorwaardelijk": False}]
    planning = raw.get("planning")
    if planning not in [s["id"] for s in lijst]:
        planning = _standaard_planning(lijst)

    st = raw.get("studieschuld")
    studie = st.get("maandlast", 0) if isinstance(st, dict) else st if isinstance(st, (int, float)) else profiel.get("duo_maandlast", 0)
    bkr = raw.get("bkr")
    if isinstance(bkr, (int, float)):
        bkr = [{"limiet": bkr}]
    bkr_maand = 0.0
    for k in bkr if isinstance(bkr, list) else []:
        if isinstance(k, dict) and not k.get("opgezegd"):
            bkr_maand += float(k["maandlast"]) if k.get("maandlast") is not None else BKR_PCT_LIMIET * float(k.get("limiet") or 0)

    eg = raw.get("eigen_geld")
    eg = {"nu": eg} if isinstance(eg, (int, float)) else eg if isinstance(eg, dict) else {}
    kk = _blok(raw, "kosten_koper")
    return {
        "bron": "profiel" if uit_profiel else "financien",
        "alleenstaand": bool(raw.get("alleenstaand", f_cfg.get("alleenstaand", True))),
        "starter_tot": _datum(raw.get("starter_tot")) or _datum(f_cfg.get("starter_tot")),
        "leeftijd": profiel.get("leeftijd"),
        "scenarios": lijst,
        "planning": planning,
        "studieschuld_maand": float(studie or 0),
        "bkr_maand": bkr_maand,
        "eigen_geld": {"nu": float(eg.get("nu", profiel.get("eigen_inleg", 0)) or 0), "datum": _datum(eg.get("datum"), vandaag),
                       "per_maand": float(eg.get("per_maand") or 0)},
        "buffer": float(eg.get("buffer", 0) or 0),
        "kk_vast": float(kk.get("vast", KK_VAST_STANDAARD)),
        "nhg_pct": _als_fractie(kk.get("nhg_pct", NHG_PREMIE * 100), 0.05),
    }


def _eigen_geld_op(inv: dict, scenario: dict) -> float:
    """Eigen geld op de scenariodatum, zonder buffer."""
    if scenario.get("eigen_geld") is not None:
        return float(scenario["eigen_geld"])
    eg = inv["eigen_geld"]
    return eg["nu"] + eg["per_maand"] * _maanden_tussen(eg["datum"], scenario["datum"])


def _is_starter(inv: dict, datum: date) -> bool:
    if inv.get("starter_tot"):
        return datum < inv["starter_tot"]
    try:
        return inv.get("leeftijd") is not None and int(inv["leeftijd"]) < STARTER_LEEFTIJD_TOT
    except (TypeError, ValueError):
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
    """Korte zin zonder bedragen: het eerste scenario (op datum) waarin de woning past.

    "Past " + het label met een kleine eerste letter ("Past nu"); bij een voorwaardelijk scenario
    "Past alleen " + het label. Past hij nergens: "Past in geen scenario"."""
    for s in scenarios:
        if s["past"]:
            lab = s["label"] or s["id"]
            return ("Past alleen " if s.get("_voorwaardelijk") else "Past ") + lab[:1].lower() + lab[1:]
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


_FIN_ZONDER_PRIJS = ("max_hypotheek", "marge_lenen", "kosten_koper", "kk_soort", "tekort", "netto", "bruto", "grens",
                     "grens_soort", "opbouw", "koopsom", "hypotheek", "over", "scenario_tekst")


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
    vast = {"rente": frac, "rente_datum": rente.get("datum"), "rente_bron": rente.get("bron"), "rentevast_jaren": rentevast,
            "planning": inv["planning"] if met_scenarios else None}
    prijs = woning.get("prijs")
    if not (isinstance(prijs, (int, float)) and prijs > 0):
        return {**dict.fromkeys(_FIN_ZONDER_PRIJS), **vast, "rente": _als_fractie(rente.get("pct"), 0.2), "scenarios": [],
                "poort": "PRIJS ONBEKEND", "redenen": ["Geen vraagprijs: geen leentoets en geen woonlasten."]}

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
               "_hyp": hyp, "_kk": kk, "_kk_soort": kk_soort, "_tekort": tekort, "_bruto_jaar": s["bruto_jaar"],
               "_voorwaardelijk": s["voorwaardelijk"]}
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
        redenen.append(f"Hoogste hypotheek {eur(max_hyp)}: {eur(koop - max_hyp)} uit eigen geld.")
    if tekort > f["kk_onzekerheid"]:
        redenen.append(f"Eigen geld: {eur(tekort)} tekort.")
    if over > 0:
        redenen.append(f"Woonlasten {eur(over)} boven " + ("je grens." if grens_soort == "netto" else "de norm (bruto)."))

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
        "koopsom": koop, "hypotheek": hyp, "over": over, **vast,
        "scenarios": [{k: v for k, v in s.items() if not k.startswith("_")} for s in scenarios] if met_scenarios else [],
        "scenario_tekst": _scenario_tekst(scenarios) if met_scenarios else None,
        "poort": status, "redenen": redenen,
    }


def poort(woning: dict, cfg: dict, fin: dict) -> dict:
    """Harde eisen boven op de financiële poort. Nooit onzichtbaar.

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
    """'Past · € 196 onder je grens'."""
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
    # Een canon met bedrag betekent erfpacht, ook als 'zonder erfpacht' elders 'exclusief' bedoelt
    # ('Servicekosten € 120 (zonder erfpacht). Canon € 350 per jaar.'): dan nooit 'eigen grond'.
    erfpacht_in_tekst = _erfpacht_genoemd(t) or bool(re.search(r"\bcanon\b.{0,60}€|€.{0,40}\bcanon\b", t))
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


_RICHTING = r"(zuid[- ]?west|zuid[- ]?oost|noord[- ]?west|noord[- ]?oost|zuid|noord|west|oost)"


def _richting(m: re.Match | None) -> str | None:
    """'zuid-west' -> 'Zuidwest'."""
    return m.group(1).replace("-", "").replace(" ", "").capitalize() if m else None


def buitenruimte(d: dict, ch: dict, tekst: str) -> dict:
    """{"soort": None|"frans balkon"|"balkon"|"dakterras"|"tuin", "m2", "richting", "bron", "zeker"}.

    Kenmerken eerst; in tekst woordgrenzen en ontkenning; een frans balkon is geen buitenruimte.
    Zonligging: de richting na balkon/terras/tuin, niet de eerste richting in de tekst.
    zeker=False: niets gevonden, dus onbekend (geen minpunt).
    Bewust geen harde filter in funda_zoek: funda's boolean (has_balcony) is onbetrouwbaar,
    dus buitenruimte telt hier mee in de score en wijst geen woning af."""
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
            richting = _richting(re.search(r"\b(?:op|aan)\s+(?:het\s+|de\s+)?" + _RICHTING + r"(?:en|zijde|kant)?\b",
                                           t[anker.end(): anker.end() + 60]))
            if richting:
                break
        if richting is None and soort == "tuin" and ch.get("Ligging tuin"):
            richting = _richting(re.search(_RICHTING, ch["Ligging tuin"].lower()))
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


def label_aanname(label: str, bouwjaar=None) -> tuple[str, str | None]:
    """(label om de energiekosten mee te rekenen, toelichting of None).

    Een bekend label blijft wat het is. Zonder label: het slechtste (G), tenzij het bouwjaar
    een beter label aannemelijk maakt (LABEL_AANNAME_BOUWJAAR). Niet zeker, wel voorzichtig:
    liever te hoge stookkosten dan een woning die op papier past en in de winter niet."""
    if label in ENERGIE_PER_LABEL:
        return label, None
    for vanaf, aanname in LABEL_AANNAME_BOUWJAAR:
        if _is_getal(bouwjaar) and vanaf <= bouwjaar <= 2100:
            return aanname, f"bouwjaar {int(bouwjaar)}"
    return LABEL_AANNAME_ZONDER, None


_RANGTELWOORD = {"eerste": 1, "tweede": 2, "derde": 3, "vierde": 4, "vijfde": 5, "zesde": 6, "zevende": 7,
                 "achtste": 8, "negende": 9, "tiende": 10}
_RANG = "|".join(_RANGTELWOORD)
_WOONLAAG_TEKST = re.compile(r"\bop\s+de\s+(\d+)e\s+woonlaag|\bop\s+de\s+(" + _RANG + r")\s+woonlaag")
_VERDIEPING_TEKST = re.compile(r"\b(?:op\s+de\s+)?(\d+)e\s+(?:verdieping|etage)\b|\bop\s+de\s+(" + _RANG
                               + r")\s+(?:verdieping|etage)\b")


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
        for patroon, erbij in ((_WOONLAAG_TEKST, 0), (_VERDIEPING_TEKST, 1)):
            m = patroon.search(t)
            if m:
                laag = (int(m.group(1)) if m.group(1) else _RANGTELWOORD[m.group(2)]) + erbij
                bron = "advertentietekst"
                break
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


_DAK_SCHUIN = re.compile(r"zadeldak|schilddak|mansarde|lessenaar|tentdak|dwarskap|puntdak|\bkap\b")
_DAK_PLAT = re.compile(r"plat\s*dak")
# Sterk: het gaat vanzelf over de woonruimte (schuine wanden, kapverdieping, dakkapel).
_KAP_TEKST = re.compile(
    r"schuine?\s+(?:wand(?:en)?|plafonds?)\b|\bkapverdieping|\bknieschot(?:ten)?\b|\bdakkapel(?:len)?\b")
# Zwak: kan ook over het pand gaan ("het complex heeft een schuin dak", "onder de kap van de stalling",
# "de zolderverdieping is van de bovenburen"). Telt alleen met een woonruimtewoord in dezelfde zin.
_KAP_ZWAK = re.compile(
    r"schuine?\s+(?:dak(?:en|vlak(?:ken)?|delen|kant(?:en)?)?|kap|zijdes?)\b|onder\s+de\s+(?:kap|nok)\b"
    r"|\bzolder(?:verdieping|etage)|\bvide\b[^.]{0,40}\bnok\b|\bin\s+de\s+nok\b")
_WOONRUIMTE = re.compile(r"\b(?:slaap|woon|bad|werk|studeer|hobby|logeer|kinder|zit|eet)?kamers?\b|\bkeuken|\bwoning\b"
                         r"|\bappartement\b|\bwoonruimte|\bleefruimte|\bwerkplek|\bstudio\b|\bliving\b|\bwoonlaag\b"
                         r"|\bwoonverdieping|\bslaapverdieping|\bmaisonnette")
_KNIESCHOT = re.compile(r"\bknieschot(?:ten)?\b")
# Een zin over iets anders dan deze woning: de buren, het buurpand.
_NIET_DEZE_WONING = re.compile(r"\b(?:boven|beneden|onder)?buren\b|\bbuurpand|\bnaastgelegen|\bbuurman\b|\bbuurvrouw\b")
# Een zin over iets anders dan de woonruimte: de berging op zolder, de gemeenschappelijke zolder, de buren.
_KAP_NIET_WONING = re.compile(r"\bberg(?:ing|zolder|ruimte|vliering)|\bvliering|\bopslag|gemeenschappelijk|gezamenlijk"
                              r"|\bwaszolder|" + _NIET_DEZE_WONING.pattern)
# Bij een zwakke aanwijzing ook: het complex, de VvE, de stalling, de kavel, de installaties.
_KAP_NIET_WONING_ZWAK = re.compile(_KAP_NIET_WONING.pattern + r"|\bcomplex\b|\bappartementencomplex|\bvve\b"
                                   r"|vereniging\s+van\s+eigenaren|\bstalling|\bcarport|\bkavel\b|\binstallaties?\b|\bcv-?ketel")
_BOVENSTE = re.compile(r"\b(?:bovenste|hoogste)\s+(?:verdieping|etage|woonlaag)|\btopverdieping|\btopetage|\bdakappartement")
_ONTKEND_VOOR = re.compile(r"\b(?:geen|niet|zonder|nergens)\b[^.]{0,25}$")
# Ontkenning achter het woord: "zonwering is niet toegestaan", "airco is niet aanwezig", "de zolderetage is
# niet bij de woning inbegrepen". Alleen deze vaste vormen: "schuine wanden, maar niet storend" blijft een feit.
_ONTKEND_NA = re.compile(r"^[^.!?\n]{0,45}?\b(?:niet|geen)\s+(?:\w+\s+){0,2}?(?:aanwezig|toegestaan|inbegrepen|mogelijk"
                         r"|bij\s+de\s+woning|van\s+toepassing)\b")


def _zin_rond(t: str, start: int, eind: int) -> str:
    a = max(t.rfind(c, 0, start) for c in ".!?\n") + 1
    einden = [i for i in (t.find(c, eind) for c in ".!?\n") if i >= 0]
    return t[a:min(einden) if einden else len(t)]


def _zonder_ontkenning(patroon: re.Pattern, t: str, niet: re.Pattern | None = None, eis: re.Pattern | None = None) -> bool:
    """Staat het patroon in t, niet ontkend (ervoor of erachter)? niet: een zin waarin dit patroon staat,
    telt niet. eis: de zin moet dit patroon ook bevatten."""
    for m in patroon.finditer(t):
        if _ONTKEND_VOOR.search(t[max(0, m.start() - 30):m.start()]) or _ONTKEND_NA.search(t[m.end():m.end() + 80]):
            continue
        if niet is not None or eis is not None:
            zin = _zin_rond(t, m.start(), m.end())
            if (niet is not None and niet.search(zin)) or (eis is not None and not eis.search(zin)):
                continue
        return True
    return False


def _lagen(ch: dict) -> tuple[int, int | None]:
    """(woonlagen van de woning, bouwlagen van het pand of None)."""
    return _getal(ch.get("Aantal woonlagen")) or 1, _getal(ch.get("Aantal bouwlagen")) or _getal(ch.get("Bouwlagen"))


def schuin_dak(ch: dict, tekst: str = "", laag: int | None = None) -> dict:
    """Ligt (een deel van) de woonruimte onder een schuin dak? -> {"status", "bron", "maisonnette", "bovenste"}.

    status "zeker": de advertentie zegt het over de woonruimte, of het kenmerk 'Soort dak' noemt een
    schuin dak en de woning ligt aantoonbaar bovenin (tekst "bovenste verdieping", of woonlaag plus
    eigen woonlagen = het aantal bouwlagen van het pand). "mogelijk": schuin daktype, maar niet aan te
    tonen dat de woning bovenin ligt. None: plat dak of geen aanwijzing (onbekend is geen minpunt).
    Kenmerken eerst, tekst als aanvulling. In de tekst twee soorten aanwijzingen:
    - sterk (schuine wanden, kapverdieping, knieschot, dakkapel): telt, behalve in een zin over de
      berging, een gemeenschappelijke zolder of de buren;
    - zwak (schuin dak, onder de kap, zolderverdieping, vide tot in de nok): telt alleen met een
      woonruimtewoord in dezelfde zin (slaapkamer, woning, werkplek) en niet in een zin over het complex,
      de VvE, de stalling of de bovenburen. Ligt de woning aantoonbaar niet bovenin (woonlaag onder het
      aantal bouwlagen), dan telt een zwakke aanwijzing ook niet.
    Een ontkenning telt niet, ervoor ("geen schuine wanden") of erachter ("de zolderetage is niet bij de
    woning inbegrepen"). De waarden van 'Soort dak' zijn niet gemeten op echte advertenties: de
    labeltelling in de log laat zien of funda het kenmerk zo noemt."""
    t = (tekst or "").lower()
    dak = str(ch.get("Soort dak") or ch.get("Dak") or "").lower()
    schuin_type = bool(_DAK_SCHUIN.search(dak))
    woonlagen, bouwlagen = _lagen(ch)
    maisonnette = woonlagen >= 2 or bool(re.search(r"\bmaisonnette|\bdubbel(?:e)?\s+bovenhuis",
                                                   t + " " + str(ch.get("Soort appartement") or "").lower()))
    # Bovenin of niet is alleen aan te tonen met de woonlaag en het aantal bouwlagen van het pand.
    bovenin = laag + woonlagen - 1 >= bouwlagen if laag and bouwlagen else None
    niet_bovenin = bovenin is False
    bovenste = bool(bovenin) or (not niet_bovenin and _zonder_ontkenning(_BOVENSTE, t, niet=_KAP_NIET_WONING))
    uit = {"status": None, "bron": "", "maisonnette": maisonnette, "bovenste": bovenste}
    # Een knieschot staat altijd in de woonruimte onder de kap, ook in een zin over bergruimte erachter.
    if (_zonder_ontkenning(_KAP_TEKST, t, niet=_KAP_NIET_WONING) or _zonder_ontkenning(_KNIESCHOT, t)
            or (not niet_bovenin and _zonder_ontkenning(_KAP_ZWAK, t, niet=_KAP_NIET_WONING_ZWAK, eis=_WOONRUIMTE))):
        uit.update(status="zeker", bron="advertentietekst")
    elif schuin_type and bovenste and not _DAK_PLAT.search(dak):
        uit.update(status="zeker", bron="kenmerk 'Soort dak'")
    elif schuin_type:                                    # ook een samengesteld dak (deels plat)
        uit.update(status="mogelijk", bron="kenmerk 'Soort dak'")
    return uit


_VVE_KENMERKEN = ("Inschrijving KvK", "Jaarlijkse vergadering", "Reservefonds aanwezig", "Onderhoudsplan")


def _vve_kenmerken(ch: dict) -> tuple[list[str], list[str]]:
    """De VvE-kenmerken met 'ja' en die met 'nee'."""
    waarde = {k: (ch.get(k) or "").lower() for k in _VVE_KENMERKEN}
    return [k for k in waarde if waarde[k].startswith("ja")], [k for k in waarde if waarde[k].startswith("nee")]


def vve_status(ch: dict, tekst: str) -> str:
    """'actief', 'slapend' of 'onbekend' (kenmerken KvK, ALV, reservefonds, MJOP; tekst)."""
    if re.search(r"(?:vve|vereniging)[^.]{0,40}\b(?:niet actief|slapend)|slapende\s+vve", (tekst or "").lower()):
        return "slapend"
    ja, nee = _vve_kenmerken(ch)
    return "slapend" if len(nee) >= 3 else "actief" if len(ja) >= 3 else "onbekend"


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
     "Vraag de notulen van de laatste twee ledenvergaderingen en het bedrag."),
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


def prijswijzigingen(d: dict | None) -> list:
    """De ruwe prijshistorie uit d["_enrichment"]["price_history"]: {"changes": [...]} of een kale lijst."""
    enr = (d or {}).get("_enrichment") if isinstance((d or {}).get("_enrichment"), dict) else {}
    ph = enr.get("price_history")
    changes = ph.get("changes") if isinstance(ph, dict) else ph
    return changes if isinstance(changes, list) else []


def prijshistorie(changes) -> dict:
    """Vraagprijzen na de laatste verkoop (op tijd gesorteerd), de hoogste daarvan en de nieuwste WOZ.

    Een piek uit een eerdere verkoopperiode telt niet als prijsdaling. De WOZ is
    {"bedrag", "jaar", "datum"} (datum ISO uit de regel, of None), of None. "zonder_prijs": de datum
    van de laatste vraagprijsregel zonder bedrag na de laatste verkoop, of None."""
    rijen = sorted(((_tijd(c), str(c.get("status") or "").lower(), _prijs_van(c)) for c in (changes or []) if isinstance(c, dict)),
                   key=lambda r: r[0])
    na = max((t for t, status, _ in rijen if status == "sold"), default="")
    vraag = [(t, p) for t, status, p in rijen if status == "asking_price" and t > na]
    met = [(t, p) for t, p in vraag if p]
    # Een vraagprijsregel zonder bedrag na de laatste verkoop: de woning stond toen zonder prijs te koop.
    # Alleen de datum; er wordt nooit met een prijs 0 gerekend.
    zonder = [t for t, p in vraag if not p]
    woz_t, woz_p = next(((t, p) for t, status, p in reversed(rijen) if status == "woz" and p), (None, None))
    return {
        "zonder_prijs": zonder[-1] if zonder else None,
        "vraagprijzen": [{"prijs": p, "datum": t} for t, p in met],
        "hoogste": max((p for _, p in met), default=None),
        "woz": {"bedrag": woz_p, "jaar": int(woz_t[:4]) if woz_t else None, "datum": woz_t or None} if woz_p else None,
    }


# ---------------------------------------------------------------------------------------
# Verrijking (alleen lezen; ophalen gebeurt in funda_verrijking.py)
# ---------------------------------------------------------------------------------------
def _bron(verrijking: dict | None, naam: str) -> tuple[str, dict | None, str | None]:
    """(status, data, reden) voor één bron; accepteert {"status", "data"} en kale data."""
    e = verrijking.get(naam) if isinstance(verrijking, dict) else None
    if e is None:
        return "uit", None, None
    if e == "fout":
        return "onbekend", None, "bron gaf geen antwoord"
    if e == "niet_nodig":
        return "niet_nodig", None, None
    if not isinstance(e, dict):
        return "onbekend", None, None
    if "status" not in e:
        return "ok", e, None
    data = e.get("data") if isinstance(e.get("data"), dict) else None
    st = str(e.get("status") or "onbekend")
    return ("onbekend" if st == "ok" and data is None else st), data, e.get("reden")


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


def _dag_kort(x: date) -> str:
    return f"{x.day} {_MAANDEN_KORT[x.month - 1]} {x.year}"


# Onderdeel van de items uit de open bronnen van 18 nov 2026. Geen gewicht en geen bereik: ze tellen
# niet mee in de score tot de spreiding tussen buurten bekend is. funda_ui toont ze in een eigen blok.
OMGEVING = "omgeving"
INFO_TONEN = (OMGEVING,)
# Informatieve items over de woning zelf ("Schuin dak: mogelijk", "Eerder zonder prijs"): funda_ui toont ze
# in het blok Woning, de markdown in een eigen regel.
INFO_WONING = ("prijsverloop", "schuin_dak")
# d["_zonder_prijs_gezien"] als de dag van de waarneming niet bekend is (een cache-element van voor
# 19 nov 2026 hield geen datum bij): dan een item zonder datum, geen verzonnen datum. Zelfde waarde als
# funda_sitemap_zoek.ZONDER_PRIJS_ONBEKEND (test_funda_sitemap.py).
ZONDER_PRIJS_ONBEKEND = "onbekend"
_OVERSTROMING = {1: ("extreem klein", "kleiner dan 1 op 30.000"), 2: ("zeer klein", "1 op 3.000 tot 1 op 30.000"),
                 3: ("klein", "1 op 300 tot 1 op 3.000"), 4: ("middelgroot", "1 op 30 tot 1 op 300"),
                 5: ("groot", "groter dan 1 op 30")}
_GRONDWATER = {1: "kleine toename", 2: "aanmerkelijke toename", 3: "grote toename", 4: "zeer grote toename",
               5: "kleine kans"}
_WATEROVERLAST_LET_OP = ("hoog", "zeer hoog")


def _omgeving(label: str, waarde: str, bron: str, kort: str, uitleg: str, let_op: bool = False, vraag: str | None = None) -> dict:
    return _item(OMGEVING, "let_op" if let_op else "neutraal", label, waarde, bron, kort=kort, vraag=vraag, uitleg=uitleg)


def _procenten(*paren) -> list[str]:
    """['55% koop', '45% huur'] voor de paren (getal, naam) waarvan het getal bekend is."""
    return [f"{nl(x, 0)}% {naam}" for x, naam in paren if _is_getal(x)]


def _omgeving_kerncijfers(kc: dict) -> list[dict]:
    jaar = kc.get("jaar") or 2024
    bron, uitgave = f"CBS {jaar}", f"(CBS, uitgave {jaar})"
    uit = []
    if _is_getal(kc.get("woz")) and kc["woz"] > 0:
        uit.append(_omgeving("WOZ buurt gemiddeld", eur(kc["woz"] * 1000), bron, "WOZ buurt",
                             f"Gemiddelde WOZ-waarde van alle woningen in de buurt {uitgave}. Zegt niets over deze woning zelf."))
    delen = _procenten((kc.get("koop_pct"), "koop"), (kc.get("huur_pct"), "huur"))
    if delen:
        extra = _procenten((kc.get("corporatie_pct"), "van een woningcorporatie"), (kc.get("meergezins_pct"), "appartementen"))
        uit.append(_omgeving("Koop en huur buurt", ", ".join(delen), bron, "koop en huur",
                             f"Aandeel van de woningen in de buurt {uitgave}" + (": " + ", ".join(extra) if extra else "") + "."))
    afst = [(kc.get(f"{lang}_km"), kort, lang) for kort, lang in (("super", "supermarkt"), ("trein", "treinstation"), ("huisarts", "huisarts"))]
    afst = [a for a in afst if _is_getal(a[0])]
    if afst:
        uit.append(_omgeving("Voorzieningen", ", ".join(f"{kort} {nl(x)} km" for x, kort, _ in afst[:2]), bron, "voorzieningen",
                             "Gemiddelde afstand over de weg vanuit de buurt: "
                             + ", ".join(f"{lang} {nl(x)} km" for x, _, lang in afst) + f" {uitgave}."))
    delen = _procenten((kc.get("aardgasvrij_pct"), "aardgasvrij"), (kc.get("stadsverwarming_pct"), "warmtenet"))
    if delen:
        uit.append(_omgeving("Verwarming buurt", ", ".join(delen), bron, "verwarming buurt",
                             f"Aandeel woningen in de buurt zonder aardgas en met stadsverwarming {uitgave}. "
                             "Zegt iets over hoe ver de buurt is met van het gas af gaan."))
    return uit


_POLITIECIJFERS = (("misdrijven", "Misdrijven buurt", "Alle geregistreerde misdrijven"),
                   ("woninginbraak", "Woninginbraak buurt", "Diefstal en inbraak uit woningen, ook pogingen"),
                   ("vernieling", "Vernieling buurt", "Vernieling en zaakbeschadiging"),
                   ("overlast", "Overlast buurt", "Alle geregistreerde meldingen van overlast"))


def _omgeving_veiligheid(vh: dict) -> list[dict]:
    def kort_getal(v):
        return nl(v, 0 if v >= 20 else 1)

    jaar = vh.get("jaar") or ""
    uit = []
    for sleutel, label, wat in _POLITIECIJFERS:
        x, g = vh.get(f"{sleutel}_per_1000"), vh.get(f"gem_{sleutel}_per_1000")
        if not _is_getal(x):
            continue
        waarde = f"{kort_getal(x)} per 1.000 woningen"
        if _is_getal(g):
            met = f"{kort_getal(x)} per 1.000 (gemeente {kort_getal(g)})"
            waarde = met if len(met) <= 32 else waarde
        uit.append(_omgeving(label, waarde, f"politie via CBS, {jaar}".rstrip(", "), label.lower(),
                             f"{wat}, door de politie geregistreerd in {jaar}, per 1.000 woningen in de buurt"
                             + (f"; in de hele gemeente {kort_getal(g)}" if _is_getal(g) else "")
                             + ". Waar veel winkels, horeca of kantoren zijn, valt het cijfer hoger uit: "
                               "de noemer is het aantal woningen."))
    return uit


def _omgeving_lucht(lu: dict, dr: dict) -> list[dict]:
    """Duiding tegen het WHO-advies, de EU-grenswaarde vanaf 2030 en de huidige EU-grenswaarde."""
    uit = []
    for sleutel, label, naam in (("no2", "Stikstofdioxide (NO2)", "stikstofdioxide"), ("pm25", "Fijnstof (PM2,5)", "fijnstof PM2,5")):
        x = lu.get(sleutel)
        if not _is_getal(x):
            continue
        who, eu30, eu = dr[f"{sleutel}_who"], dr[f"{sleutel}_eu_2030"], dr[f"{sleutel}_eu_grens"]
        duiding = ("binnen WHO-advies" if x <= who else "boven WHO-advies" if x <= eu30
                   else "boven EU-norm 2030" if x <= eu else "boven EU-grenswaarde")
        uit.append(_omgeving(label, f"{nl(x)} µg/m³, {duiding}", "RIVM 2024", f"{sleutel} {nl(x)}",
                             f"Jaargemiddelde {naam} op dit punt in 2024, in microgram per m³. WHO-advies {who}, "
                             f"EU-grenswaarde {eu} en vanaf 2030 {eu30}.", let_op=duiding.startswith("boven EU")))
    if _is_getal(lu.get("groen_pct")):
        uit.append(_omgeving("Groen binnen 500 m", f"{nl(lu['groen_pct'], 0)}%", "RIVM 2022", "groen",
                             "Gemiddeld aandeel groen (bomen, struiken, gras) binnen 500 m van dit punt (RIVM-groenkaart 2022)."))
    return uit


def _omgeving_klimaat(kl: dict) -> list[dict]:
    bron, uit = "Klimaateffectatlas", []
    wo = kl.get("wateroverlast")
    if isinstance(wo, str) and wo:
        hoog = wo in _WATEROVERLAST_LET_OP
        uit.append(_omgeving("Wateroverlast bij bui",
                             "geen hinderlijke waterdiepte" if wo == "geen" else f"{wo}, {kl.get('waterdiepte') or ''}".rstrip(", "),
                             bron, "wateroverlast bij bui",
                             "Berekende waterdiepte rond het pand bij een extreme bui. Zegt vooral iets over de "
                             "begane grond, kelder en berging, niet over een hogere verdieping.", let_op=hoog,
                             vraag="Vraag of er water in de kelder, berging of entree heeft gestaan." if hoog else None))
    kans = kl.get("overstromingskans")
    if _is_getal(kans) and kans in _OVERSTROMING:      # een lijst of dict uit een beschadigde cache: overslaan
        naam, per_jaar = _OVERSTROMING[kans]
        uit.append(_omgeving("Overstromingskans", naam, bron, "overstromingskans",
                             f"Kans per jaar op meer dan 20 cm water op deze plek bij een overstroming: {per_jaar} "
                             "(huidige situatie).", let_op=kans >= 4))
    gw = kl.get("grondwater")
    if _is_getal(gw) and gw in _GRONDWATER:
        uit.append(_omgeving("Grondwateroverlast 2050", _GRONDWATER[gw], bron, "grondwateroverlast",
                             "Kleine kans op grondwateroverlast door een lage grondwaterstand." if gw == 5 else
                             "Toename van de kans op grondwateroverlast in 2050 (klimaatscenario hoog), "
                             "op gebiedsniveau: geen oordeel over dit pand.", let_op=gw in (3, 4)))
    return uit


def _omgeving_erfgoed(eg: dict, monument_funda: bool) -> list[dict]:
    uit = []
    if eg.get("gezicht"):
        sinds = f", aangewezen in {eg['gezicht_sinds']}" if eg.get("gezicht_sinds") else ""
        uit.append(_omgeving("Beschermd gezicht", str(eg["gezicht"]), "RCE", "beschermd gezicht",
                             f"Beschermd stads- of dorpsgezicht{sinds}. Voor veranderingen aan de buitenkant is vaker "
                             "een vergunning nodig; dat geldt ook voor onderhoud door de VvE."))
    n = eg.get("monumenten_dichtbij")
    if _is_getal(n) and n > 0 and not monument_funda:
        uit.append(_omgeving("Rijksmonument dichtbij", f"{int(n)} binnen 25 m", "RCE", "rijksmonument dichtbij",
                             "Dit pand zelf of een buurpand: controleer het adres in het monumentenregister. "
                             "Een monument vraagt een vergunning voor verbouwen en duurder onderhoud."))
    return uit


def omgeving_items(verrijking: dict | None, dr: dict | None = None, monument_funda: bool = False) -> list[dict]:
    """Items uit de open bronnen kerncijfers, veiligheid, lucht, klimaat en erfgoed. Allemaal 0 punten.

    Feitelijk en kort: het getal, het jaar en wat het betekent. Geen oordeel over een buurt. Een bron
    die uit staat of niets gaf, levert geen item (ook geen "onbekend": dat zou de regel "n onbekend"
    vullen met bronnen die niet meetellen); de status per bron staat in beoordeling["verrijking"]."""
    dr = dr or STANDAARD["drempels"]
    uit: list[dict] = []
    for naam, maak in (("kerncijfers", _omgeving_kerncijfers), ("veiligheid", _omgeving_veiligheid),
                       ("lucht", lambda lu: _omgeving_lucht(lu, dr)), ("klimaat", _omgeving_klimaat),
                       ("erfgoed", lambda eg: _omgeving_erfgoed(eg, monument_funda))):
        status, data, _ = _bron(verrijking, naam)
        if status == "ok" and data:
            uit += maak(data)
    return uit


# Binnenklimaat: een indicatie uit aanwijzingen, geen meting (verzoek eigenaar, 19 nov 2026). Twee informatieve
# items, "Zomer" en "Winter", 0 punten en geen gewicht. funda_ui toont ze in het blok Woning.
BINNENKLIMAAT = "binnenklimaat"
ISOLATIE_BOUWJAAR = 1975                       # daarvoor zelden isolatie vanaf de bouw (zelfde grens als label_aanname)
GROEN_WEINIG_PCT, GROEN_VEEL_PCT = 15, 40      # eigen indeling van het percentage groen binnen 500 m; niet geijkt
_LABEL_KOUD, _LABEL_WARM = ("E", "F", "G"), ("A++++", "A+++", "A++", "A+", "A", "B")
_ZON_WARM, _ZON_KOEL = ("Zuid", "Zuidwest", "West"), ("Noord", "Noordoost", "Oost")
_VEEL_GLAS = re.compile(r"grote\s+raampartij(?:en)?|glazen\s+(?:pui|gevel|wand)|\bglaspui|\bveel\s+glas\b|\bserre\b"
                        r"|\bdakramen?\b|\blichtkoepel|ramen\s+van\s+vloer\s+tot\s+plafond")
_DWARS = re.compile(r"\bdoorzon|\bhoek(?:appartement|woning|ligging)|dwarsventilatie"
                    r"|ramen\s+aan\s+(?:twee|2|drie|3)\s+(?:zijden|kanten)|aan\s+(?:twee|2|drie|3)\s+(?:zijden|kanten)\s+(?:ramen|daglicht)")
_HOEK = re.compile(r"\bhoek(?:appartement|woning|ligging)")
_ZONWERING = re.compile(r"zonwering|\bscreens?\b|zonnescherm(?:en)?|\brolluik(?:en)?\b|\bluiken\b|\bmarkiezen\b|\bmarkies\b"
                        r"|\bairco\b|airconditioning")
_ENKEL_GLAS = re.compile(r"\benkel\s*glas|gedeeltelijk\s+dubbel\s+glas")
_GOED_GLAS = re.compile(r"\bhr\s*\+*\s*-?\s*glas|dubbel\s+glas|dubbele\s+beglazing|triple\s+glas|drievoudig\s+glas|isolatieglas")
_ISOLATIE = re.compile(r"dakisolatie|muurisolatie|spouwmuurisolatie|gevelisolatie|vloerisolatie|volledig\s+ge[iï]soleerd")
_DAKISOLATIE = re.compile(r"dakisolatie|volledig\s+ge[iï]soleerd")
_KACHEL = re.compile(r"gaskachel|gashaard|moederhaard|elektrische\s+(?:verwarming|kachel)")
_COLLECTIEF = re.compile(r"stadsverwarming|blokverwarming|warmtenet")


def _klimaat_item(seizoen: str, tegen: list[str], voor: list[str], woorden: tuple, vraag: str, opmerkingen=()) -> dict:
    """Eén item van het binnenklimaat. woorden: (waarde bij meer tegen, bij gelijk, bij meer voor, kopje tegen, kopje voor)."""
    meer_tegen, gelijk, meer_voor, kop_tegen, kop_voor = woorden
    n_tegen, n_voor = len(tegen), len(voor)
    waarde = (f"{meer_tegen}: {n_tegen} aanwijzing" + ("" if n_tegen == 1 else "en") if n_tegen > n_voor else
              gelijk if n_tegen == n_voor else f"{meer_voor}: {n_voor} aanwijzing" + ("" if n_voor == 1 else "en"))
    uitleg = "Een indicatie uit de advertentie en open kaarten. De temperatuur in huis is niet gemeten." + "".join(
        f" {kop}: " + "; ".join(lijst) + "." for kop, lijst in ((kop_tegen, tegen), (kop_voor, voor), ("Niet meegeteld", opmerkingen))
        if lijst)
    return _item(BINNENKLIMAAT, "neutraal", seizoen, waarde, "aanwijzingen, niet gemeten",
                 kort=f"{seizoen.lower()}: " + waarde.split(":")[0], vraag=vraag, uitleg=uitleg)


def binnenklimaat(w: dict, ch: dict, tekst: str, bag: dict | None = None, verrijking: dict | None = None,
                  label: str = "?", reken_label: str | None = None, bouwjaar=None) -> list[dict]:
    """Indicatie van het binnenklimaat: hooguit twee informatieve items, "Zomer" en "Winter" (0 punten).

    Geen meting: alleen aanwijzingen uit de kenmerken, de advertentietekst en wat de verrijking al heeft
    (groen binnen 500 m), geen nieuw verzoek. Onbekend is geen aanwijzing en geen minpunt; zonder enige
    aanwijzing komt er geen item. Een onbekend energielabel telt niet mee: naast een andere aanwijzing voor
    de winter staat het rekenlabel uit label_aanname() in de uitleg onder "Niet meegeteld", als aanname.
    Daar staat ook stads- of blokverwarming (dat gaat over kosten, niet over warm of koud).
    Kenmerken eerst ('Isolatie', 'Verwarming', 'Voorzieningen', 'Soort appartement', 'Gelegen op'), de tekst
    als aanvulling en zonder ontkende zinnen ("geen airco", "zonwering is niet toegestaan") of zinnen over
    de buren ("het hoekappartement van de buren"). Niet gemeten op echte advertenties: 'Soort dak',
    'Aantal bouwlagen', de ligging van balkon of tuin als kenmerk, en zonwering of airco in 'Voorzieningen'."""
    ch = ch if isinstance(ch, dict) else {}
    t = (tekst or "").lower()

    def kenm(naam):
        return str(ch.get(naam) or "").lower()

    def genoemd(patroon, *kenmerken):
        return any(patroon.search(kenm(k)) for k in kenmerken) or _zonder_ontkenning(patroon, t, niet=_NIET_DEZE_WONING)

    iso, verw, soort = kenm("Isolatie"), kenm("Verwarming"), kenm("Soort appartement")
    laag = woonlaag(ch, tekst)[0]
    kap = schuin_dak(ch, tekst, laag)
    woonlagen, bouwlagen = _lagen(ch)
    onder_kap = kap["status"] == "zeker"
    bovenste = onder_kap or kap["bovenste"] or "penthouse" in soort
    # Alleen een uitdrukkelijke begane grond telt: of funda's "1e woonlaag" de begane grond is, is niet gemeten.
    begane_grond = "begane grond" in kenm("Gelegen op") or "benedenwoning" in soort
    tussen = not bovenste and not begane_grond and (
        "tussenverdieping" in soort or bool(laag and laag >= 2 and bouwlagen and laag + woonlagen - 1 < bouwlagen))
    hoek = genoemd(_HOEK, "Soort appartement", "Ligging")
    bj = bouwjaar if _is_getal(bouwjaar) else _getal(bag.get("bouwjaar")) if isinstance(bag, dict) else None
    oud = bool(bj and bj < ISOLATIE_BOUWJAAR)
    richting = buitenruimte(w or {}, ch, tekst)["richting"]
    lucht_st, lucht, _ = _bron(verrijking, "lucht")
    groen = lucht["groen_pct"] if lucht_st == "ok" and lucht and _is_getal(lucht.get("groen_pct")) else None
    deels_enkel = "gedeeltelijk dubbel glas" in iso or "gedeeltelijk dubbel glas" in t

    warm, koel = [], []
    if onder_kap:
        warm.append("woonruimte direct onder een schuin dak")
    elif bovenste:
        warm.append("bovenste woonlaag, direct onder het dak")
    if bovenste and oud and iso and not _DAKISOLATIE.search(iso) and not _zonder_ontkenning(_DAKISOLATIE, t):
        warm.append(f"bouwjaar {int(bj)} en geen dakisolatie genoemd")
    if richting in _ZON_WARM:
        warm.append(f"buitenruimte op het {richting.lower()}en: middag- en avondzon op die gevel")
    if genoemd(_VEEL_GLAS):
        warm.append("veel glas volgens de advertentie")
    if groen is not None and groen < GROEN_WEINIG_PCT:
        warm.append(f"weinig groen in de buurt ({nl(groen, 0)}% binnen 500 m)")
    if genoemd(_DWARS, "Soort appartement", "Ligging"):
        koel.append("ramen aan meer kanten (doorzon of hoek): 's avonds goed door te luchten")
    if genoemd(_ZONWERING, "Voorzieningen"):
        koel.append("zonwering, luiken of airco genoemd")
    if tussen:
        koel.append("tussenverdieping: geen dak direct boven de woning")
    if richting in _ZON_KOEL:
        koel.append(f"buitenruimte op het {richting.lower()}en: weinig middagzon op die gevel")
    if groen is not None and groen >= GROEN_VEEL_PCT:
        koel.append(f"veel groen in de buurt ({nl(groen, 0)}% binnen 500 m)")

    koud, behaaglijk = [], []
    if hoek and (begane_grond or bovenste):
        koud.append(("begane grond" if begane_grond else "bovenste woonlaag") + " op een hoek: veel buitenvlak")
    elif begane_grond:
        koud.append("begane grond: koude vloer mogelijk")
    elif bovenste:
        koud.append("bovenste woonlaag: warmteverlies via het dak mogelijk")
    elif hoek:
        koud.append("hoekligging: een extra buitengevel")
    if deels_enkel:
        koud.append("gedeeltelijk dubbel glas, dus deels enkel glas")
    elif genoemd(_ENKEL_GLAS, "Isolatie"):
        koud.append("enkel glas genoemd")
    isolatie = bool(_ISOLATIE.search(iso)) or _zonder_ontkenning(_ISOLATIE, t)
    if "geen isolatie" in iso:
        koud.append("volgens de advertentie geen isolatie")
    elif oud and iso and not isolatie:
        koud.append(f"bouwjaar {int(bj)} en geen dak-, muur- of vloerisolatie genoemd")
    if _KACHEL.search(verw):
        koud.append("verwarming met losse kachels, geen centrale verwarming")
    if tussen:
        behaaglijk.append("tussenverdieping: woningen erboven en eronder, weinig buitenvlak")
    if not deels_enkel and genoemd(_GOED_GLAS, "Isolatie"):
        behaaglijk.append("dubbel of HR-glas genoemd")
    if isolatie:
        behaaglijk.append("dak-, muur- of vloerisolatie genoemd")
    # Het label: een bekend label is een aanwijzing. Een aangenomen label niet: dat staat alleen als
    # opmerking in de uitleg, naast een echte aanwijzing, en telt niet mee in "n aanwijzingen".
    reken = reken_label or label
    opmerkingen = []
    if label in _LABEL_KOUD:
        koud.append(f"energielabel {label}")
    elif label in _LABEL_WARM:
        behaaglijk.append(f"energielabel {label}")
    elif label not in ENERGIE_PER_LABEL and (koud or behaaglijk):
        if reken in _LABEL_KOUD:
            opmerkingen.append(f"energielabel onbekend, gerekend als {reken}: een aanname, geen gegeven")
        elif reken in _LABEL_WARM:
            opmerkingen.append(f"energielabel onbekend, gerekend als {reken} op grond van het bouwjaar: een aanname")
    # Stads- of blokverwarming zegt iets over de kosten, niet over warm of koud.
    if _COLLECTIEF.search(verw):
        opmerkingen.append("stads- of blokverwarming: de stookkosten zitten dan vaak in de servicekosten")

    uit: list[dict] = []
    if warm or koel:
        uit.append(_klimaat_item("Zomer", warm, koel, ("kans op warmte", "aanwijzingen voor warm en koel", "eerder koel",
                                                       "Warmer", "Koeler of beter af te koelen"),
                                 "Vraag bij de bezichtiging hoe warm het in de zomer wordt en of het 's avonds afkoelt."))
    if koud or behaaglijk:
        uit.append(_klimaat_item("Winter", koud, behaaglijk, ("kans op kou", "aanwijzingen voor warm en koud", "eerder warm",
                                                             "Kouder", "Warmer"),
                                 "Vraag bij de bezichtiging naar tocht, koude vloeren en het energieverbruik van vorig jaar.",
                                 opmerkingen))
    return uit


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


def _oppervlak(w: dict) -> int:
    m2 = w.get("living_area") or 0
    try:
        return int(m2)
    except (TypeError, ValueError):
        return _getal(m2) or 0


# De stappen van beoordeel(): elk geeft de items van één onderdeel. De volgorde van de items telt (bij
# gelijke punten noemt de uitlegregel het eerste item), dus beoordeel() roept ze in vaste volgorde aan.
def _items_geld(fin: dict, dr: dict, kk_onz: float) -> list[dict]:
    """Woonlasten als onderdeel van de score (de financiering zelf is de poort), eigen geld en leenruimte."""
    if fin["netto"] is None:
        return [_item("woonlasten", "onbekend", "Woonlasten", "prijs onbekend", "funda", kort="woonlasten onbekend",
                      vraag="Vraag de vraagprijs of een richtprijs.")]
    netto_grens = fin["grens_soort"] == "netto"
    lasten = fin["netto"] if netto_grens else fin["bruto"]
    ruimte = fin["grens"] - lasten
    oord = "goed" if ruimte >= dr["woonlasten_ruim_onder_grens"] else ("let_op" if ruimte < 0 else "neutraal")
    uit = [_item("woonlasten", oord, "Woonlasten", f"{eur(lasten)} {'netto' if netto_grens else 'bruto'} per maand",
                 "berekening", _begrens(ruimte / 100, -1.5, 1.5), kort=f"woonlasten {eur(lasten)}",
                 uitleg=(f"Netto, jaar 1. Je grens: {eur(fin['grens'])}." if netto_grens else
                         f"Bruto. Zonder eigen grens geldt de norm van 33% van je bruto inkomen ({eur(fin['grens'])})."))]
    tekort, bron = fin["tekort"], "berekening, kosten koper ≈"
    if tekort > kk_onz:
        uit.append(_item("financiering", "let_op", "Eigen geld", f"{eur(tekort)} tekort", bron))
    elif tekort > 0:
        uit.append(_item("financiering", "neutraal", "Eigen geld", "net genoeg (schatting)", bron,
                         vraag="Laat je kosten koper narekenen door een adviseur.",
                         uitleg=f"Tekort {eur(tekort)} valt binnen de onzekerheid van de kosten koper."))
    else:
        uit.append(_item("financiering", "neutraal", "Eigen geld", f"genoeg, {eur(-tekort)} over", bron))
    marge = fin["marge_lenen"]
    if marge >= 0:
        uit.append(_item("financiering", "neutraal", "Leenruimte", f"{eur(marge)} over", "leentoets 2026"))
    else:
        uit.append(_item("financiering", "sterk" if tekort > kk_onz else "neutraal", "Leenruimte",
                         f"{eur(-marge)} te weinig", "leentoets 2026", kort="leenruimte te klein"))
    if fin["scenario_tekst"]:
        uit.append(_item("financiering", "neutraal", "Leentoets", fin["scenario_tekst"], "leentoets 2026, jouw scenario's",
                         kort=fin["scenario_tekst"].lower()))
    return uit


def _items_buitenruimte(br: dict, dr: dict) -> list[dict]:
    soort, bron, r = br["soort"], br["bron"], br["richting"]
    if soort is None and br["zeker"]:
        return [_item("buitenruimte", "sterk", "Buitenruimte", "geen", bron, -1.5, kort="geen buitenruimte")]
    if soort is None:
        return [_item("buitenruimte", "onbekend", "Buitenruimte", "niet vermeld", "funda", kort="buitenruimte onbekend",
                      vraag="Vraag of er een balkon of andere buitenruimte is.")]
    if soort == "frans balkon":
        return [_item("buitenruimte", "let_op", "Buitenruimte", "alleen frans balkon", bron, -1.0, kort="alleen frans balkon")]
    maat = f"{br['m2']} m²" if br["m2"] else "maat onbekend"
    p = 1.0 if soort in ("dakterras", "tuin") else (0.5 if (br["m2"] or 0) >= dr["buitenruimte_balkon_min_m2"] else 0.0)
    uit = [_item("buitenruimte", "goed" if p > 0 else "neutraal", soort.capitalize(), maat, bron, p,
                 kort=f"{soort} {maat if br['m2'] else ''}".strip() + (f" {r.lower()}" if r else ""),
                 vraag="Is er een vergunning voor het dakterras en staat het in de splitsingsakte?" if soort == "dakterras" else None)]
    if r:
        zon = 0.5 if r in ("Zuid", "Zuidwest", "Zuidoost", "West") else (-0.5 if r.startswith("Noord") else 0.0)
        uit.append(_item("buitenruimte", "goed" if zon > 0 else ("let_op" if zon < 0 else "neutraal"), "Zon op buitenruimte",
                         r.lower(), "advertentietekst", zon, kort=f"zon {r.lower()}"))
    return uit


def _items_oppervlak(m2: int, wens, dr: dict) -> list[dict]:
    if not m2:
        return [_item("oppervlak", "onbekend", "Woonoppervlak", "onbekend", "funda", kort="oppervlak onbekend")]
    oord = "goed" if m2 >= wens + 10 else ("let_op" if m2 < wens - 10 else "neutraal")
    return [_item("oppervlak", oord, "Woonoppervlak", f"{m2} m² (wens {wens})", "funda",
                  _begrens((m2 - wens) / dr["oppervlak_stap_m2"], -1.0, 1.0), kort=f"{m2} m²")]


def _items_woonlaag(laag, lift, bron: str, mx) -> list[dict]:
    if laag and lift is False and laag > mx:
        return [_item("woonlaag_lift", "sterk" if laag >= mx + 2 else "let_op", "Trappen", f"{laag}e woonlaag, geen lift",
                      bron, max(-1.5, -0.5 * (laag - mx)), kort=f"{laag}e zonder lift")]
    if laag and lift is None and laag > mx:
        return [_item("woonlaag_lift", "onbekend", "Lift", "niet vermeld", "funda", kort="lift onbekend",
                      vraag=f"Is er een lift? De woning ligt op de {laag}e woonlaag.")]
    if laag and lift and laag >= 3:
        return [_item("woonlaag_lift", "goed", "Lift", f"{laag}e woonlaag", "kenmerk 'Voorzieningen'", kort=f"lift, {laag}e woonlaag")]
    return []


def _items_schuin_dak(kap: dict, dr: dict) -> list[dict]:
    """Klein minpunt als de woonruimte onder de kap ligt (besluit eigenaar, 18 nov 2026)."""
    if kap["status"] == "zeker":
        waarde = ("bovenste woonlaag onder de kap" if kap["maisonnette"] else
                  "bovenste etage onder de kap" if kap["bovenste"] else "woonruimte onder schuin dak")
        return [_item("schuin_dak", "let_op", "Schuin dak", waarde, kap["bron"], dr["schuin_dak_punten"], kort="onder schuin dak",
                      vraag="Vraag de bruikbare oppervlakte boven 1,50 m hoogte op.",
                      uitleg="Onder een schuin dak is minder vloer bruikbaar dan het aantal m² doet denken, en de ruimte voelt anders.")]
    if kap["status"] == "mogelijk":
        return [_item("schuin_dak", "neutraal", "Schuin dak", "mogelijk onder schuin dak", kap["bron"], kort="mogelijk schuin dak",
                      uitleg="Het pand heeft een schuin dak; of deze woning eronder ligt, is niet te zien. "
                             "Kijk op de foto's en de plattegrond.")]
    return []


def _items_reisafstand(routes, cfg: dict, werk_bekend: bool) -> list[dict]:
    routes = [r for r in (routes or []) if isinstance(r, dict) and isinstance(r.get("km"), (int, float))]
    if not routes:
        return [_item("reisafstand", "onbekend", "Reisafstand", "onbekend", "route", kort="reisafstand onbekend")] if werk_bekend else []
    gewicht = cfg["werk"].get("gewicht") or {}
    goed_km, slecht_km = cfg["werk"]["km_goed"], cfg["werk"]["km_slecht"]
    uit = []
    for rt in routes:
        g = float(gewicht.get(rt.get("label"), 0)) if gewicht else 1 / len(routes)
        km = float(rt["km"])
        f = _begrens(((goed_km + slecht_km) / 2 - km) / ((slecht_km - goed_km) / 2), -1.0, 1.0)
        oord = "goed" if km <= goed_km else ("let_op" if km >= slecht_km else "neutraal")
        uit.append(_item("reisafstand", oord, f"Werk {rt.get('label') or ''}".strip(), f"≈ {nl(km)} km",
                         "route" if rt.get("soort") == "weg" else "schatting (hemelsbreed x 1,3)", g * f, kort=f"werk {nl(km)} km"))
    return uit


def _items_energielabel(label: str, bron: str, reken_label: str, grond: str | None, dr: dict) -> list[dict]:
    """Kosten zitten in de woonlasten, leenruimte in de poort; hier alleen het verbouwrisico."""
    if label in dr["energielabel_slecht"]:
        extra = tabel()["label_verduurzamen"].get(label)
        return [_item("energielabel", "let_op", "Energielabel", label, bron, -1.0, kort=f"label {label}",
                      vraag="Vraag naar verduurzamingsplannen van de VvE.",
                      uitleg=(f"Voor energiebesparende maatregelen mag je tot {eur(extra)} extra lenen." if extra else None))]
    if label == "?":
        return [_item("energielabel", "onbekend", "Energielabel", f"onbekend, gerekend als {reken_label}", bron,
                      kort="label onbekend", vraag="Vraag het energielabel op.",
                      uitleg=(f"Energiekosten gerekend met label {reken_label}"
                              + (f", op grond van {grond}." if grond else ": zonder label gaan we uit van het slechtste.")
                              + " Een aanname, geen gegeven."))]
    if label in dr["energielabel_goed"]:
        return [_item("energielabel", "goed", "Energielabel", label, bron, kort=f"label {label}",
                      uitleg="Lagere stookkosten en meer leenruimte; dat zit al in woonlasten en leentoets.")]
    return []


# Erfpachtstatus met een vast item: (oordeel, label, waarde, punten, kort, vraag).
_ERFPACHT_ONDUIDELIJK = ("let_op", "Erfpacht", "voorwaarden onbekend", -0.5, "erfpacht onduidelijk",
                         "Vraag de erfpachtakte: canon, afkoop en einddatum.")
_ERFPACHT_ITEM = {
    "eigen": ("goed", "Grond", "eigen grond", 0.0, "eigen grond", None),
    "eeuwig_afgekocht": ("goed", "Erfpacht", "eeuwigdurend afgekocht", 0.0, "erfpacht afgekocht", None),
    "voortdurend": ("sterk", "Erfpacht", "voortdurend, canon herzien", -1.5, "voortdurende erfpacht",
                    "Vraag wanneer het tijdvak afloopt en wat de nieuwe canon wordt."),
    "afgekocht_looptijd_onbekend": _ERFPACHT_ONDUIDELIJK,
    "erfpacht_onduidelijk": _ERFPACHT_ONDUIDELIJK,
    "onbekend": ("onbekend", "Eigendom", "niet vermeld", 0.0, "eigendom onbekend", "Vraag of het eigen grond of erfpacht is."),
}


def _items_erfpacht(erf: dict, jaar_nu: int, dr: dict) -> list[dict]:
    st, bron, eind, canon = erf["status"], erf["bron"], erf["eind"], erf["canon_jaar"]
    if st == "afgekocht_tot":
        jaren = eind - jaar_nu
        p = 0.0 if jaren >= dr["erfpacht_afkoop_middel_jaren"] else (-1.0 if jaren >= dr["erfpacht_afkoop_kort_jaren"] else -2.0)
        return [_item("erfpacht", "sterk" if p <= -2.0 else ("let_op" if p < 0 else "neutraal"), "Erfpacht",
                      f"afgekocht tot {eind} ({jaren} jaar)" if jaren >= 0 else f"afkoop verlopen in {eind}", bron, p,
                      kort=f"afkoop tot {eind}", vraag=f"Vraag wat de canon na {eind} wordt.")]
    if st == "eeuwig_canon":
        return [_item("erfpacht", "let_op", "Erfpachtcanon", f"{eur(canon)} per jaar" if canon else "bedrag onbekend", bron, -0.5,
                      kort="erfpachtcanon", vraag="Vraag de erfpachtakte en de datum van de volgende herziening.",
                      uitleg="De canon zit in je woonlasten en in de leentoets." if canon else None)]
    oord, label, waarde, p, kort, vraag = _ERFPACHT_ITEM.get(st, _ERFPACHT_ITEM["onbekend"])
    return [_item("erfpacht", oord, label, waarde, bron, p, kort=kort, vraag=vraag)]


def _nog_ophalen(reden, status: str):
    return reden or ("Nog niet opgehaald. Komt bij een volgende update." if status == "budget" else None)


def _items_vve(ch: dict, tekst: str, vve, vve_bron: str, stook: bool, m2: int, n_vbo, bag_st: str, bag_reden,
               dr: dict) -> list[dict]:
    """VvE: de bijdrage, de kenmerken (KvK, vergadering, fonds, plan), de tekst en het aantal adressen uit de BAG."""
    uit: list[dict] = []
    add = uit.append
    if vve is None:
        add(_item("vve", "onbekend", "VvE-bijdrage", f"onbekend, gerekend met {eur(VVE_GESCHAT)}", "aanname",
                  kort="VvE-bijdrage onbekend", vraag="Vraag de maandelijkse VvE-bijdrage op."))
    else:
        per_m2 = vve / max(m2, 1)
        hoogte = (None if stook else "laag" if per_m2 < dr["vve_bijdrage_laag_per_m2"]
                  else "hoog" if per_m2 > dr["vve_bijdrage_hoog_per_m2"] else None)
        add(_item("vve", "let_op" if hoogte else "neutraal", "VvE-bijdrage",
                  f"{eur(vve)} per maand" + (", met stookkosten" if stook else f", {hoogte}" if hoogte else ""), vve_bron,
                  kort=f"VvE {eur(vve)}" + (f" {hoogte}" if hoogte else ""),
                  vraag="Lage bijdrage: vraag de stand van het reservefonds en het onderhoudsplan." if hoogte == "laag" else None,
                  uitleg="Zit al in je woonlasten." if hoogte == "hoog" else None))
    slapend = vve_status(ch, tekst) == "slapend"
    ja, nee = _vve_kenmerken(ch)
    if slapend:
        add(_item("vve", "sterk", "VvE", "niet actief", "kenmerken en tekst", -1.0, kort="VvE niet actief",
                  vraag="Vraag of de VvE een rekening, verzekering en vergadering heeft."))
    if "Reservefonds aanwezig" in nee:
        add(_item("vve", "let_op", "Reservefonds", "nee", "kenmerk 'Reservefonds aanwezig'", -0.5, kort="geen reservefonds"))
    if "Onderhoudsplan" in nee:
        add(_item("vve", "let_op", "Onderhoudsplan", "nee", "kenmerk 'Onderhoudsplan'", -0.5, kort="geen onderhoudsplan"))
    if len(ja) == len(_VVE_KENMERKEN) and not slapend:
        add(_item("vve", "goed", "VvE op orde", "KvK, vergadering, fonds en plan", "kenmerken", 0.5, kort="VvE op orde"))
    if n_vbo is not None and n_vbo <= dr["vve_klein_max_woningen"]:
        add(_item("vve", "let_op", "Kleine VvE", f"{n_vbo} adressen in het pand", "BAG", -0.5, kort=f"VvE van {n_vbo}",
                  vraag="Kleine VvE: vraag notulen, onderhoudsplan en stand reservefonds.",
                  uitleg="Grote kosten (dak, fundering) deel je met weinig eigenaren."))
    elif n_vbo is not None:
        add(_item("vve", "neutraal", "Pand", f"{n_vbo} adressen", "BAG", kort=f"pand met {n_vbo} adressen"))
    elif bag_st in ("onbekend", "budget"):
        add(_item("vve", "onbekend", "VvE-grootte", "onbekend", "BAG", kort="VvE-grootte onbekend",
                  uitleg=_nog_ophalen(bag_reden, bag_st)))
    return uit


def _items_fundering(verrijking, bj, bj_bag, klein: bool, herstel: bool, dr: dict) -> list[dict]:
    """Funderingsrisico van de buurt, alleen bij een bouwjaar voor de grens (1970)."""
    st, fu, reden = _bron(verrijking, "fundering")
    grens = dr["fundering_bouwjaar_voor"]
    uit: list[dict] = []
    if bj and bj >= grens and st in ("ok", "niet_nodig", "onbekend", "budget"):
        uit.append(_item("fundering", "neutraal", "Fundering", f"bouwjaar {bj}, na {grens}", "BAG" if bj_bag else "funda",
                         kort="fundering geen risico"))
    elif st in ("onbekend", "budget"):
        uit.append(_item("fundering", "onbekend", "Funderingsrisico buurt", "onbekend", "Klimaateffectatlas", kort="fundering onbekend",
                         uitleg=_nog_ophalen(reden, st), vraag="Vraag de VvE of er funderingsonderzoek is gedaan."))
    elif st == "ok" and fu:
        klassen = [(k, v) for k, v in fu.items() if v in FUND_KLASSE]
        if klassen:
            soort, klasse = max(klassen, key=lambda kv: FUND_KLASSE.index(kv[1]))
            rang = FUND_KLASSE.index(klasse)
            if rang >= FUND_KLASSE.index(dr["fundering_klasse_let_op"]) and not herstel:
                uit.append(_item("fundering", "sterk" if rang >= 3 else "let_op", "Funderingsrisico buurt", f"{soort} {klasse} (2050)",
                                 "Klimaateffectatlas, buurtniveau", {2: -0.5, 3: -1.0, 4: -1.5}[rang] + (-0.5 if klein else 0.0),
                                 kort=f"fundering {klasse}",
                                 vraag="Vraag de VvE naar funderingsonderzoek en of ze ervoor reserveert.",
                                 uitleg=f"Pand uit {bj}. Kaart op buurtniveau: geen oordeel over dit pand."))
            else:
                uit.append(_item("fundering", "goed", "Funderingsrisico buurt", klasse, "Klimaateffectatlas, buurtniveau",
                                 0.5 if herstel and rang >= 2 else 0.0, kort=f"fundering {klasse}"))
    if herstel:
        uit.append(_item("fundering", "goed", "Funderingsherstel", "uitgevoerd (advertentie)", "advertentietekst",
                         kort="fundering hersteld", vraag="Vraag het rapport en de garantie van het herstel."))
    return uit


def _items_geluid(verrijking, dr: dict) -> list[dict]:
    """Geluid aan de gevel: het zwaarste van weg en trein, dag en nacht."""
    st, ge, reden = _bron(verrijking, "geluid")
    if not (st == "ok" and ge):
        return [_item("geluid", "onbekend", "Geluid aan de gevel", "onbekend", "RIVM", kort="geluid onbekend",
                      uitleg=reden)] if st in ("onbekend", "budget") else []

    def db(veld):                                       # None = geen waarde of onder de kaartgrens
        v = ge.get(veld)
        return v if isinstance(v, (int, float)) and v > -9000 else None

    lden_w, lden_t = db("lden_weg"), db("lden_trein")
    if lden_w is None and lden_t is None:
        return [_item("geluid", "goed", "Geluid aan de gevel", "rustig, onder de kaartgrens", "RIVM 2022/2023", kort="rustige gevel")]
    stap = max(sum(db(veld) >= grens for grens in dr[f"geluid_{veld}"])
               for veld in ("lden_weg", "lnight_weg", "lden_trein", "lnight_trein") if db(veld) is not None)
    soort = "trein" if (lden_t or 0) > (lden_w or 0) else "weg"
    lden, nacht = (lden_t if soort == "trein" else lden_w), db(f"lnight_{soort}")
    waarde = f"{nl(lden, 0)} dB" + (f", nacht {nl(nacht, 0)} dB" if nacht is not None else "") + f" ({soort})"
    oord = ["neutraal", "let_op", "sterk", "sterk"][min(stap, 3)]
    if stap == 0 and lden < dr["geluid_rustig_lden"]:
        oord, waarde = "goed", f"rustig, {nl(lden, 0)} dB"
    return [_item("geluid", oord, "Geluid aan de gevel", waarde, "RIVM 2022/2023", -0.5 * min(stap, 3),
                  kort=f"geluid {nl(lden, 0)} dB", uitleg="Rekenwaarde op het adrespunt. De achtergevel kan stiller zijn.",
                  vraag="Vraag aan welke kant de slaapkamer ligt en hoe de ramen zijn." if stap else None)]


def _items_buurt(twijfel_z: list[str], verrijking, dr: dict) -> list[dict]:
    """Buurt: jouw lijst blijft leidend, data vult aan (nooit bevolkingskenmerken).

    Een zwakke Leefbaarometer komt als zin bij twijfel_z (in place), tenzij de buurt al op jouw lijst staat."""
    uit = [it for it in map(_twijfel_item, twijfel_z) if it]
    st, bu, reden = _bron(verrijking, "buurt")
    if st == "ok" and bu:
        k = bu.get("kscore")
        if isinstance(k, (int, float)) and int(k) in LBM_KLASSE:
            k = int(k)
            klasse, jaar = LBM_KLASSE[k], bu.get("jaar") or 2024
            if k <= dr["leefbaarometer_twijfel_max"]:
                if not any(z.lower().startswith("twijfelbuurt") for z in twijfel_z):
                    twijfel_z.append(f"Leefbaarometer {klasse} ({jaar}). Buurt staat niet op jouw lijst.")
                uit.append(_item("buurt", "sterk", "Leefbaarometer", f"{klasse} ({jaar})", "Leefbaarometer 3.0", kort="buurt zwak",
                                 uitleg="Staat niet op je uitsluitlijst. Zelf bekijken en eventueel toevoegen."))
            else:
                goed = k >= dr["leefbaarometer_goed_min"]
                uit.append(_item("buurt", "goed" if goed else "neutraal", "Leefbaarometer", f"{klasse} ({jaar})", "Leefbaarometer 3.0",
                                 0.5 if goed else 0.0, kort=f"buurt {klasse}"))
        onv = bu.get("onv")
        if isinstance(onv, (int, float)) and onv <= dr["leefbaarometer_onv_let_op"]:
            uit.append(_item("buurt", "let_op", "Overlast en onveiligheid", f"{nl(onv, 2)} tegenover Nederland", "Leefbaarometer 3.0",
                             -0.5, kort="overlast buurt"))
    elif st in ("onbekend", "budget"):
        uit.append(_item("buurt", "onbekend", "Buurtdata", "onbekend", "Leefbaarometer", kort="buurtdata onbekend", uitleg=reden))
    tv = (bu or {}).get("tevreden_woonomgeving") if st == "ok" else None
    tv_st, tv_data, _ = _bron(verrijking, "tevredenheid")
    if tv is None and tv_st == "ok" and tv_data:
        tv = tv_data.get("tevreden_woonomgeving", tv_data.get("tevreden"))
    if isinstance(tv, (int, float)):
        laag = tv < dr["tevreden_woonomgeving_let_op"]
        if laag or tv >= dr["tevreden_woonomgeving_goed"]:
            uit.append(_item("buurt", "let_op" if laag else "goed", "Tevreden met buurt", f"{nl(tv, 0)}% (2024)",
                             "RIVM-gezondheidsmonitor", -0.5 if laag else 0.0, kort=f"tevreden {nl(tv, 0)}%",
                             uitleg="Modelschatting met onzekerheidsmarge." if laag else None))
    return uit


def _items_zonder_prijs(ruw, hist: dict) -> list[dict]:
    """Eerder zonder vraagprijs aangeboden: eigen waarneming (d["_zonder_prijs_gezien"]), anders funda's prijshistorie."""
    eigen = _datum(ruw)
    wanneer = eigen or _datum(hist.get("zonder_prijs"))
    if not wanneer and ruw != ZONDER_PRIJS_ONBEKEND:
        return []
    return [_item("prijsverloop", "neutraal", "Eerder zonder prijs",
                  f"gezien op {_dag_kort(wanneer)}" if wanneer else "gezien, datum onbekend",
                  "eigen waarneming" if eigen or not wanneer else "funda prijshistorie", kort="eerder zonder prijs",
                  uitleg="Deze woning stond eerder zonder vraagprijs te koop (prijs op aanvraag). "
                         "Vraag de makelaar waarom er nu wel een prijs staat.")]


def _items_staat(w: dict, ch: dict, signalen: list[tuple], m2: int, bj_bag, bj_funda, dr: dict) -> list[dict]:
    """Staat en clausules uit de advertentie (funderingsherstel staat bij de fundering)."""
    uit = [_item(onderdeel, oord, lab, waarde, "advertentietekst", p, kort=kort, vraag=vraag)
           for sid, _, _, onderdeel, oord, lab, waarde, p, kort, vraag in signalen if sid != "funderingsherstel"]
    if w.get("is_fixer_upper") and not any(s[0] == "opknapper" for s in signalen):
        uit.append(_item("staat", "sterk", "Staat", "kluswoning", "funda", -1.5, kort="kluswoning",
                         vraag="Laat een verbouwbegroting maken voor je bod."))
    if w.get("is_monument"):
        uit.append(_item("staat", "neutraal", "Monument", "ja", "funda", kort="monument",
                         vraag="Vraag welke verbouwingen een vergunning nodig hebben."))
    if (ch.get("Aanvaarding") or w.get("acceptance") or "").lower().startswith("in overleg"):
        uit.append(_item("clausules", "neutraal", "Oplevering", "in overleg", "kenmerk 'Aanvaarding'", kort="oplevering in overleg"))
    inhoud = _getal(ch.get("Inhoud")) if ch.get("Inhoud") else None
    if inhoud and m2 and inhoud / m2 >= dr["inhoud_per_m2_hoog"]:
        uit.append(_item("staat", "neutraal", "Hoge ruimtes", f"{nl(inhoud / m2)} m³ per m²", "kenmerk 'Inhoud'", kort="hoge ruimtes",
                         uitleg="Sfeer, maar ook meer stookkosten."))
    if bj_bag and bj_funda and abs(bj_bag - bj_funda) >= dr["bouwjaar_verschil_bag_funda"]:
        uit.append(_item("staat", "neutraal", "Bouwjaar", f"funda {bj_funda}, BAG {bj_bag}", "BAG", kort="bouwjaar wijkt af"))
    return uit


def _items_markt(prijs, m2: int, gem, verklaard: bool, dr: dict) -> list[dict]:
    """Prijs per m² tegenover de buurt. verklaard: de lage prijs komt al door de staat of het label."""
    if not (prijs and isinstance(gem, (int, float)) and gem > 0 and m2):
        return []
    diff = (prijs / m2 - gem) / gem * 100
    onder = diff <= -dr["markt_afwijking_pct"] and not verklaard
    if not onder and diff < dr["markt_afwijking_pct"]:
        return []
    tekst = f"{nl(abs(diff), 0)}% onder" if onder else f"{nl(diff, 0)}% boven"
    return [_item("markt", "goed" if onder else "let_op", "Prijs per m²", f"{tekst} de buurt", "funda-buurtcijfer",
                  0.5 if onder else -0.5, kort=f"m²-prijs {tekst} buurt",
                  uitleg="Vergeleken met alle te koop staande woningen in de buurt.")]


def _items_info(w: dict, woz: dict | None, makelaar: dict) -> list[dict]:
    """Informatief, 0 punten: WOZ, makelaar, open huis."""
    uit = []
    if woz and woz["bedrag"]:
        jr = woz["jaar"]
        uit.append(_item("info", "neutraal", "WOZ-waarde", f"{eur(woz['bedrag'])}" + (f" (WOZ {jr})" if jr else ""),
                         "funda prijshistorie", kort="WOZ-waarde",
                         uitleg=f"Waardepeildatum 1 januari {jr - 1}: de WOZ loopt achter op de markt." if jr else None))
    cijfer = makelaar.get("review_average")
    if isinstance(cijfer, (int, float)):
        n = makelaar.get("review_count")
        uit.append(_item("info", "neutraal", "Makelaar", f"{nl(cijfer)} uit {n} reviews" if n else nl(cijfer),
                         "funda" + (f", {makelaar['name']}" if makelaar.get("name") else ""), kort="makelaar"))
    if w.get("open_house"):
        uit.append(_item("info", "neutraal", "Open huis", "gepland", "funda", kort="open huis"))
    return uit


def _items_kansen(tr: dict, prijs, hoogste, cfg: dict) -> list[dict]:
    """Kansen bij bieden: tellen niet mee, elke oorzaak één keer."""
    uit = []
    if tr.get("gedaald") and tr.get("drop_bedrag"):
        uit.append(_item("kans", "kans", "Prijs verlaagd", f"{eur(tr['drop_bedrag'])} lager", "eigen tracking", kort="prijs verlaagd",
                         uitleg=f"Was {eur(tr['eerdere_prijs'])}." if tr.get("eerdere_prijs") else None))
    elif prijs and hoogste and hoogste > prijs:
        uit.append(_item("kans", "kans", "Prijs verlaagd", f"{eur(hoogste - prijs)} lager", "funda prijshistorie",
                         kort="prijs verlaagd", uitleg=f"Hoogste vraagprijs sinds de laatste verkoop: {eur(hoogste)}."))
    dagen = tr.get("dagen") or 0
    if isinstance(dagen, (int, float)) and dagen >= cfg["lang_op_funda_dagen"]:
        uit.append(_item("kans", "kans", "Lang te koop", f"{int(dagen)} dagen", "eigen tracking", kort="lang te koop"))
    return uit


def beoordeel(d: dict, details: dict | None, routes: list | None, twijfel: list | None, profiel: dict | None,
              config: dict | None, verrijking: dict | None = None, *, rente: dict | None = None,
              vandaag=None) -> dict:
    """Beoordeling van één woning volgens het datacontract ("Uitvoer" in de moduledocstring)."""
    vandaag = _datum(vandaag, date.today())
    profiel = profiel or {}
    cfg = config if isinstance(config, dict) and "gewichten" in config else laad_config(profiel)
    rente = rente or rente_uit_config(cfg, vandaag)
    d = d or {}
    w = _woning(d, details)
    ch = _blok(w, "characteristics")
    tekst = str(w.get("description") or "")
    dr = cfg["drempels"]
    m2 = _oppervlak(w)
    twijfel_z = _twijfel_zinnen(d.get("_twijfel") if twijfel is None else twijfel)
    enr = _blok(d, "_enrichment")

    # Wat de financiering nodig heeft: label, erfpacht, VvE-bijdrage, energiekosten en de WOZ.
    label, label_bron = energielabel(w, ch, tekst)
    erf = erfpacht(ch, tekst)
    vve, vve_bron = vve_maand(ch, tekst)
    stook = stookkosten_in_vve(ch, tekst)
    # Bouwjaar: BAG gaat voor, anders funda. Zonder label bepaalt het ook het rekenlabel van de energiekosten.
    bag_st, bag, bag_reden = _bron(verrijking, "bag")
    bag = bag if bag_st == "ok" else None
    bj_funda = _getal(w.get("construction_year")) or _getal(ch.get("Bouwjaar"))
    bj_bag = _getal((bag or {}).get("bouwjaar"))
    bj = bj_bag or bj_funda
    n_vbo = _getal((bag or {}).get("aantal_vbo_pand"))
    reken_label, label_grond = label_aanname(label, bj)
    energie = ENERGIE_PER_LABEL[reken_label] * max(m2, 40) / 75 * (STOOK_IN_VVE_FACTOR if stook else 1)
    hist = prijshistorie(prijswijzigingen(d))
    prijs = w.get("price") if isinstance(w.get("price"), (int, float)) and w.get("price") > 0 else None
    fin = financiering({"prijs": prijs, "label": None if label == "?" else label, "canon_jaar": erf["canon_jaar"],
                        "vve": vve, "vve_bron": vve_bron, "energie": energie, "stook_in_vve": stook,
                        "woz": (hist["woz"] or {}).get("bedrag")}, cfg, profiel, rente, vandaag)
    gate = poort(w, cfg, fin)
    signalen = lees_advertentie(tekst)
    sig_ids = {s[0] for s in signalen}
    laag, lift, laag_bron = woonlaag(ch, tekst)
    # De lage m²-prijs van een kluswoning of een slecht label is geen koopje.
    verklaard = bool(w.get("is_fixer_upper")) or "opknapper" in sig_ids or label in dr["energielabel_slecht"]

    items = [
        *_items_geld(fin, dr, cfg["financiering"]["kk_onzekerheid"]),
        *_items_buitenruimte(buitenruimte(w, ch, tekst), dr),
        *_items_oppervlak(m2, cfg["m2_wens"], dr),
        *_items_woonlaag(laag, lift, laag_bron, cfg["max_woonlaag_zonder_lift"]),
        *_items_schuin_dak(schuin_dak(ch, tekst, laag), dr),
        *_items_reisafstand(routes, cfg, bool(profiel.get("werk_postcodes"))),
        *_items_energielabel(label, label_bron, reken_label, label_grond, dr),
        *_items_erfpacht(erf, vandaag.year, dr),
        *_items_vve(ch, tekst, vve, vve_bron, stook, m2, n_vbo, bag_st, bag_reden, dr),
        *_items_fundering(verrijking, bj, bj_bag, n_vbo is not None and n_vbo <= dr["vve_klein_max_woningen"],
                          "funderingsherstel" in sig_ids, dr),
        *_items_geluid(verrijking, dr),
        *_items_buurt(twijfel_z, verrijking, dr),
        *omgeving_items(verrijking, dr, monument_funda=bool(w.get("is_monument"))),
        # Alleen als er nu wel een prijs is; nooit rekenen met prijs 0.
        *(_items_zonder_prijs(d.get("_zonder_prijs_gezien"), hist) if prijs else []),
        *_items_staat(w, ch, signalen, m2, bj_bag, bj_funda, dr),
        *_items_markt(prijs, m2, _blok(enr, "market").get("avg_asking_price_per_m2"), verklaard, dr),
        # Parkeren heeft standaard gewicht 0: zichtbaar, telt niet mee.
        *([_item("parkeren", "goed", "Parkeerplek", "eigen plek", "funda", 0.5, kort="eigen parkeerplek")]
          if w.get("has_parking_on_site") or w.get("has_parking_enclosed") else []),
        *_items_info(w, hist["woz"], _blok(enr, "broker")),
        *_items_kansen(_blok(d, "_track"), prijs, hist["hoogste"], cfg),
        *binnenklimaat(w, ch, tekst, bag, verrijking, label, reken_label, bj),
    ]
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
        if i["onderdeel"] == BINNENKLIMAAT:   # die vraag staat bij het item zelf; hier zou hij de vaste vragen verdringen
            continue
        if i.get("vraag") and i["vraag"] not in vragen:
            vragen.append(i["vraag"])
    for v in VRAGEN_ALTIJD:
        if v not in vragen:
            vragen.append(v)
    fin_uit = {k: v for k, v in fin.items() if k not in ("poort", "redenen")}
    namen = ["bag", "fundering", "geluid", "buurt"]
    if isinstance(verrijking, dict):
        namen += [k for k in verrijking if k not in namen
                  and k in ("tevredenheid", "kerncijfers", "veiligheid", "lucht", "klimaat", "erfgoed")]
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


def log_prijshistorie(woningen) -> dict:
    """Meting voor "eerder zonder prijs aangeboden": welke statuswaarden funda's prijshistorie geeft en
    hoeveel regels geen bedrag hebben. Alleen aantallen: {"woningen", "regels", "status": {naam: n},
    "zonder_bedrag": {naam: n}}. Een statuswaarde die niet op een kort woord lijkt, telt als "anders"."""
    uit = {"woningen": 0, "regels": 0, "status": {}, "zonder_bedrag": {}}
    for d in woningen or []:
        changes = prijswijzigingen(d if isinstance(d, dict) else None)
        if not changes:
            continue
        uit["woningen"] += 1
        for c in changes:
            if not isinstance(c, dict):
                continue
            st = str(c.get("status") or "").strip().lower()
            st = st if re.fullmatch(r"[a-z_]{1,30}", st) else ("leeg" if not st else "anders")
            uit["regels"] += 1
            uit["status"][st] = uit["status"].get(st, 0) + 1
            if not _prijs_van(c):
                uit["zonder_bedrag"][st] = uit["zonder_bedrag"].get(st, 0) + 1
    uit["status"] = dict(sorted(uit["status"].items()))
    uit["zonder_bedrag"] = dict(sorted(uit["zonder_bedrag"].items()))
    return uit
