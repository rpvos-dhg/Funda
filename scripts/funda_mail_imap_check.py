"""Doet de IMAP-verbinding het, met de echte secrets? Alleen tellen, niets tonen.

Dit controleert de kéten login -> zoeken -> decoderen -> parsen tegen de echte
mailbox. Daar is geen alert-mail voor nodig: elke funda-mail bewijst dat het
transport werkt. Nul woningen is dus een geldige, geslaagde uitkomst.

VEILIGHEID - waarom hier zo weinig geprint wordt:
De Actions-log van een publieke repo is voor iedereen leesbaar, en in een
mailbox zitten dingen die daar niet horen (een wachtwoord-reset-link is er een).
Daarom print dit script uitsluitend getallen en vormen:
- geen onderwerpen, geen afzenders, geen mailtekst;
- geen tracking-links of -tokens, alleen hoeveel er waren;
- wel tiny_id's van woningen: dat zijn publieke funda-nummers.
Houd dat zo bij elke wijziging.

Exit 0 = de keten werkt (ook bij nul woningen). Exit 1 = verbinding, login of
zoeken mislukt, of er is niets ingesteld.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funda_mail_bron import (  # noqa: E402
    vind_tracking_links,
    vind_woning_links,
)
from funda_mail_ophalen import haal_mail_teksten, mail_config  # noqa: E402


def main() -> int:
    config = mail_config()
    if not config:
        print("FOUT: geen mailinstellingen gevonden.")
        print("  Nodig: FUNDA_MAIL_USER en FUNDA_MAIL_PASSWORD in de omgeving.")
        print("  (In Actions: als Secrets, en meegegeven in de env van de stap.)")
        return 1

    # Wel de host en de map, niet de gebruiker: dat is een mailadres.
    print(f"host: {config['host']}  map: {config['map_naam']}")
    print(f"gebruiker: ingesteld ({len(config['gebruiker'])} tekens)")
    print(f"wachtwoord: ingesteld ({len(config['wachtwoord'])} tekens)")

    try:
        teksten = haal_mail_teksten(**config, sinds_dagen=14,
                                    log=lambda b: print(f"  [log] {b}"))
    except Exception as exc:
        print(f"\nFOUT: mailbox niet te lezen: {type(exc).__name__}: {exc}")
        if "AUTHENTICATIONFAILED" in str(exc).upper():
            print("  Dat is een inlogfout. Gmail wil hier een app-wachtwoord "
                  "(niet het gewone wachtwoord), en IMAP moet aanstaan.")
        return 1

    print(f"\nmails gevonden: {len(teksten)}")
    totaal_woningen: list[str] = []
    for i, tekst in enumerate(teksten, 1):
        woningen = vind_woning_links(tekst)
        tracking = vind_tracking_links(tekst)
        totaal_woningen.extend(t for _, t in woningen)
        print(f"  mail {i}: {len(tekst)} tekens, {len(woningen)} woninglink(s), "
              f"{len(tracking)} tracking-link(s)")

    unieke = sorted(set(totaal_woningen))
    print(f"\nunieke woningen (tiny_id, publieke nummers): {len(unieke)}")
    if unieke:
        print(f"  {', '.join(unieke[:20])}")

    print("\nOK: login, zoeken en decoderen werken tegen de echte mailbox.")
    if not unieke:
        print("Nul woningen is hier geen fout: de alert-mail van de bewaarde "
              "zoekopdracht is er nog niet, of bevat geen nieuw aanbod.")
        print("Staan er wél tracking-links maar nul woningen in een alert-mail, "
              "dan verpakt funda de woninglink; zie los_tracking_link_op().")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
