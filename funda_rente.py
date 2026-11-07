"""Actuele hypotheekrente voor het woningrapport (besluiten.md punt 5).

Volgorde, de eerste die lukt:
1. handmatig: financien.rente.pct (met financien.rente.datum) in de config. Gaat altijd
   voor en kost geen verzoek.
2. ASN: de tariefbladen die ASN zelf publiceert. De rentepagina
   (www.asnbank.nl/hypotheek/hypotheekrentes.html) laadt de tabel met JavaScript uit een
   eigen API die een sleutel uit de JavaScript-bundel vraagt; die gebruiken we niet.
   Dezelfde pagina linkt naar het rentearchief met per wijziging een statisch tariefblad
   (PDF achter een .html-link, "Rentetarieven ASN Hypotheek per <datum>"). Het nieuwste
   blad tot en met vandaag geeft de tabel annuïteiten en lineair: rentevast 1 tot 20 jaar
   tegen de tariefgroepen (NHG, <= 60%, <= 80%, <= 90%, <= 106%, > 106%).
3. DNB: het maandcijfer "rente op nieuwe hypotheken" naar rentevastklasse. De eigen
   DNB-API vraagt een abonnementssleutel; hetzelfde DNB-cijfer staat open in het ECB
   Data Portal (dataset MIR, Nederland, bron NL2 = DNB). Eén CSV-verzoek, vier klassen.
4. standaard: 4,11% (laagste NHG 30 jaar vast, 6 juli 2026, uit de audit), met melding.

Hooguit één poging per dag (cache-sectie "rente" in funda_enrichment_cache.json). Een
ASN-blad of DNB-cijfer van een eerdere dag blijft bruikbaar; de nieuwste datum wint.
robots.txt per host eerst (www.asnbank.nl en data-api.ecb.europa.eu staan het toe,
gemeten 7 nov 2026), hooguit een dag gecacht. Netwerk via dezelfde Sessie als
funda_verrijking: eerlijke user-agent, time-outs, stoppen bij 401/403/429/5xx, nooit een omweg.

Publiek: huidige_rente(cfg, cache, vandaag, http=None) -> {"pct", "bron", "datum", "oud", "melding"}.
"""

from __future__ import annotations

import calendar
import csv
import io
import logging
import re
import time
from datetime import date

from funda_verrijking import BronFout, GeenBudget, Sessie, _datum

ASN_ARCHIEF = "https://www.asnbank.nl/hypotheek/hypotheekrentes/hypotheekrente-archief.html"
ASN_BASIS = "https://www.asnbank.nl"
ECB_MIR_NL = ("https://data-api.ecb.europa.eu/service/data/MIR/M.NL.B.A2C.F+I+O+P.R.A.2250.EUR.N"
              "?lastNObservations=1&format=csvdata")
# ECB-code voor de rentevastklasse: F = variabel tot 1 jaar, I = 1 tot 5, O = 5 tot 10, P = langer dan 10.
DNB_KLASSEN = (("F", 1, "tot 1 jaar"), ("I", 5, "1 tot 5 jaar"), ("O", 10, "5 tot 10 jaar"),
               ("P", 99, "langer dan 10 jaar"))

STANDAARD_PCT = 4.11
STANDAARD_DATUM = "2026-07-06"
OUD_NA_DAGEN = 30
MAANDEN = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
           "september": 9, "oktober": 10, "november": 11, "december": 12}
MAAND_NAAM = {v: k for k, v in MAANDEN.items()}
# Kolommen van het ASN-blad: 0 = NHG, daarna de tariefgroepen naar marktwaarde (bovengrens in %).
ASN_TARIEFGROEPEN = ((60, 1), (80, 2), (90, 3), (106, 4), (float("inf"), 5))

STANDAARD = {"pct": None, "datum": None, "rentevast_jaren": 10, "nhg": True, "ltv": 100, "bron": "auto",
             "max_dagen": OUD_NA_DAGEN}


def instellingen(cfg: dict | None) -> dict:
    """financien.rente uit de config, aangevuld met de standaard."""
    cfg = cfg or {}
    fin = cfg.get("financien")
    if not isinstance(fin, dict) and isinstance(cfg.get("beoordeling"), dict):
        fin = cfg["beoordeling"].get("financien")
    r = (fin or {}).get("rente") if isinstance(fin, dict) else None
    uit = dict(STANDAARD)
    if isinstance(r, dict):
        uit.update({k: r[k] for k in STANDAARD if k in r})
    return uit


def _nl(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def datum_nl(d) -> str:
    d = _datum(d)
    return f"{d.day} {MAAND_NAAM[d.month]} {d.year}"


def _datum_uit_tekst(tekst: str) -> date | None:
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(MAANDEN) + r")\s+(\d{4})\b", tekst or "", flags=re.I)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MAANDEN[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


# ---------------------------------------------------------------- ASN

def asn_links(html: str) -> list[tuple[date, str]]:
    """Tariefbladen "ASN Hypotheek" (niet Bespaarhypotheek) uit het archief, nieuwste eerst.

    De datum komt uit de linktekst of de title ("per 8 augustus 2026"), niet uit de
    bestandsnaam: gemeten op 7 nov 2026 heette het blad van 8 augustus
    "...-per-22-augustus-2026.html"."""
    gezien, uit = set(), []
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html or "", flags=re.S | re.I):
        attrs, tekst = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        href = re.search(r'href="([^"]+)"', attrs)
        if not href or not re.match(r"/downloads/rentetarieven-asn-hypotheek-per-[\w-]+\.html$", href.group(1)):
            continue
        titel = re.search(r'title="([^"]*)"', attrs)
        d = _datum_uit_tekst(tekst) or _datum_uit_tekst(titel.group(1) if titel else "")
        if not d or href.group(1) in gezien:
            continue
        gezien.add(href.group(1))
        uit.append((d, ASN_BASIS + href.group(1)))
    return sorted(uit, key=lambda x: x[0], reverse=True)


def asn_tabel(paginas: list[str]) -> tuple[date | None, dict[str, list[float]]]:
    """(met ingang van, {rentevast_jaren: [NHG, <=60, <=80, <=90, <=106, >106]}) uit de
    pagina "Tarieven Annuïteiten en Lineaire Hypotheken"."""
    for tekst in paginas or []:
        if not re.search(r"Annu.teiten en Lineaire Hypotheken", tekst or "") or "Duurzaam" in tekst:
            continue
        tabel = {}
        for regel in tekst.splitlines():
            m = re.match(r"\s*(\d{1,2})\s+jaar\s+(.*)$", regel)
            if not m:
                continue
            pcts = [float(x.replace(",", ".")) for x in re.findall(r"(\d{1,2},\d{1,3})\s*%", m.group(2))]
            if len(pcts) == 6 and all(0.1 <= p <= 20 for p in pcts):
                tabel[str(int(m.group(1)))] = pcts
        if tabel:
            return _datum_uit_tekst(tekst), tabel
    return None, {}


def asn_kies(tabel: dict[str, list[float]], jaren: int, nhg: bool, ltv: float) -> tuple[float, int, str | None]:
    """-> (pct, gebruikte rentevast_jaren, melding)."""
    rijen = sorted(int(k) for k in tabel)
    if not rijen:
        raise BronFout("lege tabel")
    melding = None
    if jaren in rijen:
        j = jaren
    else:
        lager = [r for r in rijen if r <= jaren]
        j = max(lager) if lager else min(rijen)
        melding = f"ASN kent geen rentevast {jaren} jaar; {j} jaar gebruikt."
    if nhg:
        kolom = 0
    else:
        kolom = next(k for grens, k in ASN_TARIEFGROEPEN if float(ltv) <= grens)
    return tabel[str(j)][kolom], j, melding


def pdf_tekst_pypdf(body: bytes) -> list[str]:
    try:
        import pypdf  # noqa: PLC0415
    except ImportError:
        raise BronFout("pypdf ontbreekt (zie requirements.txt)") from None
    logging.getLogger("pypdf").setLevel(logging.ERROR)     # geen waarschuwingen over kapotte PDF's in de log
    try:
        lezer = pypdf.PdfReader(io.BytesIO(body))
        return [p.extract_text() or "" for p in lezer.pages[:6]]
    except Exception as exc:  # noqa: BLE001
        raise BronFout(f"tariefblad niet te lezen ({type(exc).__name__})") from None


def asn_ophalen(sessie: Sessie, vandaag, pdf_tekst=None) -> dict:
    html = sessie.haal(ASN_ARCHIEF, "text/html").decode("utf-8", "replace")
    links = [(d, u) for d, u in asn_links(html) if d <= _datum(vandaag)]
    if not links:
        raise BronFout("geen tariefblad in het archief")
    link_datum, url = links[0]
    body = sessie.haal(url, "application/pdf")
    if not body.startswith(b"%PDF"):
        raise BronFout("tariefblad is geen PDF")
    pdf_datum, tabel = asn_tabel((pdf_tekst or pdf_tekst_pypdf)(body))
    if not tabel:
        raise BronFout("tabel annuïteiten en lineair niet gevonden")
    return {"datum": (pdf_datum or link_datum).isoformat(), "opgehaald": _datum(vandaag).isoformat(),
            "tabel": tabel}


# ---------------------------------------------------------------- DNB (via ECB Data Portal)

def dnb_parse(tekst: str) -> dict:
    reeks, periodes = {}, set()
    for r in csv.DictReader(io.StringIO(tekst or "")):
        if r.get("REF_AREA") != "NL" or r.get("BS_ITEM") != "A2C":
            continue
        code = r.get("MATURITY_NOT_IRATE")
        try:
            waarde = float(r.get("OBS_VALUE") or "")
        except ValueError:
            continue
        if code in {c for c, _, _ in DNB_KLASSEN} and 0.1 <= waarde <= 20:
            reeks[code] = waarde
            periodes.add(r.get("TIME_PERIOD") or "")
    if not reeks:
        raise BronFout("geen DNB-cijfer in het antwoord")
    periode = max(periodes)
    m = re.fullmatch(r"(\d{4})-(\d{2})", periode)
    if not m:
        raise BronFout("onbekende periode")
    j, mnd = int(m.group(1)), int(m.group(2))
    laatste = date(j, mnd, calendar.monthrange(j, mnd)[1])
    return {"periode": periode, "datum": laatste.isoformat(), "reeks": reeks}


def dnb_kies(reeks: dict[str, float], jaren: int) -> tuple[float, str]:
    for code, tot, naam in DNB_KLASSEN:
        if jaren <= tot and code in reeks:
            return reeks[code], naam
    for code, _, naam in reversed(DNB_KLASSEN):
        if code in reeks:
            return reeks[code], naam
    raise BronFout("geen passende rentevastklasse")


def dnb_ophalen(sessie: Sessie, vandaag) -> dict:
    d = dnb_parse(sessie.haal(ECB_MIR_NL, "text/csv").decode("utf-8", "replace"))
    d["opgehaald"] = _datum(vandaag).isoformat()
    return d


# ---------------------------------------------------------------- publiek

def _uitkomst(pct: float, bron: str, datum: str | None, vandaag, max_dagen: int, meldingen: list[str]) -> dict:
    oud = True if not datum else (_datum(vandaag) - _datum(datum)).days > max_dagen
    if datum and oud:
        meldingen.append(f"De rente is van {datum_nl(datum)}, ouder dan {max_dagen} dagen.")
    return {"pct": round(float(pct), 2), "bron": bron, "datum": datum, "oud": oud,
            "melding": " ".join(m for m in meldingen if m) or None}


def huidige_rente(cfg: dict | None, cache: dict, vandaag, http=None, ua: str | None = None, log=print,
                  pdf_tekst=None, slaap=time.sleep) -> dict:
    """De rente om mee te rekenen. Fail-soft: gooit nooit.

    -> {"pct": float (procenten, 4.29 = 4,29%), "bron": "handmatig"|"ASN"|"DNB"|"standaard",
        "datum": "JJJJ-MM-DD" (peildatum van het cijfer; None bij een handmatige waarde zonder
        datum), "oud": bool (ouder dan 30 dagen), "melding": str|None}
    """
    r = instellingen(cfg)
    dag = _datum(vandaag).isoformat()
    max_dagen = int(r.get("max_dagen") or OUD_NA_DAGEN)
    try:
        jaren = int(r.get("rentevast_jaren") or 10)
    except (TypeError, ValueError):
        jaren = 10

    # 1. Handmatig gaat altijd voor.
    if r.get("pct") is not None:
        try:
            pct = float(r["pct"])
        except (TypeError, ValueError):
            pct = None
        if pct is not None:
            pct = pct * 100 if pct < 1 else pct            # 0.0429 en 4.29 betekenen allebei 4,29%
            datum = None
            try:
                datum = _datum(r["datum"]).isoformat() if r.get("datum") else None
            except ValueError:
                datum = None
            meldingen = [] if datum else ["Zet financien.rente.datum bij je handmatige rente."]
            log(f"[rente] handmatige waarde uit de config ({_nl(pct)}%)")
            return _uitkomst(pct, "handmatig", datum, dag, max_dagen, meldingen)

    sectie = cache.get("rente")
    if not isinstance(sectie, dict):
        sectie = cache["rente"] = {}
    bron = str(r.get("bron") or "auto").lower()

    # 2. Hooguit één poging per dag.
    if bron != "uit" and sectie.get("laatste_poging") != dag:
        sessie = Sessie(cache, dag, http=http, ua=ua, max_verzoeken=8, timeout_s=15, pauze_s=0.5, slaap=slaap)
        fouten: dict[str, str] = {}
        if bron in ("auto", "asn"):
            try:
                sectie["asn"] = asn_ophalen(sessie, dag, pdf_tekst)
            except (BronFout, GeenBudget) as exc:
                fouten["asn"] = str(exc) or type(exc).__name__
            except Exception as exc:  # noqa: BLE001
                fouten["asn"] = f"onverwacht antwoord ({type(exc).__name__})"
        if bron == "dnb" or (bron == "auto" and "asn" in fouten):
            try:
                sectie["dnb"] = dnb_ophalen(sessie, dag)
            except (BronFout, GeenBudget) as exc:
                fouten["dnb"] = str(exc) or type(exc).__name__
            except Exception as exc:  # noqa: BLE001
                fouten["dnb"] = f"onverwacht antwoord ({type(exc).__name__})"
        sectie["laatste_poging"] = dag
        sectie["fouten"] = fouten
        status = ", ".join(f"{h} {s}x{n}" for (h, s), n in sorted(sessie.per_host.items(), key=str))
        log(f"[rente] {sessie.gedaan} verzoeken" + (f" ({status})" if status else "")
            + ("; mislukt: " + ", ".join(sorted(fouten)) if fouten else ""))

    fouten = sectie.get("fouten") or {}
    kandidaten = []
    asn = sectie.get("asn")
    if bron in ("auto", "asn") and isinstance(asn, dict) and asn.get("tabel"):
        try:
            pct, j, mel = asn_kies(asn["tabel"], jaren, bool(r.get("nhg", True)), r.get("ltv") or 100)
            meldingen = [mel]
            if asn.get("opgehaald") != dag and "asn" in fouten:
                meldingen.insert(0, f"ASN-tarieven vandaag niet opgehaald ({fouten['asn']}); "
                                    f"laatste blad van {datum_nl(asn['datum'])}.")
            kandidaten.append((asn["datum"], 1, pct, "ASN", meldingen))
        except (BronFout, KeyError, IndexError, StopIteration, ValueError):
            pass
    dnb = sectie.get("dnb")
    if bron in ("auto", "dnb") and isinstance(dnb, dict) and dnb.get("reeks"):
        try:
            pct, klasse = dnb_kies(dnb["reeks"], jaren)
            meldingen = []
            if "asn" in fouten and bron == "auto":
                meldingen.append(f"ASN niet bereikbaar ({fouten['asn']}).")
            meldingen.append(f"Gemiddelde rente op nieuwe hypotheken, rentevast {klasse}, "
                             f"{MAAND_NAAM[_datum(dnb['datum']).month]} {_datum(dnb['datum']).year} (DNB), "
                             "geen aanbod van een bank.")
            kandidaten.append((dnb["datum"], 0, pct, "DNB", meldingen))
        except (BronFout, KeyError, ValueError):
            pass
    if kandidaten:
        datum, _, pct, naam, meldingen = max(kandidaten, key=lambda k: (k[0], k[1]))
        uit = _uitkomst(pct, naam, datum, dag, max_dagen, list(meldingen))
    else:
        redenen = "; ".join(f"{k.upper()}: {v}" for k, v in sorted(fouten.items()))
        uit = _uitkomst(STANDAARD_PCT, "standaard", STANDAARD_DATUM, dag, max_dagen,
                        [f"Geen actuele rente gevonden{' (' + redenen + ')' if redenen else ''}. "
                         f"Gerekend met {_nl(STANDAARD_PCT)}% van {datum_nl(STANDAARD_DATUM)}; "
                         "zet financien.rente.pct in je config."])
    log(f"[rente] bron {uit['bron']}, {_nl(uit['pct'])}%, peildatum {uit['datum']}" + (", oud" if uit["oud"] else ""))
    return uit
