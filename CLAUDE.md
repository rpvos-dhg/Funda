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
  (notificatiemails, terugval). `kies_zoeker()` kiest; zie hieronder.
- `funda_rapport.py` - bouwt markdown/HTML/PWA. Rekent maandlasten, hypotheek
  (NHG, starter), reisafstand naar werk, erfpacht, energielabel, pros/cons.
- `.github/workflows/funda-daily.yml` - draait 2x/dag (08:30 en 16:30 UTC =
  10:30 en 18:30 NL), genereert het rapport en pusht `docs/`.
- `funda_personal.example.json` - template voor de privé-config.

## Privébestanden (NIET op git, staan in .gitignore)

Deze leven alleen lokaal en mogen nooit gecommit worden:
`funda_personal.json` (inkomen, postcodes), `funda_pwa_password.txt`,
`funda_seen_ids.json`, `funda_tracking.json`, `funda_werk_coords.json`,
`funda_blacklist.json`, `funda_log.txt`.

Op GitHub komen dezelfde gegevens uit Secrets: `FUNDA_PERSONAL_JSON` en
`FUNDA_PWA_PASSWORD`. Optionele PWA push gebruikt `WEB_PUSH_PUBLIC_KEY`,
`WEB_PUSH_PRIVATE_KEY` en `WEB_PUSH_SUBSCRIPTION`. De state (seen-ids, tracking,
werk-coords, verrijkingscache en `funda_sitemap_cache.json`) staat in de
Actions-cache, niet in de repo.

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
  Diagnose herhalen: workflow "Funda API debug" (de probes draaien ook
  automatisch zodra een dagelijkse run faalt). Die workflow heeft drie jobs:
  **tests** moet groen zijn en zegt iets over de code; **funda-live** staat op
  `continue-on-error` en zegt iets over funda's kant; **mail-live** zegt iets
  over onze eigen mailconfiguratie en mag daarom wél gewoon rood worden. Zo
  blijft de workflow groen bij een netwerkblokkade, terwijl de job-status
  leesbaar blijft: funda-live rood = funda dicht, groen = funda laat weer door.
  Bewust op job-niveau, want `continue-on-error` op een stap laat GitHub die
  stap als "success" rapporteren ook als het commando faalde. Het échte
  faalsignaal blijft de dagelijkse workflow, die wél rood wordt en niets
  publiceert.
- **Zoekpagina geeft sinds 8 okt 2026 een 403 vanaf GitHub Actions.** Daarmee
  ligt ook de HTML-route eruit; de dagelijkse run faalt luid en publiceert niets.
  Gemeten op 9 oktober met `scripts/funda_403_probe.py`: zes TLS-profielen
  (safari15_5/17_0, chrome120/124/131, firefox133) x drie headersets (minimaal,
  browser-achtig, met referer) plus twee varianten die eerst de homepage
  bezoeken - **alle twintig 403**, body ~536 bytes. De blokkade zit dus op het
  netwerk/IP van de runner, niet op hoe de client zich voordoet; headers of TLS-
  profielen aanpassen helpt niet. Upstream pyfunda v3.1.5 voegde juist dat toe
  (chrome124 + roteren bij 403 + backoff), dus upgraden lost dit óók niet op.
  Gemeten per pad (`scripts/funda_bronnen_probe.py`): zoekpagina met én zonder
  slash 403, Nuxt-payload 403, **detailpagina als HTML ook 403**, sitemap 404
  (alleen `/sitemap.xml`; de echte staat op `/sitemap_index.xml/` en geeft 200,
  zie de sitemaproute), robots.txt 200, homepage 200. Vrijwel heel `www.funda.nl` is dus dicht voor de
  runner; de homepage komt alleen door omdat die uit Akamai's statische cache
  komt. De aparte API-host `listing-detail-page.funda.io` geeft nog wél 200.
  Ook gemeten: pyfunda **v3.1.5** (`scripts/funda_v315_probe.py`), die in augustus
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
  - **Vaste vingerafdruk.** pyfunda v2.9.0 loopt in `_find_working_fingerprint()`
    zijn `FINGERPRINT_POOL` af (twee app-JA3's, twee Safari-profielen, okhttp,
    chrome) tot er één een 200 krijgt: stil wisselen bij een blokkade. De
    `Funda`-subklasse in `funda_zoek.py` overschrijft dat: alleen
    `FINGERPRINT_POOL[0]`, en werkt die niet, dan een `RuntimeError` die dat
    uitlegt (één keer per run, daarna onthouden). De sitemap- en HTML-zoeker
    gebruiken elk ook één vast curl_cffi-profiel (`safari15_5`). Een 401, 403 of
    bot-controle = luid falen. Vastgepind in
    `test_funda_zoek.py::test_vaste_vingerafdruk` (tegen het echte pyfunda).
- **Sitemaproute: funda's eigen sitemaps als bron** (`funda_sitemap_zoek.py`). In
  `auto` de derde stap: api -> html -> **sitemap** -> mail. Werkt vanaf Actions
  zonder mailbox. Gemeten op 6 nov 2026 (runs
  [42260153909](https://github.com/rpvos-dhg/Funda/actions/runs/42260153909),
  [42261516145](https://github.com/rpvos-dhg/Funda/actions/runs/42261516145),
  [42262032618](https://github.com/rpvos-dhg/Funda/actions/runs/42262032618)):
  - `robots.txt` (200, text/plain) staat `/detail/` en `/zoeken/` toe voor `*`
    en noemt `Sitemap: https://www.funda.nl/sitemap_index.xml/`. Let op de slash:
    `/sitemap.xml` is 404, daarom vond `funda_bronnen_probe.py` eerder niets. De
    zoeker leest robots.txt elke run en stopt als `/detail/` wordt uitgesloten.
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
    coördinaten) = doorlaten. Steden via `sitemap_steden` (funda-slugs).
  - **Opstart: achterstand.** Een lege cache betekent ~3.100 woningen zonder
    gegevens. Per run `sitemap_max_verkennen` (standaard 200) detail-calls,
    nieuwste lastmod eerst; bij 2 runs per dag is dat na hooguit ~8 dagen weg
    (verre en te dure woningen kosten maar één call). Nieuw aanbod zit vanaf de
    eerste run in de top. **Sneller:** workflow "Funda dagelijks rapport"
    handmatig starten met input `sitemap_max_verkennen` = 600 (wordt
    `FUNDA_SITEMAP_MAX_VERKENNEN`); leeg laten = standaard.
  - Luid falen blijft: 403, HTML in plaats van XML of nul kandidaten =
    `RuntimeError` en exit 2 via de bestaande checks in `main()`; de eerste vijf
    detail-calls allemaal mislukt = "detail-endpoint werkt niet", ook exit 2.
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
  - Valideren tegen de echte site: `scripts/funda_sitemap_validatie.py`
    (end-to-end door `main()`, zonder rapport of push) en
    `scripts/funda_sitemap_probe.py` (robots en sitemaps meten).
- **robots.txt van de API-hosts.** `www.funda.nl` staat `/detail/` en de sitemap
  toe. `listing-detail-page.funda.io` (het detail-endpoint), `local-listings` en
  `listing-detail-summary` (beide `.funda.io`) hebben `Disallow: /`. Elke
  funda-route hier (api, html, sitemap, mail en de pool) verrijkt via die
  detail-host; dat is een keuze van de gebruiker. `local-listings` en
  `listing-detail-summary` worden door dit script niet aangeroepen.
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
  - De vocabulaire van `soortwoning` is **niet** gemeten. `mail-live` print
    daarom de woningtypes volgens de URL-slug, zodat zichtbaar is of er
    überhaupt huizen in de mails zitten en of het filter het juiste woord kent.
  - Prijs, oppervlak en straal hebben sinds 6 nov 2026 wél een nafilter, zie
    hierboven.
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
- **Mailroute: transport via IMAP; sinds de sitemaproute de terugval.** `auto` is
  nu api -> html -> sitemap -> mail: de mailbox wordt alleen nog geopend als de
  sitemaps ook niet werken. `funda_mail_ophalen.py` haalt de mails op,
  `funda_mail_bron.py` haalt er de woningen uit. Bewust gescheiden: het transport is te testen zonder mailbox, de
  parser zonder netwerk.
  - Twee nieuwe instellingen: `FUNDA_MAIL_USER` (of `mail_gebruiker` in de
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
    dat zijn publieke funda-nummers. Houd dat zo. Draait als job `mail-live` in
    de debug-workflow, die wél gewoon rood mag worden: die gaat over onze eigen
    configuratie, niet over funda's kant.
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
  - In `auto` staat de mailroute achteraan en wordt die alleen gekozen als er
    echt woningen uit komen. Een lege mailbron zou de run op de nul-woningen-
    check laten vallen met een misleidende melding, terwijl de echte oorzaak is
    dat er geen mailroute is ingericht. `HtmlZoeker.bereikbaar()` en
    `SitemapZoeker.bereikbaar()` doen de tussenstappen: één of twee goedkope
    calls, zodat niet alle prijsbanden op een 403 lopen.
  - Werkt geen enkele bron, dan zet `kies_zoeker()` één `::error` met alle
    oorzaken (API, zoekpagina, sitemaps, mail) en geeft een `GeenBron` terug die
    bij elke zoekaanroep faalt zonder netwerk; `main()` stopt dan met exit 2.
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
    `test_funda_zoek.py::test_geen_dubbele_detail_calls` (twee runs door `main()`).
  - Het rapport viel bij een mislukte prijshistorie terug op de URL, en pyfunda
    haalde de woning dan nog eens op via het detail-endpoint. Die terugval geldt
    nu alleen als er geen listing is.
- **Gmail-wachtwoord vervalt.** Op 4 nov 2026 22:02 begon Gmail de login te
  weigeren (`AUTHENTICATIONFAILED`); daarna faalde elke run. Een app-wachtwoord
  wordt onder meer ingetrokken als het Google-wachtwoord wijzigt. De run zet nu een
  `::error::` met die uitleg, in plaats van te eindigen op de (al weken bekende)
  403 van de zoekpagina. Terugkijkvenster van de mail is nu 14 dagen
  (`mail_dagen_terug`), zodat een paar dagen storing geen woningen kost.
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
    `auto` (standaard: api -> html -> sitemap -> mail, de eerste die werkt),
    `api`, `html`, `sitemap`, `mail`. Zodra funda de API of de zoekpagina weer
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
  HTML i.p.v. XML, nul kandidaten, detail-endpoint dicht) wordt bij elke
  zoekaanroep opnieuw gegooid, zonder nieuw verzoek, en eindigt in exit 2.
- **pyfunda pin.** Het script gebruikt de v2.x API (`f.search_listing(...)` en
  `r.data` dicts). v3+ is een dataclass-rewrite zonder die methodes. Daarom is
  pyfunda vastgepind op `v2.9.0` in zowel `requirements.txt` als de workflow.
  Niet zomaar upgraden zonder de code mee te porten.
- **Niet in OneDrive zetten.** De repo stond eerst in een OneDrive-map. Dat gaf
  afgekapte bestanden bij opslaan en kapotte `.git`-locks. Daarom verplaatst naar
  `C:\dev\Funda`. Houd de repo buiten OneDrive.
- **Encryptie verplicht in CI.** `funda_rapport.py` weigert een onversleuteld
  rapport te schrijven als `FUNDA_REQUIRE_ENCRYPTION=1` (gezet in de workflow),
  zodat er nooit per ongeluk leesbare data publiek komt.
- **Bot pusht zelf.** De workflow commit `docs/` terug naar `main`. Doe lokaal
  altijd `git pull --rebase` voor je commit, anders wordt je push afgewezen.

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
  prijs/m2/straal), beschikbaarheid en de pool (inclusief het storingsgeval),
  de auto-volgorde api -> html -> sitemap -> mail, exit 2 bij een kapotte
  sitemapbron, geen dubbele detail-calls tussen sitemapzoeker en pool (twee
  runs door `main()`), `_sitemap_overslaan` met straal, de workflow-input en de
  vaste vingerafdruk (in een subproces tegen het echte pyfunda, zonder netwerk).
  `auto_push()` staat in deze tests uit: `main()` eindigt ermee, en de
  `git diff --cached`-check daarin ziet álle gestagede wijzigingen, dus zonder
  die stub commit een testrun je gestagede werk als "auto: rapport".
- `python test_funda_sitemap.py` - offline tests voor de sitemaproute: robots en
  index ontleden, kandidaten per stad/type, doelmarkt, drop-in-gedrag per
  prijsband, cache over runs, koop-sitemaps overslaan bij een ongewijzigde index
  (lastmod en Last-Modified), coördinaten in de cache, `pool_oordeel`/`neem_op`,
  de lastmod-meting, budget/achterstand en foutgevallen (403, HTML i.p.v. XML,
  robots-verbod, nul kandidaten, detail-endpoint dicht, gzip).
- `python test_funda_mail.py` - offline tests voor de mailbron: linkextractie per
  vorm, ondoorzichtige tracking-links, redirects volgen (inclusief hoplimiet en
  kapotte call), routekeuze van `woningen_uit_mail()`, drop-in-gedrag en cache.
  De opmaak van de alert-mail zelf is nog niet gemeten; valideer met
  `scripts/funda_mail_validatie.py <mail.eml>` zodra die er is.
- `python test_funda_mail_ophalen.py` - offline tests voor het IMAP-transport:
  decoderen van quoted-printable/base64 en andere charsets, IMAP-datumnotatie,
  payload uit een imaplib-antwoord, en het gedrag bij een lege mailbox, een
  mislukte zoekopdracht, een onophaalbare mail en een fout bij afsluiten. Draait
  op een stub-mailbox, dus geen mailaccount nodig.
- `python test_funda_html.py` - offline tests voor de HTML-zoekfallback
  (URL-opbouw, kaart-parser, drop-in-gedrag, dedup). Draait op een fixture die is
  nagebouwd op echte markup, dus geen netwerk nodig.
- `python scripts/funda_html_validatie.py` - controleert diezelfde parser tegen
  de échte funda.nl. Dit is de test die afgaat als funda hun HTML verandert.
- `test_funda.py` (indien aanwezig) stubt de funda-library en test
  band-splitsing, tracking, prijsdaling-detectie en rapport-rendering offline.

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
  stuurt daarna met `scripts/send_web_push.cjs` een Web Push bij nieuwe woningen.
