// Web Push naar de PWA bij nieuwe woningen. Leest funda_run_summary.json (funda_zoek.py).
//
// Per woning één regel. Met beoordeling (funda_zoek.vul_summary_aan zet status_push en score):
//   "<adres>, <stad> · Past · 8,3"      (poortwoord: Past, Krap, Past niet of Prijs onbekend)
// Zonder beoordeling: "<adres>, <stad> · 68 m2" (of "· prijs op aanvraag · 70 m2").
// Nooit een eurobedrag. De statusregel uit het rapport ("€ 65 onder de norm (bruto)", "€ 26.610
// eigen geld te weinig") geeft met de publieke code het inkomen of het eigen geld prijs, en een
// melding staat leesbaar op het vergrendelscherm. De bedragen staan in het versleutelde rapport.
// Vangnet: elk deel met een €-teken valt weg, ook bij een oude samenvatting met `status`.
//
//   node scripts/send_web_push.cjs                       (in de workflow, met de Web Push-secrets)
//   require("./scripts/send_web_push.cjs").regel(home)   (tests, zonder te versturen)
const fs = require("fs");

const SUMMARY_FILE = "funda_run_summary.json";

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.log(`[push] ${name} ontbreekt, push overgeslagen.`);
    process.exit(0);
  }
  return value;
}

function scoreTekst(value) {
  return Number(value).toFixed(1).replace(".", ",");
}

// Een deel met een €-teken hoort niet in een melding: bedragen staan alleen in het rapport.
function zonderBedragen(delen) {
  return delen.map((d) => String(d == null ? "" : d).trim()).filter((d) => d && !d.includes("€"));
}

function poortwoord(home) {
  // status_push is al alleen het poortwoord. Een oude samenvatting heeft de hele statusregel in
  // `status` ("Past · € 196 onder je grens"): dan alleen het eerste deel.
  if (typeof home.status_push === "string" && home.status_push.trim()) return home.status_push;
  if (typeof home.status === "string" && home.status.trim()) return home.status.split(" · ")[0];
  return "";
}

function regel(home) {
  const kop = `${home.title}${home.city ? `, ${home.city}` : ""}`;
  const woord = poortwoord(home);
  let delen;
  if (woord) {
    const score = typeof home.score === "number" && Number.isFinite(home.score) ? scoreTekst(home.score) : "";
    delen = [kop, ...woord.split(" · "), score];
  } else {
    // Zonder beoordeling: geen vraagprijs, wel "prijs op aanvraag" als die ontbreekt.
    const area = home.living_area ? `${home.living_area} m2` : "? m2";
    delen = [kop, home.price ? "" : "prijs op aanvraag", area];
  }
  return zonderBedragen(delen).join(" · ");
}

function reportUrl() {
  if (process.env.WEB_PUSH_URL) return process.env.WEB_PUSH_URL;
  const repo = process.env.GITHUB_REPOSITORY || "";
  const [owner, name] = repo.split("/");
  if (owner && name) return `https://${owner}.github.io/${name}/`;
  return "https://rpvos-dhg.github.io/Funda/";
}

function payloadVoor(summary) {
  const count = Number(summary.nieuw_count || 0);
  const homes = Array.isArray(summary.nieuw) ? summary.nieuw : [];
  return {
    title: `${count} nieuwe ${count === 1 ? "woning" : "woningen"}`,
    body: homes.slice(0, 3).map(regel).join("\n") || "Open het rapport voor de nieuwste woningen.",
    url: reportUrl(),
    tag: "funda-new-listings",
  };
}

function main() {
  if (!fs.existsSync(SUMMARY_FILE)) {
    console.log(`[push] ${SUMMARY_FILE} niet gevonden, push overgeslagen.`);
    process.exit(0);
  }

  const summary = JSON.parse(fs.readFileSync(SUMMARY_FILE, "utf8"));
  const count = Number(summary.nieuw_count || 0);
  if (count <= 0) {
    console.log("[push] Geen nieuwe woningen, push overgeslagen.");
    process.exit(0);
  }

  const publicKey = required("WEB_PUSH_PUBLIC_KEY");
  const privateKey = required("WEB_PUSH_PRIVATE_KEY");
  const rawSubscription = required("WEB_PUSH_SUBSCRIPTION");
  const subject = process.env.WEB_PUSH_SUBJECT || reportUrl();
  const webpush = require("web-push");

  let parsedSubscription;
  try {
    parsedSubscription = JSON.parse(rawSubscription);
  } catch (error) {
    console.error("[push] WEB_PUSH_SUBSCRIPTION is geen geldige JSON.");
    throw error;
  }

  const subscriptions = Array.isArray(parsedSubscription) ? parsedSubscription : [parsedSubscription];
  const payload = JSON.stringify(payloadVoor(summary));

  webpush.setVapidDetails(subject, publicKey, privateKey);

  (async () => {
    let sent = 0;
    for (const subscription of subscriptions) {
      try {
        await webpush.sendNotification(subscription, payload);
        sent += 1;
      } catch (error) {
        const status = error.statusCode ? ` (${error.statusCode})` : "";
        console.error(`[push] Verzenden mislukt${status}: ${error.body || error.message}`);
        if (error.statusCode === 404 || error.statusCode === 410) {
          console.error("[push] Subscription is verlopen; maak een nieuwe subscription in de PWA.");
        }
        process.exitCode = 1;
      }
    }
    console.log(`[push] Verzonden naar ${sent}/${subscriptions.length} subscription(s).`);
  })();
}

module.exports = { regel, payloadVoor, scoreTekst, zonderBedragen };

if (require.main === module) main();
