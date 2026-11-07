# Meetgeschiedenis

De metingen en run-id's waarop de regels in `CLAUDE.md` rusten. `CLAUDE.md` houdt
de regels en besluiten; hier staat waarom en hoe dat is vastgesteld. Dit bestand
wordt niet automatisch geladen. Het staat bewust niet in `docs/`, want GitHub
Pages publiceert die map.

Geen persoonsgegevens hier: geen postcodes, adressen, bedragen van het profiel of
namen. Run-id's verwijzen naar de Actions-runs van rpvos-dhg/Funda.

## Zoek-API dicht (aug 2026)

- 18 aug 2026: `listing-search-wonen.funda.io/_msearch/template` geeft
  `401 no token provided`. pyfunda stuurt geen token mee, ook v3.1.4 niet.
  Upstream issue 0xMH/pyfunda#15 van dezelfde datum; toen nog open en zonder
  commits sinds 17 juli.
- 19 aug 2026, de maintainer in #15: funda zette Firebase App Check op de mobiele
  zoek-API. Een geldig `x-firebase-appcheck`-token komt alleen na device
  attestation (Play Integrity / App Attest).

## www.funda.nl dicht vanaf Actions (okt 2026)

Sinds 8 okt 2026 geeft de zoekpagina een 403 vanaf GitHub Actions. Gemeten op
9 okt met drie scripts die in de opruimronde van nov 2026 zijn weggehaald
(`scripts/funda_403_probe.py`, `scripts/funda_bronnen_probe.py`,
`scripts/funda_v315_probe.py`; terug te vinden met `git log -- <pad>`, de laatste
versie met `git show 87f9695^:<pad>`):

- Zes TLS-profielen (safari15_5/17_0, chrome120/124/131, firefox133) maal drie
  headersets (minimaal, browser-achtig, met referer), plus twee varianten die
  eerst de homepage bezoeken: alle twintig 403, body ongeveer 536 bytes. De
  blokkade zit dus op het netwerk of IP van de runner, niet op hoe de client zich
  voordoet.
- Per pad: zoekpagina met en zonder slash 403, Nuxt-payload 403, detailpagina als
  HTML ook 403, `/sitemap.xml` 404 (de echte sitemap staat op
  `/sitemap_index.xml/`, met slash; een eerdere meting vond daardoor niets),
  robots.txt 200, homepage 200 (uit Akamai's statische cache). De API-host
  `listing-detail-page.funda.io` gaf wel 200.
- pyfunda v3.1.5 voegde in augustus een webroute toe (chrome124, roteren bij 403,
  backoff). `search()` gaf `curl (92) HTTP/2 stream reset by server`. Upgraden
  helpt dus niet, en kost ook de incompatibele v3-rewrite.
- Mail als bron: op 9 okt stonden er geen alert-mails van een bewaarde
  zoekopdracht in de mailbox. Funda mailt wel transactioneel via
  `notificaties@service.funda.nl`, dus het kanaal werkte.

## Mailroute (okt en nov 2026)

- 9 okt 2026: twee transactionele funda-mails bekeken (één uit 2022, één uit
  2026). In het text/plain-deel stonden inhoudelijke links onverpakt. Eén mail
  volledig uitgelezen (plat en html, 30.206 tekens) had 9 tracking-links: funda
  gebruikt zijn tracker in het html-deel ruim. De "online versie"-link is een
  ondoorzichtige redirect (`links.funda.nl/s/vb/<token>/<token>/23` en
  `links.funda.nl/e/evib?_t=..&_m=..&_e=..`), zonder `?url=` met de echte URL.
- 9 okt 2026: `links.funda.nl` gaf vanaf Actions een 403 (`probeer_trackerhost()`
  in de IMAP-check, op de wortel van de host, zodat er geen eenmalig klik-token
  sneuvelde).
- 9 okt 2026: de check tegen de echte mailbox gaf nul funda-mails over 14 dagen
  in INBOX, terwijl Gmail er die dag één liet zien. Die mail had de labels
  `IMPORTANT` en `CATEGORY_UPDATES`, maar niet `INBOX`: gearchiveerd. Daarom zoekt
  `kies_map()` de map met de `\All`-vlag op.
- 17 okt t/m 4 nov 2026: de mailroute leverde op Actions 35 woningen. Over 38
  runs stonden 27 van die 35 er maar 8 tot 9 runs in (ongeveer 4 dagen), omdat de
  mail daarna buiten het terugkijkvenster viel. Aanleiding voor de pool.
- 4 nov 2026 22:02: Gmail weigerde de login (`AUTHENTICATIONFAILED`); daarna
  faalde elke run op de (al weken bekende) 403 van de zoekpagina. Aanleiding voor
  de `::error::` met uitleg en het terugkijkvenster van 14 dagen.
- 6 nov 2026: de job `mail-live` uit "Funda API debug" en de mailroute uit `auto`
  weggehaald; de sitemaproute is de bron op Actions.

## Straal-nafilter (6 nov 2026)

De 35 woningen uit de mailperiode, gegeocodeerd op postcode: 24 lagen verder dan
5 km van de zoekpostcode, tot 8,1 km, in wijken die niet in `UITSLUIT_BUURTEN`
staan omdat funda's straal ze vroeger al wegfilterde. Alle 59 woningen uit de
API- en HTML-runs lagen binnen 4,8 km. Zonder nafilter leek het daardoor alsof
uitgesloten wijken terugkwamen.

## Sitemaproute (6 nov 2026)

- Runs 42260153909, 42261516145 en 42262032618 (`scripts/funda_sitemap_probe.py`
  en `scripts/funda_sitemap_validatie.py`): robots.txt (200, text/plain) staat
  `/detail/` en `/zoeken/` toe voor `*` en noemt
  `Sitemap: https://www.funda.nl/sitemap_index.xml/`. De index en de vier
  koop-sitemaps geven 200 met XML.
- Omvang: 102.365 koop-URL's, ongeveer 23 MB XML, elk met `<lastmod>`. Den Haag
  3.695, Voorburg 262; na de slug-afwijslijst (huis, parkeren, bouwgrond) 3.103
  kandidaten. Alle 35 woningen uit de mailperiode staan erin.
- Vertraging: index-lastmod 04:59 NL, om 18:29 NL nog dezelfde snapshot.
  Dagelijks verversen is vermoed, niet over meerdere dagen gemeten.
- Speling op de lastmod: de index gaf per verzoek soms een seconde verschil
  (koop3 04:59:26 en 04:59:27, zelfde ETag). Een exacte vergelijking haalde
  daardoor elke run alle koop-sitemaps opnieuw op (e2e-run 42272395594); nu 10
  minuten speling per koop-sitemap.
- Eerste e2e-run 42271742515: crash in `main()` op een woning zonder vraagprijs
  (`price=None` in `sort()`); opgelost, vastgepind in
  `test_funda_zoek.py::test_prijs_onbekend`.
- E2e in `auto`, run 42273695515 (TEST-config met straal 6 -> 5 km, twee runs in
  één job, geen secrets): API 401 en zoekpagina 403, dus `sitemap`.
  - Run 1 (lege cache): 6 sitemap-verzoeken, 200 detail-calls (1x 404), 8 in de
    doelmarkt, 6 na de filters (2 niet beschikbaar), 167 s.
  - Run 2: 2 sitemap-verzoeken (koop-sitemaps uit de cache), 208 detail-calls
    (8 ververst, 200 verkend), 191 op de cache overgeslagen, 16 in de doelmarkt,
    8 na de filters (2 nieuw, 6 eerder gezien), 154 s.
  - Beide runs 0 dubbele detail-calls.
- Prijs op aanvraag: in diezelfde e2e rekende het rapport een woning zonder
  vraagprijs met prijs 0 ("€ 0 | 145 m2"): budget "PAST", minimale maandlast,
  hoogste score, dus bovenaan. Run 42290940091 toonde een appartement van 145 m2
  ver buiten het budget. Sinds 6 nov 2026 gaan woningen zonder vraagprijs
  standaard weg, en heeft het rapport de poort "Prijs onbekend".
- Codex-review PR #13: in de pool telden time-outs met 404's ertussen door tot 5,
  terwijl het endpoint gewoon antwoordde. Nu zet een nette 404 de reeks terug op 0
  (`test_pool_404_beeindigt_reeks`).

## Eerlijke client (6 nov 2026)

- Tot nov 2026 zette de `Funda`-subklasse pyfunda vast op
  `FINGERPRINT_POOL[0]`: niet meer wisselen, maar wel de sterkste vermomming, de
  app zelf.
- Gemeten: een client met Python-TLS, eigen user-agent en geen app-headers krijgt
  van het detail-endpoint 200 met JSON, eerst vanaf een sandbox en daarna vanaf
  Actions in e2e-run 42281508702: twee runs in `auto`, 200 en 208 detail-calls,
  alleen nette 404's als fout (1 en 2, `[404, 404]`: pyfunda probeert tinyId en
  daarna globalId), 0 dubbele calls, 153 s en 146 s (was 167 s en 154 s met de
  app-vermomming), zelfde aantallen als de e2e daarvoor. De zoek-API gaf met deze
  client geen 401 maar een `HTTP/2 stream reset by server`.
- Probes: tot nov 2026 draaide de dagelijkse workflow na een mislukte run
  automatisch `funda_api_debug.py`, en die probeerde de zoek-API met safari15_5,
  chrome124, zonder impersonate en met een nep-`x-funda-app-version`. Dat is het
  wisselen dat `CLAUDE.md` verbiedt, twee keer per dag zolang het stuk was. Die
  stap is weg.
- `links.funda.nl` gebruikte tot nov 2026 het profiel `chrome124`; nu hetzelfde
  vaste `safari15_5` als `www.funda.nl`.

## Geocoding via PDOK (7 nov 2026)

Gemeten op de postcode van het stadhuis (4 adressen): `limit=1` in 7,7 en 11,3 s,
`limit=10` in 36,6 s, `limit=50` in 24 s. Met minder adressen dan de limit zoekt
de server de hele postcode af. Daarom `limit=1`, time-out 60 s en één poging per
postcode per run. OSRM (`router.project-osrm.org`) heeft geen robots.txt: op
`/robots.txt` komt een JSON-fout terug.

## Actions-cache en publiceren (6 nov 2026)

- PR #13 voegde `funda_thuis_coords.json` en `funda_sitemap_cache.json` toe aan de
  padenlijst van de cache. Daarna vond `restore-keys: funda-state-` de oude caches
  niet meer ("Cache not found"). De opstartrun 42287980238 begon met 0 gezien,
  lege tracking en geen blacklist, en meldde 9 "nieuwe" woningen. Hersteld met een
  tijdelijke migratie in `funda-daily.yml` (de oude cache apart ophalen met de
  oude padenlijst, samenvoegen met `scripts/state_migratie.py`). Gemeten in run
  42290940091: seen 137+9 -> 142, tracking 137+9 -> 142. Daarna zijn de
  migratiestappen weer uit de workflow gehaald.
- Run 42290940091 schreef het rapport, maar de push werd geweigerd
  (`rejected ... fetch first`): tijdens de run was een PR in main gemerged. Sindsdien
  doet de publiceerstap `git pull --rebase origin main` vóór de push.
- Twee worktrees op dezelfde branch: in de ene werd gecommit, en de andere
  checkout had daarna die commit als gestagede terugdraaiing. Een lokale run zou
  die als "auto: rapport" hebben gepusht. Sindsdien commit `auto_push()` alleen
  `docs/`.
