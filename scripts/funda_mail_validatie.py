"""Controleer de mail-parser tegen een échte funda-notificatiemail.

De parser in funda_mail_bron.py is gebouwd op het woning-URL-patroon, dat
gemeten is. Hoe de notificatiemail van een bewaarde zoekopdracht eruitziet is dat
níet: bij het schrijven stond er geen bewaarde zoekopdracht aan, dus was er geen
echte mail. Dit script dicht dat gat.

Gebruik: bewaar één notificatiemail als bestand (in Gmail: drie puntjes ->
"Origineel weergeven" -> kopiëren naar een .txt of .eml) en draai:

    python scripts/funda_mail_validatie.py pad/naar/mail.eml
    python scripts/funda_mail_validatie.py pad/naar/mail.eml --volg-redirects

Zonder woningen maar met `links.funda.nl`-links zegt het script dat ook: dan zit
de woninglink achter funda's click-tracker en helpt `--volg-redirects`. Dat volgen
is een echte klik in die tracker, dus het staat niet standaard aan.

Het script laat zien welke woningen eruit komen, en - als er netwerk is naar het
detail-endpoint - of die ook te verrijken zijn.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from funda_mail_bron import (  # noqa: E402
    MailBron,
    vind_tracking_links,
    woningen_uit_mail,
)

VERPLICHT = ("global_id", "city", "neighbourhood", "price", "living_area")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    vlaggen = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 1 or vlaggen - {"--volg-redirects"}:
        print(__doc__)
        return 2
    volg = "--volg-redirects" in vlaggen

    pad = Path(args[0])
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

    woningen = woningen_uit_mail(ruw, volg_redirects=volg,
                                 log=lambda b: print(f"  [log] {b}"))
    print(f"\nwoningen gevonden: {len(woningen)}")
    for pad_, tiny in woningen:
        print(f"  {tiny}  {pad_}")

    if not woningen:
        # Twee heel verschillende oorzaken, dus hier uit elkaar gehouden.
        tracking = vind_tracking_links(ruw)
        if tracking:
            print(f"\nGEEN directe woninglinks, maar wel {len(tracking)} ondoorzichtige "
                  f"tracking-link(s), bijvoorbeeld:\n  {tracking[0][:110]}")
            print("\nDit is het verpakte geval: funda zet de woninglink achter zijn "
                  "click-tracker. Draai dan met --volg-redirects om die te volgen "
                  "(dat is een echte klik in funda's tracker, dus niet standaard aan).")
            return 1
        print("\nFOUT: geen woningen en geen tracking-links. Dit is of een mail zonder "
              "nieuw aanbod, of de opmaak wijkt af van wat de parser verwacht; stuur "
              "een stukje van de HTML mee zodat de parser bijgewerkt kan worden.")
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
