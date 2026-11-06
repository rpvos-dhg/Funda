"""Probe: zijn funda's robots.txt en sitemaps een bruikbare ontdekkingsbron?

Sitemaps zijn juist bedoeld voor geautomatiseerde lezers. Als ze vanaf een
Actions-runner bereikbaar zijn en per woning een <lastmod> hebben, kan het
script daar de nieuwste woning-URL's uit halen en ze via het detail-endpoint
(dat vanaf Actions wél werkt) verrijken. Deze probe meet of dat kan:

1. robots.txt ophalen en volledig printen (die is publiek), met de
   Sitemap:-regels en de Disallow-regels voor /detail/, /koop/ en /zoeken/.
2. Elke genoemde sitemap(-index) ophalen: status, content-type, server, grootte,
   gzip, aantal <loc>, of er <lastmod> in staat. Een index volgen naar de
   kind-sitemaps over koopwoningen; Den Haag en Voorburg tellen.
3. Als er detail-URL's met lastmod zijn: de nieuwste voor Den Haag/Voorburg via
   get_listing verrijken en meten hoeveel er in de doelmarkt vallen, hoe vers de
   sitemaps zijn, en of de woningen uit de mailperiode erin staan (recall).

Spelregels, hard:
- Eén client, met de instellingen die de repo al gebruikt (curl_cffi met het
  safari-profiel en de UA uit funda_html_zoek.py, en de gepatchte Funda-client
  uit funda_zoek.py voor het detail-endpoint: één gewone client, geen
  app-vingerafdruk). Geen wisselende profielen of UA's: geeft iets 401/403 of
  een bot-controle, dan wordt dat genoteerd en stopt dat pad.
- robots.txt van www.funda.nl wordt gerespecteerd: een URL die voor `*` is
  uitgesloten, wordt niet opgehaald. Die dekt de detail-calls niet; die gaan
  naar listing-detail-page.funda.io (Disallow: /), zie CLAUDE.md.
- Hooguit MAX_VERZOEKEN verzoeken per run, met minstens PAUZE seconden ertussen.
- Print geen privégegevens. Alleen publieke funda-gegevens (URL's, tiny_id,
  adres, prijs). funda_personal.json wordt niet gelezen.

Bijsturen zonder codewijziging (alle optioneel):
- SITEMAP_EXTRA: komma-gescheiden sitemap-URL's die extra opgehaald moeten worden
  (bijvoorbeeld kind-sitemaps die een vorige run in een index vond).
- SITEMAP_MAX_KINDEREN: hoeveel kind-sitemaps maximaal (standaard 30).
- SITEMAP_MAX_DETAIL: hoeveel detail-calls maximaal (standaard 12).
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from curl_cffi import requests as curl_requests

ROBOTS_URL = "https://www.funda.nl/robots.txt"

# Zelfde instellingen als HtmlZoeker in funda_html_zoek.py. Bewust één profiel.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {"user-agent": UA, "accept-language": "nl-NL,nl;q=0.9"}
IMPERSONATE = "safari15_5"

MAX_VERZOEKEN = 58
PAUZE = 0.7
MAX_KINDEREN = int(os.environ.get("SITEMAP_MAX_KINDEREN") or 30)
MAX_DETAIL = int(os.environ.get("SITEMAP_MAX_DETAIL") or 12)

# Doelmarkt (publieke zoekcriteria, geen privégegevens).
DOEL_STEDEN = ("den-haag", "voorburg")
DOEL_PRIJS = (230_000, 310_000)
DOEL_M2 = 55

# Woningen die eerder in het rapport stonden, om de recall te meten. Bewust NIET
# in de repo: samen verraden die het zoekgebied en budget. Lokaal in
# funda_seeds_lokaal.json (gitignored, een JSON-lijst met tiny_id's); zonder dat
# bestand slaat de recall-meting over.
def _laad_seeds() -> set[str]:
    pad = Path(__file__).resolve().parent.parent / "funda_seeds_lokaal.json"
    try:
        return {str(x) for x in json.loads(pad.read_text(encoding="utf-8"))}
    except Exception:
        return set()


MAIL_SEEDS = _laad_seeds()

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
URL_BLOK_RE = re.compile(r"<(url|sitemap)>(.*?)</\1>", re.I | re.S)
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)
TINY_RE = re.compile(r"/(\d{7,9})/?(?:$|[?#])")
# Oud funda-formaat: /koop/<stad>/appartement-<id>-<straat>/
TINY_OUD_RE = re.compile(r"/koop/[^/]+/[a-z]+-(\d{7,9})-")

INTERESSANTE_HEADERS = ("server", "content-type", "content-encoding", "content-length",
                        "last-modified", "cache-control", "age", "x-cache", "x-akamai-transformed",
                        "akamai-grn", "x-robots-tag")


class Teller:
    def __init__(self) -> None:
        self.n = 0
        self.sessie = curl_requests.Session(impersonate=IMPERSONATE)
        self.laatste = 0.0

    def over(self) -> int:
        return MAX_VERZOEKEN - self.n

    def get(self, url: str):
        if self.n >= MAX_VERZOEKEN:
            raise RuntimeError("verzoekbudget op")
        wacht = PAUZE - (time.monotonic() - self.laatste)
        if wacht > 0:
            time.sleep(wacht)
        self.n += 1
        try:
            return self.sessie.get(url, headers=HEADERS, timeout=40)
        finally:
            self.laatste = time.monotonic()


# -- robots.txt ---------------------------------------------------------------

def parse_robots(tekst: str) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """Sitemap-regels en per user-agent de Allow/Disallow-regels."""
    sitemaps: list[str] = []
    groepen: dict[str, list[tuple[str, str]]] = {}
    huidige: list[str] = []
    vorige_was_agent = False
    for ruw in tekst.splitlines():
        regel = ruw.split("#", 1)[0].strip()
        if not regel or ":" not in regel:
            continue
        sleutel, waarde = regel.split(":", 1)
        sleutel = sleutel.strip().lower()
        waarde = waarde.strip()
        if sleutel == "sitemap":
            sitemaps.append(waarde)
            continue
        if sleutel == "user-agent":
            if not vorige_was_agent:
                huidige = []
            huidige.append(waarde.lower())
            groepen.setdefault(waarde.lower(), [])
            vorige_was_agent = True
            continue
        vorige_was_agent = False
        if sleutel in ("allow", "disallow"):
            for agent in huidige:
                groepen.setdefault(agent, []).append((sleutel, waarde))
    return sitemaps, groepen


def _patroon(regel: str) -> re.Pattern[str]:
    eind = regel.endswith("$")
    kern = regel[:-1] if eind else regel
    rx = "".join(".*" if c == "*" else re.escape(c) for c in kern)
    return re.compile("^" + rx + ("$" if eind else ""))


def mag_ophalen(url: str, regels: list[tuple[str, str]]) -> tuple[bool, str]:
    """Google-semantiek: langste overeenkomende regel wint, Allow bij gelijkspel."""
    deel = urlparse(url)
    pad = deel.path + (f"?{deel.query}" if deel.query else "")
    beste: tuple[int, bool, str] | None = None
    for soort, waarde in regels:
        if not waarde:
            continue
        if _patroon(waarde).match(pad):
            lengte = len(waarde)
            toestaan = soort == "allow"
            if beste is None or lengte > beste[0] or (lengte == beste[0] and toestaan):
                beste = (lengte, toestaan, f"{soort}: {waarde}")
    if beste is None:
        return True, "geen regel"
    return beste[1], beste[2]


# -- sitemaps -----------------------------------------------------------------

def body_tekst(resp) -> tuple[str, bool]:
    ruw = resp.content or b""
    is_gzip = ruw[:2] == b"\x1f\x8b"
    if is_gzip:
        try:
            ruw = gzip.decompress(ruw)
        except Exception as exc:  # noqa: BLE001
            return f"<gzip kapot: {exc}>", True
    return ruw.decode("utf-8", errors="replace"), is_gzip


def ontleed_sitemap(tekst: str) -> dict:
    soort = "index" if re.search(r"<sitemapindex", tekst, re.I) else (
        "urlset" if re.search(r"<urlset", tekst, re.I) else "onbekend")
    items: list[tuple[str, str | None]] = []
    for _tag, blok in URL_BLOK_RE.findall(tekst):
        loc = LOC_RE.search(blok)
        if not loc:
            continue
        lm = LASTMOD_RE.search(blok)
        items.append((loc.group(1).replace("&amp;", "&"), lm.group(1) if lm else None))
    if not items:
        items = [(u, None) for u in LOC_RE.findall(tekst)]
    return {"soort": soort, "items": items,
            "n_loc": len(LOC_RE.findall(tekst)),
            "n_lastmod": len(LASTMOD_RE.findall(tekst))}


def parse_datum(waarde: str | None) -> datetime | None:
    if not waarde:
        return None
    w = waarde.strip().replace("Z", "+00:00")
    for poging in (w, w[:19], w[:10]):
        try:
            d = datetime.fromisoformat(poging)
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    return None


def tiny_uit(url: str) -> str | None:
    m = TINY_RE.search(url) or TINY_OUD_RE.search(url)
    return m.group(1) if m else None


def stad_uit(url: str) -> str | None:
    pad = urlparse(url).path
    m = re.match(r"^/(?:detail/)?koop/([^/]+)/", pad)
    return m.group(1) if m else None


def relevantie(url: str) -> int:
    """Hoe waarschijnlijk gaat een kind-sitemap over koopwoningen?"""
    u = url.lower()
    score = 0
    for woord, punten in (("koop", 4), ("detail", 3), ("listing", 3), ("object", 2),
                          ("woning", 2), ("aanbod", 2), ("wonen", 1), ("den-haag", 3),
                          ("voorburg", 3), ("zuid-holland", 2)):
        if woord in u:
            score += punten
    for woord in ("huur", "makelaar", "blog", "nieuwbouw", "meer-weten", "artikel",
                  "europe", "en/", "recreatie", "bedrijf", "agrarisch", "parkeer"):
        if woord in u:
            score -= 4
    return score


def meet_sitemap(t: Teller, url: str, regels: list[tuple[str, str]], niveau: int) -> dict | None:
    inspring = "  " * niveau
    ok, waarom = mag_ophalen(url, regels)
    if not ok:
        print(f"{inspring}OVERGESLAGEN (robots.txt {waarom}): {url}")
        return None
    try:
        resp = t.get(url)
    except Exception as exc:  # noqa: BLE001
        print(f"{inspring}EXC {type(exc).__name__}: {str(exc)[:120]} | {url}")
        return None
    tekst, is_gzip = body_tekst(resp)
    hdr = {k: resp.headers.get(k) for k in INTERESSANTE_HEADERS if resp.headers.get(k)}
    print(f"{inspring}[{t.n:2}] {resp.status_code} {url}")
    print(f"{inspring}     bytes={len(resp.content or b'')} gzip-body={is_gzip} "
          f"headers={json.dumps(hdr, ensure_ascii=False)}")
    if resp.status_code != 200:
        print(f"{inspring}     body-begin: {tekst[:160]!r}")
        return {"url": url, "status": resp.status_code}
    if "Je bent bijna op de pagina" in tekst or "<html" in tekst[:500].lower():
        print(f"{inspring}     LET OP: HTML i.p.v. XML (bot-controle of foutpagina). "
              f"Titel: {re.search(r'<title>(.*?)</title>', tekst, re.S).group(1)[:80] if '<title>' in tekst else '-'}")
        return {"url": url, "status": resp.status_code, "html": True}
    info = ontleed_sitemap(tekst)
    info.update({"url": url, "status": resp.status_code, "gzip": is_gzip})
    lastmods = sorted(d for d in (parse_datum(lm) for _u, lm in info["items"]) if d)
    print(f"{inspring}     soort={info['soort']} <loc>={info['n_loc']} <lastmod>={info['n_lastmod']}"
          + (f" lastmod {lastmods[0].isoformat()} .. {lastmods[-1].isoformat()}" if lastmods else ""))
    for u, lm in info["items"][:3]:
        print(f"{inspring}     voorbeeld: {u}  lastmod={lm}")
    return info


# -- verrijken ----------------------------------------------------------------

def verrijk(kandidaten: list[tuple[str, str | None]], budget: int) -> list[dict]:
    """get_listing via pyfunda (zelfde client als funda_zoek.py)."""
    if budget <= 1:
        print("Geen budget meer voor detail-calls.")
        return []
    # De gepatchte client van de dagelijkse run, niet pyfunda zelf: die doet zich
    # voor als funda's app en loopt bij een weigering alle vingerafdrukken af.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from funda_zoek import Funda

    f = Funda()
    uit: list[dict] = []
    for url, lm in kandidaten[:budget]:
        time.sleep(PAUZE)
        try:
            listing = f.get_listing(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  detail MISLUKT {url}: {type(exc).__name__}: {str(exc)[:100]}")
            uit.append({"url": url, "fout": str(exc)[:100]})
            continue
        d = dict(listing.data or {})
        prijs = d.get("price")
        m2 = d.get("living_area")
        in_doel = (
            d.get("status") == "available"
            and isinstance(prijs, (int, float)) and DOEL_PRIJS[0] <= prijs <= DOEL_PRIJS[1]
            and isinstance(m2, (int, float)) and m2 >= DOEL_M2
            and (d.get("object_type") or "").lower() in ("apartment", "appartement", "")
        )
        rij = {
            "tiny_id": d.get("tiny_id"), "adres": d.get("title"), "stad": d.get("city"),
            "prijs": prijs, "m2": m2, "type": d.get("object_type"), "soort": d.get("house_type"),
            "status": d.get("status"), "publicatie": d.get("publication_date"),
            "aangeboden_sinds": d.get("offered_since"), "lastmod": lm, "in_doelmarkt": in_doel,
        }
        print("  detail " + json.dumps(rij, ensure_ascii=False))
        uit.append(rij)
    return uit


# -- hoofdroutine -------------------------------------------------------------

def main() -> int:
    nu = datetime.now(timezone.utc)
    print(f"Sitemap-probe, start {nu.isoformat(timespec='seconds')}; budget {MAX_VERZOEKEN} "
          f"verzoeken, pauze {PAUZE}s, profiel {IMPERSONATE}.\n")
    t = Teller()

    # 1. robots.txt
    print("=== 1. robots.txt ===")
    try:
        resp = t.get(ROBOTS_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"robots.txt: EXC {type(exc).__name__}: {exc}")
        return 0
    robots, _gz = body_tekst(resp)
    hdr = {k: resp.headers.get(k) for k in INTERESSANTE_HEADERS if resp.headers.get(k)}
    print(f"status={resp.status_code} bytes={len(resp.content or b'')} headers={json.dumps(hdr)}")
    if resp.status_code != 200 or "<html" in robots[:500].lower():
        print("robots.txt is niet de echte robots.txt (status of HTML). Begin body:")
        print(robots[:600])
        print("\nStop: zonder robots.txt geen sitemaplijst en geen regels om te respecteren.")
        return 0
    print("----- begin robots.txt -----")
    print(robots.rstrip())
    print("----- einde robots.txt -----\n")

    sitemaps, groepen = parse_robots(robots)
    regels_ster = groepen.get("*", [])
    print(f"Sitemap-regels ({len(sitemaps)}):")
    for s in sitemaps:
        print(f"  {s}")
    print(f"User-agent-groepen: {sorted(groepen)}")
    print("Regels voor * die /detail/, /koop/, /zoeken/ of sitemap raken:")
    for soort, waarde in regels_ster:
        if any(w in waarde.lower() for w in ("/detail", "/koop", "/zoeken", "sitemap")):
            print(f"  {soort}: {waarde}")
    for test in ("https://www.funda.nl/detail/koop/den-haag/appartement-x-1/44000000/",
                 "https://www.funda.nl/koop/den-haag/",
                 "https://www.funda.nl/zoeken/koop?selected_area=%5B%22den-haag%22%5D"):
        ok, waarom = mag_ophalen(test, regels_ster)
        print(f"  robots-oordeel voor {urlparse(test).path}: {'toegestaan' if ok else 'VERBODEN'} ({waarom})")
    print()

    extra = [u.strip() for u in (os.environ.get("SITEMAP_EXTRA") or "").split(",") if u.strip()]
    if not sitemaps and not extra:
        print("Geen Sitemap:-regels in robots.txt. Stop.")
        return 0

    # 2. sitemaps (indexen) ophalen
    print("=== 2. sitemaps ===")
    alle_urls: dict[str, str | None] = {}
    indexen_kinderen: list[tuple[str, str | None]] = []
    bezocht: set[str] = set()

    def verwerk(info: dict | None) -> None:
        if not info or "items" not in info:
            return
        if info["soort"] == "index":
            indexen_kinderen.extend(info["items"])
            namen = Counter(re.sub(r"\d+", "#", urlparse(u).path) for u, _ in info["items"])
            print(f"     kind-sitemaps per naampatroon: {dict(namen.most_common(25))}")
        else:
            for u, lm in info["items"]:
                alle_urls[u] = lm

    for s in sitemaps + extra:
        if s in bezocht or t.over() <= MAX_DETAIL + 1:
            continue
        bezocht.add(s)
        verwerk(meet_sitemap(t, s, regels_ster, 1))

    # Kinderen kiezen: meest relevant eerst, binnen gelijke relevantie de nieuwste.
    ronde = 0
    while indexen_kinderen and ronde < 3:
        ronde += 1
        kandidaten = [(u, lm) for u, lm in indexen_kinderen if u not in bezocht]
        indexen_kinderen = []
        kandidaten.sort(key=lambda x: (relevantie(x[0]),
                                       parse_datum(x[1]) or datetime.min.replace(tzinfo=timezone.utc)),
                        reverse=True)
        print(f"\n  ronde {ronde}: {len(kandidaten)} kind-sitemaps; top 15 op relevantie/lastmod:")
        for u, lm in kandidaten[:15]:
            print(f"    score={relevantie(u):3} lastmod={lm} {u}")
        gekozen = [k for k in kandidaten if relevantie(k[0]) > 0] or kandidaten
        for u, _lm in gekozen[:MAX_KINDEREN]:
            if t.over() <= MAX_DETAIL + 1:
                print("  (budget gereserveerd voor detail-calls; stop met sitemaps)")
                break
            bezocht.add(u)
            verwerk(meet_sitemap(t, u, regels_ster, 2))

    # 3. tellen
    print("\n=== 3. woning-URL's in de opgehaalde sitemaps ===")
    print(f"URL's totaal: {len(alle_urls)}")
    per_soort = Counter()
    for u in alle_urls:
        pad = urlparse(u).path
        per_soort[re.sub(r"^(/[^/]+(?:/[^/]+)?).*", r"\1", pad)] += 1
    print(f"Per padvoorvoegsel: {dict(per_soort.most_common(15))}")

    doel: list[tuple[str, str | None]] = []
    per_stad = Counter()
    for u, lm in alle_urls.items():
        stad = stad_uit(u)
        if stad:
            per_stad[stad] += 1
        if stad in DOEL_STEDEN:
            doel.append((u, lm))
    print(f"Koop-URL's per stad (top 10): {dict(per_stad.most_common(10))}")
    print(f"Den Haag: {per_stad.get('den-haag', 0)}, Voorburg: {per_stad.get('voorburg', 0)}")
    appart = [x for x in doel if "/appartement-" in x[0] or re.search(r"/koop/[^/]+/appartement", x[0])]
    print(f"Waarvan appartement volgens slug: {len(appart)}")

    met_lm = [(u, lm, parse_datum(lm)) for u, lm in doel if parse_datum(lm)]
    print(f"Doelstad-URL's met lastmod: {len(met_lm)} van {len(doel)}")
    if met_lm:
        met_lm.sort(key=lambda x: x[2], reverse=True)
        nieuwste = met_lm[0][2]
        print(f"Nieuwste lastmod: {nieuwste.isoformat()} ({(nu - nieuwste).total_seconds() / 3600:.1f} uur voor de run)")
        for dagen in (1, 3, 7, 30):
            n = sum(1 for _u, _l, d in met_lm if (nu - d).days < dagen)
            print(f"  lastmod < {dagen:2} dag(en): {n}")
        print("Tien nieuwste:")
        for u, lm, _d in met_lm[:10]:
            print(f"  {lm} {u}")

    gevonden_tiny = {tiny_uit(u) for u in alle_urls}
    treffers = sorted(MAIL_SEEDS & gevonden_tiny)
    print(f"\nRecall op seeds uit de mailperiode: {len(treffers)} van {len(MAIL_SEEDS)} "
          f"in de opgehaalde sitemaps: {treffers}")
    if alle_urls and not treffers:
        print("  (let op: alleen de opgehaalde deel-sitemaps zijn doorzocht)")

    # 4. verrijken
    print("\n=== 4. verrijken via het detail-endpoint ===")
    if not doel:
        print("Geen Den Haag/Voorburg-URL's gevonden; niets te verrijken.")
    else:
        if met_lm:
            volgorde = [(u, lm) for u, lm, _d in met_lm if (u, lm) in set(appart)] or \
                       [(u, lm) for u, lm, _d in met_lm]
        else:
            # Zonder lastmod: hoogste tiny_id is een redelijke benadering van nieuwst.
            volgorde = sorted(appart or doel, key=lambda x: int(tiny_uit(x[0]) or 0), reverse=True)
            print("Geen lastmod: kies op hoogste tiny_id.")
        budget = min(MAX_DETAIL + 1, t.over())
        rijen = verrijk(volgorde, budget)
        ok = [r for r in rijen if "fout" not in r]
        print(f"\nVerrijkt: {len(ok)} van {len(rijen)}; in doelmarkt: "
              f"{sum(1 for r in ok if r['in_doelmarkt'])}; status available: "
              f"{sum(1 for r in ok if r['status'] == 'available')}")
        t.n += len(rijen) + 1  # detail-calls (plus pyfunda's testverzoek) in de telling

    print(f"\nVerzoeken gebruikt: ~{t.n} (max {MAX_VERZOEKEN}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
