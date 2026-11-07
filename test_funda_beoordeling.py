"""Offline tests voor funda_beoordeling.py: leentoets 2026, scenario's, poort, score, parsers,
sortering en het datacontract. Geen netwerk, alleen fictieve data.

Draaien: python test_funda_beoordeling.py

De golden file testdata/beoordeling_verwacht.json is de uitvoer van beoordeel() op
testdata/woningen.json met het fictieve profiel uit die fixture (plus de fictieve grens van
€ 1.450 en de fictieve verrijking hieronder). Na een bewuste wijziging van het model:
    python test_funda_beoordeling.py --schrijf-verwacht
en het verschil in de PR uitleggen.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

import funda_beoordeling as fb  # noqa: E402

FIXTURE = HIER / "testdata" / "woningen.json"
VERWACHT = HIER / "testdata" / "beoordeling_verwacht.json"
VANDAAG = "2026-11-06"          # de fixture is van 6 november 2026; vaste klok voor de tests
GRENS_FICTIEF = 1450            # fictieve netto grens van de fixture (beoordeling.md par. 10)
TWIJFEL_BUURTEN_FIXTURE = ("Mariahoeve", "Houtwijk", "Leyenburg")

# FICTIEF: verzonnen verrijkingswaarden (vorm van funda_verrijking), geen meting van een echte
# buurt of een echt pand. "fout" = de bron gaf geen antwoord; None bij trein = onder de kaartgrens.
VERRIJKING_FICTIEF = {
    "w01": {"bag": {"bouwjaar": 1932, "aantal_vbo_pand": 3}, "fundering": {"verschilzetting": "zeer laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 48, "lnight_weg": 39, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 9, "onv": 0.10, "tevreden_woonomgeving": 91}},
    "w02": {"bag": {"bouwjaar": 1925, "aantal_vbo_pand": 4}, "fundering": {"verschilzetting": "laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 52, "lnight_weg": 43, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 8, "onv": 0.05, "tevreden_woonomgeving": 89}},
    "w03": {"bag": {"bouwjaar": 1962, "aantal_vbo_pand": 64}, "fundering": {"verschilzetting": "matig", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 61, "lnight_weg": 52, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 5, "onv": -0.05, "tevreden_woonomgeving": 84}},
    "w04": {"bag": {"bouwjaar": 1908, "aantal_vbo_pand": 3}, "fundering": "fout",
            "geluid": {"lden_weg": 50, "lnight_weg": 41, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 8, "onv": 0.08, "tevreden_woonomgeving": 92}},
    "w05": {"bag": {"bouwjaar": 1929, "aantal_vbo_pand": 6}, "fundering": {"verschilzetting": "laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 57, "lnight_weg": 48, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 7, "onv": 0.02, "tevreden_woonomgeving": 88}},
    "w06": {"bag": {"bouwjaar": 1958, "aantal_vbo_pand": 48}, "fundering": {"verschilzetting": "hoog", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 47, "lnight_weg": 38, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 7, "onv": 0.04, "tevreden_woonomgeving": 92}},
    "w07": {"bag": {"bouwjaar": 1998, "aantal_vbo_pand": 36}, "fundering": "niet_nodig",
            "geluid": {"lden_weg": 49, "lnight_weg": 40, "lden_trein": 58, "lnight_trein": 50},
            "buurt": {"kscore": 6, "onv": -0.02, "tevreden_woonomgeving": 87}},
    "w08": {"bag": {"bouwjaar": 2021, "aantal_vbo_pand": 120}, "fundering": "niet_nodig",
            "geluid": {"lden_weg": 63, "lnight_weg": 54, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 5, "onv": -0.18, "tevreden_woonomgeving": 78}},
    "w09": {"bag": {"bouwjaar": 1895, "aantal_vbo_pand": 2}, "fundering": {"verschilzetting": "matig", "paalrot": "laag"},
            "geluid": {"lden_weg": 54, "lnight_weg": 45, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 6, "onv": -0.08, "tevreden_woonomgeving": 85}},
    "w10": {"bag": {"bouwjaar": 1968, "aantal_vbo_pand": 80}, "fundering": {"verschilzetting": "laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 56, "lnight_weg": 47, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 6, "onv": -0.04, "tevreden_woonomgeving": 86}},
    "w11": {"bag": {"bouwjaar": 1935, "aantal_vbo_pand": 4}, "fundering": {"verschilzetting": "zeer laag", "paalrot": "zeer laag"},
            "geluid": "fout", "buurt": {"kscore": 4, "onv": -0.21, "tevreden_woonomgeving": 79}},
    "w12": {"bag": {"bouwjaar": 1955, "aantal_vbo_pand": 8}, "fundering": {"verschilzetting": "laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 53, "lnight_weg": 44, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 7, "onv": 0.01, "tevreden_woonomgeving": 90}},
    "w13": {"bag": {"bouwjaar": 1936, "aantal_vbo_pand": 5}, "fundering": {"verschilzetting": "zeer laag", "paalrot": "zeer laag"},
            "geluid": {"lden_weg": 45, "lnight_weg": 36, "lden_trein": None, "lnight_trein": None},
            "buurt": {"kscore": 9, "onv": 0.12, "tevreden_woonomgeving": 93}},
}

# FICTIEF financien-blok voor de scenariotests. Geen echte cijfers.
FINANCIEN_FICTIEF = {
    "alleenstaand": True,
    "starter_tot": "2030-01-01",
    "scenarios": {
        "nu": {"bruto_jaar": 52000, "label": "Nu"},
        "2027_01": {"bruto_jaar": 56000, "label": "Vanaf jan 2027"},
        "2027_01_met_cao": {"bruto_jaar": 61000, "label": "Met cao-verhoging"},
    },
    "studieschuld": {"maandlast": 40},
    "bkr": [{"limiet": 1000, "opgezegd": True}],
    "eigen_geld": {"nu": 10000, "datum": "2026-11-06", "per_maand": 300, "buffer": 1500},
    "kosten_koper": {"vast": 5000, "nhg_pct": 0.4},
    "rente": {"pct": 4.2, "datum": "2026-11-01", "rentevast_jaren": 10},
}


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return bool(voorwaarde)


# ---------------------------------------------------------------------------------------
# Hulp: fixture omzetten naar de invoer van beoordeel(), zoals funda_rapport dat straks doet
# ---------------------------------------------------------------------------------------
def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _km(listing: dict, werk: dict, factor: float) -> float:
    dlat = math.radians(werk["lat"] - listing["latitude"])
    dlon = math.radians(werk["lon"] - listing["longitude"])
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(listing["latitude"])) * math.cos(math.radians(werk["lat"]))
         * math.sin(dlon / 2) ** 2)
    return round(2 * 6371 * math.asin(math.sqrt(a)) * factor, 1)


def _verrijking(wid: str) -> dict:
    uit = {}
    for bron, v in VERRIJKING_FICTIEF.get(wid, {}).items():
        if v == "fout":
            uit[bron] = {"status": "onbekend", "data": None, "reden": "bron gaf geen antwoord"}
        elif v == "niet_nodig":
            uit[bron] = {"status": "niet_nodig", "data": None}
        else:
            uit[bron] = {"status": "ok", "data": v}
    return uit


def invoer(w: dict, fx: dict) -> tuple:
    """(d, details, routes, twijfel) voor één fixture-woning."""
    listing = w["listing"]
    d = dict(listing)
    d["_track"] = w["track"]
    markt = fx["markt"].get(w["fixture"].get("markt_sleutel") or "") or {}
    mk = fx["makelaars"].get(str(w["fixture"].get("makelaar") or ""), {})
    rev = mk.get("reviews") if isinstance(mk.get("reviews"), dict) and "_fout" not in mk.get("reviews", {}) else {}
    d["_enrichment"] = {
        "price_history": {"changes": w["price_history"] if isinstance(w["price_history"], list) else []},
        "market": {"avg_asking_price_per_m2": markt.get("avg_asking_price_per_m2"), "insights": markt},
        "broker": {"name": (mk.get("info") or {}).get("name"), "review_average": rev.get("average"),
                   "review_count": rev.get("number_of_reviews")},
    }
    osrm = bool(w["fixture"].get("osrm"))
    routes = [{"label": x["label"], "km": _km(listing, x, 1.27 if osrm else 1.3), "soort": "weg" if osrm else "schatting"}
              for x in fx["meta"]["werk"]]
    twijfel = []
    if listing.get("neighbourhood") in TWIJFEL_BUURTEN_FIXTURE:
        twijfel.append(f"Twijfelbuurt {listing['neighbourhood']} (jouw lijst). Onderaan gezet.")
    if "leidschendam-voorburg" in (listing.get("city") or "").lower():
        twijfel.append("Stad onduidelijk: Leidschendam of Voorburg? Funda geeft alleen de gemeente.")
    return d, listing, routes, twijfel


def beoordeel_fixture() -> list[dict]:
    fx = _fixture()
    profiel = fx["meta"]["profiel"]
    cfg = fb.laad_config(dict(profiel, beoordeling={"max_woonlasten_netto": GRENS_FICTIEF}))
    rijen = []
    for w in fx["woningen"]:
        d, details, routes, twijfel = invoer(w, fx)
        b = fb.beoordeel(d, details, routes, twijfel, profiel, cfg, _verrijking(w["fixture"]["id"]), vandaag=VANDAAG)
        rijen.append({"id": w["fixture"]["id"], "beoordeling": b})
    return fb.sorteer(rijen)


def _minimaal(**extra) -> dict:
    """Een fictieve woning zonder kenmerken en zonder tekst."""
    d = {"title": "Teststraat 1", "city": "Den Haag", "neighbourhood": "Testbuurt", "price": None, "living_area": None}
    d.update(extra)
    return d


def _fin_woning(prijs, label="C", canon=0, vve=150, energie=170, woz=None) -> dict:
    return {"prijs": prijs, "label": label, "canon_jaar": canon, "vve": vve, "vve_bron": "kenmerk 'Bijdrage VvE'",
            "energie": energie, "stook_in_vve": False, "woz": woz}


# ---------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------
def test_leentoets() -> bool:
    print("test: leentoets 2026 (tabel 1, labels, alleenstaand, studieschuld, BKR, canon, toetsrente)")
    ok = True
    t = fb.tabel()
    ok &= check("tabeljaar = lopend jaar (faalt op 1 januari: vervang dan de tabel)", t["jaar"] == date.today().year,
                f"tabel {t['jaar']}, nu {date.today().year}")
    ok &= check("96 rijen, 30.000 tot en met 125.000", len(t["_rijen"]) == 96 and min(t["_rijen"]) == 30000
                and max(t["_rijen"]) == 125000)
    ok &= check("62.000 en 4,11% geeft 23,6%", abs(fb.fl_pct(62000, 0.0411) - 0.236) < 1e-9, str(fb.fl_pct(62000, 0.0411)))
    ok &= check("rente als procent werkt ook (4,11)", fb.fl_pct(62000, fb.toetsrente(4.11, 30)) == fb.fl_pct(62000, 0.0411))
    ok &= check("kolomgrens 4,000% valt in 3,501 tot 4,000", abs(fb.fl_pct(62000, 0.04) - 0.227) < 1e-9)
    ok &= check("kolomgrens 4,001% valt in 4,001 tot 4,500", abs(fb.fl_pct(62000, 0.04001) - 0.236) < 1e-9)
    ok &= check("onder 30.000 geldt de rij van 30.000", fb.fl_pct(25000, 0.0411) == fb.fl_pct(30000, 0.0411) == 0.209)
    ok &= check("boven 125.000 geldt de rij van 125.000", fb.fl_pct(140000, 0.07) == 0.322)
    ok &= check("rij 31.999 = rij 31.000", fb.fl_pct(31999, 0.03) == 0.193)
    mh = fb.max_hypotheek(62000, 0.0411, 30, "C", alleenstaand=True)
    ok &= check("label C alleenstaand bij 4,11% = € 274.043 (audit)", abs(mh - 274043) <= 1, str(mh))
    zonder = fb.max_hypotheek(62000, 0.0411, 30, "C", alleenstaand=False)
    ok &= check("alleenstaand telt 17.000", mh - zonder == 17000, str(mh - zonder))
    ok &= check("alleenstaand alleen boven 30.000",
                fb.max_hypotheek(30000, 0.0411, alleenstaand=True) == fb.max_hypotheek(30000, 0.0411, alleenstaand=False)
                and fb.max_hypotheek(30001, 0.0411, alleenstaand=True) - fb.max_hypotheek(30001, 0.0411) == 17000)
    labels = {lab: fb.label_bedrag(lab) for lab in ("G", "F", "E", "D", "C", "B", "A", "A+", "A++", "A+++", "A++++", "?", None)}
    ok &= check("bedragen per label (art. 4 lid 3)", labels == {"G": 0, "F": 0, "E": 0, "D": 5000, "C": 5000, "B": 10000,
                "A": 10000, "A+": 20000, "A++": 20000, "A+++": 25000, "A++++": 30000, "?": 0, None: 0}, str(labels))
    basis = fb.leentoets(62000, 0.0411)
    ok &= check("toetsrente bij 10 jaar vast = werkelijke rente", fb.toetsrente(0.0411, 10) == 0.0411)
    ok &= check("toetsrente bij 5 jaar vast = 5%", fb.toetsrente(0.0411, 5) == 0.05)
    ok &= check("toetsrente bij 5 jaar vast en 5,6% rente = 5,6%", fb.toetsrente(0.056, 5) == 0.056)
    kort = fb.leentoets(62000, 0.0411, rentevast_jaren=5)
    ok &= check("korte rentevaste periode verlaagt de max. hypotheek", kort["max_hypotheek"] < basis["max_hypotheek"]
                and kort["fl_pct"] == fb.fl_pct(62000, 0.05))
    st = fb.leentoets(62000, 0.0411, studieschuld_maand=100)
    ok &= check("studieschuld: maandlast x weging 1,25 bij 4,001 tot 4,500%",
                st["studieschuld_weging"] == 1.25 and abs(st["aftrek_studieschuld"] - 125.0) < 1e-9)
    ok &= check("studieschuld weging 1,20 bij 3,501 tot 4,000%", fb.studieschuld_weging(0.04) == 1.20)
    ok &= check("wegingstabel heeft 12 kolommen, oplopend",
                len(fb.STUDIESCHULD_WEGING) == 12 and fb.STUDIESCHULD_WEGING == sorted(fb.STUDIESCHULD_WEGING))
    ok &= check("studieschuld verlaagt de max. hypotheek",
                abs((basis["max_hypotheek"] - st["max_hypotheek"]) - 125 / fb.annuiteit(1, 0.0411)) <= 1)
    bkr = fb.leentoets(62000, 0.0411, bkr_maand=fb.BKR_PCT_LIMIET * 5000)
    ok &= check("BKR: 2% van de limiet per maand", abs(bkr["aftrek_bkr"] - 100) < 1e-9
                and bkr["max_hypotheek"] < basis["max_hypotheek"])
    canon = fb.leentoets(62000, 0.0411, canon_jaar=1200)
    ok &= check("erfpachtcanon: canon/12 van de toegestane last", abs(canon["aftrek_canon"] - 100) < 1e-9
                and canon["max_hypotheek"] < basis["max_hypotheek"])
    ok &= check("geen negatieve hypotheek bij hoge lasten", fb.leentoets(30000, 0.0411, studieschuld_maand=5000)["basis"] == 0)
    return ok


def test_kosten_koper_en_koopsom() -> bool:
    print("test: kosten koper en max. koopsom")
    ok = True
    kk, soort = fb.kosten_koper(250000, 250000, True)
    ok &= check("starter: vast + 0,4% NHG, geen overdrachtsbelasting", (kk, soort) == (7000, "startersvrijstelling"), f"{kk} {soort}")
    kk, soort = fb.kosten_koper(250000, 250000, False)
    ok &= check("geen starter: 2% overdrachtsbelasting", (kk, soort) == (12000, "2% overdrachtsbelasting"), f"{kk} {soort}")
    kk, soort = fb.kosten_koper(600000, 450000, True)
    ok &= check("starter boven de grens van 555.000 betaalt 2%", soort == "2% overdrachtsbelasting" and kk == 6000 + 1800 + 12000, str(kk))
    kk, _ = fb.kosten_koper(500000, 480000, True)
    ok &= check("geen NHG-premie boven 470.000", kk == 6000, str(kk))
    kk, _ = fb.kosten_koper(300000, 300000, True, kk_vast=5000, nhg_pct=0.4)
    ok &= check("nhg_pct in procent (0,4) werkt", kk == 6200, str(kk))
    for starter in (True, False):
        mk = fb.max_koopsom(280000, 12000, starter, 5000, 0.004)
        k1, _ = fb.kosten_koper(mk, min(mk, 280000), starter, 5000, 0.004)
        k2, _ = fb.kosten_koper(mk + 50, min(mk + 50, 280000), starter, 5000, 0.004)
        ok &= check(f"max. koopsom ({'starter' if starter else 'geen starter'}) past precies",
                    mk - 280000 + k1 <= 12000 + 0.5 and (mk + 50) - 280000 + k2 > 12000, str(mk))
    ok &= check("te weinig eigen geld voor de vaste kosten: max. koopsom 0", fb.max_koopsom(280000, 1000, True, 5000, 0.004) == 0)
    return ok


def test_scenarios() -> bool:
    print("test: scenario's uit een fictief financien-blok")
    ok = True
    cfg = fb.laad_config({"leeftijd": 30, "beoordeling": {"max_woonlasten_netto": 1600}, "financien": FINANCIEN_FICTIEF})
    rente = {"pct": 4.2, "bron": "handmatig", "datum": "2026-11-01", "oud": False, "melding": None}
    inv = fb.financien_invoer(cfg, {"leeftijd": 30}, VANDAAG)
    ok &= check("planning standaard 2027_01", inv["planning"] == "2027_01")
    ok &= check("scenario's op datum, cao na de basis", [s["id"] for s in inv["scenarios"]] == ["nu", "2027_01", "2027_01_met_cao"])
    eg = {s["id"]: fb._eigen_geld_op(inv, s) for s in inv["scenarios"]}
    ok &= check("eigen geld groeit per maand tot de scenariodatum", eg == {"nu": 10000, "2027_01": 10600, "2027_01_met_cao": 10600}, str(eg))
    ok &= check("opgezegde BKR-limiet telt niet", inv["bkr_maand"] == 0)

    overzicht = fb.scenario_overzicht(cfg, {"leeftijd": 30}, rente, VANDAAG)
    mh = {s["id"]: s["max_hypotheek"] for s in overzicht}
    ok &= check("max. hypotheek stijgt met het inkomen", mh["nu"] < mh["2027_01"] < mh["2027_01_met_cao"], str(mh))
    verwacht_nu = fb.max_hypotheek(52000, 0.042, 10, None, 0, 40, 0, True)
    ok &= check("scenario nu = leentoets met studieschuld en alleenstaand", mh["nu"] == verwacht_nu, f"{mh['nu']} {verwacht_nu}")
    mk_nu = next(s["max_koopsom"] for s in overzicht if s["id"] == "nu")
    ok &= check("max. koopsom = max. koopsom(max. hyp, eigen geld min buffer)",
                mk_nu == fb.max_koopsom(mh["nu"], 10000 - 1500, True, 5000, 0.004), str(mk_nu))

    def fin_voor(prijs, label="C", cfg_=cfg):
        return fb.financiering(_fin_woning(prijs, label), cfg_, {"leeftijd": 30}, rente, VANDAAG)

    mk = {s["id"]: s["max_koopsom"] for s in overzicht}
    gevallen = [
        (mk["nu"] - 6000, "Past nu"),
        ((mk["nu"] + mk["2027_01"]) // 2 + 4000, "Past vanaf jan 2027"),
        ((mk["2027_01"] + mk["2027_01_met_cao"]) // 2 + 6000, "Alleen met cao-verhoging"),
        (mk["2027_01_met_cao"] + 30000, "Past in geen scenario"),
    ]
    for prijs, tekst in gevallen:
        f = fin_voor(prijs)
        ok &= check(f"scenario-tekst bij {prijs}: {tekst}", f["scenario_tekst"] == tekst, str(f["scenario_tekst"]))
    f = fin_voor(gevallen[1][0])
    ok &= check("scenario's in het contract: id, label, max_hypotheek, max_koopsom, past",
                all(set(s) == {"id", "label", "max_hypotheek", "max_koopsom", "past"} for s in f["scenarios"])
                and [s["id"] for s in f["scenarios"]] == ["nu", "2027_01", "2027_01_met_cao"]
                and all(isinstance(s["past"], bool) for s in f["scenarios"]))
    ok &= check("planning in de financiering", f["planning"] == "2027_01")
    plan = next(s for s in f["scenarios"] if s["id"] == "2027_01")
    ok &= check("de poort volgt het planningsscenario", f["max_hypotheek"] == plan["max_hypotheek"] and plan["past"]
                and f["poort"] in ("PAST", "KRAP"), f"{f['poort']} {f['max_hypotheek']}")
    cfg_nu = fb.laad_config({"leeftijd": 30, "beoordeling": {"max_woonlasten_netto": 1600},
                             "financien": dict(FINANCIEN_FICTIEF, planning="nu")})
    f_nu = fin_voor(gevallen[1][0], cfg_=cfg_nu)
    ok &= check("planning 'nu': dezelfde woning valt dan op eigen geld", f_nu["poort"] in ("KRAP", "PAST NIET")
                and f_nu["tekort"] > f["tekort"], f"{f_nu['poort']} {f_nu['tekort']}")
    g = fin_voor(gevallen[1][0], "G")
    a = fin_voor(gevallen[1][0], "A")
    ok &= check("label van de woning telt per scenario mee (A 10.000 meer dan G)",
                all(x["max_hypotheek"] - y["max_hypotheek"] == 10000 for x, y in zip(a["scenarios"], g["scenarios"])))
    tekst_alles = json.dumps([fin_voor(p)["scenario_tekst"] for p, _ in gevallen] + [fin_voor(p)["redenen"] for p, _ in gevallen])
    ok &= check("geen inkomensbedragen in scenario-tekst", not any(str(v) in tekst_alles or f"{v:,}".replace(",", ".") in tekst_alles
                                                                  for v in (52000, 56000, 61000)))

    leeg = fb.financiering(_fin_woning(None), cfg, {"leeftijd": 30}, rente, VANDAAG)
    ok &= check("prijs onbekend: geen scenario's, geen tekst", leeg["scenarios"] == [] and leeg["scenario_tekst"] is None
                and leeg["netto"] is None and leeg["poort"] == "PRIJS ONBEKEND")
    zonder = fb.financiering(_fin_woning(250000), fb.laad_config({"bruto_jaar": 52000, "eigen_inleg": 9000, "leeftijd": 30}),
                             {"bruto_jaar": 52000, "eigen_inleg": 9000, "leeftijd": 30}, rente, VANDAAG)
    ok &= check("zonder financien: lege lijst, planning None", zonder["scenarios"] == [] and zonder["planning"] is None
                and zonder["scenario_tekst"] is None and zonder["max_hypotheek"] > 0)

    # Aliassen (zoals de eigenaar zijn cijfers bijhoudt) geven hetzelfde als de gedocumenteerde vorm.
    alias = {
        "alleenstaand": True, "startersvrijstelling_tot": "2030-01-01",
        "toetsinkomen": {"nu": 52000, "2027_01": 56000, "2027_01_met_cao": 61000},
        "verplichtingen_maand": {"duo": 40}, "bkr_limieten": 0,
        "eigen_geld": {"nu": 10000, "per_maand": 300, "datum": "2026-11-06"}, "buffer": 1500,
        "kosten_koper": {"vast": 5000, "nhg_pct": 0.4},
        "rente": {"handmatig": 4.2, "datum": "2026-11-01", "rentevast_jaar": 10},
    }
    cfg_alias = fb.laad_config({"leeftijd": 30, "financien": alias})
    a1 = [(s["id"], s["max_hypotheek"], s["max_koopsom"]) for s in fb.scenario_overzicht(cfg_alias, {}, rente, VANDAAG)]
    a2 = [(s["id"], s["max_hypotheek"], s["max_koopsom"]) for s in overzicht]
    ok &= check("aliassen (toetsinkomen, verplichtingen_maand, buffer, ...) geven hetzelfde", a1 == a2, f"{a1} {a2}")
    ok &= check("rente uit financien.rente (handmatig)", fb.rente_uit_config(cfg_alias, VANDAAG)["pct"] == 4.2
                and fb.rente_uit_config(cfg_alias, VANDAAG)["bron"] == "handmatig")
    vast = dict(alias, eigen_geld={"nu": 10000, "2027_01": 20000})
    inv2 = fb.financien_invoer(fb.laad_config({"financien": vast}), {}, VANDAAG)
    ok &= check("vaste waarde eigen geld per scenario gaat voor",
                {s["id"]: fb._eigen_geld_op(inv2, s) for s in inv2["scenarios"]}["2027_01"] == 20000)
    bkr_open = fb.financien_invoer(fb.laad_config({"financien": dict(FINANCIEN_FICTIEF, bkr=[{"limiet": 2500}])}), {}, VANDAAG)
    ok &= check("niet opgezegde limiet: 2% per maand", bkr_open["bkr_maand"] == 50)
    return ok


def test_rente() -> bool:
    print("test: rente als parameter, uit de config of standaard")
    ok = True
    cfg = fb.laad_config({"bruto_jaar": 62000, "eigen_inleg": 10000, "leeftijd": 30})
    r = fb.rente_uit_config(cfg, VANDAAG)
    ok &= check("zonder rente: standaard 4,11% van 6 juli 2026 (par. 8.4)", r["pct"] == 4.11 and r["datum"] == "2026-07-06"
                and r["bron"] == "standaard")
    ok &= check("standaardrente is oud en geeft een melding", r["oud"] is True and "dagen oud" in (r["melding"] or ""))
    p = {"bruto_jaar": 62000, "eigen_inleg": 10000, "leeftijd": 30}
    f1 = fb.financiering(_fin_woning(250000), cfg, p, None, VANDAAG)
    f2 = fb.financiering(_fin_woning(250000), cfg, p, {"pct": 4.25, "bron": "ASN", "datum": "2026-11-05", "oud": False,
                                                       "melding": None}, VANDAAG)
    ok &= check("standaardrente in de financiering", f1["rente"] == 0.0411 and f1["rente_bron"] == "standaard"
                and f1["rentevast_jaren"] == 30)
    ok &= check("rente-parameter gaat voor (pct in procenten)", f2["rente"] == 0.0425 and f2["rente_datum"] == "2026-11-05"
                and f2["rente_bron"] == "ASN")
    ok &= check("hogere rente: hogere bruto maandlast", f2["opbouw"]["bruto_hyp"] > f1["opbouw"]["bruto_hyp"])
    cfg_h = fb.laad_config(dict(p, beoordeling={"financiering": {"rente": 0.039, "rente_datum": "2026-10-30"}}))
    rh = fb.rente_uit_config(cfg_h, VANDAAG)
    ok &= check("handmatige rente in beoordeling.financiering (fractie)", rh["pct"] == 3.9 and rh["bron"] == "handmatig"
                and rh["oud"] is False and rh["melding"] is None)
    return ok


def test_poort() -> bool:
    print("test: poort, grensgevallen en statusregel")
    ok = True
    cfg = fb.laad_config({})
    for tekort, verwacht in ((1500, "PAST"), (1501, "KRAP"), (5000, "KRAP"), (5001, "PAST NIET")):
        ok &= check(f"tekort {tekort} -> {verwacht}", fb.poort_financieel(tekort, 0, cfg) == verwacht)
    for over, verwacht in ((0, "PAST"), (1, "KRAP"), (150, "KRAP"), (151, "PAST NIET")):
        ok &= check(f"over {over} -> {verwacht}", fb.poort_financieel(0, over, cfg) == verwacht)
    cfg_m = fb.laad_config({"beoordeling": {"krap_marge": 50}})
    ok &= check("krap_marge instelbaar", fb.poort_financieel(0, 51, cfg_m) == "PAST NIET" and fb.poort_financieel(0, 50, cfg_m) == "KRAP")
    cfg_oud = fb.laad_config({"beoordeling": {"financiering": {"woonlasten_marge_past_niet": 80, "max_woonlasten_netto": 1300}}})
    ok &= check("oude sleutels (par. 10) werken nog", cfg_oud["krap_marge"] == 80 and cfg_oud["max_woonlasten_netto"] == 1300)

    profiel = {"bruto_jaar": 62000, "eigen_inleg": 10000, "duo_maandlast": 0, "leeftijd": 30}
    for prijs in (None, 0):
        b = fb.beoordeel(_minimaal(price=prijs, living_area=70), None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)
        tekst = json.dumps(b, ensure_ascii=False)
        ok &= check(f"prijs {prijs!r}: Prijs onbekend zonder woonlasten en zonder € 0",
                    b["poort"] == "PRIJS ONBEKEND" and b["financiering"]["netto"] is None and "€ 0" not in tekst
                    and b["status_kort"] == "Prijs onbekend · geen vraagprijs, dus geen leentoets", b["status_kort"])

    grens = {"bruto_jaar": 62000, "eigen_inleg": 10000, "duo_maandlast": 0, "leeftijd": 30,
             "beoordeling": {"max_woonlasten_netto": 1450}}
    cfg_g = fb.laad_config(grens)
    sk = {}
    for naam, fin in {
        "past": {"tekort": -10, "netto": 1254, "bruto": 1500, "grens": 1450, "grens_soort": "netto", "over": -196},
        "krap_eigen": {"tekort": 3000, "netto": 1400, "bruto": 1700, "grens": 1450, "grens_soort": "netto", "over": -50},
        "krap_boven": {"tekort": 0, "netto": 1474, "bruto": 1700, "grens": 1450, "grens_soort": "netto", "over": 24},
        "pn_eigen": {"tekort": 16565, "netto": 1476, "bruto": 1800, "grens": 1450, "grens_soort": "netto", "over": 26},
        "pn_boven": {"tekort": 0, "netto": 1614, "bruto": 1900, "grens": 1450, "grens_soort": "netto", "over": 164},
        "bruto": {"tekort": 0, "netto": 1300, "bruto": 1600, "grens": 1705, "grens_soort": "bruto norm", "over": -105},
        "op_grens": {"tekort": 0, "netto": 1450, "bruto": 1700, "grens": 1450, "grens_soort": "netto", "over": 0},
    }.items():
        fin["poort"] = fb.poort_financieel(fin["tekort"], fin["over"], cfg_g)
        sk[naam] = fb.status_kort(fin["poort"], fin, [], cfg_g)
    ok &= check("statusregel Past", sk["past"] == "Past · € 196 onder je grens", sk["past"])
    ok &= check("statusregel Krap, eigen geld", sk["krap_eigen"] == "Krap · € 3.000 eigen geld te weinig", sk["krap_eigen"])
    ok &= check("statusregel Krap, boven grens", sk["krap_boven"] == "Krap · € 24 boven je grens", sk["krap_boven"])
    ok &= check("statusregel Past niet, eigen geld", sk["pn_eigen"] == "Past niet · € 16.565 eigen geld te weinig", sk["pn_eigen"])
    ok &= check("statusregel Past niet, boven grens", sk["pn_boven"] == "Past niet · € 164 boven je grens", sk["pn_boven"])
    ok &= check("statusregel bruto norm", sk["bruto"] == "Past · € 105 onder de norm (bruto)", sk["bruto"])
    ok &= check("precies op de grens: geen '€ 0'", sk["op_grens"] == "Past · precies op je grens", sk["op_grens"])

    # Zonder eigen grens: bruto tegen 33% van het bruto maandinkomen.
    f = fb.financiering(_fin_woning(250000), fb.laad_config(profiel), profiel, None, VANDAAG)
    ok &= check("zonder grens: bruto norm 33%", f["grens_soort"] == "bruto norm" and f["grens"] == round(62000 / 12 * 0.33))
    return ok


def test_harde_eisen() -> bool:
    print("test: harde eisen")
    ok = True
    profiel = {"bruto_jaar": 62000, "eigen_inleg": 20000, "duo_maandlast": 0, "leeftijd": 30}
    d = _minimaal(price=200000, living_area=70, is_auction=True)
    b = fb.beoordeel(d, None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)
    ok &= check("veiling = Past niet met reden", b["poort"] == "PAST NIET" and any("Veiling" in r for r in b["poort_redenen"])
                and b["status_kort"].startswith("Past niet · veiling"), b["status_kort"])
    ok &= check("nooit onzichtbaar: er komt gewoon een beoordeling", isinstance(b["score"], float) and b["let_op"] is not None)
    cfg_uit = fb.laad_config(dict(profiel, beoordeling={"harde_eisen": {"veiling": False}}))
    ok &= check("veiling-eis uit te zetten", fb.beoordeel(d, None, [], [], profiel, cfg_uit, vandaag=VANDAAG)["poort"] != "PAST NIET")
    klus = _minimaal(price=200000, living_area=70, description="Opknapper met veel potentie.")
    ok &= check("kluswoning standaard geen harde eis",
                fb.beoordeel(klus, None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)["poort"] != "PAST NIET")
    cfg_k = fb.laad_config(dict(profiel, beoordeling={"harde_eisen": {"kluswoning": True}}))
    ok &= check("kluswoning als harde eis", fb.beoordeel(klus, None, [], [], profiel, cfg_k, vandaag=VANDAAG)["poort"] == "PAST NIET")
    hoog = _minimaal(price=200000, living_area=70, characteristics={"Gelegen op": "4e woonlaag", "Voorzieningen": "Mechanische ventilatie"})
    cfg_l = fb.laad_config(dict(profiel, beoordeling={"harde_eisen": {"max_woonlaag_zonder_lift": 3}}))
    b = fb.beoordeel(hoog, None, [], [], profiel, cfg_l, vandaag=VANDAAG)
    ok &= check("4e woonlaag zonder lift boven de harde grens", b["poort"] == "PAST NIET"
                and "4e woonlaag zonder lift." in b["poort_redenen"])
    bg = _minimaal(price=200000, living_area=70, characteristics={"Gelegen op": "Begane grond"})
    ok &= check("vangnet begane grond", fb.beoordeel(bg, None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)["poort"] == "PAST NIET")
    return ok


def test_score() -> bool:
    print("test: score (basis, begrenzing, gewichten, onbekend)")
    ok = True
    profiel = {}
    cfg = fb.laad_config(profiel)
    leeg = fb.beoordeel(_minimaal(), None, [], [], profiel, cfg, vandaag=VANDAAG)
    ok &= check("alles onbekend: score = basis 5,0", leeg["score"] == 5.0 and leeg["onderdelen"] == {}, str(leeg["onderdelen"]))
    ok &= check("onbekend telt niet mee maar staat onder Onbekend", len(leeg["onbekend"]) >= 4
                and all(i["punten"] == 0 for i in leeg["onbekend"]))
    vve_slecht = _minimaal(characteristics={"Inschrijving KvK": "Nee", "Jaarlijkse vergadering": "Nee", "Reservefonds aanwezig": "Nee",
                                            "Onderhoudsplan": "Nee"},
                           description="De VvE is niet actief. Er is een eenmalige heffing aangekondigd. Het pand wordt nog gesplitst.")
    b = fb.beoordeel(vve_slecht, None, [], [], profiel, cfg, vandaag=VANDAAG)
    ruw = sum(i["punten"] for i in b["let_op"] if i["onderdeel"] == "vve")
    ok &= check("onderdeel begrensd (VvE ruw −3,0, begrensd op −1,5)", ruw <= -2.5 and b["onderdelen"]["vve"]["punten"] == -1.5,
                f"ruw {ruw}, onderdeel {b['onderdelen'].get('vve')}")
    fx = _fixture()
    w09 = next(w for w in fx["woningen"] if w["fixture"]["id"] == "w09")
    d, det, routes, tw = invoer(w09, fx)
    cfg_fx = fb.laad_config(dict(fx["meta"]["profiel"], beoordeling={"max_woonlasten_netto": GRENS_FICTIEF}))
    b09 = fb.beoordeel(d, det, routes, tw, fx["meta"]["profiel"], cfg_fx, _verrijking("w09"), vandaag=VANDAAG)
    ok &= check("score begrensd op 0 met '(grens)' in de uitleg", b09["score"] == 0.0 and "(grens)" in b09["uitleg_regel"])
    w13 = next(w for w in fx["woningen"] if w["fixture"]["id"] == "w13")
    d, det, routes, tw = invoer(w13, fx)
    hoog = fb.laad_config(dict(fx["meta"]["profiel"], beoordeling={"max_woonlasten_netto": GRENS_FICTIEF,
                                                                    "gewichten": {k: 5 for k in ("woonlasten", "buitenruimte", "vve", "buurt", "markt")}}))
    b13 = fb.beoordeel(d, det, routes, tw, fx["meta"]["profiel"], hoog, _verrijking("w13"), vandaag=VANDAAG)
    ok &= check("score begrensd op 10", b13["score"] == 10.0 and "(grens)" in b13["uitleg_regel"], str(b13["score"]))
    nul = fb.laad_config(dict(fx["meta"]["profiel"], beoordeling={"max_woonlasten_netto": GRENS_FICTIEF, "gewichten": {"buitenruimte": 0}}))
    b0 = fb.beoordeel(d, det, routes, tw, fx["meta"]["profiel"], nul, _verrijking("w13"), vandaag=VANDAAG)
    b1 = fb.beoordeel(d, det, routes, tw, fx["meta"]["profiel"], cfg_fx, _verrijking("w13"), vandaag=VANDAAG)
    ok &= check("gewicht 0 haalt het onderdeel uit score en redenregel", "buitenruimte" not in b0["onderdelen"]
                and "balkon" not in b0["uitleg_regel"] and abs((b1["score"] - b0["score"]) - 1.0) < 0.051,
                f"{b1['score']} -> {b0['score']}: {b0['uitleg_regel']}")
    ok &= check("gewicht 0: regels blijven zichtbaar in Pluspunten", any(i["onderdeel"] == "buitenruimte" for i in b0["pluspunten"]))
    dubbel = fb.laad_config(dict(fx["meta"]["profiel"], beoordeling={"max_woonlasten_netto": GRENS_FICTIEF, "gewichten": {"oppervlak": 2}}))
    b2 = fb.beoordeel(d, det, routes, tw, fx["meta"]["profiel"], dubbel, _verrijking("w13"), vandaag=VANDAAG)
    ok &= check("gewicht 2 verdubbelt het onderdeel", abs(b2["onderdelen"]["oppervlak"]["punten"] - 2 * b1["onderdelen"]["oppervlak"]["punten"]) < 0.011)
    som = fb._rond1(5 + sum(o["punten"] for o in b1["onderdelen"].values()))
    ok &= check("score = basis + som onderdelen", b1["score"] == som, f"{b1['score']} {som}")
    return ok


ENERGIELABEL_ZINNEN = [
    ("Energielabel C.", "C"), ("Definitief energielabel A++", "A++"), ("Het energielabel is C.", "C"),
    ("De woning heeft energielabel: B", "B"),
    ("Met na-isolatie van de gevel is energielabel B haalbaar; het huidige label is E.", "E"),
    ("Voorlopig energielabel C (geldig tot 2033).", "C"), ("Energieklasse D", "D"),
    ("Energielabel A+ en vloerverwarming.", "A+"), ("Het energielabel wordt aangevraagd.", "?"),
    ("Energie-index 1,12, energielabel B.", "B"),
]
SERVICEKOSTEN_ZINNEN = [
    ("Servicekosten € 165 per maand.", 165), ("De servicekosten bedragen € 95,50 per maand.", 95),
    ("Bijdrage VvE € 140 per maand.", 140), ("De maandelijkse bijdrage aan de VvE bedraagt € 125.", 125),
    ("VvE-bijdrage: € 1.680 per jaar.", 140), ("Servicekosten € 2.100,- per jaar.", 175),
    ("Servicekosten: € 150 per kwartaal.", 50),
    ("De VvE (48 appartementen) is actief. Servicekosten € 190 per maand.", 190),
    ("De VvE (48 appartementen) is actief en ingeschreven bij de KvK.", None),
    ("Actieve VvE met 24 leden; bijdrage VvE € 160 per maand.", 160),
    ("Gezonde VvE sinds 1985. De maandelijkse bijdrage is € 135.", 135),
    ("VvE-bijdrage € 210 per maand, inclusief voorschot stookkosten.", 210),
]
ERFPACHT_ZINNEN = [
    ("Eigen grond.", ("eigen", None, None)),
    ("Let op: geen eigen grond, eeuwigdurende erfpacht met een canon van € 640 per jaar.", ("eeuwig_canon", 640, None)),
    ("Parkeerplaats op eigen grond; het appartement staat op eeuwigdurende erfpacht, canon € 410 per jaar.", ("eeuwig_canon", 410, None)),
    ("Eeuwigdurende erfpacht, niet afgekocht; de jaarlijkse canon bedraagt € 1.250,-.", ("eeuwig_canon", 1250, None)),
    ("Eeuwigdurende erfpacht, canon afgekocht. Bijdrage VvE € 140 per maand.", ("eeuwig_afgekocht", None, None)),
    ("Eeuwigdurende erfpacht, canon afgekocht. Het energielabel C is geldig tot 2034.", ("eeuwig_afgekocht", None, None)),
    ("Erfpacht afgekocht tot 31.12.2056.", ("afgekocht_tot", None, 2056)),
    ("Erfpacht afgekocht tot 31-12-2056.", ("afgekocht_tot", None, 2056)),
    ("Eeuwigdurende erfpacht; de canon is vooruitbetaald tot 2045.", ("afgekocht_tot", None, 2045)),
    ("Erfpachtcanon € 45,- per maand.", ("erfpacht_onduidelijk", 540, None)),
    ("Eeuwigdurende erfpacht, canon afgekocht tot 2056.", ("afgekocht_tot", None, 2056)),
    ("Erfpacht; de canon is afgekocht tot en met 2050.", ("afgekocht_tot", None, 2050)),
    ("Eeuwigdurende erfpacht, canon afgekocht tot 2026.", ("afgekocht_tot", None, 2026)),
    ("Voortdurende erfpacht; het huidige tijdvak loopt tot 2041, canon € 380 per jaar.", ("voortdurend", 380, None)),
    ("Het gebouw wordt voortdurend goed onderhouden. Eeuwigdurende erfpacht, canon afgekocht.", ("eeuwig_afgekocht", None, None)),
    ("De woning staat op grond van de gemeente (erfpacht), de canon wordt jaarlijks geïndexeerd.", ("erfpacht_onduidelijk", None, None)),
]
ZON_ZINNEN = [
    ("Balkon op het zuidwesten.", "Zuidwest"),
    ("De woonkamer ligt op het zuiden, het balkon aan de achterzijde op het noorden.", "Noord"),
    ("Ruim balkon aan de achterzijde, in het populaire Den Haag Zuidwest.", None),
    ("Balkon op het oosten met ochtendzon, gelegen aan de Westduinweg.", "Oost"),
    ("Zonnig balkon met de hele middag zon.", None),
    ("Balkon op zuid-west.", "Zuidwest"),
    ("De woonkamer ligt op het noorden, het balkon aan de achterzijde op het zuiden.", "Zuid"),
]
BUITENRUIMTE_ZINNEN = [   # (zin, (soort, telt als buitenruimte))
    ("Woonkamer met frans balkon.", ("frans balkon", False)),
    ("Geen balkon, wel een gemeenschappelijke binnentuin.", (None, False)),
    ("Balkon op het zuiden en gebruik van de gemeenschappelijke binnentuin.", ("balkon", True)),
    ("Slaapkamer aan de tuinzijde met uitzicht op de tuinen van de buren.", (None, False)),
    ("Op loopafstand van de terrassen op het Plein.", (None, False)),
    ("Een dakterras is niet mogelijk.", (None, False)),
    ("Gelegen in Tuindorp, nabij het park.", (None, False)),
]
ADVERTENTIE_ZINNEN = [
    ("Ouderdomsclausule van toepassing.", {"ouderdomsclausule"}),
    ("Er is geen ouderdomsclausule opgenomen.", set()),
    ("In de koopakte wordt een asbestclausule opgenomen.", {"asbest"}),
    ("Er is geen asbest aanwezig.", set()),
    ("Niet-zelfbewoningsclausule van toepassing.", {"niet_zelfbewoning"}),
    ("Het dakterras is aangelegd zonder vergunning.", {"dakterras_zonder_vergunning"}),
    ("Het dakterras is aangelegd met vergunning. De schuur is gedoogd.", set()),
    ("Het pand wordt nog gesplitst in appartementsrechten.", {"in_splitsing"}),
    ("Er is geen extra bijdrage aangekondigd.", set()),
    ("De VvE heeft een eenmalige heffing van € 2.500 vastgesteld.", {"extra_bijdrage"}),
    ("In 2019 is de fundering hersteld.", {"funderingsherstel"}),
    ("Geen achterstallig onderhoud, alles is op orde.", set()),
    ("Er is sprake van lekkage aan het dak.", {"vocht"}),
    ("Recht van overpad voor de buren.", {"erfdienstbaarheid"}),
]


def test_parsers() -> bool:
    print("test: parsers (52 zinnen uit de audit, advertentielezer met ontkenning, kenmerken eerst)")
    ok = True
    fout = []
    for zin, v in ENERGIELABEL_ZINNEN:
        if fb.energielabel({}, {}, zin)[0] != v:
            fout.append(("energielabel", zin, fb.energielabel({}, {}, zin)[0]))
    for zin, v in SERVICEKOSTEN_ZINNEN:
        if fb.vve_maand({}, zin)[0] != v:
            fout.append(("servicekosten", zin, fb.vve_maand({}, zin)[0]))
    for zin, v in ERFPACHT_ZINNEN:
        i = fb.erfpacht({}, zin)
        if (i["status"], i["canon_jaar"], i["eind"]) != v:
            fout.append(("erfpacht", zin, i))
    for zin, v in ZON_ZINNEN:
        if fb.buitenruimte({}, {}, zin)["richting"] != v:
            fout.append(("zonligging", zin, fb.buitenruimte({}, {}, zin)))
    for zin, (soort, telt) in BUITENRUIMTE_ZINNEN:
        b = fb.buitenruimte({}, {}, zin)
        if b["soort"] != soort or (b["soort"] not in (None, "frans balkon")) != telt:
            fout.append(("buitenruimte", zin, b))
    n = len(ENERGIELABEL_ZINNEN) + len(SERVICEKOSTEN_ZINNEN) + len(ERFPACHT_ZINNEN) + len(ZON_ZINNEN) + len(BUITENRUIMTE_ZINNEN)
    ok &= check(f"{n - len(fout)}/{n} zinnen uit beoordeling-audit goed", n == 52 and not fout, str(fout[:3]))
    adv_fout = [(z, v, {s[0] for s in fb.lees_advertentie(z)}) for z, v in ADVERTENTIE_ZINNEN
                if {s[0] for s in fb.lees_advertentie(z)} != v]
    ok &= check(f"advertentielezer {len(ADVERTENTIE_ZINNEN) - len(adv_fout)}/{len(ADVERTENTIE_ZINNEN)}", not adv_fout, str(adv_fout))
    ontkend = {sid for sid, _, ontk, *_ in fb.SIGNALEN if ontk}
    getest = set()
    for zin, v in ADVERTENTIE_ZINNEN:
        if not v:
            getest |= {s[0] for s in fb.SIGNALEN if s[2] and re.search(s[1], zin.lower())}
    extra = {"opknapper": "Dit is geen opknapper.", "vocht": "Er is geen lekkage.", "funderingsherstel": "Fundering is niet hersteld."}
    for sid, zin in extra.items():
        if fb.lees_advertentie(zin):
            fout.append(("ontkenning", zin))
        getest.add(sid)
    ok &= check("elk signaal met ontkenningscontrole heeft een ontkende zin", ontkend <= getest and not fout, str(ontkend - getest))

    # Kenmerken gaan voor tekst.
    ch = {"Bijdrage VvE": "€ 1.800 per jaar"}
    ok &= check("VvE uit kenmerk, per jaar omgerekend", fb.vve_maand(ch, "Servicekosten € 99 per maand.") == (150, "kenmerk 'Bijdrage VvE'"))
    ok &= check("VvE uit 'Periodieke bijdrage'", fb.vve_maand({"Periodieke bijdrage": "Ja (€ 140,00 per maand)"}, "")[0] == 140)
    e = fb.erfpacht({"Eigendomssituatie": "Gemeentelijk eigendom belast met eeuwigdurende erfpacht", "Lasten": "Niet afgekocht, € 900 per jaar"}, "")
    ok &= check("kenmerk Lasten 'niet afgekocht' is geen afkoop", e["status"] == "eeuwig_canon" and e["canon_jaar"] == 900, str(e))
    e = fb.erfpacht({"Eigendomssituatie": "Gemeentelijk eigendom belast met erfpacht", "Lasten": "Afgekocht tot 31-12-2071"}, "")
    ok &= check("kenmerk Lasten 'afgekocht tot 2071'", e["status"] == "afgekocht_tot" and e["eind"] == 2071)
    ok &= check("kenmerk Volle eigendom wint van tekst", fb.erfpacht({"Eigendomssituatie": "Volle eigendom"}, "Erfpacht, canon € 500 per jaar.")["status"] == "eigen")
    ok &= check("'canon afgekocht tot 2056' geeft geen canon", fb.erfpacht({}, "Eeuwigdurende erfpacht, canon afgekocht tot 2056.")["canon_jaar"] is None)
    ok &= check("'De VvE (48 appartementen)' geeft geen € 48", fb.vve_maand({}, "De VvE (48 appartementen) is actief.")[0] is None)
    br = fb.buitenruimte({}, {"Balkon/dakterras": "Balkon aanwezig en frans balkon aanwezig", "Gebouwgebonden buitenruimte": "6 m²"}, "")
    ok &= check("kenmerk balkon plus frans balkon = balkon", br["soort"] == "balkon" and br["m2"] == 6, str(br))
    br = fb.buitenruimte({"has_balcony": False}, {"Balkon/dakterras": "Niet aanwezig"}, "")
    ok &= check("kenmerk 'Niet aanwezig' = zeker geen buitenruimte", br["soort"] is None and br["zeker"] is True)
    br = fb.buitenruimte({}, {}, "Lichte woonkamer en twee slaapkamers.")
    ok &= check("niets gevonden = onbekend, geen minpunt", br["soort"] is None and br["zeker"] is False)
    ok &= check("label uit veld met plussen", fb.energielabel({"energy_label": "A+++"}, {}, "") == ("A+++", "funda"))
    ok &= check("label 'unknown' valt terug op kenmerk", fb.energielabel({"energy_label": "unknown"}, {"Energielabel": "D"}, "")[0] == "D")
    ok &= check("woonlaag uit kenmerk, lift uit voorzieningen", fb.woonlaag({"Gelegen op": "4e woonlaag", "Voorzieningen": "Lift"})[:2] == (4, True))
    ok &= check("voorzieningen zonder lift = geen lift", fb.woonlaag({"Gelegen op": "3e woonlaag", "Voorzieningen": "Mechanische ventilatie"})[:2] == (3, False))
    ok &= check("woonlaag uit tekst, lift onbekend", fb.woonlaag({}, "Appartement op de derde woonlaag.")[:2] == (3, None))
    ok &= check("2e verdieping = 3e woonlaag", fb.woonlaag({}, "Gelegen op de 2e verdieping, zonder lift.")[:2] == (3, False))
    ok &= check("VvE slapend uit tekst", fb.vve_status({}, "Kleine VvE met twee leden, niet actief.") == "slapend")
    ok &= check("VvE actief uit kenmerken", fb.vve_status({"Inschrijving KvK": "Ja", "Jaarlijkse vergadering": "Ja", "Onderhoudsplan": "Ja"}, "") == "actief")
    ok &= check("stookkosten in VvE bij blokverwarming", fb.stookkosten_in_vve({"Verwarming": "Blokverwarming"}, ""))

    # Prijshistorie: alleen vraagprijzen na de laatste verkoop, gesorteerd op tijd.
    hist = fb.prijshistorie([
        {"price": 260000, "status": "asking_price", "timestamp": "2026-10-01T00:00:00"},
        {"price": 330000, "status": "asking_price", "timestamp": "2019-03-01T00:00:00"},
        {"price": 300000, "status": "sold", "timestamp": "2019-06-01T00:00:00"},
        {"price": 275000, "status": "asking_price", "date": "12 aug, 2026"},
        {"price": 240000, "status": "woz", "timestamp": "2026-01-01T00:00:00"},
        {"price": 230000, "status": "woz", "timestamp": "2025-01-01T00:00:00"},
    ])
    ok &= check("piek uit een eerdere verkoopperiode telt niet", hist["hoogste"] == 275000, str(hist["hoogste"]))
    ok &= check("vraagprijzen op tijd gesorteerd", [v["prijs"] for v in hist["vraagprijzen"]] == [275000, 260000])
    ok &= check("nieuwste WOZ met jaar", hist["woz"] == {"bedrag": 240000, "jaar": 2026})
    return ok


# Fixronde: een mogelijkheid tot afkoop is geen afkoop, een einddatum met maandnaam telt, 'geen erfpacht' is eigen grond.
ERFPACHT_FIXRONDE = [   # (kenmerken, zin, (status, canon_jaar, eind))
    ({"Eigendomssituatie": "Gemeentelijk eigendom belast met erfpacht"},
     "Erfpacht met een canon van € 1.250 per jaar. De canon kan worden afgekocht.", ("erfpacht_onduidelijk", 1250, None)),
    ({}, "Erfpacht, canon € 980 per jaar. Afkopen is mogelijk, dan wordt het eeuwigdurend afgekocht.",
     ("erfpacht_onduidelijk", 980, None)),
    ({}, "Erfpacht, canon € 980 per jaar. Omzetten naar eeuwigdurend afgekocht is mogelijk.", ("erfpacht_onduidelijk", 980, None)),
    ({}, "Eeuwigdurende erfpacht, canon kan worden afgekocht; canon € 500 per jaar.", ("eeuwig_canon", 500, None)),
    ({}, "Eeuwigdurende erfpacht, canon afgekocht tot 1 januari 2035.", ("afgekocht_tot", None, 2035)),
    ({}, "Eeuwigdurende erfpacht, canon afgekocht tot 01-01-2035.", ("afgekocht_tot", None, 2035)),
    ({}, "Erfpacht, de canon is afgekocht tot 31 dec. 2061.", ("afgekocht_tot", None, 2061)),
    ({}, "Eeuwigdurende erfpacht, canon afgekocht tot het einde van het tijdvak.", ("afgekocht_looptijd_onbekend", None, None)),
    ({}, "Het appartement staat op eigen grond, geen erfpacht.", ("eigen", None, None)),
    ({}, "Het appartement is niet belast met erfpacht.", ("eigen", None, None)),
    ({}, "Let op: geen eigen grond, eeuwigdurende erfpacht met een canon van € 640 per jaar.", ("eeuwig_canon", 640, None)),
]


def test_erfpacht_fixronde() -> bool:
    print("test: erfpacht (afkoop alleen als feit, einddatum met maandnaam, 'geen erfpacht')")
    ok = True
    fout = []
    for ch, zin, v in ERFPACHT_FIXRONDE:
        i = fb.erfpacht(ch, zin)
        if (i["status"], i["canon_jaar"], i["eind"]) != v:
            fout.append((zin, i))
    ok &= check(f"{len(ERFPACHT_FIXRONDE) - len(fout)}/{len(ERFPACHT_FIXRONDE)} zinnen goed", not fout, str(fout[:3]))

    # Door het hele model: 'kan worden afgekocht' laat de canon in de woonlasten en de leentoets staan.
    fx = _fixture()
    profiel = fx["meta"]["profiel"]
    cfg = fb.laad_config(dict(profiel, beoordeling={"max_woonlasten_netto": GRENS_FICTIEF}))
    w = next(x for x in fx["woningen"] if x["fixture"]["id"] == "w02")

    def met(tekst, eig):
        d, details, routes, twijfel = invoer(w, fx)
        d = dict(d, description=tekst, characteristics=dict(d.get("characteristics") or {}, Eigendomssituatie=eig))
        return fb.beoordeel(d, d, routes, twijfel, profiel, cfg, _verrijking("w02"), vandaag=VANDAAG)

    eig = "Gemeentelijk eigendom belast met erfpacht"
    kan = met("Erfpacht met een canon van € 1.250 per jaar. De canon kan worden afgekocht.", eig)
    is_ = met("Erfpacht, de canon is afgekocht tot 2070.", eig)
    c_kan = kan["financiering"]["opbouw"].get("canon_maand") or 0
    c_is = is_["financiering"]["opbouw"].get("canon_maand") or 0
    ok &= check("'kan worden afgekocht': canon € 104 per maand in de woonlasten", round(c_kan) == 104, str(c_kan))
    ok &= check("'is afgekocht tot 2070': geen canon", c_is == 0, str(c_is))
    ok &= check("canon verlaagt de max. hypotheek", kan["financiering"]["max_hypotheek"] < is_["financiering"]["max_hypotheek"],
                f'{kan["financiering"]["max_hypotheek"]} / {is_["financiering"]["max_hypotheek"]}')
    eeuwig = met("Eeuwigdurende erfpacht, canon afgekocht tot 1 januari 2035.", eig)
    ok &= check("'afgekocht tot 1 januari 2035' is geen pluspunt 'eeuwigdurend afgekocht'",
                not any(i["onderdeel"] == "erfpacht" for i in eeuwig["pluspunten"])
                and eeuwig["onderdelen"]["erfpacht"]["punten"] < 0, str(eeuwig["onderdelen"].get("erfpacht")))
    return ok


# Eindreview: een ontkenning telt alleen als hij direct vóór 'erfpacht' staat. 'Niet in eigendom
# maar in erfpacht' is erfpacht; het 'niet' hoort bij 'eigendom'. FICTIEVE advertentiezinnen.
ERFPACHT_ONTKENNING = [   # (zin, (status, canon_jaar, eind))
    ("De grond is niet in eigendom maar in erfpacht bij de gemeente Den Haag, canon € 1.200 per jaar.",
     ("erfpacht_onduidelijk", 1200, None)),
    ("Geen VvE-bijdrage, wel erfpacht.", ("erfpacht_onduidelijk", None, None)),
    # 'zonder erfpacht' als 'exclusief', met elders een canon: erfpacht, geen eigen grond.
    ("Servicekosten € 120 per maand (zonder erfpacht). Canon € 350 per jaar.",
     ("erfpacht_onduidelijk", 350, None)),
    ("Zonder de erfpacht van € 600 per jaar zijn de maandlasten laag. Canon € 600 per jaar.",
     ("erfpacht_onduidelijk", 600, None)),
    ("Niet afgekocht: erfpacht loopt tot 2045.", ("erfpacht_onduidelijk", None, None)),
    ("Geen lift aanwezig en erfpacht canon € 412 per jaar.", ("erfpacht_onduidelijk", 412, None)),
    ("De VvE is niet groot en erfpacht canon bedraagt € 1.250 per jaar.", ("erfpacht_onduidelijk", 1250, None)),
    ("Geen eigen grond maar erfpacht, canon € 500 per jaar.", ("erfpacht_onduidelijk", 500, None)),
    ("Niet op eigen grond maar erfpacht van de gemeente, canon € 500 per jaar.", ("erfpacht_onduidelijk", 500, None)),
    # Echte ontkenningen blijven eigen grond.
    ("Het appartement staat op eigen grond, geen erfpacht.", ("eigen", None, None)),
    ("Het appartement is niet belast met erfpacht.", ("eigen", None, None)),
    ("Het appartement is niet belast met de erfpacht van de gemeente.", ("eigen", None, None)),
    ("Appartement zonder erfpacht.", ("eigen", None, None)),
    ("De grond is niet in erfpacht uitgegeven.", ("eigen", None, None)),
    ("Er is geen sprake van erfpacht.", ("eigen", None, None)),
    ("Geen erfpachtcanon, de grond is van de VvE.", ("eigen", None, None)),
]


def test_erfpacht_ontkenning() -> bool:
    print("test: erfpacht (ontkenning alleen direct ervoor: 'niet in eigendom maar in erfpacht' is erfpacht)")
    ok = True
    fout = []
    for zin, v in ERFPACHT_ONTKENNING:
        i = fb.erfpacht({}, zin)
        if (i["status"], i["canon_jaar"], i["eind"]) != v:
            fout.append((zin, i))
    ok &= check(f"{len(ERFPACHT_ONTKENNING) - len(fout)}/{len(ERFPACHT_ONTKENNING)} zinnen goed", not fout, str(fout[:3]))

    # Door het hele model, zonder kenmerk 'Eigendomssituatie': de canon blijft in de woonlasten.
    fx = _fixture()
    profiel = fx["meta"]["profiel"]
    cfg = fb.laad_config(dict(profiel, beoordeling={"max_woonlasten_netto": GRENS_FICTIEF}))
    w = next(x for x in fx["woningen"] if x["fixture"]["id"] == "w02")
    d, details, routes, twijfel = invoer(w, fx)
    ch = {k: v for k, v in (d.get("characteristics") or {}).items() if k != "Eigendomssituatie"}
    d = dict(d, characteristics=ch,
             description="De grond is niet in eigendom maar in erfpacht bij de gemeente Den Haag, canon € 1.200 per jaar.")
    b = fb.beoordeel(d, d, routes, twijfel, profiel, cfg, _verrijking("w02"), vandaag=VANDAAG)
    canon = b["financiering"]["opbouw"].get("canon_maand") or 0
    ok &= check("canon € 100 per maand in de woonlasten", round(canon) == 100, str(canon))
    ok &= check("geen pluspunt 'eigen grond'",
                not any(i["onderdeel"] == "erfpacht" for i in b["pluspunten"]), str(b["pluspunten"]))
    return ok


def test_sortering() -> bool:
    print("test: sortering (geen vraagprijs, poort, twijfel, -score)")
    ok = True
    rijen = [
        {"id": "a", "beoordeling": {"poort": "KRAP", "twijfel": [], "score": 9.0}},
        {"id": "b", "beoordeling": {"poort": "PAST", "twijfel": ["Twijfelbuurt X (jouw lijst)."], "score": 9.5}},
        {"id": "c", "beoordeling": {"poort": "PAST", "twijfel": [], "score": 6.0}},
        {"id": "d", "beoordeling": {"poort": "PRIJS ONBEKEND", "twijfel": [], "score": 9.9}},
        {"id": "e", "beoordeling": {"poort": "PAST NIET", "twijfel": [], "score": 8.0}},
        {"id": "f", "beoordeling": {"poort": "PAST", "twijfel": [], "score": 7.0}},
    ]
    volg = [r["id"] for r in fb.sorteer(rijen)]
    ok &= check("twijfel met hogere score staat onder een zonder twijfel", volg == ["f", "c", "b", "a", "e", "d"], str(volg))
    ok &= check("POORT_RANG", fb.POORT_RANG == {"PAST": 0, "KRAP": 1, "PAST NIET": 2, "PRIJS ONBEKEND": 3})
    kaal = [r["beoordeling"] for r in rijen]
    ok &= check("werkt ook op de beoordeling zelf", [fb.sorteer_sleutel(b) for b in kaal] == [fb.sorteer_sleutel(r) for r in rijen])
    # Eindreview: zonder vraagprijs altijd achteraan, ook als een harde eis (veiling) hem op PAST NIET zet.
    zonder = {"koopsom": None, "netto": None}
    met = {"koopsom": 250000, "netto": 1300}
    rijen2 = [
        {"id": "veiling", "beoordeling": {"poort": "PAST NIET", "twijfel": [], "score": 5.0, "financiering": zonder}},
        {"id": "gewoon", "beoordeling": {"poort": "PAST NIET", "twijfel": [], "score": 3.5, "financiering": met}},
        {"id": "onbekend", "beoordeling": {"poort": "PRIJS ONBEKEND", "twijfel": [], "score": 9.9, "financiering": zonder}},
        {"id": "past", "beoordeling": {"poort": "PAST", "twijfel": ["Twijfelbuurt X (jouw lijst)."], "score": 1.0,
                                       "financiering": met}},
        # Rapportrij (funda_rapport.bouw_rij): prijs_onbekend gaat voor.
        {"id": "rij", "prijs_onbekend": True, "beoordeling": {"poort": "PAST NIET", "twijfel": [], "score": 9.0}},
    ]
    volg2 = [r["id"] for r in fb.sorteer(rijen2)]
    ok &= check("zonder vraagprijs achteraan, ook op PAST NIET door een harde eis",
                volg2 == ["past", "gewoon", "rij", "veiling", "onbekend"], str(volg2))
    return ok


VERBODEN = ("herkomst", "nationaliteit", "migratie", "migrant", "allochto", "autochto", "etnisch", "bevolking",
            "p_nw_mig", "p_west", "uitkering", "opleiding", "families_with_children", "inhabitants", "inkomen_",
            "huishoud", "leeftijdsopbouw")


def _alle_teksten(x) -> list[str]:
    if isinstance(x, dict):
        return [t for k, v in x.items() for t in [str(k)] + _alle_teksten(v)]
    if isinstance(x, list):
        return [t for v in x for t in _alle_teksten(v)]
    return [x] if isinstance(x, str) else []


def test_contract() -> bool:
    print("test: datacontract (beoordeling.md par. 9)")
    ok = True
    rijen = beoordeel_fixture()
    sleutels = {"poort", "poort_redenen", "status_kort", "twijfel", "score", "onderdelen", "uitleg_regel", "let_op",
                "pluspunten", "onbekend", "info", "kansen", "zelf_nagaan", "financiering", "verrijking"}
    item_velden = {"onderdeel", "groep", "oordeel", "label", "waarde", "bron", "punten", "kort", "vraag", "uitleg"}
    fin_velden = {"max_hypotheek", "marge_lenen", "kosten_koper", "kk_soort", "tekort", "netto", "bruto", "grens", "grens_soort",
                  "opbouw", "rente", "rente_datum", "rentevast_jaren", "scenarios", "planning", "scenario_tekst"}
    opbouw_velden = {"bruto_hyp", "belastingvoordeel", "vve", "vve_bron", "vve_geschat", "energie", "stook_in_vve", "overig", "canon_maand"}
    fouten = []
    for r in rijen:
        b, wid = r["beoordeling"], r["id"]
        if set(b) != sleutels:
            fouten.append((wid, "sleutels", set(b) ^ sleutels))
        if not fin_velden <= set(b["financiering"]):
            fouten.append((wid, "financiering", fin_velden - set(b["financiering"])))
        if b["financiering"]["opbouw"] is not None and not opbouw_velden <= set(b["financiering"]["opbouw"]):
            fouten.append((wid, "opbouw"))
        if b["poort"] not in fb.POORT_RANG or not (0 <= b["score"] <= 10) or round(b["score"], 1) != b["score"]:
            fouten.append((wid, "poort/score"))
        if len(b["uitleg_regel"]) > 96:
            fouten.append((wid, "uitleg_regel te lang", len(b["uitleg_regel"])))
        if len(b["zelf_nagaan"]) > 6:
            fouten.append((wid, "zelf_nagaan"))
        for naam, o in b["onderdelen"].items():
            if o["kort"].strip().lower() in (naam, naam.replace("_", " ")):
                fouten.append((wid, "onderdeel kort", naam))
        for groep, verwacht in (("let_op", "let_op"), ("pluspunten", "plus"), ("onbekend", "onbekend"), ("info", "info"), ("kansen", "kans")):
            for i in b[groep]:
                if set(i) != item_velden:
                    fouten.append((wid, "item velden", i))
                if i["groep"] != verwacht or fb.OORDEEL_GROEP[i["oordeel"]] != i["groep"]:
                    fouten.append((wid, "groep", i["label"]))
                if len(i["label"]) > 24 or len(i["waarde"]) > 32:
                    fouten.append((wid, "lengte", i["label"], i["waarde"]))
                if not i["kort"] or i["kort"].strip().lower() in (i["onderdeel"], i["onderdeel"].replace("_", " ")):
                    fouten.append((wid, "kort = onderdeel", i))
                if groep in ("onbekend", "kansen", "info") and i["onderdeel"] in ("info", "kans", "financiering") and i["punten"] != 0:
                    fouten.append((wid, "punten bij info/kans", i["label"]))
        teksten = _alle_teksten(b)
        if any("\u2014" in t or "\u2013" in t for t in teksten):
            fouten.append((wid, "em dash of gedachtestreepje"))
        if any(v in t.lower() for t in teksten for v in VERBODEN):
            fouten.append((wid, "bevolkingskenmerk", [t for t in teksten if any(v in t.lower() for v in VERBODEN)][:2]))
        if b["poort"] == "PRIJS ONBEKEND" and "€ 0" in json.dumps(b, ensure_ascii=False):
            fouten.append((wid, "€ 0"))
    ok &= check(f"{len(rijen)} beoordelingen volgen het contract", not fouten, str(fouten[:4]))
    ok &= check("prijs onbekend staat achteraan", rijen[-1]["beoordeling"]["poort"] == "PRIJS ONBEKEND")
    tw = [r for r in rijen if r["beoordeling"]["twijfel"]]
    ok &= check("twijfel zichtbaar als zin, zonder 'Onderaan gezet.'",
                tw and all(z.endswith(".") and "Onderaan gezet" not in z for r in tw for z in r["beoordeling"]["twijfel"]),
                str([r["beoordeling"]["twijfel"] for r in tw]))
    ok &= check("Leefbaarometer zwak buiten je lijst wordt twijfel",
                any(z.startswith("Leefbaarometer zwak (2024)") for r in rijen if r["id"] == "w11" for z in r["beoordeling"]["twijfel"]))
    return ok


def test_geen_bevolkingskenmerken() -> bool:
    print("test: geen bevolkingskenmerken in de uitvoer, ook niet als de bron ze levert")
    ok = True
    d = _minimaal(price=240000, living_area=70)
    d["_enrichment"] = {"market": {"avg_asking_price_per_m2": 4000,
                                   "insights": {"inhabitants": 9870, "families_with_children_pct": 21.4}}}
    verrijking = {"buurt": {"status": "ok", "data": {"kscore": 7, "onv": 0.1, "herkomst_pct": 33.3, "p_nw_mig_a": 12,
                                                     "nationaliteit": "x", "inkomen_gem": 31000, "opleiding_laag": 20}},
                  "bag": {"status": "ok", "data": {"bouwjaar": 1930, "aantal_vbo_pand": 6, "bevolking": 1}}}
    profiel = {"bruto_jaar": 62000, "eigen_inleg": 10000, "leeftijd": 30}
    b = fb.beoordeel(d, None, [], [], profiel, fb.laad_config(profiel), verrijking, vandaag=VANDAAG)
    tekst = json.dumps(b, ensure_ascii=False).lower()
    gevonden = [v for v in VERBODEN + ("33,3", "33.3", "31.000", "9870", "21,4") if v in tekst]
    ok &= check("geen herkomst, inkomen of samenstelling van de buurt", not gevonden, str(gevonden))
    ok &= check("verrijking in de uitvoer alleen als status", all(isinstance(v, str) for v in b["verrijking"].values()), str(b["verrijking"]))
    return ok


def test_verrijking_vormen() -> bool:
    print("test: verrijking als status-dict of als kale data, en fail-soft")
    ok = True
    fx = _fixture()
    w = next(x for x in fx["woningen"] if x["fixture"]["id"] == "w03")
    d, det, routes, tw = invoer(w, fx)
    profiel = fx["meta"]["profiel"]
    cfg = fb.laad_config(dict(profiel, beoordeling={"max_woonlasten_netto": GRENS_FICTIEF}))
    a = fb.beoordeel(d, det, routes, tw, profiel, cfg, _verrijking("w03"), vandaag=VANDAAG)
    b = fb.beoordeel(d, det, routes, tw, profiel, cfg, VERRIJKING_FICTIEF["w03"], vandaag=VANDAAG)
    ok &= check("kale data (vorm van verrijking_stub) = status-dict", a == b)
    zonder = fb.beoordeel(d, det, routes, tw, profiel, cfg, None, vandaag=VANDAAG)
    ok &= check("zonder verrijking: alles 'uit', geen onbekend-regels voor bronnen",
                set(zonder["verrijking"].values()) == {"uit"} and not any(i["onderdeel"] in ("geluid", "fundering") for i in zonder["onbekend"]))
    budget = {k: {"status": "budget", "data": None} for k in ("bag", "fundering", "geluid", "buurt")}
    bb = fb.beoordeel(d, det, routes, tw, profiel, cfg, budget, vandaag=VANDAAG)
    ok &= check("budget op: onbekend, telt niet mee, woning blijft", bb["verrijking"]["geluid"] == "budget"
                and any(i["onderdeel"] == "geluid" for i in bb["onbekend"]) and bb["poort"] == zonder["poort"])
    raar = {"bag": "iets onverwachts", "geluid": {"status": "ok", "data": None}, "buurt": {"status": "ok", "data": {"kscore": 42}}}
    br = fb.beoordeel(d, det, routes, tw, profiel, cfg, raar, vandaag=VANDAAG)
    ok &= check("onverwachte vormen laten beoordeel() niet vallen", br["verrijking"]["bag"] == "onbekend" and isinstance(br["score"], float))
    trein = {"geluid": {"status": "ok", "data": {"lden_weg": -9999, "lnight_weg": -9999, "lden_trein": None, "lnight_trein": None}}}
    bt = fb.beoordeel(d, det, routes, tw, profiel, cfg, trein, vandaag=VANDAAG)
    ok &= check("GRAY_INDEX -9999 = onder de kaartgrens, rustig",
                any(i["label"] == "Geluid aan de gevel" and "rustig" in i["waarde"] for i in bt["pluspunten"]))
    return ok


def test_rommelige_invoer() -> bool:
    print("test: rommelige invoer laat beoordeel() niet vallen")
    ok = True
    profiel = {"bruto_jaar": 62000, "eigen_inleg": 10000, "leeftijd": "onbekend", "werk_postcodes": [["0000XX", "werk"]]}
    gevallen = {
        "alles None": ({"price": None, "living_area": None, "characteristics": None, "description": None}, None, None, None, None),
        "tekst als getal": ({"price": 250000, "living_area": "70 m²", "construction_year": "1932", "energy_label": "c+",
                             "characteristics": {"Gelegen op": "Begane grond", "Inhoud": "veel"}}, None, [], ["", None], None),
        "vreemde verrijking": ({"price": 250000, "living_area": 70},
                               {"characteristics": {"Balkon/dakterras": "Dakterras aanwezig"}, "description": "Dakterras op het zuiden."},
                               [{"label": "werk", "km": None}, {"label": "werk", "km": 3.0}], None,
                               {"bag": {"status": "ok", "data": {"bouwjaar": "1930", "aantal_vbo_pand": "4"}},
                                "fundering": {"status": "ok", "data": {"verschilzetting": "onbekende klasse"}},
                                "geluid": {"status": "ok", "data": {"lden_weg": "luid"}}, "buurt": ["geen dict"]}),
        "track en enrichment raar": ({"price": 250000, "living_area": 70, "_track": {"gedaald": True, "drop_bedrag": None, "dagen": "veel"},
                                      "_enrichment": {"price_history": {"_error": "x"}, "market": None, "broker": "x"}},
                                     None, None, None, None),
    }
    for naam, (d, det, routes, tw, verr) in gevallen.items():
        try:
            b = fb.beoordeel(d, det, routes, tw, profiel, fb.laad_config(profiel), verr, vandaag=VANDAAG)
            ok &= check(naam, b["poort"] in fb.POORT_RANG and 0 <= b["score"] <= 10, f"{b['poort']} {b['score']}")
        except Exception as exc:  # noqa: BLE001
            ok &= check(naam, False, f"{type(exc).__name__}: {exc}")
    ok &= check("laad_config zonder invoer", fb.laad_config(None)["financien"] is None and fb.laad_config("x")["score_basis"] == 5)
    return ok


def test_fixture_verwachting() -> bool:
    print("test: fixture tegen testdata/beoordeling_verwacht.json")
    ok = True
    if not VERWACHT.exists():
        return check("golden file aanwezig", False, "draai python test_funda_beoordeling.py --schrijf-verwacht")
    verwacht = json.loads(VERWACHT.read_text(encoding="utf-8"))
    kreeg = json.loads(json.dumps(beoordeel_fixture(), ensure_ascii=False))
    ok &= check("zelfde volgorde", [r["id"] for r in kreeg] == [r["id"] for r in verwacht["rijen"]],
                f"{[r['id'] for r in kreeg]}")
    v = {r["id"]: r["beoordeling"] for r in verwacht["rijen"]}
    verschil = []
    for r in kreeg:
        oud = v.get(r["id"])
        if oud != r["beoordeling"]:
            sleutels = [k for k in r["beoordeling"] if (oud or {}).get(k) != r["beoordeling"][k]]
            verschil.append((r["id"], sleutels))
    ok &= check("elke beoordeling gelijk aan de golden file", not verschil, str(verschil[:3]))
    poorten = {r["id"]: r["beoordeling"]["poort"] for r in kreeg}
    ok &= check("poort per woning (model v3)", poorten == {
        "w13": "PAST", "w01": "PAST", "w07": "PAST", "w12": "KRAP", "w06": "KRAP", "w10": "KRAP", "w11": "KRAP",
        "w03": "KRAP", "w02": "PAST NIET", "w05": "PAST NIET", "w08": "PAST NIET", "w09": "PAST NIET", "w04": "PRIJS ONBEKEND"},
        str(poorten))
    b = {r["id"]: r["beoordeling"] for r in kreeg}
    ok &= check("'niet afgekocht' geeft geen pluspunt (w05)", not any(i["onderdeel"] == "erfpacht" for i in b["w05"]["pluspunten"])
                and b["w05"]["onderdelen"]["erfpacht"]["punten"] < 0)
    ok &= check("'De VvE (48 appartementen)' geeft geen € 48 (w06)", "€ 48" not in json.dumps(b["w06"], ensure_ascii=False)
                and b["w06"]["financiering"]["opbouw"]["vve"] == 190)
    ok &= check("w13: Past · € 196 onder je grens", b["w13"]["status_kort"] == "Past · € 196 onder je grens", b["w13"]["status_kort"])
    return ok


def test_log_kenmerk_labels() -> bool:
    print("test: log_kenmerk_labels (alleen namen en aantallen)")
    ok = True
    fx = _fixture()
    tel = fb.log_kenmerk_labels([w["listing"] for w in fx["woningen"]] + [None, {"characteristics": None}])
    ok &= check("telt labels over de woningen", tel.get("Bouwjaar") == 13 and tel.get("Bijdrage VvE", 0) >= 1, str(list(tel.items())[:4]))
    waarden = {str(v) for w in fx["woningen"] for v in (w["listing"].get("characteristics") or {}).values()}
    ok &= check("geen waarden in de uitvoer", all(isinstance(k, str) and isinstance(n, int) for k, n in tel.items())
                and not (set(tel) & waarden - {"Ja", "Nee"}))
    ok &= check("leeg is leeg", fb.log_kenmerk_labels([]) == {} and fb.log_kenmerk_labels(None) == {})
    return ok


def test_kansen_en_info() -> bool:
    print("test: kansen en informatieve punten tellen niet mee")
    ok = True
    profiel = {"bruto_jaar": 62000, "eigen_inleg": 10000, "leeftijd": 30}
    d = _minimaal(price=240000, living_area=70)
    basis = fb.beoordeel(d, None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)
    d2 = dict(d, _track={"gedaald": True, "drop_bedrag": 15000, "eerdere_prijs": 255000, "dagen": 120}, open_house=True)
    kans = fb.beoordeel(d2, None, [], [], profiel, fb.laad_config(profiel), vandaag=VANDAAG)
    ok &= check("prijsdaling en lang te koop als kans, 0 punten", {i["label"] for i in kans["kansen"]} == {"Prijs verlaagd", "Lang te koop"}
                and kans["score"] == basis["score"])
    cfg = fb.laad_config(dict(profiel, beoordeling={"lang_op_funda_dagen": 150}))
    ok &= check("lang_op_funda_dagen uit de config", {i["label"] for i in fb.beoordeel(d2, None, [], [], profiel, cfg, vandaag=VANDAAG)["kansen"]} == {"Prijs verlaagd"})
    ok &= check("lang_op_funda_dagen op het hoogste niveau (bestaande sleutel)", fb.laad_config({"lang_op_funda_dagen": 30})["lang_op_funda_dagen"] == 30)
    ok &= check("open huis is info", any(i["label"] == "Open huis" for i in kans["info"]))
    return ok


def test_import_zonder_personal() -> bool:
    print("test: importeert zonder funda_personal.json en zonder funda_rapport")
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        code = ("import sys; sys.path.insert(0, %r); import funda_beoordeling as fb; "
                "print(fb.laad_config(None)['score_basis'], 'funda_rapport' in sys.modules, 'funda_zoek' in sys.modules)") % str(HIER)
        uit = subprocess.run([sys.executable, "-c", code], cwd=tmp, capture_output=True, text=True, timeout=60,
                             env={k: v for k, v in os.environ.items() if not k.startswith("FUNDA_")})
    ok &= check("import in een lege map", uit.returncode == 0 and uit.stdout.strip() == "5 False False", uit.stdout + uit.stderr)
    bron = (HIER / "funda_beoordeling.py").read_text(encoding="utf-8")
    ok &= check("geen netwerk-imports", not any(m in bron for m in ("import requests", "urllib", "http.client", "socket", "curl_cffi")))
    ok &= check("geen em dash of gedachtestreepje in de module", "\u2014" not in bron and "\u2013" not in bron)
    return ok


def schrijf_verwacht() -> None:
    rijen = beoordeel_fixture()
    doc = {
        "_doc": ("Uitvoer van funda_beoordeling.beoordeel() op testdata/woningen.json, in rapportvolgorde (sorteer()). "
                 "FICTIEF: woningen, profiel en verrijking zijn verzonnen. Invoer: meta.profiel uit de fixture, "
                 "beoordeling.max_woonlasten_netto = 1450 (fictief), rente = standaard (geen parameter), vandaag = "
                 "2026-11-06, verrijking = VERRIJKING_FICTIEF uit test_funda_beoordeling.py. Bijwerken: "
                 "python test_funda_beoordeling.py --schrijf-verwacht"),
        "invoer": {"vandaag": VANDAAG, "beoordeling": {"max_woonlasten_netto": GRENS_FICTIEF}, "rente": "standaard"},
        "rijen": rijen,
    }
    VERWACHT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Geschreven: {VERWACHT.relative_to(HIER)} ({len(rijen)} woningen)")


def main() -> int:
    if "--schrijf-verwacht" in sys.argv:
        schrijf_verwacht()
        return 0
    resultaten = [test_leentoets(), test_kosten_koper_en_koopsom(), test_scenarios(), test_rente(), test_poort(),
                  test_harde_eisen(), test_score(), test_parsers(), test_erfpacht_fixronde(), test_erfpacht_ontkenning(), test_sortering(), test_contract(),
                  test_geen_bevolkingskenmerken(), test_verrijking_vormen(), test_rommelige_invoer(), test_fixture_verwachting(),
                  test_log_kenmerk_labels(), test_kansen_en_info(), test_import_zonder_personal()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
