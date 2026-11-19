"""Verrijking per woning uit open bronnen (CLAUDE.md, "Verrijking").

Negen bronnen, elk fail-soft: een kapotte bron geeft "onbekend" en de run gaat door.

- bag:       PDOK BAG OGC API v2. Bouwjaar en aantal verblijfsobjecten van het pand
             (benadering van de VvE-grootte), gebruiksdoel van het verblijfsobject.
- fundering: Klimaateffectatlas, risicokaarten fundering 2050 hoog (Deltares 2021),
             verschilzetting en paalrot op buurtniveau. Alleen bij een pand van voor 1970.
             Samen met klimaat in één verzoek (zie "Fundering en klimaat" hieronder).
- geluid:    RIVM-geluidkaarten aan de gevel: Lden en Lnight, wegverkeer 2022 en trein 2023.
- buurt:     buurtcode via PDOK CBS-buurten 2024, Leefbaarometer 3.0 (2024) en de
             RIVM-gezondheidsmonitor 2024 (tevredenheid, via CBS dataderden 50150NED).

- kerncijfers: CBS Wijken en buurten 2024 uit dezelfde PDOK-call als de buurtcode: gemiddelde WOZ,
             koop, huur en corporatie, meergezins, stadsverwarming en aardgasvrij, afstand tot
             supermarkt, station en huisarts. Het aantal woningen alleen als noemer.
- veiligheid: geregistreerde misdrijven (47018NED) en overlast (47024NED) van de politie via CBS
             dataderden, 2025, per 1.000 woningen, voor de buurt en de gemeente.
- lucht:     RIVM, jaargemiddelde NO2 en PM2,5 (2024) en het percentage groen binnen 500 m (2022).
- klimaat:   Klimaateffectatlas: wateroverlast rond het pand, overstromingskans, grondwateroverlast.
- erfgoed:   RCE via PDOK: beschermd stads- of dorpsgezicht op het punt, rijksmonumenten binnen 25 m.

De laatste vijf zijn van 18 nov 2026 en tellen in het model nog niet mee in de score (0 punten).

Laag- en veldnamen zijn gemeten op 7 en 18 nov 2026 (ingekorte antwoorden in
testdata/verrijking/). Gemeten op openbare plekken (het Plein en het stadhuis in Den
Haag), nooit op een woonadres.

Regels (CLAUDE.md):
- Al het netwerk loopt via één injecteerbare functie `http(url, timeout=, headers=)`
  die `(status, body_bytes)` teruggeeft; de tests geven een nep-functie mee.
- Eerlijke user-agent (`EERLIJKE_UA` hieronder, de enige bron; of als parameter), time-outs,
  sequentieel met een pauze, robots.txt per host eerst. Vers op de dag van ophalen (RFC 9309
  par. 2.4: hooguit 24 uur); de laatste goede versie (hooguit 30 dagen) alleen als terugval
  wanneer robots.txt onbereikbaar is (time-out of 5xx).
- Per host stoppen bij 401/403/429/5xx. Een weigering wordt nooit omzeild: geen andere
  user-agent, host of client. Na een weigering blijft de host een dag dicht.
- Budget per run (standaard 90 verzoeken). Past en Krap eerst, daarna op score. Het budget gaat per
  woning: vooraf telt `kosten()` wat de woning nog vraagt (wat niet in de cache staat, met de kosten
  uit SECTIES, plus robots.txt per host die deze run nog niet gelezen is). Past dat niet, dan krijgt
  de hele woning "budget" voor wat ontbreekt en gaat het budget naar de volgende woning die wel
  past. Zo blijft er geen woning half gevuld. De telling is een bovengrens (een onbekende buurt telt
  als nieuwe buurt in een nieuwe gemeente). Kost een woning meer dan het hele budget (alleen bij een
  lage max_calls_per_run), dan gaat de eerste zo'n woning voorop en begint hij met het onaangeroerde
  budget: wat lukt staat daarna in de cache, dus hij wacht niet eeuwig, ook niet achter een woning die
  elke run een paar verzoeken vraagt. Twee zeldzame extra verzoeken staan niet in de telling: de ruimere tweede BAG-poging en
  de terugval van fundering en klimaat.
- Cache in het bestaande funda_enrichment_cache.json, als eigen secties (de tabel SECTIES).
  Een antwoord blijft `bewaar_dagen` geldig, een fout wordt na `fout_opnieuw_na_dagen`
  (1) opnieuw geprobeerd.
- Allowlist van velden: alleen de velden in VELDEN komen in de cache. Herkomst,
  nationaliteit, inkomen en andere bevolkingskenmerken worden nooit gelezen of bewaard.
- Logregels tonen alleen aantallen per bron en status, nooit adressen, postcodes of
  coördinaten.

Fundering en klimaat (19 nov 2026): beide komen van dezelfde WMS op hetzelfde punt en gaan daarom
in één GetFeatureInfo, zoals geluid en lucht al meerdere lagen per verzoek vragen. Alleen de lagen
die nog nodig zijn: staat er één in de cache, is er één uit of is fundering niet nodig, dan gaat
alleen de andere. De cachesecties `fundering` en `klimaat` en hun elementen zijn niet veranderd.
Gemeten tegen de echte dienst op 19 nov 2026 (testdata/verrijking/meting.json): op vijf openbare
punten in Den Haag gaf het gecombineerde antwoord voor beide bronnen hetzelfde als de twee losse
(5 van 5), met de features achter elkaar in de volgorde van de lagen in het verzoek. De fixture
kea_gecombineerd_getfeatureinfo.json is een ingekort echt antwoord. feature_count groeit mee met het
aantal lagen (10 per laag), zodat een laag met meerdere vlakken de latere lagen niet verdringt.
De terugval blijft als vangnet voor andere punten: geeft het gecombineerde antwoord voor een bron
niets bruikbaars terwijl de dienst wel antwoordde, dan wordt die bron één keer los opgehaald. Gaf dat
losse verzoek wel iets, dan klopte de combinatie niet; na twee keer (KEA_LOS_NA) vraagt de rest van de
run los. Weigert de dienst de combinatie als geheel (status 4xx, geen JSON), dan gaan beide los en
vraagt de rest van de run meteen niet meer gecombineerd. De log telt de terugvallen.

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

import funda_beoordeling
from funda_beoordeling import FUND_KLASSE, LBM_KLASSE

# ---------------------------------------------------------------- netiquette

# Hoe dit project zich meldt bij elke host die het met een eigen client aanspreekt: de open bronnen
# hier, PDOK en OSRM (funda_rapport), de rentebronnen (funda_rente) en funda's API-hosts (de
# Funda-subklasse in funda_zoek, die hem als EERLIJKE_UA exporteert). Als zichzelf, met een link naar
# de publieke repo; geen browser, geen app. Eén bron: hier. Niet voor www.funda.nl: daar gebruiken de
# sitemap- en HTML-zoeker bewust één vast Safari-profiel (funda_sitemap_zoek.UA en IMPERSONATE).
EERLIJKE_UA = "funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)"
# De naam waarmee robots.txt ons per groep kan aanspreken: het deel van de user-agent voor de "/".
ROBOTS_AGENT = EERLIJKE_UA.split("/", 1)[0]

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
# De namen van die klassen, van laag naar hoog: FUND_KLASSE uit funda_beoordeling (één bron).
KEA_KLASSEN = {
    "verschilzetting": ((1.0, "zeer laag"), (5.0, "laag"), (10.0, "matig"), (25.0, "hoog"), (math.inf, "zeer hoog")),
    "paalrot": ((0.8, "zeer laag"), (3.0, "laag"), (6.0, "matig"), (15.0, "hoog"), (math.inf, "zeer hoog")),
}

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
# De namen van kscore 1 tot 9: LBM_KLASSE uit funda_beoordeling (één bron).

CBS_50150 = "https://dataderden.cbs.nl/ODataApi/odata/50150NED/TypedDataSet"
CBS_PERIODE = "2024JJ00"
CBS_LEEFTIJD_18PLUS = "20300"          # "18 jaar of ouder" (dimensie Leeftijd, gemeten)
CBS_MARGES = {"MW00000": "waarde", "MOG0095": "min", "MBG0095": "max"}

# ---------------------------------------------------------------- bronnen (gemeten 18 nov 2026)

# CBS-kerncijfers per buurt: dezelfde PDOK-call als de buurtcode (244 velden; alleen KERN_PDOK wordt
# gelezen). De uitgave 2025 mist WOZ en afstanden, daarom 2024. Missend = -99997 (en verwante codes).
KERN_JAAR = 2024
KERN_PDOK = {
    "woz": "gemiddelde_woningwaarde",                      # x 1.000 euro
    "koop_pct": "percentage_koopwoningen",
    "huur_pct": "percentage_huurwoningen",
    "corporatie_pct": "perc_huurwoningen_in_bezit_woningcorporaties",
    "meergezins_pct": "percentage_meergezinswoning",
    "stadsverwarming_pct": "percentage_woningen_met_stadsverwarming",
    "aardgasvrij_pct": "percentage_aardgasvrije_woningen",
    "supermarkt_km": "grote_supermarkt_gemiddelde_afstand_in_km",
    "treinstation_km": "treinstation_gemiddelde_afstand_in_km",
    "huisarts_km": "huisartsenpraktijk_gemiddelde_afstand_in_km",
    "woningen": "woningvoorraad",                          # alleen als noemer; nooit in de uitvoer of de log
}
PDOK_GEMEENTEN = "https://api.pdok.nl/cbs/wijken-en-buurten-2024/ogc/v1/collections/gemeenten/items"
# Onder dit aantal woningen geen cijfer per 1.000 woningen: de noemer is dan te klein om iets te zeggen.
MIN_WONINGEN_NOEMER = 100

# Politiecijfers per buurt via CBS dataderden (OData). 47018NED: geregistreerde misdrijven per jaar,
# 47024NED: geregistreerde overlast. Eén verzoek per tabel geeft de buurt en de gemeente samen
# (gemeentesleutel met spaties aangevuld, daarom startswith). Sleutels van de dimensie zijn zes tekens
# breed ("1.1.1 "). 2025 is het laatste volledige jaar (tabel 2012-2025, gewijzigd 16 nov 2026).
CBS_MISDRIJVEN = "https://dataderden.cbs.nl/ODataApi/odata/47018NED/TypedDataSet"
CBS_OVERLAST = "https://dataderden.cbs.nl/ODataApi/odata/47024NED/TypedDataSet"
POLITIE_JAAR = 2025
POLITIE_PERIODE = f"{POLITIE_JAAR}JJ00"
MISDRIJF_CODES = {"0.0.0": "misdrijven", "1.1.1": "woninginbraak", "2.2.1": "vernieling"}
OVERLAST_CODES = {"0.0.0": "overlast"}
# Per cachesectie: tabel, dimensie, onderwerp en de codes die gelezen worden.
POLITIE_TABELLEN = {
    "misdrijven": (CBS_MISDRIJVEN, "SoortMisdrijf", "GeregistreerdeMisdrijven_1", MISDRIJF_CODES),
    "overlast": (CBS_OVERLAST, "Overlast", "GeregistreerdeOverlast_1", OVERLAST_CODES),
}

# RIVM: jaargemiddelde NO2 en PM2,5 (microgram per m3, NSL-kaart 2024) en het percentage groen binnen
# 500 m (groenkaart 2022). Eén verzoek; volgorde telt, net als bij RIVM_LAGEN. De namen dragen een
# datum: verdwijnt een jaargang, dan wordt de bron "onbekend" tot deze lijst is bijgewerkt.
RIVM_LUCHT_LAGEN = (
    ("no2", "rivm_nsl_20260401_gm_NO22024"),
    ("pm25", "rivm_nsl_20260401_gm_PM252024"),
    ("groen_pct", "groenkaart_cjp_2022_500m"),
)

# Klimaateffectatlas, drie lagen in één verzoek. Betekenis uit de legenda (GetLegendGraphic):
# - wateroverlast: per pand de klasse van de waterdiepte rond het pand bij een extreme bui;
# - overstromingskans: raster, klasse 1 tot 5 (kans per jaar op meer dan 20 cm water, huidig);
# - grondwater: klasse van de toename van de kans op grondwateroverlast in 2050 (scenario hoog).
# Niet opgenomen: hitteeiland en gevoelstemperatuur_2022 (waarde gemeten, eenheid niet te onderbouwen).
KEA_KLIMAAT_LAGEN = {
    "wateroverlast": "nl_fcab_omgevingsscore_wateroverlast_v20260806",
    "overstromingskans": "plaatsgebonden_overstromingskans_huidig_20_cm_20251120",
    "grondwater": "kans_grondwateroverlast_2050hoog",
}
KEA_WATERDIEPTE = {"0 tot 2 cm": "geen", "2 tot 10 cm": "zeer laag", "10 tot 15 cm": "laag",
                   "15 tot 20 cm": "middel", "20 tot 30 cm": "hoog", "meer dan 30 cm": "zeer hoog"}

# Erfgoed via PDOK (RCE, INSPIRE): beschermde stads- en dorpsgezichten als vlak, rijksmonumenten als
# punt. De eigen WFS van de RCE gaf op het meetpunt geen treffers en wordt niet gebruikt.
RCE_BASIS = "https://api.pdok.nl/rce/beschermde-gebieden-cultuurhistorie/ogc/v1/collections"
RCE_GEZICHT = "nlps-stadsendorpsgezichten"
RCE_MONUMENT = "nlps-rijksmonumenten"
MONUMENT_STRAAL_M = 25

BRONNEN = ("bag", "fundering", "geluid", "buurt", "kerncijfers", "veiligheid", "lucht", "klimaat", "erfgoed")

# ---------------------------------------------------------------- cachesecties en allowlist

# Eén tabel voor de eigen secties in funda_enrichment_cache.json. Per sectie: de bewaartermijn in dagen
# (de standaard; beoordeling.verrijking.bewaar_dagen gaat voor), het aantal verzoeken voor een nieuw
# element en de allowlist: alleen deze velden komen in de cache, cache_schrijf() weigert alles daarbuiten.
# fundering en klimaat delen één verzoek als ze samen nodig zijn (KEA_BRONNEN): samen 1, niet 2.
# Erachter: waarop de sleutel staat en welke schakelaar in beoordeling.verrijking.bronnen de sectie vult.
_POLITIE_VELDEN = {s: ("jaar",) + tuple(c.values()) + tuple("gem_" + k for k in c.values())
                   for s, (_, _, _, c) in POLITIE_TABELLEN.items()}
SECTIES = {
    "bag": (180, 2, ("bouwjaar", "aantal_vbo_pand", "gebruiksdoel", "gebruiksdoel_pand")),   # adres; bag
    "fundering": (365, 1, ("verschilzetting", "paalrot")),                 # punt; fundering (deelt met klimaat)
    "geluid": (365, 1, ("lden_weg", "lnight_weg", "lden_trein", "lnight_trein")),            # punt; geluid
    "buurtcode": (365, 1, ("buurtcode", "buurtnaam", "gemeentenaam")),   # punt; buurt, kerncijfers of veiligheid
    # buurtcode, met één verzoek per gemeente ("gemeente|<naam>" bewaart alleen een aantal); buurt
    "leefbaarometer": (30, 1, ("kscore", "lbm", "afw", "fys", "onv", "soc", "vrz", "won")),
    "tevredenheid": (90, 1, ("tevreden_woonomgeving", "tevreden_woonomgeving_min", "tevreden_woonomgeving_max",
                             "tevreden_woning")),                                            # buurtcode; tevredenheid
    "robots": (1, 1, ("regels",)),                                                           # host
    "verrijking_weigering": (None, 0, None),              # host -> {datum, status}; telt fout_opnieuw_na_dagen
    # buurtcode; kerncijfers of veiligheid. Komt mee met het verzoek voor de buurtcode; alleen bij een
    # buurtcode van voor 18 nov 2026 een eigen verzoek.
    "kerncijfers": (365, 1, tuple(KERN_PDOK) + ("gemeentecode",)),
    "gemeente": (365, 1, ("woningen",)),                                                     # gemeentecode; veiligheid
    "misdrijven": (180, 1, _POLITIE_VELDEN["misdrijven"]),                                   # buurtcode; veiligheid
    "overlast": (180, 1, _POLITIE_VELDEN["overlast"]),                                       # buurtcode; veiligheid
    "lucht": (365, 1, tuple(k for k, _ in RIVM_LUCHT_LAGEN)),                                # punt; lucht (en groen)
    "klimaat": (365, 1, ("wateroverlast", "waterdiepte", "overstromingskans", "grondwater")),   # punt; klimaat (deelt)
    "erfgoed": (180, 2, ("gezicht", "gezicht_sinds", "monumenten_dichtbij")),                # punt; erfgoed
}
CACHE_SECTIES = tuple(SECTIES)
VELDEN = {s: velden for s, (_, _, velden) in SECTIES.items() if velden is not None}
# De gemeentemarkering in de sectie leefbaarometer ("gemeente|<naam>") bewaart alleen een aantal.
LBM_GEMEENTE_VELDEN = ("buurten",)
# Per 1.000 woningen, buurt en gemeente: wat de bron veiligheid uitvoert (de aantallen zelf blijven in de cache).
VEILIGHEID_SOORTEN = tuple(MISDRIJF_CODES.values()) + tuple(OVERLAST_CODES.values())
# Velden die per bron in de uitvoer mogen staan (cache-velden plus wat hier wordt afgeleid).
UITVOER_VELDEN = {
    "bag": VELDEN["bag"],
    "fundering": VELDEN["fundering"] + ("bouwjaar",),
    "geluid": VELDEN["geluid"],
    "buurt": VELDEN["buurtcode"] + VELDEN["leefbaarometer"] + VELDEN["tevredenheid"],
    # Zonder het aantal woningen (alleen noemer) en de gemeentecode.
    "kerncijfers": tuple(k for k in KERN_PDOK if k != "woningen") + ("jaar",),
    "veiligheid": ("jaar",) + tuple(f"{k}_per_1000" for k in VEILIGHEID_SOORTEN)
                  + tuple(f"gem_{k}_per_1000" for k in VEILIGHEID_SOORTEN),
    "lucht": VELDEN["lucht"],
    "klimaat": VELDEN["klimaat"],
    "erfgoed": VELDEN["erfgoed"],
}

# ---------------------------------------------------------------- instellingen

# De enige standaard voor beoordeling.verrijking: funda_beoordeling.STANDAARD heeft geen eigen blok,
# en instellingen() legt het blok uit de config (beoordeling.verrijking) hier overheen.
STANDAARD = {
    "aan": True,
    "bronnen": {"bag": True, "fundering": True, "geluid": True, "buurt": True, "tevredenheid": True,
                "kerncijfers": True, "veiligheid": True, "lucht": True, "groen": True, "klimaat": True,
                "erfgoed": True},
    # Een nieuwe woning kost 8 verzoeken (BAG 2, geluid 1, buurt 1, lucht en groen 1, fundering en
    # klimaat samen 1, erfgoed 2), een nieuwe buurt 3 erbij (tevredenheid, misdrijven, overlast) en een
    # nieuwe gemeente 2 (Leefbaarometer, aantal woningen): hooguit 13, plus één robots.txt per host per
    # dag (vijf hosts). Tot 19 nov 2026 was dat 9 per woning bij een pand van voor de funderingsdrempel
    # (fundering en klimaat elk een eigen verzoek) en 8 bij een nieuwer pand. Met 90 passen er, na de
    # vijf robots.txt, tien nieuwe woningen in een bekende buurt in een run (85 / 8) en zes in elk een
    # nieuwe buurt en gemeente (85 / 13). Het budget gaat per woning (kosten()): wat niet in zijn
    # geheel past, krijgt "budget" en gaat de volgende run verder (Past en Krap eerst).
    "max_calls_per_run": 90,
    "timeout_s": 10,
    "pauze_s": 0.25,
    "fout_opnieuw_na_dagen": 1,
    "fouten_op_rij_stop": 3,
    # Jaarcijfers per buurt blijven lang: de bron verandert hooguit één keer per jaar.
    "bewaar_dagen": {s: dagen for s, (dagen, _, _) in SECTIES.items() if dagen is not None},
}
# RFC 9309 par. 2.4: een gecachete robots.txt niet langer dan 24 uur gebruiken, tenzij hij onbereikbaar
# is. Vers = opgehaald op dezelfde dag (twee runs per dag: hooguit één verzoek per host per dag).
# Onbereikbaar (time-out, 5xx): de laatste goede versie, hooguit ROBOTS_TERUGVAL_DAGEN oud.
ROBOTS_DAGEN = 1
ROBOTS_TERUGVAL_DAGEN = 30
# De drempels die de verrijking zelf gebruikt (signalen en twijfel). De waarden komen uit
# funda_beoordeling.STANDAARD["drempels"] (één bron; dat blok is ruimer); de config kan ze overschrijven.
DREMPEL_SLEUTELS = (
    "vve_klein_max_woningen", "fundering_bouwjaar_voor", "fundering_klasse_let_op",
    "geluid_lden_weg", "geluid_lnight_weg", "geluid_lden_trein", "geluid_lnight_trein", "geluid_rustig_lden",
    "leefbaarometer_twijfel_max", "leefbaarometer_goed_min", "leefbaarometer_onv_let_op",
    "tevreden_woonomgeving_let_op", "tevreden_woonomgeving_goed",
)
DREMPELS = {k: copy.deepcopy(funda_beoordeling.STANDAARD["drempels"][k]) for k in DREMPEL_SLEUTELS}
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

def _leeftijd(e, vandaag, veld: str = "fetched") -> int | None:
    """Dagen sinds de datum in e[veld]; None zonder element, zonder datum of met een onleesbare datum."""
    try:
        return _dagen(e[veld], vandaag) if isinstance(e, dict) and e.get(veld) else None
    except ValueError:
        return None


def cache_lees(cache: dict, sectie: str, sleutel: str, vcfg: dict, vandaag) -> tuple[object, str | None]:
    """-> (data, status). Status "vers" (gebruiken), "fout_vers" (niet opnieuw proberen)
    of None (ophalen)."""
    s = cache.get(sectie)
    e = s.get(sleutel) if isinstance(s, dict) else None
    dagen = _leeftijd(e, vandaag)
    if dagen is None:
        return None, None
    if e.get("fout"):
        return (None, "fout_vers") if dagen < vcfg["fout_opnieuw_na_dagen"] else (None, None)
    # Een element in een onverwachte vorm (met de hand bewerkt, afgekapt) telt als afwezig: opnieuw ophalen.
    if dagen <= vcfg["bewaar_dagen"].get(sectie, 30) and isinstance(e.get("data"), dict):
        return e["data"], "vers"
    return None, None


def cache_schrijf(cache: dict, sectie: str, sleutel: str, vandaag, data=None, fout: str | None = None) -> None:
    if isinstance(data, dict):
        gemeente = sectie == "leefbaarometer" and sleutel.startswith("gemeente|")
        toegestaan = LBM_GEMEENTE_VELDEN if gemeente else VELDEN.get(sectie)
        extra = sorted(set(data) - set(toegestaan)) if toegestaan is not None else []
        if extra:
            raise ValueError(f"veld buiten de allowlist voor {sectie}: {', '.join(extra)}")
    e = {"fetched": _datum(vandaag).isoformat(), "data": data}
    if fout:
        e["fout"] = fout
    if not isinstance(cache.get(sectie), dict):
        cache[sectie] = {}
    cache[sectie][sleutel] = e


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
            dagen = _leeftijd(e, vandaag, "fetched" if isinstance(e, dict) and e.get("fetched") else "datum")
            if dagen is None or dagen > grens:
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

def robots_regels(tekst: str, agent: str = ROBOTS_AGENT) -> list[list[str]]:
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
        if patroon and _robots_patroon(patroon).match(pad):
            lengte = len(patroon)
            if lengte > beste_len or (lengte == beste_len and soort == "allow"):
                beste_len, beste = lengte, soort == "allow"
    return beste


# ---------------------------------------------------------------- netwerk

class BronFout(Exception):
    """Een bron gaf geen bruikbaar antwoord. Wordt "onbekend" in het rapport."""


class HostGestopt(BronFout):
    """De host is deze run dicht (weigering, 5xx, time-outs of robots.txt)."""


class GeenAntwoord(BronFout):
    """De host antwoordde niet (time-out, verbinding, DNS). Anders dan een antwoord dat niet bruikbaar is."""


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


class Sessie:
    """Eén run: budget, pauze, robots per host en een stroomonderbreker per host."""

    def __init__(self, cache: dict, vandaag, http=None, ua: str | None = None, max_verzoeken: int = 60,
                 timeout_s: float = 10, pauze_s: float = 0.25, fout_opnieuw_na_dagen: int = 1,
                 fouten_op_rij_stop: int = 3, robots_dagen: int = ROBOTS_DAGEN,
                 robots_terugval_dagen: int = ROBOTS_TERUGVAL_DAGEN, slaap=time.sleep):
        self.cache = cache
        self.vandaag = _datum(vandaag).isoformat()
        self.http = http or standaard_http
        self.ua = ua or EERLIJKE_UA
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
        # Budget per woning (verrijk): een woning die niet in het budget past, leest alleen de cache.
        self.alleen_cache = False
        self.overgeslagen = 0
        # Fundering en klimaat: hoe vaak het gecombineerde antwoord voor een bron niets bruikbaars gaf
        # (bron -> aantal), en of de dienst de combinatie als geheel weigerde (dan de rest van de run los).
        self.terugval: Counter = Counter()
        self.kea_los = False
        self.kea_mis = 0                            # terugvallen waarbij het losse verzoek wel iets gaf

    def host_dicht(self, host: str) -> bool:
        """Krijgt deze host deze run geen verzoek meer (gestopt, of een weigering van hooguit een dag oud)?"""
        if host in self.dicht:
            return True
        w = (self.cache.get("verrijking_weigering") or {}).get(host)
        dagen = _leeftijd(w, self.vandaag, "datum")
        return dagen is not None and dagen < self.fout_opnieuw_na_dagen

    def robots_kost(self, host: str) -> int | None:
        """Verzoeken die robots.txt van deze host nog kost: 0 (deze run of vandaag al gelezen), 1, of
        None als robots.txt vandaag niet te lezen was (de host krijgt dan geen verzoek)."""
        if host in self.robots_run:
            return 0
        e = (self.cache.get("robots") or {}).get(host)
        dagen = _leeftijd(e, self.vandaag)
        if dagen is not None and e.get("fout"):
            return None if dagen < self.fout_opnieuw_na_dagen else 1
        if dagen is not None and isinstance(e.get("data"), dict) and 0 <= dagen < self.robots_dagen:
            return 0
        return 1

    def kost(self, per_host: dict) -> int:
        """Bovengrens van de verzoeken voor {host: aantal}, met robots.txt, zonder hosts die dicht zijn."""
        n = 0
        for host, aantal in per_host.items():
            robots = None if self.host_dicht(host) else self.robots_kost(host)
            if aantal > 0 and robots is not None:
                n += aantal + robots
        return n

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

    def _stop(self, host: str, reden: str, mee: bool = False) -> HostGestopt:
        """Sluit de host voor deze run; met mee=True ook voor een volgende Sessie (neem_over)."""
        self.dicht[host] = reden
        if mee:
            self.geweigerd[host] = reden
        return HostGestopt(reden)

    def _verzoek(self, url: str, accept: str) -> tuple[int, bytes]:
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
            raise GeenAntwoord(f"geen antwoord ({type(exc).__name__})") from None
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
        dagen, oud = _leeftijd(e, self.vandaag), None
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
            status = None
        if oud is not None and (status is None or status >= 500):
            regels = oud                                 # onbereikbaar: de laatste goede versie
        elif status == 200:
            regels = robots_regels(body.decode("utf-8", "replace"))
            cache_schrijf(self.cache, "robots", host, self.vandaag, data={"regels": regels})
        elif 400 <= status < 500 and status not in (401, 403, 429):
            regels = []                                  # geen robots.txt: alles toegestaan
            cache_schrijf(self.cache, "robots", host, self.vandaag, data={"regels": regels})
        else:
            cache_schrijf(self.cache, "robots", host, self.vandaag, fout=f"status {status}")
            raise self._stop(host, f"robots.txt gaf status {status}", mee=True)
        self.robots_run[host] = regels
        return regels

    def haal(self, url: str, accept: str = "application/json") -> bytes:
        if self.alleen_cache:
            raise GeenBudget()
        deel = urllib.parse.urlparse(url)
        host = deel.hostname or ""
        if deel.scheme != "https" or not host:
            raise BronFout("alleen https")
        if host in self.dicht:
            raise HostGestopt(self.dicht[host])
        w = (self.cache.get("verrijking_weigering") or {}).get(host)
        dagen = _leeftijd(w, self.vandaag, "datum")
        if dagen is not None and dagen < self.fout_opnieuw_na_dagen:
            raise self._stop(host, f"weigerde eerder (status {w.get('status')})")
        pad = deel.path + (f"?{deel.query}" if deel.query else "")
        if not robots_mag(self._robots_regels(host), pad):
            raise self._stop(host, "robots.txt staat dit pad niet toe")
        status, body = self._verzoek(url, accept)
        if status in (401, 403, 429):
            self.cache.setdefault("verrijking_weigering", {})[host] = {"datum": self.vandaag, "status": status}
            raise self._stop(host, f"geweigerd (status {status})", mee=True)
        if status >= 500:
            raise self._stop(host, f"serverfout (status {status})", mee=True)
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

def _veld(w: dict, *namen):
    """De eerste gevulde waarde, in de rij zelf en dan in rij["d"], rij["listing"] en rij["details"]."""
    for bron in [w] + [w[k] for k in ("d", "listing", "details") if isinstance(w.get(k), dict)]:
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


def _bouwjaar(v) -> int | None:
    """Een bouwjaar als getal; None bij een plaatshouder (1005 en 9999 in de BAG) of iets onleesbaars."""
    try:
        bj = int(v)
    except (TypeError, ValueError):
        return None
    return bj if 1200 <= bj <= date.today().year + 5 else None


def prioriteit(w: dict) -> tuple[int, float]:
    """Past en Krap eerst, daarna op score (hoog eerst). Zonder beoordeling ertussenin."""
    bs = [b for b in (w.get("beoordeling"), w.get("_beoordeling"), (w.get("d") or {}).get("_beoordeling"))
          if isinstance(b, dict)]
    poort = next((b["poort"].upper() for b in bs if isinstance(b.get("poort"), str)), "")
    score = next((float(b["score"]) for b in bs if isinstance(b.get("score"), (int, float))), 0.0)
    return POORT_RANG.get(poort, POORT_ONBEKEND_RANG), -score


# ---------------------------------------------------------------- parsers (op de gemeten antwoorden)

def _features(antwoord: dict, verplicht: bool = False) -> list:
    fs = antwoord.get("features")
    if verplicht and not isinstance(fs, list):
        raise BronFout("onverwacht antwoord")
    return fs or []


def _props(f: dict) -> dict:
    return f.get("properties") or {}


def bag_kies(antwoord: dict, postcode: str, huisnummer: str, toevoeging: str) -> tuple[dict | None, list[str]]:
    """Uit een verblijfsobject-antwoord: (verblijfsobject of None, pand-links).

    Een exacte toevoeging gaat voor. Zonder exacte treffer telt het pand alleen als alle
    verblijfsobjecten met dit nummer in hetzelfde pand liggen."""
    treffers = []
    for f in _features(antwoord):
        p = _props(f)
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
    p = _props(pand)
    try:
        n = int(p.get("aantal_verblijfsobjecten"))
    except (TypeError, ValueError):
        n = None
    return {"bouwjaar": _bouwjaar(p.get("bouwjaar")), "aantal_vbo_pand": n,
            "gebruiksdoel": _doel((vbo or {}).get("gebruiksdoel")) if vbo else None,
            "gebruiksdoel_pand": _doel(p.get("gebruiksdoel"))}


def _doel(v):
    """Een gebruiksdoel uit de BAG: tekst of een lijst van teksten. Iets anders = None."""
    if isinstance(v, str):
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    return None


def _tekst(v) -> str | None:
    return (v.strip() or None) if isinstance(v, str) else None


def _kaartwaarde(v) -> float | None:
    """Een kaartwaarde als getal; None als hij ontbreekt of negatief is (-9999 = buiten de kaart)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 or math.isnan(x) else x


def kea_klasse(soort: str, waarde) -> str | None:
    v = _kaartwaarde(waarde)
    return None if v is None else next((naam for grens, naam in KEA_KLASSEN[soort] if v <= grens), None)


def kea_parse(antwoord: dict) -> dict:
    uit = {"verschilzetting": None, "paalrot": None}
    laag_naar_soort = {v: k for k, v in KEA_LAGEN.items()}
    for f in _features(antwoord):
        laag = str(f.get("id") or "").split(".", 1)[0]
        soort = laag_naar_soort.get(laag)
        if not soort:
            continue
        waarde = next((v for k, v in _props(f).items() if k.startswith("sterke_c")), None)
        uit[soort] = kea_klasse(soort, waarde)
    if uit["verschilzetting"] is None and uit["paalrot"] is None:
        raise BronFout("geen kaartwaarde op dit punt")
    return uit


def _gray_per_laag(antwoord: dict, lagen: tuple, wat: str) -> dict:
    """De rasterwaarde per veld. De features hebben geen id: ze tellen op volgorde van de lagen."""
    fs = _features(antwoord)
    if len(fs) != len(lagen):
        raise BronFout(f"{len(fs)} van {len(lagen)} {wat} in het antwoord")
    return {veld: _props(f).get("GRAY_INDEX") for (veld, _), f in zip(lagen, fs)}


def rivm_parse(antwoord: dict) -> dict:
    ruw = _gray_per_laag(antwoord, RIVM_LAGEN, "geluidlagen")
    # Onder de kaartgrens (-9999) is geen fout: dan None.
    return {veld: None if (x := _kaartwaarde(v)) is None else int(round(x)) for veld, v in ruw.items()}


def pdok_buurt_parse(antwoord: dict) -> dict:
    fs = _features(antwoord)
    if not fs:
        raise BronFout("geen CBS-buurt op dit punt")
    p = _props(fs[0])
    uit = {k: _tekst(p.get(k)) for k in VELDEN["buurtcode"]}  # allowlist: niets anders lezen; alleen tekst
    if not uit["buurtcode"]:
        raise BronFout("buurt zonder buurtcode")
    return uit


def _cbs_getal(v) -> float | None:
    """Een CBS-waarde; None bij een code voor "ontbreekt" (-99997 en verwante negatieve codes)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v < 0 or math.isnan(v):
        return None
    return v


def pdok_kern_parse(antwoord: dict, buurtcode: str | None = None) -> dict:
    """Kerncijfers van de buurt uit hetzelfde PDOK-antwoord als de buurtcode. Alleen KERN_PDOK en de
    gemeentecode worden gelezen (allowlist): geen bevolkingsveld komt hier doorheen."""
    for f in _features(antwoord):
        p = _props(f)
        if buurtcode and p.get("buurtcode") != buurtcode:
            continue
        uit = {k: _cbs_getal(p.get(veld)) for k, veld in KERN_PDOK.items()}
        if all(x is None for x in uit.values()):
            raise BronFout("geen kerncijfers voor deze buurt")
        gm = p.get("gemeentecode")
        uit["gemeentecode"] = gm if isinstance(gm, str) and re.fullmatch(r"GM\d{4}", gm) else None
        return uit
    raise BronFout("geen CBS-buurt op dit punt")


def pdok_gemeente_parse(antwoord: dict, gemeentecode: str) -> dict:
    """Aantal woningen van de gemeente (de noemer van het gemeentecijfer). Het antwoord kan ook een
    watervlak met dezelfde code bevatten (woningvoorraad -99997): het grootste geldige getal telt."""
    aantallen = [_cbs_getal(_props(f).get("woningvoorraad")) for f in _features(antwoord)
                 if _props(f).get("gemeentecode") == gemeentecode]
    aantallen = [a for a in aantallen if a]
    if not aantallen:
        raise BronFout("geen aantal woningen voor de gemeente")
    return {"woningen": int(max(aantallen))}


def politie_parse(antwoord: dict, dimensie: str, onderwerp: str, codes: dict, buurtcode: str) -> dict:
    """Aantallen per soort voor de buurt en de gemeente uit één OData-antwoord (47018NED of 47024NED)."""
    uit: dict = {"jaar": POLITIE_JAAR}
    for naam in codes.values():
        uit[naam] = uit["gem_" + naam] = None
    for r in antwoord.get("value") or []:
        naam = codes.get(str(r.get(dimensie) or "").strip())
        regio = str(r.get("WijkenEnBuurten") or "").strip()
        n = _cbs_getal(r.get(onderwerp))
        if not naam or n is None or str(r.get("Perioden") or "").strip() != POLITIE_PERIODE:
            continue
        if regio == buurtcode:
            uit[naam] = int(n)
        elif regio.startswith("GM"):
            uit["gem_" + naam] = int(n)
    if all(uit[n] is None for n in codes.values()):
        raise BronFout("geen cijfers voor deze buurt")
    return uit


def lucht_parse(antwoord: dict) -> dict:
    uit = {}
    for veld, ruw in _gray_per_laag(antwoord, RIVM_LUCHT_LAGEN, "lagen").items():
        x = _cbs_getal(ruw)                                              # negatief = buiten de kaart
        uit[veld] = None if x is None else (int(round(x)) if veld == "groen_pct" else round(float(x), 1))
    if all(x is None for x in uit.values()):
        raise BronFout("geen kaartwaarde op dit punt")
    return uit


def _klasse_1_5(v) -> int | None:
    x = _kaartwaarde(v)
    return int(x) if x in (1, 2, 3, 4, 5) else None


def klimaat_parse(antwoord: dict) -> dict:
    """Wateroverlast (klasse van het pand op het punt), overstromingskans en grondwater (klasse 1 tot 5).
    Geen pand of geen klasse op het punt = None, geen fout. Van het pand alleen de klasse: het
    BAG-nummer en het bouwjaar in het antwoord worden niet gelezen."""
    fs = _features(antwoord, verplicht=True)
    uit = {k: None for k in VELDEN["klimaat"]}
    for f in fs:
        laag = str(f.get("id") or "").split(".", 1)[0]
        p = _props(f)
        if laag == KEA_KLIMAAT_LAGEN["wateroverlast"]:
            diepte = str(p.get("waterdiepte_klasse") or "").strip()
            if diepte in KEA_WATERDIEPTE:
                uit["wateroverlast"], uit["waterdiepte"] = KEA_WATERDIEPTE[diepte], diepte
        elif laag == KEA_KLIMAAT_LAGEN["grondwater"]:
            uit["grondwater"] = _klasse_1_5(p.get("gridcode"))
        elif "GRAY_INDEX" in p:                                  # het enige raster in dit verzoek
            uit["overstromingskans"] = _klasse_1_5(p.get("GRAY_INDEX"))
    return uit


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def gezicht_parse(antwoord: dict) -> dict:
    """Beschermd stads- of dorpsgezicht op het punt: naam en jaar van aanwijzing, of None."""
    for f in _features(antwoord, verplicht=True):
        p = _props(f)
        if p.get("namespace") == RCE_GEZICHT:
            jaar = str(p.get("legalfoundationdate") or "")[:4]
            return {"gezicht": str(p.get("text") or "").strip() or "ja",
                    "gezicht_sinds": int(jaar) if jaar.isdigit() else None}
    return {"gezicht": None, "gezicht_sinds": None}


def monument_parse(antwoord: dict, lat: float, lon: float) -> int:
    """Aantal rijksmonumenten (punten) binnen MONUMENT_STRAAL_M van het punt."""
    n = 0
    for f in _features(antwoord, verplicht=True):
        c = (f.get("geometry") or {}).get("coordinates")
        if _props(f).get("namespace") != RCE_MONUMENT or not isinstance(c, list) or len(c) < 2:
            continue
        try:
            if _meters(lat, lon, float(c[1]), float(c[0])) <= MONUMENT_STRAAL_M:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _getal(v) -> float | None:
    """Een getal (geen bool, geen NaN of oneindig); tekst of iets anders = None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return v


def lbm_parse(antwoord: dict) -> dict[str, dict]:
    """Per buurtcode de velden van de Leefbaarometer. Een antwoord zonder lijst features is een fout
    (anders zou een foutdocument als "gemeente zonder buurten" 30 dagen in de cache staan); een
    feature in een onverwachte vorm wordt overgeslagen en een waarde die geen getal is, wordt None."""
    if not isinstance(antwoord, dict) or not isinstance(antwoord.get("features"), list):
        raise BronFout("onverwacht antwoord")
    uit = {}
    for f in antwoord["features"]:
        p = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not p["id"].strip():
            continue
        velden = {k: _getal(p.get(k)) for k in VELDEN["leefbaarometer"]}
        k = velden["kscore"]
        velden["kscore"] = int(k) if k is not None and k == int(k) and int(k) in LBM_KLASSE else None
        uit[p["id"].strip()] = velden
    if antwoord["features"] and not uit:
        raise BronFout("onverwacht antwoord")
    return uit


def cbs_tevreden_parse(antwoord: dict) -> dict:
    uit = {k: None for k in VELDEN["tevredenheid"]}
    for r in antwoord.get("value") or []:
        marge = CBS_MARGES.get(str(r.get("Marges") or "").strip())
        v = _cbs_getal(r.get("TevredenMetDeWoonomgeving_57"))      # tekst of een code voor "ontbreekt" = None
        if marge == "waarde":
            uit["tevreden_woonomgeving"] = v
            uit["tevreden_woning"] = _cbs_getal(r.get("TevredenMetDeWoning_56"))
        elif marge == "min":
            uit["tevreden_woonomgeving_min"] = v
        elif marge == "max":
            uit["tevreden_woonomgeving_max"] = v
    if uit["tevreden_woonomgeving"] is None and uit["tevreden_woning"] is None:
        raise BronFout("geen tevredenheidscijfer voor deze buurt")
    return uit


# ---------------------------------------------------------------- URL's: één vorm per soort dienst

def _bbox(lat: float, lon: float, dlat: float, dlon: float) -> str:
    return f"{lon - dlon:.6f},{lat - dlat:.6f},{lon + dlon:.6f},{lat + dlat:.6f}"


def _ogc_url(collectie: str, **filters) -> str:
    """OGC API Features: de items van een collectie (PDOK), als JSON."""
    return collectie + "?" + "&".join(f"{k}={v}" for k, v in filters.items()) + "&f=json"


WMS_FEATURES_PER_LAAG = 10


def _wms_url(wms: str, lagen, lat: float, lon: float) -> str:
    """WMS 1.3.0 GetFeatureInfo met CRS:84 (lon,lat), bbox van ~100 x 100 m, pixel in het midden.

    Bij de Klimaateffectatlas groeit feature_count mee met het aantal lagen (10 per laag): telt de dienst
    het maximum over alle lagen samen, dan vallen de laatste lagen van een gecombineerd verzoek niet weg
    als een eerdere laag meerdere vlakken op het punt heeft. De RIVM-lagen zijn rasters met één waarde
    per laag; daar blijft het de gemeten 10."""
    q = ",".join(lagen)
    par = {"service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo", "layers": q,
           "query_layers": q, "styles": "", "crs": "CRS:84", "bbox": _bbox(lat, lon, 0.00045, 0.00073),
           "width": 101, "height": 101, "i": 50, "j": 50, "info_format": "application/json",
           "feature_count": WMS_FEATURES_PER_LAAG * (len(tuple(lagen)) if wms == KEA_WMS else 1)}
    return wms + "?" + urllib.parse.urlencode(par, safe=",:")


def _odata_url(tabel: str, filt: str, sel: str) -> str:
    """CBS OData (dataderden): een TypedDataSet met een filter en alleen de gevraagde kolommen."""
    return tabel + "?" + urllib.parse.urlencode({"$filter": filt, "$select": sel, "$format": "json"},
                                                quote_via=urllib.parse.quote)


def _buurt_url(lat: float, lon: float) -> str:
    return _ogc_url(PDOK_BUURTEN, bbox=_bbox(lat, lon, 0.00001, 0.00001))    # PDOK weigert een bbox zonder oppervlak


def _politie_url(basis: str, dimensie: str, onderwerp: str, codes: dict, buurtcode: str, gemeentecode: str | None) -> str:
    regio = f"WijkenEnBuurten eq '{buurtcode}'"
    if gemeentecode:
        regio = f"({regio} or startswith(WijkenEnBuurten,'{gemeentecode}'))"
    soorten = " or ".join(f"{dimensie} eq '{c.ljust(6)}'" for c in codes)
    return _odata_url(basis, f"{regio} and Perioden eq '{POLITIE_PERIODE}' and ({soorten})",
                      f"{dimensie},WijkenEnBuurten,Perioden,{onderwerp}")


def _tevreden_url(buurtcode: str) -> str:
    return _odata_url(CBS_50150, f"WijkenEnBuurten eq '{buurtcode}' and Perioden eq '{CBS_PERIODE}' "
                                 f"and Leeftijd eq '{CBS_LEEFTIJD_18PLUS}'",
                      "Marges,WijkenEnBuurten,TevredenMetDeWoning_56,TevredenMetDeWoonomgeving_57")


def _lbm_url(gemeente: str) -> str:
    par = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": LBM_LAAG,
           "outputFormat": "application/json", "propertyName": "id," + ",".join(VELDEN["leefbaarometer"]),
           "cql_filter": "gemeente='" + gemeente.replace("'", "''") + "'"}
    return LBM_WFS + "?" + urllib.parse.urlencode(par)


# ---------------------------------------------------------------- ophalen per bron

def bag_ophalen(sessie: Sessie, pc: str, nr: str, ext: str, lat: float, lon: float) -> dict:
    """Verblijfsobjecten rond het punt (zo nodig één ruimere poging), daarna het pand."""
    for dlat, dlon, limit in ((0.00014, 0.00022, 200), (0.0007, 0.0011, 1000)):
        url = _ogc_url(f"{BAG_BASIS}/verblijfsobject/items", bbox=_bbox(lat, lon, dlat, dlon), limit=limit)
        vbo, panden = bag_kies(sessie.haal_json(url), pc, nr, ext)
        if panden:
            break
    else:
        raise BronFout("adres niet gevonden in de BAG rond het punt")
    href = panden[0]
    if not href.startswith(BAG_PAND_PREFIX):
        raise BronFout("onverwachte pand-link")
    return bag_pand_velden(sessie.haal_json(href + ("&" if "?" in href else "?") + "f=json"), vbo)


def erfgoed_ophalen(sessie: Sessie, lat: float, lon: float) -> dict:
    def rce(collectie: str, dlat: float, dlon: float) -> dict:
        return sessie.haal_json(_ogc_url(f"{RCE_BASIS}/{collectie}/items", bbox=_bbox(lat, lon, dlat, dlon), limit=50))
    uit = gezicht_parse(rce("rce_inspire_polygons", 0.00001, 0.00001))
    dlat = MONUMENT_STRAAL_M / 111_320
    uit["monumenten_dichtbij"] = monument_parse(rce("rce_inspire_points", dlat, dlat / math.cos(math.radians(lat))),
                                                lat, lon)
    return uit


# Bronnen met één WMS GetFeatureInfo op het punt. De naam is ook de cachesectie en de schakelaar.
WMS_BRONNEN = {
    "fundering": (KEA_WMS, tuple(KEA_LAGEN.values()), kea_parse),
    "geluid": (RIVM_WMS, tuple(n for _, n in RIVM_LAGEN), rivm_parse),
    "lucht": (RIVM_WMS, tuple(n for _, n in RIVM_LUCHT_LAGEN), lucht_parse),
    "klimaat": (KEA_WMS, tuple(KEA_KLIMAAT_LAGEN.values()), klimaat_parse),
}


def _punt_ophalen(naam: str, sessie: Sessie, lat: float, lon: float) -> dict:
    if naam == "erfgoed":
        return erfgoed_ophalen(sessie, lat, lon)
    wms, lagen, parse = WMS_BRONNEN[naam]
    return parse(sessie.haal_json(_wms_url(wms, lagen, lat, lon)))


# Fundering en klimaat komen van dezelfde WMS op hetzelfde punt: samen één verzoek (zie de docstring).
KEA_BRONNEN = ("fundering", "klimaat")
KEA_LOS_NA = 2   # zo vaak gaf los wel iets en het gecombineerde antwoord niet: daarna de rest van de run los


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or ""


def _buurt_ophalen(sessie: Sessie, cache: dict, lat: float, lon: float) -> dict:
    """Buurtcode van het punt; de kerncijfers uit hetzelfde antwoord gaan per buurtcode de cache in."""
    antwoord = sessie.haal_json(_buurt_url(lat, lon))
    data = pdok_buurt_parse(antwoord)
    try:
        kern = {"data": pdok_kern_parse(antwoord, data["buurtcode"])}
    except BronFout as exc:
        kern = {"fout": str(exc)}
    except Exception as exc:  # noqa: BLE001  onverwachte kerncijfers nemen de buurtcode niet mee
        kern = {"fout": f"onverwacht antwoord ({type(exc).__name__})"}
    cache_schrijf(cache, "kerncijfers", data["buurtcode"], sessie.vandaag, **kern)
    return data


# ---------------------------------------------------------------- resultaat per bron

def _res(status: str, data=None, reden: str | None = None, uit_cache: bool = False, signalen=None) -> dict:
    """De vaste vorm van een resultaat. Status: ok, onbekend, budget, uit of niet_nodig."""
    return {"status": status, "data": data, "reden": reden, "uit_cache": uit_cache, "signalen": signalen or []}


def _uit() -> dict:
    return _res("uit", reden="staat uit in de config")


def _mislukt(exc: Exception, sessie: Sessie, cache: dict, sectie: str, sleutel: str) -> dict:
    """Een GeenBudget of BronFout als resultaat. Alleen een fout van de bron zelf komt in de cache
    (fout_opnieuw_na_dagen niet opnieuw); een op budget of een gestopte host zegt niets over dit element."""
    if isinstance(exc, GeenBudget):
        return _res("budget", reden="budget voor deze run op")
    if isinstance(exc, HostGestopt):
        return _res("onbekend", reden=f"bron gestopt: {exc}")
    cache_schrijf(cache, sectie, sleutel, sessie.vandaag, fout=str(exc))
    return _res("onbekend", reden=str(exc))


def _met_cache(sessie: Sessie, cache: dict, sectie: str, sleutel: str, vcfg: dict, ophalen) -> dict:
    """Eén element van een sectie: uit de cache, of opgehaald en bewaard."""
    data, st = cache_lees(cache, sectie, sleutel, vcfg, sessie.vandaag)
    if st == "vers":
        return _res("ok", data, uit_cache=True)
    if st == "fout_vers":
        reden = f"vorige poging mislukt ({cache[sectie][sleutel].get('fout')}); na een dag opnieuw"
        return {"status": "onbekend", "data": None, "uit_cache": True, "reden": reden, "signalen": []}
    try:
        nodig = SECTIES[sectie][1]
        if nodig > 1 and sessie.over < nodig:                  # meer dan één verzoek: niet half beginnen
            raise GeenBudget()
        data = ophalen()
    except (GeenBudget, BronFout) as exc:
        return _mislukt(exc, sessie, cache, sectie, sleutel)
    except Exception as exc:  # noqa: BLE001  onverwacht antwoord: nooit de run laten vallen
        cache_schrijf(cache, sectie, sleutel, sessie.vandaag, fout=f"onverwacht antwoord ({type(exc).__name__})")
        return _res("onbekend", reden="onverwacht antwoord")
    cache_schrijf(cache, sectie, sleutel, sessie.vandaag, data=data)
    return _res("ok", data)


def _kea_ophalen(sessie: Sessie, cache: dict, vcfg: dict, punt: tuple, namen) -> dict[str, dict]:
    """Fundering en klimaat op het punt, voor de bronnen in `namen`: {bron: resultaat}.

    Wat in de cache staat, komt daaruit. Blijft er één bron over, dan het gewone losse verzoek. Blijven
    beide over, dan één verzoek met alle lagen; elke bron leest daaruit zijn eigen lagen en komt los
    van de andere in zijn eigen cachesectie. Een fout of een onverwachte vorm bij de ene bron raakt de
    andere niet. Terugval (gemeten op vijf punten, maar niet op elk punt te voorspellen): gaf de
    dienst wel antwoord maar is er voor een bron niets bruikbaars, dan wordt die bron één keer los
    opgehaald, en dat losse antwoord geldt. Gaf het losse verzoek KEA_LOS_NA keer wel iets waar de combinatie
    niets gaf, dan gaat de rest van de run los (sessie.kea_los)."""
    sleutel = punt_sleutel(*punt)

    def los(naam: str) -> dict:
        return _met_cache(sessie, cache, naam, sleutel, vcfg, lambda: _punt_ophalen(naam, sessie, *punt))

    open_ = [n for n in namen if cache_lees(cache, n, sleutel, vcfg, sessie.vandaag)[1] is None]
    uit = {n: los(n) for n in namen if n not in open_}              # uit de cache: geen verzoek
    if len(open_) < 2 or sessie.kea_los:
        uit.update({n: los(n) for n in open_})
        return uit
    lagen = tuple(laag for n in open_ for laag in WMS_BRONNEN[n][1])
    try:
        antwoord = sessie.haal_json(_wms_url(KEA_WMS, lagen, *punt))
    except (GeenBudget, HostGestopt, GeenAntwoord) as exc:          # geen antwoord: zegt niets over de combinatie
        uit.update({n: _mislukt(exc, sessie, cache, n, sleutel) for n in open_})
        return uit
    except BronFout:                                                # wel een antwoord, niet bruikbaar (4xx, geen JSON)
        sessie.kea_los = True
        antwoord = None
    for n in open_:
        data = None
        try:
            if antwoord is not None:
                data = WMS_BRONNEN[n][2](antwoord)
                if not isinstance(data, dict) or all(x is None for x in data.values()):
                    data = None
                else:
                    cache_schrijf(cache, n, sleutel, sessie.vandaag, data=data)
        except Exception:  # noqa: BLE001  BronFout of een onverwachte vorm: alleen deze bron, en die gaat los
            data = None
        if data is None:
            sessie.terugval[n] += 1
            uit[n] = los(n)
            # Gaf het losse verzoek wel iets, dan klopte de combinatie niet (een punt zonder kaartwaarde
            # geeft los ook niets, en zegt dus niets). Na KEA_LOS_NA keer vraagt de rest van de run los:
            # anders kost elke nieuwe woning drie verzoeken in plaats van twee.
            d = uit[n].get("data")
            if antwoord is not None and uit[n]["status"] == "ok" and isinstance(d, dict) and any(x is not None for x in d.values()):
                sessie.kea_mis += 1
                if sessie.kea_mis >= KEA_LOS_NA:
                    sessie.kea_los = True
        else:
            uit[n] = _res("ok", data)
    return uit


def _leefbaarometer(sessie: Sessie, cache: dict, vcfg: dict, buurtcode: str, gemeente: str | None) -> dict:
    """Eén WFS-verzoek per gemeente (30 dagen), daarna per buurtcode uit de cache."""
    data, st = cache_lees(cache, "leefbaarometer", buurtcode, vcfg, sessie.vandaag)
    if st == "vers":
        return _res("ok", data, uit_cache=True)
    if not gemeente:
        return _res("onbekend", reden="gemeente onbekend")
    marker = "gemeente|" + gemeente
    _, mst = cache_lees(cache, "leefbaarometer", marker, vcfg, sessie.vandaag)
    if mst == "vers":
        return _res("onbekend", reden="buurt niet in de Leefbaarometer", uit_cache=True)
    if mst == "fout_vers":
        return _res("onbekend", reden="vorige poging mislukt; na een dag opnieuw", uit_cache=True)
    try:
        buurten = lbm_parse(sessie.haal_json(_lbm_url(gemeente)))
        for code, velden in buurten.items():
            cache_schrijf(cache, "leefbaarometer", code, sessie.vandaag, data=velden)
    except (GeenBudget, BronFout) as exc:
        return _mislukt(exc, sessie, cache, "leefbaarometer", marker)
    except Exception as exc:  # noqa: BLE001  onverwacht antwoord: alleen deze bron onbekend, de woning gaat door
        cache_schrijf(cache, "leefbaarometer", marker, sessie.vandaag,
                      fout=f"onverwacht antwoord ({type(exc).__name__})")
        return _res("onbekend", reden="onverwacht antwoord")
    cache_schrijf(cache, "leefbaarometer", marker, sessie.vandaag, data={"buurten": len(buurten)})
    if buurtcode in buurten:
        return _res("ok", buurten[buurtcode])
    return _res("onbekend", reden="buurt niet in de Leefbaarometer")


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
    for veld in VELDEN["geluid"]:
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
        tekst = f"Leefbaarometer {LBM_KLASSE[k]} ({LBM_JAAR}) in {naam}."
        if k <= dr["leefbaarometer_twijfel_max"]:
            twijfel = True
            uit.append(_signaal("sterk", tekst + " Staat de buurt niet op jouw lijst? Bekijk hem zelf."))
        else:
            uit.append(_signaal("goed" if k >= dr["leefbaarometer_goed_min"] else "info", tekst))
    onv = data.get("onv")
    if isinstance(onv, (int, float)) and onv <= dr["leefbaarometer_onv_let_op"]:
        uit.append(_signaal("let_op", f"Overlast en onveiligheid {_teken(onv)} ten opzichte van Nederland "
                                      f"(Leefbaarometer {LBM_JAAR})."))
    tv = data.get("tevreden_woonomgeving")
    if isinstance(tv, (int, float)):
        lo, hi = data.get("tevreden_woonomgeving_min"), data.get("tevreden_woonomgeving_max")
        marge = f", marge {_nl(lo, 0)} tot {_nl(hi, 0)}%" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
        niveau = ("let_op" if tv < dr["tevreden_woonomgeving_let_op"]
                  else "goed" if tv >= dr["tevreden_woonomgeving_goed"] else "info")
        uit.append(_signaal(niveau, f"Tevreden met de woonomgeving: {_nl(tv, 0)}% (RIVM 2024, modelschatting{marge})."))
    return uit, twijfel


# ---------------------------------------------------------------- één woning

def _verrijk_een(w: dict, sessie: Sessie, cache: dict, vcfg: dict, dr: dict) -> dict:
    aan = vcfg.get("bronnen") or {}
    punt = _coords(w)
    res: dict[str, dict] = {}

    def puntbron(naam: str) -> dict:
        if not aan.get(naam, True):
            return _uit()
        if not punt:
            return _res("onbekend", reden="geen coördinaten")
        return _met_cache(sessie, cache, naam, punt_sleutel(*punt), vcfg, lambda: _punt_ophalen(naam, sessie, *punt))

    if not aan.get("bag", True):
        res["bag"] = _uit()
    else:
        pc, nr = _postcode(w), _huisnummer(w)
        ext = _norm_toevoeging(_veld(w, "house_number_ext", "toevoeging"))
        if not pc or not nr or not punt:               # niets te vragen: geen verzoek en geen cache
            res["bag"] = {"status": "onbekend", "data": None, "uit_cache": False,
                          "reden": "geen coördinaten" if pc and nr else "geen postcode of huisnummer", "signalen": []}
        else:
            res["bag"] = _met_cache(sessie, cache, "bag", _hash_sleutel("adres", pc, nr, ext), vcfg,
                                    lambda: bag_ophalen(sessie, pc, nr, ext, *punt))
            if res["bag"]["status"] == "ok":
                res["bag"]["signalen"] = signalen_bag(res["bag"]["data"], dr)
    bag_data = res["bag"].get("data") or {}
    bouwjaar = bag_data.get("bouwjaar") or _bouwjaar(str(_veld(w, "construction_year", "bouwjaar") or "")[:4])
    n_vbo = bag_data.get("aantal_vbo_pand")

    # Fundering: alleen bij een pand van voor 1970 (of een onbekend bouwjaar). Samen met klimaat in
    # één verzoek (_kea_ophalen); wat uit staat, niet nodig is of geen punt heeft, vraagt niets.
    if aan.get("fundering", True) and bouwjaar and bouwjaar >= dr["fundering_bouwjaar_voor"]:
        res["fundering"] = _res("niet_nodig", {"bouwjaar": bouwjaar})
    kea = [n for n in KEA_BRONNEN if n not in res and punt and aan.get(n, True)]
    res.update(_kea_ophalen(sessie, cache, vcfg, punt, kea) if kea else {})
    for naam in KEA_BRONNEN:
        if naam not in res:
            res[naam] = puntbron(naam)                 # uit of geen coördinaten
    f = res["fundering"]
    f["signalen"] = signalen_fundering(f["status"], f.get("data"), bouwjaar, n_vbo, dr)

    res["geluid"] = puntbron("geluid")
    if res["geluid"]["status"] == "ok":
        res["geluid"]["signalen"] = signalen_geluid(res["geluid"]["data"], dr)

    # Buurt: buurtcode, Leefbaarometer, tevredenheid. De buurtcode is ook nodig voor de kerncijfers
    # en de politiecijfers.
    bc = None
    if punt and any(aan.get(b, True) for b in ("buurt", "kerncijfers", "veiligheid")):
        bc = _met_cache(sessie, cache, "buurtcode", punt_sleutel(*punt), vcfg,
                        lambda: _buurt_ophalen(sessie, cache, *punt))
    res["buurt"] = _buurt(sessie, cache, vcfg, dr, aan, punt, bc)

    # Kerncijfers en politiecijfers per buurt
    code = bc["data"]["buurtcode"] if bc and bc["status"] == "ok" else None
    kern = None
    if code and (aan.get("kerncijfers", True) or aan.get("veiligheid", True)):
        # Uit de cache (gevuld door _buurt_ophalen); een buurtcode van voor 18 nov 2026 heeft ze nog
        # niet: dan één keer hetzelfde PDOK-verzoek opnieuw.
        kern = _met_cache(sessie, cache, "kerncijfers", code, vcfg,
                          lambda: pdok_kern_parse(sessie.haal_json(_buurt_url(*punt)), code))
    for naam in ("kerncijfers", "veiligheid"):
        if not aan.get(naam, True):
            res[naam] = _uit()
        elif not punt:
            res[naam] = _res("onbekend", reden="geen coördinaten")
        elif not code:
            res[naam] = _res(bc["status"], reden=bc["reden"])
        elif kern["status"] != "ok":
            res[naam] = _res(kern["status"], reden=kern["reden"])
        elif naam == "kerncijfers":
            data = {k: kern["data"].get(k) for k in UITVOER_VELDEN["kerncijfers"] if k != "jaar"}
            data["jaar"] = KERN_JAAR
            res[naam] = _res("ok", data, uit_cache=kern["uit_cache"])
        else:
            res[naam] = _veiligheid(sessie, cache, vcfg, code, kern["data"])

    # Lucht en groen (RIVM) en erfgoed (RCE via PDOK); klimaat is hierboven met fundering opgehaald
    for naam in ("lucht", "erfgoed"):
        res[naam] = puntbron(naam)
    if res["lucht"]["status"] == "ok" and not aan.get("groen", True):
        res["lucht"]["data"] = dict(res["lucht"]["data"], groen_pct=None)
    return res


def kosten(w: dict, sessie: Sessie, cache: dict, vcfg: dict, dr: dict) -> int:
    """Bovengrens van de verzoeken die deze woning nog vraagt: wat niet (vers) in de cache staat, met de
    kosten uit SECTIES, plus robots.txt per host die nog niet gelezen is. Volgt _verrijk_een.

    Een bron die uit staat, niet nodig is, vandaag al mislukte of op een gestopte host staat, kost
    niets. Is de buurtcode nog onbekend, dan telt de buurt als nieuw in een nieuwe gemeente."""
    aan = vcfg.get("bronnen") or {}
    punt = _coords(w)
    per_host: Counter = Counter()
    pdok, kea, rivm = _host(BAG_BASIS), _host(KEA_WMS), _host(RIVM_WMS)
    cbs, lbm = _host(CBS_50150), _host(LBM_WFS)

    def open_(sectie: str, sleutel: str) -> bool:
        return cache_lees(cache, sectie, sleutel, vcfg, sessie.vandaag)[1] is None

    def tel(host: str, sectie: str, sleutel: str) -> None:
        if open_(sectie, sleutel):
            per_host[host] += SECTIES[sectie][1]

    if not punt:                                       # zonder punt vraagt geen enkele bron iets
        return 0
    pt = punt_sleutel(*punt)
    bouwjaar = _bouwjaar(str(_veld(w, "construction_year", "bouwjaar") or "")[:4])
    pc, nr = _postcode(w), _huisnummer(w)
    if aan.get("bag", True) and pc and nr:
        adres = _hash_sleutel("adres", pc, nr, _norm_toevoeging(_veld(w, "house_number_ext", "toevoeging")))
        tel(pdok, "bag", adres)
        bag, st = cache_lees(cache, "bag", adres, vcfg, sessie.vandaag)
        if st == "vers":
            bouwjaar = bag.get("bouwjaar") or bouwjaar
        elif st is None:
            bouwjaar = None                            # de BAG kan een ander bouwjaar geven: fundering meetellen
    nodig = [n for n in KEA_BRONNEN if aan.get(n, True) and open_(n, pt)
             and not (n == "fundering" and bouwjaar and bouwjaar >= dr["fundering_bouwjaar_voor"])]
    if nodig:                                          # samen één verzoek
        per_host[kea] += max(SECTIES[n][1] for n in nodig)
    for naam, host in (("geluid", rivm), ("lucht", rivm), ("erfgoed", pdok)):
        if aan.get(naam, True):
            tel(host, naam, pt)

    buurt, veilig = aan.get("buurt", True), aan.get("veiligheid", True)
    if not (buurt or veilig or aan.get("kerncijfers", True)):
        return sessie.kost(per_host)
    bc, st = cache_lees(cache, "buurtcode", pt, vcfg, sessie.vandaag)
    code = bc.get("buurtcode") if st == "vers" else None
    if st == "fout_vers" or (st == "vers" and not isinstance(code, str)):
        return sessie.kost(per_host)
    politie = {cbs: sum(SECTIES[s][1] for s in POLITIE_TABELLEN), pdok: SECTIES["gemeente"][1]}
    if st is None:                                     # nieuwe buurt: het ergste geval
        if sessie.host_dicht(pdok) or sessie.robots_kost(pdok) is None:
            return sessie.kost(per_host)               # geen buurtcode te krijgen: dan ook niets erachter
        per_host[pdok] += SECTIES["buurtcode"][1]
        if buurt:
            per_host[lbm] += SECTIES["leefbaarometer"][1]
            per_host[cbs] += SECTIES["tevredenheid"][1] if aan.get("tevredenheid", True) else 0
        per_host.update(politie if veilig else {})
        return sessie.kost(per_host)
    if buurt:
        gemeente = bc.get("gemeentenaam")
        if open_("leefbaarometer", code) and isinstance(gemeente, str) and gemeente:
            tel(lbm, "leefbaarometer", "gemeente|" + gemeente)
        if aan.get("tevredenheid", True):
            tel(cbs, "tevredenheid", code)
    kern, kst = cache_lees(cache, "kerncijfers", code, vcfg, sessie.vandaag)
    if kst is None:
        per_host[pdok] += SECTIES["kerncijfers"][1]
        per_host.update(politie if veilig else {})
    elif kst == "vers" and veilig and re.fullmatch(r"BU\d{8}", code):
        woningen = kern.get("woningen")
        if isinstance(woningen, (int, float)) and woningen >= MIN_WONINGEN_NOEMER:
            for sectie in POLITIE_TABELLEN:
                tel(cbs, sectie, code)
            if isinstance(kern.get("gemeentecode"), str):
                tel(pdok, "gemeente", kern["gemeentecode"])
    return sessie.kost(per_host)


def _per_1000(aantal, woningen) -> float | None:
    if not isinstance(aantal, (int, float)) or not isinstance(woningen, (int, float)) or woningen < MIN_WONINGEN_NOEMER:
        return None
    return round(aantal / woningen * 1000, 1)


def _veiligheid(sessie: Sessie, cache: dict, vcfg: dict, code: str, kern: dict) -> dict:
    """Geregistreerde misdrijven en overlast per 1.000 woningen, voor de buurt en de gemeente.

    Het aantal woningen (CBS-kerncijfers) is alleen de noemer en komt niet in de uitvoer."""
    woningen = kern.get("woningen")
    if not isinstance(woningen, (int, float)) or woningen < MIN_WONINGEN_NOEMER:
        return _res("onbekend", reden="te weinig woningen in de buurt voor een cijfer per 1.000")
    if not re.fullmatch(r"BU\d{8}", code):
        return _res("onbekend", reden="onverwachte buurtcode")
    gm = kern.get("gemeentecode")
    delen = [_met_cache(sessie, cache, sectie, code, vcfg, lambda t=tabel: politie_parse(
        sessie.haal_json(_politie_url(*t, code, gm)), *t[1:], code)) for sectie, tabel in POLITIE_TABELLEN.items()]
    goed = [x for x in delen if x["status"] == "ok"]
    redenen = "; ".join(x["reden"] for x in delen if x["status"] != "ok" and x.get("reden")) or None
    if not goed:
        return _res("budget" if "budget" in [x["status"] for x in delen] else "onbekend", reden=redenen)
    gem_woningen = None
    if gm:
        g = _met_cache(sessie, cache, "gemeente", gm, vcfg, lambda: pdok_gemeente_parse(
            sessie.haal_json(_ogc_url(PDOK_GEMEENTEN, gemeentecode=gm, limit=10)), gm))
        gem_woningen = (g.get("data") or {}).get("woningen") if g["status"] == "ok" else None
    aantallen = {}
    for x in goed:
        aantallen.update(x["data"])
    data = {"jaar": aantallen.get("jaar") or POLITIE_JAAR}
    for k in VEILIGHEID_SOORTEN:
        data[f"{k}_per_1000"] = _per_1000(aantallen.get(k), woningen)
        data[f"gem_{k}_per_1000"] = _per_1000(aantallen.get("gem_" + k), gem_woningen)
    return _res("ok", data, redenen, all(x["uit_cache"] for x in goed))


def _buurt(sessie: Sessie, cache: dict, vcfg: dict, dr: dict, aan: dict, punt, bc: dict | None) -> dict:
    if not aan.get("buurt", True):
        return dict(_uit(), twijfel=False)
    if not punt:
        return dict(_res("onbekend", reden="geen coördinaten"), twijfel=False, delen={})
    delen = {"buurtcode": bc["status"]}
    if bc["status"] != "ok":
        return dict(_res(bc["status"], reden=bc["reden"], uit_cache=bc["uit_cache"]), twijfel=False, delen=delen)
    code = bc["data"]["buurtcode"]
    lbm = _leefbaarometer(sessie, cache, vcfg, code, bc["data"].get("gemeentenaam"))
    delen["leefbaarometer"] = lbm["status"]
    if aan.get("tevredenheid", True):
        tv = _met_cache(sessie, cache, "tevredenheid", code, vcfg,
                        lambda: cbs_tevreden_parse(sessie.haal_json(_tevreden_url(code))))
    else:
        tv = _uit()
    delen["tevredenheid"] = tv["status"]
    data = dict(bc["data"])
    for sectie, x in (("leefbaarometer", lbm), ("tevredenheid", tv)):
        for k in VELDEN[sectie]:
            data[k] = (x.get("data") or {}).get(k)
    redenen = "; ".join(f"{naam}: {x['reden']}" for naam, x in (("Leefbaarometer", lbm), ("tevredenheid", tv))
                        if x["status"] not in ("ok", "uit") and x.get("reden")) or None
    if lbm["status"] == "ok" or tv["status"] == "ok":
        sig, twijfel = signalen_buurt(data, dr)
        uit_cache = all(x.get("uit_cache") for x in (bc, lbm, tv) if x["status"] != "uit")
        return dict(_res("ok", data, redenen, uit_cache, sig), twijfel=twijfel, delen=delen)
    status = "budget" if "budget" in (lbm["status"], tv["status"]) else "onbekend"
    return dict(_res(status, reden=redenen), twijfel=False, delen=delen)


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


def postcode_sleutel(postcode) -> str | None:
    """Sleutel van een postcode in funda_werk_coords.json en funda_thuis_coords.json: een hash,
    zodat de postcode niet leesbaar in het bestand staat. Geen geldige postcode -> None."""
    pc = postcode_norm(postcode)
    return _hash_sleutel("pc", pc) if pc else None


def coords_cache_lees(pad) -> tuple[dict, bool]:
    """Een coördinatencache als {gehashte sleutel: [lat, lon]}, plus of er iets is omgezet.

    Migratie bij laden: een oude leesbare sleutel (de postcode zelf) wordt de hash; iets wat geen
    postcode en geen hash is, of geen coördinatenpaar heeft, valt weg. Is er omgezet, dan schrijft
    de aanroeper het bestand opnieuw (coords_cache_schrijf): de leesbare sleutel staat er dan niet
    meer in. Een onleesbaar of ontbrekend bestand = leeg."""
    try:
        ruw = json.loads(pad.read_text(encoding="utf-8")) if pad.exists() else {}
    except Exception:  # noqa: BLE001
        ruw = {}
    uit: dict = {}
    omgezet = False
    for k, waarde in (ruw.items() if isinstance(ruw, dict) else ()):
        punt = coord_paar(waarde)
        if isinstance(k, str) and re.fullmatch(r"pc:[0-9a-f]{20}", k) and punt:
            uit[k] = list(punt)
            continue
        omgezet = True
        sleutel = postcode_sleutel(k)
        if sleutel and punt:
            uit.setdefault(sleutel, list(punt))
    return uit, omgezet


def coords_cache_schrijf(pad, cache: dict) -> None:
    pad.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def postcode_url(postcode: str) -> str:
    return _ogc_url(BAG_ADRES, postcode=postcode, limit=GEOCODE_LIMIET)


def postcode_punt_parse(antwoord: dict, postcode: str) -> tuple[float, float] | None:
    """(lat, lon) van een postcode uit een adres-antwoord: het gemiddelde van de adrespunten.

    Alleen features met precies deze postcode en een punt in Nederland. Adressen met status
    "Naamgeving uitgegeven" gaan voor; een ingetrokken adres telt alleen als er geen ander is."""
    uitgegeven, alle = [], []
    for f in (antwoord or {}).get("features") or []:
        p = _props(f)
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
       voor bron in BRONNEN. Bij buurt ook "twijfel" (Leefbaarometer
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
    def kost_van(i: int) -> int:
        try:
            return kosten(woningen[i], sessie, cache, vcfg, dr)
        except Exception:  # noqa: BLE001  de telling mag de woning nooit tegenhouden
            return 0

    volgorde = sorted(range(len(woningen)), key=lambda j: prioriteit(woningen[j]))
    # Een woning die meer kost dan het hele budget (alleen bij een lage max_calls_per_run) past nooit in
    # zijn geheel en begint daarom met een onaangeroerd budget. Stond hij achter een woning die elke run
    # een paar verzoeken vraagt (een herpoging, een nieuw huisnummer in een bekend pand), dan was het
    # budget nooit onaangeroerd en wachtte hij eeuwig. Daarom gaat de eerste zo'n woning voorop: wat lukt
    # staat daarna in de cache, dus na een of twee runs past hij en geldt de gewone volgorde weer.
    te_duur = next((i for i in volgorde if kost_van(i) > sessie.max_verzoeken), None)
    if te_duur is not None:
        volgorde.remove(te_duur)
        volgorde.insert(0, te_duur)
    for i in volgorde:
        # Budget per woning: alleen beginnen als de hele woning past. Anders leest hij alleen de cache
        # ("budget" voor wat ontbreekt) en gaat het budget naar de volgende woning die wel past. Kost
        # een woning meer dan het hele budget, dan begint hij toch zolang het budget onaangeroerd is.
        kost = kost_van(i)
        te_groot = kost > sessie.max_verzoeken and sessie.over == sessie.max_verzoeken
        sessie.alleen_cache = kost > sessie.over and not te_groot
        sessie.overgeslagen += sessie.alleen_cache
        try:
            uit[sleutels[i]] = _verrijk_een(woningen[i], sessie, cache, vcfg, dr)
        except Exception as exc:  # noqa: BLE001  vangnet: nooit een woning minder
            uit[sleutels[i]] = {b: {"status": "onbekend", "data": None, "uit_cache": False, "signalen": [],
                                    "reden": f"interne fout ({type(exc).__name__})"} for b in BRONNEN}
    sessie.alleen_cache = False
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
        if sessie.overgeslagen:
            regels.append(f"[verrijking] {sessie.overgeslagen} woningen pasten niet in het budget en wachten "
                          "op de volgende run")
        if sessie.terugval:
            delen = ", ".join(f"{b} {n}" for b, n in sorted(sessie.terugval.items()))
            regels.append(f"[verrijking] gecombineerd verzoek fundering en klimaat gaf niets bruikbaars, los "
                          f"opgehaald: {delen}" + ("; de rest van de run los" if sessie.kea_los else ""))
    n_zwak = sum(1 for w in uitvoer.values() if (w.get("buurt") or {}).get("twijfel"))
    if n_zwak:
        regels.append(f"[verrijking] {n_zwak} woningen in een buurt met Leefbaarometer zwak of slechter")
    return regels
