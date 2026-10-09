"""Controleer de mail-parser tegen een échte funda-notificatiemail.

De parser in funda_mail_bron.py is gebouwd op het woning-URL-patroon, dat
gemeten is. Hoe funda's notificatiemail eruitziet is dat níet: bij het schrijven
stond er geen bewaarde zoekopdracht aan, dus was er geen echte mail. Dit script
dicht dat gat.

Gebruik: bewaar één notificatiemail als bestand (in Gmail: drie puntjes ->
"Origineel weergeven" -> kopiëren naar een .txt of .eml) en draai:

    python scripts/funda_mail_validatie.py pad/naar/mail.eml

Het script laat zien welke woningen eruit komen, en - als er netwerk is naar het
detail-endpoint - of die ook te verrijken zijn.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from funda_mail_bron import MailBron, vind_woning_links  # noqa: E402

VERPLICHT = ("global_id", "city", "neighbourhood", "price", "living_area")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    pad = Path(argv[1])
    if not pad.exists():
        print(f"FOUT: {pad} bestaat niet.")
        return 1

    # Een .eml is grotendeels platte tekst; losse quoted-printable regels
    # verhinderen het vinden van URL's niet, maar meld het wel.
    ruw = pad.read_bytes().decode("utf-8", errors="replace")
    print(f"bestand: {pad} ({len(ruw)} bytes)")
    if "quoted-printable" in ruw.lower():
        print("let op: mail is quoted-printable; als er links gemist worden, "
              "decodeer de mail eerst.")

    woningen = vind_woning_links(ruw)
    print(f"\nwoningen gevonden: {len(woningen)}")
    for pad_, tiny in woningen:
        print(f"  {tiny}  {pad_}")

    if not woningen:
        print("\nFOUT: geen woningen gevonden. De mailopmaak wijkt af van wat de "
              "parser verwacht; stuur een stukje van de HTML mee zodat "
              "vind_woning_links() bijgewerkt kan worden.")
        return 1

    # Verrijking is optioneel: zonder netwerk naar funda is de linkextractie al
    # het antwoord op de vraag of de parser werkt.
    try:
        from funda import Funda
    except Exception as exc:
        print(f"\npyfunda niet beschikbaar ({exc}); verrijking overgeslagen.")
        return 0

    print("\nverrijken via het detail-endpoint (max 3):")
    bron = MailBron(Funda(), woningen[:3], pauze=0.5, log=lambda b: print(f"  [log] {b}"))
    resultaten = bron.search_listing()
    if not resultaten:
        print("FOUT: geen enkele woning verrijkt; het detail-endpoint doet het "
              "mogelijk ook niet meer.")
        return 1

    fouten = 0
    for r in resultaten:
        d = r.data
        print(f"  {d.get('global_id')} | {d.get('title')} | {d.get('city')} "
              f"| buurt={d.get('neighbourhood')} | EUR {d.get('price')} "
              f"| {d.get('living_area')} m2")
        ontbreekt = [v for v in VERPLICHT if not d.get(v)]
        if not (d.get("description") or "").strip():
            ontbreekt.append("description")
        if ontbreekt:
            print(f"    ONTBREEKT: {ontbreekt}")
            fouten += 1

    if fouten:
        print(f"\nFOUT: {fouten} woning(en) met ontbrekende velden.")
        return 1

    print("\nOK: mail-parser en detail-verrijking werken op een echte mail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
