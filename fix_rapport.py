"""Eenmalige reparatie: herstelt een door sync afgekapte funda_rapport.py.
Draai lokaal:  python fix_rapport.py
Knipt vanaf de laatste functie en zet de volledige, correcte staart terug.
"""
from pathlib import Path

p = Path(__file__).parent / "funda_rapport.py"
src = p.read_text(encoding="utf-8")
anchor = "\ndef schrijf_pwa_assets("
i = src.find(anchor)
if i < 0:
    raise SystemExit("Kan ankerpunt niet vinden; bestand te ver afgekapt. Neem contact op.")

tail = '''
def schrijf_pwa_assets(rijen: list[dict]) -> Path:
    """Genereer alle PWA bestanden in pwa/ subfolder."""
    pwa_dir = Path(__file__).parent / PWA_DIR_NAAM
    pwa_dir.mkdir(exist_ok=True)
    (pwa_dir / "manifest.json").write_text(PWA_MANIFEST, encoding="utf-8")
    (pwa_dir / "service-worker.js").write_text(PWA_SERVICE_WORKER, encoding="utf-8")
    (pwa_dir / "icon.svg").write_text(PWA_ICON_SVG, encoding="utf-8")

    # Lees password en versleutel als beschikbaar.
    inner_html = render_html(rijen, is_pwa=False)  # standalone body
    if PWA_PASSWORD_FILE.exists():
        password = PWA_PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if password:
            beveiligd = beveilig_html(inner_html, password)
            (pwa_dir / "index.html").write_text(beveiligd, encoding="utf-8")
            return pwa_dir

    # Vangrail: in CI (publieke repo) NOOIT onversleuteld publiceren.
    import os
    if os.environ.get("FUNDA_REQUIRE_ENCRYPTION") == "1":
        raise RuntimeError(
            "FUNDA_REQUIRE_ENCRYPTION=1 maar geen wachtwoord gevonden; "
            "weiger om een onversleuteld rapport te schrijven."
        )

    # Fallback (lokaal): onbeveiligd, zelfde tags als eerder.
    print("[rapport] WAARSCHUWING: geen funda_pwa_password.txt gevonden, PWA wordt onversleuteld geschreven!")
    (pwa_dir / "index.html").write_text(render_html(rijen, is_pwa=True), encoding="utf-8")
    return pwa_dir
'''

nieuw = src[:i] + tail
compile(nieuw, "funda_rapport.py", "exec")  # faalt als er nog iets stuk is
p.write_text(nieuw, encoding="utf-8")
print(f"OK: funda_rapport.py hersteld ({len(nieuw)} bytes) en compileert.")
