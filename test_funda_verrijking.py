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
    print("Signaalregels")
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
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("robots.txt zelfde dag uit de cache", web2.aantal("data.rivm.nl") == 0)
    web2b = NepWeb(ws)
    web2b.robots["data.rivm.nl"] = (200, b"User-agent: *\nDisallow: /geo/\n")
    v.verrijk(ws, cache, cfg(), dag(1), http=web2b, ua=UA, log=STIL)
    ok &= check("robots.txt volgende dag opnieuw (één keer)", web2b.aantal("data.rivm.nl") == 1
                and web2b.aantal("data.rivm.nl", "/robots.txt") == 1)
    web3 = NepWeb(ws)
    web3.robots["api.pdok.nl"] = (503, b"")
    uit3 = v.verrijk(ws, {}, cfg(), VANDAAG, http=web3, ua=UA, log=STIL)
    ok &= check("robots.txt met 5xx: host deze run niet gebruiken", web3.aantal("api.pdok.nl") == 1
                and {x["bag"]["status"] for x in uit3.values()} == {"onbekend"})
    return ok


def test_robots_een_dag() -> bool:
    """RFC 9309 par. 2.4: een gecachete robots.txt hooguit 24 uur gebruiken, tenzij hij onbereikbaar
    is. Eindreview: de cache hield hem 30 dagen vers, dus een nieuwe 'Disallow: /' werd tot een maand
    lang genegeerd. Nu: vers op de dag van ophalen; de laatste goede versie (hooguit 30 dagen) alleen
    als terugval bij een time-out of 5xx. Een weigering (401/403/429) is geen onbereikbaarheid."""
    print("robots.txt hooguit een dag gecacht, 30 dagen alleen als terugval bij onbereikbaar")
    url = "https://data.rivm.nl/geo/alo/wms?service=WMS&request=GetFeatureInfo"
    robots = "https://data.rivm.nl/robots.txt"

    def web(antwoord):
        calls: list[str] = []

        def http(u, timeout=None, headers=None):
            calls.append(u)
            if u.endswith("/robots.txt"):
                if isinstance(antwoord, Exception):
                    raise antwoord
                return antwoord
            return 200, b"{}"
        return http, calls

    def poging(cache, n, antwoord, keer=1, **kw):
        http, calls = web(antwoord)
        s = v.Sessie(cache, dag(n), http=http, ua=UA, pauze_s=0, **kw)
        uit = []
        for _ in range(keer):
            try:
                s.haal_json(url)
                uit.append("ok")
            except v.BronFout as exc:
                uit.append(f"gestopt: {exc}")
        return uit, calls

    def alles_mag() -> dict:   # gisteren gemeten: geen regels
        c: dict = {}
        v.cache_schrijf(c, "robots", "data.rivm.nl", VANDAAG, data={"regels": []})
        return c

    verbiedt = (200, b"User-agent: *\nDisallow: /\n")
    ok = True
    uit, calls = poging(alles_mag(), 0, verbiedt)
    ok &= check("zelfde dag: uit de cache", uit == ["ok"] and calls == [url], str(calls))
    uit, calls = poging(alles_mag(), 1, verbiedt)
    ok &= check("volgende dag: robots.txt opnieuw, nieuw verbod geldt meteen",
                calls == [robots] and uit == ["gestopt: robots.txt staat dit pad niet toe"], f"{uit} {calls}")
    uit, calls = poging(alles_mag(), 1, verbiedt, robots_dagen=30)
    ok &= check("robots_dagen 30 uit een oude config: toch hooguit een dag", calls == [robots], str(calls))
    ok &= check("standaard in de config: 1 dag", v.STANDAARD["bewaar_dagen"]["robots"] == 1)

    c = alles_mag()
    uit, calls = poging(c, 10, (503, b""), keer=3)
    ok &= check("onbereikbaar (503): laatste goede versie als terugval, één robots-verzoek per run",
                uit == ["ok"] * 3 and calls == [robots, url, url, url], f"{uit} {calls}")
    ok &= check("terugval laat de goede versie in de cache staan",
                c["robots"]["data.rivm.nl"] == {"fetched": VANDAAG, "data": {"regels": []}}, str(c["robots"]))
    uit, calls = poging(alles_mag(), 10, TimeoutError("nep"))
    ok &= check("onbereikbaar (time-out): ook de terugval", uit == ["ok"] and calls == [robots, url], f"{uit} {calls}")
    uit, calls = poging(alles_mag(), 31, (503, b""))
    ok &= check("terugval ouder dan 30 dagen: host deze run niet gebruiken",
                calls == [robots] and uit[0].startswith("gestopt"), f"{uit} {calls}")
    uit, calls = poging(alles_mag(), 1, (403, b""))
    ok &= check("weigering (403) is geen onbereikbaarheid: geen terugval",
                calls == [robots] and uit[0].startswith("gestopt"), f"{uit} {calls}")
    uit, calls = poging({}, 0, (503, b""))
    ok &= check("zonder eerdere versie: 503 stopt de host, zoals voorheen",
                calls == [robots] and uit[0].startswith("gestopt"), f"{uit} {calls}")
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
    print("Vorm van de uitvoer: wat funda_beoordeling leest (contract in funda_beoordeling.py)")
    import funda_beoordeling as fb
    ws = woningen()
    web = NepWeb(ws)
    web.status["data.rivm.nl"] = 500
    uit = v.verrijk(ws, {}, cfg(), VANDAAG, http=web, ua=UA, log=STIL)
    w = uit[str(ws[0]["global_id"])]
    # Door de lezer van het model zelf: fb._bron() geeft (status, data, reden) per bron.
    gelezen = {b: fb._bron(w, b) for b in v.BRONNEN}
    ok = check("bronnen", set(w) >= {"bag", "fundering", "geluid", "buurt"})
    ok &= check("status zoals het model hem leest",
                {b: st for b, (st, _, _) in gelezen.items()}
                == {"bag": "ok", "fundering": w["fundering"]["status"], "geluid": "onbekend", "buurt": "ok"})
    ok &= check("bag: bouwjaar en aantal_vbo_pand", {"bouwjaar", "aantal_vbo_pand"} <= set(gelezen["bag"][1] or {}))
    ok &= check("geluid kapot: geen data, wel een reden",
                gelezen["geluid"][1] is None and bool(gelezen["geluid"][2]))
    ok &= check("buurt: kscore, onv, tevreden_woonomgeving",
                {"kscore", "onv", "tevreden_woonomgeving"} <= set(gelezen["buurt"][1] or {}))
    st_fu, fu, _ = gelezen["fundering"]
    ok &= check("fundering: verschilzetting en paalrot, of niet_nodig",
                st_fu == "niet_nodig" or set(fu or {}) == {"verschilzetting", "paalrot"})
    for b in v.BRONNEN:
        ok &= check(f"{b}: status, data, reden, signalen",
                    {"status", "data", "reden", "signalen"} <= set(w[b]))
    ok &= check("buurt: twijfel en delen", "twijfel" in w["buurt"] and set(w["buurt"]["delen"]) ==
                {"buurtcode", "leefbaarometer", "tevredenheid"})
    ok &= check("prioriteit: Past voor Krap voor onbekend voor Past niet",
                sorted(["PAST NIET", None, "KRAP", "PAST"], key=lambda p: v.prioriteit({"beoordeling": {"poort": p}}))
                == ["PAST", "KRAP", None, "PAST NIET"])
    ok &= check("prioriteit: poort en score uit d[\"_beoordeling\"]",
                v.prioriteit({"_beoordeling": {"poort": "KRAP", "score": 6.0}}) == (1, -6.0))
    return ok


def test_ua() -> bool:
    print("User-agent: één constante in funda_verrijking, door funda_zoek en funda_rapport hergebruikt")
    import funda_rapport
    import funda_sitemap_zoek
    import funda_zoek
    ok = check("de waarde zelf (met repo-link)", v.EERLIJKE_UA == UA)
    ok &= check("funda_zoek exporteert dezelfde constante als EERLIJKE_UA", funda_zoek.EERLIJKE_UA is v.EERLIJKE_UA)
    ok &= check("funda_rapport gebruikt dezelfde constante", funda_rapport.EERLIJKE_UA is v.EERLIJKE_UA)
    ok &= check("robots.txt: de naam voor de '/'", v.ROBOTS_AGENT == "funda-dagelijkse-check")
    ok &= check("niet voor www.funda.nl: daar het vaste Safari-profiel",
                funda_sitemap_zoek.UA != v.EERLIJKE_UA and "Safari" in funda_sitemap_zoek.UA)
    # Geen tweede kopie van de waarde in de code (tests mogen hem vastpinnen, zoals UA hierboven).
    code = sorted(HIER.glob("funda_*.py")) + sorted((HIER / "scripts").glob("*.py"))
    kopie = [p.name for p in code if p.name != "funda_verrijking.py"
             and "funda-dagelijkse-check/" in p.read_text(encoding="utf-8")]
    ok &= check("de waarde staat alleen in funda_verrijking.py", not kopie, str(kopie))
    web = NepWeb(woningen()[:1])
    v.verrijk(woningen()[:1], {}, cfg(), VANDAAG, http=web, log=STIL)
    ok &= check("zonder ua-parameter: EERLIJKE_UA in de header",
                {h.get("User-Agent") for h in web.headers} == {v.EERLIJKE_UA})
    return ok


def test_een_bron() -> bool:
    print("Eén bron: verrijkingsstandaard hier, klassen en drempels uit funda_beoordeling")
    import funda_beoordeling as fb
    ok = check("funda_beoordeling.STANDAARD heeft geen eigen verrijkingsblok", "verrijking" not in fb.STANDAARD)
    ok &= check("laad_config zonder override: geen verrijkingsblok", "verrijking" not in fb.laad_config({}))
    # De productieroute: funda_rapport geeft laad_config() door aan verrijk() en dus aan instellingen().
    ok &= check("standaard uit funda_verrijking.STANDAARD", v.instellingen(fb.laad_config({}))[0] == v.STANDAARD)
    eigen = {"beoordeling": {"verrijking": {"max_calls_per_run": 7, "bronnen": {"geluid": False}},
                             "drempels": {"geluid_rustig_lden": 45}}}
    vcfg, dr = v.instellingen(fb.laad_config(eigen))
    ok &= check("override beoordeling.verrijking werkt (via laad_config)",
                vcfg["max_calls_per_run"] == 7 and vcfg["bronnen"]["geluid"] is False
                and vcfg["bronnen"]["bag"] is True and vcfg["timeout_s"] == v.STANDAARD["timeout_s"]
                and vcfg["bewaar_dagen"] == v.STANDAARD["bewaar_dagen"], str(vcfg))
    ok &= check("override werkt ook op de hele persoonlijke config", v.instellingen(eigen)[0] == vcfg)
    ok &= check("override drempels werkt", dr["geluid_rustig_lden"] == 45)
    ok &= check("standaard ongewijzigd na een override", v.STANDAARD["max_calls_per_run"] == 60
                and v.STANDAARD["bronnen"]["geluid"] is True)
    ok &= check("LBM_KLASSE en FUND_KLASSE zijn die van funda_beoordeling",
                v.LBM_KLASSE is fb.LBM_KLASSE and v.FUND_KLASSE is fb.FUND_KLASSE)
    ok &= check("klassen van de Klimaateffectatlas zijn precies FUND_KLASSE, van laag naar hoog",
                all([k for _, k in grenzen] == list(fb.FUND_KLASSE) for grenzen in v.KEA_KLASSEN.values()))
    ok &= check("drempels van de verrijking komen uit funda_beoordeling.STANDAARD",
                v.DREMPELS == {k: fb.STANDAARD["drempels"][k] for k in v.DREMPEL_SLEUTELS}
                and v.instellingen({})[1] == v.DREMPELS)
    bron = (HIER / "funda_verrijking.py").read_text(encoding="utf-8")
    ok &= check("geen eigen kopie van de klassen in funda_verrijking.py",
                "LBM_KLASSE = " not in bron and "FUND_KLASSE = " not in bron)
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


class NepGeo:
    """Nep-HTTP voor de geocoding: robots.txt van api.pdok.nl en de collectie adres in de gemeten vorm.

    punten: postcode -> lijst van (lon, lat, status). Een postcode die er niet in staat, geeft een
    lege FeatureCollection, zoals PDOK bij een onbekende postcode."""

    def __init__(self, punten: dict | None = None, robots: tuple[int, bytes] | None = None):
        self.punten = punten or {}
        self.robots = robots or (200, b"User-agent: *\nAllow: /\nDisallow: /bzk/locatieserver/*\n")
        self.calls: list[str] = []
        self.timeouts: list = []
        self.headers: list[dict] = []
        self.status: int | None = None
        self.time_out = False

    def __call__(self, url: str, timeout=None, headers=None):
        self.calls.append(url)
        self.timeouts.append(timeout)
        self.headers.append(dict(headers or {}))
        d = urllib.parse.urlparse(url)
        if d.path == "/robots.txt":
            return self.robots
        if self.time_out:
            raise TimeoutError("nep")
        if self.status is not None:
            return self.status, b"{}"
        if d.hostname == "api.pdok.nl" and d.path.endswith("/adres/items"):
            pc = urllib.parse.parse_qs(d.query)["postcode"][0]
            basis = fixture("bag_adres_postcode.json")
            sjabloon = basis["features"][0]
            fs = []
            for lon, lat, status in self.punten.get(pc, []):
                f = copy.deepcopy(sjabloon)
                f["properties"].update({"postcode": pc, "status": status})
                f["geometry"]["coordinates"] = [lon, lat]
                fs.append(f)
            basis["features"], basis["numberReturned"] = fs, len(fs)
            return 200, json.dumps(basis).encode()
        return 404, b"{}"


def test_geocode() -> bool:
    """Postcode naar punt via de BAG-collectie adres op api.pdok.nl (CLAUDE.md, "Geocoding en routes")."""
    print("Geocoding van postcodes via PDOK BAG (adres)")
    ok = check("postcode_norm", v.postcode_norm("2511 bt") == "2511BT" and v.postcode_norm(" 2511BT ") == "2511BT"
               and v.postcode_norm("251BT") is None and v.postcode_norm(None) is None
               and v.postcode_norm("2511BT1") is None)
    ok &= check("coord_paar", v.coord_paar([52.1, 4.3]) == (52.1, 4.3) and v.coord_paar(("52", "4")) == (52.0, 4.0)
                and v.coord_paar([52.1]) is None and v.coord_paar(["x", 4]) is None and v.coord_paar(None) is None)
    url = v.postcode_url("2511BT")
    d = urllib.parse.urlparse(url)
    ok &= check("URL: BAG-collectie adres op api.pdok.nl, filter op postcode, f=json",
                d.hostname == "api.pdok.nl" and d.path == "/kadaster/bag/ogc/v2/collections/adres/items"
                and urllib.parse.parse_qs(d.query) == {"postcode": ["2511BT"], "limit": [str(v.GEOCODE_LIMIET)],
                                                       "f": ["json"]}, url)
    regels = v.robots_regels("User-agent: *\nAllow: /\nDisallow: /bzk/locatieserver/*\n")
    ok &= check("robots.txt van api.pdok.nl staat dit pad toe", v.robots_mag(regels, d.path + "?" + d.query))

    # Het echte (ingekorte) antwoord: 4 adressen, waarvan 1 ingetrokken. Gemiddelde van de 3 uitgegeven.
    echt = fixture("bag_adres_postcode.json")
    punt = v.postcode_punt_parse(echt, "2511BT")
    uitgegeven = [f["geometry"]["coordinates"] for f in echt["features"]
                  if f["properties"]["status"] == "Naamgeving uitgegeven"]
    verwacht = (round(sum(c[1] for c in uitgegeven) / 3, 6), round(sum(c[0] for c in uitgegeven) / 3, 6))
    ok &= check("echt antwoord: gemiddelde van de uitgegeven adressen, (lat, lon)",
                len(uitgegeven) == 3 and punt == verwacht and 52.07 < punt[0] < 52.08 and 4.31 < punt[1] < 4.32,
                str(punt))
    alleen_ingetrokken = copy.deepcopy(echt)
    alleen_ingetrokken["features"] = [f for f in alleen_ingetrokken["features"]
                                      if f["properties"]["status"] != "Naamgeving uitgegeven"]
    ok &= check("alleen een ingetrokken adres: dat punt",
                v.postcode_punt_parse(alleen_ingetrokken, "2511BT") == (52.078037, 4.317236))
    ok &= check("andere postcode in het antwoord telt niet", v.postcode_punt_parse(echt, "9999ZZ") is None)
    buiten = copy.deepcopy(echt)
    for f in buiten["features"]:
        f["geometry"]["coordinates"] = [52.07, 4.31]          # omgedraaid: geen punt in Nederland
    ok &= check("punt buiten Nederland telt niet", v.postcode_punt_parse(buiten, "2511BT") is None)
    ok &= check("leeg antwoord", v.postcode_punt_parse({"features": []}, "2511BT") is None
                and v.postcode_punt_parse({}, "2511BT") is None)

    # Door de Geocoder, met fictieve postcodes.
    web = NepGeo({"1011AB": [(4.90, 52.37, "Naamgeving uitgegeven"), (4.91, 52.38, "Naamgeving uitgegeven")]})
    g = v.Geocoder(http=web, ua=UA, slaap=STIL)
    punt, reden = g.punt("1011 ab")
    ok &= check("gevonden: (lat, lon), geen reden", punt == (52.375, 4.905) and reden is None, f"{punt} {reden}")
    ok &= check("eerst robots.txt van api.pdok.nl, dan de adresvraag",
                [urllib.parse.urlparse(u).path for u in web.calls]
                == ["/robots.txt", "/kadaster/bag/ogc/v2/collections/adres/items"], str(web.calls))
    ok &= check("eerlijke user-agent en een ruime time-out",
                {h.get("User-Agent") for h in web.headers} == {UA} and all(t >= 30 for t in web.timeouts),
                str(web.timeouts))
    g.punt("1011AB")
    ok &= check("zelfde postcode deze run: geen tweede verzoek", len(web.calls) == 2, str(len(web.calls)))
    punt, reden = g.punt("1012AB")
    ok &= check("onbekende postcode: None met reden, zonder postcode erin",
                punt is None and "niet gevonden" in (reden or "") and "1012" not in (reden or ""), str(reden))
    g.punt("1012AB")
    ok &= check("ook een mislukte postcode maar één poging per run, robots.txt één keer",
                len(web.calls) == 3 and sum(u.endswith("/robots.txt") for u in web.calls) == 1, str(web.calls))
    ok &= check("ongeldige postcode: geen verzoek", g.punt("onzin") == (None, "geen geldige postcode")
                and len(web.calls) == 3)
    ok &= check("alleen api.pdok.nl, nooit Nominatim of de Locatieserver",
                {urllib.parse.urlparse(u).hostname for u in web.calls} == {"api.pdok.nl"}
                and not any("locatieserver" in u or "nominatim" in u for u in web.calls))

    web = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    web.time_out = True
    g = v.Geocoder(http=web, ua=UA, slaap=STIL)
    eerste, tweede = g.punt("1011AB"), g.punt("1012AB")
    ok &= check("time-out: None, en de host is deze run dicht (geen tweede poging)",
                eerste[0] is None and tweede[0] is None and len(web.calls) == 2 and "api.pdok.nl" in g.sessie.dicht,
                f"{eerste} {tweede} {web.calls}")
    for status in (403, 429, 503):
        web = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
        web.status = status
        g = v.Geocoder(http=web, ua=UA, slaap=STIL)
        punt, reden = g.punt("1011AB")
        g.punt("1012AB")
        ok &= check(f"status {status}: None, host dicht, niet omzeild", punt is None and str(status) in (reden or "")
                    and len(web.calls) == 2, f"{reden} {web.calls}")
    web = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]},
                 robots=(200, b"User-agent: *\nDisallow: /kadaster/\n"))
    punt, reden = v.Geocoder(http=web, ua=UA, slaap=STIL).punt("1011AB")
    ok &= check("robots.txt verbiedt het pad: alleen robots.txt opgevraagd",
                punt is None and "robots" in (reden or "") and len(web.calls) == 1, f"{reden} {web.calls}")
    web = NepGeo()

    def kapot(url, timeout=None, headers=None):
        web.calls.append(url)
        return (200, b"User-agent: *\nAllow: /\n") if url.endswith("/robots.txt") else (200, b"geen json")
    punt, reden = v.Geocoder(http=kapot, ua=UA, slaap=STIL).punt("1011AB")
    ok &= check("geen geldige JSON: None met reden, gooit niet", punt is None and "JSON" in (reden or ""), str(reden))
    return ok


def test_geocode_gedeelde_stand() -> bool:
    """Geocoding en verrijking spreken allebei api.pdok.nl aan en hebben één stand (CLAUDE.md, "Geocoding en
    routes"): een weigering geldt een dag voor beide en komt in de cache, een serverfout sluit de host de
    rest van de run ook voor de verrijking, robots.txt één keer per run. Een time-out van het zware
    postcodeverzoek gaat niet mee. Fictieve postcodes, de 13 fictieve woningen."""
    print("Geocoding en verrijking: één stand voor api.pdok.nl")
    ws = woningen()[:3]
    pdok_paden = ("/kadaster/bag/", "/cbs/wijken-en-buurten-2024/")
    ok = check("limit=1 in de adresvraag (stopt bij het eerste adres)", "&limit=1&" in v.postcode_url("1011AB"),
               v.postcode_url("1011AB"))

    # 1. Weigering bij de geocoding: de verrijking in dezelfde run stuurt niets naar api.pdok.nl.
    geo = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    geo.status = 429
    g = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache={})   # de cache, los geladen
    punt, reden = g.punt("1011AB")
    ok &= check("geocoding: 429 = geen punt", punt is None and "429" in (reden or ""), str(reden))
    cache: dict = {}                                                          # de cache van genereer_rapport
    web = NepWeb(ws)
    logs: list[str] = []
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=logs.append, vooraf=g.sessie)
    ok &= check("verrijking dezelfde run: geen verzoek naar api.pdok.nl, ook geen robots.txt",
                web.aantal("api.pdok.nl") == 0, str([u for u in web.calls if "pdok" in u][:3]))
    ok &= check("en bag onbekend met de weigering als reden, andere hosts gewoon",
                all(uit[str(w["global_id"])]["bag"]["status"] == "onbekend"
                    and "429" in (uit[str(w["global_id"])]["bag"]["reden"] or "") for w in ws)
                and web.aantal("data.rivm.nl") > 0)
    ok &= check("weigering in funda_enrichment_cache.json (verrijking_weigering)",
                (cache.get("verrijking_weigering") or {}).get("api.pdok.nl") == {"datum": VANDAAG, "status": 429},
                str(cache.get("verrijking_weigering")))
    ok &= check("log: api.pdok.nl gestopt, alleen de reden",
                any("api.pdok.nl deze run gestopt: geweigerd (status 429)" in r for r in logs), str(logs))
    web2 = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("volgende run dezelfde dag: nog steeds dicht", web2.aantal("api.pdok.nl") == 0)
    web3 = NepWeb(ws)
    uit3 = v.verrijk(ws, cache, cfg(), dag(1), http=web3, ua=UA, log=STIL)
    ok &= check("dag erna: opnieuw, en dan ok", web3.aantal("api.pdok.nl", "/kadaster/bag/") >= 1
                and all(uit3[str(w["global_id"])]["bag"]["status"] == "ok" for w in ws))

    # 2. Weigering bij de verrijking: de Geocoder (die de cache meekrijgt) vraagt die dag niets.
    cache = {"verrijking_weigering": {"api.pdok.nl": {"datum": VANDAAG, "status": 403}}}
    geo = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    punt, reden = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache=cache).punt("1011AB")
    ok &= check("eerdere weigering van de verrijking: geocoding stuurt niets, ook geen robots.txt",
                punt is None and "403" in (reden or "") and geo.calls == [], f"{reden} {geo.calls}")
    punt, _ = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=dag(1), cache=cache).punt("1011AB")
    ok &= check("dag erna: geocoding weer geprobeerd", punt == (52.37, 4.9) and len(geo.calls) == 2, str(geo.calls))

    # 3. Serverfout bij de geocoding: de rest van de run dicht, niet bewaard.
    geo = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    geo.status = 503
    g = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache={})
    g.punt("1011AB")
    cache = {}
    web = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL, vooraf=g.sessie)
    ok &= check("503 bij de geocoding: verrijking deze run niet naar api.pdok.nl, geen weigering bewaard",
                web.aantal("api.pdok.nl") == 0 and not (cache.get("verrijking_weigering") or {}))
    web2 = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web2, ua=UA, log=STIL)
    ok &= check("volgende run: weer geprobeerd", web2.aantal("api.pdok.nl", "/kadaster/bag/") >= 1)

    # 4. Time-out bij de geocoding: de verrijking gaat door, robots.txt niet opnieuw.
    geo = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    geo.time_out = True
    g = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache={})
    punt, _ = g.punt("1011AB")
    cache = {}
    web = NepWeb(ws)
    uit = v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL, vooraf=g.sessie)
    ok &= check("time-out bij de geocoding: verrijking vraagt api.pdok.nl wel, en krijgt bag",
                punt is None and any(web.aantal("api.pdok.nl", p) for p in pdok_paden)
                and all(uit[str(w["global_id"])]["bag"]["status"] == "ok" for w in ws))
    ok &= check("robots.txt van api.pdok.nl één keer deze run (bij de geocoding)",
                sum(u.endswith("/robots.txt") for u in geo.calls) == 1 and web.aantal("api.pdok.nl", "/robots.txt") == 0)

    # 5. Geslaagd: robots.txt één keer, en in de cache.
    geo = NepGeo({"1011AB": [(4.9, 52.37, "Naamgeving uitgegeven")]})
    g = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache={})
    g.punt("1011AB")
    cache = {}
    web = NepWeb(ws)
    v.verrijk(ws, cache, cfg(), VANDAAG, http=web, ua=UA, log=STIL, vooraf=g.sessie)
    ok &= check("geslaagd: robots.txt niet opnieuw, wel in de cache",
                web.aantal("api.pdok.nl", "/robots.txt") == 0 and web.aantal("api.pdok.nl", "/kadaster/bag/") >= 1
                and ((cache.get("robots") or {}).get("api.pdok.nl") or {}).get("fetched") == VANDAAG)

    # 6. neem_cache_over: per host de nieuwste, de Geocoder bij gelijke datum; verrijking uit = toch bewaard.
    nieuwer = {"robots": {"api.pdok.nl": {"fetched": dag(1), "data": {"regels": []}}}}
    v.neem_cache_over(nieuwer, g.sessie)
    ok &= check("neem_cache_over: een nieuwere versie blijft staan", nieuwer["robots"]["api.pdok.nl"]["fetched"] == dag(1))
    geo = NepGeo()
    geo.status = 429
    g = v.Geocoder(http=geo, ua=UA, slaap=STIL, vandaag=VANDAAG, cache={})
    g.punt("1011AB")
    cache = {"verrijking_weigering": "kapot"}
    v.verrijk(ws, cache, {"beoordeling": {"verrijking": {"aan": False}}}, VANDAAG, http=NepWeb(ws), ua=UA, log=STIL,
              vooraf=g.sessie)
    ok &= check("verrijking uit: de weigering van de geocoding komt toch in de cache",
                cache["verrijking_weigering"].get("api.pdok.nl", {}).get("status") == 429, str(cache))
    return ok


def main() -> int:
    resultaten = [test_parsers(), test_gray_index(), test_volledige_run(), test_bron_faalt(), test_weigering(),
                  test_fout_opnieuw(), test_allowlist(), test_budget(), test_uit(), test_signalen(), test_robots(), test_robots_een_dag(),
                  test_log(), test_bag_matching(), test_vorm(), test_ua(), test_een_bron(), test_doorverwijzing(), test_geocode(), test_geocode_gedeelde_stand()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
