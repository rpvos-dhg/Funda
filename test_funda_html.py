"""Offline tests voor de HTML-zoekfallback. Geen netwerk nodig.

De fixture hieronder is nagebouwd op echte markup van funda.nl (Vue/Nuxt SSR,
Tailwind-klassen), opgehaald via scripts/funda_html_analyse.py.

Draaien: python test_funda_html.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from funda_html_zoek import HtmlZoeker, bouw_zoek_url, parse_kaarten, snap_straal


def kaart_html(
    *,
    stad_slug: str,
    slug: str,
    tiny_id: str,
    adres: str,
    postcode: str,
    stad: str,
    prijs: str,
    m2: str,
    kamers: str,
    nieuw: bool = False,
) -> str:
    badge = (
        '<div class="absolute top-1 left-2 z-2"><!--[--><span class="mr-1 mb-1 inline-block '
        'rounded-sm px-2 py-0.5 text-xs font-semibold bg-primary-50 text-white">'
        "<!--[-->Nieuw<!--]--></span><!--]--></div>"
        if nieuw
        else "<!---->"
    )
    return (
        '<div class="@container border-b pb-3"><div class="flex flex-col @lg:flex-row">'
        '<div class="relative overflow-hidden rounded-md">'
        f"{badge}"
        f'<a href="/detail/koop/{stad_slug}/{slug}/{tiny_id}/" class="min-w-[358px]">'
        '<div class="aspect-[3/2] size-full"><img width="720" height="480" '
        'srcset="https://cloud.funda.nl/x?options=width=228 228w" alt="main image">'
        "</div></a></div>"
        '<div class="flex grow flex-col justify-between p-4">'
        f'<h2 class="truncate font-semibold"><!--[-->{adres}<!--]--></h2>'
        f'<div class="truncate text-neutral-80"><!--[-->{postcode} {stad}<!--]--></div>'
        f'<p class="font-semibold"><!--[-->{prijs}<!--]--></p>'
        f'<ul class="flex gap-4"><li><span>{m2}</span></li><li><span>{kamers}</span></li></ul>'
        '<div class="text-xs"><!--[-->MHXog (Maxime Hendrickx OG)<!--]--></div>'
        "</div></div></div>"
    )


PAGINA = (
    '<!doctype html><html lang="nl"><head><title>Koopwoningen Den Haag | Funda</title></head>'
    '<body><div class="results"><div class="flex flex-col gap-3 mt-4">'
    + kaart_html(
        stad_slug="den-haag",
        slug="appartement-jonckbloetplein-30",
        tiny_id="44576894",
        adres="Jonckbloetplein 30",
        postcode="2523 AS",
        stad="Den Haag",
        prijs="€ 299.000 k.k.",
        m2="73 m²",
        kamers="4",
        nieuw=True,
    )
    + kaart_html(
        stad_slug="voorburg",
        slug="appartement-rodelaan-139",
        tiny_id="44564274",
        adres="Rodelaan 139",
        postcode="2283 GH",
        stad="Voorburg",
        prijs="€ 275.000 k.k.",
        m2="68 m²",
        kamers="3",
    )
    + kaart_html(
        stad_slug="rijswijk",
        slug="appartement-generaal-spoorlaan-12",
        tiny_id="44511111",
        adres="Generaal Spoorlaan 12",
        postcode="2283 GA",
        stad="Rijswijk",
        prijs="€ 260.000 k.k.",
        m2="61 m²",
        kamers="3",
    )
    + "</div></div></body></html>"
)


class StubListing:
    def __init__(self, data):
        self.data = data


class StubClient:
    """Doet alsof het detail-endpoint werkt; telt de calls."""

    def __init__(self, extra: dict | None = None, faal_op: set[str] | None = None):
        self.calls: list[str] = []
        self.extra = extra or {}
        self.faal_op = faal_op or set()

    def get_listing(self, ident):
        self.calls.append(str(ident))
        for stuk in self.faal_op:
            if stuk in str(ident):
                raise RuntimeError("detail stuk")
        tiny = "".join(c for c in str(ident).split("/")[-2] if c.isdigit())
        data = {
            "global_id": f"g{tiny}",
            "tiny_id": tiny,
            "neighbourhood": self.extra.get(tiny, "Bomenbuurt"),
            "energy_label": "C",
            "description": "Ruim appartement met balkon.",
        }
        return StubListing(data)


def check(naam: str, voorwaarde: bool, extra: str = "") -> bool:
    print(f"  {'OK  ' if voorwaarde else 'FOUT'} {naam}{(' -> ' + extra) if extra else ''}")
    return voorwaarde


def test_url() -> bool:
    print("test: URL-opbouw")
    ok = True
    url = bouw_zoek_url(
        gebied="Den Haag",
        radius_km=5,
        prijs_min=230000,
        prijs_max=250000,
        object_type=["apartment"],
        oppervlakte_min=52,
        sort="date_up",
        pagina=2,
    )
    ok &= check("straal in selected_area", "den-haag%2C5km" in url, url)
    ok &= check("prijsband", "price=230000-250000" in url)
    ok &= check("oppervlakte", "floor_area=52-" in url)
    ok &= check("paginering", "search_result=2" in url)
    ok &= check("beschikbaarheid standaard", "availability" in url)

    kaal = bouw_zoek_url(gebied="2513AA")
    ok &= check("postcode lowercase, geen straal", "2513aa" in kaal and "km" not in kaal, kaal)
    ok &= check("pagina 1 zonder search_result", "search_result" not in kaal)
    return ok


def test_straal() -> bool:
    print("test: straal snappen naar wat funda accepteert")
    # Een niet-ondersteunde straal geeft geen fout maar een lege resultatenpagina
    # (status 200, nul kaarten). Dat kostte een productierun met radius_km=6.
    ok = True
    ok &= check("geen straal blijft None", snap_straal(None) is None)
    ok &= check("6 -> 5", snap_straal(6) == 5, str(snap_straal(6)))
    ok &= check("7 -> 5", snap_straal(7) == 5, str(snap_straal(7)))
    ok &= check("8 -> 10", snap_straal(8) == 10, str(snap_straal(8)))
    ok &= check("3 -> 2", snap_straal(3) == 2, str(snap_straal(3)))
    ok &= check("100 -> 50", snap_straal(100) == 50, str(snap_straal(100)))
    ok &= check("5 blijft 5", snap_straal(5) == 5)

    url = bouw_zoek_url(gebied="2513AA", radius_km=6)
    ok &= check("URL gebruikt gesnapte straal", "2513aa%2C5km" in url, url)
    ok &= check("geen 6km in URL", "6km" not in url)
    return ok


def test_parse() -> bool:
    print("test: kaarten parsen")
    ok = True
    kaarten = parse_kaarten(PAGINA)
    ok &= check("drie kaarten", len(kaarten) == 3, str(len(kaarten)))
    if len(kaarten) != 3:
        return False

    eerste = kaarten[0]
    ok &= check("tiny_id", eerste["tiny_id"] == "44576894", str(eerste["tiny_id"]))
    ok &= check("titel", eerste["title"] == "Jonckbloetplein 30", str(eerste["title"]))
    ok &= check("postcode", eerste["postcode"] == "2523 AS", str(eerste["postcode"]))
    ok &= check("stad", eerste["city"] == "Den Haag", str(eerste["city"]))
    ok &= check("prijs", eerste["price"] == 299000, str(eerste["price"]))
    ok &= check("oppervlakte", eerste["living_area"] == 73, str(eerste["living_area"]))
    ok &= check("huisnummer", eerste["house_number"] == "30", str(eerste["house_number"]))
    ok &= check("nieuw-badge", eerste["is_nieuw_badge"] is True)
    ok &= check("tweede zonder badge", kaarten[1]["is_nieuw_badge"] is False)
    ok &= check("stad uit slug", kaarten[1]["city"] == "Voorburg", str(kaarten[1]["city"]))
    ok &= check("lege pagina geeft niets", parse_kaarten("<html><body>niets</body></html>") == [])
    return ok


def test_zoeker() -> bool:
    print("test: HtmlZoeker als drop-in")
    ok = True
    client = StubClient()
    zoeker = HtmlZoeker(client, overslaan=lambda k: (k.get("city") or "") == "Rijswijk")
    zoeker._haal = lambda url: PAGINA  # netwerk uitschakelen
    zoeker._pauze = 0

    res = zoeker.search_listing(
        location="den-haag", radius_km=5, price_min=230000, price_max=310000,
        object_type=["apartment"], area_min=52, page=0,
    )
    # Overgeslagen kaarten komen wél terug (anders kapt de pagineerlus af),
    # maar zonder detail-call. De stad-filter in funda_zoek.py wijst ze af.
    ok &= check("alle drie teruggegeven", len(res) == 3, str(len(res)))
    ok &= check("geen detail-call voor Rijswijk", not any("rijswijk" in c for c in client.calls))
    ok &= check("twee detail-calls gedaan", len(client.calls) == 2, str(len(client.calls)))
    overgeslagen = [r.data for r in res if r.data.get("_bron") == "html-kaart"]
    ok &= check("overgeslagene gemarkeerd", len(overgeslagen) == 1, str(len(overgeslagen)))
    ok &= check("overgeslagene houdt stad", overgeslagen[0].get("city") == "Rijswijk")
    ok &= check("data heeft .data-vorm", all(hasattr(r, "data") for r in res))

    eerste = res[0].data
    ok &= check("buurt uit detail", eerste.get("neighbourhood") == "Bomenbuurt", str(eerste.get("neighbourhood")))
    ok &= check("prijs uit kaart aangevuld", eerste.get("price") == 299000, str(eerste.get("price")))
    ok &= check("energielabel uit detail", eerste.get("energy_label") == "C")
    ok &= check("bron gemarkeerd", eerste.get("_bron") == "html")

    # get_listing moet uit de cache komen, dus geen extra call.
    voor = len(client.calls)
    zoeker.get_listing(eerste["global_id"])
    ok &= check("get_listing uit cache", len(client.calls) == voor, f"{voor} -> {len(client.calls)}")

    # Mislukte detail-call: woning overslaan in plaats van half gevuld doorlaten.
    client2 = StubClient(faal_op={"44564274"})
    zoeker2 = HtmlZoeker(client2)
    zoeker2._haal = lambda url: PAGINA
    zoeker2._pauze = 0
    res2 = zoeker2.search_listing(location="den-haag", page=0)
    ok &= check("kapotte detail overgeslagen", len(res2) == 2, str(len(res2)))

    # Pagina waarvan alles wordt overgeslagen mag niet leeg terugkomen.
    zoeker3 = HtmlZoeker(StubClient(), overslaan=lambda k: True)
    zoeker3._haal = lambda url: PAGINA
    zoeker3._pauze = 0
    res3 = zoeker3.search_listing(location="den-haag", page=0)
    ok &= check("volledig overgeslagen pagina blijft niet-leeg", len(res3) == 3, str(len(res3)))
    return ok


def test_dedup() -> bool:
    print("test: duplicaten kosten geen tweede detail-call")
    ok = True
    client = StubClient()
    zoeker = HtmlZoeker(client)
    zoeker._haal = lambda url: PAGINA
    zoeker._pauze = 0

    zoeker.search_listing(location="den-haag", page=0)
    na_eerste = len(client.calls)
    ok &= check("eerste ronde doet calls", na_eerste == 3, str(na_eerste))

    # Zelfde pagina nog eens (andere prijsband of sortering): alles uit cache.
    res = zoeker.search_listing(location="den-haag", sort="oldest", page=0)
    ok &= check("tweede ronde zonder extra calls", len(client.calls) == na_eerste,
                f"{na_eerste} -> {len(client.calls)}")
    ok &= check("tweede ronde levert wel resultaten", len(res) == 3, str(len(res)))
    return ok


def test_delegatie() -> bool:
    print("test: onbekende methodes vallen door naar de client")
    ok = True

    class RijkeClient(StubClient):
        def get_price_history(self, ident):
            return [{"prijs": 1}]

        def get_market_insights(self, *a, **k):
            return {"stad": "Den Haag"}

    zoeker = HtmlZoeker(RijkeClient())
    ok &= check("get_price_history bereikbaar", zoeker.get_price_history("x") == [{"prijs": 1}])
    ok &= check("get_market_insights bereikbaar", zoeker.get_market_insights()["stad"] == "Den Haag")
    try:
        zoeker.bestaat_niet_echt()
        ok &= check("onbekende methode geeft AttributeError", False)
    except AttributeError:
        ok &= check("onbekende methode geeft AttributeError", True)
    return ok


def test_botmuur() -> bool:
    print("test: bot-controle wordt herkend")
    zoeker = HtmlZoeker(StubClient())
    zoeker._pauze = 0

    class Resp:
        status_code = 200
        text = "<html>Je bent bijna op de pagina die je zoekt</html>"

    class Sessie:
        def get(self, *a, **k):
            return Resp()

    zoeker._sessie = Sessie()
    try:
        zoeker.search_listing(location="den-haag", page=0)
    except RuntimeError as exc:
        return check("RuntimeError bij bot-muur", "bot-controle" in str(exc), str(exc))
    return check("RuntimeError bij bot-muur", False, "geen exception")


def test_profiel_www() -> bool:
    """HtmlZoeker en SitemapZoeker gebruiken voor www.funda.nl hetzelfde vaste profiel en dezelfde user-agent,
    uit één bron (funda_sitemap_zoek). Een nep-sessie, dus geen netwerk."""
    print("test: één profiel en user-agent voor www.funda.nl")
    import funda_html_zoek
    import funda_sitemap_zoek
    from curl_cffi import requests as curl_requests

    gezien = []

    class Resp:
        status_code = 200
        text = "<html></html>"
        content = b"<urlset></urlset>"
        headers = {}

    class NepSessie:
        def __init__(self, impersonate=None, **_k):
            self.impersonate = impersonate

        def get(self, url, headers=None, **_k):
            gezien.append((self.impersonate, (headers or {}).get("user-agent")))
            return Resp()

    echt = curl_requests.Session
    curl_requests.Session = NepSessie
    try:
        HtmlZoeker(StubClient())._haal("https://www.funda.nl/zoeken/koop")
        funda_sitemap_zoek.SitemapZoeker(StubClient())._haal_http("https://www.funda.nl/sitemap_index.xml/")
    finally:
        curl_requests.Session = echt
    bron = (Path(funda_html_zoek.__file__)).read_text(encoding="utf-8")
    return all([
        check("beide zoekers: zelfde profiel en UA", len(gezien) == 2 and gezien[0] == gezien[1]
              == (funda_sitemap_zoek.IMPERSONATE, funda_sitemap_zoek.UA), str(gezien)),
        check("profiel is safari15_5 met een Safari-UA", funda_sitemap_zoek.IMPERSONATE == "safari15_5"
              and "Safari/" in funda_sitemap_zoek.UA),
        check("funda_html_zoek heeft geen eigen kopie", funda_html_zoek.UA is funda_sitemap_zoek.UA
              and "safari15_5" not in bron and "Version/17.0" not in bron),
    ])


def test_publieke_log() -> bool:
    """Op Actions zonder postcode, prijs- en m2-grenzen in de zoek-URL en zonder detailpad bij een fout."""
    print("test: zoek-URL en detailfout in de publieke log")

    def logregels(actions: bool) -> str:
        regels: list[str] = []
        zoeker = HtmlZoeker(StubClient(faal_op={"44564274"}), log=regels.append)
        zoeker._haal = lambda url: PAGINA
        zoeker._pauze = 0
        oud = os.environ.pop("GITHUB_ACTIONS", None)
        if actions:
            os.environ["GITHUB_ACTIONS"] = "true"
        try:
            zoeker.search_listing(location="1234ab", radius_km=5, price_min=230000, price_max=250000,
                                  area_min=52, page=0)
        finally:
            os.environ.pop("GITHUB_ACTIONS", None)
            if oud is not None:
                os.environ["GITHUB_ACTIONS"] = oud
        return "\n".join(regels)

    publiek, lokaal = logregels(True), logregels(False)
    lekken = [s for s in ("1234ab", "230000", "250000", "52-", "/detail/", "44564274") if s in publiek]
    return all([
        check("Actions: postcode, grenzen en detailpad verborgen", not lekken, ", ".join(lekken)),
        check("Actions: de rest van de zoek-URL blijft", "selected_area=(verborgen)" in publiek
              and "price=(verborgen)" in publiek and "floor_area=(verborgen)" in publiek
              and "availability=" in publiek),
        check("Actions: detailfout zonder woning", "Detail mislukt voor een woning" in publiek),
        check("lokaal: zoek-URL en detailpad volledig", "1234ab" in lokaal and "230000-250000" in lokaal
              and "/detail/" in lokaal),
    ])


def main() -> int:
    resultaten = [test_url(), test_straal(), test_parse(), test_zoeker(), test_dedup(), test_delegatie(), test_botmuur(),
                  test_profiel_www(), test_publieke_log()]
    print()
    if all(resultaten):
        print("Alle tests geslaagd.")
        return 0
    print("ER ZIJN TESTS GEFAALD.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
