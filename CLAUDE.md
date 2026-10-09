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
werk-coords en verrijkingscache) staat in de Actions-cache, niet in de repo.

## Belangrijke valkuilen (eerder tegengekomen)

- **Zoek-API zit sinds 18 aug 2026 achter auth (`401 no token provided`).**
  `listing-search-wonen.funda.io/_msearch/template` eist nu een token dat
  pyfunda niet meestuurt; ook v3.1.4 niet (upstream issue 0xMH/pyfunda#15, zelfde
  datum, nog steeds open en zonder commits sinds 17 juli). Daarom zoekt het
  script nu via de publieke zoekpagina, zie hieronder.
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
  slash 403, Nuxt-payload 403, **detailpagina als HTML ook 403**, sitemap 404,
  robots.txt 200, homepage 200. Vrijwel heel `www.funda.nl` is dus dicht voor de
  runner; de homepage komt alleen door omdat die uit Akamai's statische cache
  komt. De aparte API-host `listing-detail-page.funda.io` geeft nog wél 200.
  Ook gemeten: pyfunda **v3.1.5** (`scripts/funda_v315_probe.py`), die in augustus
  een webroute toevoegde. `search()` geeft `curl (92) HTTP/2 stream reset by
  server`. Upgraden helpt dus niet, en kost ook de incompatibele v3-rewrite.
  Zoeken vereist een ander uitgaand IP (self-hosted runner op een eigen netwerk,
  waar dit project oorspronkelijk liep), óf een bron die funda zelf pusht:
  een bewaarde zoekopdracht met mailnotificatie. Die mails staan er nu niet
  (gecheckt in Gmail, 9 okt); funda mailt wel transactioneel via
  `notificaties@service.funda.nl`, dus het kanaal werkt. Met zo'n mail als bron
  kan het detail-endpoint de rest nog gewoon aanvullen. Zie de mailbron hieronder.
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
  - **Gebied: ruim zetten.** Stad, buurt en straat-segment worden na het ophalen
    nog gefilterd (`is_uitgesloten_stad`, `is_uitgesloten_buurt`,
    `is_uitgesloten_straat_nr`), net als belegging en begane grond. Extra gebied
    in de zoekopdracht kost dus alleen wat ruis, en mist niets.
  - **Prijs en m2: exact zetten.** `PRIJS_MIN`, `PRIJS_MAX` en `M2_MIN` zijn
    alléén zoekparameters; er is **geen** nafilter op prijs of oppervlak. Bij de
    mailroute bepaalt de bewaarde zoekopdracht die grenzen dus volledig, en staat
    hij te ruim, dan komen te dure of te kleine woningen ongefilterd in het
    rapport. Wil je dat afdekken, dan moet er eerst een nafilter bij.
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
- **Mailroute: transport via IMAP, en `auto` is nu api -> html -> mail.**
  `funda_mail_ophalen.py` haalt de mails op, `funda_mail_bron.py` haalt er de
  woningen uit. Bewust gescheiden: het transport is te testen zonder mailbox, de
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
    dat er geen mailroute is ingericht. `HtmlZoeker.bereikbaar()` doet de
    tussenstap: één goedkope call, zodat niet alle prijsbanden op een 403 lopen.
- **Zoeken gaat via HTML, verrijken via de API.** `funda_html_zoek.py` haalt de
  woning-URL's van `www.funda.nl/zoeken/koop` (server-rendered Vue/Nuxt, geen
  bot-muur vanaf een Actions-runner) en laat het detail-endpoint - dat nog wél
  werkt - de rest invullen. Dat detail-antwoord bevat exact dezelfde velden als
  de oude zoek-API, inclusief `neighbourhood`, waar de buurtfilters op draaien.
  `HtmlZoeker` is een drop-in voor het `Funda`-object, dus `main()` en het
  rapport weten hier niets van.
  - Schakelen met `FUNDA_ZOEK_METHODE` of `zoek_methode` in de config:
    `auto` (standaard, probeert eerst de API en valt terug op HTML), `api`, `html`.
    Zodra Funda de API weer openzet, schakelt `auto` vanzelf terug.
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
  Action groen blijft.
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
  slagen maar samen nul woningen opleveren.
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
