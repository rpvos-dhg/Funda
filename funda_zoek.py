"""
Dagelijkse Funda-check voor een koopappartement.

Zoekt koopappartementen rond de zoekpostcode uit funda_personal.json, binnen
de prijs- en oppervlaktegrenzen uit diezelfde config. Filtert beleggingsobjecten
en begane grond weg, sluit ongewenste buurten uit en markeert twijfelbuurten
met een waarschuwing. Woningen die al bekend zijn, blijven via de pool in beeld;
"nieuw" betekent: niet eerder gezien.

Vereisten (pyfunda vastgepind op v2.9.0):
    pip install -r requirements.txt

Gebruik:
    python funda_zoek.py                 # volledige run, rapport, commit en push van docs/
    python funda_zoek.py --no-open       # zonder browser
    python funda_zoek.py --no-push       # zonder commit en push
    python funda_zoek.py --debug-wijken
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from datetime import datetime

from funda import Funda as _Funda

from funda_sitemap_zoek import (
    ACHTERSTAND as SITEMAP_ACHTERSTAND,
    DICHT_NA,
    MISLUKT as SITEMAP_MISLUKT,
    NIET_IN_SITEMAP,
    OPGEHAALD as SITEMAP_OPGEHAALD,
    OVERGESLAGEN as SITEMAP_OVERGESLAGEN,
    DetailEndpointDicht,
    WoningNietGevonden,
    log_tekst,
    publieke_log,
)

from funda_verrijking import coord_paar

try:
    from funda_rapport import genereer_rapport
except ImportError:
    genereer_rapport = None


# Hoe deze client zich bij funda's API-hosts meldt: als zichzelf, met een link
# naar de (publieke) repo. Geen browser, geen app.
EERLIJKE_UA = "funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)"
# Statussen waarmee een endpoint zegt "jij niet" of "nu even niet". pyfunda maakt
# van élke status behalve 200 een LookupError; zonder dit onderscheid lijkt een
# blokkade halverwege de run op een handvol verkochte woningen.
GEWEIGERD = {401, 403, 429}
NIET_GEVONDEN = {404, 410}


class Funda(_Funda):
    """Patch voor pyfunda v2.9.0 (gepind, zie CLAUDE.md).

    Funda migreerde op 2 juli 2026 hun search-template server-side van
    "search_result_20250805" naar "search_result_20260227". pyfunda v2.9.0
    stuurt nog de oude, verouderde id mee: de API antwoordt dan met HTTP 200
    maar een error per deel-query, wat v2.9.0 stil als "0 resultaten"
    interpreteert (geen exception, geen foutmelding - vandaar dat dit
    onopgemerkt bleef). Pas is er in pyfunda v3.1.2, maar v3 is een
    incompatibele dataclass-rewrite. Daarom hier alleen de template-id
    patchen in plaats van te upgraden.

    Daarnaast, los van de template:
    - **Eerlijke client.** pyfunda doet zich voor als funda's Android-app: de
      TLS-vingerafdruk (JA3) van de echte Dart/Flutter-app, `user-agent: Dart/3.9`,
      `x-funda-app-platform: android` en datadog-traceheaders, en wisselt bij een
      weigering stil naar een volgend profiel uit `FINGERPRINT_POOL` (pyfunda
      noemt zelf "bot detection" als reden). Dat is botbescherming omzeilen (zie
      CLAUDE.md). Hier gaat elk verzoek via één gewone client: curl zonder
      browser- of app-profiel, met een user-agent die dit project noemt
      (`EERLIJKE_UA`) en zonder app-headers. Er wordt nooit een vingerafdruk
      gezocht of gewisseld.
    - **Statuscodes.** pyfunda geeft bij elke status behalve 200 een
      LookupError. Hier: 401/403/429 wordt `DetailEndpointDicht` (de run stopt
      luid), 404/410 wordt `WoningNietGevonden` (de woning is weg, het endpoint
      werkt). De rest blijft een gewone LookupError.
    - **Tellen.** Hoeveel detail-calls deze run deed, en hoeveel daarvan een
      woning ophaalden die deze run al was opgehaald. Staat aan het eind van de
      run in de log, zodat dubbel werk opvalt.
    """

    _STALE_SEARCH_TEMPLATE_ID = "search_result_20250805"
    _FIXED_SEARCH_TEMPLATE_ID = "search_result_20260227"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.detail_calls = 0
        self.detail_dubbel = 0
        self._opgehaald: set[str] = set()
        self._statussen: list[int] = []
        self._eerlijke_sessie = None

    # -- Transport: één gewone client, geen vingerafdruk ----------------------

    def _ensure_session(self) -> None:
        if self._eerlijke_sessie is None:
            from curl_cffi import requests as curl_requests  # lokaal: tests stubben pyfunda

            # Zonder `impersonate`: gewone curl, geen browser- of app-profiel.
            self._eerlijke_sessie = curl_requests.Session()

    def _find_working_fingerprint(self) -> dict:
        raise RuntimeError("Deze client zoekt geen vingerafdruk: elk verzoek gaat via "
                           "één gewone client (zie de Funda-docstring in funda_zoek.py).")

    def _verzoek(self, methode: str, url: str, *, data=None, json_data=None):
        self._ensure_session()
        headers = {"user-agent": EERLIJKE_UA, "accept": "application/json"}
        kwargs = {"headers": headers, "timeout": self.timeout}
        if json_data is not None:
            kwargs["json"] = json_data
        elif data is not None:
            headers["content-type"] = "application/json"
            kwargs["data"] = data
        resp = self._eerlijke_sessie.request(methode, url, **kwargs)
        self._statussen.append(int(getattr(resp, "status_code", 0) or 0))
        return resp

    def _get(self, url, headers_list):
        # headers_list zijn pyfunda's app-headers; bewust genegeerd.
        return self._verzoek("GET", url)

    def _post(self, url, headers_list, data=None, json_data=None, for_search=False):
        if for_search and data and self._STALE_SEARCH_TEMPLATE_ID in data:
            data = data.replace(self._STALE_SEARCH_TEMPLATE_ID, self._FIXED_SEARCH_TEMPLATE_ID)
        return self._verzoek("POST", url, data=data, json_data=json_data)

    # -- Detail-calls -----------------------------------------------------------

    def _vertaal_fout(self, exc: LookupError, listing_id) -> Exception:
        """pyfunda's LookupError, maar dan naar de status die het endpoint gaf."""
        statussen = list(self._statussen)
        geweigerd = [s for s in statussen if s in GEWEIGERD]
        if geweigerd:
            return DetailEndpointDicht(
                f"status {geweigerd[-1]} voor {listing_id}: het endpoint weigert deze client. "
                "Bewust geen andere client of vingerafdruk geprobeerd (zie CLAUDE.md).")
        storing = [s for s in statussen if s >= 500 or s == 0]
        if any(s in NIET_GEVONDEN for s in statussen) and not storing:
            return WoningNietGevonden(f"Listing {listing_id} niet gevonden (status {statussen})")
        return exc

    def get_listing(self, listing_id):
        self.detail_calls += 1
        self._statussen = []
        try:
            listing = super().get_listing(listing_id)
        except LookupError as exc:
            vertaald = self._vertaal_fout(exc, listing_id)
            if vertaald is exc:
                raise
            raise vertaald from exc
        data = getattr(listing, "data", None) or {}
        sleutel = str(data.get("global_id") or data.get("tiny_id") or listing_id)
        if sleutel in self._opgehaald:
            self.detail_dubbel += 1
        self._opgehaald.add(sleutel)
        return listing


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

# Nafilter op afstand tot de zoekpostcode. Bij de API- en HTML-route deed funda
# dit zelf: de straal ging als zoekparameter mee en werd afgerond op een waarde
# die funda kent (5 km bij een ingestelde 6). Bij de mailroute bepaalt de bewaarde
# zoekopdracht het gebied, en staat die op "heel Den Haag", dan komen Ypenburg,
# Wateringse Veld en Loosduinen binnen zonder dat iets ze tegenhoudt. Die wijken
# staan niet in UITSLUIT_BUURTEN, omdat de straal ze vroeger al wegfilterde.
# Standaard dezelfde afgeronde straal als funda gebruikte, zodat elke bron
# hetzelfde gebied oplevert. Zet `straal_nafilter_km` op 0 om uit te zetten.
STRAAL_NAFILTER_KM = _PERSONAL.get("straal_nafilter_km")

# Woningen zonder vraagprijs ("prijs op aanvraag"). De oude zoek-API liet die
# server-side weg, want ze vallen niet binnen een prijsfilter. De sitemaproute
# liet ze door (onbekend = doorlaten), en zo kwam op 6 nov 2026 een appartement
# van 145 m2 in Belgisch Park in het rapport (run 42290940091). Standaard dus
# weer weg; met `prijs_onbekend_tonen: true` komen ze terug, onderaan en met
# "PRIJS ONBEKEND".
PRIJS_ONBEKEND_TONEN = bool(_PERSONAL.get("prijs_onbekend_tonen", False))

# Pool: eerder getoonde woningen die elke run opnieuw gecontroleerd worden, zodat
# ze in het rapport blijven zolang ze te koop staan. Zie controleer_pool().
POOL_DAGEN = int(_PERSONAL.get("pool_dagen", 120))
POOL_MAX = int(_PERSONAL.get("pool_max", 150))

# Hoe ver de mailroute terugkijkt. Was 3 dagen: dan gingen woningen verloren
# zodra de run een paar dagen stuk was. De detail-calls zijn per run gecacht en
# oude woningen vallen vanzelf af op beschikbaarheid, dus ruim is goedkoop.
MAIL_DAGEN = int(_PERSONAL.get("mail_dagen_terug", 14))

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
    "Rivierenbuurt",  # Noord + Zuid: veel huur/belegging, hoge criminaliteit/overlast, grenst aan Schilderswijk/Laak
    "Laakhaven",  # Laakhaven-West/-Oost: bedrijvigheid/studentenbouw, grenst aan Laakkwartier/Schilderswijk
    "Duindorp",  # afgesproken 23 jul 2026 (PR #8, nooit gemerged): niet top gevonden, o.a. Tholensestraat
]

# Steden die je niet wil zien (substring match op city-veld, case-insensitive).
# Funda gebruikt soms varianten als "Rijswijk (ZH)", dus geen exact match.
UITSLUIT_STEDEN = ["Rijswijk", "Leidschendam"]

# Plaatsen die je WEL wil, ook als ze in een uitgesloten gemeente liggen. Deze
# gaan voor op UITSLUIT_STEDEN.
#
# Waarom dit nodig is: Voorburg valt onder de gemeente Leidschendam-Voorburg.
# Zonder deze uitzondering matcht de substring "Leidschendam" op
# "Leidschendam-Voorburg" en valt al het Voorburg-aanbod stil weg - geen
# foutmelding, gewoon niets in het rapport. Precies de faalmodus die je niet ziet.
WENS_STEDEN = ["Voorburg"]

# Geeft funda alleen de gemeentenaam terug, dan is niet te zien of de woning in
# Voorburg of in Leidschendam staat. Die tonen we met een waarschuwing in plaats
# van ze weg te gooien: stil verliezen is erger dan een keer te veel laten zien.
TWIJFEL_STEDEN_PATROON = [
    ("leidschendam-voorburg", "gemeente Leidschendam-Voorburg: kan Leidschendam zijn"),
    ("leidschendam voorburg", "gemeente Leidschendam-Voorburg: kan Leidschendam zijn"),
]

# Woningtypes die geen appartement zijn. Substring-match, case-insensitive, op
# het veld `house_type` uit de detail-API (funda's `soortwoning`).
#
# Waarom een afwijslijst en geen toestaanlijst: funda gebruikt voor appartementen
# allerlei subtypes (bovenwoning, portiekflat, maisonnette, galerijflat,
# penthouse, studio, benedenwoning). Een lijst van toegestane woorden zou die
# stuk voor stuk afwijzen zodra er eentje mist. Nu geldt: onbekend type =
# doorlaten. Stil verliezen is erger dan een keer te veel laten zien.
#
# Dit nafilter bestaat omdat PRIJS_MIN, PRIJS_MAX, M2_MIN en object_type alléén
# zoekparameters zijn. Bij de mailroute bepaalt de bewaarde zoekopdracht wat er
# binnenkomt, en staat daar "Woonhuis" aangevinkt, dan belandt dat ongefilterd
# in het rapport - de begane-grond-filter grijpt er niet op, want die kijkt naar
# omschrijvingen als "appartement op de begane grond".
GEEN_APPARTEMENT = [
    "eengezinswoning", "woonhuis", "herenhuis", "tussenwoning", "hoekwoning",
    "eindwoning", "rijtjeshuis", "vrijstaand", "geschakeld", "bungalow",
    "villa", "landhuis", "grachtenpand", "woonboerderij", "dijkwoning",
    "2-onder-1-kap", "twee-onder-een-kap",
]

# Slug-voorvoegsels in de woning-URL die op een huis wijzen. Bewust alleen het
# eerste segment van de slug: een straatnaam als "Huisduinenstraat" mag niet
# meetellen.
HUIS_SLUGS = {"huis", "woonhuis"}

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
# Worden afgewezen: liever hoger wonen, voor rust en minder inbraakrisico.
BG_WOORDEN = [
    "woning op de begane grond", "appartement op de begane grond",
    "gelegen op de begane grond", "ligt op de begane grond",
    "begane-grondappartement", "beganegrondappartement",
    "gelijkvloers appartement", "parterre appartement", "parterrewoning",
    "souterrainwoning", "souterrainappartement",
    "benedenwoning", "benedenappartement",
]

# Straat-segmenten: voor straten waarvan slechts een deel acceptabel is.
# Sleutel = lowercased straatnaam, value = (min_huisnummer, max_huisnummer of None, stad).
STRAAT_SEGMENTEN = {
    "beeklaan": (320, None, "Den Haag"),  # alleen nummers >= 320 (Bomenbuurt/Duinoord-kant)
}

# State naast het script.
STATE_FILE = Path(__file__).parent / "funda_seen_ids.json"
LOG_FILE = Path(__file__).parent / "funda_log.txt"
BLACKLIST_FILE = Path(__file__).parent / "funda_blacklist.json"
# Prijs- en datumgeschiedenis die we zelf bijhouden. Onafhankelijk van wat
# Funda wel/niet teruggeeft, dus betrouwbaar voor prijsdaling-detectie.
TRACKING_FILE = Path(__file__).parent / "funda_tracking.json"
SUMMARY_FILE = Path(__file__).parent / "funda_run_summary.json"
# Coördinaten van de zoekpostcode, voor het afstandsfilter. In de Actions-cache,
# niet in de repo: een postcode is privé.
THUIS_CACHE = Path(__file__).parent / "funda_thuis_coords.json"


def _int_instelling(omgeving: str, sleutel: str, standaard: int) -> int:
    """Geheel getal uit de omgeving, dan de config, dan de standaard.

    Een lege waarde telt als niet gezet: de workflow geeft een lege
    workflow_dispatch-input door als lege omgevingsvariabele.
    """
    for bron, waarde in ((omgeving, os.environ.get(omgeving)), (sleutel, _PERSONAL.get(sleutel))):
        if waarde is None or not str(waarde).strip():
            continue
        try:
            return int(str(waarde).strip())
        except ValueError:
            print(f"WAARSCHUWING: {bron}={waarde!r} is geen geheel getal; genegeerd.")
    return standaard


# Sitemaproute (funda_sitemap_zoek.py). De sitemaps kennen geen straal, alleen
# URL's per plaats; de stad-, buurt- en afstandsfilters doen de rest. Steden
# zoals funda ze in de URL zet; "Den Haag" wordt vanzelf "den-haag"
# (funda_sitemap_zoek.stad_slug). Een stad zonder één URL laat de run falen.
SITEMAP_STEDEN = _PERSONAL.get("sitemap_steden") or ["den-haag", "voorburg"]
# Verkennende detail-calls per run (nieuwste lastmod eerst) voor woningen die
# nieuw zijn of een andere lastmod hebben. De eerste runs is er een achterstand
# (het hele bestaande aanbod, ~3.100 kandidaten); die loopt zo over een paar
# dagen leeg in plaats van in één run duizenden calls te doen. Eenmalig
# versnellen kan met de workflow-input sitemap_max_verkennen, tot het plafond.
# Plafond: besluit van 6 nov 2026 (CLAUDE.md, "robots.txt van de API-hosts"):
# opstart hooguit 600 per run, ook niet hoger via de omgeving of de config.
SITEMAP_MAX_VERKENNEN_PLAFOND = 600


def _begrens_verkennen(n: int) -> int:
    if n > SITEMAP_MAX_VERKENNEN_PLAFOND:
        print(f"WAARSCHUWING: sitemap_max_verkennen={n} is hoger dan het plafond "
              f"van {SITEMAP_MAX_VERKENNEN_PLAFOND}; dat plafond wordt gebruikt.")
        return SITEMAP_MAX_VERKENNEN_PLAFOND
    return n


SITEMAP_MAX_VERKENNEN = _begrens_verkennen(
    _int_instelling("FUNDA_SITEMAP_MAX_VERKENNEN", "sitemap_max_verkennen", 200))
# Per woning lastmod en filtervelden, plus de laatste index en kandidatenlijst.
# Hoort in de Actions-cache (en in .gitignore).
SITEMAP_CACHE_FILE = Path(__file__).parent / "funda_sitemap_cache.json"


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
    """Logregel naar stdout en funda_log.txt. Op Actions via log_tekst(): geen woning-URL's of -nummers."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] {log_tekst(msg)}"
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
        # None bij "prijs op aanvraag"; de pushmelding toont dan geen "€ 0".
        prijs = None if prijs_onbekend(d) else int(d["price"])
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


def _poortwoord(b: dict) -> str | None:
    """'Past', 'Krap', 'Past niet' of 'Prijs onbekend' uit een beoordeling, zonder bedragen."""
    from funda_beoordeling import POORT_NAAM
    woord = POORT_NAAM.get(b.get("poort"))
    if not woord and isinstance(b.get("status_kort"), str):
        woord = b["status_kort"].split(" · ")[0].strip()
    if not woord or "€" in woord:
        return None
    return woord


def vul_summary_aan(woningen: list[dict]) -> int:
    """Na het rapport: poortwoord en score per nieuwe woning in funda_run_summary.json.

    schrijf_run_summary() draait vóór het rapport (de push-preview hangt eraan); het rapport zet
    daarna d["_beoordeling"] op dezelfde dicts. Hier komen `status_push` (alleen het poortwoord:
    Past, Krap, Past niet of Prijs onbekend) en `score` erbij, voor scripts/send_web_push.cjs.
    Bewust niet de statusregel (status_kort): die noemt bedragen die van het profiel afhangen
    ('€ 65 onder de norm (bruto)' geeft met de publieke code het bruto inkomen terug, '€ 26.610
    eigen geld te weinig' het eigen geld), en een melding staat leesbaar op het vergrendelscherm.
    De bedragen blijven in het versleutelde rapport. Zonder beoordeling of zonder bestand verandert
    er niets. Geeft het aantal aangevulde woningen.

    De nieuwe woningen komen daarna in de volgorde van "Aanbevolen" (funda_beoordeling.sorteer:
    geen vraagprijs, poort, twijfel, -score), want de push toont de eerste drie. Woningen zonder
    beoordeling gaan achteraan, in hun oude volgorde.
    """
    from funda_beoordeling import sorteer_sleutel
    beoordeling, volgorde = {}, {}
    for d in woningen:
        b = d.get("_beoordeling")
        if isinstance(b, dict) and _poortwoord(b):
            lid = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url") or "")
            beoordeling[lid] = b
            # Zelfde rij-vorm als funda_rapport.bouw_rij, zodat de sleutel gelijk is aan die van het rapport.
            volgorde[lid] = sorteer_sleutel({"beoordeling": b, "prijs_onbekend": prijs_onbekend(d)})
    if not beoordeling:
        return 0
    try:
        payload = json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for item in payload.get("nieuw") or []:
        b = beoordeling.get(str(item.get("id") or ""))
        if not b:
            continue
        item.pop("status", None)   # oude vorm met de hele statusregel
        item["status_push"] = _poortwoord(b)
        if isinstance(b.get("score"), (int, float)) and not isinstance(b.get("score"), bool):
            item["score"] = round(float(b["score"]), 1)
        n += 1
    if n:
        def plek(item: dict) -> tuple:
            lid = str(item.get("id") or "")
            return (0, volgorde[lid]) if lid in volgorde else (1,)   # zonder beoordeling achteraan (stabiel)

        payload["nieuw"].sort(key=plek)
        SUMMARY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return n


def twijfel_redenen(d: dict) -> list[str]:
    """Korte zinnen voor het rapport (d["_twijfel"]): de woning blijft staan, onderaan in zijn groep.

    Het rapport zet er "Onderaan gezet." achter; het model kopieert de lijsten hier niet. Twijfel
    door een zwakke Leefbaarometer komt uit de verrijking, niet uit deze functie."""
    uit = []
    buurt = is_twijfelbuurt((d.get("neighbourhood") or "").strip())
    if buurt:
        uit.append(f"Twijfelbuurt {buurt} (jouw lijst).")
    reden = is_twijfelstad((d.get("city") or "").strip())
    if reden:
        uit.append("Stad onduidelijk: Leidschendam of Voorburg? Funda geeft alleen de gemeente."
                   if "leidschendam" in reden.lower() else f"Stad onduidelijk: {reden}.")
    return uit


def is_uitgesloten_buurt(buurt: str) -> str | None:
    s = buurt.lower()
    for u in UITSLUIT_BUURTEN:
        if u.lower() in s:
            return u
    return None


def is_uitgesloten_stad(stad: str) -> str | None:
    """Moet deze stad weg? WENS_STEDEN gaat voor op UITSLUIT_STEDEN.

    Die voorrang is er voor gemeentenamen die een gewenste plaats bevatten,
    zoals Leidschendam-Voorburg; zie de toelichting bij WENS_STEDEN.
    """
    s = stad.lower()
    if any(w.lower() in s for w in WENS_STEDEN):
        return None
    for u in UITSLUIT_STEDEN:
        if u.lower() in s:
            return u
    return None


def is_twijfelstad(stad: str) -> str | None:
    """Dubbelzinnige gemeentenaam: tonen, maar met een waarschuwing erbij."""
    s = stad.lower()
    for patroon, reden in TWIJFEL_STEDEN_PATROON:
        if patroon in s:
            return reden
    return None


def is_geen_appartement(d: dict) -> str | None:
    """Is dit geen appartement? Geeft de reden terug, of None bij doorlaten.

    Kijkt eerst naar `house_type` (het betrouwbare veld uit de detail-API) en
    anders naar het type-voorvoegsel in de woning-URL. Levert geen van beide
    iets op, dan laten we de woning door: onbekend is geen reden om weg te
    gooien.
    """
    soort = str(d.get("house_type") or "").lower()
    for woord in GEEN_APPARTEMENT:
        if woord in soort:
            return d.get("house_type") or woord

    url = str(d.get("detail_url") or "")
    delen = [deel for deel in url.split("/") if deel]
    if len(delen) >= 2:
        slug_type = delen[-2].split("-")[0].lower()
        if slug_type in HUIS_SLUGS:
            return slug_type
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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


_THUIS: dict[str, tuple[float, float] | None] = {}


def thuis_coords() -> tuple[float, float] | None:
    """Coördinaten van de zoekpostcode, voor het afstandsfilter.

    Volgorde: `thuis_coords` uit de config, dan funda_thuis_coords.json
    ({postcode: [lat, lon]}), dan één poging via PDOK (CLAUDE.md, "Geocoding en routes");
    een gevonden punt komt voorgoed in dat bestand. Staat het afstandsfilter uit,
    dan geen verzoek. Lukt het niet, dan een ::warning:: en None: het
    afstandsfilter slaat dan over in plaats van alles weg te gooien. Eén keer per
    run opgezocht.
    """
    if "v" in _THUIS:
        return _THUIS["v"]
    resultaat = coord_paar(_PERSONAL.get("thuis_coords"))
    if resultaat is None:
        try:
            cache = json.loads(THUIS_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        resultaat = coord_paar(cache.get(POSTCODE)) if isinstance(cache, dict) else None
        if resultaat is None and nafilter_straal_km() is not None:
            try:
                from funda_rapport import geocodeer_postcode
                resultaat, reden = geocodeer_postcode(POSTCODE)
            except Exception as exc:
                resultaat, reden = None, f"interne fout ({type(exc).__name__})"
            if resultaat:
                try:
                    THUIS_CACHE.write_text(json.dumps({POSTCODE: list(resultaat)}), encoding="utf-8")
                except Exception as exc:
                    print(f"Thuiscoördinaten niet bewaard ({type(exc).__name__}).")
            else:
                # Zonder postcode in de melding: de Actions-log is publiek.
                print(log_tekst(f"::warning::Afstandsfilter: zoekpostcode niet te geocoderen via PDOK ({reden}); "
                                "deze run zonder afstandsfilter. Zet thuis_coords in de config om dit over te slaan."))
    _THUIS["v"] = resultaat
    return resultaat


def nafilter_straal_km() -> float | None:
    """Straal voor het afstandsfilter, of None als het uit staat.

    Standaard de straal die funda zelf gebruikte: de ingestelde waarde afgerond op
    wat funda kent (1, 2, 5, 10, ...). Zo levert de mailroute hetzelfde gebied op
    als de oude API- en HTML-route.
    """
    if STRAAL_NAFILTER_KM is not None:
        try:
            waarde = float(STRAAL_NAFILTER_KM)
        except (TypeError, ValueError):
            return None
        return waarde or None
    if not RADIUS_KM:
        return None
    from funda_html_zoek import snap_straal
    return float(snap_straal(RADIUS_KM))


def _als_int(waarde) -> int | None:
    try:
        return int(waarde) if waarde not in (None, "") else None
    except (TypeError, ValueError):
        return None


def buiten_zoekcriteria(d: dict, thuis: tuple[float, float] | None = None,
                        straal_km: float | None = None) -> str | None:
    """Valt deze woning buiten prijs, oppervlak of straal? Geeft de reden.

    Bij de API- en HTML-route deed funda dit al in de zoekopdracht. Bij de
    mailroute en de pool niet: daar bepaalt de bewaarde zoekopdracht of de
    tracking wat binnenkomt. Dit maakt alle bronnen gelijk. Ontbreekt een
    gegeven, dan laten we de woning door: onbekend is geen reden om weg te gooien.
    Uitzondering: geen vraagprijs. Die viel bij de oude zoekopdracht altijd buiten
    het prijsfilter, dus hier ook, tenzij `prijs_onbekend_tonen` aan staat.
    """
    prijs = _als_int(d.get("price"))
    if not prijs and not PRIJS_ONBEKEND_TONEN:
        return "geen vraagprijs (prijs op aanvraag)"
    if prijs:
        if PRIJS_MAX and prijs > PRIJS_MAX:
            return f"prijs € {prijs:,} boven maximum € {PRIJS_MAX:,}"
        if PRIJS_MIN and prijs < PRIJS_MIN:
            return f"prijs € {prijs:,} onder minimum € {PRIJS_MIN:,}"
    m2 = _als_int(d.get("living_area"))
    if m2 and M2_MIN and m2 < M2_MIN:
        return f"{m2} m2 onder minimum {M2_MIN} m2"
    lat, lon = d.get("latitude"), d.get("longitude")
    if thuis and straal_km and lat and lon:
        try:
            km = _haversine_km(thuis[0], thuis[1], float(lat), float(lon))
        except (TypeError, ValueError):
            return None
        if km > straal_km:
            return f"{km:.1f} km van de zoekpostcode (max {straal_km:g} km)"
    return None


# Waarden van het kenmerk "Status" die betekenen dat de woning nu niet te koop
# staat. De oude zoekopdracht vroeg alleen availability=available op, dus deze
# kwamen er toen ook niet in.
NIET_BESCHIKBAAR_TIJDELIJK = ("onder bod", "onder optie", "in onderhandeling")
NIET_BESCHIKBAAR_DEFINITIEF = ("verkocht", "ingetrokken")


def beschikbaarheid(d: dict) -> tuple[str, str | None]:
    """('ja' | 'tijdelijk' | 'weg', status-tekst) voor een woning uit de detail-API.

    `status` komt van pyfunda (IsSoldOrRented). Het kenmerk "Status" uit de
    Overdracht-sectie is fijner (onder bod, verkocht onder voorbehoud), maar die
    vocabulaire is niet gemeten; daarom alleen bekende woorden, en de run logt
    welke waarden voorkwamen. Onbekend = beschikbaar.
    """
    kenmerken = d.get("characteristics") or {}
    status_tekst = str(kenmerken.get("Status") or "").strip()
    s = status_tekst.lower()
    if str(d.get("status") or "").lower() == "sold":
        return "weg", status_tekst or "sold"
    if any(w in s for w in NIET_BESCHIKBAAR_DEFINITIEF):
        return "weg", status_tekst
    if any(w in s for w in NIET_BESCHIKBAAR_TIJDELIJK):
        return "tijdelijk", status_tekst
    return "ja", status_tekst or None


class DetailCacheZoeker:
    """Onthoudt detail-calls binnen één run.

    Dezelfde woning wordt anders tot drie keer opgehaald: in de pool-controle, in
    de detail-check en in het rapport. Alles behalve get_listing gaat ongewijzigd
    door naar de onderliggende zoeker.
    """

    def __init__(self, zoeker: object) -> None:
        self._zoeker = zoeker
        self._cache: dict[str, object] = {}

    def get_listing(self, listing_id):
        sleutel = str(listing_id)
        if sleutel in self._cache:
            return self._cache[sleutel]
        listing = self._zoeker.get_listing(listing_id)
        self.onthoud(listing, sleutel)
        return listing

    def onthoud(self, listing: object, *extra_sleutels: str) -> None:
        data = getattr(listing, "data", None) or {}
        for veld in ("global_id", "listing_id", "tiny_id"):
            if data.get(veld):
                self._cache[str(data[veld])] = listing
        for sleutel in extra_sleutels:
            if sleutel:
                self._cache[sleutel] = listing

    def __getattr__(self, naam: str):
        if naam.startswith("_"):
            raise AttributeError(naam)
        return getattr(self._zoeker, naam)


class PoolResultaat:
    """Zelfde vorm als pyfunda's Listing: een `.data`-dict."""

    __slots__ = ("data",)

    def __init__(self, data: dict) -> None:
        self.data = data


def _pool_ident(sleutel: str, rec: dict):
    """Waarmee get_listing deze woning kan ophalen, of None."""
    url = rec.get("url") or ""
    if url:
        return url if url.startswith("http") else f"https://www.funda.nl{url}"
    if sleutel.isdigit():
        return int(sleutel)
    if sleutel.startswith("/detail/"):
        return f"https://www.funda.nl{sleutel}"
    return None


def _pool_eindcheck(op_rij: int) -> None:
    """Eindigde de run (zoeker plus pool) met mislukte calls? Dan stoppen.

    Dan is niet te zeggen of het endpoint nog werkt: misschien ging het net
    dicht, en dan missen de laatst opgehaalde woningen in het rapport. Liever
    geen rapport dan een half rapport, en zeker niets als weg markeren. Een
    nette 404 telt hier niet mee (zie DICHT_NA).
    """
    if op_rij:
        raise DetailEndpointDicht(
            f"de laatste {op_rij} detail-call(s) van de run mislukten; niet te zeggen of "
            f"het detail-endpoint nog werkt")


def controleer_pool(zoeker: DetailCacheZoeker, tracking: dict, al_binnen: set[str],
                    *, dagen: int, maximum: int, pauze: float = 0.4,
                    sitemap: object | None = None) -> list[PoolResultaat]:
    """Eerder getoonde woningen opnieuw ophalen en teruggeven als ze nog te koop staan.

    Waarom: de mailroute ziet alleen wat funda de laatste dagen mailde. Zonder dit
    verdwijnt een woning uit het rapport zodra de mail ouder is dan het
    terugkijkvenster, ook als hij gewoon nog te koop staat. Vroeger hield de
    zoekopdracht zelf die woningen in beeld; nu doet de tracking dat.

    Een woning die verkocht is, wordt in de tracking gemarkeerd en daarna niet
    meer opgevraagd. Onder bod of onder optie: deze run niet tonen, wel blijven
    volgen. Drie keer niet op te halen: als weg markeren.

    Met de sitemaproute (`sitemap` is dan de SitemapZoeker van deze run) geldt
    één principe: **de sitemap bepaalt wat de pool níet hoeft op te halen, het
    detail-endpoint bepaalt wat weg is.** Nooit twee detail-calls voor dezelfde
    woning in één run. Per getrackte woning (SitemapZoeker.pool_oordeel):
    - opgehaald door de zoeker: oordelen op dat antwoord, zonder nieuwe call;
    - door de zoeker geprobeerd en mislukt: overslaan, geen tweede poging;
    - op de cache overgeslagen (lastmod gelijk, en buiten de doelmarkt of door
      een filter afgewezen): overslaan, want sinds de vorige call is er niets
      veranderd dat het oordeel kan omdraaien;
    - in de achterstand (staat in de sitemap, nog niet verkend): zelf ophalen en
      in de sitemapcache vastleggen, zodat de zoeker hem niet nog eens verkent;
    - niet meer in de sitemap: één controle-call. Verkocht, ingetrokken of niet
      op te halen (terwijl het endpoint deze run wél werkte) = meteen weg, en dan
      nooit meer opgevraagd. Nog te koop = gewoon tonen: de sitemap loopt een dag
      achter en of "onder bod" erin blijft is niet gemeten, dus ontbreken in de
      sitemap is alleen een reden om te controleren, niet om weg te gooien;
    - onbekend (geen URL, of een stad buiten de sitemapsteden): zoals zonder
      sitemap.

    Werkt het endpoint deze run? Bewijs is een geslaagde call, van de pool zelf
    óf van de sitemapzoeker, of een nette 404 (`WoningNietGevonden`: ook dat is
    een antwoord). Een 404 telt daarom niet als storing. Weigert het endpoint
    (401/403/429) of mislukken DICHT_NA calls op rij - de teller loopt door vanaf
    de laatste calls van de sitemapzoeker - dan `DetailEndpointDicht`: main()
    stopt met exit 2 in plaats van een rapport zonder deze woningen te schrijven.
    Eindigt de run met zo'n mislukte call (ook als dat er minder dan DICHT_NA
    zijn), dan ook: misschien ging het endpoint net dicht.
    """
    # Bewijs dat het endpoint deze run werkt: geslaagde calls van de sitemapzoeker
    # tellen mee. Anders liep een run waarin de pool alleen een ingetrokken woning
    # (404) controleerde vast: nooit als weg gemarkeerd, elke run een call.
    st = (getattr(sitemap, "statistiek", None) or {}) if sitemap is not None else {}
    geslaagd = int(st.get("detail_geslaagd") or 0)
    op_rij = int(st.get("detail_op_rij_mislukt") or 0)   # loopt door vanaf de zoeker
    if dagen <= 0 or maximum <= 0:
        _pool_eindcheck(op_rij)
        return []
    vandaag = datetime.now().strftime("%Y-%m-%d")
    grens = datetime.now().timestamp() - dagen * 86400

    oordelen: Counter[str] = Counter()
    kandidaten = []
    for sleutel, rec in tracking.items():
        if sleutel in al_binnen or not isinstance(rec, dict) or rec.get("weg"):
            continue
        try:
            laatst = datetime.strptime(rec.get("last_seen") or "", "%Y-%m-%d").timestamp()
        except ValueError:
            continue
        if laatst < grens:
            continue
        ident = _pool_ident(sleutel, rec)
        if ident is None:
            continue
        oordeel = sitemap.pool_oordeel(rec.get("url") or ident) if sitemap is not None else None
        if oordeel:
            oordelen[oordeel] += 1
        if oordeel in (SITEMAP_MISLUKT, SITEMAP_OVERGESLAGEN):
            continue
        kandidaten.append((rec.get("last_seen") or "", sleutel, rec, ident, oordeel))
    kandidaten.sort(key=lambda k: (k[0], k[1]), reverse=True)
    if len(kandidaten) > maximum:
        log(f"Pool: {len(kandidaten)} kandidaten, alleen de {maximum} recentste gecontroleerd.")
        kandidaten = kandidaten[:maximum]

    resultaten: list[PoolResultaat] = []
    teller: Counter[str] = Counter()
    statussen: Counter[str] = Counter()
    controle: Counter[str] = Counter()   # uitkomst voor woningen die niet meer in de sitemap staan
    mislukt: list[dict] = []
    mislukt_buiten_sitemap: list[dict] = []
    antwoord_404 = False
    vastgelegd = 0
    for _laatst, sleutel, rec, ident, oordeel in kandidaten:
        # Al opgehaald door de sitemapzoeker: get_listing komt uit diens geheugen.
        uit_zoeker = oordeel == SITEMAP_OPGEHAALD
        try:
            listing = zoeker.get_listing(ident)
        except DetailEndpointDicht:
            raise
        except Exception as exc:
            teller["fout"] += 1
            if oordeel == NIET_IN_SITEMAP:
                controle["fout"] += 1
                mislukt_buiten_sitemap.append(rec)
            else:
                mislukt.append(rec)
            if isinstance(exc, WoningNietGevonden):
                antwoord_404 = True   # een antwoord, geen storing
                op_rij = 0            # en dus het einde van een reeks storingen
                continue
            op_rij += 1
            if op_rij >= DICHT_NA:
                raise DetailEndpointDicht(
                    f"Pool: {op_rij} detail-calls op rij mislukt (laatste: "
                    f"{type(exc).__name__}: {exc}); het detail-endpoint lijkt dicht.") from exc
            continue
        finally:
            if not uit_zoeker:
                time.sleep(pauze)
        if not uit_zoeker:
            geslaagd += 1
            op_rij = 0
        rec.pop("pool_fout", None)
        data = dict(getattr(listing, "data", None) or {})
        if not data:
            teller["leeg"] += 1
            continue
        zoeker.onthoud(listing, sleutel)
        if oordeel == SITEMAP_ACHTERSTAND and sitemap is not None and sitemap.neem_op(listing):
            vastgelegd += 1
        if any(str(data.get(v)) in al_binnen for v in ("global_id", "tiny_id") if data.get(v)):
            continue  # zit al in deze run, onder een andere sleutel
        oordeel_beschikbaar, status_tekst = beschikbaarheid(data)
        statussen[status_tekst or "(geen)"] += 1
        if oordeel == NIET_IN_SITEMAP:
            controle[oordeel_beschikbaar] += 1
        if oordeel_beschikbaar == "weg":
            rec["weg"] = {"datum": vandaag, "reden": status_tekst or "verkocht"}
            teller["weg"] += 1
            continue
        if oordeel_beschikbaar == "tijdelijk":
            teller["tijdelijk"] += 1
            continue
        data.setdefault("detail_url", data.get("url") or rec.get("url") or "")
        data["_bron"] = "pool"
        resultaten.append(PoolResultaat(data))
        teller["beschikbaar"] += 1

    _pool_eindcheck(op_rij)
    # Een mislukte call telt alleen mee als het endpoint deze run wél werkte.
    # Anders zou een storing van drie runs alle bekende woningen als weg
    # markeren, en die komen dan nooit meer terug in de pool.
    if geslaagd or antwoord_404:
        for rec in mislukt:
            rec["pool_fout"] = int(rec.get("pool_fout") or 0) + 1
            if rec["pool_fout"] >= 3:
                rec["weg"] = {"datum": vandaag, "reden": "3x niet op te halen"}
                teller["weg"] += 1
        # Niet in de sitemap én niet op te halen: twee onafhankelijke signalen,
        # dus meteen weg in plaats van na drie runs.
        for rec in mislukt_buiten_sitemap:
            rec["weg"] = {"datum": vandaag, "reden": "niet in de sitemap en niet op te halen"}
            teller["weg"] += 1
    if vastgelegd:
        sitemap.bewaar_cache()

    if kandidaten:
        log(f"Pool: {len(kandidaten)} bekende woning(en) gecontroleerd: "
            f"{teller['beschikbaar']} nog te koop, {teller['tijdelijk']} onder bod/optie, "
            f"{teller['weg']} weg, {teller['fout']} fout.")
        # Alleen de statuswaarden, geen adressen: zo is te zien of het filter de
        # woorden kent die funda gebruikt.
        log("Pool: statuswaarden: " + ", ".join(f"{s} ({n}x)" for s, n in statussen.most_common()))
    if sitemap is not None:
        # Alleen getallen, ook als alles 0 is: laat zien dat de pool geen dubbel
        # werk doet, en hoeveel getrackte woningen uit de sitemap verdwijnen
        # (meting eerste week). Getrackte woningen die al in deze run zaten, komen
        # uit de sitemap en tellen hier dus niet mee.
        log(f"Pool en sitemap: {sum(oordelen.values())} getrackte woning(en) buiten deze run "
            f"(binnen {dagen} dagen gezien); "
            f"{oordelen[SITEMAP_OPGEHAALD]} al opgehaald door de sitemapzoeker (geen call), "
            f"{oordelen[SITEMAP_MISLUKT]} daar mislukt (geen tweede call), "
            f"{oordelen[SITEMAP_OVERGESLAGEN]} op cache overgeslagen, "
            f"{oordelen[SITEMAP_ACHTERSTAND]} in de achterstand ({vastgelegd} vastgelegd in de cache), "
            f"{oordelen[NIET_IN_SITEMAP]} niet meer in de sitemap, "
            f"{oordelen['onbekend']} onbekend.")
        if oordelen[NIET_IN_SITEMAP]:
            log(f"Pool: {oordelen[NIET_IN_SITEMAP]} getrackte woning(en) niet meer in de sitemap; "
                f"controle-call: {controle['weg']} weg, {controle['ja']} nog te koop, "
                f"{controle['tijdelijk']} onder bod/optie, {controle['fout']} niet op te halen.")
    return resultaten


def auto_push(folder: Path | None = None) -> None:
    """Add, commit en push docs/ naar GitHub. Skip als geen wijzigingen of bij --no-push.

    Alleen docs/: de check en de commit krijgen allebei het pad mee. Eerder nam
    de commit alles mee wat gestaged stond. Een werkkopie waarvan de branch
    onder de checkout was verschoven (een tweede worktree op dezelfde branch
    had gecommit) had een gestagede terugdraaiing van de code, en een lokale
    run zette die als "auto: rapport" op de branch. Andere gestagede
    wijzigingen blijven nu gewoon gestaged staan.
    """
    if "--no-push" in sys.argv:
        log("Auto-push overgeslagen (--no-push).")
        return
    folder = folder or Path(__file__).parent
    docs_dir = folder / "docs"
    if not docs_dir.exists():
        log("Geen docs/ folder, push overgeslagen.")
        return
    try:
        subprocess.run(["git", "-C", str(folder), "add", "docs/"], capture_output=True, timeout=10)
        diff = subprocess.run(
            ["git", "-C", str(folder), "diff", "--cached", "--quiet", "--", "docs/"],
            capture_output=True, timeout=10,
        )
        if diff.returncode == 0:
            log("Geen docs-wijzigingen, push overgeslagen.")
            return
        msg = f"auto: rapport {datetime.now():%Y-%m-%d %H:%M}"
        commit = subprocess.run(
            ["git", "-C", str(folder), "commit", "-m", msg, "--", "docs/"],
            capture_output=True, timeout=10,
        )
        if commit.returncode != 0:
            err = (commit.stderr or commit.stdout).decode("utf-8", errors="ignore")[:300]
            log(f"Commit fout, push overgeslagen: {err}")
            return
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


def prijs_onbekend(d: dict) -> bool:
    """Geen vraagprijs ("prijs op aanvraag")? Dan price None of 0.

    De oude zoek-API liet die server-side weg; de sitemap- en mailroute laten ze
    bewust door (onbekend = doorlaten). Tonen mag, maar nooit als prijs 0: dat gaf
    in het rapport budget "PAST", de hoogste score en een bovenste plek.
    """
    prijs = d.get("price")
    return not (isinstance(prijs, (int, float)) and prijs > 0)


def update_tracking(tracking: dict, sleutel: str, prijs: int, pub_datum: str | None) -> dict:
    """Werk tracking bij voor een woning. Geeft afgeleide flags terug.

    Een onbekende prijs (0) komt niet in de prijsreeks: anders lijkt een woning
    die naar "prijs op aanvraag" gaat een prijsdaling van 100%.
    """
    vandaag = datetime.now().strftime("%Y-%m-%d")
    rec = tracking.get(sleutel)
    if rec is None:
        rec = {"first_seen": vandaag, "last_seen": vandaag,
               "prices": [[vandaag, prijs]] if prijs else [], "pub_datum": pub_datum}
        tracking[sleutel] = rec
    else:
        rec["last_seen"] = vandaag
        if pub_datum and not rec.get("pub_datum"):
            rec["pub_datum"] = pub_datum
        prijzen = rec.get("prices") or []
        if prijs and (not prijzen or prijzen[-1][1] != prijs):
            prijzen.append([vandaag, prijs])
        rec["prices"] = prijzen

    # Afgeleide flags.
    prijzen = [p for p in (rec.get("prices") or []) if p[1]] or [[vandaag, prijs]]
    eerste_prijs = prijzen[0][1]
    top_prijs = max(p for _, p in prijzen)
    gedaald = bool(prijs) and prijs < top_prijs
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


# === Zoekmethode kiezen ===

def _mag_detail_call_overslaan(kaart: dict) -> bool:
    """Voorfilter voor de HTML-zoeker: is een detail-call zinloos?

    Alleen op wat de zoekpagina zelf al prijsgeeft. Scheelt honderden calls per
    run; de gewone filters verderop wijzen deze woningen alsnog af.
    """
    if is_uitgesloten_stad((kaart.get("city") or "").strip()):
        return True
    return is_uitgesloten_straat_nr(kaart) is not None


def _sitemap_overslaan(d: dict) -> bool:
    """Voor de sitemapzoeker: valt een woning (of haar gecachte velden) toch af?

    Dezelfde regels als in main(): woningtype, stad, buurt, straat-segment en
    prijs/m2/straal (`buiten_zoekcriteria`). De zoeker gebruikt dit om afgewezen
    woningen niet elke run opnieuw op te halen; met de coördinaten in de cache
    kost een woning buiten de straal na de eerste keer geen call meer, tot haar
    lastmod verandert. Onbekend = doorlaten: zonder coördinaten (of zonder
    thuiscoördinaten) telt de straal niet.

    Beschikbaarheid hoort hier bewust niet bij: "onder bod" kan terugdraaien, en
    of de lastmod dan verandert is nog niet gemeten. Woningen die verder door
    alle filters komen, worden daarom elke run vers opgehaald.
    """
    return bool(
        is_geen_appartement(d)
        or is_uitgesloten_stad((d.get("city") or "").strip())
        or is_uitgesloten_buurt((d.get("neighbourhood") or "").strip())
        or is_uitgesloten_straat_nr(d)
        or buiten_zoekcriteria(d, thuis_coords(), nafilter_straal_km())
    )


def _woningen_uit_mailbox() -> list[tuple[str, str]]:
    """Woningen uit de funda-mails in de mailbox, zonder dubbelen.

    Alleen bij zoek_methode 'mail'; 'auto' opent de mailbox niet. Geeft een lege
    lijst als er niets te halen is; main() laat de run dan falen op de
    nul-woningen-check in plaats van een leeg rapport te publiceren.
    """
    from funda_mail_bron import woningen_uit_mail
    from funda_mail_ophalen import haal_mail_teksten, mail_config

    config = mail_config(_PERSONAL)
    if not config:
        log("Mailroute: geen mailinstellingen (FUNDA_MAIL_USER en "
            "FUNDA_MAIL_PASSWORD); niets op te halen.")
        return []

    try:
        teksten = haal_mail_teksten(**config, sinds_dagen=MAIL_DAGEN, max_mails=100, log=log)
    except Exception as exc:
        log(f"Mailbox niet te lezen ({type(exc).__name__}: {exc}).")
        # Als de mailroute nodig is, is dit de echte oorzaak van een mislukte run.
        # Zonder deze regel eindigt de log op de 403 van de zoekpagina, en die is
        # al weken bekend en dus niet de reden dat het vandaag stuk is.
        if "AUTHENTICATIONFAILED" in str(exc) or "Invalid credentials" in str(exc):
            print("::error::Gmail weigert de login (AUTHENTICATIONFAILED). Het "
                  "app-wachtwoord in omgevingsvariabele FUNDA_MAIL_PASSWORD is niet meer geldig. "
                  "Dat gebeurt onder meer na een wijziging van het Google-wachtwoord. "
                  "Maak een nieuw app-wachtwoord op "
                  "https://myaccount.google.com/apppasswords en zet het in de omgevingsvariabele.")
        else:
            print(log_tekst(f"::error::Mailbox niet te lezen: {type(exc).__name__}: {exc}"))
        return []

    woningen: list[tuple[str, str]] = []
    gezien: set[str] = set()
    for tekst in teksten:
        for pad, tiny_id in woningen_uit_mail(tekst, log=log):
            if tiny_id not in gezien:
                gezien.add(tiny_id)
                woningen.append((pad, tiny_id))
    log(f"Mailroute: {len(woningen)} unieke woning(en) uit {len(teksten)} mail(s).")
    return woningen


class GeenBron:
    """Zoeker voor als geen enkele bron werkt.

    Elke zoekaanroep faalt, zonder netwerk. main() stopt dan op de
    exit-2-check ("alle zoekopdrachten mislukt") en het rapport blijft staan.
    De echte oorzaken staan in de ::error die kies_zoeker() er vlak voor zet.
    """

    def __init__(self, client: object, boodschap: str) -> None:
        self._client = client
        self.boodschap = boodschap

    def search_listing(self, *_args, **_kwargs):
        raise RuntimeError("geen enkele zoekbron werkt (oorzaken in de ::error hierboven)")

    def get_listing(self, listing_id):
        return self._client.get_listing(listing_id)

    def __getattr__(self, naam: str):
        if naam.startswith("_"):
            raise AttributeError(naam)
        return getattr(self._client, naam)


def _kort(tekst: object, n: int = 160) -> str:
    regel = " ".join(str(tekst).split())
    return regel if len(regel) <= n else regel[: n - 3] + "..."


def kies_zoeker(f: "Funda") -> tuple[object, str]:
    """Bepaal waarmee we zoeken: de API, de zoekpagina of de sitemaps.

    'auto' (standaard) loopt ze in die volgorde af en gebruikt de eerste die
    werkt. Zo schakelt het zichzelf terug zodra funda de API of de zoekpagina
    weer openzet, zonder dat er iets aan de configuratie hoeft. Per bron kost
    die vraag weinig: één zoek-call, één pagina, robots.txt plus de
    sitemap-index. Bij de sitemaps gebeurt daarna meteen het zoekwerk zelf
    (onthouden voor de zoekronde in main()), zodat een kapotte koop-sitemap in
    de ::error hieronder terechtkomt.

    De mailroute zit niet in 'auto' (besluit 6 nov 2026: de sitemaproute is de
    bron op Actions) en opent de mailbox alleen als zoek_methode 'mail' is.
    Werkt geen enkele bron, dan één ::error met alle oorzaken en een GeenBron,
    zodat de run luid faalt op de exit-2-check in main() zonder nog iets op te
    halen. Is het detail-endpoint dicht, dan geeft de sitemapzoeker die fout bij
    elke zoekaanroep en stopt main() ook met exit 2.
    """
    methode = (os.environ.get("FUNDA_ZOEK_METHODE")
               or _PERSONAL.get("zoek_methode") or "auto").lower()

    if methode not in {"auto", "api", "html", "sitemap", "mail"}:
        log(f"Onbekende zoek_methode {methode!r}, val terug op 'auto'.")
        methode = "auto"

    def html_zoeker():
        from funda_html_zoek import HtmlZoeker

        return HtmlZoeker(f, overslaan=_mag_detail_call_overslaan, log=log)

    def sitemap_zoeker():
        from funda_sitemap_zoek import SitemapZoeker

        return SitemapZoeker(
            f,
            steden=SITEMAP_STEDEN,
            prijs_min=PRIJS_MIN,
            prijs_max=PRIJS_MAX,
            m2_min=M2_MIN,
            max_verkennen=SITEMAP_MAX_VERKENNEN,
            overslaan=_sitemap_overslaan,
            cache_pad=SITEMAP_CACHE_FILE,
            log=log,
        )

    def mail_zoeker():
        from funda_mail_bron import MailBron

        return MailBron(f, _woningen_uit_mailbox(), log=log)

    if methode == "mail":
        log("Zoekmethode: mail (afgedwongen via configuratie).")
        return mail_zoeker(), "mail"

    if methode == "sitemap":
        log("Zoekmethode: sitemap (afgedwongen via configuratie).")
        return sitemap_zoeker(), "sitemap"

    if methode == "html":
        log("Zoekmethode: HTML (afgedwongen via configuratie).")
        return html_zoeker(), "html"

    if methode == "api":
        log("Zoekmethode: API (afgedwongen via configuratie).")
        return f, "api"

    redenen: list[str] = []

    # 1. De zoek-API: één call.
    try:
        f.search_listing(
            location=POSTCODE,
            radius_km=RADIUS_KM,
            offering_type="buy",
            price_min=PRIJS_MIN,
            price_max=PRIJS_MAX,
            object_type=["apartment"],
            availability=["available"],
            page=0,
        )
    except Exception as exc:
        log(f"Zoek-API doet het niet ({exc}); probeer de HTML-zoekpagina.")
        redenen.append(f"zoek-API: {_kort(exc)}")
    else:
        log("Zoekmethode: API.")
        return f, "api"

    # 2. De zoekpagina. Eén goedkope call, want sinds 8 okt 2026 geeft die een
    # 403 vanaf Actions; dan is er geen reden om alle prijsbanden af te lopen.
    zoeker = html_zoeker()
    try:
        bereikbaar = zoeker.bereikbaar()
    except Exception as exc:
        log(f"Zoekpagina niet te bereiken ({exc}).")
        zoeker.reden = str(exc)
        bereikbaar = False
    if bereikbaar:
        log("Zoekmethode: HTML.")
        return zoeker, "html"
    redenen.append(f"zoekpagina: {_kort(getattr(zoeker, 'reden', None) or 'niet bereikbaar')}")

    # 3. De sitemaps: robots.txt en de index. Die twee verzoeken hergebruikt de
    # zoeker daarna, dus dit kost niets extra. bereikbaar() zegt alleen dat de
    # index er is; het echte werk (koop-sitemaps, detail-calls) gebeurt daarom
    # hier al. Het resultaat wordt onthouden, dus dat kost ook niets extra, en
    # gaat het mis, dan staat de oorzaak in de ::error.
    sitemap = sitemap_zoeker()
    try:
        bereikbaar = sitemap.bereikbaar()
    except Exception as exc:
        log(f"Sitemaps niet te bereiken ({exc}).")
        sitemap.reden = str(exc)
        bereikbaar = False
    if bereikbaar:
        try:
            sitemap.ophalen()
        except DetailEndpointDicht as exc:
            # Elke funda-route verrijkt via dit endpoint, dus er is geen
            # terugval. De sitemapzoeker gooit deze fout bij elke zoekaanroep,
            # en main() stopt dan met exit 2.
            log(f"Sitemaproute: het detail-endpoint werkt niet ({exc}); geen terugval.")
            return sitemap, "sitemap"
        except Exception as exc:
            log(f"Sitemaps bereikbaar, maar ophalen mislukte ({exc}).")
            sitemap.reden = str(exc)
        else:
            log("Zoekmethode: sitemap (zoek-API en zoekpagina liggen eruit).")
            return sitemap, "sitemap"
    redenen.append(f"sitemaps: {_kort(getattr(sitemap, 'reden', None) or 'niet bereikbaar')}")

    boodschap = "Geen enkele zoekbron werkt. " + "; ".join(redenen) + "."
    log(boodschap)
    print(f"::error::{log_tekst(boodschap)}")
    return GeenBron(f, boodschap), "geen"


# === Hoofdroutine ===

def _log_kosten(f: object, bron: object, methode: str, start: float) -> None:
    """Eén regel met wat deze run kostte; alleen getallen."""
    delen = [f"methode {methode}", f"duur {time.monotonic() - start:.0f}s",
             f"detail-calls {getattr(f, 'detail_calls', '?')} "
             f"(waarvan dezelfde woning nog eens: {getattr(f, 'detail_dubbel', '?')})"]
    st = getattr(bron, "statistiek", None) if methode == "sitemap" else None
    if st:
        koop = ("niet opnieuw opgehaald (index ongewijzigd)" if st.get("index_ongewijzigd")
                else f"{st.get('koop_sitemaps_opgehaald')} opgehaald")
        delen += [f"sitemap-verzoeken {st.get('sitemap_verzoeken')}", f"koop-sitemaps {koop}",
                  f"kandidaten {st.get('kandidaten')}", f"in doelmarkt {st.get('in_doelmarkt')}",
                  f"achterstand {st.get('achterstand')}"]
    log("Run-kosten: " + "; ".join(delen) + ".")


def main() -> None:
    debug_wijken = "--debug-wijken" in sys.argv
    start = time.monotonic()
    f = Funda()
    seen = laad_state()
    mode = " (debug-wijken)" if debug_wijken else ""
    # De log van een publieke repo is voor iedereen leesbaar; de postcode is privé.
    toon_pc = "(verborgen)" if publieke_log() else POSTCODE
    log(f"Start{mode}. Postcode {toon_pc}, radius {RADIUS_KM}km. Reeds gezien: {len(seen)}.")

    bron, zoek_methode = kies_zoeker(f)
    zoeker = DetailCacheZoeker(bron)

    # Zoek per prijsband los, zodat we onder Funda's resultaatkap (~140) blijven
    # en ook woningen vinden die al lang te koop staan. Dedup op id.
    banden = maak_prijs_banden(PRIJS_MIN, PRIJS_MAX, PRIJS_BAND_STAP)
    rauwe = []
    gezien_ids: set[str] = set()
    # Onderscheid "de markt heeft niets" van "de API doet het niet": tel geslaagde
    # en mislukte zoek-calls apart. Zonder dit onderscheid ziet een kapotte API er
    # precies hetzelfde uit als een lege markt, en overschrijft een stukgelopen run
    # een goed rapport met een leeg rapport.
    zoek_ok = 0
    zoek_fout = 0
    zoek_fout_redenen: Counter[str] = Counter()
    # Op Actions geen regel per prijsband: de grenzen komen uit het profiel, het
    # aantal banden geeft (maal de bandstap) de breedte van het budget en de
    # aantallen per band waar in die breedte het aanbod valt. Om dezelfde reden
    # daar geen aantallen zoek-calls (banden maal sorteringen) en elke zoekfout
    # één keer. Lokaal blijft alles staan, voor de diagnose.
    publiek = publieke_log()

    def aantal(n: int) -> str:
        return "" if publiek else f" {n}"

    for band_min, band_max in banden:
        band_n = 0
        band_label = f"€ {band_min:,}-{band_max:,}"
        for sort in ZOEK_SORTS:
            sort_n = 0
            sort_label = sort or "standaard"
            for pagina in range(PAGINAS):
                try:
                    results = zoeker.search_listing(
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
                    zoek_fout += 1
                    reden = str(exc)[:80]
                    if not publiek:
                        log(f"Fout band {band_label} sort {sort_label} pagina {pagina}: {exc}")
                    elif reden not in zoek_fout_redenen:
                        log(f"Zoekfout: {exc}")
                    zoek_fout_redenen[reden] += 1
                    break
                zoek_ok += 1
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
            if not publiek:
                log(f"Band {band_label} ({sort_label}): {sort_n} nieuw.")
        if not publiek:
            log(f"Band {band_label}: {band_n} uniek na alle sorteringen.")

    log(f"Totaal opgehaald (na dedup): {len(rauwe)} (via {zoek_methode}).")

    # Geen enkele geslaagde zoek-call = de API is stuk (bijv. 401), niet de markt.
    # Hard stoppen: geen rapport schrijven, geen state bijwerken. Zo blijft het
    # vorige (gevulde) rapport staan en kleurt de Action rood in plaats van dat
    # het probleem onopgemerkt doorsijpelt als "0 woningen".
    if zoek_ok == 0 and zoek_fout:
        top = ", ".join(reden + ("" if publiek else f" ({n}x)")
                        for reden, n in zoek_fout_redenen.most_common(3))
        boodschap = (
            f"Alle{aantal(zoek_fout)} zoekopdrachten mislukt, geen enkele geslaagde call. "
            f"Meest voorkomend: {top}. Rapport NIET bijgewerkt."
        )
        log(boodschap)
        print(f"::error::{log_tekst(boodschap)}")
        raise SystemExit(2)

    # Variant op hetzelfde probleem: alle calls slagen, maar er komt niets terug.
    # Zo faalt de HTML-route als funda hun markup wijzigt - de pagina geeft netjes
    # 200 en de parser vindt simpelweg nul kaarten, zonder exception. Voor deze
    # zoekopdracht (hele regio, brede prijsband) is nul woningen in de praktijk
    # geen lege markt maar een stukke zoekmethode. Dus dezelfde behandeling:
    # rapport en state met rust laten en de run rood laten worden.
    if not rauwe:
        boodschap = (
            f"Nul woningen gevonden terwijl alle{aantal(zoek_ok)} zoek-calls slaagden "
            f"(methode: {zoek_methode}). Dat wijst op een stukke zoekmethode, niet "
            f"op een lege markt. Rapport NIET bijgewerkt."
        )
        log(boodschap)
        print(f"::error::{log_tekst(boodschap)}")
        raise SystemExit(2)

    if zoek_fout:
        hoeveel = ("een deel van de zoek-calls" if publiek
                   else f"{zoek_fout} van {zoek_ok + zoek_fout} zoek-calls")
        log(f"Let op: {hoeveel} mislukt; resultaat kan onvolledig zijn.")

    # Eerder getoonde woningen die deze run niet binnenkwamen opnieuw controleren.
    # Pas ná de checks hierboven: een stukke zoekmethode moet nog steeds luid
    # falen, ook als de pool wél iets oplevert.
    tracking = laad_tracking()
    al_binnen: set[str] = set()
    for r in rauwe:
        for veld in ("global_id", "listing_id", "tiny_id", "detail_url"):
            if r.data.get(veld):
                al_binnen.add(str(r.data[veld]))
    # Bij de sitemaproute weet de pool wat de zoeker al ophaalde of bewust
    # oversloeg, zodat geen woning twee keer per run wordt opgehaald.
    try:
        pool = controleer_pool(zoeker, tracking, al_binnen, dagen=POOL_DAGEN, maximum=POOL_MAX,
                               sitemap=bron if zoek_methode == "sitemap" else None)
    except DetailEndpointDicht as exc:
        # Het endpoint ging tijdens de run dicht. Doorgaan geeft een rapport
        # zonder de bekende woningen, en dat blijft staan zolang de volgende
        # runs al bij de eerste call falen. Dus net als hierboven: stoppen.
        boodschap = f"Detail-endpoint ging tijdens de run dicht ({exc}). Rapport NIET bijgewerkt."
        log(boodschap)
        print(f"::error::{log_tekst(boodschap)}")
        raise SystemExit(2)
    rauwe.extend(pool)

    # Debug: alle binnenkomende wijken inventariseren. Alleen lokaal: de buurtnamen
    # met aantallen tonen het zoekgebied, en de log op Actions is publiek.
    if debug_wijken and publieke_log():
        log("--debug-wijken werkt alleen lokaal (de log op Actions is publiek).")
    elif debug_wijken:
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
            elif is_twijfelbuurt(buurt) or is_twijfelstad(stad):
                tag = "TWIJFEL "
            else:
                tag = "OK      "
            print(f"  [{tag}] {n:>2}x  {naam}")
        print()

    # Filter op stad, buurt en straat-segment.
    voor: list = []
    weg_stad = weg_buurt = weg_straat = weg_type = weg_status = weg_criteria = 0
    thuis = thuis_coords()
    straal = nafilter_straal_km()
    if straal and not thuis:
        log("Afstandsfilter: zoekpostcode niet te geocoderen; deze run zonder afstandsfilter.")
    status_mail: Counter[str] = Counter()
    for r in rauwe:
        d = r.data
        stad = (d.get("city") or "").strip()
        buurt = (d.get("neighbourhood") or "").strip()
        geen_app = is_geen_appartement(d)
        if geen_app:
            weg_type += 1
            continue
        # De oude zoekopdracht vroeg alleen beschikbare woningen op. Een mail van
        # tien dagen terug kan inmiddels onder bod staan.
        oordeel, status_tekst = beschikbaarheid(d)
        if d.get("_bron") == "mail":
            status_mail[status_tekst or "(geen)"] += 1
        if oordeel != "ja":
            weg_status += 1
            continue
        if buiten_zoekcriteria(d, thuis, straal):
            weg_criteria += 1
            continue
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

    log(f"Na filter: {len(voor)} (weg: {weg_type} woningtype, {weg_status} niet beschikbaar, "
        f"{weg_criteria} buiten prijs/m2/straal, {weg_stad} stad, {weg_buurt} buurt, "
        f"{weg_straat} straat-segment).")
    if status_mail:
        log("Mailbron: statuswaarden: "
            + ", ".join(f"{s} ({n}x)" for s, n in status_mail.most_common()))

    # Detail-check op beleggingsobject, begane grond en blacklist.
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
            details = zoeker.get_listing(lid)
            details_data = details.data if hasattr(details, "data") else None

            # Bij de API-route heeft het zoekresultaat geen coördinaten; die komen
            # pas uit de detail-call. Dus hier nog een keer, met alles erbij.
            if details_data and buiten_zoekcriteria({**d, **details_data}, thuis, straal):
                weg_criteria += 1
                continue
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

            if redenen:
                afgewezen.append((d, redenen))
            else:
                pub_data[sleutel] = _parse_pub_datum(details_data)
                goed.append(d)
            time.sleep(0.5)
        except Exception as exc:
            log(f"Detail fout {'voor een woning' if publieke_log() else lid}: {exc} - tonen by default.")
            goed.append(d)
    if weg_criteria:
        log(f"Buiten prijs/m2/straal in totaal (incl. na detail-call): {weg_criteria}.")

    # Werk prijs-/looptijd-tracking bij en hang afgeleide flags aan elke woning.
    n_gedaald = n_lang = 0
    for d in goed:
        sleutel = str(d.get("global_id") or d.get("listing_id") or d.get("detail_url"))
        prijs = int(d.get("price") or 0)
        flags = update_tracking(tracking, sleutel, prijs, pub_data.get(sleutel))
        # De URL bewaren, zodat de pool deze woning later zelf kan ophalen. En een
        # woning die weer opduikt, is niet meer weg.
        rec = tracking.get(sleutel)
        if isinstance(rec, dict):
            if _detail_url(d):
                rec["url"] = _detail_url(d)
            rec.pop("weg", None)
            rec.pop("pool_fout", None)
        d["_track"] = flags
        # Twijfel zichtbaar in het rapport, onderaan in de groep (nooit een filter).
        d["_twijfel"] = twijfel_redenen(d)
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
    # twijfelbuurten en woningen zonder vraagprijs naar onderen, daarna op prijs.
    # Dit is de volgorde van de console en de voorlopige samenvatting; na het rapport
    # zet vul_summary_aan() de push in de volgorde van "Aanbevolen" (funda_beoordeling.sorteer).
    def sort_key(d: dict):
        buurt = (d.get("neighbourhood") or "")
        twijfel = (is_twijfelbuurt(buurt) is not None
                   or is_twijfelstad(d.get("city", "") or "") is not None)
        tr = d.get("_track") or {}
        gedaald = bool(tr.get("gedaald"))
        lang = tr.get("dagen", 0) >= LANG_OP_FUNDA_DAGEN
        # `or 0`: een woning zonder vraagprijs ("prijs op aanvraag") heeft
        # price=None. De sitemap- en mailroute laten die bewust door (onbekend =
        # doorlaten), en None naast een getal laat sort() crashen.
        return (not gedaald, not lang, twijfel or prijs_onbekend(d), d.get("price") or 0)

    nieuw.sort(key=sort_key)
    bekend.sort(key=sort_key)
    schrijf_run_summary(nieuw, bekend, afgewezen)

    # Output. Op Actions alleen aantallen: de log van een publieke repo is voor
    # iedereen leesbaar, en de lijst (adres, postcode, buurt, prijs, URL) zou
    # zoekgebied, budget en de gevolgde en afgewezen woningen laten zien. De
    # lijst staat in het versleutelde rapport.
    print("\n" + "=" * 78)
    print(f"NIEUW: {len(nieuw)}    Eerder gezien: {len(bekend)}    Afgewezen: {len(afgewezen)}")
    print("=" * 78)

    if publieke_log():
        toon_aantallen(nieuw, bekend, afgewezen)
    else:
        toon_lijsten(nieuw, bekend, afgewezen)

    # State updaten.
    nieuwe_set = {str(d.get("global_id") or d.get("listing_id") or d.get("detail_url")) for d in goed}
    bewaar_state(seen | nieuwe_set)
    log(f"Klaar. Nieuw vandaag: {len(nieuw)}. State bevat nu {len(seen | nieuwe_set)} id's.")

    # Rapport genereren over alle goedgekeurde woningen, met markering nieuw vs eerder.
    # Altijd genereren (ook bij 0 matches) zodat de "Gegenereerd"-datum in het
    # rapport nooit blijft hangen op de laatste run met resultaten.
    if genereer_rapport:
        try:
            nieuw_ids = {str(d.get("global_id") or d.get("listing_id") or d.get("detail_url")) for d in nieuw}
            pad = genereer_rapport(zoeker, goed, nieuw_ids)
            log(f"Rapport: {pad.name}")
            if nieuw:
                n = vul_summary_aan(nieuw)
                log(f"Pushsamenvatting: {n} van {len(nieuw)} nieuwe woningen met poortwoord en score.")

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

    _log_kosten(f, bron, zoek_methode, start)

    # Auto-push docs/ naar GitHub (skipt zelf als er geen wijzigingen zijn).
    auto_push()


def reden_soort(reden: str) -> str:
    """De soort van een afwijsreden voor de telling: belegging, begane grond of blacklist."""
    if reden == "blacklist":
        return "blacklist"
    if reden.startswith("begane grond"):
        return "begane grond"
    return "belegging"


def toon_aantallen(nieuw: list[dict], bekend: list[dict],
                   afgewezen: list[tuple[dict, list[str]]]) -> None:
    """Voor de publieke log op Actions: alleen aantallen, geen woning.

    Een woning met meer redenen (belegging én begane grond) telt bij elke soort één keer."""
    def gedaald(ds: list[dict]) -> int:
        return sum(1 for d in ds if (d.get("_track") or {}).get("gedaald"))

    print(f"Met prijsdaling: {gedaald(nieuw)} nieuw, {gedaald(bekend)} eerder gezien.")
    if afgewezen:
        soorten: Counter[str] = Counter()
        for _d, redenen in afgewezen:
            soorten.update({reden_soort(r) for r in redenen})
        print("Afgewezen per reden: "
              + ", ".join(f"{soort} {soorten[soort]}" for soort in ("belegging", "begane grond", "blacklist")
                          if soorten[soort]) + ".")
    print("Geen woninglijst op Actions (de log is publiek); die staat in het versleutelde rapport.")


def toon_lijsten(nieuw: list[dict], bekend: list[dict],
                 afgewezen: list[tuple[dict, list[str]]]) -> None:
    """Lokaal: de volledige lijst, met adres, buurt, prijs en URL per woning."""
    for d in nieuw:
        toon(d, prefix="NIEUW")

    if bekend:
        print("\n--- Eerder gezien, nog steeds beschikbaar ---")
        for d in bekend:
            toon(d, prefix="     ")

    if afgewezen:
        print("\n--- Afgewezen (belegging/bg/blacklist) ---")
        for d, w in afgewezen:
            print(f"  {d.get('title')}: {', '.join(w)}")


def toon(d: dict, prefix: str = "") -> None:
    prijs = d.get("price") or 0   # None bij "prijs op aanvraag"
    m2 = d.get("living_area", 0) or 0
    ppm = prijs // m2 if m2 else 0
    label = d.get("energy_label", "?")
    buurt = d.get("neighbourhood", "")
    twijfel = is_twijfelbuurt(buurt)
    flag = f" /!\\ TWIJFELBUURT ({twijfel})" if twijfel else ""
    twijfel_stad = is_twijfelstad(d.get("city", "") or "")
    if twijfel_stad:
        flag += f" /!\\ STAD ONDUIDELIJK ({twijfel_stad})"
    if prijs_onbekend(d):
        flag += " /!\\ PRIJS ONBEKEND (prijs op aanvraag)"

    tr = d.get("_track") or {}
    if tr.get("gedaald"):
        flag += f" /!\\ PRIJS GEDAALD -€{tr['drop_bedrag']:,} ({tr['drop_pct']}%)"
    if tr.get("dagen", 0) >= LANG_OP_FUNDA_DAGEN:
        bron = "" if tr.get("dagen_bron") == "funda" else "+"
        flag += f" /!\\ LANG OP FUNDA ({tr['dagen']}{bron}d)"

    url = d.get("detail_url", "")
    if url and not url.startswith("http"):
        url = f"https://www.funda.nl{url}"
    prijs_tekst = "prijs op aanvraag" if prijs_onbekend(d) else f"€ {prijs:,} | {m2} m2 (€{ppm}/m2)"
    if prijs_onbekend(d):
        prijs_tekst += f" | {m2} m2"
    print(f"\n[{prefix}] {prijs_tekst} | label {label}{flag}")
    print(f"  {d.get('title')}, {d.get('postcode')} {d.get('city')}")
    print(f"  Wijk: {buurt}")
    print(f"  {d.get('bedrooms')} slpk | {d.get('rooms')} kamers")
    if tr.get("gedaald") and tr.get("eerdere_prijs"):
        print(f"  Was € {tr['eerdere_prijs']:,}, nu € {prijs:,} (wijziging {tr.get('laatste_wijziging')})")
    print(f"  {url}")


if __name__ == "__main__":
    main()
