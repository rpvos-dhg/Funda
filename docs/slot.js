/* Slotscherm van het woningrapport: ontsleutelen in de browser. Publiek leesbaar, geen geheimen.

   Sleutelopbouw (spiegel van funda_rapport.beveilig_html, waarden uit #slot-data):
     hoofdsleutel = PBKDF2-SHA256(wachtwoord, vast app-zout, 600.000 iteraties)
     runsleutel   = HKDF-SHA256(hoofdsleutel, salt = run-zout, info = versiestring) -> AES-256-GCM
     klare tekst  = lengte (4 bytes, big-endian) + gzip(body) + nullen tot de vaste blokmaat
   "Onthoud op dit apparaat" bewaart alleen de hoofdsleutel, als niet-exporteerbare HKDF-sleutel
   (alleen deriveKey) in IndexedDB. Wie die opslag leest, kan er het rapport mee openen, maar het
   wachtwoord raden kost per poging nog steeds de volle 600.000 iteraties. */
(function(){
'use strict';
const P = JSON.parse(document.getElementById("slot-data").textContent);
const DB = "funda_rapport_slot", BAK = "sleutels", ID = "hoofd_v2", DAGEN = 30;
const OUD_ID = "basis";                 // vroeger: de PBKDF2-basissleutel (een afleiding met 1 iteratie was mogelijk)
const OUD_PW = "funda_pw_persist_v1";   // nog vroeger: het wachtwoord leesbaar in localStorage
const TE_OUD = "Deze browser kan het rapport niet openen. Werk je iPhone bij naar iOS 16.4 of nieuwer.";
const IN_FRAME = "Dit rapport opent niet binnen een andere pagina. Open het rechtstreeks.";
const $ = (id) => document.getElementById(id);
function b64(s){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a;}
class TeOud extends Error {}
async function hoofdSleutel(pw){
  const basis = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveBits"]);
  const bits = new Uint8Array(await crypto.subtle.deriveBits(
    {name:"PBKDF2", salt:b64(P.app_zout), iterations:P.iters, hash:"SHA-256"}, basis, 256));
  try { return await crypto.subtle.importKey("raw", bits, "HKDF", false, ["deriveKey"]); }
  finally { bits.fill(0); }
}
async function decrypt(hoofd){
  if(P.gz && typeof DecompressionStream === "undefined") throw new TeOud();
  const key = await crypto.subtle.deriveKey({name:"HKDF", hash:"SHA-256", salt:b64(P.zout), info:new TextEncoder().encode(P.info)},
    hoofd, {name:"AES-GCM", length:256}, false, ["decrypt"]);
  const vol = new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM", iv:b64(P.iv)}, key, b64(P.ct)));  // fout wachtwoord = fout hier
  const n = new DataView(vol.buffer).getUint32(0);   // opvulling eraf: de eerste 4 bytes zijn de lengte
  if(n > vol.length - 4) throw new Error("lengte klopt niet");
  const pt = vol.subarray(4, 4 + n);
  if(!P.gz) return new TextDecoder().decode(pt);
  return await new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
}
function db(modus, werk){
  return new Promise((ok, nee) => {
    if(!window.indexedDB) return nee(new Error("geen IndexedDB"));
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(BAK);
    r.onerror = () => nee(r.error); r.onblocked = () => nee(new Error("geblokkeerd"));
    r.onsuccess = () => {
      const d = r.result; let uit;
      try {
        const tx = d.transaction(BAK, modus), q = werk(tx.objectStore(BAK));
        q.onsuccess = () => { uit = q.result; };
        tx.oncomplete = () => { d.close(); ok(uit); };
        tx.onerror = tx.onabort = () => { d.close(); nee(tx.error || new Error("afgebroken")); };
      } catch(e){ d.close(); nee(e); }   // bijv. DataCloneError: deze browser bewaart geen CryptoKey
    };
  });
}
const bewaar = (sleutel) => db("readwrite", (s) => s.put({sleutel, tot: Date.now() + DAGEN * 864e5}, ID));
const haal = () => db("readonly", (s) => s.get(ID));
const wis = () => db("readwrite", (s) => s.delete(ID));
const wisOud = () => db("readwrite", (s) => s.delete(OUD_ID));
/* Alleen een sleutel van het nieuwe soort telt: HKDF, niet exporteerbaar, alleen deriveKey. */
function geldig(b){
  const k = b && b.sleutel;
  return !!k && Date.now() <= b.tot && k.algorithm && k.algorithm.name === "HKDF" && k.extractable === false
    && k.usages.length === 1 && k.usages[0] === "deriveKey";
}
function onthouden(ja){ window.fundaApparaat.onthouden = ja; $("vergeet").hidden = !ja; }
window.fundaApparaat = {
  onthouden: false,
  vergeet: async () => { await wis(); onthouden(false); },
  /* Vergrendel: de bewaarde sleutel weg en terug naar het slotscherm. Lukt het wissen niet, dan toch herladen. */
  vergrendel: async () => { try { await wis(); } catch(_){} $("content").innerHTML = ""; location.reload(); }
};
/* Pauze na foute pogingen: vanaf de vijfde 30 seconden, daarna telkens het dubbele, hooguit een kwartier.
   Dit remt raden op het slotscherm zelf (iemand met je apparaat in handen). Tegen een aanval op het
   publieke versleutelde bestand helpt het niet: daar beschermt alleen een sterk wachtwoord. */
const POGINGEN = "funda_slot_pogingen", GRATIS = 4, PAUZE_S = 30, PAUZE_MAX_S = 900;
let pogingenGeheugen = {n: 0, tot: 0};   // als localStorage niet werkt
function pogingen(){
  try {
    const p = JSON.parse(localStorage.getItem(POGINGEN) || "null");
    /* Een eindtijd verder weg dan de langste pauze (klok stond voor) wordt daarop teruggezet. */
    if(p && Number.isFinite(p.n) && Number.isFinite(p.tot)) return {n: Math.max(0, p.n), tot: Math.min(p.tot, Date.now() + PAUZE_MAX_S * 1000)};
  } catch(_){}
  return pogingenGeheugen;
}
function zetPogingen(p){
  pogingenGeheugen = p;
  try { if(p.n) localStorage.setItem(POGINGEN, JSON.stringify(p)); else localStorage.removeItem(POGINGEN); } catch(_){}
}
function pauzeSeconden(n){ return n <= GRATIS ? 0 : Math.min(PAUZE_S * Math.pow(2, n - GRATIS - 1), PAUZE_MAX_S); }
function foutePoging(){
  const p = pogingen(), n = p.n + 1;
  zetPogingen({n: n, tot: Date.now() + pauzeSeconden(n) * 1000});
}
function restSeconden(){
  const p = pogingen(), rest = Math.ceil((p.tot - Date.now()) / 1000);
  /* Een klok die is teruggezet mag de pauze niet langer maken dan de langste pauze. */
  return Math.max(0, Math.min(rest, PAUZE_MAX_S));
}
function wachtTekst(s){
  const m = Math.floor(s / 60), r = String(s % 60).padStart(2, "0");
  return "Te veel foute pogingen. Probeer het over " + m + ":" + r + " opnieuw.";
}
/* Zet het formulier op slot tot de pauze om is. Geeft true als er een pauze loopt. */
function pauzeer(){
  clearInterval(pauzeer.t);
  const pw = $("pw"), btn = $("btn"), err = $("err");
  if(restSeconden() <= 0) return false;
  pw.disabled = true; btn.disabled = true; btn.textContent = "Ontgrendel";
  const tik = () => {
    const s = restSeconden();
    if(s > 0){ err.textContent = wachtTekst(s); return; }
    clearInterval(pauzeer.t);
    err.textContent = ""; pw.disabled = false; btn.disabled = false; pw.focus();
  };
  tik(); pauzeer.t = setInterval(tik, 1000);
  return true;
}
function melding(tekst){
  const m = $("slot-melding"); m.textContent = tekst; m.hidden = false;
  clearTimeout(melding.t); melding.t = setTimeout(() => { m.hidden = true; }, 8000);
}
function toon(html){
  const c = $("content"); c.hidden = false; c.innerHTML = html;
  $("slot").hidden = true;
  if(window.fundaAfterReportLoad) window.fundaAfterReportLoad();
}
function opruimen(){
  try { localStorage.removeItem(OUD_PW); } catch(_){}
  try { sessionStorage.removeItem("funda_pw"); } catch(_){}
  return wisOud().catch(() => {});
}
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  window.addEventListener('load', () => navigator.serviceWorker.register('service-worker.js', {scope:'./'}).catch(()=>{}));
}
/* In een frame nooit ontgrendelen: een andere pagina kan er een laag overheen leggen en tikken sturen. */
if(window.top !== window.self){
  $("err").textContent = IN_FRAME;
  ["pw", "pw-toon", "remember", "btn"].forEach((id) => { $(id).disabled = true; });
  $("slot-form").addEventListener("submit", (e) => e.preventDefault());
  return;
}
$("pw-toon").addEventListener("click", function(){
  const pw = $("pw"), zicht = pw.type === "password";
  pw.type = zicht ? "text" : "password";
  this.setAttribute("aria-pressed", String(zicht)); this.setAttribute("aria-label", zicht ? "Verberg wachtwoord" : "Toon wachtwoord");
});
$("vergeet").addEventListener("click", async () => {
  try { await window.fundaApparaat.vergeet(); melding("Dit apparaat is vergeten."); } catch(_){ melding("Vergeten lukte niet. Probeer het opnieuw, of wis de websitegegevens van dit rapport in je browser."); }
});
$("slot-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = $("pw"), btn = $("btn"), err = $("err");
  if(pauzeer()) return;
  if(!pw.value){ err.textContent = "Vul je wachtwoord in."; pw.focus(); return; }   // leeg is geen poging
  err.textContent = ""; pw.removeAttribute("aria-invalid");
  btn.disabled = true; btn.innerHTML = '<span class="draai" aria-hidden="true"></span> Ontgrendel';
  try {
    await new Promise(r => setTimeout(r, 50));
    const hoofd = await hoofdSleutel(pw.value);
    const html = await decrypt(hoofd);
    pw.value = "";
    zetPogingen({n: 0, tot: 0});
    if($("remember").checked){
      try { await bewaar(hoofd); onthouden(true); }
      catch(_){ melding("Onthouden lukt niet in deze browser. Vul je wachtwoord de volgende keer opnieuw in."); }
    }
    toon(html);
  } catch(ex){
    if(ex instanceof TeOud){ err.textContent = TE_OUD; }
    else {
      foutePoging();
      pw.setAttribute("aria-invalid", "true"); err.textContent = "Dit wachtwoord klopt niet. Probeer het opnieuw.";
    }
    btn.disabled = false; btn.textContent = "Ontgrendel";
    if(!pauzeer()) pw.focus();
  }
});
(async () => {
  // Migratie: een oud bewaard wachtwoord en een sleutel van het oude soort gaan weg, ongebruikt.
  // Daarna vul je één keer je wachtwoord in.
  await opruimen();
  pauzeer();   // een lopende pauze overleeft herladen
  let bewaard = null;
  try { bewaard = await haal(); } catch(_){}
  if(!bewaard) return;
  if(!geldig(bewaard)){ try { await wis(); } catch(_){} return; }
  onthouden(true);
  try {
    toon(await decrypt(bewaard.sleutel));
  } catch(ex){
    if(ex instanceof TeOud){ $("err").textContent = TE_OUD; return; }
    try { await wis(); } catch(_){}   // nieuw wachtwoord: de oude sleutel past niet meer
    onthouden(false);
    $("err").textContent = "De onthouden sleutel werkt niet meer. Vul je wachtwoord opnieuw in.";
  }
})();
})();
