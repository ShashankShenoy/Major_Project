# dashboard.py — MARVIS · Maritime Visual Surveillance Intelligence System
# Run: streamlit run dashboard.py

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import json, math, time
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import plotly.graph_objects as go
import plotly.express as px

RECENT_FRAME_WINDOW = 60
_CACHED_RESULTS = []
_CACHED_RESULTS_PATH = None
_CACHED_RESULTS_MTIME = 0

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="MARVIS · Maritime Surveillance",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Keep dashboard data fresh without manual refresh.
st_autorefresh(interval=2000, limit=None, key="live_dashboard_refresh")

# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL CSS  ── military-grade dark tactical aesthetic
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Share+Tech+Mono&family=Exo+2:wght@300;400;500&display=swap');

:root {
    --bg0:#050810; --bg1:#080d14; --bg2:#0b1019; --bg3:#0e1520;
    --border:#162030; --border2:#1e2e42;
    --teal:#00f5b4; --teal2:#00c890; --teal3:rgba(0,245,180,0.08);
    --blue:#1e90ff; --blue2:rgba(30,144,255,0.12);
    --red:#ff2d55;  --red2:rgba(255,45,85,0.12);
    --amber:#ffb800; --amber2:rgba(255,184,0,0.12);
    --purple:#9f6eff;
    --text:#b8cdd8; --textd:#4a6070; --textb:#e8f2f8;
    --mono:'Share Tech Mono',monospace;
    --head:'Rajdhani',sans-serif;
    --body:'Exo 2',sans-serif;
    --r:3px;
}

*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: var(--body) !important;
    background: var(--bg0) !important;
    color: var(--text) !important;
}

/* hide streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0 1.2rem 3rem !important; max-width: 100% !important; }
[data-testid="stSidebar"] > div { background: var(--bg1) !important; }
[data-testid="stSidebar"] { border-right: 1px solid var(--border) !important; }

/* ── SCANLINE OVERLAY ── */
body::before {
    content:''; pointer-events:none; position:fixed; inset:0; z-index:9999;
    background: repeating-linear-gradient(0deg,
        rgba(0,0,0,0.07) 0px, rgba(0,0,0,0.07) 1px,
        transparent 1px, transparent 3px);
}

/* ── TOP HEADER ── */
.marvis-hdr {
    display:flex; align-items:center; justify-content:space-between;
    padding:.9rem 1.4rem .7rem;
    background: linear-gradient(90deg,#050d10 0%,#080f17 60%,#050d10 100%);
    border-bottom: 1px solid var(--border2);
    margin-bottom:1.2rem;
    position:relative; overflow:hidden;
}
.marvis-hdr::after {
    content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
    background:linear-gradient(90deg,transparent,var(--teal2),transparent);
    opacity:.4;
}
.hdr-brand { display:flex; align-items:flex-end; gap:14px; }
.hdr-logo {
    font-family:var(--head); font-size:2rem; font-weight:700;
    color:var(--teal); letter-spacing:.18em; line-height:1;
}
.hdr-tagline {
    font-family:var(--mono); font-size:.62rem;
    color:var(--textd); letter-spacing:.14em;
    padding-bottom:3px;
}
.hdr-right { display:flex; align-items:center; gap:18px; }
.live-badge {
    display:inline-flex; align-items:center; gap:7px;
    font-family:var(--mono); font-size:.62rem; letter-spacing:.14em;
    color:var(--teal); border:1px solid rgba(0,245,180,.22);
    background:rgba(0,245,180,.06); padding:4px 12px; border-radius:var(--r);
}
.live-dot { width:7px;height:7px;border-radius:50%;background:var(--teal);
    box-shadow:0 0 6px var(--teal); animation:pulse 1.4s ease-in-out infinite; }
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.8)}}
.hdr-time {
    font-family:var(--mono); font-size:.65rem; color:var(--textd); letter-spacing:.08em; }

/* ── METRICS ROW ── */
.mrow { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:1.2rem; }
.mcard {
    background:var(--bg1); border:1px solid var(--border);
    border-top:2px solid var(--teal); padding:.9rem 1.1rem;
    position:relative; overflow:hidden; transition:border-color .2s;
}
.mcard:hover { border-color: var(--teal2); }
.mcard::before {
    content:''; position:absolute; top:0;right:0;
    width:50px;height:50px;
    background:radial-gradient(circle at top right,rgba(0,245,180,.07),transparent);
}
.mcard.blue  { border-top-color:var(--blue); }
.mcard.amber { border-top-color:var(--amber); }
.mcard.red   { border-top-color:var(--red); }
.mcard.purple{ border-top-color:var(--purple); }
.mcard-ico  { font-size:.95rem; margin-bottom:5px; }
.mcard-val  { font-family:var(--head); font-size:2.1rem; font-weight:700;
    color:#fff; line-height:1; }
.mcard-lbl  { font-family:var(--mono); font-size:.58rem; letter-spacing:.12em;
    color:var(--textd); text-transform:uppercase; margin-top:3px; }
.mcard-sub  { font-size:.7rem; color:var(--textd); margin-top:2px; }
.note-box {
    margin-top:0.85rem;
    padding:.95rem 1rem;
    border:1px solid rgba(0,245,180,.16);
    background:rgba(0,245,180,.06);
    color:var(--textd);
    font-family:var(--mono);
    font-size:.82rem;
    border-radius:10px;
}

/* ── SECTION LABEL ── */
.sec-lbl {
    font-family:var(--mono); font-size:.6rem; letter-spacing:.2em;
    color:var(--textd); text-transform:uppercase;
    display:flex; align-items:center; gap:8px;
    margin-bottom:.6rem; padding-bottom:.4rem;
    border-bottom:1px solid var(--border);
}
.sec-lbl::before { content:''; display:inline-block; width:3px; height:12px;
    background:var(--teal); border-radius:1px; }

/* ── ALERT PANEL ── */
.alert-wrap { margin-bottom:1.2rem; }
.alert-item {
    display:flex; align-items:center; gap:10px;
    padding:.5rem .85rem; margin-bottom:5px;
    background:var(--bg2); border:1px solid var(--border);
    border-left:3px solid transparent; font-size:.78rem;
    transition: background .15s;
}
.alert-item:hover { background:var(--bg3); }
.alert-item.critical { border-left-color:var(--red); background:rgba(255,45,85,.04); }
.alert-item.high     { border-left-color:var(--amber); background:rgba(255,184,0,.04); }
.alert-item.medium   { border-left-color:#ff7700; background:rgba(255,119,0,.03); }
.alert-item.low      { border-left-color:var(--textd); }
.abadge {
    font-family:var(--mono); font-size:.56rem; letter-spacing:.08em;
    padding:2px 7px; border-radius:2px; flex-shrink:0; font-weight:600; }
.abadge.critical { background:var(--red2); color:var(--red); border:1px solid rgba(255,45,85,.3); }
.abadge.high     { background:var(--amber2); color:var(--amber); border:1px solid rgba(255,184,0,.3); }
.abadge.medium   { background:rgba(255,119,0,.1); color:#ff7700; border:1px solid rgba(255,119,0,.3); }
.abadge.low      { background:rgba(74,96,112,.15); color:var(--textd); border:1px solid var(--border); }
.aships { font-family:var(--mono); font-size:.72rem; color:#fff; }
.ameta  { margin-left:auto; font-family:var(--mono); font-size:.64rem; color:var(--textd); }
.aflash { animation: flashred 1s ease-in-out 3; }
@keyframes flashred{0%,100%{background:rgba(255,45,85,.04)}50%{background:rgba(255,45,85,.12)}}

/* ── VESSEL TABLE ── */
.vtbl { width:100%; border-collapse:collapse; }
.vtbl th {
    font-family:var(--mono); font-size:.58rem; letter-spacing:.13em;
    color:var(--textd); text-transform:uppercase;
    padding:.5rem .8rem; text-align:left;
    border-bottom:1px solid var(--border2); white-space:nowrap;
}
.vtbl td {
    padding:.44rem .8rem; border-bottom:1px solid rgba(22,32,48,.6);
    font-family:var(--mono); font-size:.7rem; color:var(--text);
    white-space:nowrap;
}
.vtbl tr:hover td { background:rgba(0,245,180,.03); }
.vid { display:inline-flex; align-items:center; justify-content:center;
    width:28px; height:20px; border:1px solid currentColor;
    border-radius:2px; font-size:.62rem; font-weight:600; }
.method-lstm    { color:var(--teal);   background:rgba(0,245,180,.08); padding:1px 6px; border-radius:2px; }
.method-partial { color:var(--blue);   background:var(--blue2);        padding:1px 6px; border-radius:2px; }
.method-kin     { color:var(--textd);  background:rgba(74,96,112,.15); padding:1px 6px; border-radius:2px; }
.dir-arrow { font-size:.9rem; }
.cbar-wrap { display:flex; align-items:center; gap:6px; }
.cbar-bg   { width:48px; height:3px; background:var(--border2); border-radius:2px; }
.cbar-fill { height:100%; border-radius:2px; }
.status-ok { color:var(--teal); font-size:.6rem; letter-spacing:.06em; }
.pred-steps { color:var(--blue); }

/* ── COMPASS ── */
.compass-wrap { display:flex; flex-direction:column; align-items:center; gap:4px; }
.compass-ring {
    width:90px; height:90px; border-radius:50%;
    border:1px solid var(--border2);
    background:conic-gradient(from 0deg, rgba(0,245,180,.03), rgba(0,245,180,.08), rgba(0,245,180,.03));
    position:relative; display:flex; align-items:center; justify-content:center;
}
.compass-n,.compass-s,.compass-e,.compass-w {
    position:absolute; font-family:var(--mono); font-size:.5rem; color:var(--textd); }
.compass-n { top:4px; left:50%; transform:translateX(-50%); color:var(--red); }
.compass-s { bottom:4px; left:50%; transform:translateX(-50%); }
.compass-e { right:6px; top:50%; transform:translateY(-50%); }
.compass-w { left:6px; top:50%; transform:translateY(-50%); }
.compass-needle {
    position:absolute; width:2px; background:linear-gradient(var(--teal),rgba(0,245,180,.2));
    border-radius:1px; transform-origin:bottom center; bottom:50%;
}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {
    background:var(--bg2); border-bottom:1px solid var(--border2); gap:0; }
.stTabs [data-baseweb="tab"] {
    font-family:var(--mono) !important; font-size:.64rem !important;
    letter-spacing:.1em; color:var(--textd) !important;
    padding:.65rem 1.4rem !important;
    border-bottom:2px solid transparent !important;
    background:transparent !important;
}
.stTabs [aria-selected="true"] {
    color:var(--teal) !important; border-bottom-color:var(--teal) !important; }
.stTabs [data-baseweb="tab-panel"] { padding:0 !important; background:transparent !important; }

/* ── SIDEBAR ── */
.sb-title {
    font-family:var(--head); font-size:1rem; font-weight:700;
    color:var(--teal); letter-spacing:.15em;
    padding:.5rem 0 .75rem; border-bottom:1px solid var(--border); margin-bottom:.75rem;
}
.sb-section {
    font-family:var(--mono); font-size:.56rem; letter-spacing:.15em;
    color:var(--textd); text-transform:uppercase; margin:.75rem 0 .4rem; }
.sb-info {
    font-family:var(--mono); font-size:.62rem; color:var(--textd);
    line-height:2; background:var(--bg2); border:1px solid var(--border);
    padding:.6rem .75rem; border-radius:var(--r); }
.sb-info span { color:var(--text); }

div[data-testid="stNumberInput"] label,
div[data-testid="stSlider"] label,
div[data-testid="stTextInput"] label { font-family:var(--mono) !important; font-size:.62rem !important; color:var(--textd) !important; letter-spacing:.08em; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
SHIP_COLORS = ['#00f5b4','#1e90ff','#ff2d55','#ffb800','#9f6eff',
               '#00ccff','#ff6644','#55ff88','#ff44aa','#88aaff','#ffdd44','#44ffcc']

PLOTLY_BASE = dict(
    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(8,13,20,1)',
    font=dict(family='Share Tech Mono, monospace', color='#4a6070', size=10),
    xaxis=dict(gridcolor='#162030', linecolor='#162030', tickfont=dict(size=9), zeroline=False),
    yaxis=dict(gridcolor='#162030', linecolor='#162030', tickfont=dict(size=9), zeroline=False),
    margin=dict(l=44,r=16,t=38,b=36),
    hoverlabel=dict(bgcolor='#0e1520', bordercolor='#1e2e42',
                    font=dict(family='Share Tech Mono', size=10)),
    legend=dict(bgcolor='rgba(0,0,0,0)', bordercolor='#162030', borderwidth=1,
                font=dict(size=9), orientation='v'),
)

DIR_ARROWS = {
    'N':'↑','NE':'↗','E':'→','SE':'↘',
    'S':'↓','SW':'↙','W':'←','NW':'↖','stationary':'·'
}
DIR_LABELS = {
    'N':'N','NE':'NE','E':'E','SE':'SE',
    'S':'S','SW':'SW','W':'W','NW':'NW','stationary':'STATIONARY'
}

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING & PARSING
# ══════════════════════════════════════════════════════════════════════════════
# @st.cache_data(ttl=5)
def json_path_info(path):
    p = Path(path)
    if not p.exists():
        return f"Missing results file: {p.resolve()}"
    try:
        stat = p.stat()
        return (
            f"File exists: {p.resolve()} · {stat.st_size:,} bytes · "
            f"modified {datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M:%S}"
        )
    except Exception as exc:
        return f"Unable to inspect results file: {exc}"


def load_results(path):
    global _CACHED_RESULTS, _CACHED_RESULTS_PATH, _CACHED_RESULTS_MTIME
    p = Path(path)
    if not p.exists():
        return []

    try:
        mtime = p.stat().st_mtime
        resolved = str(p.resolve())
        if _CACHED_RESULTS_PATH == resolved and mtime == _CACHED_RESULTS_MTIME:
            return _CACHED_RESULTS

        with open(p, "r", encoding="utf-8") as f:
            results = json.load(f)

        _CACHED_RESULTS = results
        _CACHED_RESULTS_PATH = resolved
        _CACHED_RESULTS_MTIME = mtime
        return results
    except json.JSONDecodeError:
        if _CACHED_RESULTS_PATH == str(p.resolve()):
            return _CACHED_RESULTS
        return []
    except Exception:
        if _CACHED_RESULTS_PATH == str(p.resolve()):
            return _CACHED_RESULTS
        return []


def parse_metrics(results):
    if not results:
        return dict(total=0, unique=0, avg=0.0, frames=0, alerts=0,
                    lstm_frames=0, kin_frames=0, peak=0)
    ids, total, lstm_f, kin_f, peak = set(), 0, 0, 0, 0
    for fr in results:
        cnt = fr.get('ship_count', 0)
        total += cnt
        peak = max(peak, cnt)
        for s in fr.get('ships', []):
            ids.add(s.get('id'))
            m = s.get('prediction_method','')
            if 'LSTM' in str(m).upper(): lstm_f += 1
            else: kin_f += 1
    alerts = sum(len(fr.get('collision_alerts',[])) for fr in results)
    return dict(total=total, unique=len(ids), avg=total/len(results),
                frames=len(results), alerts=alerts,
                lstm_frames=lstm_f, kin_frames=kin_f, peak=peak)

def parse_ships(results):
    """Returns per-ship aggregated stats."""
    stats = defaultdict(lambda: dict(
        frames=0, conf=[], speed=[], heading=[], direction='',
        pred_steps=[], method=[], pos=[], gps=[]
    ))
    for fr in results:
        for s in fr.get('ships', []):
            sid = s.get('id')
            d = stats[sid]
            d['frames'] += 1
            d['conf'].append(s.get('confidence', 0))
            d['speed'].append(s.get('speed', 0))
            d['heading'].append(s.get('heading', 0))
            d['direction'] = s.get('direction', '--')
            d['pred_steps'].append(len(s.get('predicted_path', [])))
            d['method'].append(s.get('prediction_method', 'KIN'))
            d['pos'].append(s.get('center', [0,0]))
            gps = s.get('gps_lat'), s.get('gps_lon')
            if gps[0] is not None: d['gps'].append(gps)
    rows = []
    for sid, d in stats.items():
        methods = d['method']
        lstm_pct = sum(1 for m in methods if 'LSTM' in str(m).upper()) / max(len(methods),1) * 100
        rows.append(dict(
            id=sid, frames=d['frames'],
            conf=np.mean(d['conf']) if d['conf'] else 0,
            speed=np.mean(d['speed']) if d['speed'] else 0,
            heading=np.mean(d['heading']) if d['heading'] else 0,
            direction=d['direction'],
            pred_steps=np.mean(d['pred_steps']) if d['pred_steps'] else 0,
            lstm_pct=lstm_pct,
            last_method=d['method'][-1] if d['method'] else 'KIN',
            last_pos=d['pos'][-1] if d['pos'] else [0,0],
            last_gps=d['gps'][-1] if d['gps'] else None,
            color=SHIP_COLORS[sid % len(SHIP_COLORS)]
        ))
    return sorted(rows, key=lambda r: r['frames'], reverse=True)

def parse_alerts(results):
    seen, alerts = set(), []
    for fr in results:
        for a in fr.get('collision_alerts', []):
            key = (min(a['ship1_id'],a['ship2_id']), max(a['ship1_id'],a['ship2_id']))
            if key not in seen:
                seen.add(key)
                alerts.append(a)
    return sorted(alerts, key=lambda a: ['critical','high','medium','low'].index(
        a.get('risk_level','low')))

def parse_trajectories(results):
    traj = defaultdict(list)
    pred_traj = defaultdict(list)
    for fr in results:
        for s in fr.get('ships', []):
            sid = s.get('id')
            c = s.get('center', [0,0])
            traj[sid].append((c[0], c[1], fr.get('frame',0),
                              s.get('heading',0), s.get('speed',0),
                              s.get('direction','--'),
                              s.get('prediction_method','KIN')))
            pred = s.get('predicted_path', [])
            if pred: pred_traj[sid] = pred  # keep last prediction per ship
    return traj, pred_traj

# ══════════════════════════════════════════════════════════════════════════════
# PLOT FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def plot_trajectories(results):
    traj, pred_traj = parse_trajectories(results)
    if not traj:
        return go.Figure()

    # ── STEP 1: collect all ACTUAL trajectory points to find bounds ──
    all_xs, all_ys = [], []
    for sid, pts in traj.items():
        all_xs += [p[0] for p in pts]
        all_ys += [p[1] for p in pts]

    if not all_xs:
        return go.Figure()

    # ── STEP 2: remove outlier ships (positions > 2 std devs from median) ──
    med_x, med_y   = np.median(all_xs), np.median(all_ys)
    std_x, std_y   = np.std(all_xs),   np.std(all_ys)
    clip = 2.5
    x_lo, x_hi = med_x - clip*std_x, med_x + clip*std_x
    y_lo, y_hi = med_y - clip*std_y, med_y + clip*std_y

    # keep ships whose AVERAGE position is within bounds
    good_sids = []
    for sid, pts in traj.items():
        ax = np.mean([p[0] for p in pts])
        ay = np.mean([p[1] for p in pts])
        if x_lo <= ax <= x_hi and y_lo <= ay <= y_hi:
            good_sids.append(sid)

    # ── STEP 3: recompute clean bounds with padding ──
    clean_xs, clean_ys = [], []
    for sid in good_sids:
        clean_xs += [p[0] for p in traj[sid]]
        clean_ys += [p[1] for p in traj[sid]]

    pad_x = max((max(clean_xs)-min(clean_xs))*0.12, 50)
    pad_y = max((max(clean_ys)-min(clean_ys))*0.12, 50)
    xr = [min(clean_xs)-pad_x, max(clean_xs)+pad_x]
    yr = [min(clean_ys)-pad_y, max(clean_ys)+pad_y]

    fig = go.Figure()

    for sid in good_sids:
        pts = traj[sid]
        col = SHIP_COLORS[sid % len(SHIP_COLORS)]
        xs  = [p[0] for p in pts]
        ys  = [p[1] for p in pts]
        hdgs    = [p[3] for p in pts]
        spds    = [p[4] for p in pts]
        dirs    = [p[5] for p in pts]
        methods = [p[6] for p in pts]

        # ── actual trail (no legend entry — we label directly) ──
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode='lines',
            showlegend=False,
            line=dict(color=col, width=2.2),
            opacity=.9,
            customdata=list(zip(hdgs, spds, dirs, methods)),
            hovertemplate=(
                f'<b style="color:{col}">SHIP {sid:02d}</b><br>'
                'HDG: %{{customdata[0]:.1f}}°<br>'
                'SPD: %{{customdata[1]:.2f}}<br>'
                'DIR: %{{customdata[2]}}<br>'
                'MODEL: %{{customdata[3]}}<extra></extra>'
            ).replace('{{','%{').replace('}}','}')
        ))

        # ── start dot ──
        fig.add_trace(go.Scatter(
            x=[xs[0]], y=[ys[0]], mode='markers',
            showlegend=False,
            marker=dict(color=col, size=7, symbol='circle-open',
                        line=dict(width=1.5, color=col)),
            hoverinfo='skip'
        ))

        # ── current position: arrow marker ──
        fig.add_trace(go.Scatter(
            x=[xs[-1]], y=[ys[-1]], mode='markers',
            showlegend=False,
            marker=dict(color=col, size=11, symbol='arrow',
                        angle=hdgs[-1] if hdgs else 0,
                        line=dict(width=0)),
            hoverinfo='skip'
        ))

        # ── SHIP ID label directly on the plot at current position ──
        fig.add_annotation(
            x=xs[-1], y=ys[-1],
            text=f'<b>{sid:02d}</b>',
            showarrow=False,
            font=dict(family='Share Tech Mono', size=10, color=col),
            bgcolor='rgba(8,13,20,0.75)',
            bordercolor=col,
            borderwidth=1,
            borderpad=3,
            xanchor='left',
            yanchor='middle',
            xshift=14,
        )

        # ── predicted path (dashed, same color, no legend) ──
        pred = pred_traj.get(sid, [])
        if pred:
            pred_xs = [xs[-1]] + [p[0] for p in pred]
            pred_ys = [ys[-1]] + [p[1] for p in pred]
            # clip predicted points to plot bounds too
            pred_xs = [np.clip(v, xr[0], xr[1]) for v in pred_xs]
            pred_ys = [np.clip(v, yr[0], yr[1]) for v in pred_ys]
            fig.add_trace(go.Scatter(
                x=pred_xs, y=pred_ys,
                mode='lines+markers',
                showlegend=False,
                line=dict(color=col, width=1.3, dash='dot'),
                marker=dict(color=col, size=3, opacity=.45),
                opacity=.5,
                hovertemplate=f'<b>PREDICTED · Ship {sid:02d}</b><br>X: %{{x:.0f}}<br>Y: %{{y:.0f}}<extra></extra>'
            ))
            # arrowhead at end of prediction
            if len(pred_xs) > 1:
                fig.add_annotation(
                    x=pred_xs[-1], y=pred_ys[-1],
                    ax=pred_xs[-2], ay=pred_ys[-2],
                    xref='x', yref='y', axref='x', ayref='y',
                    showarrow=True,
                    arrowhead=2, arrowsize=1, arrowwidth=1.5,
                    arrowcolor=col,
                    opacity=.55,
                )

    # ── legend box (manual, bottom-left) ──
    fig.add_annotation(
        x=xr[0]+pad_x*0.3, y=yr[0]+pad_y*0.3,
        xref='x', yref='y',
        text='──  Actual path<br>····  LSTM prediction<br>○  Start  ▶  Current',
        showarrow=False,
        font=dict(family='Share Tech Mono', size=9, color='#4a6070'),
        bgcolor='rgba(8,13,20,0.8)',
        bordercolor='#162030',
        borderwidth=1,
        borderpad=6,
        align='left',
        xanchor='left', yanchor='bottom',
    )

    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(
            text='VESSEL TRAJECTORY MAP  ·  labels = ship ID  ·  dotted = LSTM predicted path',
            font=dict(size=10, color='#4a6070'), x=.01
        ),
        height=500,
        xaxis=dict(range=xr, gridcolor='#162030', linecolor='#162030',
                   tickfont=dict(size=9), zeroline=False, title='X (pixels)'),
        yaxis=dict(range=yr, gridcolor='#162030', linecolor='#162030',
                   tickfont=dict(size=9), zeroline=False, title='Y (pixels)'),
        showlegend=False,
    )
    fig.update_layout(**layout)
    return fig

def plot_timeline(results):
    frames = [f.get('frame',0) for f in results]
    counts = [f.get('ship_count',0) for f in results]
    # LSTM vs kinematic per frame
    lstm_counts, kin_counts = [], []
    for fr in results:
        lc = sum(1 for s in fr.get('ships',[]) if 'LSTM' in str(s.get('prediction_method','')).upper())
        kc = len(fr.get('ships',[])) - lc
        lstm_counts.append(lc)
        kin_counts.append(kc)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=frames, y=counts, name='Total Ships',
        mode='lines', fill='tozeroy',
        fillcolor='rgba(0,245,180,.06)',
        line=dict(color='#00f5b4', width=1.5),
        hovertemplate='Frame %{x}<br>Ships: %{y}<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=frames, y=lstm_counts, name='LSTM Active',
        mode='lines', line=dict(color='#1e90ff', width=1, dash='dot'),
        hovertemplate='Frame %{x}<br>LSTM ships: %{y}<extra></extra>'
    ))
    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(text='DETECTION TIMELINE  ·  blue = ships using LSTM prediction',
                   font=dict(size=10, color='#4a6070'), x=.01),
        height=240, xaxis_title='FRAME', yaxis_title='COUNT',
    )
    fig.update_layout(**layout)
    return fig

def plot_heading_rose(ship_rows):
    if not ship_rows: return None
    headings = [r['heading'] for r in ship_rows]
    fig = go.Figure(go.Barpolar(
        r=[1]*len(headings),
        theta=headings,
        width=[15]*len(headings),
        marker_color=[SHIP_COLORS[r['id'] % len(SHIP_COLORS)] for r in ship_rows],
        marker_line_color='#080d14',
        marker_line_width=1,
        opacity=.85,
    ))
    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(text='HEADING DISTRIBUTION', font=dict(size=10, color='#4a6070'), x=.01),
        height=260,
        polar=dict(
            bgcolor='rgba(8,13,20,1)',
            angularaxis=dict(tickfont=dict(size=8, color='#4a6070'),
                             gridcolor='#162030', linecolor='#162030',
                             direction='clockwise', rotation=90),
            radialaxis=dict(visible=False),
        ),
        showlegend=False,
    )
    fig.update_layout(**layout)
    return fig

def plot_speed_scatter(ship_rows):
    if not ship_rows: return None
    fig = go.Figure()
    for r in ship_rows:
        col = r['color']
        fig.add_trace(go.Bar(
            x=[f"#{r['id']:02d}"],
            y=[r['speed']],
            name=f"Ship {r['id']}",
            marker_color=col,
            marker_line_color='#050810',
            marker_line_width=1,
            width=.6,
            hovertemplate=f"Ship {r['id']}<br>Avg Speed: {r['speed']:.3f}<extra></extra>"
        ))
    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(text='AVG SPEED PER VESSEL', font=dict(size=10, color='#4a6070'), x=.01),
        height=200, showlegend=False, bargap=.3,
        xaxis_title='VESSEL', yaxis_title='SPEED (px/frame)',
    )
    fig.update_layout(**layout)
    return fig

def plot_lstm_vs_kin(ship_rows):
    if not ship_rows: return None
    ids = [f"#{r['id']:02d}" for r in ship_rows]
    lstm_pcts = [r['lstm_pct'] for r in ship_rows]
    kin_pcts  = [100-v for v in lstm_pcts]
    fig = go.Figure()
    fig.add_trace(go.Bar(name='LSTM', x=ids, y=lstm_pcts,
        marker_color='#00f5b4', marker_line_width=0, opacity=.85))
    fig.add_trace(go.Bar(name='Kinematic', x=ids, y=kin_pcts,
        marker_color='#1e2e42', marker_line_width=0, opacity=.85))
    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(text='LSTM vs KINEMATIC PREDICTION USAGE (%)',
                   font=dict(size=10,color='#4a6070'), x=.01),
        height=200, barmode='stack', showlegend=True,
        xaxis_title='VESSEL', yaxis_title='%',
    )
    fig.update_layout(**layout)
    return fig

def plot_confidence(ship_rows):
    if not ship_rows: return None
    fig = go.Figure()
    xs = [f"#{r['id']:02d}" for r in ship_rows]
    ys = [r['conf'] for r in ship_rows]
    cols = [r['color'] for r in ship_rows]
    fig.add_trace(go.Bar(x=xs, y=ys, marker_color=cols,
        marker_line_color='#050810', marker_line_width=1, opacity=.85,
        hovertemplate='Ship %{x}<br>Conf: %{y:.3f}<extra></extra>'))
    fig.add_shape(type='line', x0=-.5, x1=len(xs)-.5, y0=.5, y1=.5,
        line=dict(color='#ffb800', width=1, dash='dot'))
    layout = dict(PLOTLY_BASE)
    layout.update(
        title=dict(text='DETECTION CONFIDENCE BY VESSEL  ·  yellow = 0.5 threshold',
                   font=dict(size=10,color='#4a6070'), x=.01),
        height=200, showlegend=False, yaxis_range=[0,1],
        xaxis_title='VESSEL', yaxis_title='CONFIDENCE',
    )
    fig.update_layout(**layout)
    return fig

# ══════════════════════════════════════════════════════════════════════════════
# UI RENDER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════
def render_header():
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    st.markdown(f"""
    <div class="marvis-hdr">
      <div class="hdr-brand">
        <div class="hdr-logo">MARVIS</div>
        <div class="hdr-tagline">MARITIME VISUAL SURVEILLANCE INTELLIGENCE · SINGAPORE STRAIT</div>
      </div>
      <div class="hdr-right">
        <span class="live-badge"><span class="live-dot"></span>SYSTEM ACTIVE</span>
        <span class="hdr-time">{now} UTC+8</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

def render_metrics(m):
    lstm_pct = m['lstm_frames'] / max(m['lstm_frames']+m['kin_frames'],1)*100
    st.markdown(f"""
    <div class="mrow">
      <div class="mcard">
        <div class="mcard-ico">🛳️</div>
        <div class="mcard-val">{m['total']:,}</div>
        <div class="mcard-lbl">Total Detections</div>
        <div class="mcard-sub">Peak: {m['peak']} / frame</div>
      </div>
      <div class="mcard blue">
        <div class="mcard-ico">🔵</div>
        <div class="mcard-val">{m['unique']}</div>
        <div class="mcard-lbl">Unique Vessels</div>
        <div class="mcard-sub">Across {m['frames']:,} frames</div>
      </div>
      <div class="mcard amber">
        <div class="mcard-ico">📡</div>
        <div class="mcard-val">{m['avg']:.1f}</div>
        <div class="mcard-lbl">Avg Ships / Frame</div>
        <div class="mcard-sub">{m['frames']:,} frames processed</div>
      </div>
      <div class="mcard red">
        <div class="mcard-ico">⚠️</div>
        <div class="mcard-val">{m['alerts']}</div>
        <div class="mcard-lbl">Collision Alerts</div>
        <div class="mcard-sub">CPA risk events</div>
      </div>
      <div class="mcard purple">
        <div class="mcard-ico">🧠</div>
        <div class="mcard-val">{lstm_pct:.0f}%</div>
        <div class="mcard-lbl">LSTM Coverage</div>
        <div class="mcard-sub">vs kinematic fallback</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if m['frames'] == 0:
        st.markdown(
            '<div class="note-box">LSTM coverage is unavailable until the pipeline starts producing frames.</div>',
            unsafe_allow_html=True
        )
    elif m['lstm_frames'] == 0:
        warmup_text = (
            'LSTM is warming up — the first frames may use kinematic fallback. '
            'Coverage will appear once the sequence model stabilizes.'
            if m['frames'] < 20 else
            'No LSTM predictions detected yet; verify the predictor pipeline.'
        )
        st.markdown(f'<div class="note-box">{warmup_text}</div>', unsafe_allow_html=True)

def render_alerts(alerts):
    if not alerts:
        st.markdown("""
        <div class="sec-lbl">Collision Risk Monitor</div>
        <div style="font-family:var(--mono);font-size:.7rem;color:var(--textd);
             padding:.6rem .8rem;background:var(--bg1);border:1px solid var(--border)">
          ✓ &nbsp; NO ACTIVE COLLISION ALERTS
        </div>""", unsafe_allow_html=True)
        return

    st.markdown('<div class="sec-lbl">Collision Risk Monitor</div>', unsafe_allow_html=True)
    for a in alerts:
        lvl   = a.get('risk_level','low').lower()
        s1,s2 = a.get('ship1_id','?'), a.get('ship2_id','?')
        cpa   = a.get('cpa_distance', 0)
        ttc   = a.get('time_to_cpa', 0)
        flash = 'aflash' if lvl == 'critical' else ''
        st.markdown(f"""
        <div class="alert-item {lvl} {flash}">
          <span class="abadge {lvl}">{lvl.upper()}</span>
          <span class="aships">SHIP {s1:02d} ↔ SHIP {s2:02d}</span>
          <span style="font-size:.7rem;color:var(--textd)">
            Closest Point of Approach
          </span>
          <span class="ameta">
            CPA &nbsp;<b style="color:#fff">{cpa:.1f}m</b>
            &nbsp;·&nbsp;
            TTC &nbsp;<b style="color:#fff">{ttc:.1f}s</b>
          </span>
        </div>
        """, unsafe_allow_html=True)

def render_vessel_table(ship_rows):
    st.markdown('<div class="sec-lbl">Vessel Registry — Live Tracking Data</div>', unsafe_allow_html=True)
    if not ship_rows:
        st.markdown('<div style="font-family:var(--mono);font-size:.7rem;color:var(--textd);padding:.6rem">NO VESSEL DATA</div>', unsafe_allow_html=True)
        return

    rows_html = ""
    for r in ship_rows[:15]:
        col = r['color']
        conf_w = int(r['conf']*52)
        m = str(r['last_method']).upper()
        if 'LSTM' in m and 'PARTIAL' not in m:
            mcls, mlbl = 'method-lstm', 'LSTM'
        elif 'PARTIAL' in m:
            mcls, mlbl = 'method-partial', 'LSTM-P'
        else:
            mcls, mlbl = 'method-kin', 'KIN'

        dir_arrow = DIR_ARROWS.get(r['direction'], '·')
        dir_label = DIR_LABELS.get(r['direction'], r['direction'])
        gps_str = f"{r['last_gps'][0]:.5f}N  {r['last_gps'][1]:.5f}E" if r['last_gps'] else '—'
        pos_str = f"{r['last_pos'][0]:.0f}, {r['last_pos'][1]:.0f}"

        rows_html += f"""
        <tr>
          <td><span class="vid" style="color:{col};border-color:{col}">{r['id']:02d}</span></td>
          <td>{r['frames']}</td>
          <td>
            <div class="cbar-wrap">
              <div class="cbar-bg"><div class="cbar-fill" style="width:{conf_w}px;background:{col}"></div></div>
              <span>{r['conf']:.3f}</span>
            </div>
          </td>
          <td>{r['speed']:.3f}</td>
          <td>{r['heading']:.1f}°</td>
          <td><span style="font-size:.9rem">{dir_arrow}</span> <span style="letter-spacing:.06em">{dir_label}</span></td>
          <td><span class="pred-steps">{r['pred_steps']:.0f}</span></td>
          <td><span class="{mcls}">{mlbl}</span></td>
          <td style="color:var(--textd);font-size:.62rem">{pos_str}</td>
          <td style="color:var(--textd);font-size:.62rem">{gps_str}</td>
          <td><span class="status-ok">● TRACKING</span></td>
        </tr>"""

    st.markdown(f"""
    <div style="overflow-x:auto">
    <table class="vtbl">
      <thead><tr>
        <th>ID</th><th>FRAMES</th><th>CONFIDENCE</th>
        <th>SPEED</th><th>HEADING</th><th>DIRECTION</th>
        <th>PRED STEPS</th><th>MODEL</th>
        <th>PIXEL POS</th><th>GPS</th><th>STATUS</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    </div>""", unsafe_allow_html=True)

def render_sidebar():
    st.sidebar.markdown('<div class="sb-title">⬡ MARVIS CONFIG</div>', unsafe_allow_html=True)
    json_path = st.sidebar.text_input("Results JSON Path", value="outputs/results.json")
    st.sidebar.markdown(f"<div class='sb-info' style='font-size:.78rem;line-height:1.4'>{json_path_info(json_path)}</div>", unsafe_allow_html=True)

    st.sidebar.markdown('<div class="sb-section">Camera Parameters</div>', unsafe_allow_html=True)
    lat = st.sidebar.number_input("Latitude", value=1.2800, format="%.4f")
    lon = st.sidebar.number_input("Longitude", value=103.8500, format="%.4f")

    st.sidebar.markdown('<div class="sb-section">Alert Thresholds (metres)</div>', unsafe_allow_html=True)
    st.sidebar.slider("🔴 Critical CPA", 0, 200, 50)
    st.sidebar.slider("🟠 High CPA", 0, 400, 100)
    st.sidebar.slider("🟡 Medium CPA", 0, 600, 200)

    st.sidebar.markdown('<div class="sb-section">System Info</div>', unsafe_allow_html=True)
    st.sidebar.markdown("""
    <div class="sb-info">
      DETECTOR&nbsp;&nbsp; <span>YOLOv8m</span><br>
      TRACKER&nbsp;&nbsp;&nbsp; <span>DeepOCSORT</span><br>
      PREDICTOR&nbsp; <span>Seq2Seq LSTM</span><br>
      ENCODER&nbsp;&nbsp;&nbsp; <span>Bidirectional</span><br>
      ATTENTION&nbsp; <span>✓ Enabled</span><br>
      DATASET&nbsp;&nbsp;&nbsp; <span>SMD v1.0</span><br>
      COLLISION&nbsp; <span>CPA Algorithm</span><br>
      DEVICE&nbsp;&nbsp;&nbsp;&nbsp; <span>CPU / CUDA</span>
    </div>""", unsafe_allow_html=True)

    st.sidebar.markdown('<div class="sb-section">Pipeline</div>', unsafe_allow_html=True)
    st.sidebar.markdown("""
    <div class="sb-info" style="line-height:2.2">
      1 · <span>YOLOv8 Detection</span><br>
      2 · <span>DeepOCSORT Tracking</span><br>
      3 · <span>LSTM Prediction</span><br>
      4 · <span>CPA Collision Check</span><br>
      5 · <span>GPS Georeferencing</span><br>
      6 · <span>Dashboard Viz</span>
    </div>""", unsafe_allow_html=True)

    return json_path

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    json_path = render_sidebar()
    results = load_results(json_path)[-RECENT_FRAME_WINDOW:]
    metrics   = parse_metrics(results)

    st.caption(
    f"Dashboard refresh: {time.strftime('%H:%M:%S')} | "
    f"Frames: {metrics['frames']}"
    )
    
    ship_rows = parse_ships(results)
    alerts    = parse_alerts(results)

    render_header()
    render_metrics(metrics)
    render_alerts(alerts)

    if not results:
        st.markdown("""
        <div style="background:var(--bg1);border:1px solid var(--border);
             border-left:3px solid var(--red);padding:1.4rem 1.6rem;margin:1rem 0">
          <div style="font-family:var(--mono);color:var(--red);font-size:.75rem;margin-bottom:.5rem">
            ⚠ &nbsp; NO RESULTS LOADED
          </div>
          <div style="font-family:var(--mono);font-size:.68rem;color:var(--textd)">
            Run the detection pipeline first:<br>
            <span style="color:var(--teal);margin-top:.4rem;display:block">
              python app.py input.avi outputs/result.mp4 outputs/results.json
            </span>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── TABS ──────────────────────────────────────────────────────────────────
    t0,t1,t2,t3 = st.tabs([
        "  📍  TRAJECTORY MAP  ",
        "  🧠  PREDICTION ANALYSIS  ",
        "  🛳️  VESSEL REGISTRY  ",
        "  📊  TIMELINE & STATS  ",
    ])

    if not results:
        st.stop()

    # ── TAB 0: TRAJECTORY MAP ─────────────────────────────────────────────────
    with t0:
        cola, colb = st.columns([3, 1])
        with cola:
            st.plotly_chart(plot_trajectories(results),
                            use_container_width=True,
                            config=dict(displayModeBar=False))
        with colb:
            st.markdown('<div class="sec-lbl">Active Vessels</div>', unsafe_allow_html=True)
            for r in ship_rows[:8]:
                col_hex = r['color']
                arrow = DIR_ARROWS.get(r['direction'], '·')
                dlabel = DIR_LABELS.get(r['direction'], r['direction'])
                gps_line = (f"{r['last_gps'][0]:.4f}N" if r['last_gps'] else
                            f"{r['last_pos'][0]:.0f}px")
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:8px;
                     padding:.4rem .6rem;margin-bottom:4px;
                     background:var(--bg2);border:1px solid var(--border);
                     border-left:2px solid {col_hex}">
                  <span style="font-family:var(--mono);font-size:.62rem;
                        color:{col_hex};min-width:22px">{r['id']:02d}</span>
                  <span style="font-size:.85rem">{arrow}</span>
                  <span style="font-family:var(--mono);font-size:.58rem;color:var(--teal);min-width:24px">{dlabel}</span>
                  <span style="font-family:var(--mono);font-size:.58rem;
                        color:var(--textd);flex:1">{gps_line}</span>
                  <span style="font-family:var(--mono);font-size:.56rem;
                        color:var(--textd)">{r['speed']:.2f}</span>
                </div>
                """, unsafe_allow_html=True)

            st.markdown('<div style="margin-top:.8rem"></div>', unsafe_allow_html=True)
            st.markdown('<div class="sec-lbl">Map Legend</div>', unsafe_allow_html=True)
            st.markdown("""
            <div style="font-family:var(--mono);font-size:.6rem;color:var(--textd);
                 line-height:2.2;background:var(--bg2);border:1px solid var(--border);
                 padding:.6rem .75rem">
              ── &nbsp; Actual trajectory<br>
              ·· &nbsp; LSTM prediction<br>
              ○  &nbsp; Track start<br>
              ▶  &nbsp; Current heading<br>
              ↗  &nbsp; Predicted direction
            </div>""", unsafe_allow_html=True)

    # ── TAB 1: PREDICTION ANALYSIS ────────────────────────────────────────────
    with t1:
        st.markdown('<div class="sec-lbl" style="margin-top:.8rem">LSTM vs Kinematic Prediction Usage per Vessel</div>', unsafe_allow_html=True)
        fig_lk = plot_lstm_vs_kin(ship_rows)
        if fig_lk:
            st.plotly_chart(fig_lk, use_container_width=True, config=dict(displayModeBar=False))

        c1, c2 = st.columns(2)
        with c1:
            fig_hr = plot_heading_rose(ship_rows)
            if fig_hr:
                st.plotly_chart(fig_hr, use_container_width=True, config=dict(displayModeBar=False))
        with c2:
            fig_sp = plot_speed_scatter(ship_rows)
            if fig_sp:
                st.plotly_chart(fig_sp, use_container_width=True, config=dict(displayModeBar=False))

        # Prediction method summary
        st.markdown('<div class="sec-lbl" style="margin-top:.4rem">Prediction Method Summary</div>', unsafe_allow_html=True)
        lstm_n    = sum(1 for r in ship_rows if 'LSTM' in str(r['last_method']).upper() and 'PARTIAL' not in str(r['last_method']).upper())
        partial_n = sum(1 for r in ship_rows if 'PARTIAL' in str(r['last_method']).upper())
        kin_n     = len(ship_rows) - lstm_n - partial_n
        c1,c2,c3 = st.columns(3)
        for col_st, label, val, color, desc in [
            (c1, 'FULL LSTM', lstm_n, '#00f5b4', f'≥50 frames history · seq2seq + attention'),
            (c2, 'PARTIAL LSTM', partial_n, '#1e90ff', f'10–49 frames · zero-padded input'),
            (c3, 'KINEMATIC', kin_n, '#4a6070', f'<10 frames · linear regression fallback'),
        ]:
            with col_st:
                st.markdown(f"""
                <div style="background:var(--bg1);border:1px solid var(--border);
                     border-top:2px solid {color};padding:.9rem 1rem">
                  <div style="font-family:var(--mono);font-size:.58rem;
                       letter-spacing:.12em;color:var(--textd)">{label}</div>
                  <div style="font-family:var(--head);font-size:2rem;font-weight:700;
                       color:#fff;line-height:1.1;margin:.2rem 0">{val}</div>
                  <div style="font-size:.65rem;color:var(--textd)">{desc}</div>
                </div>
                """, unsafe_allow_html=True)

    # ── TAB 2: VESSEL REGISTRY ────────────────────────────────────────────────
    with t2:
        st.markdown('<div style="margin-top:.6rem"></div>', unsafe_allow_html=True)
        render_vessel_table(ship_rows)
        st.markdown('<div style="margin-top:.8rem"></div>', unsafe_allow_html=True)
        fig_conf = plot_confidence(ship_rows)
        if fig_conf:
            st.plotly_chart(fig_conf, use_container_width=True, config=dict(displayModeBar=False))

    # ── TAB 3: TIMELINE & STATS ───────────────────────────────────────────────
    with t3:
        st.markdown('<div style="margin-top:.6rem"></div>', unsafe_allow_html=True)
        st.plotly_chart(plot_timeline(results), use_container_width=True,
                        config=dict(displayModeBar=False))

        ca, cb, cc, cd = st.columns(4)
        stat_cards = [
            (ca, 'PEAK VESSELS', str(metrics['peak']), '#00f5b4', 'max in single frame'),
            (cb, 'TOTAL FRAMES', f"{metrics['frames']:,}", '#1e90ff', 'processed by pipeline'),
            (cc, 'AVG CONFIDENCE', f"{np.mean([r['conf'] for r in ship_rows]):.3f}" if ship_rows else '—', '#ffb800', 'across all detections'),
            (cd, 'AVG SPEED', f"{np.mean([r['speed'] for r in ship_rows]):.3f}" if ship_rows else '—', '#9f6eff', 'pixels per frame'),
        ]
        for col_st, lbl, val, color, sub in stat_cards:
            with col_st:
                st.markdown(f"""
                <div style="background:var(--bg1);border:1px solid var(--border);
                     border-top:2px solid {color};padding:.8rem 1rem">
                  <div style="font-family:var(--mono);font-size:.56rem;
                       letter-spacing:.12em;color:var(--textd)">{lbl}</div>
                  <div style="font-family:var(--head);font-size:1.7rem;font-weight:700;
                       color:#fff;line-height:1.1;margin:.2rem 0">{val}</div>
                  <div style="font-size:.65rem;color:var(--textd)">{sub}</div>
                </div>
                """, unsafe_allow_html=True)

        # Class distribution if available
        classes = defaultdict(int)
        for fr in results:
            for s in fr.get('ships',[]):
                c = s.get('class','vessel')
                classes[c] += 1
        if classes:
            st.markdown('<div class="sec-lbl" style="margin-top:1rem">Vessel Class Distribution</div>', unsafe_allow_html=True)
            fig_cls = go.Figure(data=[go.Pie(
                labels=list(classes.keys()),
                values=list(classes.values()),
                hole=.55,
                marker=dict(colors=SHIP_COLORS[:len(classes)],
                            line=dict(color='#050810', width=2)),
                textfont=dict(family='Share Tech Mono', size=9),
            )])
            layout = dict(PLOTLY_BASE)
            layout.update(height=280, showlegend=True,
                annotations=[dict(text='CLASS<br>SPLIT', x=.5, y=.5,
                    font=dict(size=8,color='#4a6070'), showarrow=False)])
            fig_cls.update_layout(**layout)
            st.plotly_chart(fig_cls, use_container_width=True, config=dict(displayModeBar=False))





if __name__ == "__main__":
    main()

