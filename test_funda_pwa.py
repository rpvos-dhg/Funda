"""Offline tests voor de versleutelde PWA: gzip vóór AES-256-GCM en de wrapper.

Ontsleutelt in Python met dezelfde parameters als de browser (PBKDF2-SHA256, 100.000
iteraties, AES-256-GCM, daarna gzip uitpakken). Geen netwerk, fictieve inhoud.

Draaien: python test_funda_pwa.py
"""
from __future__ import annotations

import base64
import gzip
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


def main() -> int:
    resultaten = [test_roundtrip(), test_wrapper(), test_geen_onversleuteld_in_ci()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print(f"{resultaten.count(False)} van {len(resultaten)} testgroepen gefaald.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
