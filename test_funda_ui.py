"""Offline tests voor de UI: funda_ui.py, ui/app.css, ui/app.js en ui/slot.html.

Draait op testdata/woningen.json (13 fictieve woningen) en testdata/beoordeling_v3.json (het
beoordelingscontract met fictieve scenario's). Geen netwerk, geen echte persoonsgegevens.

Draaien: python test_funda_ui.py
"""
from __future__ import annotations

import base64
import copy
import json
import math
import re
import shutil
import subprocess
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
SLOT_JS = (UI / "slot.js").read_text(encoding="utf-8")
SLOT_CSS = (UI / "slot.css").read_text(encoding="utf-8")
PUSH_JS = (UI / "push.js").read_text(encoding="utf-8")
SLOT_ALLES = SLOT + SLOT_CSS + SLOT_JS + PUSH_JS   # alles van het slotscherm, voor de teksten en verboden woorden

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
    ("score/pagina", "foreground-color-highlight-strong", "background-color-page", TEKST),
    ("score/kaart", "foreground-color-highlight-strong", "background-color-default", TEKST),
    ("link en knoptekst/pagina", "foreground-color-interactive-strong", "background-color-page", TEKST),
    ("link en knoptekst/kaart", "foreground-color-interactive-strong", "background-color-default", TEKST),
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
    # Rand van chip, tertiaire knop, onderknop en wissel (het vlak zelf verschilt nauwelijks van de omgeving).
    ("knoprand/pagina", "border-color-interactive-neutral", "background-color-page", NIET_TEKST),
    ("knoprand/kaart", "border-color-interactive-neutral", "background-color-default", NIET_TEKST),
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
# Merk- en fontnamen van derden, uit losse delen opgebouwd: de namen zelf horen niet in de repo te staan
# (besluit eigenaar), ook niet in deze test. Zie test_geen_merknaam.
MERKNAMEN = ["AN" + "WB", "No" + "mad", "Clan" + " Pro", "Ber" + "nina"]
VERBODEN_WOORDEN = MERKNAMEN + [MERKNAMEN[1].lower(), "#ffcd00", "#003d86"]
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
        d["_enrichment"] = {"price_history": {"changes": hist}}
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


def _is_paars(hexkleur: str) -> bool:
    """Tint tussen 250 en 330 graden met merkbare verzadiging (het afgewezen palet "Lavendel")."""
    import colorsys
    x = hexkleur.lstrip("#")
    if len(x) != 6:
        return False
    r, g, b = (int(x[i:i + 2], 16) / 255 for i in (0, 2, 4))
    tint, licht, verz = colorsys.rgb_to_hls(r, g, b)
    return 250 <= tint * 360 <= 330 and verz > 0.25 and 0.08 < licht < 0.95


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
            if set(s) != scen_velden or s["id"] not in ("nu", "later", "later_extra") or not isinstance(s["past"], bool):
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
              == {"Past nu", "Past later", "Past alleen met bonus", "Past in geen scenario", None}),
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
    uit_js -= {"card-", "kaart-vraag"}   # het vlak "Toon kaart" maakt app.js zelf (ook bij een oudere index.html)
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
    """De statusregel komt uit funda_beoordeling.status_kort() (daar getest); de UI rekent hem niet zelf uit."""
    print("statusregel uit de beoordeling, niet zelf berekend")

    def status(beoordeling, prijs=250000):
        body = funda_ui.render_report_body([{"d": {"global_id": 1, "price": prijs, "title": "Teststraat 1"},
                                             "beoordeling": beoordeling}], {})
        return re.search(r'<strong>[^<]*</strong>[^<]*', _kaart(body, "1")).group(0)

    # Een fin die met de oude eigen regel in de UI een andere tekst gaf: de UI volgt het model.
    b = {"poort": "KRAP", "status_kort": "Krap · € 3.200 eigen geld te weinig",
         "financiering": {"netto": 1474, "grens": 1450, "tekort": 3200}}
    return all([
        check("status_kort uit de beoordeling, letterlijk", status(b) == "<strong>Krap</strong> · €\u00a03.200 eigen geld te weinig",
              status(b)),
        check("beoordeling zonder status_kort: alleen het poortwoord", status({"poort": "PAST"}) == "<strong>Past</strong>",
              status({"poort": "PAST"})),
        check("zonder beoordeling: ga het zelf na", status(None) == "<strong>Krap</strong> · geen beoordeling, ga het zelf na"
              and status(None, prijs=None) == "<strong>Prijs onbekend</strong> · geen beoordeling, ga het zelf na",
              status(None) + " / " + status(None, prijs=None)),
        check("geen eigen statusberekening meer in funda_ui",
              not any(hasattr(funda_ui, n) for n in ("status_reden", "status_tekst", "TEKORT_PAST_NIET"))
              and "eigen_geld_tekort_past_niet" not in Path(funda_ui.__file__).read_text(encoding="utf-8")),
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
        if f"<strong>{naam}</strong> · {funda_ui.h(reden)}" not in kaart:
            fouten.append(r["_fixture"] + " status")
        st = b["financiering"]["scenario_tekst"]
        if st and f'<span class="w-scenario">{funda_ui.scenario_regel(st)}</span>' not in kaart:
            fouten.append(r["_fixture"] + " scenario")
        if f'st-{funda_ui.POORT_CLS[b["poort"]]}' not in kaart or f'#i-{funda_ui.POORT_IC[b["poort"]]}' not in kaart:
            fouten.append(r["_fixture"] + " poortklasse of icoon")
    w01 = _kaart(body, "7990101")
    w02 = _kaart(body, "7990102")
    w10 = _kaart(body, "7990110")
    return all([
        check("statusregel, scenario, klasse en icoon per kaart", not fouten, str(fouten)),
        check("scenario met label: Financiering: past later bij w01", "Financiering: past later" in w01),
        check("Financiering: past alleen met bonus bij w02", "Financiering: past alleen met bonus" in w02),
        check("scenario_regel", funda_ui.scenario_regel("Past nu") == "Financiering: past nu"
              and funda_ui.scenario_regel(None) == ""),
        check("scenario's in laag 2 met planning", "Later (planning)</dt><dd>past" in w01
              and "<dt>Nu</dt><dd>past niet, koopsom tot" in w01),
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
        check("geen € 0 in de body", not re.search(r"€[ \u00a0]0(?![\d.])", body)),
        check("statusregel info", "st-ONBEKEND" in kaart and "geen vraagprijs, dus geen leentoets" in kaart),
        check("nieuw: laatste kaart in Nieuw", re.findall(r'data-id="(\d+)"', nieuw_sectie)[-1] == "7990104"),
        check("eerder gezien: in de groep Prijs onbekend, na Past niet", oud.index('data-id="7990104"') > groep
              and groep > oud.index('data-poort="PAST NIET"')),
        check("achteraan in #woning-data", data["woningen"][-1]["id"] == "7990104"),
        check("geen leentoets in laag 2", "Zonder vraagprijs geen leentoets" in kaart),
        check("netto en prijs null in de data", data["woningen"][-1]["netto"] is None and data["woningen"][-1]["prijs"] is None),
    ])


def test_volgorde() -> bool:
    print("volgorde (geen vraagprijs, poort, twijfel, -score)")
    data = _woning_data(_body())["woningen"]
    sleutel = [(funda_ui.POORT_RANG[w["poort"]], w["twijfel"], -w["score"]) for w in data]
    poorten = [w["poort"] for w in data]
    krap = [w for w in data if w["poort"] == "KRAP"]
    return all([
        check("gesorteerd", sleutel == sorted(sleutel)),
        check("poorten op volgorde", poorten == sorted(poorten, key=funda_ui.POORT_RANG.get)),
        check("twijfel onderaan in Krap, ook met hogere score", [w["twijfel"] for w in krap] == sorted(w["twijfel"] for w in krap)
              and any(w["twijfel"] for w in krap)),
        check("zonder vraagprijs achteraan, ook op PAST NIET (veiling)",
              [w["id"] for w in funda_ui.sorteer([
                  {"id": "veiling", "poort": "PAST NIET", "prijs": None, "twijfel": [], "score": 9.0},
                  {"id": "onbekend", "poort": "PRIJS ONBEKEND", "prijs": None, "twijfel": [], "score": 9.9},
                  {"id": "gewoon", "poort": "PAST NIET", "prijs": 250000, "twijfel": [], "score": 3.5}])]
              == ["gewoon", "veiling", "onbekend"]),
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
    alles = {"app.css": CSS, "app.js": JS, "slot": SLOT_ALLES, "body": body}
    verboden = [(n, w) for n, t in alles.items() for w in VERBODEN_WOORDEN if w in t]
    licht, media, _ = tokenblokken()
    donker = {**licht, **media}
    return all([
        check("geen hex buiten de tokenblokken", not los, str(los[:5])),
        check("geen losse font-size", "font-size:" not in CSS),
        check("geen style= in de body", 'style="' not in body),
        check("geen merk-, font- of kleurverwijzing", not verboden, str(verboden)),
        check("UI_CSS bevat letterlijk \\2212", "\\2212" in funda_ui.UI_CSS),
        check("THEME_COLOR = topbalk (licht)", funda_ui.THEME_COLOR == licht["background-color-strong"]),
        check("ACHTERGROND = pagina (licht)", funda_ui.ACHTERGROND == licht["background-color-page"]),
        check("THEME_COLOR_DONKER = topbalk (donker)", funda_ui.THEME_COLOR_DONKER == donker.get("background-color-strong")),
        check("palet Inkt en blauw (besluit 7 nov 2026): topbalk, knop, link en pagina",
              (licht["background-color-strong"], licht["background-color-interactive-strong"],
               licht["foreground-color-interactive-strong"], licht["background-color-page"])
              == ("#0f172a", "#2563eb", "#1d4ed8", "#f4f6f9")),
        check("geen paars meer in de tokens", not any(_is_paars(v) for v in list(licht.values()) + list(donker.values())),
              str([v for v in list(licht.values()) + list(donker.values()) if _is_paars(v)])),
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
    met_uitleg = _body({"rente": {"pct": 4.11, "bron": "standaard", "datum": "2026-07-06", "oud": True,
                                  "melding": "Geen actuele rente gevonden. Gerekend met 4,11% van 6 juli 2026; "
                                             "zet financien.rente.pct in je config."}})
    rente_top = met_uitleg[met_uitleg.index('id="rente-melding"'):met_uitleg.index("</a>", met_uitleg.index('id="rente-melding"'))]
    rente_budget = met_uitleg[met_uitleg.index('id="budget"'):met_uitleg.index("</details>", met_uitleg.index('id="budget"'))]
    return all([
        check("melding bij oude rente: één zin met datum, percentage en leeftijd", 'id="rente-melding"' in oud
              and "Rente van 6 juli 2026 (4,11%) is 123 dagen oud: woonlasten kunnen afwijken. <u>Bekijk de aannames</u>" in oud),
        check("oude rente: uitleg van de rentemodule alleen in Jouw budget", "zet financien.rente.pct" not in rente_top
              and "zet financien.rente.pct in je config." in rente_budget),
        check("geen melding bij verse rente", 'id="rente-melding"' not in vers),
        check("melding uit de rentemodule zichtbaar", 'id="rente-melding"' in melding
              and "ASN gaf geen rente; DNB-maandcijfer gebruikt." in melding),
        check("bron en peildatum in budget", "standaardrente van dit rapport, peildatum 6 juli 2026 (123 dagen oud)" in budget),
        check("ASN met datum", "ASN Bank, peildatum 5 november 2026" in vers and "3,86%" in vers),
        check("rente als fractie wordt procent", "3,86%" in fractie),
        check("kop zegt rente oud", "· rente 123 dagen oud" in oud),
        check("hoogste koopsom per scenario", "Hoogste koopsom per scenario." in budget and "<dt>Nu</dt>" in budget and "<dt>Later (planning)</dt>" in budget
              and "<dt>Met bonus</dt>" in budget),
        check("groepen volgen planning", "volgen het scenario 'Later'." in budget),
        check("geen inkomen in de body", "inkomen" not in oud.lower() and "62.000" not in oud),
        check("scenario's uit meta gaan voor", "<dd>€\u00a0250.000</dd>" in _body(
            {"scenarios": [{"id": "nu", "label": "Nu", "max_koopsom": 250000}]})),
        check("je grens netto (harde spatie na €)", "<dt>Je grens</dt><dd>€\u00a01.450 netto per maand</dd>" in budget),
    ])


def test_meta_en_randgevallen() -> bool:
    print("meta optioneel en randgevallen")
    rijen, _ = testrijen()
    leeg = funda_ui.render_report_body([], {})
    zonder = funda_ui.render_report_body(rijen, {})
    push = _body({"push_beschikbaar": True})
    push_al = _body({"push_beschikbaar": True, "push_ingesteld": True})
    kaal = funda_ui.render_report_body([{"d": {"global_id": 1, "title": "Kale woning", "price": 250000}}], {})
    # FICTIEF: twee WOZ-regels, de oudste eerst. Kaart en model tonen allebei de nieuwste (prijshistorie()).
    wozen = [{"price": 230000, "status": "woz", "date": "1 jan, 2025"}, {"price": 240000, "status": "woz", "date": "1 jan, 2026"}]
    met_woz = funda_ui.render_report_body([{"d": {"global_id": 2, "title": "Woning met WOZ", "price": 250000,
                                                  "_enrichment": {"price_history": {"changes": wozen}}}}], {})
    return all([
        check("WOZ in de kaart: de nieuwste, met peildatum", "€\u00a0240.000 (peildatum 1 januari 2026)" in met_woz
              and "230.000" not in met_woz),
        check("lege lijst rendert", '<div id="app"' in leeg and _woning_data(leeg) == {"woningen": []}),
        check("zonder meta: geen runknop, wel lijst", "Nieuwe run starten" not in zonder and zonder.count("<article") == 13),
        check("met actions_url een verversknop, zonder 'run' of de naam van de host in de tekst",
              'aria-label="Ververs het rapport: opent de startpagina in een nieuw venster"' in _body()
              and "Nieuwe run" not in _body()),
        check("push-blok met de id's van de push-JS", all(f'id="{i}"' in push for i in
              ("push-subscribe-btn", "push-copy-btn", "push-subscription-output", "push-status"))),
        check("push-blok weg als er al een abonnement is", "push-subscribe-btn" not in push_al),
        check("push-blok weg zonder sleutel", "push-subscribe-btn" not in _body()),
        check("woning zonder beoordeling valt niet weg", "Kale woning" in kaal and "geen beoordeling" in kaal),
        check("apparaat-blok standaard verborgen", '<details class="opbouw" id="apparaat" hidden>' in zonder),
        check("Bijgewerkt en volgende run, kort (één regel op 390 px)", "Bijgewerkt 6 nov 10:34 · volgende 17:30" in _body()),
    ])


def test_app_js() -> bool:
    print("app.js: nieuw pas gezien in beeld, opslag")
    return all([
        check("IntersectionObserver", "new IntersectionObserver(" in JS),
        # Verbergen is een schakelaar: een verborgen woning zet je met hetzelfde oog terug
        # (eerder kon dat alleen via "Ongedaan maken" in de melding, en dubbelde de id).
        check("verborgen woning terugzetten", "'[data-actie=\"verberg\"]') && opslag.verborgen.indexOf(id) >= 0" in JS
              and "Teruggezet: " in JS and "'Zet terug'" in JS),
        check("zonder IntersectionObserver niets markeren", "!('IntersectionObserver' in window)) return;" in JS),
        check("minstens de helft zichtbaar", "GEZIEN_DEEL = 0.5" in JS and "intersectionRatio >= GEZIEN_DEEL" in JS),
        check("een seconde", "GEZIEN_MS = 1000" in JS and "}, GEZIEN_MS);" in JS),
        check("niet meer alles gezien bij pagehide", "opslag.gezien = ids" not in JS),
        # Was: synchroon en leesbaar in localStorage. Nu elke toegang via ruw(), wisRuw() of schrijf(), in try/catch;
        # achter het slotscherm versleuteld (test_opslag_js draait het in node).
        check("opslag: elke toegang tot localStorage in try/catch, en alleen onder de leesbare sleutel en de twee vakken",
              JS.count("localStorage.") == 5 and "function ruw(naam){ try { return localStorage.getItem(naam); } catch(e)" in JS
              and "function wisRuw(naam){ try { localStorage.removeItem(naam); } catch(e)" in JS
              and "try { localStorage.setItem(OPSLAG, JSON.stringify(opslag)); } catch(e){}" in JS
              and "try { localStorage.setItem(vak, pak); localStorage.removeItem(OPSLAG); } catch(e){}" in JS
              and "var OPSLAG_VAKKEN = ['funda_rapport_v2', 'funda_rapport_v2_reserve']" in JS),
        check("opslag: leesbaar schrijven alleen zonder slotscherm", "if(!veilig){ try { localStorage.setItem(OPSLAG," in JS
              and "veilig = !!a;" in JS and JS.count("localStorage.setItem(OPSLAG,") == 1),
        check("opslag: AES-GCM met een verse IV per schrijfactie, opgevuld",
              "crypto.getRandomValues(new Uint8Array(12))" in JS and "{name:'AES-GCM', iv:iv}, sleutel" in JS
              and "while(tekst.length % OPSLAG_BLOK) tekst += ' ';" in JS),
        check("opslag: de app krijgt alleen de afgeleide sleutel van het slotscherm", "a.opslagSleutel" in JS
              and "importKey" not in JS and "deriveKey" not in JS and "pw" not in re.findall(r"\bpw\b", JS)),
        check("opslag: de staat komt vóór de app start, de app blijft zolang uit beeld",
              "leesOpslag().then(function(r){" in JS and "try { start(r.staat); } finally { app.hidden = false; }" in JS
              and "if(r.melding) toast(r.melding);" in JS),
        check("kaart: laadt niet vanzelf, ook niet op een breed scherm",
              "if(window.matchMedia('(min-width:64rem)').matches) startKaart();" not in JS
              and JS.count("startKaart();") == 3   # na de keuze, bij een keuze eerder in de sessie, en als Leaflet nog laadt
              and "if(v === 'kaart'){ kiesKaart();" in JS and "else if(el.matches('[data-actie=\"toon-kaart\"]')){ kiesKaart(); }" in JS),
        check("kaart: vlak met één zin en de knop Toon kaart, zonder style-attribuut",
              "'<p>De kaart haalt tegels op bij OpenStreetMap.</p>'" in JS
              and '<button type="button" class="knop knop-sec" data-actie="toon-kaart">Toon kaart</button>' in JS
              and "style=" not in JS and ".style." not in JS and ".kaart-vraag{" in CSS and ".kaart-paneel.is-wacht .kaart-legenda{display:none}" in CSS),
        check("kaart: de keuze geldt voor de sessie en vervalt bij vergrendelen, niets in localStorage",
              "sessionStorage.setItem(KAART_GEKOZEN, '1')" in JS and "sessionStorage.removeItem(KAART_GEKOZEN)" in JS
              and "localStorage.setItem(KAART" not in JS),
        check("pins met poorticoon", "POORT_IC[w.poort]" in JS),
        check("vergeet via het slotscherm", "window.fundaApparaat" in JS and '[data-actie="vergeet"]' in JS),
    ])


# Het echte ui/app.js in node zonder DOM: de opslag met een namaak-localStorage en de Web Crypto van node.
NODE_OPSLAG = r"""
const ls = new Map(); let gezet = [];
Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {
  getItem: k => ls.has(k) ? ls.get(k) : null, removeItem: k => { ls.delete(k); },
  setItem: (k, v) => { ls.set(k, String(v)); gezet.push(k); }}});
global.window = {}; global.document = {readyState: 'loading', addEventListener(){}};
require(process.argv[1]);
const o = window.fundaRapportOpslag, V1 = 'funda_rapport_v1', V2 = 'funda_rapport_v2';
const rust = async () => { do { await new Promise(r => setTimeout(r, 2)); } while (o.bezig()); };
const maak = () => crypto.subtle.generateKey({name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt']);
(async () => {
  const uit = {};
  // 1. zonder slotscherm: leesbaar, zoals het was
  ls.set(V1, JSON.stringify({bewaard: ['1']}));
  let r = await o.lees();
  o.schrijf({bewaard: ['1', '2']});
  uit.lokaal = {staat: r.staat, melding: r.melding || '', v1: ls.get(V1), v2: ls.has(V2)};
  // 2. met slotscherm en sleutel: migratie
  const sleutel = await maak();
  window.fundaApparaat = {opslagSleutel: sleutel};
  r = await o.lees();
  uit.migratie = {staat: r.staat, melding: r.melding || '', v1_voor: ls.has(V1)};
  o.schrijf(r.staat); await rust();
  uit.migratie.v1_na = ls.has(V1); uit.migratie.v2 = ls.get(V2);
  // 3. terug uit de versleutelde opslag
  r = await o.lees();
  uit.terug = {staat: r.staat, melding: r.melding || ''};
  // 4. snel na elkaar: de laatste stand wint, schrijfacties na elkaar
  gezet = [];
  for (let i = 0; i < 20; i++) o.schrijf({bewaard: ['1', '2'], n: i});
  await rust();
  const pak = ls.get(V2);
  r = await o.lees();
  uit.snel = {n: r.staat.n, schrijfacties: gezet.filter(k => k === V2).length, iv_nieuw: JSON.parse(pak).iv !== JSON.parse(uit.migratie.v2).iv,
              even_lang: pak.length === uit.migratie.v2.length};
  // 5. een leesbare staat naast een versleutelde: de versleutelde telt, de leesbare gaat weg
  ls.set(V1, JSON.stringify({bewaard: ['oud']}));
  r = await o.lees();
  uit.beide = {n: r.staat.n, v1: ls.has(V1)};
  // 6. andere sleutel (nieuw wachtwoord) en kapotte inhoud: leeg beginnen, met een melding
  window.fundaApparaat = {opslagSleutel: await maak()};
  r = await o.lees();
  uit.andere_sleutel = {staat: r.staat, melding: r.melding || ''};
  window.fundaApparaat = {opslagSleutel: sleutel};
  uit.kapot = [];
  for (const w of ['kapot', '{}', '[]', 'null', JSON.stringify({v: 1, iv: 'AAAAAAAAAAAAAAAA', ct: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'})]) {
    ls.set(V2, w);
    r = await o.lees();
    uit.kapot.push({staat: r.staat, melding: r.melding || ''});
  }
  o.schrijf({bewaard: ['3']}); await rust();
  r = await o.lees();
  uit.na_kapot = {staat: r.staat, melding: r.melding || ''};
  // 7. slotscherm zonder sleutel: niets schrijven, wel zeggen
  window.fundaApparaat = {};
  const voor = ls.get(V2); gezet = [];
  r = await o.lees();
  o.schrijf({bewaard: ['4']}); await rust();
  uit.zonder_sleutel = {staat: r.staat, melding: r.melding || '', geschreven: gezet.length, ongewijzigd: ls.get(V2) === voor};
  // 8. een sleutel die niet past overschrijft niets: het onleesbare pakket blijft als reserve staan
  const R = 'funda_rapport_v2_reserve', A = await maak(), B = await maak(), C = await maak();
  const als = async (k, staat) => { window.fundaApparaat = {opslagSleutel: k}; const x = await o.lees();
    if (staat) { o.schrijf(staat); await rust(); } return {staat: x.staat, melding: x.melding || ''}; };
  ls.clear();
  await als(A, {bewaard: ['a1', 'a2'], verborgen: ['a3']});
  const pakA = ls.get(V2);
  const w = {};
  w.eerste_in_v2 = !!pakA && !ls.has(R);
  w.b_opent = await als(B);                                   // nieuw wachtwoord, nog niets opgeslagen
  w.niets_overschreven = ls.get(V2) === pakA && !ls.has(R);
  w.a_terug_zonder_nieuw = await als(A);                      // terug naar het oude: de lijsten zijn er
  w.b_schrijft = await als(B, {bewaard: ['b1']});             // nu wel nieuwe staat onder de nieuwe sleutel
  w.reserve_blijft = ls.get(V2) === pakA && ls.has(R);
  w.b_leest = await als(B);
  w.a_terug_na_nieuw = await als(A);                          // de oude sleutel leest zijn eigen vak, niets samengevoegd
  w.b_weer = await als(B);
  await als(A, {bewaard: ['a1', 'a2', 'a4'], verborgen: ['a3']});   // A is nu het nieuwste
  w.c_opent = await als(C, {bewaard: ['c1']});                // derde sleutel: het oudste vak (B) wordt vervangen
  w.c_leest = await als(C);
  w.a_na_c = await als(A);
  w.b_na_c = await als(B);
  w.vakken = [ls.has(V2), ls.has(R), ls.size];
  // een vol of geblokkeerd localStorage tijdens een sleutel die niet past: niets kwijt
  ls.clear(); await als(A, {bewaard: ['a1']});
  const echt = localStorage.setItem; const pakA2 = ls.get(V2);
  localStorage.setItem = () => { throw new Error('vol'); };
  w.vol = await als(B, {bewaard: ['b9']});
  localStorage.setItem = echt;
  w.vol_niets_kwijt = ls.get(V2) === pakA2 && (await als(A)).staat.bewaard[0] === 'a1';
  uit.wissel = w;
  console.log(JSON.stringify(uit));
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_opslag_js() -> bool:
    """De opslag op het apparaat in het echte ui/app.js: leesbaar zonder slotscherm, versleuteld erachter."""
    print("opslag op het apparaat: versleuteld achter het slotscherm, migratie, kapotte inhoud (node)")
    if not shutil.which("node"):
        print("  (node niet gevonden; overgeslagen)")
        return True
    r = subprocess.run(["node", "-e", NODE_OPSLAG, str(HIER / "ui" / "app.js")], capture_output=True, text=True, timeout=60)
    try:
        u = json.loads(r.stdout)
    except ValueError:
        return check("node draait de opslag van app.js", False, r.stderr[-400:])
    v2 = u["migratie"]["v2"] or ""
    pak = json.loads(v2) if v2.startswith("{") else {}
    w, staat_a = u["wissel"], {"bewaard": ["a1", "a2"], "verborgen": ["a3"]}
    leeg_met_melding = [k for k in u["kapot"] + [u["andere_sleutel"]] if k["staat"] == {} and "niet meer te lezen" in k["melding"]]
    return all([
        check("zonder slotscherm: leesbare opslag zoals het was (lokaal rapport)", u["lokaal"]["staat"] == {"bewaard": ["1"]}
              and not u["lokaal"]["melding"] and json.loads(u["lokaal"]["v1"]) == {"bewaard": ["1", "2"]} and not u["lokaal"]["v2"]),
        check("migratie: de leesbare staat ingelezen, zonder melding", u["migratie"]["staat"] == {"bewaard": ["1", "2"]}
              and not u["migratie"]["melding"] and u["migratie"]["v1_voor"]),
        check("migratie: versleuteld opgeslagen en de leesbare versie gewist", not u["migratie"]["v1_na"]
              and set(pak) == {"v", "n", "iv", "ct"} and "bewaard" not in v2, v2[:60]),
        check("IV van 12 bytes; de inhoud opgevuld tot een veelvoud van 512 tekens (plus de tag van 16 bytes)",
              len(base64.b64decode(pak.get("iv", ""))) == 12 and len(base64.b64decode(pak.get("ct", ""))) == 512 + 16
              and isinstance(pak.get("n"), int)),
        check("terug uit de versleutelde opslag", u["terug"] == {"staat": {"bewaard": ["1", "2"]}, "melding": ""}, str(u["terug"])),
        check("20 schrijfacties snel na elkaar: de laatste stand wint, in 2 schrijfacties na elkaar",
              u["snel"]["n"] == 19 and u["snel"]["schrijfacties"] == 2, str(u["snel"])),
        check("elke schrijfactie een verse IV, de lengte blijft gelijk", u["snel"]["iv_nieuw"] and u["snel"]["even_lang"]),
        check("leesbaar naast versleuteld: de versleutelde telt, de leesbare gaat weg", u["beide"] == {"n": 19, "v1": False}, str(u["beide"])),
        check("andere sleutel of kapotte inhoud (5 vormen): lege staat en één korte melding, geen fout",
              len(leeg_met_melding) == 6, str(u["kapot"])[:200]),
        check("daarna schrijft de app gewoon weer, zonder melding", u["na_kapot"] == {"staat": {"bewaard": ["3"]}, "melding": ""}),
        check("slotscherm zonder sleutel: niets geschreven, wel een melding",
              u["zonder_sleutel"]["geschreven"] == 0 and u["zonder_sleutel"]["ongewijzigd"] and "lukt nu niet" in u["zonder_sleutel"]["melding"]),
        check("sleutel die niet past: lege staat met melding, het oude pakket onaangeroerd",
              w["eerste_in_v2"] and w["b_opent"]["staat"] == {} and "niet meer te lezen" in w["b_opent"]["melding"]
              and w["niets_overschreven"], str(w["b_opent"])),
        check("terug naar de oude sleutel zonder nieuwe staat: de lijsten zijn terug, zonder melding",
              w["a_terug_zonder_nieuw"] == {"staat": staat_a, "melding": ""}, str(w["a_terug_zonder_nieuw"])),
        check("nieuwe staat onder de nieuwe sleutel gaat in het andere vak; de reserve blijft staan",
              w["reserve_blijft"] and w["b_leest"] == {"staat": {"bewaard": ["b1"]}, "melding": ""}, str(w["b_leest"])),
        check("daarna terug naar de oude sleutel: zijn eigen staat, niets samengevoegd; de nieuwe blijft ook",
              w["a_terug_na_nieuw"] == {"staat": staat_a, "melding": ""} and w["b_weer"]["staat"] == {"bewaard": ["b1"]},
              str(w["a_terug_na_nieuw"])),
        check("derde sleutel: één reserve, de nieuwste blijft (A), de oudste (B) wordt vervangen",
              w["c_opent"]["staat"] == {} and w["c_leest"]["staat"] == {"bewaard": ["c1"]}
              and w["a_na_c"]["staat"]["bewaard"] == ["a1", "a2", "a4"] and w["b_na_c"]["staat"] == {}
              and "niet meer te lezen" in w["b_na_c"]["melding"] and w["vakken"] == [True, True, 2], str(w["vakken"])),
        check("vol of geblokkeerd localStorage bij een sleutel die niet past: niets kwijt", w["vol_niets_kwijt"]),
    ])


def test_slot() -> bool:
    print("ui/slot.html, ui/slot.js en ui/slot.css")
    gevonden = re.findall(r"__[A-Z_]+__", SLOT)
    nodig = list(funda_ui.SLOT_PLACEHOLDERS)
    waarden = {p: f"<!--{p.strip('_').lower()}-->" for p in nodig}
    gevuld = funda_ui.vul_slot(waarden)
    namen = ["leaflet/leaflet.css", "app.css", "slot.css", "leaflet/leaflet.js", "app.js", "push.js", "slot.js"]
    versies = {n: f"{i:010x}" for i, n in enumerate(namen)}
    met_versie = funda_ui.vul_slot(waarden, versies=versies)
    fout_versie = []
    for kapot in ({k: w for k, w in versies.items() if k != "app.js"}, dict(versies, **{"weg.js": "0" * 10})):
        try:
            funda_ui.vul_slot(waarden, versies=kapot)
            fout_versie.append(False)
        except ValueError:
            fout_versie.append(True)
    try:
        funda_ui.vul_slot({"__CSP__": "x"})
        fout_bij_missen = False
    except ValueError:
        fout_bij_missen = True
    theme = re.search(r'<meta name="theme-color" content="(#[0-9a-fA-F]{6})">', SLOT)
    theme_donker = re.search(r'<meta name="theme-color" media="\(prefers-color-scheme: dark\)" content="(#[0-9a-fA-F]{6})">', SLOT)
    return all([
        check("precies de placeholders, elk één keer", sorted(gevonden) == sorted(nodig), str(gevonden)),
        check("vul_slot vervangt alles", not re.search(r"__[A-Z_]+__", gevuld)),
        check("vul_slot weigert ontbrekende waarden", fout_bij_missen),
        check("vul_slot met versies: elk script en elke stylesheet krijgt ?v=, de rest (manifest, iconen) niet",
              re.findall(r'(?:src|href)="([^"]*\?v=[^"]*)"', met_versie) == [f"{n}?v={versies[n]}" for n in namen]
              and 'href="manifest.json"' in met_versie and 'href="favicon.svg"' in met_versie
              and "?v=" not in gevuld),
        check("vul_slot weigert een bestand zonder versie en een versie zonder bestand", fout_versie == [True, True], str(fout_versie)),
        check("label for=pw", '<label for="pw">' in SLOT),
        check("foutmelding met role=alert", 'role="alert"' in SLOT),
        check("theme-color = THEME_COLOR", bool(theme) and theme.group(1) == funda_ui.THEME_COLOR),
        check("theme-color donker = THEME_COLOR_DONKER, vóór de gewone (eerste match telt)", bool(theme_donker)
              and theme_donker.group(1) == funda_ui.THEME_COLOR_DONKER and theme_donker.start() < theme.start()),
        check("color-scheme light dark", '<meta name="color-scheme" content="light dark">' in SLOT),
        check("geen inline script of style: alleen bestanden en het JSON-pakket", "<style" not in SLOT
              and re.findall(r"<script\b[^>]*>", SLOT) == ['<script defer src="leaflet/leaflet.js">', '<script defer src="app.js">',
                                                         '<script defer src="push.js">', '<script defer src="slot.js">',
                                                         '<script type="application/json" id="slot-data">']),
        check("CSP en no-referrer bovenaan de <head>", SLOT.index("Content-Security-Policy") < SLOT.index('name="referrer"')
              < SLOT.index("<title>")),
        check("slot.js leest het pakket uit #slot-data", 'JSON.parse(document.getElementById("slot-data").textContent)' in SLOT_JS),
        check("slot.css: geen hex buiten de tokens van app.css", not re.search(r"#[0-9a-fA-F]{3,8}\b", SLOT_CSS.replace("#content", ""))),
        check("knop Vergeet dit apparaat", ">Vergeet dit apparaat</button>" in SLOT and "window.fundaApparaat" in SLOT_JS),
        check("terugval met melding", "Onthouden lukt niet in deze browser." in SLOT_JS),
        check("geen merknaam of voornaam", "Funda Shortlist" not in SLOT and "<title>Woningrapport</title>" in SLOT),
        # 14 kB plus de pauze na foute pogingen (16 kB), plus de afgeleide sleutel voor de opslag van de app (17 kB)
        check("slotscherm (html, css en js) <= 17 kB", len((SLOT + SLOT_CSS + SLOT_JS).encode()) <= 17_000,
              f"{len((SLOT + SLOT_CSS + SLOT_JS).encode())} bytes"),
    ])


def test_veilige_uitvoer() -> bool:
    print("JSON in het script-blok, funda-links, externe links")
    rijen, meta = testrijen()
    rijen = copy.deepcopy(rijen)
    naar = "Teststraat 1 <!--<script>alert(1)</script> & </script"
    rijen[0]["d"]["title"] = naar
    body = funda_ui.render_report_body(rijen, meta)
    blok = re.search(r'<script type="application/json" id="woning-data">(.*?)</script>', body, re.S).group(1)
    data = json.loads(blok)
    url = funda_ui.funda_url
    gevallen = {
        "/detail/koop/den-haag/appartement-teststraat-1/43000001/": "https://www.funda.nl/detail/koop/den-haag/appartement-teststraat-1/43000001/",
        "detail/koop/x/": "https://www.funda.nl/detail/koop/x/",
        "https://www.funda.nl/detail/43000001/": "https://www.funda.nl/detail/43000001/",
        "http://www.funda.nl/detail/43000001/": "https://www.funda.nl/detail/43000001/",
        "https://www.funda.nl.example.invalid/x": "", "https://example.invalid/https://www.funda.nl/": "",
        "https://www.funda.nl@example.invalid/": "", "https://www.funda.nl\\@example.invalid/": "",
        "https://www.funda.nl:8443/x": "", "https://funda.nl/x": "", "//example.invalid/x": "",
        "javascript:alert(1)": "", "JaVaScRiPt:alert(1)": "", "data:text/html,x": "", "/detail/a b": "", "": "",
    }
    fout = {k: url({"url": k}) for k, v in gevallen.items() if url({"url": k}) != v}
    kwaad = funda_ui.render_report_body([{"d": {"global_id": 9, "title": "Woning", "price": 250000, "url": "javascript:alert(1)"}}], {})
    links = re.findall(r'<a\b[^>]*target="_blank"[^>]*>', body)
    return all([
        check("woning-data: geen <, > of & letterlijk", not re.search(r"[<>&]", blok), blok[:80]),
        check("woning-data: nog steeds dezelfde titel na JSON.parse", any(w["titel"] == naar for w in data["woningen"])),
        check("de titel staat ge-escaped in de kaart", "&lt;!--&lt;script&gt;alert(1)" in body and "<!--<script>" not in body),
        check("funda_url: alleen https://www.funda.nl/..., een pad krijgt de host, de rest valt weg", not fout, str(fout)),
        check("funda_url: geen tekst = geen link", url({"url": 5}) == "" and url({}) == ""),
        check("funda_url: detail_url gaat voor url", url({"detail_url": "/a/", "url": "/b/"}) == "https://www.funda.nl/a/"),
        check("woning met een vreemde link: geen knop naar funda", "javascript:" not in kwaad and "Bekijk op funda" not in kwaad),
        check("externe links: rel noopener noreferrer", len(links) >= 13 and all('rel="noopener noreferrer"' in a for a in links),
              str(len(links))),
        check("vergrendelknop in Dit apparaat", 'data-actie="vergrendel"' in body and "> Vergrendel</button>" in body
              and '[data-actie="vergrendel"]' in JS and "a.vergrendel()" in JS),
    ])


def test_groottes() -> bool:
    print("groottes")
    body = _body()
    per_woning = len(body.encode()) / 13
    return all([
        # 40 en 23 kB plus de audit van nov 2026: labels bij de iconknoppen, vervaging van de snelfilters, sluitknop op de toast
        check("ui/app.css <= 42 kB", len(CSS.encode()) <= 42_000, f"{len(CSS.encode())} bytes"),
        # Was 24 kB. Erbij (nov 2026): de versleutelde opslag op het apparaat met migratie, en het vlak "Toon kaart".
        # Was 30 kB. Erbij (19 nov 2026, 1 kB): het tweede vak, zodat een sleutel die niet past niets overschrijft.
        check("ui/app.js <= 31 kB", len(JS.encode()) <= 31_000, f"{len(JS.encode())} bytes"),
        check("body <= 14 kB per woning", per_woning <= 14_000, f"{per_woning:.0f} bytes per woning"),
    ])


def test_tekst() -> bool:
    print("tekst: geen em dash of gedachtestreepje, geen bevolkingskenmerken")
    body = _body()
    bronnen = {"body": body, "app.css": CSS, "app.js": JS, "slot": SLOT_ALLES,
               "funda_ui.py": (HIER / "funda_ui.py").read_text(encoding="utf-8")}
    streep = [n for n, t in bronnen.items() if "—" in t or "–" in t]
    return all([
        check("geen em dash of gedachtestreepje", not streep, str(streep)),
        check("geen bevolkingskenmerken in de body", not any(w in body.lower() for w in BEVOLKING)),
        check("€ met spatie, geen €-bedrag zonder spatie", not re.search(r"€\d", body)),
        check("m² en geen m2 in zichtbare tekst", " m2 " not in body),
    ])


def test_omgeving_blok() -> bool:
    """Informatieve items uit de open bronnen (18 nov 2026): een eigen uitklapblok per kaart, zonder punten."""
    print("omgeving: blok 'Buurt en omgeving' met de items uit de open bronnen")
    import funda_beoordeling as fb
    rijen, meta = testrijen()
    verrijking = {"lucht": {"status": "ok", "data": {"no2": 18.3, "pm25": 8.7, "groen_pct": 16}},
                  "veiligheid": {"status": "ok", "data": {"jaar": 2025, "misdrijven_per_1000": 498.2, "gem_misdrijven_per_1000": 146.5}},
                  "klimaat": {"status": "ok", "data": {"wateroverlast": "zeer hoog", "waterdiepte": "meer dan 30 cm"}},
                  "buurt": {"status": "ok", "data": {"buurtnaam": "Voorbeeld<b>buurt-Noord en omgeving van het park", "kscore": 7}}}
    items = fb.omgeving_items(verrijking)
    b = rijen[0]["beoordeling"]
    b["info"] = list(b.get("info") or []) + [i for i in items if i["groep"] == "info"] + [
        fb._item("prijsverloop", "neutraal", "Eerder zonder prijs", "gezien op 12 okt 2026", "eigen waarneming", uitleg="<b>uitleg</b>")]
    b["info"] += fb.binnenklimaat({}, {"Isolatie": "Geen isolatie"}, "Slaapkamer onder de kap.", None, None, "G", "G", 1930)
    b["let_op"] = list(b.get("let_op") or []) + [i for i in items if i["groep"] == "let_op"]
    body = funda_ui.render_report_body(rijen, meta)
    sleutel = funda_ui.woning_sleutel(rijen[0]["d"])
    kaart = _kaart(body, sleutel)
    m = re.search(r'<details class="opbouw omgeving">(.*?)</details>', kaart, re.S)
    blok = m.group(1) if m else ""
    mw = re.search(r'<section class="blok"><h4>Woning</h4>(.*?)</section>', kaart, re.S)
    woning = mw.group(1) if mw else ""
    n_info = len([i for i in b["info"] if i["onderdeel"] in fb.INFO_TONEN])
    andere = _kaart(body, funda_ui.woning_sleutel(rijen[1]["d"]))
    ok = [
        check("de kop noemt de buurt waarvoor de cijfers gelden, ge-escaped",
              "Buurt en omgeving: Voorbeeld&lt;b&gt;buurt-Noord en omgeving van het park <span" in blok
              and "Voorbeeld<b>buurt" not in kaart, blok[:160]),
        check("blok aanwezig met het aantal cijfers (de buurtnaam zelf telt niet mee)",
              "Buurt en omgeving" in blok and f'<span class="waarde">{n_info - 1}</span>' in blok, blok[:200]),
        check("items met label, waarde, bron en uitleg",
              all(t in blok for t in ("Stikstofdioxide (NO2)", "18,3 µg/m³, boven WHO-advies", "RIVM 2024", "WHO-advies 10",
                                      "Misdrijven buurt", "498 per 1.000 (gemeente 146)"))),
        check("'Eerder zonder prijs' gaat over de woning: in het blok Woning, niet onder Buurt en omgeving",
              "<b>Eerder zonder prijs</b>: gezien op 12 okt 2026" in woning and "Eerder zonder prijs" not in blok
              and "Telt niet mee in de score" in woning and 'class="pt ' not in woning
              and "prijsverloop" in fb.INFO_WONING and "prijsverloop" not in fb.INFO_TONEN, woning[-600:]),
        check("geen punten in het blok, wel de zin dat het niet meetelt", 'class="pt ' not in blok and "Telt nog niet mee in de score" in blok),
        check("uitleg wordt ge-escaped", "&lt;b&gt;uitleg&lt;/b&gt;" in woning and "<b>uitleg</b>" not in kaart),
        check("overige neutrale items (leenruimte en dergelijke) staan niet in het blok", "Leenruimte" not in blok and "Woonoppervlak" not in blok),
        check("een 'let op' uit een open bron staat bij Let op, zonder punten", "Wateroverlast bij bui" in kaart and "Wateroverlast bij bui" not in blok),
        check("kaart zonder zulke items: geen blok", "opbouw omgeving" not in andere and "opbouw binnenklimaat" not in andere),
        check("bron in gewone taal (audit schrijfstijl, nov 2026)", "eerder gezien door dit rapport" in woning and "eigen waarneming" not in kaart
              and funda_ui.bron_tekst("kenmerk 'Gelegen op'") == "advertentie, bij Gelegen op"
              and funda_ui.bron_tekst("berekening") == "zelf berekend" and funda_ui.bron_tekst("CBS 2024") == "CBS 2024"),
        check("binnenklimaat: zomer en winter in het blok Woning, als indicatie en zonder punten", (lambda k: bool(k)
              and "Warmte en kou in huis" in k.group(1) and "<b>Zomer</b>: kans op warmte: 2 aanwijzingen" in k.group(1)
              and "<b>Winter</b>: kans op kou" in k.group(1) and "niet gemeten" in k.group(1) and "Telt niet mee in de score" in k.group(1) and 'class="pt ' not in k.group(1)
              and "Zomer" not in blok)(re.search(r'<details class="opbouw binnenklimaat">(.*?)</details>', kaart, re.S))),
        check("CSS: binnenmarge voor de lijst in het uitklapblok", ".opbouw>.punten" in CSS),
    ]
    return all(ok)


def test_fixronde_ui() -> bool:
    """Fixronde na de review: sheet, randen, hover, topbalk, kaart, sortering, teksten."""
    print("fixronde: sheet, randen, hover, sortering en teksten")
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

    def regel(sel):
        m = re.search(r"(?:^|})\s*" + re.escape(sel) + r"\{([^}]*)\}", css, re.M)
        return m.group(1) if m else ""

    hover_buiten = [m.group(0).strip() for m in re.finditer(r"[^{}]*:hover[^{]*\{", css)
                    if "@media" not in m.group(0) and "@media (hover:hover)" not in css[max(0, m.start() - 400):m.start()]]
    body = _body()
    rijen, meta = testrijen()
    kaart105 = _kaart(body, "7990105")
    w = funda_ui._woning(rijen[0], meta)
    w["onderdelen"] = {"a": {"punten": -0.5, "kort": "erfpachtcanon"}, "b": {"punten": -0.45, "kort": "woonlasten"},
                       "c": {"punten": 0.55, "kort": "balkon"}}
    balk = re.findall(r'class="b[pm] b(\d+)"', funda_ui.opbouw_score(w))
    ok = [
        check("sheet: formulier is een flex-kolom, alleen de body scrollt",
              "display:flex" in regel(".sheet>form") and "min-height:0" in regel(".sheet>form")
              and "min-height:0" in regel(".sheet-body") and "overflow:auto" in regel(".sheet-body")),
        check("chip, tertiaire knop, onderknop en wissel: rand uit interactive-neutral (3:1)",
              all("border-color-interactive-neutral" in regel(sel) for sel in (".chip", ".knop-ter", ".onderknop", ".wissel"))),
        check("hover alleen binnen @media (hover:hover)", not hover_buiten, str(hover_buiten[:3])),
        check("topbalk-ondertitel op één regel", "white-space:nowrap" in regel(".app-top p")
              and "text-overflow:ellipsis" in regel(".app-top p")),
        check("kaartlegenda boven de bronvermelding", "bottom:calc(var(--spacing-150) + 1.5rem)" in regel(".kaart-legenda")),
        check("pins: beste woning bovenop (zIndexOffset op poort en score)",
              "zIndexOffset:(3 - POORT_RANG[w.poort]) * 1000 + Math.round((w.score || 0) * 10)" in JS),
        check("nieuw: top- en onderbalk tellen niet als in beeld (rootMargin)",
              "rootMargin: balkMarge()" in JS and "'.app-top'" in JS and "'.app-onder'" in JS),
        check("geen 'Navragen:' voor een vraag die zelf al een zin is", "Navragen:" not in body),
        check("Ook in orde: label: waarde, gescheiden met ·",
              "Energielabel: A · Grond: eigen grond" in _kaart(body, "7990113") or "Ook in orde: " not in body,
              re.search(r"Ook in orde: </span>([^<]*)", body).group(1)[:80] if "Ook in orde" in body else ""),
        check("WOZ-peildatum lang geschreven", "(peildatum 1 januari 2026)" in body and "jan, 2026" not in body),
        check("euroteken met harde spatie in de HTML (de JSON-data rendert app.js via esc())",
              "€ " not in body.split('id="woning-data"')[0] and "€\u00a0" in body),
        check("eur_tekst houdt een gewone spatie (markdown, push)", funda_ui.eur_tekst(1250) == "€ 1.250"),
        check("eur_vast is weg (eur heeft al een harde spatie)", not hasattr(funda_ui, "eur_vast")),
        check("scorebalk: −0,5 en −0,5 (afgerond) even breed, half naar boven",
              len(balk) == 3 and balk[1] == balk[2] == "3" and balk[0] == "3", str(balk)),
        check("placeholder 'Woonlasten tot' uit je grens, zonder grens geen getal",
              re.search(r'id="f-maxlasten"[^>]* placeholder="bijvoorbeeld 1450">', body) is not None
              and re.search(r'id="f-maxlasten"[^>]*>', funda_ui.render_report_body(
                  [{"d": {"global_id": 1, "price": 1}}], {})).group(0).count("placeholder") == 0),
        check("twijfeluitleg dekt leefbaarheid", "(buurt, stad of leefbaarheid onduidelijk)" in body),
        check("vergelijking: Status (poort) en Financiering (scenario), netto per maand en minuten fietsen",
              "['Status'," in JS and "['Financiering'," in JS and "' netto per maand'" in JS and "w.reis_min + ' min'" in JS and "≈" not in JS
              and "'Wanneer'" not in JS),
        check("popup: scenario met label Financiering", "'<br>Financiering: ' + esc(finTekst(w.scenario_tekst))" in JS),
        check("JS: euroteken met harde spatie", "'€\\u00a0'" in JS and "replace(/€ /g, '€\\u00a0')" in JS),
        check("één woord: apparaat (geen toestel)", all("toestel" not in t for t in (body, JS, SLOT_ALLES))),
        check("slot: fout direct onder het wachtwoordveld", SLOT.index('id="err"') < SLOT.index('id="remember"')
              and SLOT.index('id="err"') > SLOT.index('class="pw-rij"')),
        check("slot: onthouden sleutel, geen onthouden wachtwoord", "Het onthouden wachtwoord" not in SLOT_ALLES
              and "De onthouden sleutel werkt niet meer. Vul je wachtwoord opnieuw in." in SLOT_JS),
        check("WOZ zonder datum: geen peildatum", "peildatum" not in funda_ui.kenmerken(
            dict(w, woz={"price": 200000, "date": "1 jan, 2026"}))),
    ]
    ok.append(test_sortering_js())
    return all(ok)


def test_sortering_js() -> bool:
    """Prijs onbekend achteraan bij elke sortering, in het echte app.js (node, zonder DOM). Zonder node: broncheck."""
    data = _woning_data(_body())["woningen"]
    sleutels = ["aanbevolen", "score", "woonlasten", "prijs", "reis", "nieuwst"]
    if not shutil.which("node"):
        return check("SORT via onbekendAchter (node ontbreekt, alleen broncheck)",
                     "Object.keys(SORT).forEach(function(k){ SORT[k] = onbekendAchter(SORT[k]); });" in JS)
    script = ("global.window={};global.document={readyState:'loading',addEventListener(){}};"
              f"require({json.dumps(str(HIER / 'ui' / 'app.js'))});"
              "const ws=JSON.parse(require('fs').readFileSync(0,'utf8'));const uit={};"
              f"for(const k of {json.dumps(sleutels)}) uit[k]=window.fundaRapportSorteer(ws,k).map(w=>w.poort);"
              "console.log(JSON.stringify(uit));")
    r = subprocess.run(["node", "-e", script], input=json.dumps(data), capture_output=True, text=True, timeout=30)
    try:
        uit = json.loads(r.stdout)
    except ValueError:
        return check("node draait app.js", False, r.stderr[:200])
    fout = {k: v.index("PRIJS ONBEKEND") for k, v in uit.items() if "PRIJS ONBEKEND" in v and v[-1] != "PRIJS ONBEKEND"}
    return check(f"prijs onbekend achteraan bij alle {len(uit)} sorteringen (node)", len(uit) == 6 and not fout
                 and all("PRIJS ONBEKEND" in v for v in uit.values()), str(fout))


def _node_app(script_body: str, invoer) -> tuple[object, str]:
    """Draai het echte ui/app.js in node zonder DOM; script_body leest `ws` en zet `uit`."""
    script = ("global.window={};global.document={readyState:'loading',addEventListener(){}};"
              f"require({json.dumps(str(HIER / 'ui' / 'app.js'))});"
              "const ws=JSON.parse(require('fs').readFileSync(0,'utf8'));let uit=null;"
              + script_body + "console.log(JSON.stringify(uit));")
    r = subprocess.run(["node", "-e", script], input=json.dumps(invoer), capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout), ""
    except ValueError:
        return None, r.stderr[-300:]


def test_eindreview_js() -> bool:
    """Eindreview: zonder vraagprijs achteraan, ook op PAST NIET (veiling); de vergelijking zonder
    'Financiering: onbekend' als er geen scenario's zijn (secret zonder 'financien')."""
    print("test: eindreview in app.js (prijs ontbreekt achteraan, vergelijking zonder 'onbekend')")
    if not shutil.which("node"):
        print("  (node niet gevonden; overgeslagen)")
        return True
    ws = _woning_data(_body())["woningen"]
    basis = next(w for w in ws if w.get("prijs"))
    veiling = dict(basis, id="veiling", card_id="veiling", poort="PAST NIET", prijs=None, netto=None, score=9.9,
                   twijfel=[], dagen=0, reis_min=1, status_kort="Past niet · veiling, geen financieringsvoorbehoud")
    lijst = ws + [veiling]
    sleutels = ["aanbevolen", "score", "woonlasten", "prijs", "reis", "nieuwst"]
    uit, fout = _node_app(f"uit={{}};for(const k of {json.dumps(sleutels)}) "
                          "uit[k]=window.fundaRapportSorteer(ws,k).map(w=>w.prijs==null);", lijst)
    if uit is None:
        return check("node draait app.js", False, fout)
    # Na de eerste woning zonder prijs geen woning met prijs meer.
    mis = {k: v for k, v in uit.items() if True in v and not all(v[v.index(True):])}
    ok = check(f"zonder vraagprijs achteraan bij alle {len(uit)} sorteringen, ook PAST NIET (node)",
               len(uit) == 6 and not mis, str({k: v.index(True) for k, v in mis.items()}))

    def kaal(**kw):
        return dict(basis, **kw)
    zonder = [kaal(id="a", poort="PAST", status_kort="Past · € 196 onder je grens", scenario_tekst=None),
              kaal(id="b", poort="PAST NIET", status_kort="Past niet · € 9.860 eigen geld te weinig", scenario_tekst=None)]
    gemengd = [kaal(id="c", poort="KRAP", status_kort="Krap · € 12 boven je grens", scenario_tekst="Past vanaf jaar X"),
               kaal(id="d", poort="PRIJS ONBEKEND", prijs=None, netto=None, scenario_tekst=None,
                    status_kort="Prijs onbekend · geen vraagprijs, dus geen leentoets")]
    uit, fout = _node_app("uit=ws.map(l=>window.fundaRapportVergelijk(l));", [zonder, gemengd])
    if uit is None:
        return check("node: window.fundaRapportVergelijk", False, fout)
    rij = '<th scope="row">Financiering</th>'

    def cellen(html):
        if rij not in html:
            return None
        stuk = html.split(rij, 1)[1].split("</tr>", 1)[0]
        return re.findall(r"<td[^>]*>(.*?)</td>", stuk)
    ok &= check("zonder scenario's: geen rij Financiering", rij not in uit[0], str(cellen(uit[0])))
    ok &= check("gemengd: scenario en anders het poortwoord, nooit 'onbekend'",
                cellen(uit[1]) == ["past vanaf jaar X", "Prijs onbekend"], str(cellen(uit[1])))
    ok &= check("status blijft in de vergelijking", '<th scope="row">Status</th>' in uit[0])
    return ok


def test_geen_merknaam() -> bool:
    print("test: geen merk- of fontnaam van derden in een bijgehouden bestand")
    import subprocess
    try:
        namen = subprocess.run(["git", "ls-files"], cwd=HIER, capture_output=True, text=True, check=True).stdout.split("\n")
    except Exception:
        print("  (overgeslagen: geen git)")
        return True
    fout = []
    for naam in filter(None, namen):
        pad = HIER / naam
        if not pad.is_file():
            continue
        tekst = pad.read_bytes().decode("utf-8", "ignore").lower()
        fout += [naam for m in MERKNAMEN if re.search(r"(?<![a-z])" + re.escape(m.lower()) + r"(?![a-z])", tekst)]
    return check("geen enkel bestand noemt een van de namen", not fout, str(sorted(set(fout))[:8]))


def main() -> int:
    resultaten = [test_geen_merknaam(), test_contract_testdata(), test_ids_en_attributen(), test_statusregels(), test_status_en_scenario_in_kaart(),
                  test_prijs_onbekend(), test_volgorde(), test_woning_data(), test_css_regels(), test_contrast(),
                  test_rente_en_budget(), test_meta_en_randgevallen(), test_app_js(), test_opslag_js(), test_slot(), test_veilige_uitvoer(), test_groottes(), test_tekst(),
                  test_fixronde_ui(), test_eindreview_js(), test_omgeving_blok()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
