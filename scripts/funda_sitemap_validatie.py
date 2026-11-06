"""Controleer de sitemaproute tegen de echte funda, end-to-end door main().

Drie delen, samen binnen ~55 verzoeken:

A. `SitemapZoeker` met de echte pyfunda-client en een LEGE cache (dus het
   scenario van de eerste run): robots.txt, index en koop-sitemaps ophalen,
   kandidaten tellen en de nieuwste VALIDATIE_MAX_VERKENNEN verrijken.
B. Die zoeker door `funda_zoek.main()` halen (prijsbanden, sorteringen,
   paginering, stad/buurt/type-filters, detail-check), met rapport en push
   uitgeschakeld. Zo is het drop-in-gedrag getest, niet alleen de klasse.
   Daarna een tweede run met dezelfde cache en nul verkenning: dat is de
   tweede run van een dag (zelfde sitemap-snapshot), en laat zien wat een
   run kost als er niets nieuws is.
C. Kosten van de opstart: op welke plek (nieuwste lastmod eerst) staan de
   woningen die de mailroute tussen 17 okt en 4 nov toonde, en een
   steekproef uit het oudere aanbod om te schatten welk deel nog beschikbaar
   is en in de doelmarkt valt.

Print alleen publieke funda-gegevens. Leest geen funda_personal.json: de
doelmarkt staat hieronder als publieke zoekcriteria, de postcode blijft de dummy.
Publiceert niets: genereer_rapport staat uit en main() krijgt --no-push.
"""

from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HIER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HIER))

PRIJS_MIN, PRIJS_MAX, M2_MIN = 230_000, 310_000, 55
MAX_VERKENNEN = int(os.environ.get("VALIDATIE_MAX_VERKENNEN") or 30)
STEEKPROEF = int(os.environ.get("VALIDATIE_STEEKPROEF") or 0)
PAUZE = 0.6

# Zelfde lijst als in scripts/funda_sitemap_probe.py (publieke funda-nummers).
MAIL_SEEDS = {
    "80017735", "44656002", "44650476", "44652001", "44546930", "44548508",
    "44653845", "44650043", "44547026", "80018360", "44668459", "44541872",
    "44654337", "80015892", "44657010", "80010543", "44533983", "44655308",
    "44541764", "80015683", "44549244", "44541033", "80014298", "44546295",
    "44524505", "80019364", "44656881", "80017514", "44651359", "80997843",
    "44659952", "44655950", "44650472", "44546400", "80023531",
}


def main() -> int:
    nu = datetime.now(timezone.utc)
    print(f"Sitemap-validatie, start {nu.isoformat(timespec='seconds')}\n")

    sys.argv = [sys.argv[0], "--no-push", "--no-open"]
    os.environ["FUNDA_ZOEK_METHODE"] = "sitemap"
    import funda_zoek as fz
    from funda_sitemap_zoek import SitemapZoeker, in_doelmarkt, parse_datum

    fz.PRIJS_MIN, fz.PRIJS_MAX, fz.M2_MIN = PRIJS_MIN, PRIJS_MAX, M2_MIN
    fz.genereer_rapport = None  # geen rapport, dus ook geen nominatim/OSRM-calls

    client = fz.Funda()
    cache = Path(tempfile.mkdtemp()) / "funda_sitemap_cache.json"
    def maak(max_verkennen: int) -> SitemapZoeker:
        return SitemapZoeker(
            client, steden=("den-haag", "voorburg"), prijs_min=PRIJS_MIN, prijs_max=PRIJS_MAX,
            m2_min=M2_MIN, max_verkennen=max_verkennen, overslaan=fz._sitemap_overslaan,
            cache_pad=cache, pauze=PAUZE, log=fz.log,
        )

    zoeker = maak(MAX_VERKENNEN)
    fz.kies_zoeker = lambda _f: (zoeker, "sitemap")

    # --- A + B: end-to-end door main() ---------------------------------------
    print("=== A+B. main() met de sitemapzoeker (lege cache = eerste run) ===")
    t0 = time.monotonic()
    try:
        fz.main()
        uitkomst = "main() normaal afgerond"
    except SystemExit as exc:
        uitkomst = f"main() stopte met exit {exc.code}"
    duur = time.monotonic() - t0
    print(f"\n{uitkomst} in {duur:.0f}s")
    st = zoeker.statistiek
    print("Statistiek zoeker: " + json.dumps(st, ensure_ascii=False))
    nieuwste = parse_datum(st.get("nieuwste_lastmod"))
    if nieuwste:
        print(f"Nieuwste lastmod in de doelsteden: {nieuwste.isoformat()} = "
              f"{(nu - nieuwste).total_seconds() / 3600:.1f} uur voor deze run")
    samenvatting = HIER / "funda_run_summary.json"
    if samenvatting.exists():
        s = json.loads(samenvatting.read_text(encoding="utf-8"))
        print("Run-summary: " + json.dumps({k: (len(v) if isinstance(v, list) else v)
                                            for k, v in s.items()}, ensure_ascii=False))
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))["woningen"]
        print(f"Cache na de run: {len(c)} woningen, waarvan "
              f"{sum(1 for v in c.values() if zoeker._is_doel(v['velden']))} in de doelmarkt "
              f"na filters; {cache.stat().st_size} bytes")

    # --- B2: tweede run, zelfde snapshot --------------------------------------
    print("\n=== B2. Tweede run met dezelfde cache, zonder verkenning ===")
    zoeker2 = maak(0)
    fz.kies_zoeker = lambda _f: (zoeker2, "sitemap")
    t0 = time.monotonic()
    try:
        fz.main()
        uitkomst = "main() normaal afgerond"
    except SystemExit as exc:
        uitkomst = f"main() stopte met exit {exc.code}"
    print(f"\n{uitkomst} in {time.monotonic() - t0:.0f}s")
    print("Statistiek zoeker run 2: " + json.dumps(
        {k: v for k, v in zoeker2.statistiek.items() if k != "types_in_steden"}, ensure_ascii=False))

    # --- C: kosten van de opstart --------------------------------------------
    print("\n=== C. Opstartkosten ===")
    kand = zoeker.kandidaten
    print(f"Kandidaten (appartement of onbekend type, Den Haag+Voorburg): {len(kand)}")
    per_dag = Counter()
    for k in kand:
        d = parse_datum(k["lastmod"])
        if d:
            per_dag[d.date().isoformat()] += 1
    print("Kandidaten per lastmod-dag (laatste 10): " +
          json.dumps(dict(sorted(per_dag.items())[-10:])))
    posities = {k["url_id"]: i for i, k in enumerate(kand)}
    seedpos = sorted(posities[s] for s in MAIL_SEEDS if s in posities)
    print(f"Mail-seeds in de kandidatenlijst: {len(seedpos)} van {len(MAIL_SEEDS)}")
    if seedpos:
        print(f"  plek (0 = nieuwste lastmod): min {seedpos[0]}, mediaan "
              f"{seedpos[len(seedpos) // 2]}, max {seedpos[-1]}")
        for grens in (50, 100, 200, 400, 800):
            print(f"  binnen de eerste {grens:4}: {sum(1 for p in seedpos if p < grens)}")

    oud = kand[MAX_VERKENNEN:]
    if oud and STEEKPROEF:
        rnd = random.Random(20261106)
        monster = rnd.sample(oud, min(STEEKPROEF, len(oud)))
        print(f"\nSteekproef van {len(monster)} uit de {len(oud)} niet-verkende kandidaten:")
        n_ok = n_beschikbaar = n_doel = 0
        for k in monster:
            time.sleep(PAUZE)
            try:
                d = client.get_listing(f"https://www.funda.nl{k['pad']}").data
            except Exception as exc:  # noqa: BLE001
                print(f"  {k['url_id']} MISLUKT: {type(exc).__name__}: {str(exc)[:80]}")
                continue
            n_ok += 1
            doel = in_doelmarkt(d, PRIJS_MIN, PRIJS_MAX, M2_MIN)
            n_beschikbaar += d.get("status") == "available"
            n_doel += doel
            print(f"  {k['url_id']} {d.get('title')}, {d.get('city')} | EUR {d.get('price')} | "
                  f"{d.get('living_area')} m2 | {d.get('status')} | publicatie {d.get('publication_date')} "
                  f"| lastmod {k['lastmod']} | doelmarkt={doel}")
        print(f"Steekproef: {n_ok} opgehaald, {n_beschikbaar} beschikbaar, {n_doel} in doelmarkt.")

    print("\nKlaar. Geen rapport geschreven, niets gepusht.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
