"""Sistema visual de FinLens: «terminal de research editorial».

Una nota de análisis de banco de inversión impresa sobre tinta cálida, cruzada con un terminal
financiero. Tokens de diseño, CSS inyectado en Streamlit y paleta para Altair. Sin lógica de negocio.

Decisiones:
- Tinta casi negra cálida (no #000) + hueso para texto: lectura larga sin fatiga, aire de papel.
- Un único acento latón: marca acción primaria, estado «en curso» y numeración de secciones.
- Verde/rojo de mercado SOLO con significado (verificada/fallo, alcista/bajista).
- Fraunces (display serif con carácter) para titulares, IBM Plex Sans para cuerpo y IBM Plex Mono
  para cifras, tickers, modelos y traza (tabulares).
- Movimiento contenido: el nodo en curso del pipeline «escanea»; los sellos se estampan una vez.
"""
from __future__ import annotations

import streamlit as st

# --- Tokens ---------------------------------------------------------------------------------

INK = "#12110E"  # fondo
INK_2 = "#1A1915"  # superficie
INK_3 = "#24221C"  # superficie elevada
RULE = "#3A372E"  # filete fino
RULE_STRONG = "#5A5446"
PAPER = "#EDE6D6"  # texto principal (contraste ~15:1 sobre INK)
PAPER_DIM = "#BDB4A2"  # texto secundario (~9:1)
MUTED = "#958D7E"  # terciario (~5.8:1, AA)
BRASS = "#C8A24A"  # acento único (~8:1)
BRASS_DIM = "#8F7536"
UP = "#6CC38A"  # verde de mercado (~9:1)
DOWN = "#E8716A"  # rojo de mercado (~6:1)

FONT_DISPLAY = "Fraunces"
FONT_BODY = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"

FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Fraunces:ital,opsz,wght@0,9..144,300..800;1,9..144,300..700"
    "&family=IBM+Plex+Mono:wght@400;500;600"
    "&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap"
)

# Paleta para gráficos Altair (Gantt de la traza).
CHART = {
    "modelo": BRASS,
    "local": "#7D7667",
    "fallo": DOWN,
    "texto": PAPER_DIM,
    "rejilla": "#2A2822",
}

_GRAIN = (
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>"
    "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' "
    "stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 .95  0 0 0 0 .85  0 0 0 .5 0'/>"
    "</filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>\")"
)

CSS = f"""
@import url('{FONTS_URL}');
:root {{
  --ink:{INK}; --ink-2:{INK_2}; --ink-3:{INK_3}; --rule:{RULE}; --rule-strong:{RULE_STRONG};
  --paper:{PAPER}; --paper-dim:{PAPER_DIM}; --muted:{MUTED}; --brass:{BRASS}; --brass-dim:{BRASS_DIM};
  --up:{UP}; --down:{DOWN};
  --f-display:'{FONT_DISPLAY}', Georgia, 'Times New Roman', serif;
  --f-body:'{FONT_BODY}', 'Segoe UI', sans-serif;
  --f-mono:'{FONT_MONO}', 'Cascadia Mono', Consolas, monospace;
  --s1:4px; --s2:8px; --s3:16px; --s4:24px; --s5:32px; --s6:48px; --s7:64px;
}}

/* ---------- Lienzo ---------- */
.stApp {{ background: var(--ink); color: var(--paper); }}
.stApp::before {{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:0; opacity:.045;
  background-image:{_GRAIN};
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"], .block-container {{
  max-width: 1180px; padding-top: var(--s5); padding-bottom: var(--s7);
}}
html, body, .stApp, .stMarkdown, p, li, label {{ font-family: var(--f-body); }}
.stMarkdown p {{ line-height: 1.6; }}
::selection {{ background: var(--brass); color: var(--ink); }}
a {{ color: var(--brass); }}
*:focus-visible {{ outline: 2px solid var(--brass) !important; outline-offset: 2px; }}

/* ---------- Mancheta ---------- */
.fl-mast {{ border-bottom: 3px double var(--rule-strong); padding-bottom: var(--s3); margin-bottom: var(--s4); }}
.fl-mast__top {{ display:flex; justify-content:space-between; gap:var(--s3); align-items:baseline;
  font: 500 11px/1.4 var(--f-mono); letter-spacing:.14em; text-transform:uppercase; color:var(--muted);
  border-bottom:1px solid var(--rule); padding-bottom:var(--s2); }}
.fl-mast__row {{ display:flex; justify-content:space-between; align-items:flex-end; gap:var(--s4);
  flex-wrap:wrap; padding-top:var(--s3); }}
.fl-mast__row > div:first-child {{ flex:1 1 340px; min-width:0; }}
.fl-brand {{ font-family:var(--f-display); font-weight:600; font-size:clamp(44px,7vw,76px);
  line-height:.92; letter-spacing:-.02em; margin:0; color:var(--paper);
  font-variation-settings:"opsz" 144, "SOFT" 30; }}
.fl-brand em {{ font-style:italic; font-weight:400; color:var(--brass); }}
.fl-tagline {{ font-family:var(--f-display); font-style:italic; font-size:18px; color:var(--paper-dim);
  margin:var(--s2) 0 0; max-width:40ch; }}

/* ---------- Barra de proveedores ---------- */
.fl-prov {{ display:grid; grid-auto-flow:column; grid-auto-columns:minmax(0,1fr); border:1px solid var(--rule);
  min-width:min(520px,100%); flex:0 1 600px; }}
.fl-prov__cell {{ padding:var(--s2) 10px; border-left:1px solid var(--rule); min-width:0; }}
.fl-prov__cell:first-child {{ border-left:0; }}
.fl-prov__cap {{ font:600 10px/1 var(--f-mono); letter-spacing:.14em; color:var(--muted); display:flex;
  justify-content:space-between; gap:4px; }}
.fl-prov__be {{ font:500 12px/1.5 var(--f-mono); color:var(--paper); margin-top:6px; }}
.fl-prov__model {{ font:400 11px/1.3 var(--f-mono); color:var(--paper-dim); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }}
.fl-prov__cell.is-mock {{ background:repeating-linear-gradient(135deg,transparent 0 6px,rgba(200,162,74,.07) 6px 7px); }}
.fl-prov__cell.is-mock .fl-prov__be {{ color:var(--brass); }}
.fl-dot {{ width:7px; height:7px; display:inline-block; border-radius:50%; background:var(--up); }}
.is-mock .fl-dot {{ background:transparent; border:1px solid var(--brass); }}
.fl-mode {{ margin-top:var(--s3); display:flex; gap:var(--s3); align-items:baseline; flex-wrap:wrap;
  font:13px/1.5 var(--f-body); color:var(--paper-dim); }}
.fl-mode__tag {{ font:600 11px/1 var(--f-mono); letter-spacing:.14em; text-transform:uppercase;
  padding:5px 8px; border:1px solid var(--up); color:var(--up); }}
.fl-mode__tag.is-demo, .fl-mode__tag.is-partial {{ border-color:var(--brass); color:var(--brass); }}

/* ---------- Secciones tipo informe ---------- */
.fl-sec {{ display:flex; align-items:baseline; gap:var(--s3); margin:var(--s6) 0 var(--s3); }}
.fl-sec__n {{ font:500 13px/1 var(--f-mono); color:var(--brass); letter-spacing:.06em; }}
.fl-sec__t {{ font-family:var(--f-display); font-weight:500; font-size:30px; line-height:1.1; margin:0;
  color:var(--paper); letter-spacing:-.01em; white-space:nowrap; }}
.fl-sec::after {{ content:""; flex:1; border-bottom:1px solid var(--rule); transform:translateY(-6px); }}
.fl-sec__aside {{ font:12px/1.4 var(--f-mono); color:var(--muted); order:3; white-space:nowrap; }}
.fl-sub {{ font:600 11px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--muted);
  margin:var(--s5) 0 var(--s3); display:flex; gap:var(--s2); align-items:center; }}
.fl-sub b {{ color:var(--brass); font-weight:600; }}
.fl-sub::after {{ content:""; flex:1; border-bottom:1px solid var(--rule); }}

/* ---------- Ranuras de material ---------- */
.fl-slot {{ border-top:2px solid var(--rule-strong); padding-top:var(--s3); margin-bottom:var(--s2); }}
.fl-slot.is-ready {{ border-top-color:var(--up); }}
.fl-slot.is-sample {{ border-top-color:var(--brass); }}
.fl-slot__head {{ display:flex; gap:var(--s3); align-items:flex-start; }}
.fl-slot__l {{ font-family:var(--f-display); font-size:44px; line-height:.8; font-weight:300;
  color:var(--rule-strong); font-style:italic; }}
.is-ready .fl-slot__l {{ color:var(--up); }} .is-sample .fl-slot__l {{ color:var(--brass); }}
.fl-slot__t {{ font-family:var(--f-display); font-size:21px; font-weight:500; color:var(--paper); line-height:1.1; }}
.fl-slot__d {{ font:12px/1.5 var(--f-body); color:var(--muted); margin-top:2px; }}
.fl-slot__st {{ margin-top:var(--s2); font:500 11px/1.4 var(--f-mono); letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted); word-break:break-word; }}
.is-ready .fl-slot__st {{ color:var(--up); }} .is-sample .fl-slot__st {{ color:var(--brass); }}

/* ---------- Widgets de Streamlit ---------- */
[data-testid="stFileUploaderDropzone"] {{ background:var(--ink-2); border:1px dashed var(--rule-strong);
  border-radius:0; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color:var(--brass); }}
[data-testid="stFileUploaderDropzoneInstructions"] span, [data-testid="stFileUploaderDropzoneInstructions"] small
  {{ font-family:var(--f-body); }}
.stTextArea textarea, .stTextInput input {{ background:var(--ink-2); font-family:var(--f-display);
  font-size:18px; font-style:italic; border-radius:0; color:var(--paper); }}
[data-testid="stWidgetLabel"] p {{ font:600 11px/1.4 var(--f-mono) !important; letter-spacing:.12em;
  text-transform:uppercase; color:var(--paper-dim); }}
.stButton > button, [data-testid="stBaseButton-secondary"] {{ border-radius:0; font-family:var(--f-body);
  border-color:var(--rule-strong); transition:border-color .15s ease-out, color .15s ease-out; }}
.stButton > button:hover {{ border-color:var(--brass); color:var(--brass); }}
[data-testid="stBaseButton-primary"] {{ background:var(--brass) !important; color:var(--ink) !important;
  border:0 !important; font:600 13px/1 var(--f-mono) !important; letter-spacing:.16em; text-transform:uppercase;
  padding:14px 28px !important; min-height:48px; transition:background .15s ease-out, transform .15s ease-out; }}
[data-testid="stBaseButton-primary"] p {{ font:inherit !important; }}
[data-testid="stBaseButton-primary"]:hover {{ background:#D8B45C !important; }}
[data-testid="stBaseButton-primary"]:active {{ transform:translateY(1px); }}
[data-testid="stAlert"] {{ border-radius:0; }}

/* Pestañas como índice de la nota (Streamlit ≥1.5x: react-aria) */
[role="tablist"] {{ gap:0 !important; border-bottom:1px solid var(--rule); }}
[data-testid="stTab"] {{ padding:14px 18px !important; color:var(--muted); transition:color .15s ease-out; }}
[data-testid="stTab"] p {{ font:500 12px/1 var(--f-mono) !important; letter-spacing:.12em; text-transform:uppercase; }}
[data-testid="stTab"]:hover, [data-testid="stTab"][aria-selected="true"] {{ color:var(--paper); }}
.react-aria-SelectionIndicator {{ background:var(--brass) !important; height:2px !important; }}
.stTabs [data-baseweb="tab"] p {{ font:500 12px/1 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; }}
.stTabs [data-baseweb="tab-highlight"] {{ background:var(--brass); }}

/* Tabla de traza: papel de libro mayor */
.stTable table, [data-testid="stTable"] table {{ font:12px/1.45 var(--f-mono); border-collapse:collapse; }}
[data-testid="stTable"] th {{ font:600 10px/1.3 var(--f-mono) !important; letter-spacing:.12em; text-transform:uppercase;
  color:var(--muted) !important; background:transparent !important; border-bottom:1px solid var(--rule-strong) !important; }}
[data-testid="stTable"] td {{ font:12px/1.45 var(--f-mono) !important; color:var(--paper-dim); border-color:var(--rule) !important; font-variant-numeric:tabular-nums; }}

/* Chat */
[data-testid="stChatMessage"] {{ background:transparent; border-top:1px solid var(--rule); border-radius:0;
  padding:var(--s3) 0; }}
[data-testid="stChatInput"] textarea {{ font-family:var(--f-body); }}
[data-testid="stChatInput"] {{ border-radius:0; }}

/* Audio e imagen */
[data-testid="stAudio"] audio, .stAudio audio {{ width:100%; filter:sepia(.35) saturate(.8); }}
[data-testid="stImage"] img, [data-testid="stImageContainer"] img {{ border:1px solid var(--rule); }}
[data-testid="stExpander"] details {{ border-radius:0; border-color:var(--rule); }}
[data-testid="stExpander"] summary p {{ font:500 12px/1 var(--f-mono); letter-spacing:.08em; text-transform:uppercase; }}

/* ---------- Mapa del pipeline ---------- */
.fl-map {{ border:1px solid var(--rule); background:linear-gradient(var(--ink-2),var(--ink-2)) padding-box;
  padding:var(--s3) var(--s4) var(--s4); position:relative; }}
.fl-map__head {{ display:flex; justify-content:space-between; gap:var(--s3); flex-wrap:wrap;
  font:500 11px/1.4 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
  border-bottom:1px solid var(--rule); padding-bottom:var(--s2); margin-bottom:var(--s3); }}
.fl-map__head b {{ color:var(--paper); font-weight:500; }}
.fl-map__head .is-live {{ color:var(--brass); }}
.fl-phase {{ display:flex; gap:var(--s3); align-items:stretch; margin-top:var(--s3); }}
.fl-phase__label {{ writing-mode:vertical-rl; transform:rotate(180deg); font:600 10px/1 var(--f-mono);
  letter-spacing:.2em; color:var(--muted); text-transform:uppercase; border-left:1px solid var(--rule);
  padding-left:6px; text-align:center; }}
.fl-flow {{ display:flex; align-items:center; gap:0; flex:1; min-width:0; list-style:none; margin:0; padding:0; }}
.fl-stage {{ flex:1 1 0; min-width:0; display:flex; flex-direction:column; gap:var(--s2); }}
.fl-stage.is-par {{ flex-grow:1; border-left:1px solid var(--brass-dim); border-right:1px solid var(--brass-dim);
  padding:0 var(--s2); position:relative; }}
.fl-stage.is-wide {{ flex-grow:3; }}
.fl-stage__tag {{ font:500 9px/1 var(--f-mono); letter-spacing:.18em; color:var(--brass); text-transform:uppercase;
  text-align:center; }}
.fl-lane {{ display:flex; align-items:center; gap:0; }}
.fl-arrow {{ flex:0 0 18px; height:1px; background:var(--rule-strong); position:relative; }}
.fl-arrow::after {{ content:""; position:absolute; right:0; top:-3px; border-left:5px solid var(--rule-strong);
  border-top:3.5px solid transparent; border-bottom:3.5px solid transparent; }}
.fl-node {{ flex:1 1 0; min-width:0; border:1px solid var(--rule); background:var(--ink); padding:10px 10px 8px;
  position:relative; overflow:hidden; animation:fl-in .35s ease-out both; }}
.fl-node__top {{ display:flex; justify-content:space-between; font:500 10px/1 var(--f-mono); letter-spacing:.1em;
  color:var(--muted); }}
.fl-node__cap {{ color:var(--paper-dim); }}
.fl-node__t {{ font-family:var(--f-display); font-size:14.5px; word-break:normal; overflow-wrap:normal; hyphens:auto; line-height:1.15; color:var(--paper); margin:6px 0 4px;
  font-weight:500; }}
.fl-node__m {{ font:400 10.5px/1.35 var(--f-mono); color:var(--paper-dim); overflow:hidden; overflow-wrap:anywhere;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }}
.fl-node__f {{ display:flex; justify-content:space-between; gap:4px; margin-top:8px; padding-top:6px;
  border-top:1px solid var(--rule); font:500 10px/1.2 var(--f-mono); letter-spacing:.06em; }}
.fl-node__s {{ text-transform:uppercase; letter-spacing:.12em; }}
.fl-node__x {{ color:var(--paper-dim); font-variant-numeric:tabular-nums; white-space:nowrap; }}
.fl-node.st-pendiente {{ border-style:dashed; }}
.fl-node.st-pendiente .fl-node__t, .fl-node.st-pendiente .fl-node__m {{ color:var(--muted); }}
.fl-node.st-pendiente .fl-node__s {{ color:var(--muted); }}
.fl-node.st-en_curso {{ border-color:var(--brass); }}
.fl-node.st-en_curso .fl-node__s {{ color:var(--brass); }}
.fl-node.st-en_curso::after {{ content:""; position:absolute; left:0; bottom:0; height:2px; width:40%;
  background:var(--brass); animation:fl-scan 1.1s ease-in-out infinite alternate; }}
.fl-node.st-ok {{ border-top:2px solid var(--up); }}
.fl-node.st-ok .fl-node__s {{ color:var(--up); }}
.fl-node.st-simulado {{ border-top:2px solid var(--brass-dim);
  background:repeating-linear-gradient(135deg,var(--ink) 0 7px,rgba(200,162,74,.06) 7px 8px); }}
.fl-node.st-simulado .fl-node__s {{ color:var(--brass); }}
.fl-node.st-fallo {{ border-color:var(--down); border-top-width:2px; }}
.fl-node.st-fallo .fl-node__s {{ color:var(--down); }}
.fl-node.st-omitido {{ opacity:.5; border-style:dotted; }}
.fl-node.st-omitido .fl-node__s {{ color:var(--muted); }}
.fl-node__err {{ font:11px/1.35 var(--f-body); color:var(--down); margin-top:6px; }}
.fl-legend {{ display:flex; gap:var(--s4); flex-wrap:wrap; margin-top:var(--s3); font:10px/1.4 var(--f-mono);
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }}
.fl-legend i {{ display:inline-block; width:14px; height:8px; margin-right:6px; vertical-align:middle; border:1px solid var(--rule-strong); }}
.fl-legend .lg-ok {{ border-top:2px solid var(--up); }}
.fl-legend .lg-sim {{ border-top:2px solid var(--brass-dim); background:repeating-linear-gradient(135deg,transparent 0 3px,rgba(200,162,74,.35) 3px 4px); }}
.fl-legend .lg-run {{ border-color:var(--brass); }}
.fl-legend .lg-fail {{ border-color:var(--down); }}
.fl-legend .lg-pend {{ border-style:dashed; }}
@keyframes fl-scan {{ from {{ transform:translateX(0); }} to {{ transform:translateX(150%); }} }}
@keyframes fl-in {{ from {{ opacity:0; transform:translateY(4px); }} to {{ opacity:1; transform:none; }} }}

/* ---------- Nota de research ---------- */
.fl-note {{ max-width: 1080px; }}
.fl-kicker {{ font:600 11px/1.4 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--brass); }}
.fl-q {{ font-family:var(--f-display); font-style:italic; font-size:20px !important; color:var(--paper-dim); margin:var(--s2) 0 var(--s4);
  max-width:60ch; line-height:1.4; }}
.fl-lede {{ font-family:var(--f-display); font-size:23px !important; line-height:1.5 !important; color:var(--paper); max-width:62ch;
  font-weight:350; font-variation-settings:"opsz" 30; }}
.fl-lede.has-drop::first-letter {{ float:left; font-size:3.4em; line-height:.82; padding:6px 10px 0 0; color:var(--brass);
  font-weight:600; font-variation-settings:"opsz" 144; }}

.fl-figs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); border-top:1px solid var(--rule-strong);
  border-bottom:1px solid var(--rule-strong); }}
.fl-fig {{ padding:var(--s4) var(--s4) var(--s3) 0; border-right:1px solid var(--rule); position:relative; min-width:0; }}
.fl-fig + .fl-fig {{ padding-left:var(--s4); }}
.fl-fig:last-child {{ border-right:0; }}
.fl-fig__n {{ font:600 11px/1.3 var(--f-mono); letter-spacing:.14em; text-transform:uppercase; color:var(--paper-dim); }}
.fl-fig__v {{ font:500 clamp(30px,4vw,42px)/1.05 var(--f-mono); color:var(--paper); margin:var(--s2) 0 6px;
  font-variant-numeric:tabular-nums; letter-spacing:-.03em; overflow-wrap:anywhere; }}
.fl-fig__p {{ font:12px/1.4 var(--f-mono); color:var(--muted); }}
.fl-fig__foot {{ display:flex; gap:var(--s2); align-items:center; flex-wrap:wrap; margin-top:var(--s3); }}

.fl-stamp {{ display:inline-block; font:700 10px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase;
  padding:6px 8px 5px; border:1.5px solid currentColor; transform:rotate(-2.5deg);
  animation:fl-stamp .45s cubic-bezier(.2,.9,.3,1.2) both; }}
.fl-stamp.v {{ color:var(--up); box-shadow:inset 0 0 0 1px rgba(108,195,138,.25); }}
.fl-stamp.x {{ color:var(--down); }}
.fl-stamp.s {{ color:var(--paper-dim); border-style:dashed; }}
.fl-stamp.u {{ color:var(--muted); border-style:dotted; transform:none; }}
@keyframes fl-stamp {{ from {{ opacity:0; transform:rotate(-8deg) scale(1.35); }} to {{ opacity:1; transform:rotate(-2.5deg) scale(1); }} }}

.fl-chip {{ display:inline-flex; align-items:center; gap:5px; font:500 10.5px/1 var(--f-mono); letter-spacing:.06em;
  padding:4px 6px; border:1px solid var(--rule-strong); color:var(--paper-dim); white-space:nowrap; margin:2px 4px 2px 0; }}
.fl-chip::before {{ content:""; width:6px; height:6px; background:currentColor; }}
.fl-chip.o-documento {{ color:var(--paper); }}
.fl-chip.o-grafico {{ color:var(--brass); }}
.fl-chip.o-grafico::before {{ transform:rotate(45deg); }}
.fl-chip.o-audio {{ color:var(--paper-dim); }}
.fl-chip.o-audio::before {{ border-radius:50%; }}

.fl-finds {{ list-style:none; padding:0; margin:0; }}
.fl-find {{ display:grid; grid-template-columns:28px 1fr; gap:var(--s2); padding:var(--s3) 0; border-bottom:1px solid var(--rule); }}
.fl-find__i {{ font:500 12px/1.7 var(--f-mono); color:var(--brass); }}
.fl-find__s {{ font:16px/1.6 var(--f-body); color:var(--paper); }}
.fl-find__c {{ margin-top:6px; }}

.fl-corr {{ display:grid; grid-template-columns:auto 1fr; gap:var(--s4); padding:var(--s4) 0; border-bottom:1px solid var(--rule); }}
.fl-corr.is-tension {{ border-left:2px solid var(--down); padding-left:var(--s3); }}
.fl-matrix {{ display:flex; gap:3px; align-items:flex-start; }}
.fl-matrix span {{ width:42px; text-align:center; font:600 9px/1 var(--f-mono); letter-spacing:.1em; padding:22px 0 6px;
  border:1px solid var(--rule); color:var(--muted); position:relative; }}
.fl-matrix span::before {{ content:""; position:absolute; top:7px; left:50%; width:8px; height:8px; margin-left:-4px;
  border:1px solid var(--rule-strong); }}
.fl-matrix span.on {{ color:var(--paper); border-color:var(--brass-dim); }}
.fl-matrix span.on::before {{ background:var(--brass); border-color:var(--brass); }}
.fl-corr__s {{ font-family:var(--f-display); font-size:19px; line-height:1.45; color:var(--paper); }}
.fl-corr__tag {{ font:600 10px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--brass); margin-bottom:6px; }}
.is-tension .fl-corr__tag {{ color:var(--down); }}

.fl-limits {{ list-style:none; padding:0 0 0 var(--s3); margin:0; border-left:1px solid var(--rule-strong); }}
.fl-limits li {{ font:italic 15px/1.55 var(--f-display); color:var(--paper-dim); padding:4px 0; }}

.fl-editor {{ border-left:2px solid var(--brass); padding:var(--s2) var(--s3); margin:var(--s2) 0; background:rgba(200,162,74,.06); }}
.fl-editor.is-error {{ border-left-color:var(--down); background:rgba(232,113,106,.07); }}
.fl-editor__k {{ font:600 10px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--brass); }}
.is-error .fl-editor__k {{ color:var(--down); }}
.fl-editor__t {{ font:14px/1.5 var(--f-body); color:var(--paper); margin-top:4px; }}

.fl-colophon {{ margin-top:var(--s5); padding-top:var(--s2); border-top:1px solid var(--rule); display:flex; gap:var(--s3);
  font:11px/1.55 var(--f-mono); color:var(--muted); letter-spacing:.02em; }}
.fl-colophon b {{ color:var(--paper-dim); font-weight:600; letter-spacing:.14em; text-transform:uppercase; white-space:nowrap; }}

/* Entradas leídas */
.fl-read {{ border-top:2px solid var(--rule-strong); padding-top:var(--s3); }}
.fl-read__k {{ font:600 10px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--muted); }}
.fl-read__big {{ font:500 30px/1.1 var(--f-mono); color:var(--paper); margin:var(--s2) 0; font-variant-numeric:tabular-nums; }}
.fl-read__big.up {{ color:var(--up); }} .fl-read__big.down {{ color:var(--down); }}
.fl-read__t {{ font:14.5px/1.55 var(--f-body); color:var(--paper-dim); }}
.fl-read ul {{ padding-left:18px; margin:var(--s2) 0 0; }}
.fl-read li {{ font:13.5px/1.5 var(--f-body); color:var(--paper-dim); }}
.fl-quote {{ font:italic 17px/1.6 var(--f-display); color:var(--paper); border-left:2px solid var(--brass); padding-left:var(--s3);
  margin:var(--s2) 0 0; }}
.fl-empty {{ font:italic 15px/1.5 var(--f-display) !important; color:var(--muted); }}

/* KPIs de traza */
.fl-kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border-top:1px solid var(--rule-strong);
  border-bottom:1px solid var(--rule); margin-bottom:var(--s4); }}
.fl-kpi {{ padding:var(--s3) var(--s3) var(--s3) 0; border-right:1px solid var(--rule); }}
.fl-kpi + .fl-kpi {{ padding-left:var(--s3); }}
.fl-kpi:last-child {{ border-right:0; }}
.fl-kpi__k {{ font:600 10px/1 var(--f-mono); letter-spacing:.16em; text-transform:uppercase; color:var(--muted); }}
.fl-kpi__v {{ font:500 30px/1.1 var(--f-mono); color:var(--paper); margin-top:var(--s2); font-variant-numeric:tabular-nums; }}
.fl-kpi__v small {{ font-size:13px; color:var(--muted); margin-left:4px; }}
.fl-note-sm {{ font:11.5px/1.5 var(--f-mono) !important; color:var(--muted); margin-top:var(--s2); }}

/* Medios */
.fl-media-k {{ font:500 10.5px/1.4 var(--f-mono) !important; color:var(--muted); letter-spacing:.06em; margin:var(--s2) 0; }}
.fl-script {{ font:italic 17px/1.6 var(--f-display) !important; color:var(--paper-dim); margin-top:var(--s3); }}

/* Streamlit envuelve h1-h3 y les impone tamaño: se fuerza la tipografía editorial. */
.fl-brand {{ font-size:clamp(48px,7vw,80px) !important; line-height:.92 !important; padding:0 !important;
  margin:0 !important; font-weight:600 !important; }}
.fl-sec__t {{ font-size:30px !important; line-height:1.1 !important; padding:0 !important; margin:0 !important;
  font-weight:500 !important; }}
.fl-sub {{ font:600 11px/1 var(--f-mono) !important; letter-spacing:.16em !important; padding:0 !important;
  margin:var(--s5) 0 var(--s3) !important; color:var(--muted) !important; }}
.fl-thumb {{ width:100%; display:block; margin-top:var(--s3); border:1px solid var(--rule);
  filter:invert(.93) hue-rotate(180deg) saturate(.85) contrast(.95); }}

/* Mercado: contraste visión ↔ datos */
.fl-contrast {{ border-top:2px solid var(--brass); padding-top:var(--s3); }}
.fl-contrast__head {{ display:flex; gap:var(--s3); align-items:flex-end; padding-bottom:var(--s3); border-bottom:1px solid var(--rule); }}
.fl-contrast__score {{ font:500 56px/0.9 var(--f-mono); color:var(--brass); font-variant-numeric:tabular-nums; letter-spacing:-.04em; }}
.fl-contrast__k {{ font:600 10.5px/1.5 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--paper-dim); }}
.fl-contrast__list {{ list-style:none; margin:0; padding:0; }}
.fl-contrast__row {{ display:grid; grid-template-columns:150px 1fr; gap:var(--s3); padding:var(--s3) 0; border-bottom:1px solid var(--rule); }}
.fl-contrast__row.is-discrepa {{ border-left:2px solid var(--down); padding-left:var(--s3); }}
.fl-contrast__saw {{ font:italic 17px/1.45 var(--f-display); color:var(--paper); }}
.fl-contrast__data {{ font:13.5px/1.5 var(--f-body); color:var(--paper-dim); margin-top:6px; }}
.fl-contrast__saw b, .fl-contrast__data b {{ display:block; font:600 9.5px/1.4 var(--f-mono); font-style:normal; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted); margin-bottom:2px; }}
.fl-kvs {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); border-top:1px solid var(--rule-strong); }}
.fl-kv {{ padding:var(--s2) var(--s3) var(--s2) 0; border-bottom:1px solid var(--rule); }}
.fl-kv__k {{ font:600 10px/1.3 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }}
.fl-kv__v {{ font:500 20px/1.3 var(--f-mono); color:var(--paper); font-variant-numeric:tabular-nums; margin-top:4px; overflow-wrap:anywhere; }}
.fl-contrast-mini {{ display:flex; gap:var(--s2); align-items:center; flex-wrap:wrap; margin-top:var(--s2);
  font:12px/1.4 var(--f-mono); color:var(--paper-dim); }}
/* §0 Cerebro: marco editorial del lienzo */
.fl-brain-cap {{ display:flex; justify-content:space-between; gap:var(--s3); flex-wrap:wrap; font:11px/1.5 var(--f-mono);
  color:var(--muted); margin-top:var(--s2); }}
[data-testid="stIFrame"], iframe[title="st.iframe"], .stElementContainer iframe {{ border:1px solid var(--rule) !important; }}
@media (max-width: 640px) {{ .fl-contrast__row {{ grid-template-columns:1fr; gap:var(--s2); }} .fl-contrast__score {{ font-size:44px; }} }}

/* ---------- Responsive ---------- */
@media (max-width: 900px) {{
  .fl-mast__row {{ align-items:stretch; }}
  .fl-prov {{ min-width:0; width:100%; }}
  .fl-flow {{ flex-direction:column; align-items:stretch; }}
  .fl-stage {{ flex:none; }}
  .fl-phase__label {{ writing-mode:horizontal-tb; transform:none; border-left:0; padding:0; text-align:left; }}
  .fl-phase {{ flex-direction:column; gap:var(--s2); }}
  .fl-flow > .fl-arrow {{ width:1px; height:14px; flex:0 0 14px; margin-left:24px; }}
  .fl-flow > .fl-arrow::after {{ right:-3px; top:auto; bottom:0; border-left:3.5px solid transparent; border-right:3.5px solid transparent;
    border-top:5px solid var(--rule-strong); border-bottom:0; }}
  .fl-stage.is-par {{ border-left:1px solid var(--brass-dim); border-right:0; padding:var(--s2) 0 var(--s2) var(--s2); }}
}}
@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"], .block-container {{ padding-left:16px; padding-right:16px; padding-top:var(--s4); }}
  .fl-prov {{ grid-auto-flow:row; grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .fl-prov__cell {{ border-left:0; border-top:1px solid var(--rule); }}
  .fl-sec__t {{ font-size:24px; white-space:normal; }}
  .fl-sec__aside {{ display:none; }}
  .fl-lane {{ flex-direction:column; align-items:stretch; }}
  .fl-node {{ flex:none; }}
  .fl-legend {{ gap:var(--s2) var(--s3); }}
  .fl-lane > .fl-arrow {{ width:1px; height:12px; flex:0 0 12px; margin-left:24px; }}
  .fl-lane > .fl-arrow::after {{ right:-3px; top:auto; bottom:0; border-left:3.5px solid transparent; border-right:3.5px solid transparent;
    border-top:5px solid var(--rule-strong); border-bottom:0; }}
  .fl-fig {{ border-right:0; border-bottom:1px solid var(--rule); padding-left:0 !important; }}
  .fl-kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .fl-kpi {{ border-bottom:1px solid var(--rule); }}
  .fl-kpi:nth-child(2) {{ border-right:0; }}
  .fl-kpi:nth-child(3) {{ padding-left:0; }}
  .fl-corr {{ grid-template-columns:1fr; gap:var(--s2); }}
  .fl-lede {{ font-size:19px !important; }}
  .fl-mast__top span:last-child {{ display:none; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation:none !important; transition:none !important; }}
}}
"""


def inject() -> None:
    """Inyecta fuentes y CSS. Llamar una vez por ejecución, tras `st.set_page_config`."""
    # En una sola línea: el parser de Markdown no debe ver líneas en blanco ni sangrías.
    st.markdown(f"<style>{' '.join(CSS.split())}</style>", unsafe_allow_html=True)
