"""Offline tests voor funda_rente. Geen netwerk nodig.

De fixtures zijn ingekort uit de meting van 7 nov 2026 (testdata/rente/): de links
uit het ASN-rentearchief, de tekst van het tariefblad van 6 november 2026 zoals pypdf
die uitpakt, het DNB-cijfer via het ECB Data Portal en de robots.txt van asnbank.nl.

Draaien: python test_funda_rente.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import funda_rente as r

HIER = Path(__file__).resolve().parent
TD = HIER / "testdata" / "rente"
UA = "funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)"
VANDAAG = "2026-11-07"
STIL = lambda *_: None  # noqa: E731
CONTRACT = {"pct", "bron", "datum", "oud", "melding"}


def check(naam: str, ok: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if ok else 'FOUT'} {naam}{(' -> ' + extra) if extra and not ok else ''}")
    return ok


def lees(naam: str) -> str:
    return (TD / naam).read_text(encoding="utf-8")


PAGINAS = json.loads(lees("asn_tarieven_paginas.json"))["paginas"]


def nep_pdf(body: bytes) -> list[str]:
    return list(PAGINAS)


class NepWeb:
    def __init__(self):
        self.calls: list[str] = []
        self.headers: list[dict] = []
        self.status: dict[str, int] = {}
        self.robots = {"www.asnbank.nl": (200, lees("robots_asnbank.txt").encode())}
        self.archief = lees("asn_archief.html")
        self.pdf = b"%PDF-1.7 nep"

    def aantal(self, host: str) -> int:
        return sum(1 for u in self.calls if urllib.parse.urlparse(u).hostname == host)

    def __call__(self, url, timeout=None, headers=None):
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        d = urllib.parse.urlparse(url)
        if d.path == "/robots.txt":
            return self.robots.get(d.hostname, (404, b""))
        if d.hostname in self.status:
            return self.status[d.hostname], b""
        if url == r.ASN_ARCHIEF:
            return 200, self.archief.encode()
        if d.hostname == "www.asnbank.nl" and d.path.startswith("/downloads/rentetarieven-asn-hypotheek-per-"):
            return 200, self.pdf
        if url == r.ECB_MIR_NL:
            return 200, lees("ecb_mir_nl.csv").encode()
        return 404, b""


def rente(cfg, cache, web, vandaag=VANDAAG, logs=None):
    return r.huidige_rente(cfg, cache, vandaag, http=web, ua=UA, log=(logs.append if logs is not None else STIL),
                           pdf_tekst=nep_pdf, slaap=lambda s: None)


def test_parsers() -> bool:
    print("Parsers op de gemeten antwoorden")
    links = r.asn_links(lees("asn_archief.html"))
    ok = check("alleen ASN Hypotheek, geen Bespaarhypotheek",
               links and all("asn-hypotheek-per" in u for _, u in links))
    ok &= check("nieuwste eerst: 6 november 2026",
                links[0][0].isoformat() == "2026-11-06" and links[0][1].endswith("per-6-november-2026.html"))
    ok &= check("dubbele link één keer", len({u for _, u in links}) == len(links))
    aug = {u.rsplit("/", 1)[1]: d.isoformat() for d, u in links if "augustus" in u}
    ok &= check("datum uit de linktekst, niet uit de bestandsnaam",
                aug.get("rentetarieven-asn-hypotheek-per-22-augustus-2026.html") == "2026-08-08"
                and aug.get("rentetarieven-asn-hypotheek-per-22-augustus-2026-1.html") == "2026-08-22", str(aug))
    datum, tabel = r.asn_tabel(PAGINAS)
    ok &= check("ingangsdatum uit het blad", datum is not None and datum.isoformat() == "2026-11-06")
    ok &= check("elf rentevastperiodes, zes tariefgroepen", len(tabel) == 11 and all(len(x) == 6 for x in tabel.values()))
    ok &= check("10 jaar NHG = 4,29%", tabel["10"][0] == 4.29)
    ok &= check("20 jaar > 106% = 5,38%", tabel["20"][5] == 5.38)
    _, omgekeerd = r.asn_tabel(list(reversed(PAGINAS)))
    ok &= check("niet de Duurzaam Wonen-tabel (3,29%), ook niet als die eerst staat", omgekeerd["10"][0] == 4.29)
    ok &= check("aflossingsvrij wordt niet gelezen", r.asn_tabel([PAGINAS[1]])[1] == {})
    ok &= check("kiezen: 10 jaar NHG", r.asn_kies(tabel, 10, True, 100) == (4.29, 10, None))
    ok &= check("kiezen: zonder NHG bij 100% = kolom <= 106%", r.asn_kies(tabel, 10, False, 100)[0] == 4.57)
    ok &= check("kiezen: zonder NHG bij 75% = kolom <= 80%", r.asn_kies(tabel, 10, False, 75)[0] == 4.49)
    pct, j, mel = r.asn_kies(tabel, 30, True, 100)
    ok &= check("30 jaar bestaat niet: 20 jaar met melding", pct == 4.74 and j == 20 and "20 jaar" in mel)
    dnb = r.dnb_parse(lees("ecb_mir_nl.csv"))
    ok &= check("DNB: september 2026, peildatum laatste dag",
                dnb["periode"] == "2026-09" and dnb["datum"] == "2026-09-30")
    ok &= check("DNB: vier klassen", dnb["reeks"] == {"F": 4.36, "I": 4.2, "O": 3.87, "P": 3.28}, str(dnb["reeks"]))
    ok &= check("DNB-klasse bij 10 jaar = 5 tot 10 jaar", r.dnb_kies(dnb["reeks"], 10) == (3.87, "5 tot 10 jaar"))
    ok &= check("DNB-klasse bij 20 jaar en 1 jaar",
                r.dnb_kies(dnb["reeks"], 20)[0] == 3.28 and r.dnb_kies(dnb["reeks"], 1)[0] == 4.36)
    ok &= check("lege CSV = fout", _gooit(lambda: r.dnb_parse("KEY,REF_AREA\n"), r.BronFout))
    ok &= check("geen PDF = fout uit pypdf-route", _gooit(lambda: r.pdf_tekst_pypdf(b"%PDF-kapot"), r.BronFout))
    return ok


def _gooit(f, soort) -> bool:
    try:
        f()
    except soort:
        return True
    return False


def test_handmatig() -> bool:
    print("Handmatige rente gaat altijd voor")
    web = NepWeb()
    uit = rente({"financien": {"rente": {"pct": 4.15, "datum": "2026-11-01"}}}, {}, web)
    ok = check("bron handmatig, geen verzoek", uit["bron"] == "handmatig" and not web.calls)
    ok &= check("waarde en datum", uit["pct"] == 4.15 and uit["datum"] == "2026-11-01" and uit["oud"] is False)
    ok &= check("contract", set(uit) == CONTRACT and isinstance(uit["pct"], float))
    uit = rente({"financien": {"rente": {"pct": 0.0415, "datum": "2026-09-01"}}}, {}, NepWeb())
    ok &= check("0,0415 wordt 4,15%", uit["pct"] == 4.15)
    ok &= check("ouder dan 30 dagen = oud met melding", uit["oud"] is True and "ouder dan 30 dagen" in uit["melding"])
    uit = rente({"financien": {"rente": {"pct": 4.0}}}, {}, NepWeb())
    ok &= check("zonder datum: datum None, oud, vraag om datum",
                uit["datum"] is None and uit["oud"] is True and "financien.rente.datum" in uit["melding"])
    uit = rente({"beoordeling": {"financien": {"rente": {"pct": 4.2, "datum": VANDAAG}}}}, {}, NepWeb())
    ok &= check("ook onder beoordeling.financien", uit["bron"] == "handmatig" and uit["pct"] == 4.2)
    return ok


def test_asn() -> bool:
    print("ASN: archief, nieuwste tariefblad, één keer per dag")
    web = NepWeb()
    cache: dict = {"price_history": {}}
    logs: list[str] = []
    uit = rente({}, cache, web, logs=logs)
    ok = check("bron ASN, 4,29%, 6 november", uit == {"pct": 4.29, "bron": "ASN", "datum": "2026-11-06", "oud": False,
                                                     "melding": None}, str(uit))
    ok &= check("drie verzoeken: robots, archief, blad", len(web.calls) == 3, str(web.calls))
    ok &= check("robots.txt eerst", web.calls[0] == "https://www.asnbank.nl/robots.txt")
    ok &= check("eerlijke user-agent", {h.get("User-Agent") for h in web.headers} == {UA})
    ok &= check("geen DNB nodig", web.aantal("data-api.ecb.europa.eu") == 0)
    ok &= check("cache-sectie rente, andere secties blijven", "rente" in cache and "price_history" in cache
                and cache["rente"]["laatste_poging"] == VANDAAG and cache["rente"]["asn"]["tabel"]["10"][0] == 4.29)
    web2 = NepWeb()
    uit2 = rente({}, cache, web2)
    ok &= check("zelfde dag: geen verzoek, zelfde uitkomst", not web2.calls and uit2 == uit)
    uit3 = rente({"financien": {"rente": {"rentevast_jaren": 20, "nhg": False}}}, cache, NepWeb())
    ok &= check("andere instelling zelfde dag: uit de bewaarde tabel", uit3["pct"] == 4.98)
    web4 = NepWeb()
    rente({}, cache, web4, vandaag="2026-11-08")
    # robots.txt is hooguit een dag vers (RFC 9309 par. 2.4), dus de volgende dag eerst opnieuw.
    ok &= check("volgende dag: opnieuw opgehaald, robots.txt eerst", len(web4.calls) == 3
                and web4.calls[0] == "https://www.asnbank.nl/robots.txt", str(web4.calls))
    uit5 = rente({"financien": {"rente": {"rentevast_jaren": 30}}}, {}, NepWeb())
    ok &= check("rentevast 30: 20 jaar met melding", uit5["pct"] == 4.74 and "geen rentevast 30 jaar" in uit5["melding"])
    web6 = NepWeb()
    uit6 = rente({}, {}, web6, vandaag="2026-11-05")
    ok &= check("blad met een latere ingangsdatum wordt overgeslagen",
                any("per-1-november-2026" in u for u in web6.calls) and not any("per-6-november" in u for u in web6.calls)
                and uit6["bron"] == "ASN")
    ok &= check("logregel zonder bedragen in euro's", logs and not any("€" in x for x in logs))
    return ok


def test_terugval() -> bool:
    print("Terugval: DNB, daarna standaard; nooit een uitzondering")
    web = NepWeb()
    web.status["www.asnbank.nl"] = 403
    cache: dict = {}
    uit = rente({}, cache, web)
    ok = check("ASN weigert: DNB", uit["bron"] == "DNB" and uit["pct"] == 3.87 and uit["datum"] == "2026-09-30", str(uit))
    ok &= check("ASN één keer gevraagd (plus robots), geen omweg",
                [urllib.parse.urlparse(u).path for u in web.calls if "asnbank" in u] == ["/robots.txt",
                 "/hypotheek/hypotheekrentes/hypotheekrente-archief.html"])
    ok &= check("melding noemt ASN en DNB", "ASN niet bereikbaar" in uit["melding"] and "(DNB)" in uit["melding"])
    ok &= check("DNB-cijfer van september is op 7 november oud", uit["oud"] is True)
    ok &= check("weigering bewaard", cache.get("verrijking_weigering", {}).get("www.asnbank.nl", {}).get("status") == 403)
    web2 = NepWeb()
    web2.status["www.asnbank.nl"] = 503
    web2.status["data-api.ecb.europa.eu"] = 500
    uit2 = rente({}, {}, web2)
    ok &= check("alles kapot: standaard 4,11% met melding", uit2["bron"] == "standaard" and uit2["pct"] == 4.11
                and uit2["datum"] == "2026-07-06" and uit2["oud"] is True and "financien.rente.pct" in uit2["melding"])
    ok &= check("contract ook dan", set(uit2) == CONTRACT)
    # Gisteren ASN gelukt, vandaag niet: het blad van gisteren wint van het oudere DNB-cijfer.
    cache3: dict = {}
    rente({}, cache3, NepWeb(), vandaag="2026-11-07")
    web3 = NepWeb()
    web3.status["www.asnbank.nl"] = 500
    uit3 = rente({}, cache3, web3, vandaag="2026-11-08")
    ok &= check("blad van gisteren gaat voor DNB", uit3["bron"] == "ASN" and uit3["pct"] == 4.29)
    ok &= check("met melding dat vandaag mislukte", "vandaag niet opgehaald" in (uit3["melding"] or ""))
    # Een blad zonder PDF of zonder tabel is een fout, geen gok.
    web4 = NepWeb()
    web4.pdf = b"<html>geen pdf</html>"
    ok &= check("geen PDF: DNB", rente({}, {}, web4)["bron"] == "DNB")
    web5 = NepWeb()
    uit5 = r.huidige_rente({}, {}, VANDAAG, http=web5, ua=UA, log=STIL, pdf_tekst=lambda b: ["iets anders"],
                           slaap=lambda s: None)
    ok &= check("blad zonder tabel: DNB", uit5["bron"] == "DNB")
    web6 = NepWeb()
    web6.robots["www.asnbank.nl"] = (200, b"User-agent: *\nDisallow: /downloads/\n")
    uit6 = rente({}, {}, web6)
    ok &= check("robots verbiedt de bladen: niet opgehaald, DNB",
                uit6["bron"] == "DNB" and not any("/downloads/" in u for u in web6.calls))
    web7 = NepWeb()
    uit7 = rente({"financien": {"rente": {"bron": "uit"}}}, {}, web7)
    ok &= check("bron uit: geen verzoek, standaard", not web7.calls and uit7["bron"] == "standaard")
    web8 = NepWeb()
    uit8 = rente({"financien": {"rente": {"bron": "dnb"}}}, {}, web8)
    ok &= check("bron dnb: alleen DNB", uit8["bron"] == "DNB" and web8.aantal("www.asnbank.nl") == 0)

    def ontploft(url, timeout=None, headers=None):
        raise RuntimeError("stuk")
    uit9 = r.huidige_rente({}, {}, VANDAAG, http=ontploft, ua=UA, log=STIL, slaap=lambda s: None)
    ok &= check("http gooit: geen uitzondering, standaard", uit9["bron"] == "standaard")
    return ok


def main() -> int:
    resultaten = [test_parsers(), test_handmatig(), test_asn(), test_terugval()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
