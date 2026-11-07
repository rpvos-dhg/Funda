"""Offline tests voor de versleutelde PWA: gzip vóór AES-256-GCM en de wrapper.

Ontsleutelt in Python met dezelfde parameters als de browser (PBKDF2-SHA256, 100.000
iteraties, AES-256-GCM, daarna gzip uitpakken). Geen netwerk, fictieve inhoud.

Draaien: python test_funda_pwa.py
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import funda_rapport as fr

WACHTWOORD = "test-wachtwoord"
BODY = ("<main><h1>Woningen</h1>" + "".join(f"<article class=\"woning\">Teststraat {i}</article>" for i in range(40))
        + "<p>€ 1.250 · m² · −0,5</p></main>")


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return bool(voorwaarde)


def _const(html: str, naam: str) -> str:
    m = re.search(rf'const {naam}\s*=\s*"?([^";\s]+)"?;', html)
    if not m:
        raise ValueError(f"{naam} niet gevonden")
    return m.group(1)


def ontsleutel(html: str, wachtwoord: str) -> str:
    """Wat de wrapper in de browser doet, in Python: PBKDF2, AES-GCM en (bij GZ 1) gzip."""
    salt, iv, ct = (base64.b64decode(_const(html, n)) for n in ("SALT", "IV", "CT"))
    iters, gz = int(_const(html, "ITERS")), _const(html, "GZ") == "1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters)
    data = AESGCM(kdf.derive(wachtwoord.encode("utf-8"))).decrypt(iv, ct, None)
    return (gzip.decompress(data) if gz else data).decode("utf-8")


def test_roundtrip() -> bool:
    print("test: gzip vóór AES, en terug")
    met = fr.beveilig_html(BODY, WACHTWOORD)
    zonder = fr.beveilig_html(BODY, WACHTWOORD, gz=False)
    ok = check("GZ 1 standaard", _const(met, "GZ") == "1")
    ok &= check("ontsleutelen en uitpakken geeft de body terug", ontsleutel(met, WACHTWOORD) == BODY)
    ok &= check("gz=False: GZ 0 en zonder uitpakken de body", _const(zonder, "GZ") == "0"
                and ontsleutel(zonder, WACHTWOORD) == BODY)
    ok &= check("ingepakt is de ciphertext kleiner", len(_const(met, "CT")) < len(_const(zonder, "CT")),
                f"{len(_const(met, 'CT'))} tegen {len(_const(zonder, 'CT'))}")
    ok &= check("crypto-parameters ongewijzigd: 100.000 iteraties, 16 byte zout, 12 byte IV",
                _const(met, "ITERS") == "100000" and len(base64.b64decode(_const(met, "SALT"))) == 16
                and len(base64.b64decode(_const(met, "IV"))) == 12)
    ok &= check("elke run een nieuw zout en IV", _const(met, "SALT") != _const(fr.beveilig_html(BODY, WACHTWOORD), "SALT"))
    try:
        ontsleutel(met, "fout")
        ok &= check("fout wachtwoord geeft InvalidTag", False)
    except InvalidTag:
        ok &= check("fout wachtwoord geeft InvalidTag", True)
    return ok


def test_wrapper() -> bool:
    print("test: wrapper zonder losse placeholders, met uitpakken en de bestaande haak")
    uit = fr.beveilig_html(BODY, WACHTWOORD)
    rest = sorted(set(re.findall(r"__[A-Z][A-Z_]*__", uit)))
    ok = check("alle placeholders vervangen", not rest, ", ".join(rest))
    ok &= check("DecompressionStream in de wrapper", "DecompressionStream" in uit)
    ok &= check("fundaAfterReportLoad wordt aangeroepen", "fundaAfterReportLoad" in uit)
    ok &= check("melding voor een te oude browser", "iOS 16.4 of nieuwer" in uit)
    ok &= check("eigen scripts komen in de wrapper", "<script>/*eigen*/</script>" in
                fr.beveilig_html(BODY, WACHTWOORD, css="", scripts="<script>/*eigen*/</script>"))
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
    print("test: service worker v5, manifest zonder voornaam, eigen palet, slotscherm uit ui/slot.html")
    import funda_ui
    ok = check("service worker: cache funda-shortlist-v5", "const CACHE = 'funda-shortlist-v5';" in fr.PWA_SERVICE_WORKER)
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
    ok &= check("slotscherm: UI-CSS en UI-JS in de wrapper", funda_ui.UI_CSS[:200] in uit and funda_ui.UI_JS[:200] in uit)
    oud_sleutel = fr.WEB_PUSH_PUBLIC_KEY
    fr.WEB_PUSH_PUBLIC_KEY = "BFictieveSleutel"
    try:
        met_push = fr.beveilig_html(BODY, WACHTWOORD)
    finally:
        fr.WEB_PUSH_PUBLIC_KEY = oud_sleutel
    ok &= check("slotscherm: UI-JS vóór de push-JS (die haakt op fundaAfterReportLoad in)",
                met_push.index(funda_ui.UI_JS[:200]) < met_push.index("var WEB_PUSH_PUBLIC_KEY") < met_push.index("</head>"))
    ok &= check("push-JS: verbergt het blok bij een abonnement, geen losse kleur",
                "verbergAlsIngesteld" in met_push and "style.color" not in met_push)
    html = fr.render_html([], {})
    ok &= check("lokale HTML: theme-color, color-scheme en titel",
                f'content="{funda_ui.THEME_COLOR}"' in html and '<meta name="color-scheme" content="light dark">' in html
                and "<title>Woningrapport, " in html)
    for naam, tekst in (("icon.svg", fr.PWA_ICON_SVG), ("favicon.svg", fr.PWA_FAVICON_SVG), ("wrapper", uit),
                        ("manifest", fr.PWA_MANIFEST), ("lokale HTML", html)):
        ok &= check(f"{naam}: geen oude kleuren, geen geel of ANWB-blauw",
                    not any(k in tekst.lower() for k in OUDE_KLEUREN), naam)
    ok &= check("iconen in het paars van de topbalk", funda_ui.THEME_COLOR in fr.PWA_ICON_SVG
                and funda_ui.THEME_COLOR in fr.PWA_FAVICON_SVG)
    with tempfile.TemporaryDirectory() as tmp:
        pad = Path(tmp) / "icon.png"
        fr._write_png_icon(pad, 180)
        kleur = "#" + "".join(f"{c:02x}" for c in _png_pixel(pad)[:3])
        ok &= check("PNG-icoon: hoek in het paars van de topbalk (vult het vlak)", kleur == funda_ui.THEME_COLOR, kleur)
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
        namen = sorted(p.name for p in docs.iterdir())
        ok &= check("alle bestanden", namen == ["apple-touch-icon.png", "favicon.svg", "icon-512.png", "icon.svg",
                                                "index.html", "manifest.json", "service-worker.js"], ", ".join(namen))
        body = ontsleutel((docs / "index.html").read_text(encoding="utf-8"), WACHTWOORD)
        ok &= check("index.html ontsleutelt tot de nieuwe UI", 'id="woning-data"' in body and 'class="app-top' in body)
    return ok


def main() -> int:
    resultaten = [test_roundtrip(), test_wrapper(), test_geen_onversleuteld_in_ci(), test_pwa_uiterlijk(),
                  test_pwa_assets()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print(f"{resultaten.count(False)} van {len(resultaten)} testgroepen gefaald.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
