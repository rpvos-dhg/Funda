"""Oude Actions-cache samenvoegen met de huidige state (migratie 6 nov 2026).

Waarom: de versie van een Actions-cache hangt af van de lijst `path`-regels. PR #13
voegde funda_thuis_coords.json en funda_sitemap_cache.json aan die lijst toe, en
daarna vond `restore-keys: funda-state-` de oude caches niet meer ("Cache not
found"). De opstartrun van 6 nov begon daardoor met een lege state: 0 gezien,
geen tracking, geen blacklist.

De workflow haalt de oude cache apart op met de oude padenlijst en zet de
bestanden in `oude_state/`. Dit script voegt ze samen met wat de nieuwe cache gaf.
Samenvoegen is idempotent: twee keer draaien geeft hetzelfde resultaat. Er
verdwijnt nooit iets uit de huidige state.

Print alleen aantallen: de Actions-log van deze publieke repo is leesbaar voor
iedereen, en woning-id's uit de eigen tracking verraden zoekgebied en budget.

Gebruik: python scripts/state_migratie.py [oude_map] [doelmap]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BESTANDEN = ("funda_seen_ids.json", "funda_tracking.json", "funda_werk_coords.json",
             "funda_enrichment_cache.json", "funda_blacklist.json")


def lees(pad: Path, standaard):
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except Exception:
        return standaard


def schrijf(pad: Path, data) -> None:
    pad.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def unie(nieuw, oud) -> list:
    """Lijst-unie van twee json-lijsten (seen-ids, blacklist), gesorteerd."""
    waarden = set()
    for bron in (nieuw, oud):
        if isinstance(bron, list):
            waarden.update(str(x) for x in bron)
    return sorted(waarden)


def _prijzen(*bronnen) -> list:
    """Prijsgeschiedenis samenvoegen: op datum, zonder herhaalde gelijke prijs."""
    alle = []
    for bron in bronnen:
        for p in bron or []:
            if isinstance(p, (list, tuple)) and len(p) == 2 and p[0]:
                alle.append([str(p[0]), p[1]])
    alle.sort(key=lambda p: p[0])
    schoon: list = []
    for datum, prijs in alle:
        if schoon and schoon[-1][1] == prijs:
            continue
        schoon.append([datum, prijs])
    return schoon


def merge_tracking(nieuw, oud) -> dict:
    """Per woning: nieuw wint (url, weg, pool_fout), datums en prijzen gecombineerd."""
    nieuw = nieuw if isinstance(nieuw, dict) else {}
    oud = oud if isinstance(oud, dict) else {}
    uit = {k: v for k, v in oud.items()}
    for sleutel, rec in nieuw.items():
        o = uit.get(sleutel)
        if not isinstance(o, dict) or not isinstance(rec, dict):
            uit[sleutel] = rec
            continue
        samen = {**o, **rec}
        eerst = [d for d in (o.get("first_seen"), rec.get("first_seen")) if d]
        laatst = [d for d in (o.get("last_seen"), rec.get("last_seen")) if d]
        if eerst:
            samen["first_seen"] = min(eerst)
        if laatst:
            samen["last_seen"] = max(laatst)
        if rec.get("pub_datum") or o.get("pub_datum"):
            samen["pub_datum"] = rec.get("pub_datum") or o.get("pub_datum")
        samen["prices"] = _prijzen(o.get("prices"), rec.get("prices"))
        uit[sleutel] = samen
    return uit


def merge_dict(nieuw, oud) -> dict:
    """Platte dict: nieuw wint (werk-coördinaten)."""
    return {**(oud if isinstance(oud, dict) else {}), **(nieuw if isinstance(nieuw, dict) else {})}


def merge_verrijking(nieuw, oud) -> dict:
    """Verrijkingscache per sectie samenvoegen; nieuw wint per sleutel."""
    nieuw = nieuw if isinstance(nieuw, dict) else {}
    oud = oud if isinstance(oud, dict) else {}
    uit = {}
    for sectie in list(oud) + [s for s in nieuw if s not in oud]:
        a, b = oud.get(sectie), nieuw.get(sectie)
        uit[sectie] = merge_dict(b, a) if isinstance(a, dict) or isinstance(b, dict) else (b if b is not None else a)
    return uit


def migreer(oude_map: Path, doel: Path) -> dict:
    gevonden = [n for n in BESTANDEN if (oude_map / n).exists()]
    if not gevonden:
        print("Migratie: geen oude state gevonden; niets samengevoegd.")
        return {}
    oud = {n: lees(oude_map / n, None) for n in gevonden}
    nu = {n: lees(doel / n, None) for n in BESTANDEN}

    samengevoegd = {
        "funda_seen_ids.json": unie(nu["funda_seen_ids.json"], oud.get("funda_seen_ids.json")),
        "funda_tracking.json": merge_tracking(nu["funda_tracking.json"], oud.get("funda_tracking.json")),
        "funda_werk_coords.json": merge_dict(nu["funda_werk_coords.json"], oud.get("funda_werk_coords.json")),
        "funda_enrichment_cache.json": merge_verrijking(nu["funda_enrichment_cache.json"],
                                                        oud.get("funda_enrichment_cache.json")),
        "funda_blacklist.json": unie(nu["funda_blacklist.json"], oud.get("funda_blacklist.json")),
    }
    tellingen = {}
    for naam, data in samengevoegd.items():
        bron_oud, bron_nu = oud.get(naam), nu.get(naam)
        if bron_oud is None and bron_nu is None:
            continue  # bestond nergens; niet aanmaken
        schrijf(doel / naam, data)
        tellingen[naam] = (len(bron_oud or []), len(bron_nu or []), len(data))
    regels = ", ".join(f"{n.removeprefix('funda_').removesuffix('.json')} {o}+{h}->{s}"
                       for n, (o, h, s) in tellingen.items())
    print(f"Migratie: oude state samengevoegd (oud+huidig->samen): {regels}.")
    return tellingen


if __name__ == "__main__":
    oude_map = Path(sys.argv[1] if len(sys.argv) > 1 else "oude_state")
    doel = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    migreer(oude_map, doel)
