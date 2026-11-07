"""Offline tests voor de UI: funda_ui.py, ui/app.css, ui/app.js en ui/slot.html.

Draait op testdata/woningen.json (13 fictieve woningen) en testdata/beoordeling_v3.json (het
beoordelingscontract met fictieve scenario's). Geen netwerk, geen echte persoonsgegevens.

Draaien: python test_funda_ui.py
"""
from __future__ import annotations

import copy
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import funda_ui

HIER = Path(__file__).resolve().parent
TESTDATA = HIER / "testdata"
UI = HIER / "ui"
CSS = (UI / "app.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")
SLOT = (UI / "slot.html").read_text(encoding="utf-8")

# Contrastparen (WCAG 2.x): (omschrijving, voorgrond, achtergrond, minimum). Tekst 4,5; niet-tekst 3,0.
# --border-color-default en --border-color-subtle zijn decoratief (kaartrand, scheidingslijn, rand om
# een knop met tekst) en staan er bewust niet in: de component draagt zijn eigen tekst.
TEKST, NIET_TEKST = 4.5, 3.0
CONTRASTPAREN = [
    ("tekst/pagina", "foreground-color-neutral", "background-color-page", TEKST),
    ("tekst/kaart", "foreground-color-neutral", "background-color-default", TEKST),
    ("tekst/inzet", "foreground-color-neutral", "background-color-inset", TEKST),
    ("subtiel/pagina", "foreground-color-subtle", "background-color-page", TEKST),
    ("subtiel/kaart", "foreground-color-subtle", "background-color-default", TEKST),
    ("subtiel/inzet", "foreground-color-subtle", "background-color-inset", TEKST),
    ("kop/pagina", "foreground-color-strong", "background-color-page", TEKST),
    ("kop/kaart", "foreground-color-strong", "background-color-default", TEKST),
    ("link/pagina", "foreground-color-highlight-strong", "background-color-page", TEKST),
    ("link/kaart", "foreground-color-highlight-strong", "background-color-default", TEKST),
    ("knoptekst/pagina", "foreground-color-interactive-strong", "background-color-page", TEKST),
    ("knoptekst/kaart", "foreground-color-interactive-strong", "background-color-default", TEKST),
    ("knoptekst/hover", "foreground-color-interactive-strong", "background-color-interactive-weak", TEKST),
    ("topbalk", "foreground-color-on-strong", "background-color-strong", TEKST),
    ("topbalk subtiel", "foreground-color-on-strong-subtle", "background-color-strong", TEKST),
    ("topbalk hover", "foreground-color-on-strong", "background-color-on-strong-hover", TEKST),
    ("knop aan", "foreground-color-interactive-on-strong", "background-color-interactive-strong", TEKST),
    ("knop aan hover", "foreground-color-interactive-on-strong", "background-color-interactive-strong-hover", TEKST),
    ("status Past", "status-tekst", "background-color-feedback-positive-weak", TEKST),
    ("status Krap", "status-tekst", "background-color-feedback-notice-weak", TEKST),
    ("status Past niet", "status-tekst", "background-color-feedback-negative-weak", TEKST),
    ("status onbekend", "status-tekst", "background-color-feedback-informative-weak", TEKST),
    ("plus/kaart", "foreground-color-feedback-positive", "background-color-default", TEKST),
    ("min/kaart", "foreground-color-feedback-negative", "background-color-default", TEKST),
    ("plusteken", "background-color-default", "foreground-color-feedback-positive", TEKST),
    ("minteken", "background-color-default", "foreground-color-feedback-negative", TEKST),
    ("label daling", "label-tekst", "label-daling", TEKST),
    ("label lang", "label-tekst", "label-lang", TEKST),
    ("pin Past", "pin-tekst", "pin-past", TEKST),
    ("pin Krap", "pin-tekst-krap", "pin-krap", TEKST),
    ("pin Past niet", "pin-tekst", "pin-niet", TEKST),
    ("pin Prijs onbekend", "pin-tekst", "pin-onbekend", TEKST),
    ("veldrand/kaart", "border-color-interactive-neutral", "background-color-default", NIET_TEKST),
    ("veldrand/inzet", "border-color-interactive-neutral", "background-color-inset", NIET_TEKST),
    ("veldrand/pagina", "border-color-interactive-neutral", "background-color-page", NIET_TEKST),
    ("schakelaar uit", "foreground-color-subtle", "background-color-subtle", NIET_TEKST),
    ("focus/pagina", "border-color-interactive-focus", "background-color-page", NIET_TEKST),
    ("focus/kaart", "border-color-interactive-focus", "background-color-default", NIET_TEKST),
    ("keuze aan/kaart", "background-color-interactive-strong", "background-color-default", NIET_TEKST),
    ("chip aan/pagina", "background-color-interactive-strong", "background-color-page", NIET_TEKST),
    ("icoon Past", "foreground-color-feedback-positive", "background-color-feedback-positive-weak", NIET_TEKST),
    ("icoon Krap", "foreground-color-feedback-notice", "background-color-feedback-notice-weak", NIET_TEKST),
    ("icoon Past niet", "foreground-color-feedback-negative", "background-color-feedback-negative-weak", NIET_TEKST),
    ("icoon onbekend", "foreground-color-feedback-informative", "background-color-feedback-informative-weak", NIET_TEKST),
    ("rand Past", "foreground-color-feedback-positive", "background-color-default", NIET_TEKST),
    ("rand Krap", "foreground-color-feedback-notice", "background-color-default", NIET_TEKST),
    ("rand Past niet", "foreground-color-feedback-negative", "background-color-default", NIET_TEKST),
    ("rand onbekend", "foreground-color-feedback-informative", "background-color-default", NIET_TEKST),
    ("rand melding", "foreground-color-feedback-notice", "background-color-page", NIET_TEKST),
    ("balk plus", "foreground-color-feedback-positive", "background-color-inset", NIET_TEKST),
    ("balk min", "foreground-color-feedback-negative", "background-color-inset", NIET_TEKST),
]
VERBODEN_WOORDEN = ["ANWB", "Nomad", "nomad", "Clan Pro", "Bernina", "#ffcd00", "#003d86"]
BEVOLKING = ["herkomst", "nationaliteit", "migratie", "etniciteit", "allochto", "bevolkingssamenstelling"]


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return bool(voorwaarde)


# ── testdata ─────────────────────────────────────────────────────────────────
def _haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def testrijen() -> tuple[list[dict], dict]:
    """Rijen zoals funda_rapport.bouw_rij ze maakt, uit de fictieve testdata. Routes: hemelsbreed x osrm_factor."""
    td = json.loads((TESTDATA / "woningen.json").read_text(encoding="utf-8"))
    bv = json.loads((TESTDATA / "beoordeling_v3.json").read_text(encoding="utf-8"))
    per_id = {r["id"]: r["beoordeling"] for r in bv["rijen"]}
    werk, factor = td["meta"]["werk"], td["meta"]["osrm_factor"]
    rijen = []
    for w in td["woningen"]:
        d = copy.deepcopy(w["listing"])
        hist = w.get("price_history") if isinstance(w.get("price_history"), list) else []   # w04: foutobject
        wozen = [p for p in hist if p.get("status") == "woz"]
        d["_enrichment"] = {"price_history": {"latest_woz": wozen[0] if wozen else None}}
        lat, lon = d.get("latitude"), d.get("longitude")
        routes = ([{"postcode": x["postcode"], "label": x["label"], "soort": "weg",
                    "km": round(_haversine(lat, lon, x["lat"], x["lon"]) * factor, 2)} for x in werk] if lat else [])
        rijen.append({"d": d, "details": d, "beoordeling": copy.deepcopy(per_id[w["fixture"]["id"]]), "routes": routes,
                      "lat": lat, "lon": lon, "foto_url": None, "is_nieuw": bool(w["fixture"].get("nieuw")),
                      "track": w.get("track") or {}, "_fixture": w["fixture"]["id"]})
    meta = dict(bv["meta"], actions_url="https://github.com/voorbeeld/rapport/actions/workflows/rapport.yml")
    return rijen, meta


class _Html(HTMLParser):
    """Verzamelt id's, data-attributen en de artikelvolgorde uit de gerenderde body."""

    def __init__(self):
        super().__init__()
        self.ids, self.attrs, self.artikelen, self.fout = set(), [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids and not a["id"].startswith("i-"):
                self.fout.append(a["id"])
            self.ids.add(a["id"])
        self.attrs.append((tag, a))
        if tag == "article":
            self.artikelen.append(a.get("data-id"))


def _body(meta_extra: dict | None = None, rijen: list[dict] | None = None) -> str:
    r, meta = testrijen()
    meta.update(meta_extra or {})
    return funda_ui.render_report_body(rijen if rijen is not None else r, meta)


def _kaart(body: str, sleutel: str) -> str:
    begin = body.index(f'data-id="{sleutel}"')
    return body[begin:body.index("</article>", begin)]


def _woning_data(body: str) -> dict:
    m = re.search(r'<script type="application/json" id="woning-data">(.*?)</script>', body, re.S)
    return json.loads(m.group(1))


# ── kleuren ──────────────────────────────────────────────────────────────────
def _tokens(blok: str) -> dict:
    return {k: v.lower() for k, v in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{3,8})\b", blok)}


def _blok(css: str, kop: str) -> str:
    i = css.index(kop)
    j, diepte = css.index("{", i), 0
    for k in range(j, len(css)):
        diepte += {"{": 1, "}": -1}.get(css[k], 0)
        if diepte == 0:
            return css[j:k + 1]
    raise ValueError(kop)


def tokenblokken(css: str = CSS) -> tuple[dict, dict, dict]:
    zonder = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    licht = _tokens(_blok(zonder, ":root{"))
    media = _tokens(_blok(zonder, "@media (prefers-color-scheme:dark){"))
    expliciet = _tokens(_blok(zonder, ':root[data-theme="dark"]{'))
    return licht, media, expliciet


def _lum(hexkleur: str) -> float:
    x = hexkleur.lstrip("#")
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    kanalen = [int(x[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in kanalen]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def contrasten() -> list[tuple[str, float, float, float]]:
    licht, media, _ = tokenblokken()
    donker = {**licht, **media}
    return [(naam, contrast(licht[fg], licht[bg]), contrast(donker[fg], donker[bg]), minimum)
            for naam, fg, bg, minimum in CONTRASTPAREN]


def contrast_regel(naam: str, l: float, d: float) -> str:
    return f"{naam} {l:.1f}|{d:.1f}".replace(".", ",")


# ── tests ────────────────────────────────────────────────────────────────────
def test_contract_testdata() -> bool:
    print("contract in testdata/beoordeling_v3.json")
    bv = json.loads((TESTDATA / "beoordeling_v3.json").read_text(encoding="utf-8"))
    td = json.loads((TESTDATA / "woningen.json").read_text(encoding="utf-8"))
    gid = {w["fixture"]["id"]: w["listing"]["global_id"] for w in td["woningen"]}
    sleutels = {"poort", "poort_redenen", "status_kort", "twijfel", "score", "onderdelen", "uitleg_regel", "let_op",
                "pluspunten", "onbekend", "info", "kansen", "zelf_nagaan", "financiering", "verrijking"}
    item_velden = {"onderdeel", "groep", "oordeel", "label", "waarde", "bron", "punten", "kort", "vraag", "uitleg"}
    fin_velden = {"max_hypotheek", "marge_lenen", "kosten_koper", "kk_soort", "tekort", "netto", "bruto", "grens",
                  "grens_soort", "opbouw", "rente", "rente_datum", "rentevast_jaren", "scenarios", "planning", "scenario_tekst"}
    scen_velden = {"id", "label", "max_hypotheek", "max_koopsom", "past"}
    fouten = []
    for r in bv["rijen"]:
        b = r["beoordeling"]
        if set(b) != sleutels:
            fouten.append(f"{r['id']} sleutels {set(b) ^ sleutels}")
        if r["global_id"] != gid.get(r["id"]):
            fouten.append(f"{r['id']} global_id")
        for groep in ("let_op", "pluspunten", "onbekend", "info", "kansen"):
            for x in b[groep]:
                if set(x) != item_velden:
                    fouten.append(f"{r['id']} item {set(x) ^ item_velden}")
                if x["kort"].lower() == x["onderdeel"].lower():
                    fouten.append(f"{r['id']} kort = onderdeel {x['kort']}")
        for naam, v in b["onderdelen"].items():
            if v["kort"] == naam:
                fouten.append(f"{r['id']} onderdeel kort {naam}")
        f = b["financiering"]
        if set(f) != fin_velden:
            fouten.append(f"{r['id']} financiering {set(f) ^ fin_velden}")
        for s in f["scenarios"]:
            if set(s) != scen_velden or s["id"] not in ("nu", "2027_01", "2027_01_met_cao") or not isinstance(s["past"], bool):
                fouten.append(f"{r['id']} scenario {s}")
        planning = next((s for s in f["scenarios"] if s["id"] == f["planning"]), None)
        if planning and planning["past"] != (b["poort"] != "PAST NIET"):
            fouten.append(f"{r['id']} poort volgt planning niet")
        if b["poort"] == "PRIJS ONBEKEND" and any(f[k] is not None for k in ("netto", "max_hypotheek", "tekort")):
            fouten.append(f"{r['id']} prijs onbekend met bedragen")
    tekst = json.dumps(bv, ensure_ascii=False)
    return all([
        check("13 rijen", len(bv["rijen"]) == 13, str(len(bv["rijen"]))),
        check("velden volgens het contract", not fouten, "; ".join(fouten[:5])),
        check("scenario_tekst in vier soorten", {r["beoordeling"]["financiering"]["scenario_tekst"] for r in bv["rijen"]}
              == {"Past nu", "Past vanaf jan 2027", "Alleen met cao-verhoging", "Past in geen scenario", None}),
        check("geen em dash of gedachtestreepje", "—" not in tekst and "–" not in tekst),
        check("geen bevolkingskenmerken", not any(w in tekst.lower() for w in BEVOLKING)),
        check("rente in meta", set(bv["meta"]["rente"]) == {"pct", "bron", "datum", "oud", "melding"}),
    ])


def test_ids_en_attributen() -> bool:
    print("id's en data-attributen die app.js gebruikt")
    body = _body()
    p = _Html()
    p.feed(body)
    nodig = ["app", "woning-data", "nieuw", "plat", "park", "leeg", "filters", "filterform", "f-maxlasten", "f-minm2",
             "f-twijfel", "f-verborgen", "vergelijk", "vergelijk-tabel", "toast", "toast-knop", "top-tel", "bewaard-balk",
             "verborgen-regel", "toon-verborgen", "sheet-toon", "kaart", "kaart-melding", "budget", "apparaat",
             "nieuw-titel", "nieuw-leeg", "eerder", "leeg-kop", "leeg-tekst", "bewaard-tekst", "verborgen-tekst",
             "toast-tekst", "lijst"]
    uit_js = set(re.findall(r"\$\('#([\w-]+)", JS)) | set(re.findall(r"getElementById\('([\w-]+)'\)", JS))
    uit_js -= {"card-"}
    acties_js = set(re.findall(r'data-actie="(\w+)"', JS))
    acties_body = {a.get("data-actie") for _, a in p.attrs if a.get("data-actie")}
    snel = {a.get("data-snel") for _, a in p.attrs if a.get("data-snel")}
    poorten = {a.get("data-poort") for t, a in p.attrs if t == "details" and a.get("data-poort")}
    return all([
        check("vaste id's aanwezig", all(i in p.ids for i in nodig), str([i for i in nodig if i not in p.ids])),
        check("elke #id uit app.js aanwezig", uit_js <= p.ids, str(sorted(uit_js - p.ids))),
        check("geen dubbele id's", not p.fout, str(p.fout[:5])),
        check("elke data-actie uit app.js aanwezig", acties_js <= acties_body, str(acties_js - acties_body)),
        check("snelfilters", snel == {"alles", "nieuw", "past", "krap", "gedaald", "bewaard"}, str(snel)),
        check(".groep[data-poort] voor alle vier", poorten == set(funda_ui.POORTEN), str(poorten)),
        check("13 kaarten", len(p.artikelen) == 13, str(len(p.artikelen))),
        check("data-id = global_id", set(p.artikelen) == {str(r["d"]["global_id"]) for r in testrijen()[0]}),
        check("data-view lijst en kaart", {"lijst", "kaart"} <= {a.get("data-view") for _, a in p.attrs}),
        check("label for bij elk veld", all(f'for="{i}"' in body for i in ("f-maxlasten", "f-minm2", "f-twijfel", "f-verborgen"))),
    ])


def test_statusregels() -> bool:
    print("statusregel per poort (spec.md 4.2)")
    sr = funda_ui.status_tekst
    return all([
        check("Past", sr("PAST", {"netto": 1254, "grens": 1450, "tekort": -20}) == "Past · € 196 onder je grens"),
        check("Krap boven je grens", sr("KRAP", {"netto": 1474, "grens": 1450, "tekort": 8}) == "Krap · € 24 boven je grens"),
        check("Krap eigen geld", sr("KRAP", {"netto": 1400, "grens": 1450, "tekort": 3200}) == "Krap · € 3.200 eigen geld te weinig"),
        check("Krap eigen geld binnen de marge = grens", sr("KRAP", {"netto": 1474, "grens": 1450, "tekort": 1500})
              == "Krap · € 24 boven je grens"),
        check("Past niet eigen geld", sr("PAST NIET", {"netto": 1476, "grens": 1450, "tekort": 16565})
              == "Past niet · € 16.565 eigen geld te weinig"),
        check("Past niet boven je grens", sr("PAST NIET", {"netto": 1614, "grens": 1450, "tekort": -60})
              == "Past niet · € 164 boven je grens"),
        check("Prijs onbekend", sr("PRIJS ONBEKEND", {}) == "Prijs onbekend · geen vraagprijs, dus geen leentoets"),
        check("bruto norm", sr("KRAP", {"netto": 1300, "bruto": 1750, "grens": 1705, "tekort": 0, "grens_soort": "bruto norm"})
              == "Krap · € 45 boven de norm (bruto)"),
        check("drempels uit meta", funda_ui.status_reden("KRAP", {"netto": 1400, "grens": 1450, "tekort": 1200},
                                                         {"kk_onzekerheid": 1000}) == "€ 1.200 eigen geld te weinig"),
    ])


def test_status_en_scenario_in_kaart() -> bool:
    print("statusregel en scenario per woning")
    rijen, _ = testrijen()
    body = _body()
    fouten = []
    for r in rijen:
        b = r["beoordeling"]
        kaart = _kaart(body, str(r["d"]["global_id"]))
        naam, _, reden = b["status_kort"].partition(" · ")
        if f"<strong>{naam}</strong> · {reden}" not in kaart:
            fouten.append(r["_fixture"] + " status")
        st = b["financiering"]["scenario_tekst"]
        if st and f'<span class="w-scenario">{st}</span>' not in kaart:
            fouten.append(r["_fixture"] + " scenario")
        if f'st-{funda_ui.POORT_CLS[b["poort"]]}' not in kaart or f'#i-{funda_ui.POORT_IC[b["poort"]]}' not in kaart:
            fouten.append(r["_fixture"] + " poortklasse of icoon")
    w01 = _kaart(body, "7990101")
    w02 = _kaart(body, "7990102")
    w10 = _kaart(body, "7990110")
    return all([
        check("statusregel, scenario, klasse en icoon per kaart", not fouten, str(fouten)),
        check("Past vanaf jan 2027 bij w01", "Past vanaf jan 2027" in w01),
        check("Alleen met cao-verhoging bij w02", "Alleen met cao-verhoging" in w02),
        check("scenario's in laag 2 met planning", "Vanaf jan 2027 (planning)</dt><dd>past" in w01
              and "<dt>Nu</dt><dd>past niet, max. koopsom" in w01),
        check("twijfelregel met Onderaan gezet", "Twijfelbuurt Leyenburg (jouw lijst). Onderaan gezet." in w10),
        check("redenregel met minteken U+2212 in de punten", "−" in body and "-0,5" not in body),
    ])


def test_prijs_onbekend() -> bool:
    print("prijs onbekend")
    body = _body()
    kaart = _kaart(body, "7990104")
    data = _woning_data(body)
    nieuw_sectie = body[body.index('<section id="nieuw"'):body.index('id="eerder"')]
    rijen, meta = testrijen()
    for r in rijen:
        r["is_nieuw"] = False
    oud = funda_ui.render_report_body(rijen, meta)
    groep = oud.index('data-poort="PRIJS ONBEKEND"')
    return all([
        check("op aanvraag", '<dd class="cijfer-leeg">op aanvraag</dd>' in kaart),
        check("woonlasten onbekend", '<dd class="cijfer-leeg">onbekend</dd>' in kaart),
        check("geen € 0 in de body", "€ 0<" not in body and "€ 0 " not in body and "€ 0," not in body),
        check("statusregel info", "st-ONBEKEND" in kaart and "geen vraagprijs, dus geen leentoets" in kaart),
        check("nieuw: laatste kaart in Nieuw", re.findall(r'data-id="(\d+)"', nieuw_sectie)[-1] == "7990104"),
        check("eerder gezien: in de groep Prijs onbekend, na Past niet", oud.index('data-id="7990104"') > groep
              and groep > oud.index('data-poort="PAST NIET"')),
        check("achteraan in #woning-data", data["woningen"][-1]["id"] == "7990104"),
        check("geen leentoets in laag 2", "Zonder vraagprijs geen leentoets" in kaart),
        check("netto en prijs null in de data", data["woningen"][-1]["netto"] is None and data["woningen"][-1]["prijs"] is None),
    ])


def test_volgorde() -> bool:
    print("volgorde (poort, twijfel, -score)")
    data = _woning_data(_body())["woningen"]
    sleutel = [(funda_ui.POORT_RANG[w["poort"]], w["twijfel"], -w["score"]) for w in data]
    poorten = [w["poort"] for w in data]
    krap = [w for w in data if w["poort"] == "KRAP"]
    return all([
        check("gesorteerd", sleutel == sorted(sleutel)),
        check("poorten op volgorde", poorten == sorted(poorten, key=funda_ui.POORT_RANG.get)),
        check("twijfel onderaan in Krap, ook met hogere score", [w["twijfel"] for w in krap] == sorted(w["twijfel"] for w in krap)
              and any(w["twijfel"] for w in krap)),
    ])


def test_woning_data() -> bool:
    print("#woning-data")
    rijen, meta = testrijen()
    rijen[0]["d"]["title"] = "Teststraat </script><script>alert(1)</script> 1"
    body = funda_ui.render_report_body(rijen, meta)
    m = re.search(r'<script type="application/json" id="woning-data">(.*?)</script>', body, re.S)
    try:
        data = json.loads(m.group(1))
        ok = True
    except ValueError:
        data, ok = {}, False
    velden = {"id", "card_id", "titel", "buurt", "stad", "poort", "status_kort", "scenario_tekst", "netto", "prijs", "m2",
              "score", "score_tekst", "twijfel", "gedaald", "dagen", "reis_min", "reis_tekst", "top_plus", "top_let_op",
              "lat", "lon", "nieuw_run"}
    return all([
        check("geldige JSON", ok),
        check("geen </script in de data", "</script" not in m.group(1).lower()),
        check("titel met </script blijft tekst", any("</script>" in w["titel"] for w in data.get("woningen", []))),
        check("velden per woning", all(set(w) == velden for w in data.get("woningen", []))),
        check("id = global_id als tekst", all(w["id"].isdigit() for w in data.get("woningen", []))),
    ])


def test_css_regels() -> bool:
    print("CSS-regels")
    zonder_commentaar = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    rest = zonder_commentaar
    for kop in (":root{", "@media (prefers-color-scheme:dark){", ':root[data-theme="dark"]{'):
        rest = rest.replace(_blok(rest, kop), "{}", 1)
    los = re.findall(r"(?<![\w-])#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}(?:[0-9a-fA-F]{2})?)?(?![\w-])", rest)
    body = _body()
    alles = {"app.css": CSS, "app.js": JS, "slot.html": SLOT, "body": body}
    verboden = [(n, w) for n, t in alles.items() for w in VERBODEN_WOORDEN if w in t]
    licht, _, _ = tokenblokken()
    return all([
        check("geen hex buiten de tokenblokken", not los, str(los[:5])),
        check("geen losse font-size", "font-size:" not in CSS),
        check("geen style= in de body", 'style="' not in body),
        check("geen merk-, font- of kleurverwijzing", not verboden, str(verboden)),
        check("UI_CSS bevat letterlijk \\2212", "\\2212" in funda_ui.UI_CSS),
        check("THEME_COLOR = topbalk (licht)", funda_ui.THEME_COLOR == licht["background-color-strong"]),
        check("ACHTERGROND = pagina (licht)", funda_ui.ACHTERGROND == licht["background-color-page"]),
        check("labels zonder feedbackkleur", {licht["label-daling"], licht["label-lang"]}.isdisjoint(
            {licht[k] for k in licht if k.startswith("foreground-color-feedback")})),
        check("vier poortkleuren verschillend", len({licht[k] for k in ("pin-past", "pin-krap", "pin-niet", "pin-onbekend")}) == 4),
    ])


def test_contrast() -> bool:
    print("contrast WCAG AA (licht en donker)")
    licht, media, expliciet = tokenblokken()
    paren = contrasten()
    laag = [(n, round(l, 2), round(d, 2), m) for n, l, d, m in paren if l < m or d < m]
    kop = CSS[:CSS.index("*/")]
    ontbreekt = [n for n, l, d, _ in paren if contrast_regel(n, l, d) not in kop]
    for n, l, d, m in paren:
        print(f"      {n}: {l:.2f} | {d:.2f} (min {m})")
    return all([
        check("twee donkerblokken gelijk", media == expliciet, str(set(media.items()) ^ set(expliciet.items()))),
        check("donker zet alle kleurtokens die van licht afwijken", all(k in licht for k in media)),
        check(f"{len(paren)} paren boven het minimum", not laag, str(laag)),
        check("commentaarblok noemt de gemeten waarden", not ontbreekt, str(ontbreekt[:5])),
    ])


def test_rente_en_budget() -> bool:
    print("rente en Jouw budget")
    oud = _body()
    vers = _body({"rente": {"pct": 3.86, "bron": "ASN", "datum": "2026-11-05", "oud": False, "melding": None}})
    melding = _body({"rente": {"pct": 3.9, "bron": "DNB", "datum": "2026-09-30", "oud": False,
                               "melding": "ASN gaf geen rente; DNB-maandcijfer gebruikt"}})
    fractie = _body({"rente": {"pct": 0.0386, "bron": "handmatig", "datum": "2026-11-01", "oud": False, "melding": None}})
    budget = oud[oud.index('id="budget"'):oud.index("</details>", oud.index('id="budget"'))]
    return all([
        check("melding bij oude rente", 'id="rente-melding"' in oud and "Rente is 123 dagen oud" in oud),
        check("geen melding bij verse rente", 'id="rente-melding"' not in vers),
        check("melding uit de rentemodule zichtbaar", 'id="rente-melding"' in melding
              and "ASN gaf geen rente; DNB-maandcijfer gebruikt." in melding),
        check("bron en peildatum in budget", "standaardwaarde uit de code, peildatum 6 juli 2026 (123 dagen oud)" in budget),
        check("ASN met datum", "ASN Bank, peildatum 5 november 2026" in vers and "3,86%" in vers),
        check("rente als fractie wordt procent", "3,86%" in fractie),
        check("kop zegt rente oud", "· rente 123 dagen oud" in oud),
        check("max. koopsom per scenario", "<dt>Nu</dt>" in budget and "<dt>Vanaf jan 2027 (planning)</dt>" in budget
              and "<dt>Vanaf jan 2027 met cao</dt>" in budget),
        check("groepen volgen planning", "volgen het scenario &quot;Vanaf jan 2027&quot;" in budget),
        check("geen inkomen in de body", "inkomen" not in oud.lower() and "62.000" not in oud),
        check("scenario's uit meta gaan voor", "<dd>€\u00a0250.000</dd>" in _body(
            {"scenarios": [{"id": "nu", "label": "Nu", "max_koopsom": 250000}]})),
        check("je grens netto", "<dt>Je grens</dt><dd>€ 1.450 netto per maand</dd>" in budget),
    ])


def test_meta_en_randgevallen() -> bool:
    print("meta optioneel en randgevallen")
    rijen, _ = testrijen()
    leeg = funda_ui.render_report_body([], {})
    zonder = funda_ui.render_report_body(rijen, {})
    push = _body({"push_beschikbaar": True})
    push_al = _body({"push_beschikbaar": True, "push_ingesteld": True})
    kaal = funda_ui.render_report_body([{"d": {"global_id": 1, "title": "Kale woning", "price": 250000}}], {})
    return all([
        check("lege lijst rendert", '<div id="app"' in leeg and _woning_data(leeg) == {"woningen": []}),
        check("zonder meta: geen runknop, wel lijst", "Nieuwe run starten" not in zonder and zonder.count("<article") == 13),
        check("met actions_url een runknop", "Nieuwe run starten" in _body()),
        check("push-blok met de id's van de push-JS", all(f'id="{i}"' in push for i in
              ("push-subscribe-btn", "push-copy-btn", "push-subscription-output", "push-status"))),
        check("push-blok weg als er al een abonnement is", "push-subscribe-btn" not in push_al),
        check("push-blok weg zonder sleutel", "push-subscribe-btn" not in _body()),
        check("woning zonder beoordeling valt niet weg", "Kale woning" in kaal and "geen beoordeling" in kaal),
        check("apparaat-blok standaard verborgen", '<details class="opbouw" id="apparaat" hidden>' in zonder),
        check("Bijgewerkt en volgende run", "Bijgewerkt 6 nov, 10:34 · volgende rond 17:30" in _body()),
    ])


def test_app_js() -> bool:
    print("app.js: nieuw pas gezien in beeld, opslag")
    return all([
        check("IntersectionObserver", "new IntersectionObserver(" in JS),
        check("zonder IntersectionObserver niets markeren", "!('IntersectionObserver' in window)) return;" in JS),
        check("minstens de helft zichtbaar", "GEZIEN_DEEL = 0.5" in JS and "intersectionRatio >= GEZIEN_DEEL" in JS),
        check("een seconde", "GEZIEN_MS = 1000" in JS and "}, GEZIEN_MS);" in JS),
        check("niet meer alles gezien bij pagehide", "opslag.gezien = ids" not in JS),
        check("opslag in try/catch", "try { return JSON.parse(localStorage.getItem(OPSLAG)) || {}; } catch(e)" in JS
              and "try { localStorage.setItem(OPSLAG" in JS),
        check("pins met poorticoon", "POORT_IC[w.poort]" in JS),
        check("vergeet via het slotscherm", "window.fundaApparaat" in JS and '[data-actie="vergeet"]' in JS),
    ])


def test_slot() -> bool:
    print("ui/slot.html")
    gevonden = re.findall(r"__[A-Z_]+__", SLOT)
    nodig = list(funda_ui.SLOT_PLACEHOLDERS)
    waarden = {p: f"<!--{p.strip('_').lower()}-->" for p in nodig}
    waarden.update({"__GZ__": "1", "__ITERS__": "100000", "__SALT__": "c2FsdA==", "__IV__": "aXY=", "__CT__": "Y3Q="})
    gevuld = funda_ui.vul_slot(waarden)
    try:
        funda_ui.vul_slot({"__GZ__": "1"})
        fout_bij_missen = False
    except ValueError:
        fout_bij_missen = True
    zonder = SLOT
    for p in nodig:
        zonder = zonder.replace(p, "")
    theme = re.search(r'<meta name="theme-color" content="(#[0-9a-fA-F]{6})">', SLOT)
    return all([
        check("precies de placeholders, elk één keer", sorted(gevonden) == sorted(nodig), str(gevonden)),
        check("vul_slot vervangt alles", not re.search(r"__[A-Z_]+__", gevuld)),
        check("vul_slot weigert ontbrekende waarden", fout_bij_missen),
        check("label for=pw", '<label for="pw">' in SLOT),
        check("foutmelding met role=alert", 'role="alert"' in SLOT),
        check("theme-color = THEME_COLOR", bool(theme) and theme.group(1) == funda_ui.THEME_COLOR),
        check("color-scheme light dark", '<meta name="color-scheme" content="light dark">' in SLOT),
        check("gzip uitpakken", 'DecompressionStream("gzip")' in SLOT and "const GZ = __GZ__;" in SLOT),
        check("melding te oude browser", "class TeOud" in SLOT and "Werk je iPhone bij naar iOS 16.4 of nieuwer." in SLOT),
        check("niet-exporteerbare basissleutel", 'importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"])' in SLOT),
        check("sleutel in IndexedDB", "indexedDB.open(" in SLOT and "s.put({sleutel" in SLOT),
        check("nooit het wachtwoord bewaren", "localStorage.setItem" not in SLOT and "sessionStorage.setItem" not in SLOT),
        check("oud wachtwoord opgeruimd", 'OUD_PW = "funda_pw_persist_v1"' in SLOT and "localStorage.removeItem(OUD_PW)" in SLOT
              and 'sessionStorage.removeItem("funda_pw")' in SLOT),
        check("terugval met melding", "Onthouden lukt niet in deze browser." in SLOT),
        check("knop Vergeet dit apparaat", ">Vergeet dit apparaat</button>" in SLOT and "window.fundaApparaat" in SLOT),
        check("na ontsleutelen fundaAfterReportLoad", "window.fundaAfterReportLoad()" in SLOT),
        check("geen merknaam of voornaam", "Funda Shortlist" not in SLOT and "<title>Woningrapport</title>" in SLOT),
        check("slotscherm zonder placeholders <= 12 kB", len(zonder.encode()) <= 12_000, f"{len(zonder.encode())} bytes"),
    ])


def test_groottes() -> bool:
    print("groottes")
    body = _body()
    per_woning = len(body.encode()) / 13
    return all([
        check("ui/app.css <= 40 kB", len(CSS.encode()) <= 40_000, f"{len(CSS.encode())} bytes"),
        check("ui/app.js <= 22 kB", len(JS.encode()) <= 22_000, f"{len(JS.encode())} bytes"),
        check("body <= 14 kB per woning", per_woning <= 14_000, f"{per_woning:.0f} bytes per woning"),
    ])


def test_tekst() -> bool:
    print("tekst: geen em dash of gedachtestreepje, geen bevolkingskenmerken")
    body = _body()
    bronnen = {"body": body, "app.css": CSS, "app.js": JS, "slot.html": SLOT,
               "funda_ui.py": (HIER / "funda_ui.py").read_text(encoding="utf-8")}
    streep = [n for n, t in bronnen.items() if "—" in t or "–" in t]
    return all([
        check("geen em dash of gedachtestreepje", not streep, str(streep)),
        check("geen bevolkingskenmerken in de body", not any(w in body.lower() for w in BEVOLKING)),
        check("€ met spatie, geen €-bedrag zonder spatie", not re.search(r"€\d", body)),
        check("m² en geen m2 in zichtbare tekst", " m2 " not in body),
    ])


def main() -> int:
    resultaten = [test_contract_testdata(), test_ids_en_attributen(), test_statusregels(), test_status_en_scenario_in_kaart(),
                  test_prijs_onbekend(), test_volgorde(), test_woning_data(), test_css_regels(), test_contrast(),
                  test_rente_en_budget(), test_meta_en_randgevallen(), test_app_js(), test_slot(), test_groottes(), test_tekst()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
