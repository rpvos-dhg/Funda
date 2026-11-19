/* Web Push in de PWA: abonnement maken en tonen voor de secret WEB_PUSH_SUBSCRIPTION. Hoort bij het blok
   "Meldingen op deze iPhone" (funda_ui, ids push-*). Heeft dit apparaat al een abonnement, dan gaat dat
   blok dicht. De publieke sleutel staat in <meta name="funda-push-key"> (funda_rapport.push_head). */
(function(){
  var meta = document.querySelector('meta[name="funda-push-key"]');
  var WEB_PUSH_PUBLIC_KEY = meta ? meta.content : '';
  if(!WEB_PUSH_PUBLIC_KEY) return;
  function pushStatus(msg, isError){
    var el = document.getElementById('push-status');
    if(!el) return;
    el.textContent = msg || '';
    el.classList.toggle('is-fout', !!isError);
  }
  function verbergAlsIngesteld(){
    var blok = document.getElementById('meldingen');
    if(!blok || !('serviceWorker' in navigator) || !('PushManager' in window)) return;
    navigator.serviceWorker.ready.then(function(reg){ return reg.pushManager.getSubscription(); })
      .then(function(sub){ if(sub && blok.dataset.net !== '1') blok.hidden = true; })
      .catch(function(){});
  }
  function b64ToUint8Array(base64){
    var padding = '='.repeat((4 - base64.length % 4) % 4);
    var b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(b64);
    var out = new Uint8Array(raw.length);
    for(var i=0;i<raw.length;i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  /* Een fout met een eigen tekst en een vervolgstap. Elke andere fout (van de browser, vaak Engels) krijgt één vaste zin. */
  function MeldFout(tekst){ this.tekst = tekst; }
  async function ensurePushSubscription(){
    if(!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)){
      throw new MeldFout('Deze browser kan geen meldingen sturen. Zet het rapport op je beginscherm en open het daar.');
    }
    var permission = await Notification.requestPermission();
    if(permission !== 'granted') throw new MeldFout('Meldingen staan uit voor dit rapport. Zet ze aan in de instellingen van je apparaat en probeer het opnieuw.');
    var reg = await navigator.serviceWorker.ready;
    var sub = await reg.pushManager.getSubscription();
    if(!sub){
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToUint8Array(WEB_PUSH_PUBLIC_KEY)
      });
    }
    return sub;
  }
  function wirePushSetup(){
    var btn = document.getElementById('push-subscribe-btn');
    var copy = document.getElementById('push-copy-btn');
    var output = document.getElementById('push-subscription-output');
    if(!btn || !output || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    verbergAlsIngesteld();
    btn.addEventListener('click', async function(){
      btn.disabled = true;
      var blok = document.getElementById('meldingen');
      if(blok) blok.dataset.net = '1';
      pushStatus('Meldingen aanzetten…');
      try {
        var sub = await ensurePushSubscription();
        output.value = JSON.stringify(sub.toJSON(), null, 2);
        output.hidden = false;
        if(copy) copy.hidden = false;
        pushStatus('Gelukt. Kopieer dit abonnement en plak het in de instelling WEB_PUSH_SUBSCRIPTION.');
      } catch(err) {
        pushStatus(err instanceof MeldFout ? err.tekst : 'Meldingen aanzetten lukte niet. Controleer je verbinding en probeer het opnieuw.', true);
      } finally {
        btn.disabled = false;
      }
    });
    if(copy){
      copy.addEventListener('click', async function(){
        try {
          await navigator.clipboard.writeText(output.value || '');
          pushStatus('Abonnement gekopieerd.');
        } catch(err) {
          output.focus();
          output.select();
          pushStatus('Kopiëren lukte niet. Kopieer de geselecteerde tekst zelf.', true);
        }
      });
    }
  }
  var previous = window.fundaAfterReportLoad;
  window.fundaAfterReportLoad = function(){
    if(previous) previous();
    wirePushSetup();
  };
  document.addEventListener('DOMContentLoaded', wirePushSetup);
})();
