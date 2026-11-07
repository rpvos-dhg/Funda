"""Offline tests voor funda_verrijking. Geen netwerk nodig.

De parsers draaien op de ingekorte antwoorden die op 7 nov 2026 zijn gemeten
(testdata/verrijking/, op openbare plekken: het Plein en het stadhuis in Den Haag).
De runs door verrijk() gebruiken een nep-HTTP-functie die per host antwoordt met
die vormen, ingevuld voor de 13 fictieve woningen uit testdata/woningen.json.

Draaien: python test_funda_verrijking.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import funda_verrijking as v

HIER = Path(__file__).resolve().parent
TD = HIER / "testdata" / "verrijking"
UA = "funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)"
VANDAAG = "2026-11-07"
STIL = lambda *_: None  # noqa: E731


def check(naam: str, ok: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if ok else 'FOUT'} {naam}{(' -> ' + extra) if extra and not ok else ''}")
    return ok


def fixture(naam: str):
    return json.loads((TD / naam).read_text(encoding="utf-8"))


def woningen() -> list[dict]:
    doc = json.loads((HIER / "testdata" / "woningen.json").read_text(encoding="utf-8"))
    return [copy.deepcopy(w["listing"]) for w in doc["woningen"]]


def dag(n: int) -> str:
    return (date.fromisoformat(VANDAAG) + timedelta(days=n)).isoformat()


def cfg(**verrijking) -> dict:
    basis = {"pauze_s": 0, "max_calls_per_run": 200}   # ruim, behalve in test_budget
    basis.update(verrijking)
    return {"verrijking": basis}


# ---------------------------------------------------------------- nep-web

class NepWeb:
    """Antwoordt per host in de gemeten vorm. Houdt elk verzoek bij."""

    def __init__(self, ws: list[dict]):
        self.ws = ws
        self.calls: list[str] = []
        self.headers: list[dict] = []
        self.status: dict[str, int] = {}          # host -> vaste status
        self.time_out: set[str] = set()           # hosts die nooit antwoorden
        self.robots: dict[str, tuple[int, bytes]] = {}
        self.kea: dict[str, tuple[float, float]] = {}      # global_id -> (verschilzetting, paalrot)
        self.geluid: dict[str, list] = {}                  # global_id -> 4 waarden
        self.pand: dict[str, int] = {}                     # global_id -> aantal_verblijfsobjecten
        self.lbm_extra = None
        buurten = sorted({w.get("neighbourhood") or "" for w in ws})
        self.code = {b: f"BU9{i:07d}" for i, b in enumerate(buurten)}

    def aantal(self, host: str | None = None, pad: str | None = None) -> int:
        n = 0
        for u in self.calls:
            d = urllib.parse.urlparse(u)
            if (host is None or d.hostname == host) and (pad is None or pad in d.path):
                n += 1
        return n

    def _bij(self, bbox: str) -> list[dict]:
        x1, y1, x2, y2 = (float(x) for x in bbox.split(","))
        return [w for w in self.ws if x1 <= w["longitude"] <= x2 and y1 <= w["latitude"] <= y2]

    def _midden(self, q: dict) -> dict | None:
        x1, y1, x2, y2 = (float(x) for x in q["bbox"][0].split(","))
        lon, lat = (x1 + x2) / 2, (y1 + y2) / 2
        for w in self.ws:
            if abs(w["latitude"] - lat) < 1e-5 and abs(w["longitude"] - lon) < 1e-5:
                return w
        return None

    @staticmethod
    def _gemeente(w: dict) -> str:
        return "Leidschendam-Voorburg" if "voorburg" in (w.get("city") or "").lower() else "'s-Gravenhage"

    def __call__(self, url: str, timeout=None, headers=None):
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        d = urllib.parse.urlparse(url)
        host, pad = d.hostname, d.path
        q = urllib.parse.parse_qs(d.query)
        if host in self.time_out:
            raise TimeoutError("nep")
        if pad == "/robots.txt":
            return self.robots.get(host, (404, b"niet gevonden"))
        if host in self.status:
            return self.status[host], b"{}"
        if host == "api.pdok.nl" and pad.endswith("/verblijfsobject/items"):
            basis = fixture("bag_verblijfsobject_bbox.json")
            sjabloon = basis["features"][0]
            fs = []
            for w in self._bij(q["bbox"][0]):
                f = copy.deepcopy(sjabloon)
                p = f["properties"]
                p.update({"postcode": w["postcode"].replace(" ", ""), "huisnummer": int(w["house_number"]),
                          "huisletter": None, "toevoeging": w.get("house_number_ext") or None,
                          "gebruiksdoel": "woonfunctie",
                          "pand.href": [v.BAG_PAND_PREFIX + f"pand-{w['global_id']}"]})
                fs.append(f)
            basis["features"], basis["numberReturned"] = fs, len(fs)
            return 200, json.dumps(basis).encode()
        if host == "api.pdok.nl" and "/pand/items/pand-" in pad:
            gid = pad.rsplit("pand-", 1)[1]
            w = next(x for x in self.ws if str(x["global_id"]) == gid)
            p = fixture("bag_pand.json")
            p["properties"]["bouwjaar"] = w.get("construction_year")
            p["properties"]["aantal_verblijfsobjecten"] = self.pand.get(gid, 12)
            p["properties"]["gebruiksdoel"] = "woonfunctie"
            return 200, json.dumps(p).encode()
        if host == "api.pdok.nl" and "/wijken-en-buurten-2024/" in pad:
            b = fixture("pdok_buurt.json")
            w = self._midden(q)
            if w is None:
                b["features"] = []
            else:
                pr = b["features"][0]["properties"]
                pr["buurtcode"] = self.code[w.get("neighbourhood") or ""]
                pr["buurtnaam"] = w.get("neighbourhood")
                pr["gemeentenaam"] = self._gemeente(w)
            return 200, json.dumps(b).encode()
        if host == "cas.cloud.sogelink.com":
            k = fixture("kea_getfeatureinfo.json")
            w = self._midden(q)
            vz, pr = self.kea.get(str(w["global_id"]), (1.2, 0.1)) if w else (1.2, 0.1)
            k["features"][0]["properties"]["sterke_c_1"] = vz
            k["features"][1]["properties"]["sterke_c_2"] = pr
            return 200, json.dumps(k).encode()
        if host == "data.rivm.nl":
            r = fixture("rivm_getfeatureinfo.json")
            w = self._midden(q)
            waarden = self.geluid.get(str(w["global_id"]), [48, 39, -9999, -9999]) if w else [44, 36, 34, 22]
            for f, x in zip(r["features"], waarden):
                f["properties"]["GRAY_INDEX"] = x
            return 200, json.dumps(r).encode()
        if host == "geo.leefbaarometer.nl":
            gem = re.search(r"gemeente='(.*)'$", q["cql_filter"][0]).group(1).replace("''", "'")
            sjabloon = fixture("leefbaarometer_buurtscore24.json")
            f0 = sjabloon["features"][0]
            fs = []
            for buurt, code in self.code.items():
                ws = [w for w in self.ws if (w.get("neighbourhood") or "") == buurt]
                if not ws or self._gemeente(ws[0]) != gem:
                    continue
                f = copy.deepcopy(f0)
                f["properties"].update({"id": code, "gemeente": gem, "kscore": 7})
                if self.lbm_extra:
                    f["properties"].update(self.lbm_extra)
                fs.append(f)
            sjabloon["features"] = fs
            return 200, json.dumps(sjabloon).encode()
        if host == "dataderden.cbs.nl":
            c = fixture("cbs_50150ned_buurt.json")
            code = re.search(r"WijkenEnBuurten eq '([^']+)'", q["$filter"][0]).group(1)
            for r in c["value"]:
                r["WijkenEnBuurten"] = code
            return 200, json.dumps(c).encode()
        return 404, b"{}"


# ---------------------------------------------------------------- tests

def test_parsers() -> bool:
    print("Parsers op de gemeten antwoorden")
    ok = True
    vbo, panden = v.bag_kies(fixture("bag_verblijfsobject_bbox.json"), "2511BT", "70", "")
    ok &= check("BAG: verblijfsobject gekozen op postcode en huisnummer",
                vbo is not None and vbo["gebruiksdoel"] == "kantoorfunctie" and len(panden) == 1)
    pand = v.bag_pand_velden(fixture("bag_pand.json"), vbo)
    ok &= check("BAG: bouwjaar en aantal verblijfsobjecten uit het pand",
                pand == {"bouwjaar": 1995, "aantal_vbo_pand": 16, "gebruiksdoel": "kantoorfunctie",
                         "gebruiksdoel_pand": "bijeenkomstfunctie,industriefunctie,kantoorfunctie,winkelfunctie"},
                str(pand))
    ok &= check("BAG: huisletter F telt niet als hetzelfde adres zonder toevoeging",
                v.bag_kies(fixture("bag_verblijfsobject_bbox.json"), "2511BT", "70", "F")[0] is None)
    ok &= check("Klimaateffectatlas: 1,18 = laag, 0,09 = zeer laag",
                v.kea_parse(fixture("kea_getfeatureinfo.json")) == {"verschilzetting": "laag", "paalrot": "zeer laag"})
    ok &= check("RIVM: vier lagen in vaste volgorde",
                v.rivm_parse(fixture("rivm_getfeatureinfo.json"))
                == {"lden_weg": 44, "lnight_weg": 36, "lden_trein": 34, "lnight_trein": 22})
    ok &= check("PDOK-buurt: alleen buurtcode, buurtnaam, gemeentenaam",
                v.pdok_buurt_parse(fixture("pdok_buurt.json"))
                == {"buurtcode": "BU05182812", "buurtnaam": "Voorhout", "gemeentenaam": "'s-Gravenhage"})
    lbm = v.lbm_parse(fixture("leefbaarometer_buurtscore24.json"))
    ok &= check("Leefbaarometer: per buurtcode, alleen de acht velden",
                set(lbm["BU05182812"]) == set(v.VELDEN["leefbaarometer"]) and lbm["BU05182812"]["kscore"] == 9)
    tv = v.cbs_tevreden_parse(fixture("cbs_50150ned_buurt.json"))
    ok &= check("CBS 50150NED: waarde en 95%-marge",
                tv == {"tevreden_woonomgeving": 87.1, "tevreden_woonomgeving_min": 83.8,
                       "tevreden_woonomgeving_max": 91.6, "tevreden_woning": 86.0}, str(tv))
    leeftijd = {r["Key"]: r["Title"] for r in fixture("cbs_50150ned_leeftijd.json")["value"]}
    ok &= check("CBS-code 18 jaar of ouder klopt met de meting",
                leeftijd.get(v.CBS_LEEFTIJD_18PLUS) == "18 jaar of ouder")
    # De klassegrenzen in de code moeten gelijk zijn aan de legenda van de WMS.
    for soort in ("verschilzetting", "paalrot"):
        regels = fixture(f"kea_legenda_{soort}.json")["Legend"][0]["rules"]
        grenzen = [float(re.findall(r"<= '([0-9.]+)'", r["filter"])[0]) for r in regels]
        namen = [r["name"].lower() for r in regels]
        code = v.KEA_KLASSEN[soort]
        ok &= check(f"legenda {soort}: grenzen en namen gelijk aan de code",
                    namen == [n for _, n in code] and all(abs(a - b) < 1e-6 for a, b in zip(grenzen[:-1], [g for g, _ in code][:-1])),
                    f"{grenzen} {namen}")
        ok &= check(f"legenda {soort}: grenswaarde valt in de lagere klasse",
                    v.kea_klasse(soort, grenzen[0]) == namen[0] and v.kea_klasse(soort, grenzen[0] + 0.01) == namen[1])
    ok &= check("Laagnamen KEA en RIVM zoals gemeten",
                v.KEA_LAGEN["verschilzetting"] == "risicoverschilzetting_2050hoog"
                and dict(v.RIVM_LAGEN)["lnight_trein"] == "rivm_20250101_Geluid_lnight_treinverkeer_2023")
    return ok


def test_gray_index() -> bool:
    print("GRAY_INDEX -9999 is onder de kaartgrens, geen fout")
    r = fixture("rivm_getfeatureinfo.json")
    r["features"][2]["properties"]["GRAY_INDEX"] = -9999
    r["features"][3]["properties"]["GRAY_INDEX"] = -9999.0
    data = v.rivm_parse(r)
    ok = check("trein = None, weg blijft", data == {"lden_weg": 44, "lnight_weg": 36, "lden_trein": None,
                                                    "lnight_trein": None}, str(data))
    ws = woningen()[:1]
    web = NepWeb(ws)
    web.geluid[str(ws[0]["global_id"])] = [48, 39, -9999, -9999]
    uit = v.verrijk(ws, {}, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    g = uit[str(ws[0]["global_id"])]["geluid"]
    ok &= check("status ok, geen fout in de cache", g["status"] == "ok" and g["data"]["lden_trein"] is None)
    ok &= check("signaal noemt de kaartgrens", "onder de kaartgrens" in g["signalen"][0]["tekst"])
    ok &= check("te weinig lagen in het antwoord = fout",
                _gooit(lambda: v.rivm_parse({"features": r["features"][:3]}), v.BronFout))
    return ok


def _gooit(f, soort) -> bool:
    try:
        f()
    except soort:
        return True
    return False


def test_volledige_run() -> bool:
    print("Volledige run op de 13 fictieve woningen")
    ws = woningen()
    web = NepWeb(ws)
    cache: dict = {"price_history": {"x": {"fetched": "2026-11-01", "data": {}}}}
    logs: list[str] = []
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=logs.append)
    ok = check("elke woning in de uitvoer", len(uit) == len(ws) and all(str(w["global_id"]) in uit for w in ws))
    ok &= check("alle bronnen per woning", all(set(x) == set(v.BRONNEN) for x in uit.values()))
    st = {b: {x[b]["status"] for x in uit.values()} for b in v.BRONNEN}
    ok &= check("bag, geluid en buurt ok", st["bag"] == {"ok"} and st["geluid"] == {"ok"} and st["buurt"] == {"ok"},
                str(st))
    ok &= check("fundering ok of niet nodig", st["fundering"] <= {"ok", "niet_nodig"}, str(st))
    nieuw = [w for w in ws if (w.get("construction_year") or 0) >= 1970]
    ok &= check("geen KEA-verzoek voor panden van na 1970",
                web.aantal("cas.cloud.sogelink.com", "/wms") == len(ws) - len(nieuw))
    ok &= check("13 nieuwe woningen: tussen 60 en 90 verzoeken", 60 <= len(web.calls) <= 90, str(len(web.calls)))
    ok &= check("Leefbaarometer: één verzoek per gemeente",
                web.aantal("geo.leefbaarometer.nl", "/lbm3/") == len({NepWeb._gemeente(w) for w in ws}))
    ok &= check("robots.txt één keer per host", all(web.aantal(h, "/robots.txt") == 1 for h in
                                                     ("api.pdok.nl", "data.rivm.nl", "geo.leefbaarometer.nl")))
    ok &= check("eerlijke user-agent bij elk verzoek", all(h.get("User-Agent") == UA for h in web.headers))
    ok &= check("bestaande cachesecties blijven staan", "price_history" in cache)
    ok &= check("eigen secties in de cache",
                all(s in cache for s in ("bag", "fundering", "geluid", "buurtcode", "leefbaarometer", "tevredenheid",
                                         "robots")))
    w0 = uit[str(ws[0]["global_id"])]
    ok &= check("BAG-bouwjaar komt uit het pand", w0["bag"]["data"]["bouwjaar"] == ws[0]["construction_year"])
    # tweede run, zelfde dag: alles uit de cache
    web2 = NepWeb(ws)
    uit2 = v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("tweede run: nul verzoeken", len(web2.calls) == 0, str(web2.calls[:3]))
    ok &= check("tweede run: zelfde statussen",
                all(uit2[k][b]["status"] == uit[k][b]["status"] for k in uit for b in v.BRONNEN))
    ok &= check("tweede run: uit_cache", all(uit2[k]["geluid"]["uit_cache"] for k in uit2))
    ok &= check("cachesleutels zonder leesbaar adres of coördinaat",
                not any(re.search(r"\d{4}[A-Z]{2}|52\.\d|4\.\d{3}", k) for s in ("bag", "fundering", "geluid", "buurtcode")
                        for k in cache[s]))
    return ok


def test_bron_faalt() -> bool:
    print("Een kapotte bron geeft onbekend, de run gaat door")
    ws = woningen()
    web = NepWeb(ws)
    web.status["data.rivm.nl"] = 500
    uit = v.verrijk(ws, {}, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    ok = check("geen woning minder", len(uit) == len(ws))
    ok &= check("geluid onbekend voor iedereen", {x["geluid"]["status"] for x in uit.values()} == {"onbekend"})
    ok &= check("andere bronnen gewoon ok", {x["bag"]["status"] for x in uit.values()} == {"ok"}
                and {x["buurt"]["status"] for x in uit.values()} == {"ok"})
    ok &= check("5xx stopt de host na één verzoek", web.aantal("data.rivm.nl", "/geo/") == 1,
                str(web.aantal("data.rivm.nl", "/geo/")))
    # Een onverwacht antwoord (geen JSON) is ook gewoon onbekend.
    web2 = NepWeb(ws[:2])
    orig = web2.__call__

    def kapot(url, timeout=None, headers=None):
        if "cas.cloud.sogelink.com" in url and "robots" not in url:
            web2.calls.append(url)
            return 200, b"<html>geen json</html>"
        return orig(url, timeout=timeout, headers=headers)
    oud = [w for w in ws[:2] if (w.get("construction_year") or 0) < 1970]
    uit2 = v.verrijk(ws[:2], {}, cfg(), VANDAAG, http=kapot, ua=UA, log=STIL)
    ok &= check("geen JSON = fundering onbekend",
                all(uit2[str(w["global_id"])]["fundering"]["status"] == "onbekend" for w in oud) and len(oud) > 0)
    return ok


def test_weigering() -> bool:
    print("401/403/429 stopt de host, een dag lang, zonder omweg")
    ws = woningen()
    oud = [w for w in ws if (w.get("construction_year") or 0) < 1970]
    web = NepWeb(ws)
    web.status["cas.cloud.sogelink.com"] = 403
    cache: dict = {}
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    ok = check("één verzoek naar de weigerende host (plus robots)", web.aantal("cas.cloud.sogelink.com", "/public/") == 1)
    ok &= check("fundering onbekend, reden noemt de weigering",
                all(uit[str(w["global_id"])]["fundering"]["status"] == "onbekend" for w in oud)
                and "403" in (uit[str(oud[-1]["global_id"])]["fundering"]["reden"] or ""))
    ok &= check("weigering bewaard", cache.get("verrijking_weigering", {}).get("cas.cloud.sogelink.com", {}).get("status") == 403)
    ok &= check("altijd dezelfde user-agent", {h.get("User-Agent") for h in web.headers} == {UA})
    web2 = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("zelfde dag: geen nieuw verzoek naar die host", web2.aantal("cas.cloud.sogelink.com") == 0)
    web3 = NepWeb(ws)
    uit3 = v.verrijk(ws, cache, cfg(), dag(1), http=web3, ua=UA, log=STIL)
    ok &= check("dag erna: opnieuw geprobeerd", web3.aantal("cas.cloud.sogelink.com", "/public/") >= 1)
    ok &= check("en dan ok", all(uit3[str(w["global_id"])]["fundering"]["status"] == "ok" for w in oud))
    for code in (401, 429):
        webx = NepWeb(ws[:3])
        webx.status["api.pdok.nl"] = code
        v.verrijk(ws[:3], {}, cfg(), VANDAAG, http=webx, ua=UA, log=STIL)
        ok &= check(f"{code} stopt api.pdok.nl na één verzoek",
                    webx.aantal("api.pdok.nl") - webx.aantal("api.pdok.nl", "/robots.txt") == 1)
    return ok


def test_fout_opnieuw() -> bool:
    print("Fout na een dag opnieuw, data na bewaar_dagen")
    ws = woningen()[:2]
    web = NepWeb(ws)
    web.time_out.add("data.rivm.nl")
    web.robots["data.rivm.nl"] = (404, b"")
    cache: dict = {"robots": {"data.rivm.nl": {"fetched": VANDAAG, "data": {"regels": []}}}}
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    gid = str(ws[0]["global_id"])
    ok = check("time-out = onbekend", uit[gid]["geluid"]["status"] == "onbekend")
    ok &= check("fout in de cache", any(e.get("fout") for e in cache["geluid"].values()))
    web2 = NepWeb(ws)
    uit2 = v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("zelfde dag: niet opnieuw", web2.aantal("data.rivm.nl", "/geo/") == 0
                and "vorige poging" in (uit2[gid]["geluid"]["reden"] or ""))
    web3 = NepWeb(ws)
    uit3 = v.verrijk(ws, cache, cfg(), dag(1), http=web3, ua=UA, log=STIL)
    ok &= check("na een dag: opnieuw en ok", web3.aantal("data.rivm.nl", "/geo/") == len(ws)
                and uit3[gid]["geluid"]["status"] == "ok")
    web4 = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), dag(1 + 365), http=web4, ua=UA, log=STIL)
    ok &= check("binnen 365 dagen: geluid uit de cache", web4.aantal("data.rivm.nl", "/geo/") == 0)
    ok &= check("BAG (180 dagen) wel opnieuw", web4.aantal("api.pdok.nl", "/verblijfsobject/") >= 1)
    web5 = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), dag(1 + 366), http=web5, ua=UA, log=STIL)
    ok &= check("na 365 dagen: geluid opnieuw", web5.aantal("data.rivm.nl", "/geo/") == len(ws))
    # Time-outs op rij: na drie stopt de host deze run.
    ws13 = woningen()
    web6 = NepWeb(ws13)
    web6.time_out.add("data.rivm.nl")
    c6: dict = {"robots": {"data.rivm.nl": {"fetched": VANDAAG, "data": {"regels": []}}}}
    v.verrijk(ws13, c6, cfg(), VANDAAG, http=web6, ua=UA, log=STIL)
    ok &= check("drie time-outs op rij stoppen de host", web6.aantal("data.rivm.nl") == 3, str(web6.aantal("data.rivm.nl")))
    return ok


def test_allowlist() -> bool:
    print("Allowlist: geen herkomst, inkomen of ander bevolkingskenmerk in cache of uitvoer")
    pdok = fixture("pdok_buurt.json")["features"][0]["properties"]
    verboden_velden = [k for k in pdok if k not in v.VELDEN["buurtcode"]]
    ok = check("de PDOK-fixture bevat verboden velden (anders test dit niets)",
               any("herkomst" in k for k in verboden_velden) and any("inkomen" in k for k in verboden_velden))
    ws = woningen()
    web = NepWeb(ws)
    web.lbm_extra = {"migratieachtergrond": 12.3, "gemiddeld_inkomen": 1}
    cache: dict = {}
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    tekst = json.dumps(cache) + json.dumps(uit)
    for woord in ("herkomst", "migratie", "inkomen", "opleiding", "huishoudens", "aantal_inwoners",
                  "woningwaarde", "koopwoningen"):
        ok &= check(f"'{woord}' nergens", woord not in tekst)
    for sectie, velden in v.VELDEN.items():
        for k, e in (cache.get(sectie) or {}).items():
            data = e.get("data")
            if isinstance(data, dict) and not k.startswith("gemeente|"):
                if not set(data) <= set(velden):
                    ok &= check(f"cache {sectie} binnen de allowlist", False, str(sorted(data)))
    for x in uit.values():
        for b in v.BRONNEN:
            data = x[b].get("data")
            if isinstance(data, dict) and not set(data) <= set(v.UITVOER_VELDEN[b]):
                ok &= check(f"uitvoer {b} binnen de allowlist", False, str(sorted(data)))
    ok &= check("cache_schrijf weigert een veld buiten de allowlist",
                _gooit(lambda: v.cache_schrijf({}, "buurtcode", "pt:x", VANDAAG,
                                               data={"buurtcode": "BU1", "percentage_met_herkomstland_nederland": 1}),
                       ValueError))
    ok &= check("ook in de gemeentemarkering",
                _gooit(lambda: v.cache_schrijf({}, "leefbaarometer", "gemeente|x", VANDAAG, data={"inwoners": 1}),
                       ValueError))
    return ok


def test_budget() -> bool:
    print("Budget van 60 verzoeken, Past en Krap eerst")
    basis = woningen()
    ws = []
    for i in range(30):                        # 30 fictieve woningen, elk op een eigen punt
        w = copy.deepcopy(basis[i % len(basis)])
        w["global_id"] = 8_000_000 + i
        w["latitude"] = round(52.03 + i * 0.002, 6)
        w["longitude"] = round(4.25 + i * 0.002, 6)
        w["construction_year"] = 1930
        w["_beoordeling"] = {"poort": "PAST NIET" if i < 15 else ("KRAP" if i % 2 else "PAST"), "score": i / 10}
        ws.append(w)
    web = NepWeb(ws)
    cache: dict = {}
    uit = v.verrijk(ws, cache, cfg(max_calls_per_run=60), VANDAAG, http=web, ua=UA, log=STIL)
    ok = check("hooguit 60 verzoeken", len(web.calls) <= 60, str(len(web.calls)))
    ok &= check("budget opgemaakt (60 verzoeken)", len(web.calls) == 60, str(len(web.calls)))
    statussen = [x["geluid"]["status"] for x in uit.values()]
    ok &= check("een deel krijgt 'budget'", "budget" in statussen and "ok" in statussen)
    past_ok = [uit[str(w["global_id"])]["geluid"]["status"] == "ok" for w in ws if w["_beoordeling"]["poort"] == "PAST"]
    nee_budget = [uit[str(w["global_id"])]["geluid"]["status"] for w in ws if w["_beoordeling"]["poort"] == "PAST NIET"]
    ok &= check("Past eerst: alle Past-woningen verrijkt", all(past_ok), str(past_ok))
    ok &= check("Past niet als laatste: daar raakt het budget op", "budget" in nee_budget)
    ok &= check("budget wordt niet als fout bewaard",
                not any(e.get("fout") for s in ("bag", "geluid", "fundering") for e in (cache.get(s) or {}).values()))
    volgorde = [str(w["global_id"]) for w in ws]
    ok &= check("uitvoer in de volgorde van de invoer", list(uit) == volgorde)
    web2 = NepWeb(ws)
    uit2 = v.verrijk(ws, cache, cfg(max_calls_per_run=60), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("volgende run gaat verder", sum(x["geluid"]["status"] == "ok" for x in uit2.values())
                > sum(x["geluid"]["status"] == "ok" for x in uit.values()))
    web3 = NepWeb(ws)
    v.verrijk(ws, {}, cfg(max_calls_per_run=7), VANDAAG, http=web3, ua=UA, log=STIL)
    ok &= check("ander budget uit de config", len(web3.calls) <= 7, str(len(web3.calls)))
    return ok


def test_uit() -> bool:
    print("Uit in de config = geen enkel verzoek")
    ws = woningen()
    web = NepWeb(ws)
    uit = v.verrijk(ws, {}, {"beoordeling": {"verrijking": {"aan": False}}}, VANDAAG, http=web, ua=UA, log=STIL)
    ok = check("nul verzoeken", len(web.calls) == 0)
    ok &= check("alles 'uit'", {x[b]["status"] for x in uit.values() for b in v.BRONNEN} == {"uit"})
    web2 = NepWeb(ws)
    uit2 = v.verrijk(ws, {}, cfg(bronnen={"geluid": False, "tevredenheid": False}), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("geluid uit: geen RIVM-verzoek", web2.aantal("data.rivm.nl") == 0
                and {x["geluid"]["status"] for x in uit2.values()} == {"uit"})
    ok &= check("tevredenheid uit: geen CBS-verzoek, buurt wel ok", web2.aantal("dataderden.cbs.nl") == 0
                and {x["buurt"]["status"] for x in uit2.values()} == {"ok"})
    ok &= check("standaard staat de verrijking aan", v.instellingen({})[0]["aan"] is True
                and v.instellingen({})[0]["max_calls_per_run"] == 60)
    return ok


def test_signalen() -> bool:
    print("Signaalregels (huisverklikker.md par. 7)")
    dr = v.DREMPELS
    ok = check("VvE van 3 = kleine VvE (let op)", v.signalen_bag({"aantal_vbo_pand": 3, "bouwjaar": 1932}, dr)[0]["niveau"] == "let_op")
    ok &= check("VvE van 16 = info", v.signalen_bag({"aantal_vbo_pand": 16, "bouwjaar": 1995}, dr)[0]["niveau"] == "info")
    ok &= check("gebruiksdoel kantoor = let op",
                any(s["niveau"] == "let_op" and "kantoorfunctie" in s["tekst"]
                    for s in v.signalen_bag({"aantal_vbo_pand": 16, "gebruiksdoel": "kantoorfunctie"}, dr)))
    f = lambda d, bj: v.signalen_fundering("ok", d, bj, 3, dr)[0]["niveau"]  # noqa: E731
    ok &= check("1932 en matig = let op", f({"verschilzetting": "matig", "paalrot": "zeer laag"}, 1932) == "let_op")
    ok &= check("1932 en hoog = sterk", f({"verschilzetting": "hoog", "paalrot": "laag"}, 1932) == "sterk")
    ok &= check("1932 en paalrot zeer hoog = sterk", f({"verschilzetting": "laag", "paalrot": "zeer hoog"}, 1932) == "sterk")
    ok &= check("1932 en laag = goed", f({"verschilzetting": "laag", "paalrot": "zeer laag"}, 1932) == "goed")
    ok &= check("onbekend bouwjaar en hoog = alleen info", f({"verschilzetting": "hoog", "paalrot": "laag"}, None) == "info")
    tekst = v.signalen_fundering("ok", {"verschilzetting": "hoog", "paalrot": "laag"}, 1932, 3, dr)[0]["tekst"]
    ok &= check("funderingstekst noemt bouwjaar, VvE en 'geen oordeel'",
                "1932" in tekst and "3 adressen" in tekst and "Geen oordeel over dit pand" in tekst)
    ok &= check("niet nodig na 1970", v.signalen_fundering("niet_nodig", None, 1998, None, dr)[0]["niveau"] == "info")
    g = lambda *x: v.signalen_geluid(dict(zip(("lden_weg", "lnight_weg", "lden_trein", "lnight_trein"), x)), dr)[0]["niveau"]  # noqa: E731
    ok &= check("48/39 dB = rustig (goed)", g(48, 39, None, None) == "goed")
    ok &= check("52/43 dB = info", g(52, 43, None, None) == "info")
    ok &= check("57 dB = let op", g(57, 46, None, None) == "let_op")
    ok &= check("61/52 dB = sterk", g(61, 52, None, None) == "sterk")
    ok &= check("trein 58 dB = let op", g(49, 40, 58, 45) == "let_op")
    ok &= check("nacht weg 48 dB = let op", g(54, 48, None, None) == "let_op")
    sig, tw = v.signalen_buurt({"buurtnaam": "Testbuurt", "kscore": 4, "onv": -0.21, "tevreden_woonomgeving": 78,
                                "tevreden_woonomgeving_min": 74, "tevreden_woonomgeving_max": 82}, dr)
    ok &= check("Leefbaarometer zwak = twijfel en sterk", tw and sig[0]["niveau"] == "sterk")
    ok &= check("overlast -0,21 = let op", any(s["niveau"] == "let_op" and "−0,21" in s["tekst"] for s in sig))
    ok &= check("tevreden 78% = let op met marge", any(s["niveau"] == "let_op" and "78%" in s["tekst"] and "74 tot 82" in s["tekst"] for s in sig))
    sig2, tw2 = v.signalen_buurt({"buurtnaam": "Testbuurt", "kscore": 8, "onv": 0.1, "tevreden_woonomgeving": 92}, dr)
    ok &= check("Leefbaarometer zeer goed = goed, geen twijfel", not tw2 and sig2[0]["niveau"] == "goed")
    alle = json.dumps([sig, sig2, tekst], ensure_ascii=False)
    ok &= check("geen em dash of gedachtestreepje", "\u2014" not in alle and "\u2013" not in alle)
    # Door verrijk(): kleine VvE en fundering samen.
    ws = woningen()
    oud = next(w for w in ws if (w.get("construction_year") or 9999) < 1970)
    web = NepWeb([oud])
    web.pand[str(oud["global_id"])] = 3
    web.kea[str(oud["global_id"])] = (12.0, 0.1)
    uit = v.verrijk([oud], {}, cfg(), VANDAAG, http=web, ua=UA, log=STIL)[str(oud["global_id"])]
    ok &= check("door verrijk(): kleine VvE en fundering hoog = sterk",
                uit["bag"]["signalen"][0]["niveau"] == "let_op" and uit["fundering"]["signalen"][0]["niveau"] == "sterk"
                and uit["fundering"]["data"] == {"verschilzetting": "hoog", "paalrot": "zeer laag"})
    return ok


def test_robots() -> bool:
    print("robots.txt per host eerst")
    regels = v.robots_regels("User-agent: *\nAllow: /\nDisallow: /bzk/locatieserver/*\n")
    ok = check("PDOK: BAG mag", v.robots_mag(regels, "/kadaster/bag/ogc/v2/collections/pand/items?f=json"))
    ok &= check("PDOK: Locatieserver niet", not v.robots_mag(regels, "/bzk/locatieserver/search/v3_1/free?q=x"))
    ok &= check("leeg bestand = alles mag", v.robots_mag(v.robots_regels(""), "/lbm3/ows"))
    ok &= check("Disallow: / verbiedt alles", not v.robots_mag(v.robots_regels("User-agent: *\nDisallow: /\n"), "/x"))
    eigen = v.robots_regels("User-agent: *\nDisallow: /\n\nUser-agent: funda-dagelijkse-check\nAllow: /\n")
    ok &= check("eigen groep gaat voor '*'", v.robots_mag(eigen, "/x"))
    ok &= check("$ en * in patronen", not v.robots_mag(v.robots_regels("User-agent: *\nDisallow: /*.pdf$\n"), "/a/b.pdf")
                and v.robots_mag(v.robots_regels("User-agent: *\nDisallow: /*.pdf$\n"), "/a/b.pdf?x=1"))
    ws = woningen()[:3]
    web = NepWeb(ws)
    web.robots["data.rivm.nl"] = (200, b"User-agent: *\nDisallow: /geo/\n")
    cache: dict = {}
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    ok &= check("verboden pad: alleen robots.txt opgevraagd", web.aantal("data.rivm.nl") == 1
                and web.aantal("data.rivm.nl", "/robots.txt") == 1)
    ok &= check("geluid onbekend met robots als reden",
                all("robots" in (x["geluid"]["reden"] or "") for x in uit.values()))
    web2 = NepWeb(ws)
    web2.robots["data.rivm.nl"] = (200, b"User-agent: *\nDisallow: /geo/\n")
    v.verrijk(ws, cache, cfg(), dag(2), http=web2, ua=UA, log=STIL)
    ok &= check("robots.txt 30 dagen gecacht", web2.aantal("data.rivm.nl") == 0)
    web3 = NepWeb(ws)
    web3.robots["api.pdok.nl"] = (503, b"")
    uit3 = v.verrijk(ws, {}, cfg(), VANDAAG, http=web3, ua=UA, log=STIL)
    ok &= check("robots.txt met 5xx: host deze run niet gebruiken", web3.aantal("api.pdok.nl") == 1
                and {x["bag"]["status"] for x in uit3.values()} == {"onbekend"})
    return ok


def test_log() -> bool:
    print("Logregels: alleen aantallen, geen adressen, postcodes of coördinaten")
    ws = woningen()
    web = NepWeb(ws)
    web.status["dataderden.cbs.nl"] = 403
    logs: list[str] = []
    v.verrijk(ws, {}, cfg(max_calls_per_run=60), VANDAAG, http=web, ua=UA, log=logs.append)
    tekst = "\n".join(logs)
    ok = check("er zijn logregels", len(logs) >= 2 and "verzoeken van 60" in tekst, tekst)
    ok &= check("geen postcode", not re.search(r"\b\d{4}\s?[A-Z]{2}\b", tekst), tekst)
    ok &= check("geen coördinaten", not re.search(r"\b5[0-3]\.\d{3}|\b[3-7]\.\d{4}", tekst), tekst)
    straten = {re.sub(r"\s*\d.*$", "", w.get("title") or "") for w in ws}
    ok &= check("geen straatnamen", not any(s and s in tekst for s in straten))
    ok &= check("geen buurtnamen", not any((w.get("neighbourhood") or "~") in tekst for w in ws))
    ok &= check("gestopte host gemeld met status", "dataderden.cbs.nl deze run gestopt" in tekst and "403" in tekst)
    return ok


def test_bag_matching() -> bool:
    print("BAG: toevoeging, meerdere panden, vreemde pand-link")
    pand = v.BAG_PAND_PREFIX
    def f(pc, nr, letter, toev, href, doel="woonfunctie"):
        return {"properties": {"postcode": pc, "huisnummer": nr, "huisletter": letter, "toevoeging": toev,
                               "gebruiksdoel": doel, "pand.href": [href]}}
    antw = {"features": [f("1234AB", 10, None, "1", pand + "a"), f("1234AB", 10, None, "2", pand + "a"),
                         f("1234AB", 10, "A", None, pand + "a", "winkelfunctie"), f("1234AB", 12, None, None, pand + "b")]}
    vbo, panden = v.bag_kies(antw, "1234AB", "10", "2")
    ok = check("toevoeging 2 exact", vbo["toevoeging"] == "2" and panden == [pand + "a"])
    vbo, panden = v.bag_kies(antw, "1234AB", "10", "A")
    ok &= check("huisletter A exact", vbo["huisletter"] == "A")
    vbo, panden = v.bag_kies(antw, "1234AB", "10", "")
    ok &= check("geen toevoeging, alles in één pand: pand wel, object niet", vbo is None and panden == [pand + "a"])
    vbo, panden = v.bag_kies(antw, "1234AB", "10", "-II")
    ok &= check("onbekende toevoeging, één pand: pand wel", vbo is None and panden == [pand + "a"])
    antw2 = {"features": [f("1234AB", 10, None, "1", pand + "a"), f("1234AB", 10, None, "2", pand + "b")]}
    ok &= check("twee panden zonder exacte treffer: geen keuze", v.bag_kies(antw2, "1234AB", "10", "")[1] == [])
    ok &= check("ander nummer telt niet", v.bag_kies(antw, "1234AB", "11", "")[1] == [])
    ws = woningen()[:1]
    web = NepWeb(ws)
    orig = web.__call__

    def vreemd(url, timeout=None, headers=None):
        st, body = orig(url, timeout=timeout, headers=headers)
        if "/verblijfsobject/items" in url:
            d = json.loads(body)
            for x in d["features"]:
                x["properties"]["pand.href"] = ["https://elders.example/pand/1"]
            body = json.dumps(d).encode()
        return st, body
    uit = v.verrijk(ws, {}, cfg(), VANDAAG, http=vreemd, ua=UA, log=STIL)
    ok &= check("pand-link naar een andere host wordt niet gevolgd",
                uit[str(ws[0]["global_id"])]["bag"]["status"] == "onbekend"
                and not any("elders.example" in u for u in web.calls))
    ws2 = copy.deepcopy(woningen()[:1])
    ws2[0]["latitude"] += 0.0003                   # punt net naast het adres: ruimere tweede poging
    web2 = NepWeb(woningen()[:1])
    web2.ws = woningen()[:1]
    uit2 = v.verrijk(ws2, {}, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("ruimere tweede poging vindt het adres", uit2[str(ws2[0]["global_id"])]["bag"]["status"] == "ok"
                and web2.aantal("api.pdok.nl", "/verblijfsobject/") == 2)
    return ok


def test_vorm() -> bool:
    print("Vorm van de uitvoer (verrijking_stub.json en contract par. 9)")
    ws = woningen()
    web = NepWeb(ws)
    web.status["data.rivm.nl"] = 500
    uit = v.verrijk(ws, {}, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    w = uit[str(ws[0]["global_id"])]
    stub = v.als_stub(w)
    ok = check("stub-sleutels", set(stub) == {"bag", "fundering", "geluid", "buurt"})
    ok &= check("bag: bouwjaar en aantal_vbo_pand", {"bouwjaar", "aantal_vbo_pand"} <= set(stub["bag"]))
    ok &= check("geluid kapot = 'fout' zoals in de stub", stub["geluid"] == "fout")
    ok &= check("buurt: kscore, onv, tevreden_woonomgeving",
                {"kscore", "onv", "tevreden_woonomgeving"} <= set(stub["buurt"]))
    ok &= check("fundering: verschilzetting en paalrot, of niet_nodig",
                stub["fundering"] == "niet_nodig" or set(stub["fundering"]) == {"verschilzetting", "paalrot"})
    ok &= check("status_per_bron", v.status_per_bron(w) == {"bag": "ok", "fundering": w["fundering"]["status"],
                                                            "geluid": "onbekend", "buurt": "ok"})
    for b in v.BRONNEN:
        ok &= check(f"{b}: status, data, reden, signalen",
                    {"status", "data", "reden", "signalen"} <= set(w[b]))
    ok &= check("buurt: twijfel en delen", "twijfel" in w["buurt"] and set(w["buurt"]["delen"]) ==
                {"buurtcode", "leefbaarometer", "tevredenheid"})
    ok &= check("zwakke_buurten leeg bij kscore 7", v.zwakke_buurten(uit) == [])
    ok &= check("prioriteit: Past voor Krap voor onbekend voor Past niet",
                sorted(["PAST NIET", None, "KRAP", "PAST"], key=lambda p: v.prioriteit({"beoordeling": {"poort": p}}))
                == ["PAST", "KRAP", None, "PAST NIET"])
    ok &= check("poort als dict (prototype) werkt ook",
                v.prioriteit({"_beoordeling": {"poort": {"status": "KRAP"}, "score": 6.0}}) == (1, -6.0))
    return ok


def test_ua() -> bool:
    print("User-agent komt uit funda_zoek")
    import funda_zoek
    ok = check("EERLIJKE_UA wordt hergebruikt", v._eerlijke_ua() == funda_zoek.EERLIJKE_UA)
    web = NepWeb(woningen()[:1])
    v.verrijk(woningen()[:1], {}, cfg(), VANDAAG, http=web, log=STIL)
    ok &= check("zonder ua-parameter: EERLIJKE_UA in de header",
                {h.get("User-Agent") for h in web.headers} == {funda_zoek.EERLIJKE_UA})
    return ok


def test_doorverwijzing() -> bool:
    print("Doorverwijzingen: alleen dezelfde host, behalve robots.txt naar robots.txt")
    import urllib.request
    h = v._ZelfdeHost()

    def volgt(van: str, naar: str) -> bool:
        req = urllib.request.Request(van)
        return h.redirect_request(req, None, 301, "Moved", {}, naar) is not None
    ok = check("zelfde host via https", volgt("https://api.pdok.nl/a", "https://api.pdok.nl/b"))
    ok &= check("andere host niet", not volgt("https://data.rivm.nl/geo/x", "https://elders.example/geo/x"))
    ok &= check("http niet", not volgt("https://api.pdok.nl/a", "http://api.pdok.nl/a"))
    ok &= check("robots.txt naar robots.txt op een andere host wel (RFC 9309)",
                volgt("https://data-api.ecb.europa.eu/robots.txt", "https://data.ecb.europa.eu/robots.txt"))
    ok &= check("robots.txt naar een ander pad niet",
                not volgt("https://data-api.ecb.europa.eu/robots.txt", "https://elders.example/x"))
    return ok


def main() -> int:
    resultaten = [test_parsers(), test_gray_index(), test_volledige_run(), test_bron_faalt(), test_weigering(),
                  test_fout_opnieuw(), test_allowlist(), test_budget(), test_uit(), test_signalen(), test_robots(),
                  test_log(), test_bag_matching(), test_vorm(), test_ua(), test_doorverwijzing()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
