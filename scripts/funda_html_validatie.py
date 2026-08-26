"""Validatie van de HTML-zoekfallback tegen de echte funda.nl.

De offline tests (test_funda_html.py) draaien op een nagebouwde fixture. Dit
script controleert of het ook op de échte pagina werkt: haalt één zoekpagina op,
parseert de kaarten, verrijkt er een paar via het detail-endpoint en laat zien
welke velden gevuld raken.

Gebruikt geen persoonlijke gegevens: vaste voorbeeldzoekopdracht in Den Haag.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from funda import Funda  # noqa: E402

from funda_html_zoek import HtmlZoeker, bouw_zoek_url, parse_kaarten  # noqa: E402

GEBIED = "den-haag"
STRAAL = 5
PRIJS_MIN = 230_000
PRIJS_MAX = 310_000
M2_MIN = 52

# Velden waar de rest van de code op leunt.
VERWACHT = ("global_id", "city", "neighbourhood", "price", "living_area", "energy_label")


def main() -> int:
    zoeker = HtmlZoeker(Funda(), pauze=0.5, log=lambda b: print(f"  [log] {b}"))

    url = bouw_zoek_url(
        gebied=GEBIED,
        radius_km=STRAAL,
        prijs_min=PRIJS_MIN,
        prijs_max=PRIJS_MAX,
        object_type=["apartment"],
        oppervlakte_min=M2_MIN,
    )
    print(f"URL: {url}\n")

    html = zoeker._haal(url)
    kaarten = parse_kaarten(html)
    print(f"kaarten geparseerd: {len(kaarten)}")
    if not kaarten:
        print("FOUT: geen kaarten gevonden; de paginastructuur is waarschijnlijk gewijzigd.")
        return 1

    # Hoe compleet zijn de kaartvelden over de hele pagina?
    for veld in ("tiny_id", "title", "city", "postcode", "price", "living_area"):
        gevuld = sum(1 for k in kaarten if k.get(veld))
        print(f"  {veld}: {gevuld}/{len(kaarten)} gevuld")

    print("\neerste drie kaarten:")
    for k in kaarten[:3]:
        print(f"  {k['tiny_id']} | {k['title']} | {k['postcode']} {k['city']} "
              f"| EUR {k['price']} | {k['living_area']} m2 | nieuw={k['is_nieuw_badge']}")

    # Nu de echte drop-in-route: search_listing verrijkt via het detail-endpoint.
    print("\ndetail-verrijking via search_listing (eerste pagina, max 3):")
    beperkt = HtmlZoeker(Funda(), pauze=0.5, log=lambda b: print(f"  [log] {b}"))
    telling = {"n": 0}

    def alleen_eerste_drie(kaart: dict) -> bool:
        telling["n"] += 1
        return telling["n"] > 3

    beperkt._overslaan = alleen_eerste_drie
    beperkt._haal = lambda _url: html

    resultaten = beperkt.search_listing(
        location=GEBIED,
        radius_km=STRAAL,
        price_min=PRIJS_MIN,
        price_max=PRIJS_MAX,
        object_type=["apartment"],
        area_min=M2_MIN,
        page=0,
    )
    verrijkt = [r.data for r in resultaten if r.data.get("_bron") == "html"]
    print(f"  verrijkt: {len(verrijkt)}")

    fouten = 0
    for d in verrijkt:
        ontbreekt = [v for v in VERWACHT if not d.get(v)]
        print(f"  {d.get('global_id')} | {d.get('title')} | {d.get('city')} "
              f"| buurt={d.get('neighbourhood')} | EUR {d.get('price')} "
              f"| {d.get('living_area')} m2 | label={d.get('energy_label')}")
        if ontbreekt:
            print(f"    ONTBREEKT: {ontbreekt}")
            fouten += 1
        if not (d.get("description") or "").strip():
            print("    ONTBREEKT: description (nodig voor belegging/begane-grond-check)")
            fouten += 1

    if not verrijkt:
        print("FOUT: geen enkele woning verrijkt via het detail-endpoint.")
        return 1
    if fouten:
        print(f"\nFOUT: {fouten} woning(en) met ontbrekende velden.")
        return 1

    print("\nOK: parsing en detail-verrijking werken op de echte pagina.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
