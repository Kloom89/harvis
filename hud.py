"""HUD de HARVIS: orbe flotante siempre-encima (pywebview/WebView2) que se
expande a panel con historial, timers, selector de cerebro y entrada de
texto. Los comandos tipeados entran por la MISMA cola que la voz."""
import base64
import json
import logging
import os
import threading

log = logging.getLogger("kloom.hud")

_AVATAR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "assets", "harvis.png")
try:
    AVATAR_URI = ("data:image/png;base64,"
                  + base64.b64encode(open(_AVATAR, "rb").read()).decode())
except Exception:
    AVATAR_URI = ""

# --- Banner de apps de KloomStudio (mismo que la versión open source).
_PROMOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "promos")
# (slug, nombre, tagline, CTA, color de acento, url)
_PROMOS_DATA = [
    ("tv-optimizer", "TV Optimizer PRO",
     "Build, test & optimize your TradingView strategy",
     "START FREE", "#2de3c3", "https://app.optimizertrading.workers.dev"),
    ("tucora", "TuCora", "Clarity for your relationships",
     "GET APP", "#ff5f8f", "https://tucora.com.ar"),
    ("ganancia-real", "Ganancia Real",
     "Prices with real profit for your Tiendanube store",
     "SEE MORE", "#3ddc84", "https://www.tiendanube.com/tienda-aplicaciones-nube/ganancia-real"),
    ("digitala", "Digitala", "Digital delivery for your Tiendanube store",
     "SEE MORE", "#4da3ff", "https://kloomstudio.com.ar/en/apps/digitala"),
]


def _promos_json() -> str:
    out = []
    for slug, nombre, tag, cta, color, url in _PROMOS_DATA:
        logo = ""
        try:
            ruta = os.path.join(_PROMOS_DIR, f"{slug}.png")
            logo = ("data:image/png;base64,"
                    + base64.b64encode(open(ruta, "rb").read()).decode())
        except Exception:
            pass
        out.append({"logo": logo, "name": nombre, "tag": tag,
                    "cta": cta, "color": color, "url": url})
    return json.dumps(out)

ORB = (140, 76)      # cápsula: avatar + botón de privacidad
PANEL = (380, 600)
MARGIN = 16


def _pantalla():
    """Área útil del escritorio (sin taskbar) en las MISMAS unidades que
    usa mover ventanas (lógicas, virtualizadas por DPI). webview.screens
    da píxeles FÍSICOS: con escala de Windows >100% el orbe caía medio
    afuera de la pantalla."""
    import ctypes

    class _RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = _RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                  ctypes.byref(r), 0):
        return r.r, r.b
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def _escala():
    """Factor de escala de Windows (125% → 1.25). La ventana se crea en px
    físicos pero WebView2 renderiza el contenido escalado: sin multiplicar,
    el orbe de 96 CSS px necesita 120 físicos y se ve cortado."""
    import ctypes
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
:root {
  --bg: #050b12; --panel: #0a1420; --line: #12283a;
  --cyan: #35d6ff; --cyan-dim: #1a5a75; --amber: #ffb547;
  --green: #3dd68c; --text: #cfe9f5; --muted: #5d7d92;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { background: var(--bg); height: 100%; overflow: hidden;
  font: 13px/1.45 'Segoe UI', system-ui, sans-serif; color: var(--text);
  user-select: none; }

/* ---------- orbe ---------- */
/* El fondo va en el BODY y la forma la da el recorte de la ventana
   (SetWindowRgn). Nada de degradados RADIALES acá: dibujan un óvalo claro
   que se lee como una SEGUNDA cápsula adentro. Solo el ring del borde,
   que sí sigue la misma forma. */
#orb-wrap { position: fixed; inset: 0; display: flex; align-items: center;
  justify-content: center; gap: 8px; }
body:not(.expanded) { background: #0b2134; }
/* Glows CONTENIDOS: un halo ancho dentro de la cápsula se desparrama y
   se lee como una segunda cápsula adentro. */
#orb { width: 58px; height: 58px; border-radius: 50%; position: relative;
  flex: none; cursor: pointer;
  background: url(__AVATAR__) center/cover, #071a28;
  box-shadow: 0 0 6px rgba(53, 214, 255, .3);
  transition: box-shadow .4s ease, filter .4s ease; }
#orb-mute { width: 32px; height: 32px; flex: none; border-radius: 50%;
  border: 1px solid var(--line); background: rgba(4, 16, 26, .75);
  color: #7fb6cf; cursor: pointer; display: flex; align-items: center;
  justify-content: center; transition: color .2s, border-color .2s; }
#orb-mute:hover { color: var(--cyan); border-color: var(--cyan-dim); }
.muted #orb-mute { color: var(--amber); border-color: var(--amber);
  background: #241505; }
#orb-mute .tachado { display: none; }
.muted #orb-mute .tachado { display: block; }
#orb::before { content: ''; position: absolute; inset: -4px;
  border-radius: 50%; border: 2px solid transparent;
  transition: border-color .3s ease; }

.idle #orb { animation: breathg 3.2s ease-in-out infinite; }
@keyframes breathg {
  50% { box-shadow: 0 0 4px rgba(53, 214, 255, .12); } }

.armed #orb { box-shadow: 0 0 14px 2px rgba(53, 214, 255, .6); }
.armed #orb::before { border-color: var(--cyan);
  animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 50% { transform: scale(1.1); opacity: .4; } }

.thinking #orb { box-shadow: 0 0 14px 2px rgba(255, 181, 71, .55); }
.thinking #orb::before { border-color: var(--amber);
  border-top-color: transparent; border-right-color: transparent;
  animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.speaking #orb { animation: talkg .5s ease-in-out infinite; }
@keyframes talkg {
  50% { box-shadow: 0 0 16px 3px rgba(53, 214, 255, .8); } }

.chat #orb { box-shadow: 0 0 14px 2px rgba(61, 214, 140, .6); }
.chat #orb::before { border-color: var(--green);
  animation: pulse 2s ease-in-out infinite; }

.muted #orb { box-shadow: 0 0 6px rgba(255, 181, 71, .25);
  filter: grayscale(1) brightness(.55); }
.muted #orb::before { border-color: #57320f; }
body.expanded.muted #mini-orb {
  filter: grayscale(1) brightness(.55); box-shadow: none; }
#promo { --pa: #35d6ff; position: relative; display: flex;
  align-items: center; gap: 9px; cursor: pointer; margin: 6px 12px 0;
  padding: 7px 10px; border-radius: 11px; overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--pa) 35%, #143047);
  background:
    radial-gradient(130% 200% at 100% 50%,
      color-mix(in srgb, var(--pa) 20%, transparent), transparent 55%),
    radial-gradient(90% 160% at 0% 50%,
      color-mix(in srgb, var(--pa) 10%, transparent), transparent 50%),
    linear-gradient(90deg, #071320, #0a1d2e);
  transition: box-shadow .3s ease, border-color .3s ease; }
#promo::after { content: ''; position: absolute; inset: 0;
  background: linear-gradient(115deg, transparent 30%,
    rgba(255, 255, 255, .05) 45%, transparent 60%); pointer-events: none; }
#promo:hover { border-color: color-mix(in srgb, var(--pa) 70%, #143047);
  box-shadow: 0 0 14px color-mix(in srgb, var(--pa) 30%, transparent); }
#promo-logo { width: 27px; height: 27px; border-radius: 7px; flex: none;
  box-shadow: 0 0 8px color-mix(in srgb, var(--pa) 40%, transparent); }
#promo-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; }
#promo-name { font-size: 11px; color: #f2faff; letter-spacing: .3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#promo-tag { font-size: 10px; color: #9db8ca; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
#promo-cta { flex: none; font-size: 9px; font-weight: 700;
  letter-spacing: 1.2px; color: var(--pa); padding: 4px 11px;
  border: 1px solid color-mix(in srgb, var(--pa) 65%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--pa) 10%, transparent);
  text-shadow: 0 0 8px color-mix(in srgb, var(--pa) 60%, transparent); }
#promo:hover #promo-cta {
  background: color-mix(in srgb, var(--pa) 22%, transparent); }
#mic-btn, #new-btn, #stop-btn {
  background: linear-gradient(180deg, #0b2334, #081a29);
  border: 1px solid var(--line); border-radius: 10px; cursor: pointer;
  width: 38px; flex: none; display: flex; align-items: center;
  justify-content: center; color: #7fb6cf;
  transition: color .2s, border-color .2s, box-shadow .2s; }
#mic-btn:hover, #new-btn:hover, #stop-btn:hover { color: var(--cyan);
  border-color: var(--cyan-dim);
  box-shadow: 0 0 10px rgba(53, 214, 255, .25); }
.ic { width: 16px; height: 16px; fill: none; stroke: currentColor;
  stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
#stop-btn .ic { fill: currentColor; stroke: none; }
.muted #mic-btn { border-color: var(--amber); background: #241505;
  color: var(--amber); }

/* ---------- panel ---------- */
#panel { display: none; height: 100%; flex-direction: column;
  background: var(--bg); border: 1px solid var(--line);
  border-radius: 14px; overflow: hidden; }
body.expanded #orb-wrap { display: none; }
body.expanded #panel { display: flex; }

header { display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, #081524, var(--bg)); cursor: move; }
#mini-orb { width: 30px; height: 30px; border-radius: 50%; flex: none;
  background: url(__AVATAR__) center/cover, #0a2a3d;
  box-shadow: 0 0 10px rgba(53, 214, 255, .7); cursor: pointer; }
body.expanded.thinking #mini-orb {
  box-shadow: 0 0 10px rgba(255, 181, 71, .8); }
body.expanded.chat #mini-orb {
  box-shadow: 0 0 10px rgba(61, 214, 140, .8); }
h1 { font-size: 15px; letter-spacing: 4px; font-weight: 600;
  color: var(--cyan); flex: 1; display: flex; flex-direction: column;
  gap: 2px; min-width: 0; }
h1 { cursor: pointer; }
h1:hover #marca { text-decoration: underline; }
#marca { font-size: 10px; letter-spacing: 1.2px; color: #7de4ff;
  font-weight: 700; white-space: nowrap;
  text-shadow: 0 0 8px rgba(53, 214, 255, .55); }
#skills-btn { font-size: 11px; letter-spacing: 1px; color: var(--muted);
  border: 1px solid var(--line); border-radius: 20px; padding: 3px 10px;
  background: none; cursor: pointer; }
#skills-btn:hover, body.skills #skills-btn { color: var(--cyan);
  border-color: var(--cyan-dim); }

/* ---------- vista skills ---------- */
#skills-view { display: none; flex: 1; overflow-y: auto; padding: 10px 14px;
  font-size: 12px; }
body.skills #skills-view { display: block; }
body.skills #log, body.skills #timers, body.skills #brains,
body.skills #entrada { display: none !important; }
#skills-view h2 { font-size: 11px; letter-spacing: 2px; color: var(--cyan);
  text-transform: uppercase; margin: 14px 0 6px; }
#skills-view label { display: block; color: var(--muted); margin: 8px 0 3px; }
#skills-view input, #skills-view textarea { width: 100%;
  background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  color: var(--text); padding: 6px 9px; font-size: 12px; outline: none;
  font-family: inherit; resize: vertical; }
#skills-view input:focus, #skills-view textarea:focus {
  border-color: var(--cyan-dim); }
.sk-item { border: 1px solid var(--line); border-radius: 10px;
  padding: 8px 10px; margin: 6px 0; }
.sk-item b { color: var(--text); }
.sk-item .t { color: var(--muted); font-size: 11px; }
#sk-save { margin-top: 12px; width: 100%; padding: 9px 0;
  background: linear-gradient(135deg, #1691bd, #35d6ff); color: #04222e;
  border: 0; border-radius: 10px; font-weight: 600; cursor: pointer; }
#sk-status { color: var(--green); padding: 6px 0; min-height: 18px; }
.sk-accion { margin-top: 8px; width: 100%; padding: 8px 0;
  background: none; border: 1px dashed var(--cyan-dim); color: var(--cyan);
  border-radius: 10px; cursor: pointer; font-size: 12px; }
.sk-accion:hover { border-style: solid; }
.sk-salir { border: 1px solid var(--line); color: var(--muted); }
.ayuda { display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%; margin-left: 6px;
  border: 1px solid var(--cyan-dim); color: var(--cyan); font-size: 10px;
  cursor: help; position: relative; vertical-align: middle;
  letter-spacing: 0; text-transform: none; }
.ayuda:hover::after { content: attr(data-tip); position: absolute;
  left: 0; top: 20px; width: 240px; z-index: 10; white-space: normal;
  background: var(--panel); border: 1px solid var(--cyan-dim);
  border-radius: 10px; padding: 9px 11px; color: var(--text);
  font-size: 11px; line-height: 1.5; font-weight: 400;
  box-shadow: 0 6px 18px rgba(0, 0, 0, .6); }
#estado-line { font-size: 11px; color: var(--muted); padding: 6px 14px 0; }

#log { flex: 1; overflow-y: auto; padding: 10px 14px;
  display: flex; flex-direction: column; gap: 8px; }
#log::-webkit-scrollbar { width: 4px; }
#log::-webkit-scrollbar-thumb { background: var(--line); }
.msg { max-width: 88%; padding: 7px 11px; border-radius: 10px;
  white-space: pre-wrap; user-select: text; }
.yo { align-self: flex-end; background: #0d2f42;
  border: 1px solid #14455f; border-bottom-right-radius: 3px; }
.harvis { align-self: flex-start; background: var(--panel);
  border: 1px solid var(--line); border-bottom-left-radius: 3px; }
.harvis.aviso { border-color: #3d2f14; color: var(--amber); }

#timers { padding: 6px 14px; border-top: 1px solid var(--line);
  display: none; }
#timers.on { display: block; }
#timers .t { font-size: 12px; color: var(--amber); padding: 2px 0; }
#timers .t::before { content: '◔ '; }

#brains { display: flex; align-items: center; gap: 8px;
  padding: 8px 14px 0; }
#brains-label { font-size: 10px; letter-spacing: 2px; color: var(--muted);
  text-transform: uppercase; }
#brain-sel { flex: none; background: var(--panel); color: var(--cyan);
  border: 1px solid var(--line); border-radius: 8px; padding: 4px 8px;
  font-size: 11px; letter-spacing: .5px; cursor: pointer; outline: none;
  text-transform: capitalize; }
#brain-sel:hover { border-color: var(--cyan-dim); }
#brain-sel option { background: #0a1d2e; color: var(--text); }

#entrada { display: flex; gap: 8px; padding: 10px 14px 14px; }
#entrada input { flex: 1; min-width: 0; background: var(--panel);
  border: 1px solid var(--line); border-radius: 10px; color: var(--text);
  padding: 9px 12px; font-size: 13px; outline: none; }
#entrada input:focus { border-color: var(--cyan-dim); }
#send-btn { background: linear-gradient(135deg, #1691bd, #35d6ff);
  color: #04222e; border: 0; border-radius: 10px; width: 42px; flex: none;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; }
#send-btn:hover { box-shadow: 0 0 12px rgba(53, 214, 255, .45); }
</style></head><body class="idle">

<div id="orb-wrap">
  <div id="orb" title="Abrir panel" onclick="pywebview.api.toggle()"></div>
  <button id="orb-mute" title="Privacidad: apagar/prender el micrófono"
          onclick="pywebview.api.toggle_mic()"><svg class="ic"
    viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="12" rx="3"/>
    <path d="M18.5 11.5a6.5 6.5 0 0 1-13 0"/>
    <line x1="12" y1="18" x2="12" y2="21"/>
    <line class="tachado" x1="4" y1="20" x2="20" y2="4"/></svg></button>
</div>

<div id="panel">
  <header>
    <div id="mini-orb" onclick="pywebview.api.toggle()" title="Achicar"></div>
    <h1 onclick="pywebview.api.abrir_web()" title="KloomStudio.com.ar"><span id="app-name">HARVIS</span><span id="marca">by KloomStudio.com.ar</span></h1>
    <button id="skills-btn" onclick="toggleSkills()">SKILLS</button>
  </header>
  <div id="estado-line">esperando «Harvis…»</div>
  <div id="skills-view"></div>
  <div id="log"></div>
  <div id="timers"></div>
  <div id="brains"></div>
  <div id="promo" title="Apps de KloomStudio"
       onclick="pywebview.api.abrir_url(this.dataset.url)">
    <img id="promo-logo" alt="">
    <div id="promo-txt">
      <b id="promo-name"></b>
      <span id="promo-tag"></span>
    </div>
    <span id="promo-cta"></span>
  </div>
  <div id="entrada">
    <button id="mic-btn" title="Micrófono on/off"
            onclick="pywebview.api.toggle_mic()"><svg class="ic"
      viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="12" rx="3"/>
      <path d="M18.5 11.5a6.5 6.5 0 0 1-13 0"/>
      <line x1="12" y1="18" x2="12" y2="21"/></svg></button>
    <button id="new-btn" title="Conversación nueva (borra el hilo actual)"
            onclick="pywebview.api.nueva_conversacion()"><svg class="ic"
      viewBox="0 0 24 24"><path d="M20.5 12a8.5 8.5 0 1 1-2.5-6l2.5 2.4"/>
      <polyline points="20.7 3.3 20.7 8.6 15.4 8.6"/></svg></button>
    <button id="stop-btn" title="Cortala (F9): calla la voz y aborta el turno"
            onclick="pywebview.api.abortar()"><svg class="ic"
      viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11"
      rx="2.5"/></svg></button>
    <input id="cmd" placeholder="Escribile a Harvis…"
           onkeydown="if(event.key==='Enter')enviar()">
    <button id="send-btn" title="Enviar" onclick="enviar()"><svg class="ic"
      viewBox="0 0 24 24"><path d="M21 3 10.5 13.5"/>
      <path d="M21 3l-6.5 18-3.5-8-8-3.5z"/></svg></button>
  </div>
</div>

<script>
let NOMBRE = 'Harvis';
const ESTADOS = {
  idle: () => `esperando «${NOMBRE}…»`, armed: () => 'te escucho — seguí hablando',
  thinking: () => 'pensando…', speaking: () => 'hablando',
  chat: () => 'modo charla — decí «listo» para cortar',
  muted: () => 'micrófono APAGADO — tocá 🎤 para prender',
};
let ESTADO_ACTUAL = 'idle';
let BRAIN_ACTUAL = '';
const hud = {
  state(s) {
    const b = document.body;
    ['idle', 'armed', 'thinking', 'speaking', 'chat', 'muted'].forEach(c =>
      b.classList.remove(c));
    b.classList.add(s);
    ESTADO_ACTUAL = s;
    document.getElementById('estado-line').textContent =
      ESTADOS[s] ? ESTADOS[s]() : s;
  },
  rename(n) {
    NOMBRE = n;
    document.getElementById('app-name').textContent = n.toUpperCase();
    document.getElementById('cmd').placeholder = `Escribile a ${n}…`;
    if (ESTADOS[ESTADO_ACTUAL])
      document.getElementById('estado-line').textContent =
        ESTADOS[ESTADO_ACTUAL]();
  },
  clear() { document.getElementById('log').innerHTML = ''; window._stream = null; },
  replyChunk(t) {
    if (!window._stream) {
      const log = document.getElementById('log');
      window._stream = document.createElement('div');
      window._stream.className = 'msg harvis';
      log.appendChild(window._stream);
      while (log.children.length > 60) log.removeChild(log.firstChild);
    }
    window._stream.textContent +=
      (window._stream.textContent ? ' ' : '') + t;
  },
  replyEnd() { window._stream = null; },
  heard(t) { addMsg('yo', t); },
  reply(t) { addMsg('harvis', t); },
  aviso(t) { addMsg('harvis aviso', t); },
  brain(b) {
    BRAIN_ACTUAL = b;
    const s = document.getElementById('brain-sel');
    if (s) s.value = b;
  },
  brains(list) {
    const c = document.getElementById('brains');
    c.innerHTML = '<span id="brains-label">Brain:</span>';
    const s = document.createElement('select');
    s.id = 'brain-sel';
    list.forEach(b => { const o = document.createElement('option');
      o.value = b; o.textContent = b; s.appendChild(o); });
    s.onchange = () => pywebview.api.switch_brain(s.value);
    c.appendChild(s);
    s.value = BRAIN_ACTUAL || list[0];
  },
  expanded(on) { document.body.classList.toggle('expanded', on); },
  timers(list) {
    const c = document.getElementById('timers');
    c.classList.toggle('on', list.length > 0);
    c.innerHTML = list.map(t => `<div class="t">${t}</div>`).join('');
  },
};
function addMsg(cls, t) {
  const log = document.getElementById('log');
  const el = document.createElement('div');
  el.className = 'msg ' + cls; el.textContent = t;
  log.appendChild(el);
  while (log.children.length > 60) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}
function enviar() {
  const i = document.getElementById('cmd');
  if (!i.value.trim()) return;
  pywebview.api.send_text(i.value.trim()); i.value = '';
}
// Banner de apps de KloomStudio — rota cada 15 s.
const PROMOS = __PROMOS__;
let PROMO_I = Math.floor(Math.random() * PROMOS.length);
function rotarPromo() {
  const el = document.getElementById('promo');
  if (!el || !PROMOS.length) return;
  const p = PROMOS[PROMO_I++ % PROMOS.length];
  document.getElementById('promo-logo').src = p.logo;
  document.getElementById('promo-name').textContent = p.name;
  document.getElementById('promo-tag').textContent = p.tag;
  document.getElementById('promo-cta').textContent = p.cta;
  el.style.setProperty('--pa', p.color || '#35d6ff');
  el.dataset.url = p.url;
}
setInterval(rotarPromo, 15000);
rotarPromo();
const GRUPOS = {
  charla: 'Modo charla (todo va al cerebro, sin wake word)',
  redactor: 'Modo redactor (anota todo lo dictado)',
  coach: 'Modo coach (coach ontológico confrontativo)',
  privacidad: 'Modo privacidad (apaga el micrófono)',
  salir: 'Salir de un modo (charla/redactor)',
  reiniciar: 'Conversación nueva (borra el hilo actual)',
};
async function toggleSkills() {
  const b = document.body;
  b.classList.toggle('skills');
  if (!b.classList.contains('skills')) return;
  const d = await pywebview.api.get_skills_data();
  const v = document.getElementById('skills-view');
  const TIP_WAKE = 'El wake word es el nombre que despierta al asistente: ' +
    'lo decís y lo que sigue es el comando (al principio o al final de la ' +
    'frase). Acá podés cambiarlo — en cualquier idioma — y sumar variantes ' +
    'que el reconocedor de voz suele escribir mal (harvey, harry...). ' +
    'Cambiar el nombre renombra la app entera.';
  let h = `<h2>Wake word <span class="ayuda" data-tip="${TIP_WAKE}">?</span></h2>` +
    '<label>Nombre para llamarlo (ej: harvis, jarvis, hoover)</label>' +
    `<input id="sk-word" value="${d.wake.word || ''}">` +
    '<label>Variantes aceptadas (separadas por coma)</label>' +
    `<input id="sk-aliases" value="${(d.wake.aliases || []).join(', ')}">` +
    '<h2>Comandos de voz</h2>';
  for (const [k, titulo] of Object.entries(GRUPOS)) {
    h += `<label>${titulo}</label>` +
      `<textarea id="sk-${k}" rows="2">${(d.comandos[k] || []).join(', ')}</textarea>`;
  }
  h += '<button id="sk-save" onclick="guardarSkills()">Guardar y aplicar</button>' +
    '<div id="sk-status"></div><h2>Skills instaladas</h2>';
  for (const s of (d.skills || [])) {
    h += `<div class="sk-item"><b>${s.nombre}</b><br>` +
      `<span class="t">${s.desc}</span><br>` +
      `<span class="t">tools: ${s.tools.join(', ')}</span></div>`;
  }
  h += '<button class="sk-accion" onclick="instalarSkill()">＋ Instalar skill…</button>' +
    '<div class="t" style="color:var(--muted);padding:6px 0">Una skill es ' +
    'un archivo .py con sus TOOLS (mirá los de la carpeta skills/ como ' +
    'ejemplo). Al instalarla se carga al instante.</div>' +
    '<button class="sk-accion sk-salir" onclick="toggleSkills()">← Salir</button>';
  v.innerHTML = h;
}
async function instalarSkill() {
  document.getElementById('sk-status').textContent = 'Eligiendo archivo…';
  const r = await pywebview.api.instalar_skill();
  document.getElementById('sk-status').textContent = r;
  if (r.startsWith('Skill')) setTimeout(async () => {
    if (document.body.classList.contains('skills')) {
      document.body.classList.remove('skills');
      toggleSkills();          // re-render con la lista fresca
    }
  }, 3000);
}
async function guardarSkills() {
  const lista = id => document.getElementById(id).value
    .split(',').map(x => x.trim()).filter(Boolean);
  const payload = {
    wake: { word: document.getElementById('sk-word').value.trim(),
            aliases: lista('sk-aliases') },
    comandos: {},
  };
  for (const k of Object.keys(GRUPOS)) payload.comandos[k] = lista('sk-' + k);
  const r = await pywebview.api.save_comandos(JSON.stringify(payload));
  document.getElementById('sk-status').textContent = r;
}
setInterval(() => {
  if (document.body.classList.contains('expanded'))
    pywebview.api.get_timers().then(hud.timers);
}, 1000);
</script></body></html>"""


class Hud:
    def __init__(self, cfg: dict, loop, text_sink, brains: list[str],
                 mic_sink=lambda: None, skills_data=lambda: {},
                 save_fn=lambda p: "sin backend", reload_sink=lambda: None,
                 reset_sink=lambda: None, abort_sink=lambda: None,
                 skills_dir=""):
        """text_sink(str): comandos tipeados; mic_sink(): toggle del mic;
        skills_data(): dict para la vista Skills; save_fn(dict): persiste
        comandos; reload_sink(): recarga skills tras instalar (todos llegan
        desde el thread del webview)."""
        self.loop = loop
        self.text_sink = text_sink
        self.mic_sink = mic_sink
        self.skills_data = skills_data
        self.save_fn = save_fn
        self.reload_sink = reload_sink
        self.reset_sink = reset_sink
        self.abort_sink = abort_sink
        self.skills_dir = skills_dir
        self.brains = brains
        self.window = None
        self.expanded = False
        self._ready = threading.Event()
        self._pending: list[str] = []

    # ---------- API expuesta a JS (corre en thread del webview) ----------
    def _ajustar_posicion(self):
        """pywebview crea la ventana MÁS GRANDE que lo pedido (~17 px de
        chrome invisible) y el orbe quedaba cortado por el borde de la
        pantalla: se mide el rect real y se reposiciona exacto."""
        import ctypes
        try:
            u = ctypes.windll.user32
            hwnd = u.FindWindowW(None, "HARVIS")
            if not hwnd:
                return

            class _R(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]
            r = _R()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.r - r.l, r.b - r.t
            ancho, alto = _pantalla()
            u.SetWindowPos(hwnd, 0, ancho - w - MARGIN, alto - h - MARGIN,
                           0, 0, 0x0001 | 0x0004)  # NOSIZE | NOZORDER
        except Exception:
            log.debug("ajuste de posición falló", exc_info=True)

    def _hwnd(self):
        import ctypes
        return ctypes.windll.user32.FindWindowW(None, "HARVIS")

    # NOTA: nada de SetWindowRgn acá — en Win11 DWM IGNORA la región al
    # renderizar (solo la respeta para el hit-test), así que el "recorte"
    # dejaba una placa gris fantasma detrás. La cápsula es la ventana
    # entera con fondo parejo y las esquinas redondeadas nativas.

    def toggle(self):
        self.expanded = not self.expanded
        esc = _escala()
        w, h = [int(v * esc) for v in (PANEL if self.expanded else ORB)]
        ancho, alto = _pantalla()
        self.window.resize(w, h)
        self.window.move(ancho - w - MARGIN, alto - h - MARGIN)

        threading.Timer(0.2, self._ajustar_posicion).start()
        self._js(f"hud.expanded({json.dumps(self.expanded)})")

    def send_text(self, text: str):
        self.loop.call_soon_threadsafe(self.text_sink, text)

    def toggle_mic(self):
        self.loop.call_soon_threadsafe(self.mic_sink)

    def nueva_conversacion(self):
        self.loop.call_soon_threadsafe(self.reset_sink)

    def abortar(self):
        self.loop.call_soon_threadsafe(self.abort_sink)

    def abrir_web(self):
        import webbrowser
        webbrowser.open("https://kloomstudio.com.ar")
        return "ok"

    def abrir_url(self, url: str):
        """Banner de apps: solo https, nada raro."""
        import webbrowser
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)
        return "ok"

    def get_skills_data(self):
        try:
            return self.skills_data()
        except Exception as e:
            return {"error": str(e)}

    def save_comandos(self, payload: str):
        try:
            return self.save_fn(json.loads(payload))
        except Exception as e:
            log.exception("save_comandos")
            return f"Error: {e}"

    def instalar_skill(self):
        """Elige un .py, lo valida (tiene que importar y traer TOOLS o
        PROMPT), lo copia a skills/ y dispara la recarga en vivo."""
        import importlib.util
        import shutil

        import webview
        try:
            rutas = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("Skill de HARVIS (*.py)", "Todos (*.*)"))
            if not rutas:
                return "Cancelado."
            src = rutas[0]
            spec = importlib.util.spec_from_file_location("candidata", src)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                return f"La skill no carga: {e}"
            if not getattr(mod, "TOOLS", None) and \
                    not getattr(mod, "PROMPT", ""):
                return "Ese archivo no es una skill (sin TOOLS ni PROMPT)."
            destino = os.path.join(self.skills_dir, os.path.basename(src))
            existia = os.path.exists(destino)
            os.makedirs(self.skills_dir, exist_ok=True)
            shutil.copy2(src, destino)
            self.loop.call_soon_threadsafe(self.reload_sink)
            verbo = "actualizada" if existia else "instalada"
            return (f"Skill {verbo}: {os.path.basename(src)} — "
                    "recargando en vivo...")
        except Exception as e:
            log.exception("instalar_skill")
            return f"Error instalando: {e}"

    def switch_brain(self, brain: str):
        self.loop.call_soon_threadsafe(self.text_sink,
                                       f"cambiá el cerebro a {brain}")

    def get_timers(self):
        from tools.timers import PENDIENTES
        out = []
        for p in PENDIENTES.values():
            et = f" — {p['etiqueta']}" if p["etiqueta"] else ""
            out.append(f"{p['kind']} {p['due'].strftime('%H:%M')}{et}")
        return out

    # ---------- eventos desde kloom.py (thread asyncio) ----------
    def _js(self, code: str):
        if not self._ready.is_set():
            self._pending.append(code)
            return
        try:
            self.window.evaluate_js(code)
        except Exception:
            log.debug("HUD js falló", exc_info=True)

    def set_state(self, s: str):
        self._js(f"hud.state({json.dumps(s)})")

    def clear_chat(self):
        self._js("hud.clear()")

    def heard(self, t: str):
        self._js(f"hud.heard({json.dumps(t)})")

    def reply(self, t: str):
        self._js(f"hud.reply({json.dumps(t)})")

    def reply_chunk(self, t: str):
        self._js(f"hud.replyChunk({json.dumps(t)})")

    def reply_end(self):
        self._js("hud.replyEnd()")

    def aviso(self, t: str):
        self._js(f"hud.aviso({json.dumps(t)})")

    def set_brain(self, b: str):
        self._js(f"hud.brain({json.dumps(b)})")

    def set_name(self, nombre: str):
        """Renombra al asistente en todo el HUD + título de la ventana
        (barra de tareas)."""
        self._js(f"hud.rename({json.dumps(nombre)})")
        try:
            if self.window:
                self.window.set_title(nombre.upper())
        except Exception:
            log.debug("set_title falló", exc_info=True)

    # ---------- arranque ----------
    def start(self):
        """Registra el HUD para que serve_main_thread() (thread principal,
        pywebview no acepta otro) lo levante."""
        global _INSTANCE
        _INSTANCE = self
        _REGISTERED.set()

    def _set_taskbar_icon(self):
        """El ícono de la barra sale del python.exe; se pisa con WM_SETICON
        + un AppUserModelID propio para que agrupe como app HARVIS."""
        import ctypes
        try:
            ico = _AVATAR.replace("harvis.png", "harvis.ico")
            hwnd = ctypes.windll.user32.FindWindowW(None, "HARVIS")
            if not hwnd or not os.path.exists(ico):
                return
            for tam, tipo in ((16, 0), (48, 1)):   # ICON_SMALL, ICON_BIG
                hicon = ctypes.windll.user32.LoadImageW(
                    None, ico, 1, tam, tam, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
                if hicon:
                    ctypes.windll.user32.SendMessageW(hwnd, 0x80, tipo, hicon)
        except Exception:
            log.debug("no pude setear el ícono", exc_info=True)

    def _js_flush(self):
        self._set_taskbar_icon()
        self._ajustar_posicion()
        self.window.expose(self.toggle, self.send_text, self.switch_brain,
                           self.get_timers, self.toggle_mic,
                           self.get_skills_data, self.save_comandos,
                           self.instalar_skill, self.abrir_web,
                           self.abrir_url, self.nueva_conversacion,
                           self.abortar)
        self._ready.set()
        self._js(f"hud.brains({json.dumps(self.brains)})")
        for code in self._pending:
            self.window.evaluate_js(code)
        self._pending.clear()


# pywebview solo corre en el thread principal: kloom.py invierte los roles
# (asyncio va a un thread worker y el main se queda sirviendo la UI).
_INSTANCE: Hud | None = None
_REGISTERED = threading.Event()


def serve_main_thread(timeout: float = 300):
    """Bloquea el thread principal sirviendo la ventana del HUD. Vuelve si
    nadie registra un HUD (p. ej. main() murió antes). El plazo es generoso:
    cargar Whisper en una GPU ocupada más conectar el cerebro puede pasar
    el minuto, y rendirse deja a HARVIS sin ventana."""
    if not _REGISTERED.wait(timeout):
        log.warning("HUD: nadie se registró, no levanto ventana")
        return
    hud = _INSTANCE
    try:
        import webview
    except Exception as e:
        log.warning("HUD deshabilitado (pywebview no carga: %s)", e)
        threading.Event().wait()          # mantener vivo el proceso
        return
    ancho, alto = _pantalla()
    esc = _escala()
    w, h = int(ORB[0] * esc), int(ORB[1] * esc)
    hud.window = webview.create_window(
        "HARVIS", html=HTML.replace("__AVATAR__", AVATAR_URI)
                          .replace("__PROMOS__", _promos_json()),
        frameless=True, easy_drag=True,
        on_top=True, width=w, height=h,
        min_size=(ORB[0], ORB[1]),  # el default es (200,100) y pisa al orbe
        x=ancho - w - MARGIN, y=alto - h - MARGIN,
        background_color="#0b2134")
    hud.window.events.loaded += hud._js_flush
    webview.start(gui="edgechromium", private_mode=True)


def shutdown():
    """Cierra la ventana para desbloquear serve_main_thread()."""
    try:
        import webview
        for w in list(webview.windows):
            w.destroy()
    except Exception:
        pass
