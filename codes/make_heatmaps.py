r"""
Cuisine hex heatmaps and gap scores for NYC (H3 resolution 9, ~0.1 km2, ~4-6 blocks per hex).

Usage:
    python make_heatmaps.py
    (reads outputs\restaurants_labeled.csv; pass a path to override)

Outputs (in outputs\):
    hex_cuisine_scores.csv    one row per (hex, cuisine):
                                count                 restaurants of this cuisine in the hex
                                density_smoothed      distance-decayed count, this cuisine only
                                competition_weighted  smoothed + related cuisines via the matrix
                                local_competition     matrix-weighted restaurants per hex right here
                                                      (own hex + 1 ring, ~400 m)
                                area_competition      matrix-weighted restaurants per hex in the
                                                      surrounding area (rings 2-4, ~0.8-1.6 km)
                                gap_score             0-1, high where the area is busy for this
                                                      cuisine but this spot is not
                                hex_has_restaurants   False for hexes with no restaurant at all
                                                      (often water or parks): filter these out
                                                      before ranking gaps
    cuisine_heatmaps.html     interactive map: same cuisine / weighted competition / gaps

Gap logic (assumption: demand is where competition already is):
    demand     = area_competition, scaled 0-1 (95th percentile = 1)
    saturation = local_competition / area_competition
    gap_score  = demand x (1 - saturation), clipped to 0-1
    - Empty areas with no competition nearby  -> demand ~0    -> gap ~0
    - The middle of a dense cluster           -> saturation ~1 -> gap ~0
    - A quiet band between dense clusters     -> high demand, low saturation -> gap high
"""
import json
import sys

import h3
import numpy as np
import pandas as pd

from cuisine_matrix import build_matrix
from label_cuisines import CUISINES_50
from paths import OUTPUTS, ensure_dirs, find

H3_RES = 9
# Display smoothing by ring distance: own hex, 1 ring out (~400 m), 2 rings (~800 m)
RING_WEIGHTS = {0: 1.0, 1: 0.5, 2: 0.15}
# Gap score: "here" = own hex + ring 1 (ring 1 weighted), "area" = rings 2..4
LOCAL_RING1_WEIGHT = 0.25
AREA_RINGS = (2, 3, 4)
DEMAND_PERCENTILE = 95
NYC_BBOX = dict(lat_min=40.49, lat_max=40.92, lng_min=-74.27, lng_max=-73.68)


def load(path):
    df = pd.read_csv(path)
    b = NYC_BBOX
    df = df[
        df["active_establishment"].astype(str).str.lower().eq("true")
        & df["latitude"].between(b["lat_min"], b["lat_max"])
        & df["longitude"].between(b["lng_min"], b["lng_max"])
        & df["cuisine_50"].isin(CUISINES_50)
    ].copy()
    df["hex"] = [h3.latlng_to_cell(la, lo, H3_RES)
                 for la, lo in zip(df["latitude"], df["longitude"])]
    return df


def count_matrix(df):
    """C: hexes x 50 cuisines, raw restaurant counts."""
    return (df.groupby(["hex", "cuisine_50"]).size()
              .unstack(fill_value=0)
              .reindex(columns=CUISINES_50, fill_value=0))


def spread(c, ring_weights, universe):
    """Add each hex's row to its rings with the given weights."""
    idx = {h: i for i, h in enumerate(universe)}
    out = np.zeros((len(universe), c.shape[1]))
    vals = c.values.astype(float)
    for row, h in enumerate(c.index):
        for d, w in ring_weights.items():
            for n in ([h] if d == 0 else h3.grid_ring(h, d)):
                out[idx[n]] += w * vals[row]
    return pd.DataFrame(out, index=universe, columns=c.columns)


def gap_scores(c, m, universe):
    """local, area and gap per (hex, cuisine), all matrix-weighted."""
    mm = m.loc[CUISINES_50, CUISINES_50].values
    w = pd.DataFrame(c.values @ mm, index=c.index, columns=CUISINES_50)  # raw, matrix-weighted
    local = spread(w, {0: 1.0, 1: LOCAL_RING1_WEIGHT}, universe) / (1 + 6 * LOCAL_RING1_WEIGHT)
    n_area_hexes = sum(6 * k for k in AREA_RINGS)
    area = spread(w, {k: 1.0 for k in AREA_RINGS}, universe) / n_area_hexes

    cap = area.where(area > 0).quantile(DEMAND_PERCENTILE / 100).replace(0, np.nan)
    demand = (area / cap).clip(0, 1).fillna(0)
    saturation = (local / area.where(area > 0)).fillna(1.0)
    gap = (demand * (1 - saturation).clip(0, 1)).clip(0, 1)
    return local, area, gap


def to_long(c, s, e, local, area, gap):
    u = local.index
    cols = {
        "count": c.reindex(u, fill_value=0),
        "density_smoothed": s.reindex(u, fill_value=0).round(3),
        "competition_weighted": e.reindex(u, fill_value=0).round(3),
        "local_competition": local.round(3),
        "area_competition": area.round(3),
        "gap_score": gap.round(3),
    }
    out = pd.DataFrame({"hex": np.repeat(u.values, len(CUISINES_50)),
                        "cuisine": np.tile(CUISINES_50, len(u))})
    for k, v in cols.items():
        out[k] = v.values.ravel()
    out = out[(out[list(cols)].drop(columns="count") > 0).any(axis=1)]
    # Hexes with no restaurant of any kind are often water, parks or highways.
    # Filter on this before ranking gaps (recommend.py scores real listings, so it doesn't need to).
    out["hex_has_restaurants"] = out["hex"].isin(set(c.index))
    lat_lng = {h: h3.cell_to_latlng(h) for h in out["hex"].unique()}
    out["lat"] = out["hex"].map(lambda h: round(lat_lng[h][0], 6))
    out["lng"] = out["hex"].map(lambda h: round(lat_lng[h][1], 6))
    return out


def build_html(c, s, e, local, area, gap, n_by_cuisine, path):
    occupied = set(c.index)  # gaps are only drawn where some restaurant already exists
    u = list(local.index)
    S, E = s.reindex(u, fill_value=0).values, e.reindex(u, fill_value=0).values
    R = c.reindex(u, fill_value=0).values
    G, LO, AR = gap.values, local.values, area.values
    occ = np.array([h in occupied for h in u])

    used, layers = {}, {}
    for j, cu in enumerate(CUISINES_50):
        keep = np.nonzero((S[:, j] > 0) | (E[:, j] > 0) | ((G[:, j] > 0) & occ))[0]
        rows = []
        for i in keep:
            gi = used.setdefault(u[i], len(used))
            rows.append([gi, round(float(S[i, j]), 2), round(float(E[i, j]), 2), int(R[i, j]),
                         round(float(G[i, j]) if occ[i] else 0.0, 3),
                         round(float(LO[i, j]), 2), round(float(AR[i, j]), 2)])
        layers[cu] = rows
    geom = [None] * len(used)
    for h, gi in used.items():
        geom[gi] = [[round(la, 5), round(lo, 5)] for la, lo in h3.cell_to_boundary(h)]
    data = {"geom": geom, "layers": layers, "cuisines": CUISINES_50,
            "counts": {k: int(v) for k, v in n_by_cuisine.items()}}
    with open(path, "w") as f:
        f.write(HTML_TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":"))))


HTML_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NYC Cuisine Hex Map</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  html,body{height:100%;margin:0;font:14px/1.4 system-ui,sans-serif;color:#1d2433}
  #map{position:absolute;inset:0}
  .panel{position:absolute;top:12px;left:12px;z-index:1000;background:#fff;padding:12px 14px;
         border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.18);width:280px}
  .panel h1{font-size:15px;margin:0 0 8px}
  .panel label{display:block;font-size:12px;color:#5b6475;margin:8px 0 3px}
  select{width:100%;padding:5px;font-size:14px}
  .seg{display:flex;gap:4px;margin-top:2px}
  .seg button{flex:1;padding:6px 2px;border:1px solid #c8cdd8;background:#f4f6fa;border-radius:5px;cursor:pointer;font-size:12px}
  .seg button.on{background:#1d4e89;color:#fff;border-color:#1d4e89}
  .legend{margin-top:10px;font-size:12px}
  .bar{height:10px;border-radius:3px}
  .ticks{display:flex;justify-content:space-between;color:#5b6475;font-variant-numeric:tabular-nums}
  .note{font-size:11px;color:#5b6475;margin-top:8px}
</style></head><body>
<div id="map"></div>
<div class="panel">
  <h1>NYC cuisine heatmap</h1>
  <label for="cu">Cuisine</label>
  <select id="cu"></select>
  <label>Show</label>
  <div class="seg">
    <button data-m="1" class="on">Same cuisine</button>
    <button data-m="2">Competition</button>
    <button data-m="4">Gaps</button>
  </div>
  <label for="op">Hex opacity</label>
  <input id="op" type="range" min="0.1" max="0.9" step="0.05" value="0.55" style="width:100%">
  <div class="legend"><div class="bar" id="bar"></div>
    <div class="ticks"><span>0</span><span id="mx"></span></div></div>
  <div class="note" id="note"></div>
</div>
<script>
const D = __DATA__;
const map = L.map('map',{preferCanvas:true}).setView([40.72,-73.95],11);
// Basemaps that need no API key
const esri = p => `https://server.arcgisonline.com/ArcGIS/rest/services/${p}/MapServer/tile/{z}/{y}/{x}`;
const basemaps = {
  'Streets': L.tileLayer(esri('World_Street_Map'), {attribution:'Tiles &copy; Esri', maxZoom:19}),
  'Light gray': L.tileLayer(esri('Canvas/World_Light_Gray_Base'), {attribution:'Tiles &copy; Esri', maxZoom:16}),
  'OpenStreetMap': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      {attribution:'&copy; OpenStreetMap contributors', maxZoom:19}),
  'Satellite': L.tileLayer(esri('World_Imagery'), {attribution:'Tiles &copy; Esri', maxZoom:19}),
};
basemaps['Streets'].addTo(map);
// Place and street names drawn above the hexes
map.createPane('labels'); map.getPane('labels').style.zIndex = 650; map.getPane('labels').style.pointerEvents = 'none';
const labels = L.tileLayer(esri('Canvas/World_Light_Gray_Reference'), {pane:'labels', maxZoom:16});
L.control.layers(basemaps, {'Labels on top': labels}, {position:'topright', collapsed:false}).addTo(map);

const RAMPS = {
  heat: ['#fff5eb','#fdd0a2','#fd8d3c','#d94801','#7f2704'],
  gap:  ['#f7fcf5','#c7e9c0','#74c476','#238b45','#00441b'],
};
function color(t, ramp){t=Math.max(0,Math.min(1,t));const x=t*(ramp.length-1),i=Math.floor(x),f=x-i;
  if(i>=ramp.length-1)return ramp[ramp.length-1];
  const a=ramp[i],b=ramp[i+1],p=n=>parseInt(n,16);
  const c=[1,3,5].map(k=>Math.round(p(a.substr(k,2))*(1-f)+p(b.substr(k,2))*f));
  return '#'+c.map(v=>v.toString(16).padStart(2,'0')).join('');}
const sel=document.getElementById('cu'), op=document.getElementById('op');
D.cuisines.slice().sort((a,b)=>D.counts[b]-D.counts[a]).forEach(c=>{
  const o=document.createElement('option');o.value=c;o.textContent=`${c} (${D.counts[c]||0})`;sel.appendChild(o);});
const NOTES = {
  1:'Distance-decayed count of this cuisine only (own hex 1.0, next ring 0.5, two rings 0.15).',
  2:'Same density plus related cuisines, discounted by the cuisine matrix.',
  4:'Green = the surrounding 0.8–1.6 km is busy for this cuisine, but this spot is not. Empty areas and dense cores both score low.'};
let mode=1, layer=null;
function draw(){
  if(layer) map.removeLayer(layer);
  const rows=D.layers[sel.value]||[], ramp = mode===4 ? RAMPS.gap : RAMPS.heat;
  const vals=rows.map(r=>r[mode]).filter(v=>v>0).sort((a,b)=>a-b);
  const cap = mode===4 ? 1 : (vals.length ? vals[Math.floor(vals.length*0.98)]||vals[vals.length-1] : 1);
  layer=L.layerGroup();
  rows.forEach(r=>{ if(r[mode]<=0) return;
    L.polygon(D.geom[r[0]],{weight:0.5,color: mode===4?'#00441b':'#7f2704',opacity:0.35,
              fillColor:color(r[mode]/cap, ramp),fillOpacity:+op.value})
     .bindTooltip(`<b>${sel.value}</b><br>Restaurants in hex: ${r[3]}<br>Smoothed density: ${r[1]}`+
                  `<br>Weighted competition: ${r[2]}<br>Here (per hex): ${r[5]} &middot; Area (per hex): ${r[6]}`+
                  `<br><b>Gap score: ${r[4]}</b>`)
     .addTo(layer);});
  layer.addTo(map);
  document.getElementById('bar').style.background = `linear-gradient(90deg,${ramp.join(',')})`;
  document.getElementById('mx').textContent = mode===4 ? '1.0' : cap.toFixed(1)+'+';
  document.getElementById('note').textContent = NOTES[mode];
}
document.querySelectorAll('.seg button').forEach(b=>b.onclick=()=>{
  mode=+b.dataset.m; document.querySelectorAll('.seg button').forEach(x=>x.classList.toggle('on',x===b)); draw();});
sel.onchange=draw; op.oninput=draw;
draw();
</script></body></html>"""


def main(path):
    df = load(path)
    m = build_matrix()
    c = count_matrix(df)

    universe = set()
    for h in c.index:
        universe.update(h3.grid_disk(h, max(AREA_RINGS)))
    universe = sorted(universe)

    s = spread(c, RING_WEIGHTS, universe)
    e = pd.DataFrame(s.values @ m.loc[CUISINES_50, CUISINES_50].values,
                     index=s.index, columns=CUISINES_50)
    local, area, gap = gap_scores(c, m, universe)

    ensure_dirs()
    to_long(c, s, e, local, area, gap).to_csv(OUTPUTS / "hex_cuisine_scores.csv", index=False)
    build_html(c, s, e, local, area, gap, df["cuisine_50"].value_counts(),
               OUTPUTS / "cuisine_heatmaps.html")
    print(f"{len(df):,} restaurants -> {c.shape[0]:,} occupied hexes, "
          f"{len(universe):,} hexes scored (res {H3_RES})")
    print(f"Saved hex_cuisine_scores.csv and cuisine_heatmaps.html to {OUTPUTS}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else find("restaurants_labeled.csv"))
