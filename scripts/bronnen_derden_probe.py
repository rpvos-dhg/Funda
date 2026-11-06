"""Kunnen andere Nederlandse woningsites funda als bron vervangen of aanvullen?

Funda's zoekpagina geeft 403 vanaf een Actions-runner en de zoek-API eist een
token (zie CLAUDE.md). Dit script meet per derde partij, vanaf dezelfde runner:

- mag de zoekpagina gelezen worden volgens robots.txt (groep `*`)?
- status, en staan de resultaten server-side in de HTML of in een JSON-blob?
- hoeveel resultaten voor koopappartementen in Den Haag / Voorburg, ca.
  EUR 230-310k, minimaal 55 m2, en welke velden er per woning zijn;
- dekking: hoeveel van de recente funda-woningen uit `bronnen_seeds.json`
  (de mailperiode, 17 okt t/m 4 nov 2026) op de site staan;
- voor huispedia ook: komt de CBS-buurt (via PDOK) overeen met funda's buurt,
  en hoeveel woningen overleven de bestaande filters van funda_zoek.py.

Spelregels, hard:
- Eén vaste client (dezelfde curl_cffi-instellingen als funda_html_zoek.py),
  geen wisselende TLS-profielen of user-agents, geen proxy's, geen captcha's.
- Elke URL wordt eerst tegen robots.txt gecontroleerd; wat daar niet mag,
  wordt niet opgevraagd.
- Maximaal MAX_VERZOEKEN verzoeken per run, minstens PAUZE seconden ertussen.
- Geeft een site 401/403/429 of een bot-controle, dan stopt het script op dat
  pad en probeert het niet opnieuw.
- De log van deze publieke repo is leesbaar voor iedereen: er wordt alleen
  publieke advertentie-informatie geprint (adres, prijs, m2), niets privé.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Zelfde instellingen als funda_html_zoek.py: één vaste client, geen rotatie.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"}

MAX_VERZOEKEN = 60
PAUZE = 0.8

PRIJS_MIN, PRIJS_MAX, M2_MIN = 230_000, 310_000, 55

SEEDS = Path(__file__).with_name("bronnen_seeds.json")

BOT_MARKERS = ("captcha", "cf-chl", "challenge-platform", "Je bent bijna op de pagina",
               "Access denied", "Attention Required")


# --------------------------------------------------------------------------
# HTTP met budget, pauze en robots.txt
# --------------------------------------------------------------------------

class Budget(Exception):
    pass


class Client:
    def __init__(self) -> None:
        self.sessie = curl_requests.Session(impersonate="safari15_5")
        self.aantal = 0
        self.robots: dict[str, list[tuple[str, str]] | None] = {}
        self.geblokkeerd: set[str] = set()

    def _get(self, url: str):
        if self.aantal >= MAX_VERZOEKEN:
            raise Budget(f"budget van {MAX_VERZOEKEN} verzoeken op")
        if self.aantal:
            time.sleep(PAUZE)
        self.aantal += 1
        return self.sessie.get(url, headers=HEADERS, timeout=30, allow_redirects=True)

    def regels(self, host: str) -> list[tuple[str, str]] | None:
        """Allow/Disallow-regels uit de `*`-groep van robots.txt; None = onbekend."""
        if host in self.robots:
            return self.robots[host]
        try:
            resp = self._get(f"https://{host}/robots.txt")
        except Budget:
            raise
        except Exception as exc:
            print(f"    robots.txt {host}: EXC {type(exc).__name__}: {str(exc)[:90]}")
            self.robots[host] = None
            return None
        if resp.status_code != 200:
            print(f"    robots.txt {host}: status {resp.status_code} (geen regels = alles mag)")
            self.robots[host] = []
            return []
        self.robots[host] = parse_robots(resp.text or "")
        return self.robots[host]

    def mag(self, url: str) -> bool | None:
        delen = urlsplit(url)
        regels = self.regels(delen.netloc)
        if regels is None:
            return None
        return robots_toegestaan(regels, delen.path + (f"?{delen.query}" if delen.query else ""))

    def haal(self, url: str, *, label: str = "") -> tuple[int | None, str]:
        """GET met robots-check. Geeft (status, tekst); status None = niet gedaan."""
        host = urlsplit(url).netloc
        if host in self.geblokkeerd:
            print(f"    {label or url}: overgeslagen, {host} blokkeerde eerder in deze run")
            return None, ""
        mag = self.mag(url)
        if mag is None:
            print(f"    {label or url}: overgeslagen, robots.txt niet leesbaar")
            return None, ""
        if not mag:
            print(f"    {label or url}: NIET opgevraagd, robots.txt verbiedt dit pad")
            return None, ""
        try:
            resp = self._get(url)
        except Budget:
            raise
        except Exception as exc:
            print(f"    {label or url}: EXC {type(exc).__name__}: {str(exc)[:100]}")
            return None, ""
        tekst = resp.text or ""
        blok = resp.status_code in (401, 403, 429) or (
            resp.status_code == 200 and len(tekst) < 20_000
            and any(m.lower() in tekst.lower() for m in BOT_MARKERS)
        )
        print(f"    {label or url}: status={resp.status_code} len={len(tekst)}"
              + ("  << BLOKKADE, stop op dit pad" if blok else ""))
        if blok:
            self.geblokkeerd.add(host)
            return resp.status_code, ""
        if resp.status_code != 200:
            return resp.status_code, ""
        return resp.status_code, tekst


def parse_robots(tekst: str) -> list[tuple[str, str]]:
    """Regels van de groep(en) voor `*`. Eenvoudige, Google-conforme lezing."""
    regels: list[tuple[str, str]] = []
    agents: list[str] = []
    in_regels = False
    for ruw in tekst.splitlines():
        regel = ruw.split("#", 1)[0].strip()
        if not regel or ":" not in regel:
            continue
        veld, waarde = (x.strip() for x in regel.split(":", 1))
        veld = veld.lower()
        if veld == "user-agent":
            if in_regels:
                agents, in_regels = [], False
            agents.append(waarde.lower())
        elif veld in ("allow", "disallow"):
            in_regels = True
            if "*" in agents and waarde:
                regels.append((veld, waarde))
    return regels


def _patroon(regel: str) -> re.Pattern[str]:
    anker = regel.endswith("$")
    kern = regel[:-1] if anker else regel
    rx = "".join(".*" if c == "*" else re.escape(c) for c in kern)
    return re.compile("^" + rx + ("$" if anker else ""))


def robots_toegestaan(regels: list[tuple[str, str]], pad: str) -> bool:
    """Langste match wint; bij gelijke lengte wint Allow (Google-specificatie)."""
    beste: tuple[int, bool] | None = None
    for soort, waarde in regels:
        if _patroon(waarde).match(pad):
            kandidaat = (len(waarde), soort == "allow")
            if beste is None or kandidaat > beste:
                beste = kandidaat
    return True if beste is None else beste[1]


# --------------------------------------------------------------------------
# Dekking tegen de seeds
# --------------------------------------------------------------------------

def sleutel(postcode: str | None, nummer) -> tuple[str, int] | None:
    pc = re.sub(r"\s+", "", str(postcode or "")).upper()
    try:
        return pc, int(nummer)
    except (TypeError, ValueError):
        return None


def adres_nummer(adres: str) -> int | None:
    """Eerste huisnummer na de straatnaam: 'Meppelweg 906-C' -> 906."""
    m = re.search(r"\s(\d+)", " " + adres)
    return int(m.group(1)) if m else None


def laad_seeds() -> list[dict]:
    return json.loads(SEEDS.read_text(encoding="utf-8"))["woningen"]


def dekking(naam: str, gevonden: dict[tuple[str, int], dict], seeds: list[dict]) -> int:
    print(f"\n  Dekking {naam} tegen {len(seeds)} funda-woningen uit de mailperiode "
          f"(gesorteerd op laatste keer in het rapport):")
    hits = 0
    for w in seeds:
        k = sleutel(w["postcode"], adres_nummer(w["adres"]))
        rec = gevonden.get(k) if k else None
        hits += bool(rec)
        extra = ""
        if rec:
            extra = f" -> {rec.get('status') or ''} EUR {rec.get('price')} {rec.get('living_area')} m2"
        print(f"    {'JA ' if rec else 'NEE'} {w['laatst_in_rapport']} {w['adres']}, {w['stad']} "
              f"(funda {w['tiny_id']}, EUR {w['prijs']}){extra}")
    print(f"  => {naam}: {hits}/{len(seeds)} gevonden")
    return hits


# --------------------------------------------------------------------------
# Huispedia, via de prototype-module bron_huispedia.py
# --------------------------------------------------------------------------

def probe_huispedia(c: Client, seeds: list[dict]) -> dict:
    from bron_huispedia import BESCHIKBAAR, bouw_zoek_url, naar_listing, parse_detail, parse_zoekpagina

    print("\n=== Huispedia (huispedia.nl) - via bron_huispedia.py")
    uitkomst: dict = {"site": "huispedia", "status": None, "aantal": 0}
    listings: list[dict] = []
    for gemeente in ("den-haag", "leidschendam-voorburg"):
        url = bouw_zoek_url(gemeente, prijs_min=PRIJS_MIN, prijs_max=PRIJS_MAX, m2_min=M2_MIN)
        status, tekst = c.haal(url, label=f"zoek {gemeente} (appartement, prijs+m2 als filter)")
        uitkomst["status"] = status
        if not tekst:
            continue
        try:
            totaal, recs = parse_zoekpagina(tekst)
        except ValueError as exc:
            print(f"    {exc}")
            continue
        print(f"    JSON-blob (Inertia data-page): total_results={totaal} mapProperties={len(recs)}")
        print(f"    statussen: {dict(Counter(r.get('status') for r in recs))}")
        if recs:
            print(f"    velden per woning (ruw): {sorted(recs[0].keys())}")
        for r in recs:
            listings.append(naar_listing(r))
        for d in listings[-len(recs):][:3]:
            print(f"      voorbeeld: {d['title']}, {d['postcode']} {d['city']} | EUR {d['price']} | "
                  f"{d['living_area']} m2 | label {d['energy_label']} | {d['status']} | "
                  f"lat/lon {d['latitude']},{d['longitude']} | {d['broker']}")
    if not listings:
        return uitkomst

    uitkomst["aantal"] = len(listings)
    gevonden = {sleutel(d["postcode"], d["house_number"]): d for d in listings}
    uitkomst["dekking"] = dekking("Huispedia", gevonden, seeds)

    beschikbaar = [d for d in listings if d["status"] in BESCHIKBAAR]
    print(f"\n    beschikbaar (te koop/open voor bod/op termijn): {len(beschikbaar)} van {len(listings)}")

    # Buurtnamen: CBS-grenzen van PDOK, punt-in-polygoon op lat/lon.
    print("\n  CBS-buurt via PDOK (api.pdok.nl/cbs, open data):")
    locatieserver = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q=postcode:2511BT"
    print(f"    adres-zoekdienst (locatieserver) toegestaan door robots.txt: {c.mag(locatieserver)} "
          f"-> niet gebruikt")
    try:
        from buurten_cbs import BuurtBepaler, buurten_url, parse_buurten

        buurten = []
        for gemeente in ("den-haag", "leidschendam-voorburg"):
            status, tekst = c.haal(buurten_url(gemeente), label=f"CBS-buurten {gemeente}")
            if tekst:
                buurten.extend(parse_buurten(json.loads(tekst)))
        bepaler = BuurtBepaler(buurten)
        print(f"    {len(bepaler)} buurten geladen")
    except Exception as exc:  # noqa: BLE001 - meten, niet crashen
        print(f"    CBS-buurten niet te laden: {type(exc).__name__}: {exc}")
        bepaler = None

    if bepaler is not None and len(bepaler):
        for d in listings:
            d["neighbourhood"] = bepaler(d["latitude"], d["longitude"])
        gelijk = vergeleken = 0
        for w in seeds:
            d = gevonden.get(sleutel(w["postcode"], adres_nummer(w["adres"])))
            if not d:
                continue
            vergeleken += 1
            if (d.get("neighbourhood") or "").lower() == w["wijk"].lower():
                gelijk += 1
            else:
                print(f"    VERSCHIL {w['adres']}: funda={w['wijk']!r} CBS={d.get('neighbourhood')!r}")
        print(f"    buurtnaam CBS == funda: {gelijk}/{vergeleken}; zonder buurt: "
              f"{sum(1 for d in listings if not d.get('neighbourhood'))}/{len(listings)}")
        uitkomst["buurt_gelijk"] = f"{gelijk}/{vergeleken}"

        # Wat blijft er over na de bestaande, goedkope filters van funda_zoek.py?
        try:
            import funda_zoek as fz

            weg: Counter[str] = Counter()
            for d in beschikbaar:
                if fz.is_geen_appartement(d):
                    weg["woningtype"] += 1
                elif fz.is_uitgesloten_stad((d.get("city") or "").strip()):
                    weg["stad"] += 1
                elif fz.is_uitgesloten_buurt((d.get("neighbourhood") or "").strip()):
                    weg["buurt"] += 1
                elif fz.is_uitgesloten_straat_nr(d):
                    weg["straat"] += 1
                else:
                    weg["door"] += 1
            print(f"    funda_zoek-filters op de beschikbare woningen: {dict(weg)}")
            uitkomst["na_filter"] = weg["door"]
        except Exception as exc:  # noqa: BLE001
            print(f"    funda_zoek niet te importeren: {type(exc).__name__}: {exc}")

    # Twee detailpagina's (JSON-LD): verdieping, buurt, publicatiedatum.
    print("\n  Detailpagina's (JSON-LD), voor de detail-check:")
    for w in seeds[-2:]:
        d = gevonden.get(sleutel(w["postcode"], adres_nummer(w["adres"])))
        if not d:
            continue
        status, tekst = c.haal(d["detail_url"], label=f"detail {d['title']}")
        if tekst:
            det = parse_detail(tekst)
            print(f"    buurt={det.get('neighbourhood')!r} gelegen_op={det.get('gelegen_op')!r} "
                  f"soort={det.get('house_type')!r} sinds={det.get('publication_date')!r} "
                  f"kenmerken={len(det.get('kenmerken') or {})} funda-link={'funda.nl/detail' in tekst}")
    return uitkomst


# --------------------------------------------------------------------------
# Pararius koop: server-side HTML, 30 kaarten per pagina, page-N verboden
# --------------------------------------------------------------------------

PARARIUS_KAART = re.compile(r'<section\s+class="listing-search-item listing-search-item--list')


def _tekst(fragment: str) -> str:
    zonder = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_mod.unescape(zonder)).strip()


def parse_pararius(tekst: str) -> list[dict]:
    kaarten = []
    for stuk in PARARIUS_KAART.split(tekst)[1:]:
        stuk = stuk.split("</section>", 1)[0]
        href = re.search(r'href="(/[a-z-]+-te-koop/[^"]+)"', stuk)
        # aria-label op de fotolink is schoon ("Appartement Volendamlaan 988");
        # de titel-link zelf heeft data-action-attributen met '>' erin.
        label = re.search(r'aria-label="([^"]+)"', stuk)
        sub = re.search(r'listing-search-item__sub-title[^"]*"[^>]*>(.*?)</div>', stuk, re.S)
        prijs = re.search(r'listing-search-item__price-main[^>]*>(.*?)</span>', stuk, re.S)
        m2 = re.search(r'surface-area">.*?([\d.]+)\s*m²', stuk, re.S)
        kamers = re.search(r'number-of-rooms">.*?(\d+)\s*kamer', stuk, re.S)
        jaar = re.search(r'construction-period">.*?(\d{4})', stuk, re.S)
        info = re.search(r'listing-search-item__info"[^>]*>(.*?)</div>', stuk, re.S)
        pid = re.search(r'data-listing-search-item-id="([^"]+)"', stuk)
        titel = html_mod.unescape(label.group(1)).strip() if label else ""
        adres = re.sub(r"^(Appartement|Huis|Studio|Woning)\s+", "", titel)
        sub_t = _tekst(sub.group(1)) if sub else ""
        pcm = re.match(r"(\d{4}\s?[A-Z]{2})\s+(.+?)(?:\s+\((.+)\))?$", sub_t)
        prijs_t = _tekst(prijs.group(1)) if prijs else ""
        prijs_n = re.search(r"€\s*([\d.]+)", prijs_t)
        kaarten.append({
            "id": pid.group(1) if pid else None,
            "title": adres,
            "type": titel.split(" ", 1)[0] if titel else None,
            "postcode": pcm.group(1).replace(" ", "") if pcm else None,
            "city": pcm.group(2) if pcm else None,
            "neighbourhood": pcm.group(3) if pcm else None,
            "price": int(prijs_n.group(1).replace(".", "")) if prijs_n else None,
            "price_text": prijs_t,
            "living_area": int(m2.group(1).replace(".", "")) if m2 else None,
            "rooms": int(kamers.group(1)) if kamers else None,
            "construction_year": int(jaar.group(1)) if jaar else None,
            "broker": _tekst(info.group(1)) if info else None,
            "detail_url": "https://www.pararius.nl" + href.group(1) if href else None,
        })
    return kaarten


def pararius_totaal(tekst: str) -> int | None:
    m = re.search(r"search-list-header__count[^>]*>\s*([\d.]+)", tekst)
    return int(m.group(1).replace(".", "")) if m else None


def probe_pararius(c: Client, seeds: list[dict]) -> dict:
    print("\n=== Pararius koop (pararius.nl/koopwoningen)")
    uitkomst: dict = {"site": "pararius", "status": None, "aantal": 0}
    alle: dict[str, dict] = {}
    basis = "https://www.pararius.nl/koopwoningen/{stad}/appartement/{lo}-{hi}"

    status, tekst = c.haal(basis.format(stad="den-haag", lo=PRIJS_MIN, hi=PRIJS_MAX),
                           label="zoek den-haag 230-310k (pagina 1)")
    uitkomst["status"] = status
    if not tekst:
        return uitkomst
    kaarten = parse_pararius(tekst)
    print(f"    server-side HTML: totaal volgens kop={pararius_totaal(tekst)}, kaarten op pagina 1={len(kaarten)}")
    if kaarten:
        print(f"    velden per woning: {sorted(kaarten[0].keys())}")
        for k in kaarten[:3]:
            print(f"      voorbeeld: {k['title']} | {k['postcode']} {k['city']} ({k['neighbourhood']}) | "
                  f"{k['price_text']} | {k['living_area']} m2 | {k['broker']}")
    for k in kaarten:
        alle[k["id"] or k["detail_url"]] = k

    # Doorbladeren (/page-2) verbiedt robots.txt voor appartementen. Dus prijs-
    # banden die elk binnen één pagina (30 kaarten) passen; te vol = halveren.
    banden = [(lo, lo + 10_000) for lo in range(PRIJS_MIN, PRIJS_MAX, 10_000)]
    while banden:
        lo, hi = banden.pop(0)
        status, tekst = c.haal(basis.format(stad="den-haag", lo=lo, hi=hi), label=f"band {lo}-{hi}")
        if not tekst:
            break
        kaarten = parse_pararius(tekst)
        t = pararius_totaal(tekst) or 0
        print(f"      totaal={t} kaarten={len(kaarten)}")
        for k in kaarten:
            alle[k["id"] or k["detail_url"]] = k
        if t > len(kaarten) and hi - lo > 2_000:
            midden = (lo + hi) // 2
            banden[:0] = [(lo, midden), (midden, hi)]
        elif t > len(kaarten):
            print(f"      << {t - len(kaarten)} woning(en) niet bereikbaar zonder doorbladeren")

    status, tekst = c.haal(basis.format(stad="voorburg", lo=PRIJS_MIN, hi=PRIJS_MAX), label="zoek voorburg 230-310k")
    if tekst:
        kaarten = parse_pararius(tekst)
        print(f"      totaal={pararius_totaal(tekst)} kaarten={len(kaarten)}")
        for k in kaarten:
            alle[k["id"] or k["detail_url"]] = k

    doel = [k for k in alle.values() if (k["living_area"] or 0) >= M2_MIN]
    print(f"    uniek opgehaald: {len(alle)}, waarvan >= {M2_MIN} m2: {len(doel)}")
    uitkomst["aantal"] = len(doel)

    gevonden = {}
    for k in alle.values():
        s = sleutel(k["postcode"], adres_nummer(k["title"]))
        if s:
            gevonden[s] = {"status": "", "price": k["price"], "living_area": k["living_area"]}
    uitkomst["dekking"] = dekking("Pararius", gevonden, seeds)

    eerste = next(iter(alle.values()), None)
    if eerste and eerste["detail_url"]:
        status, tekst = c.haal(eerste["detail_url"], label="detailpagina (eerste kaart)")
        if tekst:
            lat = '"latitude"' in tekst
            funda = "funda.nl/detail" in tekst
            print(f"    detail: latitude={lat} funda-link={funda}")
    return uitkomst


# --------------------------------------------------------------------------
# Kleinere kandidaten: één verzoek per stuk, alleen om de stand te meten
# --------------------------------------------------------------------------

def probe_huislijn(c: Client) -> dict:
    print("\n=== Huislijn (huislijn.nl)")
    status, tekst = c.haal("https://www.huislijn.nl/koopwoning/nederland/zuid-holland/den-haag",
                           label="alle koopwoningen den-haag (pagina 1)")
    uit = {"site": "huislijn", "status": status, "aantal": 0}
    if tekst:
        m = re.search(r"Bekijk ([\d.]+) koopwoningen", tekst)
        links = set(re.findall(r'href="(/koopwoning/nederland/zuid-holland/\d+/[^"]+)"', tekst))
        totaal = int(m.group(1).replace(".", "")) if m else None
        print(f"    server-side HTML: totaal koopwoningen Den Haag (alle typen/prijzen)={totaal}, "
              f"woninglinks op pagina 1={len(links)}")
        uit["aantal"] = totaal or 0
    return uit


def probe_zah(c: Client) -> dict:
    print("\n=== Zah.nl (Zoek Alle Huizen)")
    status, tekst = c.haal("https://www.zah.nl/te-koop-den-haag/", label="koopwoningen den-haag (pagina 1)")
    uit = {"site": "zah", "status": status, "aantal": 0}
    if tekst:
        m = re.search(r"([\d.]+) [Kk]oopwoningen in Den Haag", tekst)
        pararius = len(set(re.findall(r"pararius\.nl/listing/([0-9a-f-]+)", tekst)))
        print(f"    totaal={m.group(1) if m else None}; uitgaande links naar pararius-advertenties={pararius}")
        uit["aantal"] = int(m.group(1).replace(".", "")) if m else 0
    return uit


def probe_rest(c: Client) -> list[dict]:
    uit = []
    print("\n=== Jaap.nl (in 2024 gesloten door Mediahuis, volgens nieuwsberichten)")
    status, _ = c.haal("https://www.jaap.nl/", label="homepage")
    uit.append({"site": "jaap", "status": status, "aantal": 0})
    print("\n=== Huizenzoeker.nl")
    status, tekst = c.haal("https://www.huizenzoeker.nl/", label="homepage")
    if tekst:
        titel = re.search(r"<title>([^<]*)", tekst)
        koop_links = len(re.findall(r'href="/koop', tekst))
        print(f"    titel: {titel.group(1) if titel else None!r}; koop-links={koop_links}")
    uit.append({"site": "huizenzoeker", "status": status, "aantal": 0})
    print("\n=== Walter Living: betaalde dienst, niet bevraagd (alleen genoteerd).")
    return uit


def main() -> int:
    seeds = laad_seeds()
    c = Client()
    print(f"Derde-partij woningsites als bron. Doel: koopappartement Den Haag/Voorburg, "
          f"EUR {PRIJS_MIN}-{PRIJS_MAX}, >= {M2_MIN} m2. Budget {MAX_VERZOEKEN} verzoeken, "
          f"pauze {PAUZE}s. {len(seeds)} seeds.")
    resultaten = []
    try:
        resultaten.append(probe_huispedia(c, seeds))
        resultaten.append(probe_pararius(c, seeds))
        resultaten.append(probe_huislijn(c))
        resultaten.append(probe_zah(c))
        resultaten.extend(probe_rest(c))
    except Budget as exc:
        print(f"\nGESTOPT: {exc}")

    print(f"\n=== Samenvatting ({c.aantal} verzoeken)")
    for r in resultaten:
        dek = f"{r['dekking']}/{len(seeds)}" if "dekking" in r else "-"
        extra = "".join(f" {k}={r[k]}" for k in ("buurt_gelijk", "na_filter") if k in r)
        print(f"  {r['site']:14} status={r['status']} aantal={r['aantal']} dekking={dek}{extra}")
    if c.geblokkeerd:
        print(f"  geblokkeerd: {sorted(c.geblokkeerd)}")
    # Geslaagd = minstens één bron met bruikbare dekking.
    beste = max((r.get("dekking", 0) for r in resultaten), default=0)
    return 0 if beste > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
