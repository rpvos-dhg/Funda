# CLAUDE.md

Projectcontext voor Claude Code. Lees dit eerst.

## Wat dit project doet

Dagelijkse Funda-checker voor een koopappartement (regio Den Haag). Twee Python-
scripts zoeken nieuw aanbod, analyseren betaalbaarheid en bouwen een rapport
(markdown + HTML + een versleutelde PWA). Het draait automatisch op GitHub
Actions en publiceert het rapport op GitHub Pages.

- Live rapport: https://rpvos-dhg.github.io/Funda/ (wachtwoord-beveiligd)
- Repo: https://github.com/rpvos-dhg/Funda

## Belangrijkste bestanden

- `funda_zoek.py` - hoofdscript. Zoekt per prijsband, filtert op buurt/stad/
  straat, detailcheck (belegging, begane grond, blacklist), houdt nieuw-zijn en
  prijs/looptijd-tracking bij, roept het rapport aan.
- Zoekbronnen, elk een drop-in voor pyfunda's `Funda`-object: de zoek-API zelf,
  `funda_html_zoek.py` (zoekpagina), `funda_sitemap_zoek.py` (funda's sitemaps,
  op Actions de bron die werkt) en `funda_mail_bron.py` + `funda_mail_ophalen.py`
  (notificatiemails; sinds 6 nov 2026 alleen nog met `zoek_methode: mail`, niet
  in `auto`). `kies_zoeker()` kiest; zie hieronder.
- `funda_rapport.py` - bouwt het rapport: detail-call, reisafstand naar werk,
  beoordeling, verrijking en rente per woning, en schrijft markdown, HTML en de
  versleutelde PWA in `docs/`. Zie "Rapport, beoordeling en PWA" hieronder.
- `funda_beoordeling.py` - het beoordelingsmodel: poort (Past, Krap, Past niet,
  Prijs onbekend) met de leentoets 2026 (`data/trhk_2026_tabel1.json`) en de
  scenario's, score 0 tot 10 met uitleg, parsers voor funda's kenmerken. Pure
  functies, geen netwerk.
- `funda_verrijking.py` (open bronnen per woning) en `funda_rente.py` (actuele
  hypotheekrente). Fail-soft, met budget, robots.txt en eerlijke user-agent.
- `funda_ui.py` met `ui/app.css`, `ui/app.js` en `ui/slot.html` - de UI (lijst,
  kaart, sheets) en het slotscherm. Geen import van `funda_rapport`.
- `.github/workflows/funda-daily.yml` - draait 2x/dag (08:30 en 16:30 UTC =
  10:30 en 18:30 NL), genereert het rapport en pusht `docs/`.
- `funda_personal.example.json` - template voor de privé-config.

## Privébestanden (NIET op git, staan in .gitignore)

Deze leven alleen lokaal en mogen nooit gecommit worden:
`funda_personal.json` (inkomen, postcodes, de sleutels `beoordeling` en
`financien`), `funda_pwa_password.txt`,
`funda_seen_ids.json`, `funda_tracking.json`, `funda_werk_coords.json`,
`funda_blacklist.json`, `funda_log.txt`.

Op GitHub komen dezelfde gegevens uit Secrets: `FUNDA_PERSONAL_JSON` en
`FUNDA_PWA_PASSWORD`. Optionele PWA push gebruikt `WEB_PUSH_PUBLIC_KEY`,
`WEB_PUSH_PRIVATE_KEY` en `WEB_PUSH_SUBSCRIPTION`. `FUNDA_MAIL_USER` en
`FUNDA_MAIL_PASSWORD` gebruikt geen workflow meer (sinds 6 nov 2026); die
secrets mogen weg. De state (seen-ids, tracking,
werk-coords, verrijkingscache en `funda_sitemap_cache.json`) staat in de
Actions-cache, niet in de repo.

## Rapport, beoordeling en PWA (bouwronde nov 2026)

Ontwerp en besluiten: eigen palet (geen huisstijl van een merk), verrijking aan,
financiële scenario's, rentemodule, "Onthoud" zonder leesbaar wachtwoord.

- **Volgorde in `genereer_rapport()`.** Per woning: detail-call (in `funda_zoek`
  gecacht, dus geen extra funda-verkeer), pyfunda-verrijking (prijshistorie,
  buurtcijfer, makelaar), **eerst de routes** (de reisafstand telt mee in de
  score), dan een voorlopige beoordeling. Daarna de verrijking uit open bronnen
  (Past en Krap eerst, binnen het budget) en de definitieve beoordeling.
  Sorteren op `(geen vraagprijs, poort, twijfel, -score)`: zonder vraagprijs altijd
  achteraan, ook een veiling op PAST NIET (`funda_beoordeling.sorteer`, dezelfde
  sleutel als "Aanbevolen" in de UI). De beoordeling staat in `rij["beoordeling"]`
  en in `d["_beoordeling"]` (contract: docstring van `funda_beoordeling.py`).
- **Twijfel en push (`funda_zoek.py`).** `d["_twijfel"]` = korte zinnen
  (`twijfel_redenen`: twijfelbuurt van je lijst, gemeente Leidschendam-Voorburg);
  de woning blijft staan, onderaan in zijn groep. Leefbaarometer zwak komt uit de
  verrijking. Na het rapport zet `vul_summary_aan()` per nieuwe woning
  `status_push` (alleen het poortwoord: Past, Krap, Past niet of Prijs onbekend)
  en `score` in `funda_run_summary.json`; `scripts/send_web_push.cjs` toont dan
  "<adres>, <stad> · Past · 8,3", zonder beoordeling "<adres>, <stad> · 68 m2".
  De push toont de eerste drie, en `vul_summary_aan()` zet de nieuwe woningen
  daarvoor in de volgorde van "Aanbevolen" (`funda_beoordeling.sorteer`; zonder
  beoordeling achteraan), niet die van `sort_key` in `main()` (console en
  voorlopige samenvatting). Vastgepind in `test_funda_zoek.py::test_push_volgorde`.
  **Nooit een eurobedrag in de push** (eindreview PR #19): de statusregel
  ("€ 65 onder de norm (bruto)", "€ 26.610 eigen geld te weinig") geeft met de
  publieke code en de publieke woningdata het bruto inkomen of het eigen geld
  terug, en een melding staat leesbaar op het vergrendelscherm. De bedragen staan
  alleen in het versleutelde rapport. Vangnet in het script: elk deel met een
  €-teken valt weg, ook bij een oude samenvatting met `status`.
- **Config.** `beoordeling` (grens `max_woonlasten_netto`, `krap_marge`,
  gewichten, harde eisen, `verrijking`) en `financien` (scenario's `nu`,
  `2027_01`, `2027_01_met_cao` met toetsinkomen, eigen geld, studieschuld, BKR,
  kosten koper, rente) in `funda_personal.json` en de secret
  `FUNDA_PERSONAL_JSON`. Alles optioneel; de standaard staat in de code
  (`funda_beoordeling.STANDAARD`). Voorbeeld met fictieve waarden in
  `funda_personal.example.json`. De poort volgt het planningsscenario (standaard
  `2027_01`); per woning staat erbij of hij past nu, vanaf jan 2027 of alleen
  met cao. Zonder `financien` rekent het model met `bruto_jaar`, `eigen_inleg`,
  `duo_maandlast` en `leeftijd`, zonder scenario's. Inkomen komt nooit in het
  rapport, de log of de pushmelding.
  **Welke sleutels gelden (sinds 7 nov 2026 alleen deze; de secret gebruikt ze
  ook):**
  - `beoordeling`: `score_basis`, `m2_wens`, `max_woonlaag_zonder_lift`,
    `fiets_kmu`, `lang_op_funda_dagen`, `max_woonlasten_netto`, `krap_marge`,
    `financiering` (`alleenstaand`, `overbod_pct`, `kk_onzekerheid`,
    `eigen_geld_tekort_past_niet`, `starter_tot`), `harde_eisen`, `werk`,
    `gewichten`, `drempels`, `verrijking`. `lang_op_funda_dagen` mag ook op het
    hoogste niveau (die leest `funda_zoek` ook).
  - `financien`: `alleenstaand`, `starter_tot`, `planning`, `scenarios` (per id
    `bruto_jaar`, `label`, optioneel `datum` en `eigen_geld`; een kaal getal mag
    ook), `studieschuld.maandlast`, `bkr` (`[{limiet, opgezegd}]` of
    `[{maandlast}]`), `eigen_geld` (`nu`, `datum`, `per_maand`, `buffer`),
    `kosten_koper` (`vast`, `nhg_pct`) en `rente` (`pct`, `datum`,
    `rentevast_jaren`, `bron`, `nhg`, `ltv`, `max_dagen`).
  - **Weg** (G5 van de opruimronde): `financien.toetsinkomen` (ook per
    scenario), `startersvrijstelling_tot`, `verplichtingen_maand`,
    `bkr_limieten`, `buffer` op het hoogste niveau, `eigen_geld.<scenario-id>`,
    `rente.handmatig`, `rente.rentevast_jaar`, `beoordeling.financien` en in
    `beoordeling.financiering`: `max_woonlasten_netto`,
    `woonlasten_marge_past_niet`, `rente`, `rente_datum`, `rentevast_jaren`,
    `rente_max_dagen`. Die worden niet meer gelezen. Staat er toch een in de
    config, dan zet het rapport een `::warning::` met alleen de sleutelnamen
    (`funda_beoordeling.oude_sleutels()`), nooit de waarden; anders rekent het
    stil met de standaard.
- **Rente (`funda_rente.py`).** Een handmatige rente gaat altijd voor
  (`financien.rente.pct` met `datum`; de enige plek). Rentevast staat ook daar
  (`financien.rente.rentevast_jaren`, standaard 10; korter dan 10 jaar = toetsrente
  5%). `funda_rente` leest `cfg["financien"]["rente"]` zelf; er is geen
  vertaallaag meer. Nominatim en OSRM krijgen ook
  `EERLIJKE_UA`, zonder naam. Anders het nieuwste ASN-tariefblad (statische
  PDF's in het rentearchief op `www.asnbank.nl`; robots.txt verbiedt daar alleen
  `/web/contentViewCounter`), anders het DNB-cijfer "rente op nieuwe hypotheken"
  via het ECB Data Portal (`data-api.ecb.europa.eu`, `/service/data` toegestaan),
  anders 4,11% van 6 juli 2026 met een melding (`funda_beoordeling.STANDAARD_RENTE`,
  één bron voor model en `funda_rente`). Hooguit één poging per dag. Bron
  en peildatum staan in "Jouw budget"; ouder dan 30 dagen = melding bovenaan.
  **Bewust niet gebruikt:** de eigen API achter de rentepagina van ASN (vraagt een
  sleutel uit hun JavaScript-bundel) en de API van DNB (abonnementssleutel).
- **Verrijking (`funda_verrijking.py`).** Aan (`beoordeling.verrijking.aan`).
  Bronnen en robots (gemeten 7 nov 2026): BAG en CBS-buurten via `api.pdok.nl`
  (robots verbiedt alleen de Locatieserver, die niet gebruikt wordt),
  Klimaateffectatlas (`cas.cloud.sogelink.com`, geen robots.txt), RIVM-
  geluidkaarten (`data.rivm.nl`, geen robots.txt), Leefbaarometer 3.0
  (`geo.leefbaarometer.nl`, lege robots.txt) en de RIVM-gezondheidsmonitor via
  CBS (`dataderden.cbs.nl`, geen robots.txt). robots.txt per host eerst, vers op
  de dag van ophalen (RFC 9309 par. 2.4: hooguit 24 uur; ook voor `funda_rente`);
  de laatste goede versie (hooguit 30 dagen) alleen als terugval bij een time-out
  of 5xx, nooit bij een weigering. `EERLIJKE_UA`, sequentieel met pauze, time-out 10 s, budget 60
  verzoeken per run (± 5 per nieuwe woning; daarna bijna alles uit de cache).
  Per host stoppen bij 401/403/429/5xx en die host een dag dicht laten; nooit
  omzeilen. Een fout geeft "onbekend" in het rapport, nooit exit 2 en nooit een
  woning minder. Allowlist van velden: herkomst, nationaliteit, inkomen en andere
  bevolkingskenmerken worden nooit gelezen, bewaard of getoond. Ook van funda's
  buurtcijfers wordt alleen de vraagprijs per m² bewaard; bij laden en opslaan
  gaat de hele cachesectie `market_insights` door die allowlist, ook buurten die
  deze run niet langskomen. Niet automatisch: het
  WOZ-waardeloket en KOOP (robots verbiedt het). De RIVM-laagnamen hebben een
  datum (`rivm_20250101_...`); verdwijnt een jaargang, dan wordt geluid
  "onbekend" tot `RIVM_LAGEN` is bijgewerkt.
- **Cache.** Alles in het bestaande `funda_enrichment_cache.json`, als secties:
  `price_history`, `market_insights`, `broker` (pyfunda), `bag`, `fundering`,
  `geluid`, `buurtcode`, `leefbaarometer`, `tevredenheid`, `robots`,
  `verrijking_weigering` en `rente`. Adres- en puntsleutels zijn gehasht. Geen
  nieuw cachepad (zie de valkuil over de padenlijst). Van de makelaar alleen naam
  en reviews: zijn aanbod (`get_broker_listings`, een extra funda-verzoek met
  adressen van andere woningen) wordt sinds de opruimronde van nov 2026 niet meer
  opgehaald, en bij laden en opslaan uit oude cache-elementen gehaald.
- **Fail-soft tegenover luid falen.** Rente en verrijking mogen een run nooit
  laten falen (`haal_rente`, `verrijk_rijen`). De funda-checks die een run met
  exit 2 stoppen (zoekbron stuk, detail-endpoint dicht) blijven in `main()`.
- **PWA.** De body wordt eerst met gzip ingepakt (niveau 9, mtime 0) en daarna
  versleuteld met AES-256-GCM (PBKDF2-SHA256, 100.000 iteraties, 16 byte zout,
  12 byte IV, ongewijzigd). Ciphertext comprimeert niet, dus zonder gzip vooraf
  kan Pages hem niet kleiner maken (fixture: 98 kB op schijf, 38 kB gzip). Het
  slotscherm is `ui/slot.html` (`funda_ui.vul_slot`); zonder
  `DecompressionStream` (iOS ouder dan 16.4) zegt het dat, in plaats van "fout
  wachtwoord". "Onthoud op dit apparaat" bewaart een niet-exporteerbare
  PBKDF2-sleutel in IndexedDB (30 dagen), nooit het wachtwoord; een oud bewaard
  wachtwoord wordt bij openen omgezet en gewist. Service worker cache
  `funda-shortlist-v5` (ophogen bij elke nieuwe wrapper, anders blijft een
  geïnstalleerde PWA de oude tonen). Manifest "Woningrapport" / "Woningen"
  (geen voornaam: het staat publiek), kleuren `funda_ui.THEME_COLOR` en
  `funda_ui.ACHTERGROND`, iconen in hetzelfde palet. "Nieuw" geldt per apparaat en
  telt pas als gezien als de kaart minstens half een seconde in beeld was, tussen
  de vaste top- en onderbalk.
- **Huisstijl: eigen palet "Inkt en blauw", bewust geen ANWB-huisstijl.** Kleuren,
  stylesheet, iconen en fonts van het ANWB-designsysteem zijn merkeigendom van de
  ANWB (merkrecht), en de CSS van het slotscherm staat buiten de versleuteling
  publiek op GitHub Pages. Daarom een eigen palet met dezelfde opbouw (tokens
  licht en donker, feedbackkleuren alleen voor feedback, WCAG AA gemeten).
  Tokens en regels: `.interface-design/system.md`. `test_funda_ui.py` weigert
  ANWB-blauw `#003d86`, geel `#ffcd00` en de merk- en fontnamen. Het eerdere
  paarse palet "Lavendel" is op 7 nov 2026 door de eigenaar afgewezen; de test
  weigert ook paarse tokens en pint topbalk `#0f172a`, knop `#2563eb`, link
  `#1d4ed8` en pagina `#f4f6f9` vast.
- **Log.** Alleen aantallen: labelnamen van funda's `characteristics` met hoe
  vaak ze voorkwamen (om de parsers te kalibreren), aantallen per poort,
  verrijking per bron en status, rente met bron. Nooit adressen, postcodes of
  bedragen van het profiel.
- **Jaarwissel.** `test_funda_beoordeling.py` faalt op 1 januari zolang tabel 1
  niet van het lopende jaar is: dan `data/trhk_2026_tabel1.json` (tabel 1 en de
  labelbedragen), de NHG-grens en de startersgrens in `funda_beoordeling.py`
  bijwerken. Rente: zet je eigen rente in `financien.rente` als je een offerte
  hebt; anders volgt het rapport ASN.
- **Fixture-render.** De 13 fictieve woningen in `testdata/woningen.json` gaan in
  `test_funda_zoek.py::test_rapport_testdata` door het echte
  `genereer_rapport()` (stub-client, tijdelijke map, ontsleutelen in Python).

## Belangrijke valkuilen (eerder tegengekomen)

- **Zoek-API zit sinds 18 aug 2026 achter auth (`401 no token provided`).**
  `listing-search-wonen.funda.io/_msearch/template` eist nu een token dat
  pyfunda niet meestuurt; ook v3.1.4 niet (upstream issue 0xMH/pyfunda#15, zelfde
  datum, nog steeds open en zonder commits sinds 17 juli). Daarom zoekt het
  script nu via de publieke zoekpagina, zie hieronder.
  **Oorzaak, volgens de maintainer in #15 (19 aug):** funda zette Firebase App
  Check op de mobiele zoek-API. Een geldig `x-firebase-appcheck`-token komt alleen
  na device attestation (Play Integrity / App Attest), dus vanaf een echte
  telefoon met de app uit de store. Dit komt niet meer terug via code; reken de
  zoek-API als dicht. Het detail-endpoint heeft (nog) geen App Check.
  Diagnose herhalen: workflow "Funda API debug", handmatig (sinds nov 2026 niet
  meer automatisch na een mislukte dagelijkse run, zie "Eerlijke client"
  hieronder). Die workflow heeft twee jobs:
  **tests** moet groen zijn en zegt iets over de code; **funda-live** staat op
  `continue-on-error` en zegt iets over funda's kant. (De job **mail-live**, de
  IMAP-check met de Gmail-secrets, is op 6 nov 2026 weggehaald, samen met de
  mailroute uit `auto`.) Zo
  blijft de workflow groen bij een netwerkblokkade, terwijl de job-status
  leesbaar blijft: funda-live rood = funda dicht, groen = funda laat weer door.
  Bewust op job-niveau, want `continue-on-error` op een stap laat GitHub die
  stap als "success" rapporteren ook als het commando faalde. Het échte
  faalsignaal blijft de dagelijkse workflow, die wél rood wordt en niets
  publiceert.
- **Zoekpagina geeft sinds 8 okt 2026 een 403 vanaf GitHub Actions.** Daarmee
  ligt ook de HTML-route eruit; de dagelijkse run faalt luid en publiceert niets.
  Gemeten op 9 oktober met `scripts/funda_403_probe.py` (script verwijderd in
  de opruimronde, nov 2026; terug te vinden met
  `git log -- scripts/funda_403_probe.py`): zes TLS-profielen
  (safari15_5/17_0, chrome120/124/131, firefox133) x drie headersets (minimaal,
  browser-achtig, met referer) plus twee varianten die eerst de homepage
  bezoeken - **alle twintig 403**, body ~536 bytes. De blokkade zit dus op het
  netwerk/IP van de runner, niet op hoe de client zich voordoet; headers of TLS-
  profielen aanpassen helpt niet. Upstream pyfunda v3.1.5 voegde juist dat toe
  (chrome124 + roteren bij 403 + backoff), dus upgraden lost dit óók niet op.
  Gemeten per pad (`scripts/funda_bronnen_probe.py`, script verwijderd in de
  opruimronde, nov 2026; terug te vinden met
  `git log -- scripts/funda_bronnen_probe.py`): zoekpagina met én zonder
  slash 403, Nuxt-payload 403, **detailpagina als HTML ook 403**, sitemap 404
  (alleen `/sitemap.xml`; de echte staat op `/sitemap_index.xml/` en geeft 200,
  zie de sitemaproute), robots.txt 200, homepage 200. Vrijwel heel `www.funda.nl` is dus dicht voor de
  runner; de homepage komt alleen door omdat die uit Akamai's statische cache
  komt. De aparte API-host `listing-detail-page.funda.io` geeft nog wél 200.
  Ook gemeten: pyfunda **v3.1.5** (`scripts/funda_v315_probe.py`, script
  verwijderd in de opruimronde, nov 2026; terug te vinden met
  `git log -- scripts/funda_v315_probe.py`), die in augustus
  een webroute toevoegde. `search()` geeft `curl (92) HTTP/2 stream reset by
  server`. Upgraden helpt dus niet, en kost ook de incompatibele v3-rewrite.
  Zoeken vereist een ander uitgaand IP (self-hosted runner op een eigen netwerk,
  waar dit project oorspronkelijk liep), funda's sitemaps (sinds nov 2026 de
  route op Actions, zie hieronder), óf een bron die funda zelf pusht:
  een bewaarde zoekopdracht met mailnotificatie. Die mails staan er nu niet
  (gecheckt in Gmail, 9 okt); funda mailt wel transactioneel via
  `notificaties@service.funda.nl`, dus het kanaal werkt. Met zo'n mail als bron
  kan het detail-endpoint de rest nog gewoon aanvullen. Zie de mailbron hieronder.
- **Bewust niet gedaan: funda's botbescherming omzeilen.** In #15 en PR #16
  noemen mensen een nieuwere TLS-vingerafdruk (`chrome146`) en de host
  `listing-search-wonen.funda.nl` (de zoekbackend van de website, zonder App
  Check) als manier om weer te zoeken. Op 6 nov 2026 bewust niet uitgeprobeerd
  vanaf een server: vingerafdrukken afwisselen of een andere host kiezen om een
  blokkade te passeren is een botcheck omzeilen. Wat wél kan: funda's eigen
  mails, de sitemaps, het detail-endpoint, en het script draaien vanaf een eigen
  (thuis)netwerk zoals het oorspronkelijk draaide.
  - **Eerlijke client voor funda's API-hosts.** pyfunda v2.9.0 doet zich voor
    als funda's Android-app: de TLS-vingerafdruk (JA3) "captured from real
    Dart/Flutter app traffic", `user-agent: Dart/3.9 (dart:io)`,
    `x-funda-app-platform: android` en datadog-traceheaders. En bij een
    weigering loopt `_find_working_fingerprint()` zijn `FINGERPRINT_POOL` af
    (twee app-JA3's, twee Safari-profielen, okhttp, chrome) tot er één doorkomt;
    pyfunda noemt zelf "bot detection" als reden. Tot nov 2026 zette de
    `Funda`-subklasse dat vast op `FINGERPRINT_POOL[0]`: niet meer wisselen,
    maar wel de sterkste vermomming, de app zelf. **Nu** gaat elk verzoek van de
    subklasse (detail, zoek-API, prijshistorie, makelaar) via één gewone client:
    curl zonder browser- of app-profiel, `user-agent:
    funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)`
    (`EERLIJKE_UA`), geen app- of traceheaders. Er wordt nooit een vingerafdruk
    gezocht. **Gemeten op 6 nov 2026**: zo'n client (Python-TLS, eigen UA, geen
    app-headers) krijgt van het detail-endpoint gewoon 200 met JSON, eerst vanaf
    een sandbox en daarna vanaf Actions in e2e-run
    [42281508702](https://github.com/rpvos-dhg/Funda/actions/runs/42281508702):
    twee runs in `auto`, 200 en 208 detail-calls, alleen nette 404's als fout
    (1 en 2, `[404, 404]`: pyfunda probeert tinyId en daarna globalId), 0
    dubbele calls, 153 s en 146 s (was 167 s en 154 s met de app-vermomming),
    zelfde aantallen als de e2e daarvoor. De zoek-API geeft met deze client geen
    401 maar een `HTTP/2 stream reset by server`; `auto` gaat dan net zo door
    naar de volgende bron. Weigert het endpoint de eerlijke client
    ooit, dan is dat een 401/403 en faalt de run luid; niet terugzetten naar de
    app-vermomming zonder dat de gebruiker daar bewust voor kiest. Vastgepind in
    `test_funda_zoek.py::test_eerlijke_client` (tegen het echte pyfunda, met een
    nep-sessie).
  - **Statuscodes.** pyfunda maakt van élke status behalve 200 een
    `LookupError("Listing ... not found")`, dus een 403 of 429 halverwege de run
    leek op een verkochte woning. De subklasse vertaalt: 401/403/429 =
    `DetailEndpointDicht` (run stopt, exit 2), 404/410 = `WoningNietGevonden`
    (woning weg, endpoint werkt), de rest blijft een gewone `LookupError` (telt
    als storing). Beide klassen staan in `funda_sitemap_zoek.py`.
  - De sitemap- en HTML-zoeker gebruiken voor `www.funda.nl` hetzelfde vaste
    curl_cffi-profiel (`safari15_5`, Safari-UA), uit één bron:
    `funda_sitemap_zoek.UA` en `IMPERSONATE`; `funda_html_zoek` importeert ze
    (`test_funda_html.py::test_profiel_www`). Een 401, 403 of bot-controle =
    luid falen. Hetzelfde profiel geldt voor `links.funda.nl` (de mailroute,
    alleen lokaal en alleen als je redirects laat volgen:
    `funda_mail_bron.TRACKER_IMPERSONATE`, ook in `funda_mail_imap_check.py`);
    tot nov 2026 stond daar `chrome124`.
  - **Probes.** De dagelijkse workflow draaide na een mislukte run automatisch
    `funda_api_debug.py`, en die probeerde de zoek-API met safari15_5, chrome124,
    zonder impersonate en met een nep-`x-funda-app-version`: precies het
    wisselen dat hierboven verboden is, twee keer per dag zolang het stuk was.
    Die stap is weg; `funda_api_debug.py` gebruikt nu per host één vaste client
    (de eerlijke voor de API-hosts, het safari-profiel voor `www.funda.nl`) en
    draait alleen handmatig. Alle scripts gebruiken `from funda_zoek import
    Funda`, nooit pyfunda's eigen `Funda` (die wisselt nog steeds).
- **Sitemaproute: funda's eigen sitemaps als bron** (`funda_sitemap_zoek.py`). In
  `auto` de derde en laatste stap: api -> html -> **sitemap**. Werkt vanaf
  Actions zonder mailbox, en is sinds 6 nov 2026 dé bron op Actions (besluit van
  de eigenaar; de mailroute is daarmee niet meer nodig). Gemeten op 6 nov 2026 (runs
  [42260153909](https://github.com/rpvos-dhg/Funda/actions/runs/42260153909),
  [42261516145](https://github.com/rpvos-dhg/Funda/actions/runs/42261516145),
  [42262032618](https://github.com/rpvos-dhg/Funda/actions/runs/42262032618)):
  - `robots.txt` (200, text/plain) staat `/detail/` en `/zoeken/` toe voor `*`
    en noemt `Sitemap: https://www.funda.nl/sitemap_index.xml/`. Let op de slash:
    `/sitemap.xml` is 404, een eerdere meting vond daardoor niets. De
    zoeker leest robots.txt elke run en stopt als `/detail/` wordt uitgesloten.
    **Maar dat is de robots.txt van `www.funda.nl`**, en de zoeker haalt daar
    nooit een `/detail/`-pagina op: de detail-calls gaan naar
    `listing-detail-page.funda.io`, en die heeft `Disallow: /` (zie "robots.txt
    van de API-hosts" hieronder). De check kan die calls dus niet tegenhouden.
  - De index wijst naar `sitemap-detail-koop1..4.xml` (plus huur, nieuwbouw,
    recreatie, europe): 102.365 koop-URL's, ~23 MB XML, **elk met `<lastmod>`**.
    Den Haag 3.695, Voorburg 262; na de slug-afwijslijst (huis, parkeren,
    bouwgrond) 3.103 kandidaten. Alle 35 woningen die de mailroute van 17 okt
    t/m 4 nov toonde, staan erin.
  - **Vertraging: ongeveer een dag.** Index-lastmod 04:59 NL, om 18:29 NL nog
    dezelfde snapshot; dagelijks verversen is vermoed, niet over meerdere dagen
    gemeten. De run van 18:30 ziet dezelfde snapshot als die van 10:30.
  - Werking: de sitemap geeft alleen URL + lastmod; prijs, m2, buurt, status en
    coördinaten komen van het detail-endpoint. `funda_sitemap_cache.json` bewaart
    per woning lastmod en die velden, plus het index-kenmerk en de
    kandidatenlijst. Per run gaan robots.txt en de index altijd (2 verzoeken); de
    koop-sitemaps alleen als de lastmod in de index (anders de
    Last-Modified-header) veranderd is. **Met 10 minuten speling per
    koop-sitemap**: de index geeft per verzoek soms een seconde verschil (gemeten
    6 nov: koop3 04:59:26 en 04:59:27, zelfde ETag), en een exacte vergelijking
    haalde daardoor elke run alles opnieuw op (e2e-run
    [42272395594](https://github.com/rpvos-dhg/Funda/actions/runs/42272395594)). Ongewijzigde lastmod en buiten de
    doelmarkt of afgewezen door type/stad/buurt/straat/prijs/m2/straal
    (`_sitemap_overslaan`, met `buiten_zoekcriteria`) = geen call. Woningen die
    door alle filters komen, worden elke run vers opgehaald. Onbekend (bijv. geen
    coördinaten) = doorlaten. Steden via `sitemap_steden` ("Den Haag" wordt
    vanzelf "den-haag", `stad_slug()`). De kandidatenlijst uit de cache wordt
    hooguit **36 uur** hergebruikt (`MAX_HERGEBRUIK_UUR`), ook als de index
    "ongewijzigd" blijft zeggen: een index-lastmod die blijft hangen terwijl de
    koop-sitemaps veranderen, mag niet stil nieuw aanbod kosten.
  - **Opstart: achterstand.** Een lege cache betekent ~3.100 woningen zonder
    gegevens. Per run `sitemap_max_verkennen` (standaard 200) detail-calls,
    nieuwste lastmod eerst; bij 2 runs per dag is dat na hooguit ~8 dagen weg
    (verre en te dure woningen kosten maar één call). Nieuw aanbod zit vanaf de
    eerste run in de top. **Sneller:** workflow "Funda dagelijks rapport"
    handmatig starten met input `sitemap_max_verkennen` = 600 (wordt
    `FUNDA_SITEMAP_MAX_VERKENNEN`); leeg laten = standaard. Hoger gaat niet:
    `SITEMAP_MAX_VERKENNEN_PLAFOND` (600) begrenst omgeving en config, zie het
    robots-besluit hieronder. Het verkennen heeft
    ook een **tijdsbudget** van 15 minuten (`MAX_SECONDEN`; normaal ~0,8 s per
    call); wat dan openstaat, blijft achterstand. De job heeft
    `timeout-minutes: 45` als vangnet.
  - Luid falen (`RuntimeError`, exit 2 via de bestaande checks in `main()`):
    403, HTML in plaats van XML of nul kandidaten; **een ingestelde stad met nul
    URL's** (typfout of andere slug bij funda; viel eerst stil weg, terwijl
    getrackte woningen via de pool het rapport normaal lieten lijken); **de
    nieuwste lastmod onder de kandidaten ouder dan 3 dagen, of geen lastmod**
    (`MAX_LEEFTIJD_DAGEN`: een bevroren sitemap gaf anders een groene run zonder
    ooit nog nieuw aanbod).
  - **Detail-endpoint dicht, ook halverwege** (`DetailEndpointDicht`, exit 2):
    meteen bij 401/403/429, en bij `DICHT_NA` (5) mislukte calls op rij, ook na
    eerdere successen. Een nette 404 telt daar niet in mee (een antwoord van een
    werkend endpoint; de e2e zag er 1 per 200) en zet de reeks terug op 0, in
    de zoeker en in de pool (Codex-review PR #13: time-outs met 404's ertussen
    telden anders door tot 5). De pool telt door vanaf de
    laatste calls van de zoeker, en **eindigt de run met mislukte calls, dan
    ook exit 2**: misschien ging het endpoint net dicht. Zonder dit liep de run
    door, vielen de ververste woningen weg en bleef dat halve rapport staan
    zolang de volgende runs al bij de eerste call faalden. De geslaagde
    verkenning wordt vóór het stoppen in de cache bewaard.
  - **In `auto` gebeurt het zoekwerk al in `kies_zoeker()`** (`ophalen()`):
    `bereikbaar()` kijkt alleen naar robots.txt en de index; een koop-sitemap die
    daarna een 403 geeft, komt zo met zijn oorzaak in de ene `::error` en een
    `GeenBron` (exit 2). Tot 6 nov 2026 viel zo'n fout eerst nog door naar de
    mailroute. Detail-endpoint dicht: meteen exit 2, want elke route heeft dat
    endpoint nodig.
  - **Meting eerste week** (log, alleen getallen): regel "Meting lastmod" telt
    gecachte woningen met een gewijzigde lastmod en hoeveel daarvan een andere
    prijs of status kregen, én hoeveel vers opgehaalde woningen met
    ongewijzigde lastmod tóch een andere prijs of status hadden. Dat tweede getal
    hoort 0 te zijn; is het dat niet, dan mist het overslaan op de cache
    prijsdalingen van woningen net boven de grens. Regel "Pool en sitemap" telt
    hoeveel getrackte woningen niet meer in de sitemap staan. "Run-kosten" aan
    het eind: methode, duur, detail-calls (en hoeveel dubbel), sitemap-verzoeken
    en of de koop-sitemaps opnieuw zijn opgehaald.
  - **End-to-end in `auto`** (6 nov 2026, run
    [42273695515](https://github.com/rpvos-dhg/Funda/actions/runs/42273695515);
    TEST-config 2513AA, straal 6 -> 5 km, 230-310k, 55 m2; twee runs in één job,
    geen secrets): API 401 en zoekpagina 403, dus `sitemap`. Run 1 (lege cache):
    6 sitemap-verzoeken, 200 detail-calls (1x 404), 8 in de doelmarkt, 6 na de
    filters (2 niet beschikbaar), 167 s. Run 2: 2 sitemap-verzoeken (koop-sitemaps
    uit de cache), 208 detail-calls (8 ververst, 200 verkend), 191 op de cache
    overgeslagen, 16 in de doelmarkt, 8 na de filters (2 nieuw, 6 eerder gezien),
    154 s. Beide runs 0 dubbele detail-calls. De eerste e2e-run
    ([42271742515](https://github.com/rpvos-dhg/Funda/actions/runs/42271742515))
    crashte in `main()` op een woning zonder vraagprijs (`price=None` in
    `sort()`); opgelost, vastgepind in `test_funda_zoek.py::test_prijs_onbekend`.
  - **Prijs op aanvraag.** De oude zoek-API liet woningen zonder vraagprijs
    server-side weg. **Sinds 6 nov 2026 standaard weer weg** (`buiten_zoekcriteria`,
    reden "geen vraagprijs"): run 42290940091 toonde anders een appartement van
    145 m2 in Belgisch Park, ver buiten het budget. Met `prijs_onbekend_tonen: true`
    komen ze terug, en dan geldt het volgende. Daarvoor lieten de sitemap- en
    mailroute ze door (onbekend = doorlaten). Het rapport rekende dan met prijs 0: budget "PAST", minimale
    maandlast, hoogste score, dus bovenaan (e2e-run 42273695515: "€ 0 | 145 m2").
    Nu: poort "Prijs onbekend", geen leentoets en geen woonlasten, score alleen
    uit onderdelen die niet van de prijs afhangen, altijd achteraan (ook bij
    client-side sorteren: prijs en woonlasten zijn leeg in `#woning-data`), "op
    aanvraag" en "onbekend" in de kerncijfers, "prijs op aanvraag" in markdown en
    pushmelding, en in de tracking geen prijs 0 (anders een "prijsdaling" van
    100%). Vastgepind in `test_funda_zoek.py::test_prijs_onbekend_rapport`, door
    het echte `bouw_rij` en `funda_ui`.
  - Valideren tegen de echte site: `scripts/funda_sitemap_validatie.py`
    (end-to-end door `main()`, zonder rapport of push) en
    `scripts/funda_sitemap_probe.py` (robots en sitemaps meten).
- **robots.txt van de API-hosts. BESLUIT 6 nov 2026: optie (b), doorgaan.**
  `www.funda.nl` staat `/detail/` en de sitemap toe.
  `listing-detail-page.funda.io` (het detail-endpoint), `local-listings` en
  `listing-detail-summary` (beide `.funda.io`) hebben `Disallow: /`. Elke
  funda-route hier (api, html, sitemap, mail en de pool) verrijkt via die
  detail-host. De robots-check van de sitemapzoeker (`detail_verboden()`) leest
  alleen de robots.txt van `www.funda.nl` en kan de detail-calls dus **niet**
  tegenhouden. De sitemaproute schaalt het verkeer naar die host op ten
  opzichte van de HTML-route (die deed alleen detail-calls voor wat funda's
  zoekopdracht al op prijs, m2 en straal had gefilterd): **opstart ~3.100
  calls** (200 per run, ~8 dagen), **daarna tot ~450 per dag** (2 runs x
  hooguit 200 verkennend plus de ververste woningen in de doelmarkt en de
  pool); de e2e mat 200 en 208 per run. De opties waren (a) de robots.txt van
  `listing-detail-page.funda.io` meenemen in de check (dan staat de
  sitemaproute en elke verrijking uit) of (b) bewust doorgaan met dit volume.
  **Gekozen: (b)**, op 6 nov 2026 na het onderzoek gedelegeerd door de eigenaar.
  Waarborgen, en die blijven staan:
  - eerlijke user-agent met repo-link (`EERLIJKE_UA`), zodat funda ons kan
    herkennen en blokkeren;
  - meteen stoppen bij 401/403/429 (`DetailEndpointDicht`, exit 2), nooit
    omzeilen;
  - standaard hooguit 200 verkennende detail-calls per run
    (`sitemap_max_verkennen`), opstart eenmalig 600 en niet hoger
    (`SITEMAP_MAX_VERKENNEN_PLAFOND`);
  - geen wisselende vingerafdrukken.
  De `Disallow: /` op de detail-host was bij dit besluit bekend en is
  geaccepteerd; dat is dus geen reden om te heroverwegen. Sluit de robots.txt
  van `www.funda.nl` ooit `/detail/` uit, dan zet `detail_verboden()` de
  sitemaproute vanzelf uit (exit 2); dat hoeft niemand te bewaken.
  **Heroverwegen** zodra funda de eerlijke client weigert (401/403/429), funda's
  voorwaarden dit uitdrukkelijk verbieden, of funda erom vraagt. Alternatief:
  Huispedia (prototype op branch `claude/probe-andere-woningsites`). Het
  thuisnetwerk lost die gevallen niet op, want ook daar verrijkt elke route via
  de detail-host. Het verlaagt alleen het volume (de HTML-route, als de
  zoekpagina daar werkt, doet minder detail-calls), en helpt alleen als een
  weigering aan het IP van de runner hangt.
  `local-listings` en `listing-detail-summary` worden door dit script niet
  aangeroepen.
- **Mailbron: linkconventies gemeten, de alert-mail zelf nog niet.** Op 9 okt
  2026 zijn de twee transactionele funda-mails bekeken die in de eigen mailbox
  stonden (één uit 2022, één uit 2026). Daaruit:
  - In de **plattetekstversie** staan inhoudelijke links onverpakt
    (`https://www.funda.nl/makelaar/<id>`, `.../account/email-instellingen`,
    `.../meer-weten/...`). Die vindt `vind_woning_links()` zo.
  - **Maar de hele mail is een ander verhaal, en dat corrigeert bovenstaande.**
    De check van 9 okt las één echte mail volledig uit (plat + html, 30.206
    tekens) en vond **9 tracking-links**. Funda gebruikt zijn tracker in het
    html-deel dus ruim. Reken er daarom op dat de woninglink in de alert-mail
    verpakt kan zijn. Dat `tekst_uit_mail()` plat én html achter elkaar plakt is
    hier precies goed: de parser krijgt beide kansen.
  - **`links.funda.nl` geeft óók een 403 vanaf Actions** (gemeten 9 okt 2026,
    `probeer_trackerhost()` in de IMAP-check, op de wortel van de host zodat er
    geen eenmalig klik-token sneuvelt). Een verpakte woninglink is daar dus niet
    te volgen; `los_tracking_link_op()` werkt alleen lokaal of op een eigen
    netwerk. **Daarmee hangt de hele mailroute aan één ding**: dat de alert-mail
    de woninglink érgens onverpakt heeft, bijvoorbeeld in het text/plain-deel,
    waar funda in de gemeten mails gewone `www.funda.nl`-URL's zet. Staat hij in
    beide delen alleen verpakt, dan komt de mailroute op Actions niet verder dan
    de melding dat er tracking-links waren, en is een self-hosted runner de
    enige route die overblijft.
  - Alleen de "online versie"-link is verpakt, en die redirect is
    **ondoorzichtig**: `links.funda.nl/s/vb/<token>/<token>/23` (2026) en
    `links.funda.nl/e/evib?_t=..&_m=..&_e=..` (2022). Er zit dus géén `?url=`
    met de echte URL in - die aanname klopte niet en is nu weerlegd.
  - Daarom `woningen_uit_mail()` als hoofdingang: vindt die nul directe links,
    dan meldt hij hoeveel tracking-links er wél stonden. Dat scheidt "mail zonder
    nieuw aanbod" van "woninglink zit in een redirect". Alleen in dat tweede
    geval volgt `los_tracking_link_op()` de redirect, want zo'n call is een
    echte klik in funda's tracker.
  - Valideren tegen de eerste echte alert-mail:
    `python scripts/funda_mail_validatie.py <mail.eml> [--volg-redirects]`.
    Instellen staat op `https://www.funda.nl/account/email-instellingen`
    (notificaties bij je bewaarde zoekopdracht); de zoekopdrachten zelf op
    `https://www.funda.nl/zoeken/zoekopdracht/`.
  - **Niet in de repo**: echte tracking-tokens en mailinhoud horen bij een
    persoonlijke mailbox. De fixtures in `test_funda_mail.py` hebben daarom
    dummy-tokens in de gemeten vórm, niet de echte.
- **De bewaarde zoekopdracht is bij de mailroute het plafond.** Bij de oude
  API-route zocht het script zelf (prijsbanden, eigen straal) en filterde daarna.
  Bij de mailroute kan het script alleen nog wegstrepen uit wat funda mailt: wat
  die zoekopdracht mist, bestaat voor ons niet, en prijsband-splitsing helpt daar
  niet meer. Maar "ruimer zetten" geldt niet voor alles, want de twee soorten
  criteria worden heel verschillend afgehandeld:
  - **Gebied en grenzen: ruim zetten mag.** Sinds 6 nov 2026 worden straal,
    prijs en m2 na het ophalen gefilterd (`buiten_zoekcriteria`), naast stad,
    buurt, straat-segment, woningtype, belegging en begane grond. Extra gebied of
    een ruimere prijs in de zoekopdracht kost dus alleen detail-calls.
  - **Waarom de straal-nafilter er kwam (gemeten 6 nov 2026).** De 35 woningen
    uit de mailperiode (17 okt t/m 4 nov) gegeocodeerd op postcode: 24 lagen
    verder dan 5 km van de zoekpostcode, tot 8,1 km (Leyenburg, Kom Loosduinen,
    Waldeck-Noord, Venen/Oorden/Raden, Kraayenstein). Alle 59 woningen uit de
    API- en HTML-runs lagen binnen 4,8 km. Die wijken staan niet in
    `UITSLUIT_BUURTEN` omdat de straal ze vroeger al wegfilterde; zonder nafilter
    leek het alsof uitgesloten wijken terugkwamen.
  - De straal is standaard `snap_straal(radius_km)`, dus 5 bij een ingestelde 6:
    dezelfde waarde die funda's zoekopdracht gebruikte. Instelbaar met
    `straal_nafilter_km` (0 = uit). Thuiscoördinaten komen uit `thuis_coords` in
    de config of één Nominatim-call, gecacht in `funda_thuis_coords.json`.
    Lukt geocoderen niet, dan slaat het afstandsfilter over (onbekend =
    doorlaten) en staat dat in de log.
- **Nafilter op woningtype.** `PRIJS_MIN`, `PRIJS_MAX`, `M2_MIN` en
  `object_type` zijn alléén zoekparameters. Staat in de bewaarde zoekopdracht
  "Woonhuis" aangevinkt, dan belandt dat bij de mailroute ongefilterd in het
  rapport: de begane-grond-filter grijpt er niet op, want die kijkt naar
  omschrijvingen als "appartement op de begane grond", en die staan er bij een
  huis nooit. `is_geen_appartement()` vangt dat af.
  - **Afwijslijst, geen toestaanlijst.** Funda kent voor appartementen allerlei
    subtypes (bovenwoning, portiekflat, maisonnette, galerijflat, penthouse,
    studio, benedenwoning). Een lijst van toegestane woorden zou die stuk voor
    stuk afwijzen zodra er eentje mist. Nu geldt: onbekend type = doorlaten.
  - Kijkt eerst naar `house_type` (funda's `soortwoning` uit de detail-API) en
    anders naar het eerste segment van de URL-slug. Dat laatste bewust alleen
    het eerste segment: een straatnaam als "Huisduinenstraat" mag niet
    meetellen. Vastgepind in `test_funda_zoek.py::test_woningtypefilter`.
  - De vocabulaire van `soortwoning` is **niet** gemeten.
    `scripts/funda_mail_imap_check.py` (tot 6 nov 2026 de job `mail-live`, nu
    alleen lokaal) print daarom de woningtypes volgens de URL-slug, zodat
    zichtbaar is of er überhaupt huizen in de mails zitten en of het filter het
    juiste woord kent.
  - Prijs, oppervlak en straal hebben sinds 6 nov 2026 wél een nafilter, zie
    hierboven.
- **Buitenruimte: bewust geen nafilter.** funda's boolean (`has_balcony`) is
  onbetrouwbaar: een woning met balkon stond er als False in. Daarom wijst
  `funda_zoek` nooit af op buitenruimte; het model weegt hem mee in de score
  (`funda_beoordeling.buitenruimte()`, onbekend = geen minpunt). De oude,
  uitgeschakelde filter (`EIS_BUITENRUIMTE`, `heeft_buitenruimte()`) is in de
  opruimronde van nov 2026 weggehaald.
- **Voorburg versus de gemeente Leidschendam-Voorburg.** `UITSLUIT_STEDEN` doet
  een substring-match, en Voorburg valt onder de gemeente Leidschendam-Voorburg.
  Zonder voorrangsregel matcht "Leidschendam" daarop en valt al het
  Voorburg-aanbod stil weg: geen foutmelding, gewoon niets in het rapport.
  Daarom `WENS_STEDEN = ["Voorburg"]`, dat voorgaat op de uitsluitlijst. Geeft
  funda alleen de gemeentenaam terug, dan is niet te zien welke van de twee het
  is; die woningen worden getoond met de waarschuwing "STAD ONDUIDELIJK"
  (`is_twijfelstad()`) in plaats van weggegooid, en sorteren net als een
  twijfelbuurt naar onderen. Stil verliezen is erger dan een keer te veel laten
  zien. Vastgepind in `test_funda_zoek.py::test_stadfilter`, inclusief dat het
  detail-call-voorfilter zo'n woning niet overslaat.
- **Mailroute: transport via IMAP; sinds 6 nov 2026 alleen nog expliciet.**
  `auto` is api -> html -> sitemap; de mailbox gaat alleen open bij
  `zoek_methode: mail` (of `FUNDA_ZOEK_METHODE=mail`). Geen workflow geeft de
  mail-secrets nog door, dus op Actions draait de mailroute niet meer; de code
  en tests blijven voor lokaal gebruik. `funda_mail_ophalen.py` haalt de mails op,
  `funda_mail_bron.py` haalt er de woningen uit. Bewust gescheiden: het transport is te testen zonder mailbox, de
  parser zonder netwerk.
  - Twee instellingen, alleen bij `mail`: `FUNDA_MAIL_USER` (of `mail_gebruiker` in de
    config) en `FUNDA_MAIL_PASSWORD`. Dat laatste komt **alleen** uit de
    omgeving - in Actions een Secret - zodat een wachtwoord nooit in
    `funda_personal.json` belandt; `mail_config()` negeert het daar expres.
    Optioneel: `FUNDA_MAIL_HOST` (standaard imap.gmail.com), `FUNDA_MAIL_MAP`.
    Gmail wil voor een app-wachtwoord tweestapsverificatie op het account.
  - **INBOX is de verkeerde map, en dat is gemeten.** Op 9 okt 2026 gaf de check
    tegen de echte mailbox nul funda-mails over 14 dagen, terwijl Gmail er
    diezelfde dag één liet zien - die mail had `IMPORTANT, CATEGORY_UPDATES`
    maar géén `INBOX`-label. Gearchiveerd dus, en daarmee onvindbaar in INBOX.
    `kies_map()` zoekt daarom zelf de map met de **`\All`-vlag** op. Niet op
    naam, want die is taalafhankelijk: `[Gmail]/All Mail` versus
    `[Gmail]/Alle berichten`. `FUNDA_MAIL_MAP` leeg laten is dus het beste;
    een expliciete waarde gaat voor en slaat het opzoeken over.
  - `scripts/funda_mail_imap_check.py` controleert de hele keten (login ->
    mapkeuze -> zoeken -> decoderen -> parsen) tegen de echte mailbox. Nul
    woningen is daar een geslaagde uitkomst: dan is de alert-mail er nog niet.
    **Het print alleen getallen.** De Actions-log van een publieke repo is voor
    iedereen leesbaar en in een mailbox staan privédingen (een
    wachtwoord-reset-link bijvoorbeeld), dus geen onderwerpen, afzenders,
    mailtekst of tracking-links - alleen hoeveel er waren. Wel tiny_id's, want
    dat zijn publieke funda-nummers. Houd dat zo. Draaide tot 6 nov 2026 als job
    `mail-live` in de debug-workflow; nu alleen nog lokaal.
  - **Decoderen is het echte werk.** Een funda-mail is multipart met
    quoted-printable of base64 delen; in de ruwe bytes staan URL's met `=` en
    regelafbrekingen erdoorheen, en dan vindt de parser niets. `tekst_uit_mail()`
    laat de stdlib (`email`) dat uitpakken. `test_funda_mail_ophalen.py` pint dat
    vast met echt gecodeerde mails: op de ruwe bytes nul woningen, gedecodeerd
    één. Dat is ook waarom het transport geen eigen regex-werk doet.
  - Een mislukte IMAP-zoekopdracht gooit een `RuntimeError` in plaats van stil
    niets terug te geven; anders lijkt een kapotte mailbox op een week zonder
    nieuw aanbod. Een enkele onophaalbare mail wordt wél overgeslagen, en falen
    bij het afsluiten gooit de al binnengehaalde mails niet weg.
  - In `auto` (api -> html -> sitemap) doen `HtmlZoeker.bereikbaar()` en
    `SitemapZoeker.bereikbaar()` de tussenstappen: één of twee goedkope calls,
    zodat niet alle prijsbanden op een 403 lopen. Tot 6 nov 2026 stond de
    mailroute daar nog achter, als terugval.
  - Werkt geen enkele bron, dan zet `kies_zoeker()` één `::error` met de
    oorzaken (API, zoekpagina, sitemaps) en geeft een `GeenBron` terug die bij
    elke zoekaanroep faalt zonder netwerk; `main()` stopt dan met exit 2. De
    mailbox gaat in `auto` niet open, ook dan niet.
- **Pool: bekende woningen blijven in beeld.** Bij de mailroute stond elke woning
  maar ~4 dagen in het rapport (gemeten over 38 runs: 27 van 35 stonden er 8-9
  runs), want de mail viel dan buiten het terugkijkvenster. En geen enkele woning
  uit de periode daarvoor kwam terug. `controleer_pool()` haalt daarom elke run
  de woningen uit `funda_tracking.json` (laatst gezien binnen `pool_dagen`,
  standaard 120) die niet al binnenkwamen opnieuw op via het detail-endpoint.
  - Verkocht (ook "verkocht onder voorbehoud") of 3x niet op te halen: in de
    tracking gemarkeerd als `weg` en niet meer opgevraagd. Onder bod/optie: deze
    run niet tonen, wel blijven volgen. Duikt een woning weer op, dan valt `weg`.
  - Mislukte calls tellen alleen mee als het endpoint in dezelfde run wél werkte;
    anders zou een storing van drie runs alle bekende woningen wegmarkeren.
    Bewijs: een geslaagde call van de pool óf van de sitemapzoeker, of een nette
    404. Eerder telde alleen de pool zelf, en een 404 als storing: een run met
    alleen een ingetrokken woning bleef die elke run opvragen zonder hem weg te
    markeren, en vijf 404's bovenaan lieten de pool afbreken ("lijkt dicht"),
    zodat een woning uit de achterstand uit het rapport viel.
  - Weigert het endpoint (401/403/429), mislukken 5 calls op rij (zonder de
    404's), of eindigt de run op een mislukte call: `DetailEndpointDicht` en
    exit 2 in `main()`, niets als weg gemarkeerd. Eerder brak de pool alleen af
    en schreef de run een rapport zonder die woningen.
  - Beschikbaarheid leunt op pyfunda's `status` (IsSoldOrRented) en het kenmerk
    "Status". Die vocabulaire is **niet gemeten**; de log print daarom per run
    welke statuswaarden voorkwamen (bij pool en mail), zonder adressen.
  - De pool draait ná de nul-woningen-checks: een stukke zoekbron laat de run nog
    steeds luid falen, ook als de pool wel iets oplevert.
  - `tracking[...]["url"]` wordt sinds 6 nov bewaard; oudere records worden op
    globalId opgehaald (`get_listing` accepteert dat).
  - `DetailCacheZoeker` voorkomt dat dezelfde woning drie keer per run wordt
    opgehaald (pool, detail-check, rapport).
  - **Met de sitemaproute: de sitemap bepaalt wat de pool níet hoeft op te
    halen, het detail-endpoint bepaalt wat weg is.** Nooit twee detail-calls voor
    dezelfde woning in één run (`SitemapZoeker.pool_oordeel()`): al opgehaald
    door de zoeker = dat antwoord gebruiken; daar mislukt = niet nog eens; op de
    cache overgeslagen (lastmod gelijk, buiten doelmarkt of filter) = overslaan;
    in de achterstand = de pool haalt hem en legt hem vast in de sitemapcache;
    **niet meer in de sitemap = één controle-call**: verkocht/ingetrokken of niet
    op te halen (terwijl het endpoint deze run wél werkte) = meteen `weg`, nog te
    koop = gewoon tonen (de sitemap loopt een dag achter en of "onder bod" erin
    blijft is niet gemeten). Vastgepind in
    `test_funda_zoek.py::test_geen_dubbele_detail_calls` (twee runs door `main()`,
    met een verkochte én een ingetrokken woning buiten de sitemap) en
    `test_pool_404_bovenaan`.
  - Het rapport viel bij een mislukte prijshistorie terug op de URL, en pyfunda
    haalde de woning dan nog eens op via het detail-endpoint. Die terugval geldt
    nu alleen als er geen listing is.
- **Gmail-wachtwoord vervalt.** Op 4 nov 2026 22:02 begon Gmail de login te
  weigeren (`AUTHENTICATIONFAILED`); daarna faalde elke run. Een app-wachtwoord
  wordt onder meer ingetrokken als het Google-wachtwoord wijzigt. De run zet nu een
  `::error::` met die uitleg, in plaats van te eindigen op de (al weken bekende)
  403 van de zoekpagina. Terugkijkvenster van de mail is nu 14 dagen
  (`mail_dagen_terug`), zodat een paar dagen storing geen woningen kost. Sinds
  6 nov 2026 alleen nog relevant bij `zoek_methode: mail`.
- **Postcode niet in de publieke log.** Op Actions toont de startregel en de
  zoek-URL de postcode als "(verborgen)". Actions-logs van een publieke repo zijn
  voor iedereen leesbaar.
- **Zoeken gaat via HTML, verrijken via de API.** `funda_html_zoek.py` haalt de
  woning-URL's van `www.funda.nl/zoeken/koop` (server-rendered Vue/Nuxt, geen
  bot-muur vanaf een Actions-runner) en laat het detail-endpoint - dat nog wél
  werkt - de rest invullen. Dat detail-antwoord bevat exact dezelfde velden als
  de oude zoek-API, inclusief `neighbourhood`, waar de buurtfilters op draaien.
  `HtmlZoeker` is een drop-in voor het `Funda`-object, dus `main()` en het
  rapport weten hier niets van.
  - Schakelen met `FUNDA_ZOEK_METHODE` of `zoek_methode` in de config:
    `auto` (standaard: api -> html -> sitemap, de eerste die werkt), of
    `api`, `html`, `sitemap`, `mail` (die laatste alleen expliciet, niet in
    `auto`). Zodra funda de API of de zoekpagina weer
    openzet, schakelt `auto` vanzelf terug.
  - De parser leunt op de klasse `@container` per woningkaart en op de tekst in
    die kaart. Verandert funda's markup, dan faalt `test_funda_html.py` niet
    (die draait op een fixture) maar `scripts/funda_html_validatie.py` wél.
    Structuur opnieuw afleiden: `scripts/funda_html_analyse.py`.
  - Detail-calls zijn het dure deel. Ze worden gecacht en overgeslagen voor
    woningen die op stad of straat-segment toch al afvallen.
  - **De straal moet een waarde zijn die funda kent** (1, 2, 5, 10, 15, 30, 50).
    Een andere waarde, zoals de 6 km uit de config, geeft géén foutmelding maar
    een lege resultatenpagina: status 200, nul kaarten. `snap_straal()` rondt
    daarom af op de dichtstbijzijnde ondersteunde waarde, net als de oude API.
    Zelfde valkuil bij het gebied: een postcode moet lowercase en zonder spatie.
- **"0 woningen" is niet hetzelfde als "zoeken stuk".** Een run stopt met exit
  code 2 - rapport en state onaangeroerd - in twee gevallen: geen enkele
  geslaagde zoek-call (API dicht), of wél geslaagde calls maar samen nul
  woningen. Dat tweede is de faalmodus van de HTML-route: gewijzigde markup geeft
  netjes 200 en nul kaarten, zonder exception. Zonder deze checks schrijft een
  kapotte zoekmethode een leeg rapport over het gevulde rapport heen terwijl de
  Action groen blijft. Geldt ook voor de sitemapbron: een fout in de bron (403,
  HTML i.p.v. XML, nul kandidaten, een stad zonder URL's, een bevroren sitemap,
  detail-endpoint dicht) wordt bij elke zoekaanroep opnieuw gegooid, zonder
  nieuw verzoek, en eindigt in exit 2. Een derde geval: het detail-endpoint gaat
  tijdens de run dicht (in de zoeker of de pool); ook dan exit 2 en geen half
  rapport (`test_funda_zoek.py::test_endpoint_halverwege_dicht`).
- **pyfunda pin.** Het script gebruikt de v2.x API (`f.search_listing(...)` en
  `r.data` dicts). v3+ is een dataclass-rewrite zonder die methodes. Daarom is
  pyfunda vastgepind op `v2.9.0` in zowel `requirements.txt` als de workflow.
  Niet zomaar upgraden zonder de code mee te porten.
- **Niet in OneDrive zetten.** De repo stond eerst in een OneDrive-map. Dat gaf
  afgekapte bestanden bij opslaan en kapotte `.git`-locks. Daarom verplaatst naar
  `C:\dev\Funda`. Houd de repo buiten OneDrive.
- **Encryptie verplicht in CI.** `funda_rapport.py` weigert een onversleuteld
  rapport te schrijven als `FUNDA_REQUIRE_ENCRYPTION=1` (gezet in de workflow),
  zodat er nooit per ongeluk leesbare data publiek komt. Die check staat vóór het
  schrijven: dan verandert er ook verder niets in `docs/`. Gzip vóór AES
  verandert hier niets aan (`test_funda_pwa.py`).
- **Verander de padenlijst van de Actions-cache nooit zonder migratie.** De
  versie van een cache hangt af van de exacte lijst `path`-regels. PR #13 voegde
  `funda_thuis_coords.json` en `funda_sitemap_cache.json` toe, en daarna vond
  `restore-keys: funda-state-` de oude caches niet meer ("Cache not found"). De
  opstartrun van 6 nov 2026 (run 42287980238) begon daardoor met 0 gezien, lege
  tracking en geen blacklist, en meldde 9 "nieuwe" woningen. Hersteld met een
  tijdelijke migratie in `funda-daily.yml`: de oude cache apart ophalen met de
  oude padenlijst en samenvoegen met `scripts/state_migratie.py` (idempotent,
  print alleen aantallen). Gemeten in run 42290940091: seen 137+9 -> 142,
  tracking 137+9 -> 142. Daarna zijn de migratiestappen weer uit de workflow
  gehaald; het script blijft staan. Nieuwe state? Liever in een bestaand
  bestand, of dezelfde migratie opnieuw inbouwen (oude padenlijst exact
  overnemen, in dezelfde volgorde).
- **Publiceren rebaset eerst.** Run 42290940091 schreef het rapport, maar de push
  werd geweigerd (`rejected ... fetch first`): tijdens de run was een PR in main
  gemerged. De publiceerstap doet nu `git pull --rebase origin main` vóór de
  push; `docs/` wijzigt alleen de bot, dus dat is veilig.
- **Bot pusht zelf.** De workflow commit `docs/` terug naar `main`. Doe lokaal
  altijd `git pull --rebase` voor je commit, anders wordt je push afgewezen.
- **Lokale run commit alleen `docs/`.** `auto_push()` (zonder `--no-push`)
  checkt en commit met het pad `docs/` erbij; andere gestagede wijzigingen
  blijven gestaged. Eerder ging alles mee wat gestaged stond. Aanleiding
  (6 nov 2026): twee worktrees op dezelfde branch, in de ene werd gecommit, en
  de andere checkout had daarna die commit als gestagede terugdraaiing. Een
  lokale run zou die als "auto: rapport" hebben gepusht. Zet daarom nooit twee
  worktrees op dezelfde branch, en zet een checkout die zo verschoven is
  bewust gelijk (`git reset --hard HEAD`, als er geen eigen werk in staat).

## Lokaal draaien

```
pip install -r requirements.txt
python funda_zoek.py            # volledige run + rapport, opent HTML
python funda_zoek.py --no-open  # zonder browser
```

## Tests

- `python test_funda_zoek.py` - offline tests voor de veiligheidschecks in
  `main()`: een run stopt met exit 2 als álle zoek-calls falen én als ze allemaal
  slagen maar samen nul woningen opleveren. Ook de nafilters (stad, woningtype,
  prijs/m2/straal), beschikbaarheid en de pool (storing, weigering, 404's, een
  run die op een fout eindigt), de auto-volgorde api -> html -> sitemap
  (ook: koop-sitemap 403 na een bereikbare index = `GeenBron` met die oorzaak;
  detail-endpoint dicht = geen terugval; `auto` opent de mailbox nooit, ook niet
  als alles faalt; expliciet `mail` werkt nog), het plafond van 600 op
  `sitemap_max_verkennen`, exit 2 bij een kapotte sitemapbron en bij een endpoint dat
  halverwege dichtgaat, geen dubbele detail-calls tussen sitemapzoeker en pool
  (twee runs door `main()`), vijf 404's bovenaan de pool, prijs op aanvraag
  door het echte `bouw_rij`, een volledige run door `genereer_rapport()` op de
  13 fictieve woningen (versleuteld, ontsleuteld in Python, volgorde gelijk aan
  `sorteer()`, rente en verrijking die falen), `_twijfel`, `vul_summary_aan`, de
  pushvolgorde (gelijk aan `sorteer()`), `_enrichment` met alleen ruwe velden en de
  cachesleutel van `price_history`, de waarschuwing bij oude configsleutels en
  de pushtekst (met node, anders overgeslagen; nooit een €-teken, ook niet bij een oude samenvatting), `_sitemap_overslaan` met straal, de workflow-input
  en de eerlijke client met statuscodes (in een subproces tegen het echte
  pyfunda, met een nep-sessie, zonder netwerk).
  `auto_push()` staat in deze tests uit: `main()` eindigt ermee, en een testrun
  mag nooit committen of pushen. De echte `auto_push()` wordt apart getest in
  een tijdelijke repo buiten de projectmap, met een bare repo als remote
  (`test_auto_push_alleen_docs`): alleen `docs/` in de commit, een gestagede
  terugdraaiing blijft gestaged en gaat niet mee naar de remote.
- `python test_funda_sitemap.py` - offline tests voor de sitemaproute: robots en
  index ontleden, kandidaten per stad/type, doelmarkt, drop-in-gedrag per
  prijsband, cache over runs, koop-sitemaps overslaan bij een ongewijzigde index
  (lastmod en Last-Modified), coördinaten in de cache, `pool_oordeel`/`neem_op`,
  de lastmod-meting, budget/achterstand en foutgevallen (403, HTML i.p.v. XML,
  robots-verbod, nul kandidaten, detail-endpoint dicht, gzip), het endpoint dat
  halverwege dichtgaat (5 op rij na successen, meteen bij een weigering, losse
  fouten niet), het tijdsbudget, steden (spelling, een stad zonder URL's) en de
  leeftijd (bevroren sitemap, geen lastmod, kandidatenlijst na 36 uur opnieuw).
  Draait met een vaste klok (`NU`), zodat de leeftijdscheck niet afhangt van de
  dag waarop de tests draaien.
- `python test_funda_mail.py` - offline tests voor de mailbron: linkextractie per
  vorm, ondoorzichtige tracking-links, redirects volgen (inclusief hoplimiet en
  kapotte call), routekeuze van `woningen_uit_mail()`, drop-in-gedrag, cache en
  het vaste profiel voor `links.funda.nl` (gelijk aan dat van `www.funda.nl`).
  De opmaak van de alert-mail zelf is nog niet gemeten; valideer met
  `scripts/funda_mail_validatie.py <mail.eml>` zodra die er is.
- `python test_funda_mail_ophalen.py` - offline tests voor het IMAP-transport:
  decoderen van quoted-printable/base64 en andere charsets, IMAP-datumnotatie,
  payload uit een imaplib-antwoord, en het gedrag bij een lege mailbox, een
  mislukte zoekopdracht, een onophaalbare mail en een fout bij afsluiten. Draait
  op een stub-mailbox, dus geen mailaccount nodig.
- `python test_funda_html.py` - offline tests voor de HTML-zoekfallback
  (URL-opbouw, kaart-parser, drop-in-gedrag, dedup, één profiel en UA met de
  sitemapzoeker). Draait op een fixture die is
  nagebouwd op echte markup, dus geen netwerk nodig.
- `python scripts/funda_html_validatie.py` - controleert diezelfde parser tegen
  de échte funda.nl. Dit is de test die afgaat als funda hun HTML verandert.
- `python test_funda_beoordeling.py` - het model: leentoets 2026 (tabel 1,
  labelbedragen, alleenstaandenbedrag, studieschuld, BKR), scenario's, poort- en
  statusregels (ook "precies op je grens", nooit "€ 0"), harde eisen, score en
  begrenzing, parsers (52 zinnen), sortering, contract, oude configsleutels (niet
  gelezen, wel genoemd door `oude_sleutels()`), golden file
  `testdata/beoordeling_verwacht.json` (bijwerken: `--schrijf-verwacht`) en de
  jaartest (faalt op 1 januari, bewust).
- `python test_funda_ui.py` - de UI op `testdata/beoordeling_v3.json`: id's en
  data-attributen die `ui/app.js` gebruikt, statusregel uit de beoordeling (de UI
  rekent hem niet zelf), WOZ uit `prijshistorie()`, prijs onbekend,
  geldige `#woning-data`, contrast van 51 tokenparen, hex alleen in de
  tokenblokken, geen verboden merk- of fontnamen, groottes en het slotscherm.
- `python test_funda_verrijking.py` en `python test_funda_rente.py` - de open
  bronnen en de rente met een nep-HTTP-functie en ingekorte echte antwoorden
  (`testdata/verrijking/`, `testdata/rente/`): fail-soft, robots, weigering stopt
  een host, cache en budget, allowlist, één poging per dag, de standaardrente uit
  `funda_beoordeling.STANDAARD_RENTE`.
- `python test_funda_pwa.py` - gzip vóór AES en terug (in Python), fout
  wachtwoord, placeholders, geen onversleuteld rapport in CI, service worker v5,
  manifest, slotscherm, iconen in het palet.
- De workflow "Funda API debug" (job **tests**) draait elk `test_*.py` vanzelf.

## Kernfeatures (waarom de code is zoals hij is)

- **Prijsband-splitsing.** Funda kapt een zoekopdracht af op ~140 resultaten.
  Door per prijsband (stap 20k) te zoeken en te dedupen pakken we meer van de
  markt, inclusief woningen die al lang te koop staan.
- **Eigen prijs-tracking** in `funda_tracking.json`: detecteert prijsdalingen
  los van wat Funda teruggeeft. Flags voor prijsdaling en "lang op funda".
- **Verversknop** in het rapport linkt naar de Actions "Run workflow"-pagina
  (geen token nodig, dus veilig op een publieke pagina).
- **iOS PWA push** werkt zonder vaste backend: de webapp toont een subscription
  JSON, die als GitHub Secret `WEB_PUSH_SUBSCRIPTION` wordt opgeslagen. Actions
  stuurt daarna met `scripts/send_web_push.cjs` een Web Push bij nieuwe woningen,
  met per woning het poortwoord en de score (geen bedragen). Het blok "Meldingen op deze iPhone"
  verdwijnt zodra dit toestel een abonnement heeft.
- **Financiering is een poort, geen punt.** Eerst: kun je het lenen en wil je
  het elke maand betalen (netto woonlasten tegenover je grens)? Dat bepaalt de
  groep; pas daarbinnen telt de score. Onbekend is geen minpunt, twijfel zet een
  woning onderaan maar nooit weg.
