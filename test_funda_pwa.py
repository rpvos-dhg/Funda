"""Offline tests voor de versleutelde PWA: sleutelopbouw, gzip en opvulling vóór AES-256-GCM, en de wrapper.

Ontsleutelt in Python met dezelfde stappen als de browser (PBKDF2-SHA256 met het vaste app-zout,
600.000 iteraties; HKDF-SHA256 met het run-zout; AES-256-GCM; opvulling eraf; gzip uitpakken), hier
los uitgeschreven en niet via funda_rapport. Met node draait ook het echte ui/slot.js op het pakket.
Geen netwerk, fictieve inhoud.

Draaien: python test_funda_pwa.py
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import funda_rapport as fr
import funda_ui

WACHTWOORD = "test-wachtwoord"
BODY = ("<main><h1>Woningen</h1>" + "".join(f"<article class=\"woning\">Teststraat {i}</article>" for i in range(40))
        + "<p>€ 1.250 · m² · −0,5</p></main>")
BLOK = 8192
# Leaflet 1.9.4 uit het npm-pakket: dezelfde sha256 als de integrity-waarden van de oude unpkg-tags.
LEAFLET_SHA256 = {"leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
                  "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="}


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return bool(voorwaarde)


def pakket(html: str) -> dict:
    """Het JSON-pakket uit #slot-data van de wrapper."""
    m = re.search(r'<script type="application/json" id="slot-data">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("slot-data niet gevonden")
    return json.loads(m.group(1))


def _pbkdf2(wachtwoord: str, zout: bytes, iters: int) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=zout, iterations=iters).derive(wachtwoord.encode("utf-8"))


def ontsleutel(html: str, wachtwoord: str) -> str:
    """Wat ui/slot.js in de browser doet, in Python: PBKDF2, HKDF, AES-GCM, opvulling eraf en (bij gz 1) gzip."""
    p = pakket(html)
    hoofd = _pbkdf2(wachtwoord, base64.b64decode(p["app_zout"]), int(p["iters"]))
    sleutel = HKDF(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(p["zout"]),
                   info=p["info"].encode("utf-8")).derive(hoofd)
    vol = AESGCM(sleutel).decrypt(base64.b64decode(p["iv"]), base64.b64decode(p["ct"]), None)
    n = int.from_bytes(vol[:4], "big")
    if n > len(vol) - 4:
        raise ValueError("lengte klopt niet")
    data = vol[4:4 + n]
    return (gzip.decompress(data) if p["gz"] else data).decode("utf-8")


def test_roundtrip() -> bool:
    print("test: gzip en opvulling vóór AES, en terug")
    met = fr.beveilig_html(BODY, WACHTWOORD)
    zonder = fr.beveilig_html(BODY, WACHTWOORD, gz=False)
    p, p0, p2 = pakket(met), pakket(zonder), pakket(fr.beveilig_html(BODY, WACHTWOORD))
    ok = check("gz 1 standaard", p["gz"] == 1)
    ok &= check("ontsleutelen en uitpakken geeft de body terug", ontsleutel(met, WACHTWOORD) == BODY)
    ok &= check("gz=False: gz 0 en zonder uitpakken de body", p0["gz"] == 0 and ontsleutel(zonder, WACHTWOORD) == BODY)
    ok &= check("600.000 iteraties (OWASP, PBKDF2-SHA256)", p["iters"] == 600_000 and fr.KDF_ITERS == 600_000, str(p["iters"]))
    ok &= check("run-zout 16 bytes, IV 12 bytes", len(base64.b64decode(p["zout"])) == 16 and len(base64.b64decode(p["iv"])) == 12)
    ok &= check("elke run een nieuw zout en IV", p["zout"] != p2["zout"] and p["iv"] != p2["iv"])
    ok &= check("app-zout: vast, minstens 16 bytes, uit funda_rapport.APP_ZOUT",
                p["app_zout"] == p2["app_zout"] and base64.b64decode(p["app_zout"]) == fr.APP_ZOUT and len(fr.APP_ZOUT) >= 16
                and len(set(fr.APP_ZOUT)) > 8)
    ok &= check("versiestring in het pakket", p["info"] == fr.KDF_INFO and p["v"] == fr.PAKKET_VERSIE == 2)
    try:
        ontsleutel(met, "fout")
        ok &= check("fout wachtwoord geeft InvalidTag", False)
    except InvalidTag:
        ok &= check("fout wachtwoord geeft InvalidTag", True)
    return ok


def test_sleutelopbouw() -> bool:
    print("test: hoofdsleutel uit PBKDF2 met het app-zout, runsleutel uit HKDF met het run-zout")
    p = pakket(fr.beveilig_html(BODY, WACHTWOORD))
    zout, iv, ct = (base64.b64decode(p[k]) for k in ("zout", "iv", "ct"))
    hoofd = _pbkdf2(WACHTWOORD, fr.APP_ZOUT, 600_000)
    ok = check("fr.hoofdsleutel = PBKDF2-SHA256(wachtwoord, APP_ZOUT, 600.000)", fr.hoofdsleutel(WACHTWOORD) == hoofd)
    los = HKDF(algorithm=hashes.SHA256(), length=32, salt=zout, info=fr.KDF_INFO.encode()).derive(hoofd)
    ok &= check("fr.runsleutel = HKDF-SHA256(hoofdsleutel, run-zout, info)", fr.runsleutel(hoofd, zout) == los)
    ok &= check("een ander run-zout geeft een andere runsleutel", fr.runsleutel(hoofd, bytes(16)) != los)
    ok &= check("een andere versiestring geeft een andere runsleutel", fr.runsleutel(hoofd, zout, "anders") != los)

    def past(sleutel: bytes) -> bool:
        try:
            AESGCM(sleutel).decrypt(iv, ct, None)
            return True
        except InvalidTag:
            return False

    ok &= check("de runsleutel opent de ciphertext", past(los))
    # De oude opbouw (PBKDF2 direct met het run-zout) en de hoofdsleutel zelf mogen niets openen.
    ok &= check("oude opbouw (PBKDF2 met het run-zout, 100.000 of 600.000) opent niets",
                not past(_pbkdf2(WACHTWOORD, zout, 100_000)) and not past(_pbkdf2(WACHTWOORD, zout, 600_000)))
    ok &= check("de hoofdsleutel is niet de AES-sleutel", not past(hoofd))
    return ok


def test_opvulling() -> bool:
    print("test: opvulling, de ciphertext is een veelvoud van 8 kB")
    ok = check("BLOK = 8192", fr.BLOK == BLOK)
    lengtes = []
    for n in (0, 1, 100, BLOK - 21, BLOK - 20, BLOK - 19, 3 * BLOK, 50_000):
        vol = fr.vul_op(b"x" * n)
        lengtes.append((n, len(vol) + 16))
        if (len(vol) + 16) % BLOK or int.from_bytes(vol[:4], "big") != n or vol[4:4 + n] != b"x" * n or any(vol[4 + n:]):
            ok &= check(f"vul_op({n})", False, str(len(vol)))
    ok &= check("vul_op: lengteprefix, data, nullen; met tag een veelvoud van 8192", ok, str(lengtes))
    ok &= check("precies passend: geen extra blok", len(fr.vul_op(b"x" * (BLOK - 20))) == BLOK - 16
                and len(fr.vul_op(b"x" * (BLOK - 19))) == 2 * BLOK - 16)
    # Onsamendrukbare bodies van verschillende lengte: dezelfde ciphertext-lengte zolang ze in hetzelfde blok vallen.
    def ct_len(tekens: int, gz: bool = False) -> int:
        return len(base64.b64decode(pakket(fr.beveilig_html("a" * tekens, WACHTWOORD, gz=gz))["ct"]))
    a, b, c = ct_len(1000), ct_len(5000), ct_len(9000)
    ok &= check("1.000 en 5.000 tekens: even lang; 9.000: een blok meer", a == b == BLOK and c == 2 * BLOK, f"{a} {b} {c}")
    ok &= check("ook met gzip een veelvoud van 8192", ct_len(200_000, gz=True) % BLOK == 0)
    return ok


def _script_tags(html: str) -> list[str]:
    return re.findall(r"<script\b[^>]*>", html, re.I)


def test_wrapper() -> bool:
    print("test: wrapper met CSP, zonder inline script, zonder externe hosts")
    uit = fr.beveilig_html(BODY, WACHTWOORD)
    rest = sorted(set(re.findall(r"__[A-Z][A-Z_]*__", uit)))
    ok = check("alle placeholders vervangen", not rest, ", ".join(rest))
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', uit)
    csp = (m.group(1) if m else "").replace("&#x27;", "'")
    ok &= check("CSP als meta-tag, gelijk aan funda_rapport.CSP", csp == fr.CSP, csp)
    regels = {r.split()[0]: r.split()[1:] for r in csp.split(";") if r.strip()}
    ok &= check("CSP: default-src 'none', script-src 'self', style-src 'self' (geen unsafe-inline, geen unsafe-eval)",
                regels.get("default-src") == ["'none'"] and regels.get("script-src") == ["'self'"]
                and regels.get("style-src") == ["'self'"] and "unsafe" not in csp)
    ok &= check("CSP: img-src 'self', funda's fotohost, de OSM-tegelhost en data: (lege tegel van Leaflet)",
                regels.get("img-src") == ["'self'", "https://cloud.funda.nl", "https://tile.openstreetmap.org", "data:"],
                str(regels.get("img-src")))
    ok &= check("CSP: connect, manifest en worker 'self'; base-uri en form-action 'none'",
                all(regels.get(k) == ["'self'"] for k in ("connect-src", "manifest-src", "worker-src"))
                and regels.get("base-uri") == ["'none'"] and regels.get("form-action") == ["'none'"])
    ok &= check("CSP: geen wildcard, geen andere host", "*" not in csp and csp.count("https://") == 2)
    eerste = min(uit.index(t) for t in ("<script", "<link", "<style") if t in uit)
    ok &= check("CSP staat vóór het eerste script en de eerste link", bool(m) and m.start() < eerste)
    tags = _script_tags(uit)
    inline = [t for t in tags if "src=" not in t and 'type="application/json"' not in t]
    ok &= check("geen inline script: elk <script> heeft een src of is JSON", bool(tags) and not inline, str(inline))
    bronnen = re.findall(r'<(?:script|link|img)\b[^>]*?(?:src|href)="([^"]*)"', uit)
    ok &= check("alle scripts, stylesheets en iconen relatief (geen externe host, geen unpkg)",
                bool(bronnen) and not any(re.match(r"(?i)[a-z][a-z0-9+.-]*:|//", b) for b in bronnen) and "unpkg" not in uit,
                str(bronnen))
    ok &= check("geen <style>, geen style-attribuut, geen on...-attribuut", "<style" not in uit
                and not re.search(r'\sstyle\s*=', uit) and not re.search(r'\son[a-z]+\s*=', uit))
    ok &= check("volgorde: Leaflet, app.js, push.js, slot.js (push haakt op fundaAfterReportLoad in)",
                [re.search(r'src="([^"]+)"', t).group(1) for t in tags if "src=" in t]
                == ["leaflet/leaflet.js", "app.js", "push.js", "slot.js"] and all(" defer " in t for t in tags if "src=" in t))
    ok &= check("geen referrer naar derden", '<meta name="referrer" content="no-referrer">' in uit)
    ok &= check("het pakket is geldige JSON zonder <", "<" not in json.dumps(pakket(uit)))
    ok &= check("tegelhost in ui/app.js = de host in de CSP, en geen andere https-host in de JavaScript",
                set(re.findall(r"https?://[^/'\"\s]+", funda_ui.UI_JS + funda_ui.SLOT_JS + funda_ui.PUSH_JS))
                == {"https://" + fr.TEGEL_HOST})
    ok &= check("tegels: alleen de herkomst als referrer (OSM weigert tegels zonder)", "referrerPolicy:'origin'" in funda_ui.UI_JS)
    return ok


def test_slot_js() -> bool:
    print("test: ui/slot.js (sleutel bewaren, migratie, frame, vergrendelen)")
    js = funda_ui.SLOT_JS
    ok = check("DecompressionStream en melding voor een te oude browser", 'DecompressionStream("gzip")' in js
               and "class TeOud" in js and "Werk je iPhone bij naar iOS 16.4 of nieuwer." in js)
    ok &= check("PBKDF2 alleen voor deriveBits, met het app-zout en de iteraties uit het pakket",
                'importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveBits"])' in js
                and 'salt:b64(P.app_zout), iterations:P.iters, hash:"SHA-256"' in js)
    ok &= check("hoofdsleutel: niet-exporteerbare HKDF-sleutel, alleen deriveKey",
                'importKey("raw", bits, "HKDF", false, ["deriveKey"])' in js and "bits.fill(0)" in js)
    ok &= check("runsleutel: HKDF met het run-zout en de versiestring, alleen decrypt",
                '{name:"HKDF", hash:"SHA-256", salt:b64(P.zout), info:new TextEncoder().encode(P.info)}' in js
                and '{name:"AES-GCM", length:256}, false, ["decrypt"]' in js)
    ok &= check("opvulling eraf via de lengte", "getUint32(0)" in js and "vol.subarray(4, 4 + n)" in js)
    ok &= check("sleutel in IndexedDB, 30 dagen, onder een nieuwe naam", "indexedDB.open(" in js and "s.put({sleutel" in js
                and 'ID = "hoofd_v2"' in js and "DAGEN = 30" in js)
    ok &= check("alleen een sleutel van het nieuwe soort telt", 'k.algorithm.name === "HKDF"' in js and "k.extractable === false" in js)
    ok &= check("migratie: oude basissleutel en oud wachtwoord gewist, niet gebruikt",
                'OUD_ID = "basis"' in js and "s.delete(OUD_ID)" in js and "localStorage.removeItem(OUD_PW)" in js
                and 'sessionStorage.removeItem("funda_pw")' in js)
    ok &= check("nooit het wachtwoord bewaren: localStorage alleen voor de teller van foute pogingen",
                js.count("localStorage.getItem(") == 1 and "localStorage.getItem(POGINGEN)" in js
                and js.count("localStorage.setItem(") == 1 and "localStorage.setItem(POGINGEN, JSON.stringify(p))" in js
                and "sessionStorage.setItem" not in js and "pw.value" not in js.split("function zetPogingen")[1].split("function pauzeSeconden")[0])
    ok &= check("pauze na foute pogingen: vier vrij, dan 30 s en verdubbelen tot een kwartier, ook na herladen",
                "GRATIS = 4, PAUZE_S = 30, PAUZE_MAX_S = 900" in js and "if(pauzeer()) return;" in js
                and "pauzeer();   // een lopende pauze overleeft herladen" in js and "zetPogingen({n: 0, tot: 0});" in js)
    ok &= check("in een frame niet ontgrendelen, met een melding", "window.top !== window.self" in js
                and "Dit rapport opent niet binnen een andere pagina." in js)
    ok &= check("vergrendel: sleutel weg en herladen", "vergrendel: async () => { try { await wis(); }" in js
                and "location.reload()" in js)
    ok &= check("na ontsleutelen fundaAfterReportLoad", "window.fundaAfterReportLoad()" in js)
    ok &= check("service worker wordt geregistreerd", "navigator.serviceWorker.register('service-worker.js'" in js)
    ok &= check("push.js: sleutel uit de meta-tag, geen losse kleur", 'meta[name="funda-push-key"]' in funda_ui.PUSH_JS
                and "verbergAlsIngesteld" in funda_ui.PUSH_JS and "style.color" not in funda_ui.PUSH_JS)
    return ok


# Het echte ui/slot.js in node, met een DOM van niets: formulier invullen, submit, en de body lezen.
NODE_SLOT = r"""
const fs = require('fs');
const invoer = JSON.parse(fs.readFileSync(0, 'utf8'));
const els = {};
function el(id){
  return els[id] || (els[id] = {id, hidden:false, textContent:'', value:'', checked:false, disabled:false, type:'password', h:{},
    addEventListener(t, f){ this.h[t] = f; }, setAttribute(){}, removeAttribute(){}, focus(){}, innerHTML:''});
}
globalThis.window = globalThis; globalThis.self = globalThis; globalThis.top = invoer.frame ? {} : globalThis;
globalThis.document = {getElementById: el};
globalThis.location = {protocol: 'file:', reload(){}};
el('slot-data').textContent = JSON.stringify(invoer.pakket);
(0, eval)(fs.readFileSync(invoer.slot_js, 'utf8'));
(async () => {
  await new Promise(r => setTimeout(r, 50));
  const uit = [];
  for (const pw of invoer.wachtwoorden) {
    el('pw').value = pw; el('content').innerHTML = '';
    if (el('slot-form').h.submit) await el('slot-form').h.submit({preventDefault(){}});
    uit.push({body: el('content').innerHTML, fout: el('err').textContent, knop_uit: el('btn').disabled});
  }
  console.log(JSON.stringify(uit));
  process.exit(0);   // de aftelklok van een pauze houdt node anders in leven
})().catch(e => { console.error(e); process.exit(1); });
"""


def _node_slot(html: str, wachtwoorden: list[str], frame: bool = False):
    invoer = {"pakket": pakket(html), "wachtwoorden": wachtwoorden, "frame": frame,
              "slot_js": str(funda_ui.UI_DIR / "slot.js")}
    r = subprocess.run(["node", "-e", NODE_SLOT], input=json.dumps(invoer), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, r.stderr[-300:]
    return json.loads(r.stdout), ""


def test_slot_js_node() -> bool:
    print("test: het echte ui/slot.js ontsleutelt wat Python versleutelt (node)")
    if not shutil.which("node"):
        print("  (node niet gevonden; overgeslagen)")
        return True
    body = BODY + "é€ " * 50
    uit, fout = _node_slot(fr.beveilig_html(body, WACHTWOORD), ["fout", WACHTWOORD])
    if uit is None:
        return check("node draait slot.js", False, fout)
    ok = check("fout wachtwoord: melding, geen body", uit[0]["body"] == "" and "klopt niet" in uit[0]["fout"])
    ok &= check("goed wachtwoord: de body, byte voor byte", uit[1]["body"] == body, uit[1]["fout"])
    uit, fout = _node_slot(fr.beveilig_html(body, WACHTWOORD), ["a", "b", "c", "d", WACHTWOORD])
    ok &= check("vier foute pogingen: nog geen pauze, het goede wachtwoord opent", uit is not None and uit[4]["body"] == body, fout)
    uit, fout = _node_slot(fr.beveilig_html(body, WACHTWOORD), ["a", "b", "c", "d", "e", WACHTWOORD])
    ok &= check("vijfde foute poging: pauze, ook het goede wachtwoord opent nu niet", uit is not None
                and "Te veel foute pogingen" in uit[4]["fout"] and uit[5]["body"] == ""
                and "Te veel foute pogingen" in uit[5]["fout"] and uit[5]["knop_uit"], fout or str(uit and uit[4:]))
    uit, fout = _node_slot(fr.beveilig_html(body, WACHTWOORD, gz=False), [WACHTWOORD])
    ok &= check("gz 0: zonder uitpakken de body", uit is not None and uit[0]["body"] == body, fout)
    uit, fout = _node_slot(fr.beveilig_html(body, WACHTWOORD), [WACHTWOORD], frame=True)
    ok &= check("in een frame: geen body, wel de melding, knop uit", uit is not None and uit[0]["body"] == ""
                and "binnen een andere pagina" in uit[0]["fout"] and uit[0]["knop_uit"], fout)
    return ok


def test_geen_onversleuteld_in_ci() -> bool:
    print("test: FUNDA_REQUIRE_ENCRYPTION=1 zonder wachtwoord schrijft niets")
    oud = (fr.UITVOER_DIR, fr.PWA_PASSWORD_FILE, os.environ.get("FUNDA_REQUIRE_ENCRYPTION"))
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        fr.UITVOER_DIR = Path(tmp)
        fr.PWA_PASSWORD_FILE = Path(tmp) / "bestaat-niet.txt"
        os.environ["FUNDA_REQUIRE_ENCRYPTION"] = "1"
        try:
            fr.schrijf_pwa_assets([])
            ok &= check("RuntimeError", False)
        except RuntimeError:
            ok &= check("RuntimeError", True)
        finally:
            fr.UITVOER_DIR, fr.PWA_PASSWORD_FILE = oud[0], oud[1]
            if oud[2] is None:
                os.environ.pop("FUNDA_REQUIRE_ENCRYPTION", None)
            else:
                os.environ["FUNDA_REQUIRE_ENCRYPTION"] = oud[2]
        ok &= check("niets geschreven", not any(Path(tmp).iterdir()), str(list(Path(tmp).iterdir())))
    return ok


OUDE_KLEUREN = ["#154c34", "#c9a23c", "#f3efe6", "#ffcd00", "#003d86"]


def _png_pixel(pad: Path, x: int = 0, y: int = 0) -> tuple[int, ...]:
    """Eén pixel uit een PNG zoals _write_png_icon hem schrijft (RGBA, filter 0)."""
    import struct
    import zlib
    data = pad.read_bytes()
    breed = struct.unpack(">I", data[16:20])[0]
    idat, i = b"", 8
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        if data[i + 4:i + 8] == b"IDAT":
            idat += data[i + 8:i + 8 + n]
        i += 12 + n
    rauw = zlib.decompress(idat)
    rij = rauw[y * (breed * 4 + 1) + 1:(y + 1) * (breed * 4 + 1)]
    return tuple(rij[x * 4:x * 4 + 4])


def test_pwa_uiterlijk() -> bool:
    print("test: service worker v6, manifest zonder voornaam, eigen palet, slotscherm uit ui/slot.html")
    sw = fr.PWA_SERVICE_WORKER
    ok = check("service worker: cache funda-shortlist-v6", "const CACHE = 'funda-shortlist-v6';" in sw)
    assets = re.findall(r"'([^']+)'", re.search(r"const ASSETS = \[(.*?)\];", sw, re.S).group(1))
    nodig = {"./", "index.html", "manifest.json", "icon.svg", "favicon.svg", "apple-touch-icon.png", "icon-512.png",
             *(n for n in fr.STATISCH if n != "leaflet/LICENSE")}
    ok &= check("service worker: alle statische bestanden in ASSETS", set(assets) == nodig, str(sorted(nodig ^ set(assets))))
    ok &= check("service worker: alleen same-origin GET's in de cache",
                "if (e.request.method !== 'GET') return;" in sw and "if (url.origin !== location.origin) return;" in sw
                and sw.index("url.origin !== location.origin") < sw.index("e.respondWith")
                and "resp.ok && resp.type === 'basic'" in sw and sw.count(".put(") == 1)
    ok &= check("service worker: index.html alleen als terugval voor een navigatie", "e.request.mode === 'navigate'" in sw)
    m = json.loads(fr.PWA_MANIFEST)
    ok &= check("manifest: Woningrapport / Woningen", m["name"] == "Woningrapport" and m["short_name"] == "Woningen",
                f"{m['name']} / {m['short_name']}")
    ok &= check("manifest: geen merknaam in de naam", "Funda" not in m["name"] and "Funda" not in m["short_name"])
    ok &= check("manifest: kleuren uit het palet", m["theme_color"] == funda_ui.THEME_COLOR
                and m["background_color"] == funda_ui.ACHTERGROND, f"{m['theme_color']} {m['background_color']}")
    uit = fr.beveilig_html(BODY, WACHTWOORD)
    ok &= check("slotscherm: <label for=\"pw\"> en role=\"alert\"", '<label for="pw">' in uit and 'role="alert"' in uit)
    ok &= check("slotscherm: theme-color uit het palet",
                f'<meta name="theme-color" content="{funda_ui.THEME_COLOR}">' in uit)
    ok &= check("slotscherm: titel Woningrapport, geen voornaam", "<title>Woningrapport</title>" in uit)
    ok &= check("slotscherm: CSS en JS als bestanden, niet in de wrapper", 'href="app.css"' in uit and 'href="slot.css"' in uit
                and funda_ui.UI_CSS[:200] not in uit and funda_ui.UI_JS[:200] not in uit and len(uit) < 20_000, str(len(uit)))
    oud_sleutel = fr.WEB_PUSH_PUBLIC_KEY
    fr.WEB_PUSH_PUBLIC_KEY = "BFictieve<Sleutel"
    try:
        met_push = fr.beveilig_html(BODY, WACHTWOORD)
        html_pwa = fr.render_html([], {}, is_pwa=True)
    finally:
        fr.WEB_PUSH_PUBLIC_KEY = oud_sleutel
    ok &= check("push: de publieke sleutel als meta-tag in de <head>, ge-escaped; zonder sleutel geen tag",
                '<meta name="funda-push-key" content="BFictieve&lt;Sleutel">' in met_push.split("</head>")[0]
                and "funda-push-key" not in uit)
    html = fr.render_html([], {})
    ok &= check("lokale HTML: Leaflet uit docs/leaflet/, geen unpkg, geen referrer",
                'href="docs/leaflet/leaflet.css"' in html and 'src="docs/leaflet/leaflet.js"' in html and "unpkg" not in html
                and '<meta name="referrer" content="no-referrer">' in html)
    ok &= check("onversleutelde PWA (lokaal, zonder wachtwoord): Leaflet uit leaflet/, push-meta en push-JS",
                'src="leaflet/leaflet.js"' in html_pwa and "unpkg" not in html_pwa and "funda-push-key" in html_pwa
                and funda_ui.PUSH_JS[:200] in html_pwa and html_pwa.index(funda_ui.UI_JS[:200]) < html_pwa.index(funda_ui.PUSH_JS[:200]))
    ok &= check("lokale HTML: theme-color, color-scheme en titel",
                f'content="{funda_ui.THEME_COLOR}"' in html and '<meta name="color-scheme" content="light dark">' in html
                and "<title>Woningrapport, " in html)
    for naam, tekst in (("icon.svg", fr.PWA_ICON_SVG), ("favicon.svg", fr.PWA_FAVICON_SVG), ("wrapper", uit),
                        ("manifest", fr.PWA_MANIFEST), ("lokale HTML", html)):
        ok &= check(f"{naam}: geen oude kleuren, geen geel of merkblauw",
                    not any(k in tekst.lower() for k in OUDE_KLEUREN), naam)
    ok &= check("iconen in het inktblauw van de topbalk", funda_ui.THEME_COLOR in fr.PWA_ICON_SVG
                and funda_ui.THEME_COLOR in fr.PWA_FAVICON_SVG)
    with tempfile.TemporaryDirectory() as tmp:
        pad = Path(tmp) / "icon.png"
        fr._write_png_icon(pad, 180)
        kleur = "#" + "".join(f"{c:02x}" for c in _png_pixel(pad)[:3])
        ok &= check("PNG-icoon: hoek in het inktblauw van de topbalk (vult het vlak)", kleur == funda_ui.THEME_COLOR, kleur)
        ok &= check("PNG-icoon: midden wit (het huis)", _png_pixel(pad, 70, 120)[:3] == (255, 255, 255),
                    str(_png_pixel(pad, 70, 120)))
    return ok


def test_pwa_assets() -> bool:
    print("test: schrijf_pwa_assets met wachtwoord schrijft alles en versleutelt index.html")
    oud = (fr.UITVOER_DIR, fr.PWA_PASSWORD_FILE)
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        fr.UITVOER_DIR = Path(tmp)
        fr.PWA_PASSWORD_FILE = Path(tmp) / "pw.txt"
        fr.PWA_PASSWORD_FILE.write_text(WACHTWOORD + "\n", encoding="utf-8")
        try:
            fr.schrijf_pwa_assets([], {"tijdstip": "2026-11-06T10:34:00+01:00"})
        finally:
            fr.UITVOER_DIR, fr.PWA_PASSWORD_FILE = oud
        docs = Path(tmp) / "docs"
        namen = sorted(str(p.relative_to(docs)).replace(os.sep, "/") for p in docs.rglob("*") if p.is_file())
        ok &= check("alle bestanden", namen == sorted(["apple-touch-icon.png", "favicon.svg", "icon-512.png", "icon.svg",
                                                       "index.html", "manifest.json", "service-worker.js", *fr.STATISCH]),
                    ", ".join(namen))
        ok &= check("CSS en JavaScript in docs/ gelijk aan ui/", all(
            (docs / doel).read_bytes() == (funda_ui.UI_DIR / bron).read_bytes() for doel, bron in fr.STATISCH.items()))
        for naam, verwacht in LEAFLET_SHA256.items():
            som = base64.b64encode(hashlib.sha256((docs / "leaflet" / naam).read_bytes()).digest()).decode()
            ok &= check(f"leaflet/{naam}: ongewijzigd uit het npm-pakket leaflet@{fr.LEAFLET_VERSIE}", som == verwacht, som)
        ok &= check("Leaflet: versie en licentie erbij", f'version="{fr.LEAFLET_VERSIE}"' in (docs / "leaflet/leaflet.js").read_text(encoding="utf-8")
                    and "BSD 2-Clause" in (docs / "leaflet/LICENSE").read_text(encoding="utf-8"))
        ok &= check("Leaflet-CSS verwijst niet naar buiten", "http" not in re.sub(r"/\*.*?\*/", "", (docs / "leaflet/leaflet.css").read_text(encoding="utf-8"), flags=re.S))
        index = (docs / "index.html").read_text(encoding="utf-8")
        ok &= check("index.html: elk script en elke stylesheet staat in docs/",
                    all((docs / b).is_file() for b in re.findall(r'<(?:script|link)\b[^>]*?(?:src|href)="([^"]*)"', index)))
        body = ontsleutel((docs / "index.html").read_text(encoding="utf-8"), WACHTWOORD)
        ok &= check("index.html ontsleutelt tot de nieuwe UI", 'id="woning-data"' in body and 'class="app-top' in body)
    return ok


def main() -> int:
    resultaten = [test_roundtrip(), test_sleutelopbouw(), test_opvulling(), test_wrapper(), test_slot_js(),
                  test_slot_js_node(), test_geen_onversleuteld_in_ci(), test_pwa_uiterlijk(), test_pwa_assets()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print(f"{resultaten.count(False)} van {len(resultaten)} testgroepen gefaald.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
