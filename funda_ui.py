"""Woningrapport: de UI (lijst, woningkaarten, sheets, kaart en voet) uit het beoordelingscontract.

Geen netwerk en geen import van funda_rapport (geen kringimport); constanten komen via `meta`.
CSS, JS en het slotscherm staan als gewone bestanden in ui/, zodat ze geen Python-escapes nodig
hebben (in een gewone Python-string wordt content:"\\2212" een octale escape).

Publieke API
  THEME_COLOR, ACHTERGROND     kleur van de topbalk en van de pagina (licht), voor manifest en theme-color
  UI_CSS, UI_JS, SLOT_HTML     inhoud van ui/app.css, ui/app.js en ui/slot.html
  SLOT_PLACEHOLDERS            de placeholders die ui/slot.html precies één keer bevat
  render_report_body(rijen, meta) -> str
                               de body: sprite, topbalk, lijst, voet, kaart, sheets en #woning-data
  vul_slot(waarden) -> str     ui/slot.html met alle placeholders vervangen (waarden per placeholdernaam)

Rij (per woning, zoals funda_rapport.bouw_rij hem maakt):
  beoordeling   contract uit beoordeling.md paragraaf 9, plus financiering.scenarios/planning/scenario_tekst
  d             zoekresultaat: global_id, title, neighbourhood, city, price, living_area, rooms, energy_label,
                url of detail_url, en _enrichment.price_history.latest_woz (WOZ met datum)
  details       detail-antwoord: characteristics, photo_urls, construction_year, offered_since (valt terug op d)
  routes        [{"label", "km"}] per werkadres; lat, lon; foto_url; is_nieuw; track (gedaald, eerdere_prijs, dagen)

Meta (alles optioneel):
  tijdstip          datetime met tijdzone (of ISO-tekst); standaard nu in Europe/Amsterdam
  actions_url       knop Nieuwe run (GitHub Actions "Run workflow")
  rente             dict van funda_rente.huidige_rente: pct (procent, 4.11), bron, datum, oud, melding
  fiets_kmu         fietssnelheid voor de fietstijd (standaard 15)
  push_beschikbaar  er is een Web Push-sleutel: toon "Meldingen op deze iPhone"
  push_ingesteld    er is al een abonnement: verberg dat blok
  scenarios         [{"id", "label", "max_koopsom"}] voor "Jouw budget"; anders afgeleid uit de rijen
  budget_regels     extra [label, tekst]-paren voor "Jouw budget" (nooit inkomen)
  kk_onzekerheid, eigen_geld_tekort_past_niet, lang_op_funda_dagen, run_cron_utc, leentoets_jaar
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_CSS = (UI_DIR / "app.css").read_text(encoding="utf-8")
UI_JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
SLOT_HTML = (UI_DIR / "slot.html").read_text(encoding="utf-8")
SLOT_PLACEHOLDERS = ("__APP_CSS__", "__MAP_HEAD__", "__APP_SCRIPTS__", "__GZ__", "__SALT__", "__IV__", "__CT__", "__ITERS__")

# Palet "Lavendel" (ui/app.css): topbalk en pagina in licht. Voor het manifest en <meta name="theme-color">.
THEME_COLOR = "#2e1f6b"
ACHTERGROND = "#f4f5f8"

AMS = ZoneInfo("Europe/Amsterdam")
RUN_CRON_UTC = [(8, 30), (16, 30)]   # .github/workflows/funda-daily.yml
FIETS_KMU = 15
KK_ONZEKERHEID = 1500
TEKORT_PAST_NIET = 5000
LANG_OP_FUNDA_DAGEN = 90
MAX_FOTOS = 6
OVERIG_STANDAARD = 160
VVE_STANDAARD = 175

POORTEN = ("PAST", "KRAP", "PAST NIET", "PRIJS ONBEKEND")
POORT_RANG = {p: i for i, p in enumerate(POORTEN)}
POORT_CLS = {"PAST": "PAST", "KRAP": "KRAP", "PAST NIET": "NIET", "PRIJS ONBEKEND": "ONBEKEND"}
POORT_IC = {"PAST": "check", "KRAP": "warn", "PAST NIET": "x", "PRIJS ONBEKEND": "info"}
POORT_NAAM = {"PAST": "Past", "KRAP": "Krap", "PAST NIET": "Past niet", "PRIJS ONBEKEND": "Prijs onbekend"}
OORDEEL_IC = {"sterk": "x", "let_op": "warn", "goed": "check", "onbekend": "vraag", "kans": "kans", "neutraal": "info"}
OORDEEL_TEKST = {"sterk": "sterk let op", "let_op": "let op", "goed": "goed", "onbekend": "onbekend", "kans": "kans",
                 "neutraal": "informatie"}
GROEP_UITLEG = {"PAST": "", "KRAP": "Woonlasten net boven je grens of eigen geld krap.",
                "PAST NIET": "Te weinig leenruimte of eigen geld, of woonlasten ruim boven je grens.",
                "PRIJS ONBEKEND": "Geen vraagprijs, dus geen leentoets."}
RENTE_BRON = {"handmatig": "handmatig ingesteld", "ASN": "ASN Bank", "DNB": "DNB, rente op nieuwe hypotheken",
              "standaard": "standaardwaarde uit de code"}
MAAND_KORT = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
MAAND_LANG = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
              "november", "december"]


# ── opmaak: één notatie (€ 1.250, m², decimale komma, minteken U+2212) ──────────
def h(s) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def nl(n) -> str:
    return f"{round(n):,}".replace(",", ".")


def eur(n) -> str:
    return "€ " + nl(n)


def eur_vast(n) -> str:
    """Bedrag dat niet tussen € en het getal afbreekt (harde spatie), voor smalle kolommen."""
    return "€ " + nl(n)


def komma(x, d=1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def punten(p) -> str:
    if abs(p) < 0.05:
        return "0"
    return ("+" if p > 0 else "−") + komma(abs(p))


def datum_kort(d: date) -> str:
    return f"{d.day} {MAAND_KORT[d.month - 1]}"


def datum_lang(d: date) -> str:
    return f"{d.day} {MAAND_LANG[d.month - 1]} {d.year}"


def ic(naam, cls="ic", label=None) -> str:
    aria = f' role="img" aria-label="{h(label)}"' if label else ' aria-hidden="true" focusable="false"'
    return f'<svg class="{cls}"{aria}><use href="#i-{naam}"/></svg>'


# Eigen iconen: lijnstijl 2 px, 24 x 24, stroke currentColor.
SPRITE = """<svg class="sprite" aria-hidden="true" focusable="false">
<symbol id="i-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16.5 9.5"/></symbol>
<symbol id="i-warn" viewBox="0 0 24 24"><path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.2v.1"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.1"/></symbol>
<symbol id="i-vraag" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6M12 17v.1"/></symbol>
<symbol id="i-kans" viewBox="0 0 24 24"><path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.2"/></symbol>
<symbol id="i-ster" viewBox="0 0 24 24"><path d="m12 3 2.8 5.8 6.2.9-4.5 4.4 1.1 6.2L12 17.4l-5.6 2.9 1.1-6.2L3 9.7l6.2-.9z"/></symbol>
<symbol id="i-fiets" viewBox="0 0 24 24"><circle cx="5.5" cy="16.5" r="3.5"/><circle cx="18.5" cy="16.5" r="3.5"/><path d="M5.5 16.5 9 9h6l3.5 7.5M9 9 12 16.5 15 9M8 6h3"/></symbol>
<symbol id="i-kaart" viewBox="0 0 24 24"><path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/></symbol>
<symbol id="i-lijst" viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.1M3.5 12h.1M3.5 18h.1"/></symbol>
<symbol id="i-filter" viewBox="0 0 24 24"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
<symbol id="i-vernieuw" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></symbol>
<symbol id="i-extern" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v6H4V6h6"/></symbol>
<symbol id="i-huis" viewBox="0 0 24 24"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/></symbol>
<symbol id="i-vergelijk" viewBox="0 0 24 24"><rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/></symbol>
<symbol id="i-sluit" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></symbol>
<symbol id="i-bel" viewBox="0 0 24 24"><path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/></symbol>
<symbol id="i-oog" viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.6 6.1A10 10 0 0 1 12 6c5 0 9 6 9 6a17 17 0 0 1-2.6 3.2M6.4 7.6A16 16 0 0 0 3 12s4 6 9 6a9 9 0 0 0 3.5-.7"/></symbol>
</svg>"""


# ── data ─────────────────────────────────────────────────────────────────────
def woning_sleutel(d: dict) -> str:
    """Zelfde sleutel als funda_rapport.woning_sleutel (global_id eerst), zonder die module te importeren."""
    return str(d.get("global_id") or d.get("listing_id") or d.get("detail_url") or d.get("title") or "")


def card_id(sleutel: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", sleutel).strip("-") or "woning"


def _url(d: dict) -> str:
    url = d.get("detail_url") or d.get("url") or ""
    if url and not url.startswith("http"):
        url = "https://www.funda.nl" + url
    return url


def _getal(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _tijdstip(meta: dict) -> datetime:
    t = meta.get("tijdstip")
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    if not isinstance(t, datetime):
        return datetime.now(AMS)
    return (t if t.tzinfo else t.replace(tzinfo=AMS)).astimezone(AMS)


def fiets_min(km, kmu=FIETS_KMU) -> int:
    return max(1, round(km / (kmu or FIETS_KMU) * 60))


def _zin(t: str) -> str:
    t = str(t).strip()
    return t if t.endswith((".", "?", "!")) else t + "."


def _woning(rij: dict, meta: dict) -> dict:
    """Alles wat de kaart nodig heeft, uit één rij. Rekent niets uit behalve presentatie."""
    d = rij.get("d") or {}
    det = rij.get("details") or {}
    b = rij.get("beoordeling") or {}
    f = b.get("financiering") or {}
    track = rij.get("track") or d.get("_track") or {}
    ch = det.get("characteristics") or d.get("characteristics") or {}
    prijs = _getal(d.get("price"))
    prijs = prijs if prijs and prijs > 0 else None
    label = d.get("energy_label") or det.get("energy_label")
    label = None if label in (None, "", "?", "unknown") else label
    kmu = meta.get("fiets_kmu") or FIETS_KMU
    routes = [{"label": r.get("label") or "", "km": r["km"], "min": fiets_min(r["km"], kmu)}
              for r in (rij.get("routes") or []) if _getal(r.get("km")) is not None]
    fotos = [u for u in (det.get("photo_urls") or d.get("photo_urls") or []) if isinstance(u, str) and u][:MAX_FOTOS]
    kansen = b.get("kansen") or []
    lang_dagen = meta.get("lang_op_funda_dagen") or LANG_OP_FUNDA_DAGEN
    lang = next((k for k in kansen if str(k.get("label", "")).startswith("Lang")), None)
    if not lang and (_getal(track.get("dagen")) or 0) >= lang_dagen:
        lang = {"label": "Lang te koop", "waarde": f"{track['dagen']} dagen"}
    poort = b.get("poort") if b.get("poort") in POORT_RANG else ("PRIJS ONBEKEND" if prijs is None else "KRAP")
    sleutel = woning_sleutel(d)
    hist = ((d.get("_enrichment") or {}).get("price_history") or {})
    w = {
        "id": sleutel, "titel": d.get("title") or det.get("title") or "Woning", "buurt": d.get("neighbourhood") or "",
        "stad": d.get("city") or "", "prijs": prijs, "m2": _getal(d.get("living_area")) or _getal(det.get("living_area")),
        "kamers": d.get("rooms") or det.get("rooms"), "label": label,
        "bouwjaar": det.get("construction_year") or d.get("construction_year"), "url": _url(d) or _url(det),
        "nieuw_run": bool(rij.get("is_nieuw")), "gedaald": bool(track.get("gedaald")),
        "eerdere_prijs": _getal(track.get("eerdere_prijs")), "dagen": _getal(track.get("dagen")), "lang": lang,
        "poort": poort, "twijfel": [_zin(t) for t in (b.get("twijfel") or []) if str(t).strip()],
        "score": _getal(b.get("score")) or 0.0, "onderdelen": b.get("onderdelen") or {},
        "let_op": b.get("let_op") or [], "plus": b.get("pluspunten") or [], "onbekend": b.get("onbekend") or [],
        "kansen": kansen, "zelf": (b.get("zelf_nagaan") or [])[:6], "fin": f, "routes": routes,
        "foto": rij.get("foto_url"), "fotos": fotos, "lat": _getal(rij.get("lat")), "lon": _getal(rij.get("lon")),
        "ch": ch, "woz": hist.get("latest_woz"), "aangeboden": det.get("offered_since") or d.get("offered_since"),
        "scenario_tekst": f.get("scenario_tekst"), "beoordeeld": bool(b),
    }
    kort = b.get("status_kort")
    if not kort:
        kort = f"{POORT_NAAM[poort]} · " + (status_reden(poort, f, meta) if b else "geen beoordeling, ga het zelf na")
    naam, _, reden = kort.partition(" · ")
    w["status_kort"] = kort
    w["status_html"] = f"<strong>{h(naam)}</strong>" + (f" · {h(reden)}" if reden else "")
    return w


def status_reden(poort: str, fin: dict, meta: dict | None = None) -> str:
    """Eén reden met het bedrag dat de poort bepaalt (spec.md 4.2). Eigen geld gaat voor als dat de poort zet."""
    meta = meta or {}
    kk = meta.get("kk_onzekerheid", KK_ONZEKERHEID)
    te_weinig = meta.get("eigen_geld_tekort_past_niet", TEKORT_PAST_NIET)
    if poort == "PRIJS ONBEKEND":
        return "geen vraagprijs, dus geen leentoets"
    bruto_norm = fin.get("grens_soort") == "bruto norm"
    lasten = fin.get("bruto") if bruto_norm else fin.get("netto")
    grens, tekort = fin.get("grens"), fin.get("tekort") or 0
    if lasten is None or grens is None:
        return f"{eur(tekort)} eigen geld te weinig" if tekort > 0 else "woonlasten onbekend"
    if (poort == "PAST NIET" and tekort > te_weinig) or (poort == "KRAP" and tekort > kk and lasten <= grens):
        return f"{eur(tekort)} eigen geld te weinig"
    if lasten <= grens:
        return f"{eur(grens - lasten)} onder " + ("de norm (bruto)" if bruto_norm else "je grens")
    return f"{eur(lasten - grens)} boven " + ("de norm (bruto)" if bruto_norm else "je grens")


def status_tekst(poort: str, fin: dict, meta: dict | None = None) -> str:
    """De korte statusregel zoals markdown, push, kaartpopup en vergelijking hem tonen."""
    return f"{POORT_NAAM[poort]} · {status_reden(poort, fin, meta)}"


def kort_tekst(naam, v) -> str:
    if naam == "woonlasten":  # het bedrag staat al in de kerncijfers
        return "lage woonlasten" if v["punten"] > 0 else "hoge woonlasten"
    return v.get("kort") or naam


def redenen_kort(w) -> list[tuple[float, str]]:
    """Hooguit 3 onderdelen: eerst onderdelen met een 'sterk' Let op, dan op absolute punten (minimaal 0,25)."""
    sterk = {}
    for x in w["let_op"]:
        if x.get("oordeel") == "sterk":
            sterk[x["onderdeel"]] = min(sterk.get(x["onderdeel"], 0), x.get("punten") or 0)
    o = sorted(w["onderdelen"].items(), key=lambda kv: (kv[0] not in sterk, -abs(kv[1]["punten"]), sterk.get(kv[0], 0)))
    uit = []
    for naam, v in o:
        if abs(v["punten"]) < 0.25 or len(uit) == 3:
            continue
        uit.append((v["punten"], kort_tekst(naam, v)))
    return uit


def reis_tekst(w) -> str:
    delen = []
    for i, r in enumerate(w["routes"]):
        naam = "" if i == 0 else f"{r['label']} "
        delen.append(f"{naam}≈ {r['min']} min")
    return " · ".join(delen)


# ── HTML ─────────────────────────────────────────────────────────────────────
def punt_html(it, met_punten=True) -> str:
    o = it.get("oordeel") or "neutraal"
    ptxt = punten(it.get("punten") or 0)
    pcls = "pt-plus" if ptxt.startswith("+") else "pt-min" if ptxt.startswith("−") else "pt-nul"
    pt = f'<span class="pt {pcls}">{ptxt if ptxt != "0" else ""}</span>' if met_punten else "<span></span>"
    vraag = f'<span class="vraag">Navragen: {h(it["vraag"])}</span>' if it.get("vraag") else ""
    uitleg = (f'<span class="uitleg">{h(it["uitleg"])}</span>' if it.get("uitleg") and o in ("sterk", "let_op")
              and it.get("onderdeel") != "woonlasten" else "")
    return (f'<li class="punt">{ic(OORDEEL_IC.get(o, "info"), "ic o-" + o)}'
            f'<span class="punt-tekst"><b>{h(it.get("label"))}</b>: {h(it.get("waarde"))}'
            f'<span class="vh"> ({OORDEEL_TEKST.get(o, o)})</span>'
            f'<span class="bron">{h(it.get("bron") or "")}</span>{uitleg}{vraag}</span>{pt}</li>')


def opbouw_score(w, basis=5.0) -> str:
    rijen = [f'<div><dt>Basis: voldoet aan je eisen</dt><dd class="gesch">{komma(basis)}</dd><dd></dd></div>']
    for naam, v in sorted(w["onderdelen"].items(), key=lambda kv: -kv[1]["punten"]):
        p = v["punten"]
        if abs(p) < 0.05:
            continue
        stap = max(1, min(10, round(abs(p) / 2 * 10)))   # 0,2 punt per stap; 2 punten = halve balk
        balk = f'<span class="balk" aria-hidden="true"><i class="{"bp" if p > 0 else "bm"} b{stap}"></i></span>'
        rijen.append(f'<div><dt>{h(v.get("kort") or naam)}</dt><dd>{punten(p)}</dd><dd>{balk}</dd></div>')
    afgekapt = w["score"] in (0, 10)
    rijen.append(f'<div class="som"><dt>Score{" (afgekapt)" if afgekapt else ""}</dt><dd>{komma(w["score"])}</dd><dd></dd></div>')
    som = sum(v["punten"] for v in w["onderdelen"].values())
    teken = "+" if som >= 0 else "−"
    zin = (f'<p class="scorezin"><strong>Score {komma(w["score"])}</strong> = basis {komma(basis)} {teken} '
           f'{komma(abs(som))} uit de onderdelen hieronder, elk begrensd'
           f'{", en daarna afgekapt op 0 en 10" if afgekapt else ""}. Onbekend en kansen tellen niet mee.</p>')
    onb = f'<p class="gesch">{len(w["onbekend"])} onbekend: telt niet mee.</p>' if w["onbekend"] else ""
    return (f'<details class="opbouw"><summary>Opbouw score <span class="waarde">{komma(w["score"])}</span>'
            f'{ic("chev", "ic chev")}</summary>{zin}<dl class="rekensom">{"".join(rijen)}{onb}</dl></details>')


def opbouw_lasten(w) -> str:
    f = w["fin"]
    o = f.get("opbouw") or {}
    if f.get("netto") is None or not o:
        return ""
    vve = o.get("vve") if o.get("vve") is not None else VVE_STANDAARD
    overig = o.get("overig") if o.get("overig") is not None else OVERIG_STANDAARD
    energie, canon = o.get("energie") or 0, o.get("canon_maand") or 0
    rente = f.get("rente")
    rentetekst = (f"{komma(rente * 100, 2)}%, " if rente else "") + (
        f"{f['rentevast_jaren']} jaar vast, annuïtair" if f.get("rentevast_jaren") else "annuïtair")
    r = [("Hypotheek, bruto", eur(o.get("bruto_hyp") or 0), rentetekst),
         ("Belastingvoordeel jaar 1", "−" + eur(o.get("belastingvoordeel") or 0), "renteaftrek min eigenwoningforfait")]
    if o.get("vve_geschat"):
        r.append(("VvE-bijdrage", "≈ " + eur(vve), "niet gevonden, geschat"))
    else:
        r.append(("VvE-bijdrage", eur(vve), "uit " + str(o.get("vve_bron") or "de advertentie")
                  + (", incl. stookkosten" if o.get("stook_in_vve") else "")))
    r.append(("Energie", "≈ " + eur(energie), f"schatting voor label {w['label'] or 'onbekend'}"
              + (", alleen elektra" if o.get("stook_in_vve") else "")))
    r.append(("Gemeente, water, inboedel", "≈ " + eur(overig), "vaste aanname"))
    if canon:
        r.append(("Erfpachtcanon", eur(canon), "per maand"))
    rij = "".join(f'<div><dt>{h(a)}<span class="vh">, </span><br><span class="gesch">{h(c)}</span></dt><dd>{h(b)}</dd></div>'
                  for a, b, c in r)
    bruto = f'<br><span class="gesch">bruto {eur(f["bruto"])}</span>' if f.get("bruto") is not None else ""
    rij += f'<div class="som"><dt>Netto per maand{bruto}</dt><dd>{eur(f["netto"])}</dd></div>'
    sam = " · bevat een schatting" if o.get("vve_geschat") else ""
    return (f'<details class="opbouw"><summary>Opbouw woonlasten <span class="waarde">{eur(f["netto"])}{sam}</span>'
            f'{ic("chev", "ic chev")}</summary><dl class="rekensom geld">{rij}</dl></details>')


def kenmerken(w) -> str:
    ch = w["ch"]
    laag = ch.get("Gelegen op")
    lift = "met lift" if "lift" in str(ch.get("Voorzieningen") or "").lower() else "geen lift"
    rijen = []
    if laag:
        rijen.append(("Woonlaag", f"{laag}, {lift}"))
    bt = ch.get("Balkon/dakterras")
    if bt:
        m2 = ch.get("Gebouwgebonden buitenruimte")
        rijen.append(("Buitenruimte", bt + (f", {m2}" if m2 and "Niet" not in bt else "")))
    if w["bouwjaar"]:
        rijen.append(("Bouwjaar", str(w["bouwjaar"])))
    rijen.append(("Energielabel", w["label"] or "onbekend"))
    if ch.get("Eigendomssituatie"):
        rijen.append(("Eigendom", ch["Eigendomssituatie"]))
    if ch.get("Verwarming"):
        rijen.append(("Verwarming", ch["Verwarming"]))
    if w["gedaald"] and w["eerdere_prijs"] and w["prijs"]:
        rijen.append(("Prijsverloop", f"was {eur(w['eerdere_prijs'])}, nu {eur(w['prijs'])}"))
    woz = w["woz"] or {}
    if _getal(woz.get("price")):
        rijen.append(("WOZ", eur(woz["price"]) + (f" (peildatum {woz['date']})" if woz.get("date") else "")))
    a = w["aangeboden"]
    if a:
        rijen.append(("Op funda", "sinds vandaag" if str(a).lower() == "vandaag" else f"sinds {a}"))
    return "".join(f"<dt>{h(x)}</dt><dd>{h(y)}</dd>" for x, y in rijen)


def financiering(w, meta: dict | None = None) -> str:
    """Laag 2, blok Geld: leentoets, eigen geld, je grens en de scenario's (zonder inkomen)."""
    meta = meta or {}
    f = w["fin"]
    if not f.get("max_hypotheek"):
        return '<p class="punt-tekst">Zonder vraagprijs geen leentoets. Vraag de makelaar naar de prijsindicatie.</p>'
    kk = meta.get("kk_onzekerheid", KK_ONZEKERHEID)
    tekort = f.get("tekort") or 0
    eigen = ("genoeg" if tekort <= 0 else
             (f"{eur(tekort)} tekort, binnen de marge van de schatting" if tekort <= kk else f"{eur(tekort)} tekort"))
    marge = f.get("marge_lenen") or 0
    rij = [("Max. hypotheek", eur(f["max_hypotheek"])),
           ("Leenruimte", f"{eur(marge)} over" if marge >= 0 else f"{eur(-marge)} te weinig")]
    if f.get("kosten_koper") is not None:
        rij.append(("Kosten koper", f"≈ {eur(f['kosten_koper'])}"
                    + (", startersvrijstelling" if f.get("kk_soort") == "startersvrijstelling" else "")))
    rij.append(("Eigen geld", eigen))
    if f.get("grens") is not None:
        soort = "bruto per maand (norm)" if f.get("grens_soort") == "bruto norm" else "netto per maand"
        rij.append(("Je grens", f"{eur(f['grens'])} {soort}"))
    for s in f.get("scenarios") or []:
        oordeel = "past" if s.get("past") else "past niet"
        extra = f", max. koopsom {eur_vast(s['max_koopsom'])}" if _getal(s.get("max_koopsom")) else ""
        plan = " (planning)" if s.get("id") == f.get("planning") else ""
        rij.append((str(s.get("label") or s.get("id")) + plan, oordeel + extra))
    return f'<dl class="kenmerken">{"".join(f"<dt>{h(a)}</dt><dd>{h(b)}</dd>" for a, b in rij)}</dl>'


def kerncijfers(w) -> str:
    """Vraagprijs · Woonlasten · Score, altijd op dezelfde plek."""
    if w["prijs"]:
        if w["gedaald"] and w["eerdere_prijs"]:
            onder = f'<dd class="sub"><span class="vh">was </span><s>{eur(w["eerdere_prijs"])}</s></dd>'
        elif w["m2"]:
            onder = f'<dd class="sub">{eur(w["prijs"] / w["m2"])} per m²</dd>'
        else:
            onder = ""
        prijs = f'<dd>{eur(w["prijs"])}</dd>{onder}'
    else:
        prijs = '<dd class="cijfer-leeg">op aanvraag</dd>'
    netto = w["fin"].get("netto")
    lasten = (f'<dd>{eur(netto)}</dd><dd class="sub">netto per maand</dd>' if netto is not None
              else '<dd class="cijfer-leeg">onbekend</dd>')
    score = f'<dd class="score-w">{komma(w["score"])}</dd><dd class="sub">van 10</dd>'
    return (f'<dl class="w-cijfers"><div><dt>Vraagprijs</dt>{prijs}</div><div><dt>Woonlasten</dt>{lasten}</div>'
            f'<div><dt>Score</dt>{score}</div></dl>')


def kaart_html(w, meta: dict | None = None) -> str:
    cid, p = w["card_id"], w["poort"]
    foto = (f'<img src="{h(w["foto"])}" alt="" loading="lazy" width="88" height="88">' if w["foto"]
            else f'{ic("huis", "ic")}<span class="vh">Geen foto</span>')
    labels = []
    if w["gedaald"]:
        labels.append('<span class="lbl lbl-daling">Prijs gedaald</span>')
    if w["lang"]:
        labels.append('<span class="lbl lbl-lang">Lang te koop</span>')
    # Woonlaag staat niet in de feitenregel (past niet op 390 px); zonder lift staat hij in de redenregel en altijd in laag 2.
    feit = ([f"{w['m2']} m²"] if w["m2"] else []) + ([f"{w['kamers']} kamers"] if w["kamers"] else []) + [
        f"label {w['label'] or 'onbekend'}"]
    reis = reis_tekst(w)
    reis_html = (f'<p class="w-reis">{ic("fiets", "ic ic-s")}<span><span class="vh">Fietstijd naar werk: </span>{h(reis)}</span></p>'
                 if reis else "")
    twijfel = "".join(f'<p class="w-twijfel">{ic("warn")}<span>{h(t)} Onderaan gezet.</span></p>' for t in w["twijfel"])
    red_html = "".join(f'<span class="r {"r-plus" if pt > 0 else "r-min"}"><span class="vh">{"plus" if pt > 0 else "min"}: </span>{h(t)}</span>'
                       for pt, t in redenen_kort(w))
    if w["onbekend"]:
        red_html += f'<span class="r r-onb">{len(w["onbekend"])} onbekend</span>'
    n_lo = len(w["let_op"])
    plus_met = [x for x in w["plus"] if (x.get("punten") or 0) > 0]
    plus_nul = [x for x in w["plus"] if (x.get("punten") or 0) <= 0]
    n_plus = len(plus_met) or len(w["plus"])
    if len(plus_met) < 3:
        plus_met, plus_nul = plus_met + plus_nul[:3 - len(plus_met)], plus_nul[3 - len(plus_met):]
    lo = "".join(punt_html(x) for x in w["let_op"]) or '<li class="punt-tekst">Niets gevonden.</li>'
    plus = "".join(punt_html(x) for x in plus_met)
    ook = (f'<p class="punt-tekst mt-100"><span class="gesch">Ook in orde: </span>'
           + h(", ".join(f"{str(x.get('label', '')).lower()} {x.get('waarde', '')}" for x in plus_nul)) + "</p>") if plus_nul else ""
    onb = "".join(punt_html(x, False) for x in w["onbekend"])
    kans = "".join(punt_html({**x, "oordeel": "kans"}, False) for x in w["kansen"])
    t = h(w["titel"])
    fotos = "".join(f'<img src="{h(u)}" alt="Foto {i + 1} van {t}" loading="lazy">' for i, u in enumerate(w["fotos"]))
    zelf = "".join(f"<li>{h(v)}</li>" for v in w["zelf"])
    blokken = [
        f'<section class="blok"><h4>{ic("warn", "ic o-let_op")}Let op <span class="tel">{n_lo}</span></h4>'
        f'<ul class="punten">{lo}</ul></section>',
        f'<section class="blok"><h4>{ic("check", "ic o-goed")}Pluspunten <span class="tel">{n_plus}</span></h4>'
        f'<ul class="punten">{plus}</ul>{ook}</section>',
    ]
    if onb or kans:
        blokken.append(f'<section class="blok"><h4>{ic("vraag", "ic o-onbekend")}Onbekend en kansen</h4><ul class="punten">{onb}{kans}</ul>'
                       f'<p class="punt-tekst gesch mt-100">Telt niet mee in de score.</p></section>')
    if w["beoordeeld"]:
        blokken.append(f'<section class="blok">{opbouw_score(w)}</section>')
    blokken.append(f'<section class="blok"><h4>Geld</h4><div class="geld-blok">{opbouw_lasten(w)}{financiering(w, meta)}</div></section>')
    blokken.append(f'<section class="blok"><h4>Woning</h4><dl class="kenmerken">{kenmerken(w)}</dl></section>')
    if zelf:
        blokken.append(f'<section class="blok"><h4>Zelf nagaan</h4><ol class="vragen">{zelf}</ol></section>')
    if fotos:
        blokken.append(f'<section class="blok breed"><h4>Foto\'s</h4><div class="fotostrip">{fotos}</div></section>')
    url = h(w["url"])
    if url:
        blokken.append(f'<div class="acties breed"><a class="knop knop-sec knop-vol" href="{url}" target="_blank" rel="noopener" '
                       f'aria-label="Bekijk {t} op funda (opent nieuw venster)">Bekijk op funda {ic("extern", "ic ic-s")}</a></div>')
        funda_knop = (f'<a class="icoonknop" href="{url}" target="_blank" rel="noopener" aria-label="Bekijk {t} op funda '
                      f'(opent nieuw venster)" title="Bekijk op funda">{ic("extern")}</a>')
    else:
        funda_knop = ""
    scenario = f'<span class="w-scenario">{h(w["scenario_tekst"])}</span>' if w["scenario_tekst"] else ""
    labels_html = f'<p class="w-labels">{"".join(labels)}</p>' if labels else ""
    return f"""<article class="woning" id="card-{cid}" data-id="{h(w['id'])}" aria-labelledby="t-{cid}">
<div class="w-status st-{POORT_CLS[p]}">{ic(POORT_IC[p])}<p>{w['status_html']}{scenario}</p></div>
<div class="w-kern"><div class="w-foto">{foto}</div><div class="w-tekst">
<div class="w-titelrij"><h3 class="w-titel" id="t-{cid}">{t}</h3>
<button type="button" class="icoonknop w-bewaar" aria-pressed="false" aria-label="Bewaar {t}">{ic('ster')}</button></div>
<p class="w-buurt">{h(w['buurt'])} · {h(w['stad'])}</p>
<p class="w-feit">{h(' · '.join(feit))}</p>{reis_html}
{labels_html}</div></div>
{kerncijfers(w)}{twijfel}
<p class="w-waarom"><span class="vh">Waarom deze score: </span>{red_html}</p>
<div class="w-voet"><details class="w-meer"><summary>Let op <span class="tel-lo">{n_lo}</span> · Pluspunten <span class="tel-lo">{n_plus}</span>
<span class="vh">, details van {t}</span>{ic('chev', 'ic chev')}</summary>
<div class="w-laag2">{''.join(blokken)}</div></details>
<div class="w-acties">{funda_knop}
<button type="button" class="icoonknop" data-actie="verberg" aria-label="Verberg {t}" title="Verberg">{ic('oog')}</button></div></div>
</article>"""


def js_data(w) -> dict:
    top_plus = max(w["plus"], key=lambda x: x.get("punten") or 0, default=None)
    top_lo = min(w["let_op"], key=lambda x: (0 if x.get("oordeel") == "sterk" else 1, x.get("punten") or 0), default=None)
    r0 = w["routes"][0] if w["routes"] else None
    return {"id": w["id"], "card_id": w["card_id"], "titel": w["titel"], "buurt": f"{w['buurt']}, {w['stad']}",
            "stad": w["stad"], "poort": w["poort"], "status_kort": w["status_kort"], "scenario_tekst": w["scenario_tekst"],
            "netto": w["fin"].get("netto"), "prijs": w["prijs"], "m2": w["m2"], "score": w["score"],
            "score_tekst": komma(w["score"]), "twijfel": bool(w["twijfel"]), "gedaald": w["gedaald"],
            "dagen": w["dagen"], "reis_min": r0["min"] if r0 else None,
            "reis_tekst": (f"fiets ≈ {r0['min']} min" if r0 else ""),
            "top_plus": f"{top_plus.get('label')}: {top_plus.get('waarde')}" if top_plus else "",
            "top_let_op": f"{top_lo.get('label')}: {top_lo.get('waarde')}" if top_lo else "",
            "lat": w["lat"], "lon": w["lon"], "nieuw_run": w["nieuw_run"]}


def volgende_run(nu: datetime, cron_utc=None) -> str:
    """Volgende run uit de cron (UTC) in Nederlandse tijd: winter 09:30 en 17:30, zomer 10:30 en 18:30."""
    for dag in (0, 1):
        for uur, minuut in (cron_utc or RUN_CRON_UTC):
            u = nu.astimezone(timezone.utc)
            t = datetime(u.year, u.month, u.day, uur, minuut, tzinfo=timezone.utc) + timedelta(days=dag)
            if t > u:
                return ("morgen " if dag else "") + t.astimezone(AMS).strftime("%H:%M")
    return ""


def sorteer(woningen: list[dict]) -> list[dict]:
    """Aanbevolen: (poort, twijfel, -score), zelfde sleutel als funda_beoordeling.sorteer()."""
    return sorted(woningen, key=lambda w: (POORT_RANG[w["poort"]], bool(w["twijfel"]), -w["score"]))


def _rente(meta: dict, woningen: list[dict], nu: datetime) -> dict:
    """Rente voor de voet en de melding: uit meta["rente"], anders uit de financiering van de eerste woning."""
    r = dict(meta.get("rente") or {})
    if r.get("pct") is None:
        f = next((w["fin"] for w in woningen if w["fin"].get("rente")), {})
        if f:
            r.update({"pct": f["rente"] * 100, "datum": f.get("rente_datum")})
    pct = _getal(r.get("pct"))
    if pct is not None and pct < 1:   # als fractie (0,0411) doorgegeven
        pct *= 100
    r["pct"] = pct
    try:
        r["peildatum"] = date.fromisoformat(str(r.get("datum")))
        r["dagen"] = (nu.date() - r["peildatum"]).days
    except ValueError:
        r["peildatum"], r["dagen"] = None, None
    r["oud"] = bool(r.get("oud"))
    r["melding"] = (str(r["melding"]).strip() or None) if r.get("melding") else None
    return r


def rente_melding(r: dict) -> str:
    """Eén zichtbare melding als de rente oud is of de rentemodule iets meldt; anders niets."""
    delen = []
    if r["oud"]:
        delen.append(f"Rente is {r['dagen']} dagen oud: woonlasten kunnen afwijken." if r.get("dagen") is not None
                     else "Rente is oud: woonlasten kunnen afwijken.")
    if r["melding"]:
        delen.append(_zin(r["melding"]))
    if not delen:
        return ""
    return (f'<a class="melding rente-melding" id="rente-melding" href="#budget" data-actie="budget">{ic("warn")}'
            f'<span>{h(" ".join(delen))} <u>Meer weten</u></span></a>')


def _scenarios_budget(meta: dict, woningen: list[dict]) -> tuple[list[tuple[str, str, bool]], str | None]:
    """Per scenario de max. koopsom (geen inkomen). Uit meta, anders de spreiding over de woningen."""
    planning = next((w["fin"].get("planning") for w in woningen if w["fin"].get("planning")), None)
    if meta.get("scenarios"):
        lijst = [(s.get("id"), s.get("label") or s.get("id"), [s.get("max_koopsom")]) for s in meta["scenarios"]]
    else:
        volg, per = [], {}
        for w in woningen:
            for s in w["fin"].get("scenarios") or []:
                if s.get("id") not in per:
                    volg.append(s.get("id"))
                    per[s.get("id")] = (s.get("label") or s.get("id"), [])
                per[s.get("id")][1].append(s.get("max_koopsom"))
        lijst = [(sid, per[sid][0], per[sid][1]) for sid in volg]
    uit = []
    for sid, label, waarden in lijst:
        w = [x for x in waarden if _getal(x)]
        if not w:
            continue
        lo, hi = min(w), max(w)
        tekst = eur_vast(lo) if lo == hi else f"{eur_vast(lo)} tot {eur_vast(hi)}"
        uit.append((str(label), tekst, sid == planning))
    plan_label = next((label for label, _, plan in uit if plan), None)
    return uit, plan_label


def _budget_html(meta: dict, woningen: list[dict], r: dict, nu: datetime) -> str:
    kmu = meta.get("fiets_kmu") or FIETS_KMU
    rijen = []
    f = next((w["fin"] for w in woningen if w["fin"].get("grens") is not None), {})
    if f:
        soort = "bruto per maand (norm uit de leentoets)" if f.get("grens_soort") == "bruto norm" else "netto per maand"
        rijen.append(("Je grens", f"{eur(f['grens'])} {soort}"))
    if r.get("pct") is not None:
        vast = next((w["fin"].get("rentevast_jaren") for w in woningen if w["fin"].get("rentevast_jaren")), None)
        rijen.append(("Rente", f"{komma(r['pct'], 2)}%" + (f", {vast} jaar vast" if vast else "")))
        bron = RENTE_BRON.get(str(r.get("bron")), str(r.get("bron") or "onbekend"))
        peil = f", peildatum {datum_lang(r['peildatum'])}" if r.get("peildatum") else ""
        oud = f" ({r['dagen']} dagen oud)" if r["oud"] and r.get("dagen") is not None else ""
        rijen.append(("Bron rente", bron + peil + oud))
    jaar = meta.get("leentoets_jaar") or nu.year
    rijen.append(("Leentoets", f"regeling hypothecair krediet {jaar}, tabel 1"))
    rijen.append(("Fietstijd", f"routeafstand gedeeld door {komma(kmu, 0) if float(kmu).is_integer() else komma(kmu)} km/u"))
    for regel in meta.get("budget_regels") or []:
        rijen.append((str(regel[0]), str(regel[1])))
    dl = "".join(f"<dt>{h(a)}</dt><dd>{h(b)}</dd>" for a, b in rijen)
    sc, plan_label = _scenarios_budget(meta, woningen)
    sc_html = ""
    if sc:
        sc_dl = "".join(f"<dt>{h(label)}{' (planning)' if plan else ''}</dt><dd>{h(tekst)}</dd>" for label, tekst, plan in sc)
        uitleg = (f" De groepen Past, Krap en Past niet volgen het scenario &quot;{h(plan_label)}&quot;." if plan_label else "")
        sc_html = (f'<p>Max. koopsom per scenario. De spreiding komt van energielabel en erfpacht.{uitleg}</p>'
                   f'<dl class="kenmerken">{sc_dl}</dl>')
    melding = ""
    if r["melding"]:
        melding = f'<p class="melding">{ic("warn")}<span>{h(_zin(r["melding"]))}</span></p>'
    kop_extra = ""
    if r["oud"] and r.get("dagen") is not None:
        kop_extra = f' <span class="waarde">· rente {r["dagen"]} dagen oud</span>'
    elif r["oud"] or r["melding"]:
        kop_extra = ' <span class="waarde">· let op de rente</span>'
    return f"""<details class="opbouw" id="budget"><summary><span>Jouw budget en aannames{kop_extra}</span>{ic('chev', 'ic chev')}</summary><div class="tekst">
{melding}<dl class="kenmerken">{dl}</dl>
{sc_html}
<ul><li>Woonlasten zijn netto, jaar 1: hypotheek min belastingvoordeel, plus VvE, energie, gemeente en erfpacht.</li>
<li>Een bedrag met ≈ is een schatting. Staat er "geschat" bij de VvE, dan is de bijdrage niet gevonden.</li>
<li>Score 0 tot 10. 5 betekent: voldoet aan je eisen. Onbekend en kansen tellen niet mee.</li></ul>
<p>Een vaste rente, je grens en de scenario's zet je in je instellingen (funda_personal.json).</p></div></details>"""


def _push_html(meta: dict) -> str:
    if not meta.get("push_beschikbaar") or meta.get("push_ingesteld"):
        return ""
    return f"""<details class="opbouw" id="meldingen"><summary>Meldingen op deze iPhone{ic('chev', 'ic chev')}</summary><div class="tekst">
<p>Krijg een melding als er nieuwe woningen zijn. Dit werkt alleen in de app op je beginscherm (iOS 16.4 of nieuwer).</p>
<div class="acties"><button type="button" class="knop knop-ter" id="push-subscribe-btn">{ic('bel', 'ic ic-s')} Meldingen aanzetten</button>
<button type="button" class="knop knop-ter" id="push-copy-btn" hidden>Kopieer het abonnement</button></div>
<p>Zet het abonnement daarna als GitHub-secret WEB_PUSH_SUBSCRIPTION.</p>
<textarea id="push-subscription-output" class="push-uitvoer" readonly hidden spellcheck="false" aria-label="Web Push-abonnement"></textarea>
<p id="push-status" class="push-status" role="status"></p></div></details>"""


APPARAAT_HTML = f"""<details class="opbouw" id="apparaat" hidden><summary>Dit apparaat{ic('chev', 'ic chev')}</summary><div class="tekst">
<p>Dit apparaat onthoudt een sleutel voor het rapport, niet je wachtwoord. Vergeet hem als je dit toestel deelt of wegdoet.</p>
<div class="acties"><button type="button" class="knop knop-ter" data-actie="vergeet">Vergeet dit apparaat</button></div></div></details>"""


def render_report_body(rijen: list[dict], meta: dict | None = None) -> str:
    """De body van het rapport. Kaarten server-side; JavaScript verplaatst ze alleen tussen groepen."""
    meta = meta or {}
    nu = _tijdstip(meta)
    woningen, gebruikt = [], set()
    for rij in rijen:
        w = _woning(rij, meta)
        cid = card_id(w["id"])
        while cid in gebruikt:
            cid += "-x"
        gebruikt.add(cid)
        w["card_id"] = cid
        woningen.append(w)
    woningen = sorteer(woningen)
    nieuw = [w for w in woningen if w["nieuw_run"]]
    groepen = {p: [w for w in woningen if not w["nieuw_run"] and w["poort"] == p] for p in POORTEN}
    tel = {p: sum(1 for w in woningen if w["poort"] == p) for p in POORTEN}
    gedaald = sum(1 for w in woningen if w["gedaald"])
    steden = sorted({w["stad"] for w in woningen if w["stad"]})
    r = _rente(meta, woningen, nu)

    def chip(k, tekst, n, aan=False):
        return f'<button type="button" class="chip" data-snel="{k}" aria-pressed="{str(aan).lower()}">{tekst} <b>{n}</b></button>'

    chips = "".join([chip("alles", "Alles", len(woningen), True), chip("nieuw", "Nieuw", len(nieuw)),
                     chip("past", "Past", tel["PAST"]), chip("krap", "Krap", tel["KRAP"]),
                     chip("gedaald", "Prijs gedaald", gedaald), chip("bewaard", "Bewaard", 0)])
    secties = [f"""<section id="nieuw" class="sectie" aria-labelledby="nieuw-titel">
<h2 class="sectie-kop"><span id="nieuw-titel">Nieuw sinds de vorige run</span> <span class="tel">{len(nieuw) or ''}</span></h2>
<p id="nieuw-leeg" class="sectie-leeg"{' hidden' if nieuw else ''}>Geen nieuwe woningen sinds de vorige run.</p>
<div class="kaarten">{''.join(kaart_html(w, meta) for w in nieuw)}</div></section>""",
               '<p id="eerder" class="groep-uitleg eerder-kop">Eerder gezien, op volgorde van financiering en score.</p>']
    for p in POORTEN:
        ws = groepen[p]
        n = len(ws)
        uitleg = f'<p class="groep-uitleg">{GROEP_UITLEG[p]}</p>' if GROEP_UITLEG[p] else ""
        secties.append(f"""<details class="groep sectie" data-poort="{p}"{'' if p == 'PAST NIET' else ' open'}{'' if n else ' hidden'}>
<summary class="sectie-kop"><h2 class="h-erf">{POORT_NAAM[p]}</h2> <span class="tel">{n} {'woning' if n == 1 else 'woningen'}</span>{ic('chev', 'ic chev')}</summary>
{uitleg}<div class="kaarten">{''.join(kaart_html(w, meta) for w in ws)}</div></details>""")
    secties.append('<section id="plat" class="sectie" hidden><h2 class="sectie-kop">Alle woningen</h2><div class="kaarten"></div></section>')

    sorteer_keuzes = [("aanbevolen", "Aanbevolen", "eerst wat past, dan op score"), ("score", "Hoogste score", ""),
                      ("woonlasten", "Laagste woonlasten", ""), ("prijs", "Laagste vraagprijs", ""),
                      ("reis", "Kortste fietstijd naar werk", ""), ("nieuwst", "Kortst op funda", "")]
    sort_html = "".join(f'<label class="keuze" for="s-{k}"><input type="radio" name="sort" id="s-{k}" value="{k}"{" checked" if k == "aanbevolen" else ""}>'
                        f'<span>{t}{f" <small>({u})</small>" if u else ""}</span></label>' for k, t, u in sorteer_keuzes)
    poort_html = "".join(f'<label class="keuze" for="p-{POORT_CLS[p]}"><input type="checkbox" name="poort" id="p-{POORT_CLS[p]}" value="{p}">'
                         f'<span>{POORT_NAAM[p]} <small>({tel[p]})</small></span></label>' for p in POORTEN)

    def stad_naam(s):
        return f"{h(s)} <small>(gemeente; Leidschendam of Voorburg)</small>" if s == "Leidschendam-Voorburg" else h(s)
    stad_html = "".join(f'<label class="keuze" for="c-{i}"><input type="checkbox" name="stad" id="c-{i}" value="{h(s)}">'
                        f'<span>{stad_naam(s)} <small>({sum(1 for w in woningen if w["stad"] == s)})</small></span></label>'
                        for i, s in enumerate(steden))
    data = json.dumps({"woningen": [js_data(w) for w in woningen]}, ensure_ascii=False).replace("</", "<\\/")
    run_iso = nu.strftime("%Y-%m-%dT%H:%M")
    actions = meta.get("actions_url")
    run_knop = (f'<a class="icoonknop" href="{h(actions)}" target="_blank" rel="noopener" '
                f'aria-label="Nieuwe run starten op GitHub (opent nieuw venster)" title="Nieuwe run">{ic("vernieuw")}</a>'
                if actions else "")
    volgende = volgende_run(nu, meta.get("run_cron_utc"))
    legenda = "".join(f'<span><i class="lp p-{POORT_CLS[p]}">{ic(POORT_IC[p])}</i>{POORT_NAAM[p]}</span>' for p in POORTEN)
    return f"""{SPRITE}
<a class="skip" href="#lijst">Naar de woningen</a>
<header class="app-top context-strong"><div class="app-top-in">
<div class="app-top-tekst"><h1>Woningen<span id="top-tel" class="top-tel" hidden></span></h1>
<p>Bijgewerkt {datum_kort(nu)}, {nu:%H:%M}{f' · volgende rond {volgende}' if volgende else ''}</p></div>
{run_knop}
</div></header>
<div id="app" class="app" data-view="lijst" data-run="{run_iso}">
<main class="app-main" id="lijst" tabindex="-1">
<div class="snel" role="group" aria-label="Snelfilters">{chips}</div>
{rente_melding(r)}
<div id="bewaard-balk" class="bewaard-balk" hidden><span id="bewaard-tekst"></span>
<button type="button" class="knop knop-sec vergelijk-knop" data-actie="vergelijk">{ic('vergelijk')} Vergelijk <span class="teller" hidden>0</span></button></div>
{''.join(secties)}
<div id="park" hidden></div>
<section id="leeg" class="leeg" hidden aria-live="polite"><h2 id="leeg-kop">Geen woningen met deze filters</h2>
<p id="leeg-tekst">Zet een filter uit of wis ze allemaal. Verborgen woningen tellen niet mee.</p>
<button type="button" class="knop knop-ter" data-actie="wis">Wis filters</button></section>
<footer class="voet">
<p id="verborgen-regel" class="verborgen-regel" hidden><span id="verborgen-tekst"></span><button type="button" class="linkknop" id="toon-verborgen">Toon ze</button></p>
{_budget_html(meta, woningen, r, nu)}
{_push_html(meta)}
{APPARAAT_HTML}
<details class="opbouw"><summary>Bronnen{ic('chev', 'ic chev')}</summary><div class="tekst"><p>funda (advertentie en kenmerken), BAG (Kadaster via PDOK),
Klimaateffectatlas, RIVM-geluidkaarten, Leefbaarometer 3.0, RIVM-gezondheidsmonitor. Kaart: OpenStreetMap.</p></div></details>
</footer>
</main>
<aside class="app-zij" aria-label="Kaart en filters">
<div class="zij-kop"><button type="button" class="knop knop-ter" data-actie="filters">{ic('filter')} Filter en sorteer <span class="teller filter-teller" hidden>0</span></button>
<button type="button" class="knop knop-ter vergelijk-knop" data-actie="vergelijk" disabled>{ic('vergelijk')} Vergelijk <span class="teller">0</span></button></div>
<div class="kaart-paneel" role="region" aria-label="Kaart met woningen. Dezelfde woningen staan in de lijst."><div id="kaart"></div>
<p id="kaart-melding" class="kaart-melding" hidden>Kaart laden…</p>
<p class="kaart-legenda">{legenda}<span><i class="lp is-nieuw"></i>Nieuw (ring)</span><span>Getal: score</span></p></div>
</aside>
<nav class="app-onder" aria-label="Weergave en acties"><div class="app-onder-in">
<button type="button" class="onderknop" data-actie="filters">{ic('filter')} Filter <span class="teller filter-teller" hidden>0</span></button>
<div class="wissel" role="group" aria-label="Weergave"><button type="button" data-view="lijst" aria-pressed="true">{ic('lijst', 'ic ic-s')} Lijst</button>
<button type="button" data-view="kaart" aria-pressed="false">{ic('kaart', 'ic ic-s')} Kaart</button></div>
</div></nav>
<dialog id="filters" class="sheet" aria-labelledby="filters-titel"><form id="filterform" method="dialog" class="h-erf">
<div class="sheet-kop"><h2 id="filters-titel">Filter en sorteer</h2><button type="button" class="icoonknop" data-actie="sluit" aria-label="Sluiten">{ic('sluit')}</button></div>
<div class="sheet-body">
<fieldset><legend>Sorteren</legend>{sort_html}</fieldset>
<fieldset><legend>Financiering</legend>{poort_html}</fieldset>
<fieldset><legend>Plaats</legend>{stad_html}</fieldset>
<fieldset><legend>Grenzen</legend><div class="velden">
<div class="veld"><label for="f-maxlasten">Max. woonlasten</label><input id="f-maxlasten" type="number" inputmode="numeric" min="0" step="50" placeholder="bijv. 1450"></div>
<div class="veld"><label for="f-minm2">Min. oppervlak (m²)</label><input id="f-minm2" type="number" inputmode="numeric" min="0" step="5" placeholder="bijv. 60"></div></div></fieldset>
<fieldset><legend>Tonen</legend>
<label class="schakel" for="f-twijfel"><span>Twijfel verbergen <small class="gesch">(buurt of stad onduidelijk)</small></span><input id="f-twijfel" type="checkbox" role="switch"></label>
<label class="schakel" for="f-verborgen"><span>Verborgen woningen tonen</span><input id="f-verborgen" type="checkbox" role="switch"></label></fieldset>
</div>
<div class="sheet-voet"><button type="button" class="knop knop-ter" data-actie="wis">Wis filters</button>
<button type="submit" class="knop knop-sec" id="sheet-toon">Toon {len(woningen)} {'woning' if len(woningen) == 1 else 'woningen'}</button></div></form></dialog>
<dialog id="vergelijk" class="sheet" aria-labelledby="vergelijk-titel">
<div class="sheet-kop"><h2 id="vergelijk-titel">Bewaarde woningen naast elkaar</h2><button type="button" class="icoonknop" data-actie="sluit" aria-label="Sluiten">{ic('sluit')}</button></div>
<div class="sheet-body"><div class="vergelijk-wrap"><table id="vergelijk-tabel" class="vergelijk"></table></div>
<p class="groep-uitleg">"Beste" is per regel de gunstigste waarde. Bewaren en vergelijken blijft op dit toestel.</p></div></dialog>
<div id="toast" class="toast context-strong" role="status" hidden><span id="toast-tekst"></span><button type="button" class="linkknop" id="toast-knop">Ongedaan maken</button></div>
</div>
<script type="application/json" id="woning-data">{data}</script>"""


def vul_slot(waarden: dict) -> str:
    """ui/slot.html met elke placeholder vervangen. waarden: {"__APP_CSS__": ..., "__GZ__": "1", ...}."""
    ontbreekt = [p for p in SLOT_PLACEHOLDERS if p not in waarden]
    if ontbreekt:
        raise ValueError("placeholders zonder waarde: " + ", ".join(ontbreekt))
    uit = SLOT_HTML
    # Eerst de korte waarden, dan pas CSS en scripts: zo kan een placeholdernaam in de CSS of JS niets kapotmaken.
    for p in ("__GZ__", "__SALT__", "__IV__", "__CT__", "__ITERS__", "__MAP_HEAD__", "__APP_SCRIPTS__", "__APP_CSS__"):
        uit = uit.replace(p, str(waarden[p]), 1)
    return uit
