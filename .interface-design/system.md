# Ontwerpsysteem: Woningrapport, palet "Lavendel"

Vastgelegde keuzes voor het woningrapport en de PWA (bouwronde november 2026). Gebruik deze
waarden; verzin ze niet opnieuw. De bron van waarheid is `ui/app.css` (tokens) met
`funda_ui.py` (markup) en `ui/slot.html` (slotscherm). `test_funda_ui.py` controleert de regels
hieronder (contrast, hex alleen in de tokenblokken, lettergrootte, verboden woorden).

## Bedoeling
- **Wie:** een starter die een koopappartement zoekt in de regio Den Haag met een krap budget. Kijkt
  twee keer per dag, op de iPhone (geïnstalleerde PWA), vaak onderweg.
- **Wat:** in een paar seconden zien wat nieuw is, of het past (poort) en waarom (score en redenen),
  en dan bewaren, verbergen of op funda openen.
- **Gevoel:** fris, rustig, overzichtelijk. Een eigen palet, geen merk.

## Kleur
Diep paars als merkkleur (topbalk, knoppen, score), koel grijs als vlak, kaarten in wit. In donker
zijn de vlakken bijna zwart met een paarse zweem en is lavendel het accent.

Regels:
- Hex staat **alleen** in de drie tokenblokken van `ui/app.css`: `:root` (licht), donker onder
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` en nog eens onder
  `:root[data-theme="dark"]` (die twee gelijk). Alle andere CSS gebruikt `var(--...)`. Enige
  uitzondering: `dialog::backdrop` (rgba; custom properties erven daar niet betrouwbaar in Safari).
- Feedbackkleuren (positief, let op, negatief, informatief) alleen voor feedback: poort, plus en min,
  fouten. Nooit als versiering.
- Kleur is nooit de enige drager: de poort is woord plus icoon (vinkje, driehoek, kruis, i), ook op
  de kaartpins en in de legenda; plus en min hebben een teken; "nieuw" op de kaart is een ring;
  "beste" in de vergelijking staat er als tekst.
- Geen ANWB-blauw (`#003d86` of verwant), geen geel (`#ffcd00`), geen merkfont of merknaam. Waarom:
  zie CLAUDE.md, "Huisstijl".

| Token | Licht | Donker | Gebruik |
|---|---|---|---|
| `--background-color-page` | `#f4f5f8` | `#121019` | pagina |
| `--background-color-default` | `#ffffff` | `#1c1927` | kaart, sheet, onderbalk |
| `--background-color-inset` | `#eef0f4` | `#252131` | fotovlak, invoerveld, balkspoor |
| `--background-color-subtle` | `#e2e5eb` | `#2f2a3d` | schakelaar uit |
| `--background-color-strong` | `#2e1f6b` | `#2e1f6b` | topbalk, toast, slotsymbool, theme-color |
| `--background-color-on-strong-hover` | `#3d2b85` | `#3d2b85` | hover in de topbalk |
| `--foreground-color-strong` | `#4527a0` | `#c9bcff` | koppen, score |
| `--foreground-color-neutral` | `#16141f` | `#f3f1f8` | lopende tekst |
| `--foreground-color-subtle` | `#5c5a68` | `#b3adc4` | meta, bron |
| `--foreground-color-on-strong` | `#ffffff` | `#ffffff` | tekst op de topbalk |
| `--foreground-color-on-strong-subtle` | `#d6cff5` | `#d6cff5` | ondertitel topbalk |
| `--foreground-color-highlight-strong` | `#5233c4` | `#b8a6ff` | tekstlinks |
| `--border-color-default` / `-subtle` | `#d3d6de` / `#e3e5ea` | `#474059` / `#2f2a3e` | knoprand, kaartrand (decoratief) |
| `--border-color-interactive-neutral` | `#6e6b7b` | `#a49db8` | onderrand veld, schakelaar, keuze |
| `--border-color-interactive-focus` | `#6c47ff` | `#a58bff` | focusring 2 px, offset 2 px |
| `--background-color-interactive-strong` | `#5233c4` | `#c4b5fd` | knop, chip aan, teller |
| `--background-color-interactive-strong-hover` | `#43299f` | `#d5caff` | |
| `--foreground-color-interactive-on-strong` | `#ffffff` | `#1f1147` | tekst op een knop |
| `--background-color-interactive-weak` | `#f1eefc` | `#2a2440` | hover tertiair |
| `--foreground-color-interactive-strong` | `#4a2fb3` | `#c9bcff` | summary, tertiaire knop |
| `--foreground-color-feedback-positive` | `#16803c` | `#6fd08f` | Past, plus |
| `--foreground-color-feedback-notice` | `#c46a00` | `#f2b860` | Krap, let op (icoon en rand) |
| `--foreground-color-feedback-negative` | `#c4282b` | `#f59a9a` | Past niet, min, fout |
| `--foreground-color-feedback-informative` | `#0b6aa8` | `#73bdf0` | Prijs onbekend, onbekend, kans |
| `--background-color-feedback-*-weak` | `#e8f6ed` / `#fdf2e1` / `#fdeceb` / `#e5f1fa` | `#15291e` / `#2e2413` / `#321a1e` / `#13263a` | statusvlak |
| `--status-tekst` | `#16141f` | `#f3f1f8` | tekst in statusregel en melding |
| `--label-daling` / `--label-lang` / `--label-tekst` | `#a3195b` / `#485a6e` / `#ffffff` | gelijk | labels "Prijs gedaald", "Lang te koop" |
| `--pin-past` / `-krap` / `-niet` / `-onbekend` | `#16803c` / `#e08a00` / `#c4282b` / `#0b6aa8` | gelijk | kaartpins (staan op de tegels) |
| `--pin-tekst` / `-tekst-krap` / `-rand` / `-nieuw` | `#ffffff` / `#16141f` / `#ffffff` / `#2e1f6b` | gelijk | Krap-pin met donkere tekst |

PWA en iconen: `funda_ui.THEME_COLOR` (`#2e1f6b`) voor `theme_color` en `<meta name="theme-color">`,
`funda_ui.ACHTERGROND` (`#f4f5f8`) voor `background_color`. Icoon: wit huis met een lavendel raam
(`#c4b5fd`) op het paars van de topbalk; de PNG vult het hele vlak (ook als maskable).

## Contrast (WCAG 2.x, gemeten)
- Tekst minimaal 4,5:1, niet-tekst (randen, iconen, focus, schakelaar, balk) minimaal 3:1, in licht
  én donker. `test_funda_ui.py` rekent 51 paren uit de tokens na.
- Laagste tekstpaar: 5,0:1 (Past-pin en plus op wit). Laagste niet-tekst: 3,5:1 (Krap-icoon op het
  Krap-vlak). In de browser gemeten op de effectieve achtergrond: 0 tekstparen onder het minimum.

## Typografie
Systeemletter: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans",
Arial, sans-serif`. Geen webfont, geen merkfont (ook niet als naam in de stack). Alle tekst via
`font: var(--token)`, nooit een losse `font-size`. Cijfers `tabular-nums`.

| Token | Waarde | Gebruik |
|---|---|---|
| `--heading-medium` | 500 22/28 | h1 slotscherm |
| `--heading-app` | 600 18/24 | h1 topbalk, sheetkop |
| `--heading-small` | 600 17/22 | adres (h3), lege toestand |
| `--paragraph-title-medium` | 600 16/24 | sectiekop, legend, knop |
| `--paragraph-title-compact` | 600 15/22 | summaries, onderknoppen |
| `--paragraph-title-small` | 600 14/20 | punten, veldlabel |
| `--paragraph-body-medium` | 400 16/24 | body, invoer (16 px: geen zoom op iOS) |
| `--paragraph-body-status` | 400 15/22 | statusregel |
| `--paragraph-body-small` | 400 14/20 | meta, lijsten, uitleg |
| `--paragraph-body-xsmall` | 400 13/18 | bron, kerncijfer-label (minimum 13 px) |
| `--label-small` | 600 13/18 | labels |
| `--label-chip` | 600 15/20 | snelfilters |
| `--cijfer-groot` | 600 20/24 | bedragen in de kerncijfers |
| `--teken` | 600 13/1 | + en − in rondjes, tellers |

Geen hoofdletters als stijl, geen letterspatiëring, vet is 600 (nooit 700). Geen tekst kleiner dan
13 px.

## Ruimte, vorm en maat
- Spacing: 25 = 2 px, 50 = 4, 75 = 6, 100 = 8, 150 = 12, 200 = 16, 300 = 24, 400 = 32. Paginarand
  mobiel 12 px, kaartpadding 12 px (desktop 16), 12 px tussen kaarten, 24 tot 32 tussen secties.
- Radius: 100 = 4 px (knop, label, foto, veld), 200 = 8 px (kaart, opbouw, sheet), pill (chip,
  teller, pin).
- Maten: `--tap` 44 px minimum voor alles wat je aantikt; `--knop` 48 px voor knoppen en summaries in
  de kaart; topbalk 56 px, onderbalk 64 px, beide plus safe area.
- Diepte: borders-first. Geen schaduw in rust; alleen de sheet heeft een backdrop.

## Iconen
Eigen tekeningen: lijnstijl 2 px, viewBox 24 x 24, `stroke: currentColor`, `fill: none`, in één
`<svg class="sprite">` bovenaan de body (`funda_ui.SPRITE`). Decoratieve iconen
`aria-hidden="true" focusable="false"`. Het slotscherm heeft een eigen inline slot- en oogicoon (de
sprite zit in de versleutelde body).

## Opbouw
- Topbalk "Woningen" met bijgewerkt en volgende run; snelfilters als chips; rentemelding alleen als de
  rente oud is; "Nieuw sinds je vorige bezoek" (per toestel, pas gezien als de kaart minstens de
  helft een seconde in beeld was); daarna per poort Past, Krap, Past niet (ingeklapt), Prijs onbekend.
- Woningkaart laag 1: statusregel (`<Poort> · <reden>`, met scenario eronder), foto, adres met ster,
  buurt en stad, feitenregel, fietstijd, labels, kerncijfers (Vraagprijs, Woonlasten, Score),
  twijfelregel ("Onderaan gezet."), redenregel, kaartvoet met Let op en Pluspunten, Bekijk op funda
  en Verberg. Laag 2 in `details`: Let op, Pluspunten, Onbekend en kansen, Opbouw score, Geld, Woning,
  Zelf nagaan, foto's.
- Voet: verborgen woningen, Jouw budget en aannames (grens, rente met bron en peildatum, max. koopsom
  per scenario, nooit inkomen), Meldingen op deze iPhone (alleen zonder abonnement), Dit apparaat,
  Bronnen.
- Desktop vanaf 64rem: lijst links, plakkende zijkolom (filter, vergelijk, kaart) rechts.

## Tekst
Nederlands, je-vorm, korte zinnen, geen em dash of gedachtestreepje. `€ 1.250` met spatie, `m²`,
decimale komma, minteken U+2212. Nooit "€ 0": zonder vraagprijs staat er "op aanvraag", zonder
woonlasten "onbekend".

## Toegankelijkheid (verplicht)
`lang="nl"`, één h1, h2 per groep, h3 per woning, `article` met `aria-labelledby`. Focusring 2 px.
Elk veld een `<label for>`, schakelaar met `role="switch"`, slotfout met `role="alert"` en
`aria-invalid`, toast `role="status"`. Ster, Verberg en Bekijk op funda hebben het adres in de naam.
`prefers-reduced-motion` zet overgangen uit. Geen horizontale scroll op 390 px.

## Beweging
Kort (onder 200 ms), alleen transform en opacity. Chevron draait 180 graden bij openen.
