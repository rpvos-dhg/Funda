"""Doet pyfunda v3.1.5 het weer? Meten, niet aannemen.

v3.1.5 voegde een webroute toe ("Use web search when mobile API is unavailable")
met chrome124, fingerprint-rotatie bij 403 en backoff. De vraag is simpel: komt
die route wél door de blokkade heen vanaf een Actions-runner?

Dit script verwacht dat `import funda` v3.1.5 oplevert, dus draai het met
PYTHONPATH naar een losse install:

    pip install --target /tmp/pf315 "git+https://github.com/0xMH/pyfunda.git@v3.1.5"
    PYTHONPATH=/tmp/pf315 python scripts/funda_v315_probe.py

Niet te combineren met de gepinde v2.9.0 in dezelfde interpreter: zelfde
packagenaam.
"""

from __future__ import annotations

import inspect


def main() -> int:
    try:
        import funda as funda_pkg
    except Exception as exc:
        print(f"import funda mislukt: {type(exc).__name__}: {exc}")
        return 1

    versie = getattr(funda_pkg, "__version__", "onbekend")
    print(f"pyfunda versie: {versie}")
    print(f"pad: {getattr(funda_pkg, '__file__', '?')}")

    Funda = getattr(funda_pkg, "Funda", None)
    if Funda is None:
        print("geen Funda-klasse gevonden")
        return 1

    # v3 heeft een andere API dan v2; zoek de zoekmethode op in plaats van te gokken.
    methodes = [n for n in dir(Funda) if "search" in n.lower() and not n.startswith("_")]
    print(f"zoekmethodes: {methodes}")

    client = Funda()

    for naam in methodes:
        fn = getattr(client, naam)
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        print(f"\n--- {naam}{sig} ---")

        # v3 heeft search_listing omgedoopt naar search(); de generator-variant
        # iter_search slaan we over, die levert hetzelfde via dezelfde route.
        if naam.startswith("iter_"):
            print("  overgeslagen (generator-variant van search)")
            continue

        for poging, kwargs in enumerate((
            {"location": "den-haag", "offering_type": "buy"},
            {"location": "den-haag"},
            {},
        )):
            try:
                res = fn(**kwargs)
            except TypeError as exc:
                print(f"  kwargs {kwargs}: signatuur past niet ({exc})")
                continue
            except Exception as exc:
                print(f"  kwargs {kwargs}: {type(exc).__name__}: {str(exc)[:160]}")
                break
            try:
                aantal = len(res)
            except TypeError:
                aantal = "?"
            print(f"  kwargs {kwargs}: GELUKT, {aantal} resultaten")
            if aantal not in ("?", 0):
                eerste = res[0]
                velden = [v for v in ("address", "price", "urls", "id") if hasattr(eerste, v)]
                print(f"    eerste resultaat heeft velden: {velden}")
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
