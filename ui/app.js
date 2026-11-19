/* Woningrapport: filteren, sorteren, nieuw, bewaren, verbergen, vergelijken, kaart. Geen netwerk, behalve
   de kaarttegels na "Toon kaart". Opslag in localStorage: achter het slotscherm versleuteld, in het
   lokale rapport zonder slotscherm leesbaar. Het slotscherm roept na het ontsleutelen
   window.fundaAfterReportLoad() aan. */
(function(){
'use strict';
var OPSLAG = 'funda_rapport_v1';
var POORT_RANG = {'PAST':0,'KRAP':1,'PAST NIET':2,'PRIJS ONBEKEND':3};
var POORT_CLS = {'PAST':'PAST','KRAP':'KRAP','PAST NIET':'NIET','PRIJS ONBEKEND':'ONBEKEND'};
var POORT_IC = {'PAST':'check','KRAP':'warn','PAST NIET':'x','PRIJS ONBEKEND':'info'};
var STANDAARD = {sort:'aanbevolen', snel:'alles', poort:[], stad:[], maxLasten:'', minM2:'', zonderTwijfel:false, toonVerborgen:false};


/* Opslag op het apparaat. Achter het slotscherm (window.fundaApparaat) staat de staat versleuteld onder
   OPSLAG_VEILIG: AES-256-GCM met de sleutel die ui/slot.js uit de hoofdsleutel afleidt, een verse IV per
   schrijfactie, opgevuld tot een veelvoud van OPSLAG_BLOK tekens. Zonder wachtwoord of onthouden sleutel
   is hij niet te lezen. Een oude leesbare staat (OPSLAG) wordt één keer ingelezen en daarna gewist.
   Het lokale rapport zonder slotscherm heeft geen sleutel en houdt de leesbare opslag. */
var OPSLAG_VEILIG = 'funda_rapport_v2', OPSLAG_BLOK = 512;
var ONLEESBAAR = 'Je bewaarde en verborgen woningen op dit apparaat zijn niet meer te lezen. Bewaar ze opnieuw.';
var GEEN_OPSLAG = 'Opslaan op dit apparaat lukt nu niet. Wat je bewaart of verbergt, geldt tot je het rapport sluit.';
var veilig = false, sleutel = null, schrijfBezig = false, schrijfWacht = false;
function ruw(naam){ try { return localStorage.getItem(naam); } catch(e){ return null; } }
function wisRuw(naam){ try { localStorage.removeItem(naam); } catch(e){} }
function ontleed(tekst){ try { var o = JSON.parse(tekst); return o && typeof o === 'object' && !Array.isArray(o) ? o : null; } catch(e){ return null; } }
function naarB64(a){ var t = ''; for(var i = 0; i < a.length; i++) t += String.fromCharCode(a[i]); return btoa(t); }
function vanB64(t){ var b = atob(t), a = new Uint8Array(b.length); for(var i = 0; i < b.length; i++) a[i] = b.charCodeAt(i); return a; }
function versleutel(tekst){
  while(tekst.length % OPSLAG_BLOK) tekst += ' ';
  var iv = crypto.getRandomValues(new Uint8Array(12));
  return crypto.subtle.encrypt({name:'AES-GCM', iv:iv}, sleutel, new TextEncoder().encode(tekst)).then(function(ct){
    return JSON.stringify({v:1, iv:naarB64(iv), ct:naarB64(new Uint8Array(ct))});
  });
}
function ontsleutel(pak){
  return Promise.resolve().then(function(){
    var p = JSON.parse(pak);
    return crypto.subtle.decrypt({name:'AES-GCM', iv:vanB64(p.iv)}, sleutel, vanB64(p.ct));
  }).then(function(pt){
    var o = ontleed(new TextDecoder().decode(pt));
    if(!o) throw new Error('geen staat');
    return o;
  });
}
/* Eén keer, vóór de app start. Geeft {staat, melding}; faalt nooit. */
function leesOpslag(){
  var a = window.fundaApparaat, kaal = ontleed(ruw(OPSLAG));
  veilig = !!a; sleutel = (a && a.opslagSleutel) || null;
  if(!veilig) return Promise.resolve({staat: kaal || {}});
  if(!sleutel) return Promise.resolve({staat: kaal || {}, melding: GEEN_OPSLAG});
  var pak = ruw(OPSLAG_VEILIG);
  if(pak == null) return Promise.resolve({staat: kaal || {}});   // eerste keer, of migratie: schrijf() wist de leesbare
  return ontsleutel(pak).then(function(staat){ wisRuw(OPSLAG); return {staat: staat}; },
    function(){ return kaal ? {staat: kaal} : {staat: {}, melding: ONLEESBAAR}; });
}
/* Schrijfacties na elkaar, de laatste stand wint: tijdens het versleutelen wacht er hooguit één, en die
   neemt de staat van dat moment. De leesbare versie gaat pas weg als de versleutelde er staat. */
function schrijf(){
  if(!veilig){ try { localStorage.setItem(OPSLAG, JSON.stringify(opslag)); } catch(e){} return; }
  if(!sleutel) return;
  if(schrijfBezig){ schrijfWacht = true; return; }
  schrijfBezig = true;
  versleutel(JSON.stringify(opslag)).then(function(pak){
    try { localStorage.setItem(OPSLAG_VEILIG, pak); localStorage.removeItem(OPSLAG); } catch(e){}
  }, function(){}).then(function(){
    schrijfBezig = false;
    if(schrijfWacht){ schrijfWacht = false; schrijf(); }
  });
}
function $(s, r){ return (r||document).querySelector(s); }
function $$(s, r){ return Array.prototype.slice.call((r||document).querySelectorAll(s)); }
// € met een harde spatie (U+00A0)
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }).replace(/€ /g, '€\u00a0'); }
function eur(n){ return n==null ? '' : '€\u00a0' + Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
// 'Past nu' -> 'past nu', achter 'Financiering:' (funda_ui.scenario_regel)
function finTekst(t){ t = String(t || ''); return t.charAt(0).toLowerCase() + t.slice(1); }

var app, data, opslag, stand, nieuwIds, kaart = null;

/* De staat komt asynchroon (ontsleutelen); tot die er is blijft de app uit beeld, zodat een verborgen
   woning niet even opflitst. */
function init(){
  app = $('#app');
  if(!app || app.dataset.klaar) return;
  app.dataset.klaar = '1';
  try { data = JSON.parse($('#woning-data').textContent); } catch(e){ data = {woningen:[]}; }
  app.hidden = true;
  leesOpslag().then(function(r){
    try { start(r.staat); } finally { app.hidden = false; }
    snelRand();
    if(r.melding) toast(r.melding);
  });
}
function lijst(x){ return Array.isArray(x) ? x : []; }
function start(staat){
  opslag = staat;
  stand = Object.assign({}, STANDAARD, opslag.stand || {});
  stand.poort = lijst(stand.poort); stand.stad = lijst(stand.stad);
  opslag.bewaard = lijst(opslag.bewaard);
  opslag.verborgen = lijst(opslag.verborgen);
  opslag.gezien = lijst(opslag.gezien);
  bepaalNieuw();
  koppel();
  zetFormulier();
  toepassen();
  apparaat();
  kaartVraag();
}

/* Nieuw sinds je vorige bezoek (anders: volgens de run). Gezien na een seconde half in beeld tussen
   de balken (zonder IntersectionObserver nooit). Wat nu niet nieuw is, is meteen bekend. */
var GEZIEN_DEEL = 0.5, GEZIEN_MS = 1000;
function bepaalNieuw(){
  var run = app.dataset.run, sessieSleutel = 'funda_rapport_nieuw_' + run, bron = 'run';
  var ids = data.woningen.map(function(w){ return w.id; });
  var gezien = (opslag.gezien || []).filter(function(id){ return ids.indexOf(id) >= 0; });
  var bewaardInSessie = null;
  try { bewaardInSessie = JSON.parse(sessionStorage.getItem(sessieSleutel)); } catch(e){}
  if(bewaardInSessie){ nieuwIds = bewaardInSessie.ids; bron = bewaardInSessie.bron; }
  else if(opslag.gezien && opslag.gezien.length){
    nieuwIds = ids.filter(function(id){ return gezien.indexOf(id) < 0; }); bron = 'bezoek';
  } else {
    nieuwIds = data.woningen.filter(function(w){ return w.nieuw_run; }).map(function(w){ return w.id; });
  }
  try { sessionStorage.setItem(sessieSleutel, JSON.stringify({ids:nieuwIds, bron:bron})); } catch(e){}
  // Alleen woningen uit deze run bewaren: zo groeit de lijst niet.
  ids.forEach(function(id){ if(nieuwIds.indexOf(id) < 0 && gezien.indexOf(id) < 0) gezien.push(id); });
  opslag.gezien = gezien;
  var kop = $('#nieuw-titel');
  if(kop) kop.textContent = bron === 'bezoek' ? 'Nieuw sinds je vorige bezoek' : 'Nieuw sinds de vorige update';
  var leeg = $('#nieuw-leeg');
  if(leeg && opslag.laatsteBezoek) leeg.textContent = 'Geen nieuwe woningen sinds je vorige bezoek (' + opslag.laatsteBezoek + ').';
  /* Ook meteen bij het openen: versleuteld schrijven is asynchroon, en bij het sluiten is dat niet zeker af. */
  function bezoek(){
    var nu = new Date();
    opslag.laatsteBezoek = nu.toLocaleDateString('nl-NL', {day:'numeric', month:'short'}) + ', ' +
      nu.toLocaleTimeString('nl-NL', {hour:'2-digit', minute:'2-digit'});
    schrijf(opslag);
  }
  bezoek();
  document.addEventListener('visibilitychange', function(){ if(document.visibilityState === 'hidden'){ bezoek(); volgGezien.stop(); } });
  window.addEventListener('pagehide', bezoek);
  volgGezien(nieuwIds.filter(function(id){ return gezien.indexOf(id) < 0; }));
}
function markeerGezien(id){
  if(!opslag.gezien) opslag.gezien = [];
  if(opslag.gezien.indexOf(id) < 0){ opslag.gezien.push(id); schrijf(opslag); }
}
/* In beeld: half de kaart, of bij een kaart hoger dan het scherm half het scherm. */
function volgGezien(teVolgen){
  var klokken = {};
  volgGezien.stop = function(){ for(var id in klokken){ clearTimeout(klokken[id]); } klokken = {}; };
  if(!teVolgen.length || !('IntersectionObserver' in window)) return;
  var drempels = []; for(var i = 0; i <= 20; i++) drempels.push(i / 20);
  var io = new IntersectionObserver(function(regels){
    regels.forEach(function(r){
      var id = r.target.dataset.id;
      var hoog = r.rootBounds ? r.rootBounds.height : window.innerHeight;
      var inBeeld = r.isIntersecting && (r.intersectionRatio >= GEZIEN_DEEL || r.intersectionRect.height >= hoog * GEZIEN_DEEL);
      if(inBeeld && document.visibilityState !== 'hidden'){
        if(!klokken[id]) klokken[id] = setTimeout(function(){
          delete klokken[id]; markeerGezien(id); io.unobserve(r.target);
        }, GEZIEN_MS);
      } else if(klokken[id]){ clearTimeout(klokken[id]); delete klokken[id]; }
    });
  }, {threshold: drempels, rootMargin: balkMarge()});
  $$('.woning').forEach(function(k){ if(teVolgen.indexOf(k.dataset.id) >= 0) io.observe(k); });
}
volgGezien.stop = function(){};
/* Onder de top- en onderbalk is niet in beeld. */
function balkMarge(){
  function hg(sel){ var el = $(sel); return el ? Math.round(el.getBoundingClientRect().height) : 0; }
  return '-' + hg('.app-top') + 'px 0px -' + hg('.app-onder') + 'px 0px';
}

function woningVan(id){ for(var i=0;i<data.woningen.length;i++) if(data.woningen[i].id===id) return data.woningen[i]; return null; }

function past(w){
  var s = stand;
  var verborgen = opslag.verborgen.indexOf(w.id) >= 0;
  if(verborgen && !s.toonVerborgen) return false;
  if(s.snel === 'nieuw' && nieuwIds.indexOf(w.id) < 0) return false;
  if(s.snel === 'past' && w.poort !== 'PAST') return false;
  if(s.snel === 'krap' && w.poort !== 'KRAP') return false;
  if(s.snel === 'gedaald' && !w.gedaald) return false;
  if(s.snel === 'bewaard' && opslag.bewaard.indexOf(w.id) < 0) return false;
  if(s.poort.length && s.poort.indexOf(w.poort) < 0) return false;
  if(s.stad.length && s.stad.indexOf(w.stad) < 0) return false;
  if(s.maxLasten && w.netto != null && w.netto > +s.maxLasten) return false;
  if(s.minM2 && (w.m2 || 0) < +s.minM2) return false;
  if(s.zonderTwijfel && w.twijfel) return false;
  return true;
}

/* Zonder vraagprijs altijd achteraan, bij elke sortering (ook een veiling op PAST NIET). */
function onbekendAchter(f){
  return function(a,b){ return (!(a.prijs>0)-!(b.prijs>0)) || f(a,b); };
}
var SORT = {
  aanbevolen: function(a,b){ return (POORT_RANG[a.poort]-POORT_RANG[b.poort]) || ((a.twijfel?1:0)-(b.twijfel?1:0)) || (b.score-a.score); },
  score: function(a,b){ return b.score-a.score; },
  woonlasten: function(a,b){ return (a.netto==null?1e9:a.netto)-(b.netto==null?1e9:b.netto); },
  prijs: function(a,b){ return (a.prijs||1e9)-(b.prijs||1e9); },
  reis: function(a,b){ return (a.reis_min==null?1e9:a.reis_min)-(b.reis_min==null?1e9:b.reis_min); },
  nieuwst: function(a,b){ return (a.dagen==null?1e9:a.dagen)-(b.dagen==null?1e9:b.dagen); }
};
Object.keys(SORT).forEach(function(k){ SORT[k] = onbekendAchter(SORT[k]); });

function toepassen(){
  var zichtbaar = data.woningen.filter(past).sort(SORT[stand.sort] || SORT.aanbevolen);
  var gegroepeerd = stand.sort === 'aanbevolen';
  var bakken = {nieuw: $('#nieuw .kaarten'), plat: $('#plat .kaarten')};
  $$('.groep').forEach(function(g){ bakken[g.dataset.poort] = $('.kaarten', g); });
  // alle kaarten terug naar #park, dan opnieuw verdelen
  var park = $('#park');
  $$('.woning').forEach(function(k){ park.appendChild(k); });
  var tel = {nieuw:0, plat:0};
  zichtbaar.forEach(function(w){
    var kaartEl = document.getElementById('card-' + w.card_id);
    if(!kaartEl) return;
    var doel = nieuwIds.indexOf(w.id) >= 0 && stand.snel !== 'bewaard' ? 'nieuw' : (gegroepeerd ? w.poort : 'plat');
    tel[doel] = (tel[doel]||0) + 1;
    bakken[doel].appendChild(kaartEl);
    var bw = $('.w-bewaar', kaartEl);
    bw.setAttribute('aria-pressed', opslag.bewaard.indexOf(w.id) >= 0 ? 'true' : 'false');
    var vb = opslag.verborgen.indexOf(w.id) >= 0, vk = $('[data-actie="verberg"]', kaartEl);
    kaartEl.classList.toggle('is-verborgen', vb);
    if(vk){
      vk.setAttribute('aria-label', (vb ? 'Zet terug: ' : 'Verberg ') + w.titel);
      var vl = $('.knop-label', vk); if(vl) vl.textContent = vb ? 'Zet terug' : 'Verberg';
    }
  });
  // nieuw-sectie: blijft staan met een regel als hij leeg is (zonder filters)
  var nieuw = $('#nieuw');
  var filterActief = actieveFilters() > 0 || stand.snel !== 'alles';
  nieuw.hidden = !tel.nieuw && filterActief;
  $('#nieuw .tel').textContent = tel.nieuw ? String(tel.nieuw) : '';
  $('#nieuw-leeg').hidden = !!tel.nieuw;
  $$('.groep').forEach(function(g){
    var n = tel[g.dataset.poort] || 0;
    g.hidden = !gegroepeerd || !n;
    $('.tel', g).textContent = n + (n === 1 ? ' woning' : ' woningen');
    if(filterActief && n) g.open = true;
  });
  $('#plat').hidden = gegroepeerd || !tel.plat;
  $('#eerder').hidden = !gegroepeerd || stand.snel === 'bewaard' || !$$('.groep').some(function(g){ return !g.hidden; });
  $('#leeg').hidden = zichtbaar.length > 0;
  var geenBewaard = stand.snel === 'bewaard' && !opslag.bewaard.length;
  $('#leeg-kop').textContent = geenBewaard ? 'Nog niets bewaard' : 'Geen woningen met deze filters';
  $('#leeg-tekst').textContent = geenBewaard ? 'Tik op de ster bij een woning om hem hier te bewaren. Bewaren blijft op dit apparaat.'
    : 'Zet een filter uit of wis ze allemaal. Verborgen woningen tellen niet mee.';
  // Bewaard telt overal zonder verborgen woningen: chip, balk, de teller op Vergelijk en de vergelijking zelf.
  var nBewaard = bewaardZichtbaar().length;
  $('#bewaard-balk').hidden = !(stand.snel === 'bewaard' && nBewaard);
  $('#bewaard-tekst').textContent = nBewaard < 2 ? 'Bewaar nog een woning om te vergelijken.'
    : nBewaard + ' bewaard. Zet ze naast elkaar:';
  // tellers
  var totaal = data.woningen.filter(function(w){ return opslag.verborgen.indexOf(w.id) < 0; }).length;
  var tt = $('#top-tel'); tt.hidden = !filterActief; tt.textContent = zichtbaar.length + ' van ' + totaal;
  var n = actieveFilters();
  $$('.filter-teller').forEach(function(t){ t.textContent = n; t.hidden = !n; });
  $$('.chip[data-snel]').forEach(function(c){ c.setAttribute('aria-pressed', c.dataset.snel === stand.snel ? 'true' : 'false'); });
  var snelTel = {alles: totaal, nieuw: nieuwIds.filter(function(id){ return opslag.verborgen.indexOf(id) < 0; }).length,
    bewaard: nBewaard};
  ['past','krap','gedaald'].forEach(function(k){
    snelTel[k] = data.woningen.filter(function(w){
      return opslag.verborgen.indexOf(w.id) < 0 && (k==='gedaald' ? w.gedaald : w.poort === k.toUpperCase());
    }).length;
  });
  $$('.chip[data-snel] b').forEach(function(b){ b.textContent = snelTel[b.parentNode.dataset.snel]; });
  var vb = opslag.verborgen.length;
  $('#verborgen-regel').hidden = !vb;
  $('#verborgen-tekst').textContent = vb + (vb === 1 ? ' woning verborgen.' : ' woningen verborgen.');
  $('#toon-verborgen').textContent = stand.toonVerborgen ? 'Verberg ze weer' : 'Toon verborgen woningen';
  var vg = $$('.vergelijk-knop');
  vg.forEach(function(k){ k.disabled = nBewaard < 2; $('.teller', k).textContent = nBewaard; });
  snelRand();
  $('#sheet-toon').textContent = 'Toon ' + zichtbaar.length + (zichtbaar.length === 1 ? ' woning' : ' woningen');
  opslag.stand = stand; schrijf(opslag);
  if(kaart) tekenPins(zichtbaar);
}

function bewaardZichtbaar(){
  return opslag.bewaard.filter(function(id){ return opslag.verborgen.indexOf(id) < 0; });
}
/* Snelfilters: een vervaging aan de kant waar nog chips buiten beeld staan (klassen, geen inline stijl: CSP). */
function snelRand(){
  var s = $('.snel'); if(!s) return;
  var max = s.scrollWidth - s.clientWidth;
  s.classList.toggle('meer-links', s.scrollLeft > 4);
  s.classList.toggle('meer-rechts', max - s.scrollLeft > 4);
}

function actieveFilters(){
  var n = 0;
  if(stand.sort !== 'aanbevolen') n++;
  n += stand.poort.length ? 1 : 0; n += stand.stad.length ? 1 : 0;
  if(stand.maxLasten) n++; if(stand.minM2) n++;
  if(stand.toonVerborgen) n++; if(stand.zonderTwijfel) n++;
  return n;
}

function zetFormulier(){
  var f = $('#filterform'); if(!f) return;
  $$('input[name="sort"]', f).forEach(function(i){ i.checked = i.value === stand.sort; });
  $$('input[name="poort"]', f).forEach(function(i){ i.checked = stand.poort.indexOf(i.value) >= 0; });
  $$('input[name="stad"]', f).forEach(function(i){ i.checked = stand.stad.indexOf(i.value) >= 0; });
  $('#f-maxlasten').value = stand.maxLasten; $('#f-minm2').value = stand.minM2;
  $('#f-verborgen').checked = !!stand.toonVerborgen;
  $('#f-twijfel').checked = !!stand.zonderTwijfel;
}
function leesFormulier(){
  var f = $('#filterform');
  stand.sort = ($('input[name="sort"]:checked', f) || {}).value || 'aanbevolen';
  stand.poort = $$('input[name="poort"]:checked', f).map(function(i){ return i.value; });
  stand.stad = $$('input[name="stad"]:checked', f).map(function(i){ return i.value; });
  stand.maxLasten = $('#f-maxlasten').value; stand.minM2 = $('#f-minm2').value;
  stand.toonVerborgen = $('#f-verborgen').checked;
  stand.zonderTwijfel = $('#f-twijfel').checked;
}

function toast(tekst, ongedaan){
  var t = $('#toast');
  $('#toast-tekst').textContent = tekst;
  var k = $('#toast-knop'); k.hidden = !ongedaan; k.onclick = function(){ ongedaan(); t.hidden = true; };
  var sl = $('#toast-sluit'); if(sl) sl.onclick = function(){ clearTimeout(toast.timer); t.hidden = true; };
  t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(function(){ t.hidden = true; }, 6000);
}

function koppel(){
  app.addEventListener('click', function(e){
    var el = e.target.closest('button, [data-actie]'); if(!el) return;
    var kaartEl = el.closest('.woning'), id = kaartEl ? kaartEl.dataset.id : null;
    if(el.matches('.chip[data-snel]')){ stand.snel = el.dataset.snel; toepassen(); }
    else if(el.matches('.w-bewaar')){
      var i = opslag.bewaard.indexOf(id);
      if(i >= 0) opslag.bewaard.splice(i, 1); else opslag.bewaard.push(id);
      schrijf(opslag); toepassen();
    }
    else if(el.matches('[data-actie="verberg"]') && opslag.verborgen.indexOf(id) >= 0){
      opslag.verborgen.splice(opslag.verborgen.indexOf(id), 1); schrijf(opslag); toepassen();
      toast('Teruggezet: ' + woningVan(id).titel + '.');
    }
    else if(el.matches('[data-actie="verberg"]')){
      var volgende = kaartEl.nextElementSibling;
      opslag.verborgen.push(id); schrijf(opslag); toepassen();
      if(volgende && volgende.matches('.woning')){ var b = $('.w-bewaar', volgende); if(b) b.focus({preventScroll:true}); }
      toast('Verborgen: ' + woningVan(id).titel + '.', function(){
        opslag.verborgen.splice(opslag.verborgen.indexOf(id), 1); schrijf(opslag); toepassen();
      });
    }
    else if(el.matches('[data-actie="filters"]')){ zetFormulier(); $('#filters').showModal(); }
    else if(el.matches('[data-actie="vergelijk"]')){ vulVergelijk(); $('#vergelijk').showModal(); }
    else if(el.matches('[data-actie="sluit"]')){ el.closest('dialog').close(); }
    else if(el.matches('[data-actie="wis"]')){
      var snel = stand.snel; stand = Object.assign({}, STANDAARD); if(el.closest('#leeg')) snel = 'alles';
      stand.snel = snel; zetFormulier(); toepassen();
    }
    else if(el.matches('[data-view]')){ zetView(el.dataset.view); }
    else if(el.matches('[data-actie="toon-kaart"]')){ kiesKaart(); }
    else if(el.matches('#toon-verborgen')){ stand.toonVerborgen = !stand.toonVerborgen; zetFormulier(); toepassen(); }
    else if(el.matches('[data-naar]')){ naarKaart(el.dataset.naar); }
    else if(el.matches('[data-actie="vergeet"]')){ vergeetApparaat(el); }
    else if(el.matches('[data-actie="vergrendel"]')){ vergrendel(el); }
    else if(el.matches('[data-actie="budget"]')){ e.preventDefault(); var b = $('#budget'); b.open = true;
      b.scrollIntoView({block:'center'}); $('summary', b).focus({preventScroll:true}); }
  });
  var f = $('#filterform');
  if(f){
    f.addEventListener('change', function(){ leesFormulier(); toepassen(); });
    f.addEventListener('input', function(){ leesFormulier(); toepassen(); });
    f.addEventListener('submit', function(e){ e.preventDefault(); $('#filters').close(); });
  }
  $$('dialog.sheet').forEach(function(d){
    d.addEventListener('click', function(e){ if(e.target === d) d.close(); });
  });
  var snel = $('.snel');
  if(snel){ snel.addEventListener('scroll', snelRand, {passive:true}); window.addEventListener('resize', snelRand); }
}

/* Het slotscherm zet window.fundaApparaat: vergrendelen, en met een bewaarde sleutel vergeten. */
function apparaat(){
  var a = window.fundaApparaat, aan = !!(a && a.vergrendel), onthoudt = !!(a && a.onthouden);
  [['#apparaat', aan], ['#apparaat-onthoudt', onthoudt], ['[data-actie="vergeet"]', onthoudt]]
    .forEach(function(p){ var el = $(p[0]); if(el) el.hidden = !p[1]; });
}
function vergrendel(knop){
  var a = window.fundaApparaat; if(!a || !a.vergrendel) return;
  try { sessionStorage.removeItem(KAART_GEKOZEN); } catch(e){}
  knop.disabled = true; a.vergrendel();
}
function vergeetApparaat(knop){
  var a = window.fundaApparaat; if(!a || !a.vergeet) return;
  knop.disabled = true;
  Promise.resolve(a.vergeet()).then(function(){
    apparaat(); toast('Dit apparaat is vergeten. Volgende keer vraagt het rapport weer om je wachtwoord.');
  }, function(){
    knop.disabled = false; toast('Vergeten lukte niet. Wis de websitegegevens van dit rapport in je browser.');
  });
}

function zetView(v){
  app.dataset.view = v;
  $$('[data-view]').forEach(function(b){ b.setAttribute('aria-pressed', b.dataset.view === v ? 'true' : 'false'); });
  if(v === 'kaart'){ kiesKaart(); setTimeout(function(){ if(kaart) kaart.invalidateSize(); }, 50); }
  window.scrollTo(0, 0);
}

function naarKaart(cardId){
  if(window.matchMedia('(max-width:63.99rem)').matches) zetView('lijst');
  var el = document.getElementById('card-' + cardId); if(!el) return;
  var groep = el.closest('details.groep'); if(groep) groep.open = true;
  var meer = $('.w-meer', el); if(meer) meer.open = true;
  el.scrollIntoView({block:'start'});
  el.classList.add('is-uitgelicht'); setTimeout(function(){ el.classList.remove('is-uitgelicht'); }, 1800);
}

/* Vergelijken. Zonder scenario's geen rij Financiering; per woning zonder: het poortwoord. */
function vergelijkHtml(ws){
  var sc = ws.some(function(w){ return w.scenario_tekst; });
  var rijen = [
    ['Status', function(w){ return esc(w.status_kort); }],
    sc && ['Financiering', function(w){ return esc(w.scenario_tekst ? finTekst(w.scenario_tekst) : String(w.status_kort||'').split(' · ')[0]); }],
    ['Woonlasten', function(w){ return w.netto==null ? 'onbekend' : eur(w.netto) + ' netto per maand'; }, 'netto', -1],
    ['Vraagprijs', function(w){ return w.prijs ? eur(w.prijs) : 'op aanvraag'; }, 'prijs', -1],
    ['Score', function(w){ return w.score_tekst; }, 'score', 1],
    ['Oppervlak', function(w){ return w.m2 + ' m²'; }, 'm2', 1],
    ['Fietsen naar werk', function(w){ return w.reis_min==null ? 'onbekend' : w.reis_min + ' min'; }, 'reis_min', -1],
    ['Sterkste plus', function(w){ return esc(w.top_plus || 'geen'); }],
    ['Sterkste let op', function(w){ return esc(w.top_let_op || 'geen'); }],
    ['Buurt', function(w){ return esc(w.buurt); }]
  ].filter(Boolean);
  var h = '<thead><tr><th scope="col"><span class="vh">Kenmerk</span></th>' +
    ws.map(function(w){ return '<th scope="col">' + esc(w.titel) + '</th>'; }).join('') + '</tr></thead><tbody>';
  rijen.forEach(function(r){
    var beste = null;
    if(r[2]){
      var vals = ws.map(function(w){ return w[r[2]]; }).filter(function(v){ return v != null; });
      if(vals.length > 1) beste = r[3] > 0 ? Math.max.apply(null, vals) : Math.min.apply(null, vals);
    }
    h += '<tr><th scope="row">' + r[0] + '</th>' + ws.map(function(w){
      var b = beste != null && w[r[2]] === beste;
      return '<td' + (b ? ' class="beste"' : '') + '>' + r[1](w) + '</td>';
    }).join('') + '</tr>';
  });
  return h + '</tbody>';
}

function vulVergelijk(){ $('#vergelijk-tabel').innerHTML = vergelijkHtml(bewaardZichtbaar().map(woningVan).filter(Boolean)); }

/* Kaart: Leaflet, pins naar poort, nieuw als ring. De kaart en de tegels laden pas als je de kaart kiest
   ("Kaart" in de onderbalk, of "Toon kaart" in het vlak op een breed scherm): eerder krijgt de tegelserver
   het zoekgebied niet te zien. De keuze geldt voor deze sessie (sessionStorage) en vervalt bij vergrendelen.
   Het vlak komt uit JavaScript, zodat het er ook staat bij een index.html van vóór deze versie. */
var KAART_GEKOZEN = 'funda_rapport_kaart';
function kaartVraag(){
  var paneel = $('.kaart-paneel'), gekozen = false;
  if(!paneel || $('#kaart-vraag')) return;
  try { gekozen = sessionStorage.getItem(KAART_GEKOZEN) === '1'; } catch(e){}
  if(gekozen && window.matchMedia('(min-width:64rem)').matches){ startKaart(); return; }
  var vlak = document.createElement('div');
  vlak.id = 'kaart-vraag'; vlak.className = 'kaart-vraag';
  vlak.innerHTML = '<p>De kaart haalt tegels op bij OpenStreetMap.</p>' +
    '<button type="button" class="knop knop-sec" data-actie="toon-kaart">Toon kaart</button>';
  paneel.appendChild(vlak); paneel.classList.add('is-wacht');
}
function kiesKaart(){
  try { sessionStorage.setItem(KAART_GEKOZEN, '1'); } catch(e){}
  var vlak = $('#kaart-vraag'), paneel = $('.kaart-paneel');
  if(vlak) vlak.parentNode.removeChild(vlak);
  if(paneel) paneel.classList.remove('is-wacht');
  startKaart();
}
function startKaart(){
  if(kaart) return;
  var doos = $('#kaart'); if(!doos) return;
  if(!window.L){
    $('#kaart-melding').hidden = false;
    var pogingen = 0, t = setInterval(function(){
      if(window.L){ clearInterval(t); $('#kaart-melding').hidden = true; startKaart(); }
      else if(++pogingen > 40){ clearInterval(t); $('#kaart-melding').textContent = 'De kaart laadt niet. Controleer je verbinding en open de kaart opnieuw. De lijst werkt wel.'; }
    }, 150);
    return;
  }
  kaart = L.map(doos, {zoomControl:true, attributionControl:true, tap:false});
  kaart.zoomControl.setPosition('topright');
  // Eén tegelhost (CSP). Alleen hier gaat de kale herkomst mee: OpenStreetMap weigert tegels zonder referrer.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; OpenStreetMap',
    referrerPolicy:'origin'}).addTo(kaart);
  kaart._pins = L.layerGroup().addTo(kaart);
  tekenPins(data.woningen.filter(past), true);
}
function tekenPins(ws, passen){
  if(!kaart) return;
  kaart._pins.clearLayers();
  var punten = [];
  ws.forEach(function(w){
    if(w.lat == null) return;
    var nieuw = nieuwIds.indexOf(w.id) >= 0;
    // Raakvlak om een pil van 32 px; het icoon draagt de poort ook zonder kleur
    var icon = L.divIcon({className:'pin-raak', iconSize:[64,44], iconAnchor:[32,22],
      html:'<span class="pin p-' + POORT_CLS[w.poort] + (nieuw ? ' is-nieuw' : '') + '"><svg class="ic" aria-hidden="true" focusable="false">' +
        '<use href="#i-' + POORT_IC[w.poort] + '"/></svg>' + esc(w.score_tekst) + '</span>'});
    // Beste woning bovenop: poort, dan score
    var m = L.marker([w.lat, w.lon], {icon:icon, title:w.titel + ', ' + w.status_kort + (nieuw ? ', nieuw' : ''), keyboard:true,
      zIndexOffset:(3 - POORT_RANG[w.poort]) * 1000 + Math.round((w.score || 0) * 10)});
    m.bindPopup('<div class="pop"><h3>' + esc(w.titel) + '</h3><p>' + esc(w.status_kort) +
      (w.scenario_tekst ? '<br>Financiering: ' + esc(finTekst(w.scenario_tekst)) : '') + '</p><p>' + esc(w.buurt) +
      (w.reis_tekst ? ' · ' + esc(w.reis_tekst) : '') + '</p><button type="button" class="knop knop-sec" data-naar="' + w.card_id +
      '">Toon in lijst</button></div>', {autoPanPaddingTopLeft:[16,64], autoPanPaddingBottomRight:[16,16]});
    m.addTo(kaart._pins); punten.push([w.lat, w.lon]);
  });
  if(passen !== false && punten.length) kaart.fitBounds(punten, {padding:[40,40], maxZoom:12});
  if(!kaart._popupKlik){
    kaart._popupKlik = true;
    kaart.on('popupopen', function(e){
      var b = e.popup.getElement().querySelector('[data-naar]');
      if(b) b.addEventListener('click', function(){ naarKaart(b.dataset.naar); kaart.closePopup(); });
    });
  }
}

window.fundaRapportInit = init;
// Sorteren zonder DOM (tests)
window.fundaRapportSorteer = function(lijst, sleutel){ return lijst.slice().sort(SORT[sleutel] || SORT.aanbevolen); };
window.fundaRapportVergelijk = vergelijkHtml;
// De opslag zonder DOM (tests): lees de staat, wijzig hem, schrijf
window.fundaRapportOpslag = {lees: function(){ return leesOpslag().then(function(r){ opslag = r.staat; return r; }); },
  schrijf: function(staat){ opslag = staat; schrijf(); }, bezig: function(){ return schrijfBezig; }};
window.fundaAfterReportLoad = init;
window.fundaRapportZetView = function(v){ zetView(v); };
if(document.readyState !== 'loading') init(); else document.addEventListener('DOMContentLoaded', init);
})();
