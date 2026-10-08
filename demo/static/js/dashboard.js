let dashboard = null;
let selectedId = null;
let activeLayer = "opportunity";
let activeView = "discover";
let requestId = 0;
let locationMap = null;
let mapMarkers = [];
let mapPopup = null;
let mapDataset = "";
let mapViewRequestId = 0;
let hovered3DFeatureId = "";
let pinned3DFeature = false;
let activeBasemap = "streets";
const mapLimits = {
  streets: {bounds: [[-74.55, 40.43], [-73.37, 41.02]], minZoom: 10},
  aerial: {bounds: [[-74.20, 40.49], [-73.60, 41.00]], minZoom: 9.7},
  buildings3d: {bounds: [[-74.20, 40.49], [-73.60, 41.00]], minZoom: 9.7},
};
const systemTheme = matchMedia("(prefers-color-scheme: dark)");
let dashboardThemeChoice = ["light", "dark"].includes(localStorage.getItem("groundwork-theme")) ? localStorage.getItem("groundwork-theme") : "system";
let currentTheme = dashboardThemeChoice === "system" ? (systemTheme.matches ? "dark" : "light") : dashboardThemeChoice;
let savedIds = [];
let savedKey = "";
const competitionCache = new Map();
const catchmentCache = new Map();
let competitionRequest = 0;
let propertyView = "all";
const hexCache = new Map();
let hexRequestId = 0;
let hoveredHexId = null;
const menuSections = ["Starters", "Mains", "Sides", "Desserts", "Drinks"];
let menuCatalog = null;
let menuCatalogKey = "";
let menuRequestId = 0;
let menuSavedKey = "";
let savedMenu = [];
let menuView = "plan";

const VECTOR_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

async function buildingMapStyle() {
  const response = await fetch(VECTOR_STYLE_URL, {mode: "cors"});
  if (!response.ok) throw new Error("3D street style unavailable");
  const style = await response.json();
  if (style.version !== 8 || style.sources?.openmaptiles?.type !== "vector" ||
      !style.layers?.some(layer => layer.source === "openmaptiles" && layer["source-layer"] === "building")) {
    throw new Error("3D building geometry unavailable");
  }
  style.layers = style.layers.filter(layer => layer.type !== "raster");
  Object.keys(style.sources).forEach(id => {if (style.sources[id].type === "raster") delete style.sources[id];});
  const firstLabel = style.layers.findIndex(layer => layer.type === "symbol");
  style.layers.splice(firstLabel < 0 ? style.layers.length : firstLabel, 0, {
    id: "nyc-buildings-3d", type: "fill-extrusion", source: "openmaptiles", "source-layer": "building", minzoom: 14.5,
    filter: ["all", [">", ["to-number", ["get", "render_height"], 0], 0], ["!=", ["get", "hide_3d"], true]],
    paint: {"fill-extrusion-color": "#7fa8d3", "fill-extrusion-height": ["to-number", ["get", "render_height"], 0],
      "fill-extrusion-base": ["to-number", ["get", "render_min_height"], 0], "fill-extrusion-opacity": 0.76},
  });
  style.layers.splice(firstLabel < 0 ? style.layers.length : firstLabel + 1, 0, {
    id: "nyc-pois-3d", type: "circle", source: "openmaptiles", "source-layer": "poi", minzoom: 16,
    filter: ["has", "name"], paint: {"circle-color": "#28b9b6", "circle-opacity": 0.82,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 16, 2.5, 18, 4],
      "circle-stroke-color": "#102a33", "circle-stroke-width": 1},
  });
  return style;
}

function mapStyle(view) {
  if (view === "aerial") return {
    version: 8,
    sources: {imagery: {type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 19, attribution: 'Imagery &copy; <a href="https://www.esri.com/">Esri</a> and its data providers'}},
    layers: [{id: "imagery", type: "raster", source: "imagery"}],
  };
  const source = "osm";
  const vector = (id, sourceLayer, type, paint, layout = {}) => ({id, source, "source-layer": sourceLayer, type, paint, layout});
  const dark = currentTheme === "dark";
  const colors = dark ? {background: "#172125", land: "#20362e", park: "#2a5b42", forest: "#27503e", grass: "#31533f", residential: "#253337", water: "#244c5a", waterLine: "#367084", street: "#8b9b97", building: "#465357", buildingOutline: "#687574", label: "#e5f0eb", halo: "#19272a"} : {background: "#eef2f0", land: "#e7eee8", park: "#cde4ce", forest: "#bcdabb", grass: "#d7e9d2", residential: "#edf0eb", water: "#b9d9e3", waterLine: "#a0cad7", street: "#ffffff", building: "#d9d5cd", buildingOutline: "#c5c7c1", label: "#38515a", halo: "#f5f6f2"};
  return {
    version: 8,
    glyphs: `${window.location.origin}/static/fonts/{fontstack}/{range}.pbf`,
    sources: {osm: {type: "vector", tiles: [`${window.location.origin}/api/osm/tiles/{z}/{x}/{y}.pbf`], minzoom: 0, maxzoom: 14, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · <a href="https://www.geofabrik.de/">Geofabrik</a>'}},
    layers: [
      {id: "background", type: "background", paint: {"background-color": colors.background}},
      vector("land", "land", "fill", {"fill-color": ["match", ["get", "kind"], "park", colors.park, "forest", colors.forest, "grass", colors.grass, "cemetery", colors.park, "residential", colors.residential, colors.land]}),
      vector("ocean", "ocean", "fill", {"fill-color": colors.water}),
      vector("water", "water_polygons", "fill", {"fill-color": colors.water}),
      vector("water-lines", "water_lines", "line", {"line-color": colors.waterLine, "line-width": 1}),
      vector("street-areas", "street_polygons", "fill", {"fill-color": colors.street}),
      vector("buildings", "buildings", "fill", {"fill-color": colors.building, "fill-outline-color": colors.buildingOutline}),
      vector("streets", "streets", "line", {"line-color": colors.street, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1, 14, 2, 18, 5]}),
      vector("street-labels", "street_labels", "symbol", {"text-color": colors.label, "text-halo-color": colors.halo, "text-halo-width": 1.3}, {"symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Open Sans Regular"], "text-size": 11}),
      vector("places", "place_labels", "symbol", {"text-color": colors.label, "text-halo-color": colors.halo, "text-halo-width": 1.5}, {"text-field": ["get", "name"], "text-font": ["Open Sans Regular"], "text-size": 12}),
    ],
  };
}

function applyMapLimits(view) {
  const limits = mapLimits[view];
  locationMap.setMaxBounds(limits.bounds);
  locationMap.setMinZoom(limits.minZoom);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function selectView(view) {
  activeView = view;
  document.querySelectorAll(".feature-tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
    button.setAttribute("aria-current", button.dataset.view === view ? "page" : "false");
  });
  renderPanels();
  if (view === "menu") loadMenuSuggestions();
}

function shortlistKey() {
  const parts = [normalizeConceptText(conceptName()), state.profile, state.cuisine, state.dietary];
  return `groundwork-shortlist:${JSON.stringify(accountOwner ? [accountOwner, ...parts] : parts)}`;
}

const accountOwner = window.GROUNDWORK_ACCESS === "account" ? window.GROUNDWORK_MENU_OWNER : null;
const BRIEF_STORAGE_KEY = accountOwner ? `groundwork-active-brief-v1:${accountOwner}` : "groundwork-active-brief-v1";
const BRIEFS_STORAGE_KEY = `groundwork-saved-briefs-v1:${accountOwner || "guest"}`;
const briefFields = ["conceptName", "profile", "rentCap", "dealType", "preferredArea", "cuisine", "averageCheck", "priceMode", "priceTier", "dietary", "description", "purchaseBudget", "otherFixedCosts", "variableCostPct", "operatingDays", "serviceStyle", "audience", "daypart"];

function restoreBrief() {
  try {
    const saved = JSON.parse(localStorage.getItem(BRIEF_STORAGE_KEY) || "null");
    if (!saved || typeof saved.conceptName !== "string") return false;
    briefFields.forEach(key => {
      if (typeof saved[key] === typeof state[key]) state[key] = saved[key];
    });
    return true;
  } catch {
    return false;
  }
}

function persistBrief() {
  const brief = Object.fromEntries(briefFields.map(key => [key, state[key]]));
  const previous = localStorage.getItem(BRIEF_STORAGE_KEY);
  localStorage.setItem(BRIEF_STORAGE_KEY, JSON.stringify(brief));
  const briefs = readStoredBriefs().filter(row => briefIdentity(row) !== briefIdentity(brief));
  briefs.unshift(brief);
  const storedBriefs = JSON.stringify(briefs.slice(0, 50));
  const previousBriefs = localStorage.getItem(BRIEFS_STORAGE_KEY);
  localStorage.setItem(BRIEFS_STORAGE_KEY, storedBriefs);
  renderSavedBriefs();
  if (previous !== JSON.stringify(brief) || previousBriefs !== storedBriefs) queueWorkspaceSync();
}

function syncSavedLocations() {
  const key = shortlistKey();
  if (key !== savedKey) {
    savedKey = key;
    try {
      let stored = JSON.parse(localStorage.getItem(key) || "null");
      if (!stored) {
        const prefix = accountOwner ? [accountOwner, normalizeConceptText(conceptName()), state.profile, state.cuisine, state.dietary] :
          [normalizeConceptText(conceptName()), state.profile, state.cuisine, state.dietary];
        stored = [];
        for (let index = 0; index < localStorage.length; index++) {
          const oldKey = localStorage.key(index);
          const parts = ownerOfStorageKey(oldKey, "groundwork-shortlist:");
          if (parts?.length > prefix.length && prefix.every((value, partIndex) => value === parts[partIndex])) {
            const oldIds = storedObject(oldKey);
            if (Array.isArray(oldIds)) stored.push(...oldIds);
          }
        }
        stored = [...new Set(stored)].slice(0, 4);
      }
      savedIds = Array.isArray(stored) ? stored.filter(id => typeof id === "string") : [];
    } catch {
      savedIds = [];
    }
  }
  const stored = JSON.stringify(savedIds);
  if (localStorage.getItem(savedKey) !== stored) {
    localStorage.setItem(savedKey, stored);
    queueWorkspaceSync();
  }
}

function toggleSavedLocation(id) {
  if (savedIds.includes(id)) savedIds = savedIds.filter(value => value !== id);
  else if (savedIds.length < 4) savedIds.push(id);
  else {
    const status = document.querySelector("#dashboardStatus");
    status.textContent = "Compare Up To Four Locations. Remove One To Save Another.";
    status.hidden = false;
    return;
  }
  localStorage.setItem(savedKey, JSON.stringify(savedIds));
  queueWorkspaceSync();
  renderAll();
}

const state = {
  conceptName: "Modern Bistro",
  profile: "restaurant",
  rentCap: 18000,
  dealType: "lease",
  preferredArea: "",
  cuisine: "any",
  averageCheck: 35,
  priceMode: "tier",
  priceTier: "$$",
  dietary: "none",
  description: "",
  purchaseBudget: 3000000,
  otherFixedCosts: "",
  variableCostPct: "",
  operatingDays: "26",
  serviceStyle: "casual",
  audience: "residents",
  daypart: "all_day",
};
const PRICE_DEFAULTS = {"$": 18, "$$": 35, "$$$": 65, "$$$$": 110};
let availableConceptImages = {};
let workspaceReady = false;
let workspaceRevision = 0;
let workspaceSyncing = false;
let workspaceSyncTimer = null;
let workspaceEditVersion = 0;
let pendingImportMarker = "";
let pendingGuestVersion = "";

function briefIdentity(brief) {
  return [normalizeConceptText(brief.conceptName || ""), brief.cuisine, brief.profile, brief.dietary, brief.dealType].join("|");
}

function readStoredBriefs() {
  try {
    const rows = JSON.parse(localStorage.getItem(BRIEFS_STORAGE_KEY) || "[]");
    return Array.isArray(rows) ? rows.filter(row => row && typeof row.conceptName === "string").slice(0, 50) : [];
  } catch {
    return [];
  }
}

function storedObject(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); }
  catch { return null; }
}

function ownerOfStorageKey(key, prefix) {
  if (!key.startsWith(prefix)) return null;
  try {
    const parts = JSON.parse(key.slice(prefix.length));
    return Array.isArray(parts) ? parts : null;
  } catch {
    return null;
  }
}

function workspaceSnapshot() {
  const shortlists = {};
  const menus = {};
  if (accountOwner) {
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index);
      const shortlistParts = ownerOfStorageKey(key, "groundwork-shortlist:");
      const menuParts = ownerOfStorageKey(key, "groundwork-menu-v2:");
      const value = storedObject(key);
      if (shortlistParts?.[0] === accountOwner && Array.isArray(value)) shortlists[key] = value.slice(0, 4);
      if (menuParts?.[0] === accountOwner && Array.isArray(value)) menus[key] = value.slice(0, 100);
    }
  }
  return {
    active_brief: storedObject(BRIEF_STORAGE_KEY),
    briefs: readStoredBriefs(),
    shortlists,
    menus,
  };
}

function applyWorkspace(workspace) {
  for (let index = localStorage.length - 1; index >= 0; index--) {
    const key = localStorage.key(index);
    if (ownerOfStorageKey(key, "groundwork-shortlist:")?.[0] === accountOwner ||
        ownerOfStorageKey(key, "groundwork-menu-v2:")?.[0] === accountOwner) localStorage.removeItem(key);
  }
  if (workspace.active_brief) localStorage.setItem(BRIEF_STORAGE_KEY, JSON.stringify(workspace.active_brief));
  else localStorage.removeItem(BRIEF_STORAGE_KEY);
  localStorage.setItem(BRIEFS_STORAGE_KEY, JSON.stringify(workspace.briefs || []));
  for (const [key, value] of Object.entries(workspace.shortlists || {})) localStorage.setItem(key, JSON.stringify(value));
  for (const [key, value] of Object.entries(workspace.menus || {})) localStorage.setItem(key, JSON.stringify(value));
  savedKey = "";
  menuSavedKey = "";
}

function mergeWorkspaces(base, incoming) {
  const briefs = [...(incoming.briefs || []), ...(base.briefs || [])];
  const seen = new Set();
  return {
    active_brief: incoming.active_brief || base.active_brief || null,
    briefs: briefs.filter(row => {
      const key = briefIdentity(row);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 50),
    shortlists: Object.fromEntries(
      [...new Set([...Object.keys(base.shortlists || {}), ...Object.keys(incoming.shortlists || {})])]
        .map(key => [key, [...new Set([...(incoming.shortlists?.[key] || []), ...(base.shortlists?.[key] || [])])].slice(0, 4)])
    ),
    menus: Object.fromEntries(
      [...new Set([...Object.keys(base.menus || {}), ...Object.keys(incoming.menus || {})])]
        .map(key => {
          const items = [...(incoming.menus?.[key] || []), ...(base.menus?.[key] || [])];
          const ids = new Set();
          return [key, items.filter(item => {
            if (ids.has(item.id)) return false;
            ids.add(item.id);
            return true;
          }).slice(0, 100)];
        })
    ),
  };
}

function guestWorkspace() {
  const shortlists = {};
  const menus = {};
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index);
    const shortlistParts = ownerOfStorageKey(key, "groundwork-shortlist:");
    const menuParts = ownerOfStorageKey(key, "groundwork-menu-v2:");
    const value = storedObject(key);
    if ([4, 12].includes(shortlistParts?.length) && Array.isArray(value)) {
      shortlists[`groundwork-shortlist:${JSON.stringify([accountOwner, ...shortlistParts])}`] = value.slice(0, 4);
    }
    if (menuParts?.[0] === "guest" && Array.isArray(value)) {
      menus[`groundwork-menu-v2:${JSON.stringify([accountOwner, ...menuParts.slice(1)])}`] = value.slice(0, 100);
    }
  }
  const active = storedObject("groundwork-active-brief-v1");
  const briefs = storedObject("groundwork-saved-briefs-v1:guest");
  return {
    active_brief: active && typeof active.conceptName === "string" ? active : null,
    briefs: Array.isArray(briefs) ? briefs : active ? [active] : [],
    shortlists,
    menus,
  };
}

function workspaceStatus(message) {
  document.querySelector("#workspaceSyncStatus").textContent = message;
  if (activeView === "menu" && accountOwner) document.querySelector("#menuSaveStatus").textContent = message;
}

function renderSavedBriefs() {
  const rows = readStoredBriefs();
  const board = document.querySelector("#savedBriefs");
  board.innerHTML = rows.length ? rows.map((brief, index) => `
    <div class="saved-brief-row">
      <div><strong>${escapeHtml(brief.conceptName)}</strong><span>${escapeHtml(profileLabel(brief.profile || "restaurant"))} · ${escapeHtml(brief.preferredArea || "New York City")}</span></div>
      <button type="button" data-open-brief="${index}" ${briefIdentity(brief) === briefIdentity(state) ? "disabled" : ""}>${briefIdentity(brief) === briefIdentity(state) ? "Current" : "Open"}</button>
      ${briefIdentity(brief) === briefIdentity(state) ? "" : `<button type="button" data-remove-brief="${index}" aria-label="Remove ${escapeHtml(brief.conceptName)}">×</button>`}
    </div>`).join("") : '<span class="saved-brief-empty">No Saved Concepts</span>';
}

function queueWorkspaceSync() {
  if (!accountOwner) {
    const version = Number(localStorage.getItem("groundwork-guest-workspace-revision") || 0) + 1;
    localStorage.setItem("groundwork-guest-workspace-revision", String(version));
    workspaceStatus("Saved on this device");
    return;
  }
  if (!workspaceReady) return;
  workspaceEditVersion++;
  localStorage.setItem(`groundwork-workspace-dirty:${accountOwner}`, "1");
  workspaceStatus("Saving...");
  clearTimeout(workspaceSyncTimer);
  workspaceSyncTimer = setTimeout(syncWorkspace, 500);
}

async function syncWorkspace() {
  if (!workspaceReady || workspaceSyncing) return;
  workspaceSyncing = true;
  const version = workspaceEditVersion;
  let payload = workspaceSnapshot();
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = await fetch("/api/workspace", {
        method: "PUT",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": window.GROUNDWORK_CSRF},
        body: JSON.stringify({revision: workspaceRevision, workspace: payload}),
      });
      if (response.status === 409 && attempt === 0) {
        const current = await fetch("/api/workspace", {cache: "no-store"});
        if (!current.ok) throw new Error("Unable to reconcile workspace.");
        const remote = await current.json();
        workspaceRevision = remote.revision;
        payload = mergeWorkspaces(remote.workspace || {active_brief: null, briefs: [], shortlists: {}, menus: {}}, payload);
        applyWorkspace(payload);
        continue;
      }
      if (!response.ok) throw new Error("Unable to save workspace.");
      workspaceRevision = (await response.json()).revision;
      if (version === workspaceEditVersion) {
        localStorage.removeItem(`groundwork-workspace-dirty:${accountOwner}`);
        if (pendingImportMarker) localStorage.setItem(pendingImportMarker, pendingGuestVersion);
        pendingImportMarker = "";
        pendingGuestVersion = "";
      }
      workspaceStatus("Saved to account");
      return;
    }
    throw new Error("Workspace changed in another session.");
  } catch {
    workspaceStatus("Saved on this device; account sync unavailable");
  } finally {
    workspaceSyncing = false;
    if (version !== workspaceEditVersion) {
      clearTimeout(workspaceSyncTimer);
      workspaceSyncTimer = setTimeout(syncWorkspace, 500);
    }
  }
}

async function initializeWorkspace() {
  if (accountOwner) {
    try {
      const response = await fetch("/api/workspace", {cache: "no-store"});
      if (!response.ok) throw new Error("Workspace unavailable.");
      const remote = await response.json();
      workspaceRevision = remote.revision;
      const local = workspaceSnapshot();
      const blank = {active_brief: null, briefs: [], shortlists: {}, menus: {}};
      let workspace = localStorage.getItem(`groundwork-workspace-dirty:${accountOwner}`)
        ? mergeWorkspaces(remote.workspace || blank, local) : remote.workspace || local;
      const importMarker = `groundwork-guest-imported:${accountOwner}`;
      const guestVersion = localStorage.getItem("groundwork-guest-workspace-revision") || "0";
      if (localStorage.getItem(importMarker) !== guestVersion) {
        const guest = guestWorkspace();
        if (guest.active_brief || guest.briefs.length || Object.keys(guest.shortlists).length || Object.keys(guest.menus).length) {
          workspace = mergeWorkspaces(guest, workspace);
          pendingImportMarker = importMarker;
          pendingGuestVersion = guestVersion;
        } else localStorage.setItem(importMarker, guestVersion);
      }
      applyWorkspace(workspace);
      workspaceReady = true;
      if (pendingImportMarker || localStorage.getItem(`groundwork-workspace-dirty:${accountOwner}`)) queueWorkspaceSync();
      else workspaceStatus("Saved to account");
    } catch {
      workspaceStatus("Account sync unavailable; working on this device");
    }
  } else workspaceStatus("Saved on this device");
  const hasSavedBrief = restoreBrief();
  if (hasSavedBrief) closeBrief();
  renderSavedBriefs();
  updateConceptImage(state.cuisine);
  syncBriefControls();
  syncSavedLocations();
  loadDashboard();
}

function updateConceptImage(cuisine) {
  const photo = document.querySelector("#briefPhoto");
  const key = cuisine && !["any", "fusion", "custom"].includes(cuisine) ? cuisine : "general";
  photo.style.backgroundImage = availableConceptImages[key] ? `url("${availableConceptImages[key]}")` : "";
}

async function loadConceptImages() {
  try {
    const response = await fetch("/api/concepts/images");
    if (!response.ok) return;
    availableConceptImages = (await response.json()).images || {};
    updateConceptImage(document.querySelector("#briefCuisine").value);
  } catch {
    // The default brief image remains available without the optional image set.
  }
}

function setTheme(theme, persist = true) {
  dashboardThemeChoice = ["light", "dark"].includes(theme) ? theme : "system";
  currentTheme = dashboardThemeChoice === "system" ? (systemTheme.matches ? "dark" : "light") : dashboardThemeChoice;
  document.documentElement.dataset.theme = currentTheme;
  if (persist) {
    if (dashboardThemeChoice === "system") localStorage.removeItem("groundwork-theme");
    else localStorage.setItem("groundwork-theme", dashboardThemeChoice);
  }
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === dashboardThemeChoice));
  });
  if (locationMap && activeBasemap === "streets") locationMap.setStyle(mapStyle("streets"));
}
systemTheme.addEventListener("change", () => {if (dashboardThemeChoice === "system") setTheme("system", false);});

const toneFor = {
  opportunity: ["#b6404a", "#df7653", "#e9b967", "#a8ca78", "#39ae88", "#087c78"],
  activity: ["#455c71", "#66849b", "#9bb2b2", "#c5ba83", "#e1a65d", "#b96a39"],
  whitespace: ["#725568", "#9a6b78", "#c28c87", "#c7ad7b", "#96bb8a", "#458a80"],
  cost: ["#a74b52", "#c47a5e", "#d5ab6f", "#b8c684", "#73af85", "#367d72"],
  walkability: ["#955158", "#c48261", "#d6b776", "#acc78c", "#6cac9a", "#337f90"],
  business_draw: ["#a34359", "#cf7968", "#deac70", "#b2c782", "#71b394", "#28878a"],
  concept_demand: ["#ad4648", "#db7952", "#e9ba6e", "#a9c77b", "#49ad8c", "#087d82"],
};

const layerTitles = {
  opportunity: "Location Opportunities",
  activity: "Local Demand",
  whitespace: "Market Gaps",
  cost: "Commercial Suitability",
  walkability: "Area Walkability",
  business_draw: "Business Draw",
  concept_demand: "Concept Demand Index",
};

function fmtMoney(value) {
  if (!Number.isFinite(Number(value))) return "--";
  return `$${Math.round(value / 1000)}k`;
}

function fmtDollar(value) {
  return Number.isFinite(Number(value)) ? `$${Math.round(Number(value)).toLocaleString("en-US")}` : "--";
}

function titleCase(value) {
  return String(value || "").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function fmtPrice(value) {
  if (!value) return "--";
  if (value >= 1000000) return `$${(value / 1000000).toFixed(value >= 10000000 ? 0 : 1)}M`;
  return `$${Math.round(value / 1000)}k`;
}

function dealLabel(value) {
  if (value === "purchase") return "Purchase";
  if (value === "either") return "Lease Or Purchase";
  return "Lease";
}

function profileLabel(value) {
  if (value === "bar") return "Bar Or Gastropub";
  if (value === "coffee") return "Coffee And Breakfast";
  if (value === "fast_casual") return "Fast Casual";
  if (value === "counter_service") return "Counter Service";
  if (value === "bakery") return "Bakery Or Pastry Shop";
  if (value === "fine_dining") return "Fine Dining";
  if (value === "takeout_delivery") return "Takeout And Delivery";
  return "Sit-Down Restaurant";
}

function defaultServiceStyle(profile) {
  return profile === "fine_dining" ? "fine_dining" : ["fast_casual", "counter_service", "takeout_delivery", "coffee", "bakery"].includes(profile) ? "quick_service" : "casual";
}

function syncTransactionFields() {
  const purchaseOnly = state.dealType === "purchase";
  document.querySelector("#monthlyBudgetField").hidden = purchaseOnly;
  document.querySelector("#purchaseBudgetField").hidden = state.dealType === "lease";
  document.querySelector(".range-control").hidden = purchaseOnly;
  document.querySelector("#purchaseTarget").hidden = !purchaseOnly;
  document.querySelector("#purchaseTargetValue").textContent = fmtPrice(state.purchaseBudget);
}

function syncPriceModeControls() {
  document.querySelector("#briefTierField").hidden = state.priceMode !== "tier";
  document.querySelector("#briefExactPriceField").hidden = state.priceMode !== "exact";
  document.querySelector("#briefAverageCheck").required = state.priceMode === "exact";
  document.querySelectorAll("[data-price-mode]").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.priceMode === state.priceMode));
  });
}

function scoreClass(value) {
  if (value >= 82) return "score-good";
  if (value >= 68) return "score-mid";
  return "score-low";
}

function colorFor(value, layer = activeLayer) {
  if (value === null || value === undefined) return "#849097";
  const colors = toneFor[layer] || toneFor.opportunity;
  const position = Math.max(0, Math.min(100, Number(value))) / 20;
  const low = Math.min(4, Math.floor(position));
  const blend = Math.min(1, position - low);
  const a = colors[low].match(/\w\w/g).map(part => parseInt(part, 16));
  const b = colors[low + 1].match(/\w\w/g).map(part => parseInt(part, 16));
  return `rgb(${a.map((channel, index) => Math.round(channel + (b[index] - channel) * blend)).join(",")})`;
}

function setActiveLayer(layer) {
  activeLayer = layer;
  document.querySelector("#mapLayerSelect").value = layer;
  document.querySelectorAll(".layer").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.layer === activeLayer);
  });
  document.querySelectorAll(".mini-tab").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.layer === activeLayer);
  });
  document.querySelector("#mapModeTitle").textContent = layerTitles[activeLayer] || "NYC Score Surface";
  if (dashboard) {
    renderMap();
    renderIntel();
  }
}

function activeMetric(location) {
  return location[activeLayer];
}

function rentDisplay(row) {
  return row.rent_label || fmtMoney(row.rent);
}

function conceptName() {
  return state.conceptName.trim() || "Restaurant Concept";
}

function cuisineLabel() {
  const cuisine = dashboard?.meta?.concept?.cuisine || state.cuisine;
  return [...document.querySelector("#briefCuisine").options].find(option => option.value === cuisine)?.textContent || "Not Specified";
}

const suggestionStyles = [
  {name: "Bistro", profile: "restaurant"},
  {name: "Café", profile: "coffee"},
  {name: "Restaurant", profile: "restaurant"},
  {name: "Restaurant With Bar", profile: "bar"},
  {name: "Fast Casual", profile: "fast_casual"},
  {name: "Counter Service", profile: "counter_service"},
  {name: "Fine Dining", profile: "fine_dining"},
  {name: "Takeout", profile: "takeout_delivery"},
];
let visibleSuggestions = [];
let selectedSuggestionIndex = -1;
let activeConceptInput = null;

function normalizeConceptText(value) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function conceptSuggestionsFor(query) {
  const text = normalizeConceptText(query);
  if (text.length < 2) return [];
  const dietary = ["vegan", "vegetarian", "halal", "kosher", "gluten free"].find(value => text.includes(value))?.replace(" ", "_") || "none";
  const catalog = [...document.querySelector("#briefCuisine").options].filter(option => !["any", "fusion", "custom", "vegetarian_vegan"].includes(option.value));
  const matches = catalog.map(option => {
    const name = normalizeConceptText(option.textContent);
    const primary = name.split(" ")[0];
    const position = text.indexOf(name);
    const primaryPosition = text.split(" ").indexOf(primary);
    return {option, matchLength: position >= 0 ? name.length : primary.length >= 3 && primaryPosition >= 0 ? primary.length : text.length >= 3 && name.startsWith(text) ? text.length : 0};
  }).filter(item => item.matchLength > 0).sort((a, b) => b.matchLength - a.matchLength);
  if (!matches.length && dietary === "none") return [];
  const match = matches[0]?.option;
  const cuisineName = match?.textContent.split(" /")[0] || "";
  const dietaryName = dietary === "none" ? "" : dietary.replace("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
  const baseName = [dietaryName, cuisineName].filter(Boolean).join(" ");
  const remaining = text.replace(normalizeConceptText(cuisineName), "").replace(normalizeConceptText(dietaryName), "").trim();
  const styles = match ? suggestionStyles : [suggestionStyles[2], suggestionStyles[1], suggestionStyles[0], ...suggestionStyles.slice(3)];
  const styleHint = /\b(with bar|gastropub|cocktail bar|wine bar)\b/.test(text) ? "bar" :
    /\b(fine dining|upscale|premium)\b/.test(text) ? "fine_dining" :
    /\b(fast casual)\b/.test(text) ? "fast_casual" :
    /\b(counter service)\b/.test(text) ? "counter_service" :
    /\b(takeout|take away|delivery)\b/.test(text) ? "takeout_delivery" :
    /\b(cafe|coffee shop)\b/.test(text) ? "coffee" : null;
  return styles.map((style, index) => ({
    title: `${baseName} ${style.name}`,
    cuisine: match?.value || "vegetarian_vegan",
    dietary,
    profile: style.profile,
    priority: styleHint === style.profile ? 200 - index : remaining && normalizeConceptText(style.name).includes(remaining) ? 100 - index : -index,
  })).sort((a, b) => b.priority - a.priority).slice(0, 5);
}

function closeConceptSuggestions() {
  document.querySelectorAll("#conceptInput, #briefConceptName, #searchInput").forEach(input => {
    const list = document.querySelector(`#${input.getAttribute("aria-controls")}`);
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  });
  visibleSuggestions = [];
  selectedSuggestionIndex = -1;
  activeConceptInput = null;
}

function chooseConceptSuggestion(item, input, preserveName = false) {
  if (item.kind === "location") {
    selectedId = item.id;
    selectView("discover");
    renderAll();
    revealSelectedRanking();
    input.value = "";
    closeConceptSuggestions();
    return;
  }
  if (input.id === "briefConceptName") {
    if (!preserveName) input.value = item.title;
    document.querySelector("#briefCuisine").value = item.cuisine;
    document.querySelector("#briefDietary").value = item.dietary;
    document.querySelector("#briefProfile").value = item.profile;
    document.querySelector("#briefServiceStyle").value = defaultServiceStyle(item.profile);
    updateConceptImage(item.cuisine);
  } else {
    state.conceptName = preserveName ? input.value.trim() : item.title;
    state.cuisine = item.cuisine;
    state.dietary = item.dietary;
    state.profile = item.profile;
    state.serviceStyle = defaultServiceStyle(item.profile);
    state.description = "";
    selectedId = null;
    if (input.id === "searchInput") input.value = "";
    syncBriefControls();
    selectView("discover");
    loadDashboard();
  }
  closeConceptSuggestions();
}

function renderConceptSuggestions(input) {
  if (activeConceptInput && activeConceptInput !== input) closeConceptSuggestions();
  activeConceptInput = input;
  const list = document.querySelector(`#${input.getAttribute("aria-controls")}`);
  const query = normalizeConceptText(input.value);
  const locations = input.id === "searchInput" && dashboard && query.length >= 2
    ? allLocations().filter(row => normalizeConceptText(`${row.name} ${row.borough}`).includes(query))
      .slice(0, 5).map(row => ({kind: "location", id: row.id, title: `${row.name} · ${row.borough}`}))
    : [];
  visibleSuggestions = locations.length ? locations : conceptSuggestionsFor(input.value);
  selectedSuggestionIndex = -1;
  list.replaceChildren();
  visibleSuggestions.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.role = "option";
    button.id = `${list.id}Option${index}`;
    button.textContent = item.title;
    button.addEventListener("click", () => chooseConceptSuggestion(item, input));
    list.append(button);
  });
  if (!visibleSuggestions.length && input.id === "searchInput" && query.length >= 2) {
    const empty = document.createElement("div");
    empty.className = "search-empty";
    empty.textContent = "No matching locations or restaurant ideas";
    list.append(empty);
  }
  list.hidden = !list.childElementCount;
  input.setAttribute("aria-expanded", String(!list.hidden));
}

function conceptParams() {
  const params = new URLSearchParams({
    concept_name: conceptName(),
    profile: state.profile,
    rent_cap: String(state.rentCap),
    purchase_budget: String(state.purchaseBudget),
    other_fixed_costs: state.otherFixedCosts,
    variable_cost_pct: state.variableCostPct,
    operating_days: state.operatingDays,
    deal_type: state.dealType,
    borough: state.preferredArea,
    cuisine: state.cuisine,
    ...(state.priceMode === "exact" ? {average_check: String(state.averageCheck)} : {}),
    price_tier: state.priceTier,
    price_mode: state.priceMode,
    dietary: state.dietary,
    description: state.description,
    service_style: state.serviceStyle,
    audience: state.audience,
    daypart: state.daypart,
  });
  const currentSaved = storedObject(shortlistKey());
  if (Array.isArray(currentSaved)) currentSaved.slice(0, 4).forEach(id => params.append("saved_id", id));
  return params;
}

async function loadDashboard() {
  const currentRequest = ++requestId;
  const status = document.querySelector("#dashboardStatus");
  status.hidden = false;
  status.textContent = "Updating Locations...";
  document.querySelector(".workspace").setAttribute("aria-busy", "true");
  const params = conceptParams();
  try {
    const response = await fetch(`/api/dashboard?${params}`);
    if (!response.ok) throw new Error("Dashboard request failed");
    const result = await response.json();
    if (currentRequest !== requestId) return;
    if (!result.locations?.length) {
      status.textContent = "No Locations Found. Update Your Search Brief.";
      document.querySelector(".workspace").classList.add("has-no-results");
      return;
    }
    dashboard = result;
    hexCache.clear();
    hexRequestId++;
    clearHexLayer();
    competitionCache.clear();
    catchmentCache.clear();
    persistBrief();
    document.querySelector(".workspace").classList.remove("has-no-results");
    selectedId = selectedId || dashboard.selected;
    if (!allLocations().some((location) => location.id === selectedId)) {
      selectedId = dashboard.selected;
    }
    syncSavedLocations();
    renderAll();
    if (activeView === "menu") loadMenuSuggestions();
    status.hidden = true;
  } catch (error) {
    if (currentRequest === requestId) {
      status.textContent = "Unable To Update Locations. Select Refresh To Retry.";
    }
  } finally {
    if (currentRequest === requestId) document.querySelector(".workspace").setAttribute("aria-busy", "false");
  }
}

function allLocations() {
  const rows = [...dashboard.locations];
  const existing = new Set(rows.map(row => row.id));
  for (const row of dashboard.saved_locations || []) {
    if (!existing.has(row.id)) rows.push(row);
  }
  return rows;
}

function selectedLocation() {
  return allLocations().find((location) => location.id === selectedId) || dashboard.locations[0];
}

function renderMetrics() {
  const best = dashboard.locations[0];
  const metrics = [
    ["Leading Location", best.name, `${best.opportunity}/100 Location Score`],
    ["Locations Ranked", dashboard.locations.length, state.preferredArea || "New York City"],
    [state.dealType === "purchase" ? "Purchase Budget" : "Monthly Budget", state.dealType === "purchase" ? fmtPrice(state.purchaseBudget) : fmtMoney(state.rentCap), "Planning Assumption"],
  ];

  document.querySelector("#metricRibbon").innerHTML = metrics.map(([label, value, sub]) => `
    <article class="metric">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${escapeHtml(value)}</div>
      <div class="metric-sub">${escapeHtml(sub)}</div>
    </article>
  `).join("");
}

function renderLocationSelect() {
  const select = document.querySelector("#locationSelect");
  select.innerHTML = allLocations().map(location => `<option value="${escapeHtml(location.id)}">${escapeHtml(location.name)}</option>`).join("");
  select.value = selectedId;
  const count = document.querySelector("#compareCount");
  count.textContent = savedIds.length;
  count.hidden = savedIds.length === 0;
}

function toggleExpandedMap(force) {
  const module = document.querySelector(".map-module");
  const expanded = typeof force === "boolean" ? force : !module.classList.contains("is-expanded");
  module.classList.toggle("is-expanded", expanded);
  document.body.classList.toggle("map-expanded", expanded);
  const button = document.querySelector("#expandMapButton");
  button.setAttribute("aria-label", expanded ? "Close Expanded Map" : "Expand Map");
  button.title = expanded ? "Close Expanded Map" : "Expand Map";
  button.textContent = expanded ? "×" : "⛶";
  requestAnimationFrame(() => locationMap?.resize());
}

function resetToNYC() {
  if (!locationMap) return;
  locationMap.fitBounds([[-74.23, 40.49], [-73.70, 40.91]], {
    padding: 30, maxZoom: 11.5, duration: 300, bearing: 0, pitch: 0,
  });
}

function clearHexLayer() {
  hoveredHexId = null;
  if (!locationMap?.getStyle()) return;
  for (const id of ["concept-hex-outline", "concept-hex-fill"]) {
    if (locationMap.getLayer(id)) locationMap.removeLayer(id);
  }
  if (locationMap.getSource("concept-hexes")) locationMap.removeSource("concept-hexes");
}

function paintHexLayer(data) {
  if (activeLayer !== "concept_demand" || !locationMap?.getStyle()) return;
  clearHexLayer();
  locationMap.addSource("concept-hexes", {type: "geojson", data});
  const labelLayer = activeBasemap === "streets" && locationMap.getLayer("street-labels") ? "street-labels" :
    activeBasemap === "buildings3d" ? locationMap.getStyle().layers.find(layer => layer.type === "symbol")?.id : undefined;
  locationMap.addLayer({id: "concept-hex-fill", type: "fill", source: "concept-hexes", paint: {
    "fill-color": ["interpolate", ["linear"], ["get", "score"], 0, "#ad4648", 20, "#db7952", 40, "#e9ba6e", 60, "#a9c77b", 80, "#49ad8c", 100, "#087d82"],
    "fill-opacity": .57,
  }}, labelLayer);
  locationMap.addLayer({id: "concept-hex-outline", type: "line", source: "concept-hexes", paint: {
    "line-color": "#f0f5ed", "line-opacity": .78, "line-width": ["interpolate", ["linear"], ["zoom"], 9, .5, 12, 1.1],
  }}, labelLayer);
}

function hexLevel() {
  const zoom = locationMap.getZoom();
  return zoom >= 14 ? "fine" : zoom >= 11.5 ? "cell" : "sector";
}

async function showHexLayer() {
  if (!locationMap || activeLayer !== "concept_demand" || !dashboard) return;
  const level = hexLevel();
  const params = conceptParams();
  params.set("level", level);
  const key = `${dashboard.meta.data_release}:${params}`;
  const currentRequest = ++hexRequestId;
  if (hexCache.has(key)) {
    paintHexLayer(hexCache.get(key));
    return;
  }
  try {
    const response = await fetch(`/api/hex-demand?${params}`);
    if (!response.ok) throw new Error("Hex demand request failed");
    const data = await response.json();
    hexCache.set(key, data);
    if (currentRequest === hexRequestId && activeLayer === "concept_demand" && level === hexLevel()) paintHexLayer(data);
  } catch {
    if (currentRequest === hexRequestId) {
      const status = document.querySelector("#dashboardStatus");
      status.textContent = "Concept Demand Is Temporarily Unavailable.";
      status.hidden = false;
    }
  }
}

function hexAtPoint(point) {
  if (activeLayer !== "concept_demand" || !locationMap.getLayer("concept-hex-fill")) return null;
  return locationMap.queryRenderedFeatures(point, {layers: ["concept-hex-fill"]})[0] || null;
}

function setMapViewStatus(message, isError = false) {
  const status = document.querySelector("#mapViewStatus");
  status.textContent = message;
  status.hidden = !message;
  status.classList.toggle("is-error", isError);
}

function collapseMapAttribution() {
  const attribution = document.querySelector("#mapStage .maplibregl-ctrl-attrib");
  if (!attribution || attribution.dataset.userOpened === "true") return;
  if (!attribution.open && !attribution.classList.contains("maplibregl-compact-show")) return;
  attribution.open = false;
  attribution.classList.remove("maplibregl-compact-show");
}

function fallbackToAerial(message) {
  if (!locationMap || activeBasemap !== "buildings3d") return;
  activeBasemap = "aerial";
  document.querySelector("#mapBasemapSelect").value = "aerial";
  locationMap.setStyle(mapStyle("aerial"));
  applyMapLimits("aerial");
  locationMap.easeTo({pitch: 0, bearing: 0, duration: 250});
  setMapViewStatus(message, true);
}

async function changeMapView(next) {
  const request = ++mapViewRequestId;
  if (!locationMap || !["streets", "aerial", "buildings3d"].includes(next)) return;
  if (next === activeBasemap) return;
  let style;
  if (next === "buildings3d") {
    setMapViewStatus("Loading 3D street map...");
    try {
      style = await buildingMapStyle();
    } catch {
      if (request !== mapViewRequestId) return;
      document.querySelector("#mapBasemapSelect").value = activeBasemap;
      setMapViewStatus("3D street map is unavailable. Aerial and Streets are still available.", true);
      return;
    }
  }
  if (request !== mapViewRequestId) return;
  activeBasemap = next;
  pinned3DFeature = false;
  hovered3DFeatureId = "";
  mapPopup?.remove();
  locationMap.setStyle(style || mapStyle(next));
  applyMapLimits(next);
  if (next === "buildings3d") {
    const location = selectedLocation();
    locationMap.easeTo({center: [location.longitude, location.latitude], zoom: Math.max(locationMap.getZoom(), 15.4), pitch: 54, bearing: -18, duration: 550});
    setMapViewStatus("Loading 3D buildings...");
  } else {
    locationMap.easeTo({pitch: 0, bearing: 0, duration: 300});
    setMapViewStatus("");
  }
}

function featureAtPoint(point) {
  if (activeBasemap !== "buildings3d" || !locationMap.getLayer("nyc-buildings-3d")) return null;
  const streetLayers = locationMap.getStyle().layers.filter(layer => layer.source === "openmaptiles" &&
    layer["source-layer"] === "transportation_name" && layer.type === "symbol").map(layer => layer.id);
  const layers = ["nyc-pois-3d", ...streetLayers, "nyc-buildings-3d"].filter(id => locationMap.getLayer(id));
  return locationMap.queryRenderedFeatures(point, {layers})[0] || null;
}

function show3DFeature(feature, lngLat, pinned = false) {
  const properties = feature.properties || {};
  const layer = feature.layer.id;
  const isBuilding = layer === "nyc-buildings-3d";
  const isPoi = layer === "nyc-pois-3d";
  const title = isBuilding ? "Building" : properties.name || (isPoi ? "Point Of Interest" : "Street");
  const detail = document.createElement("div");
  detail.className = "map-location-detail";
  const heading = document.createElement("strong");
  heading.textContent = title;
  detail.append(heading);
  const row = (label, value) => {
    const wrapper = document.createElement("div");
    const name = document.createElement("span");
    const text = document.createElement("b");
    name.textContent = label;
    text.textContent = value;
    wrapper.append(name, text);
    detail.append(wrapper);
  };
  if (isBuilding) {
    const height = Number(properties.render_height);
    if (Number.isFinite(height) && height > 0) row("Rendered Height", `${Math.round(height)} m`);
    row("Geometry", "OpenFreeMap");
  } else if (isPoi) {
    row("Category", titleCase((properties.class || properties.subclass || "Point Of Interest").replaceAll("_", " ")));
    if (properties.housenumber) row("Street Number", String(properties.housenumber));
  } else row("Map Feature", "Street");
  mapPopup?.remove();
  pinned3DFeature = pinned;
  const popup = new maplibregl.Popup({closeButton: pinned, closeOnClick: !pinned, offset: 12, maxWidth: "260px"})
    .setLngLat(lngLat).setDOMContent(detail).addTo(locationMap);
  popup.on("close", () => { if (mapPopup === popup) pinned3DFeature = false; });
  mapPopup = popup;
}

function renderMap() {
  if (!locationMap) {
    locationMap = new maplibregl.Map({container: "mapStage", style: mapStyle(activeBasemap), center: [-73.96, 40.73], zoom: 11, minZoom: mapLimits[activeBasemap].minZoom, maxZoom: 19, maxBounds: mapLimits[activeBasemap].bounds, attributionControl: false});
    locationMap.addControl(new maplibregl.NavigationControl({showCompass: true}), "top-left");
    locationMap.addControl(new maplibregl.AttributionControl({compact: true}), "bottom-right");
    const resetButton = document.createElement("button");
    resetButton.type = "button";
    resetButton.id = "resetNycButton";
    resetButton.className = "map-reset-button";
    resetButton.textContent = "Reset to NYC";
    resetButton.addEventListener("click", resetToNYC);
    document.querySelector("#mapStage").append(resetButton);
    const attribution = document.querySelector("#mapStage .maplibregl-ctrl-attrib");
    attribution.querySelector("summary").addEventListener("click", () => {
      attribution.dataset.userOpened = attribution.open ? "false" : "true";
    });
    collapseMapAttribution();
    locationMap.on("zoomend", () => {
      if (activeLayer === "concept_demand") showHexLayer();
    });
    locationMap.on("load", () => {
      if (activeLayer === "concept_demand") showHexLayer();
    });
    locationMap.on("idle", () => {
      if (activeLayer === "concept_demand" && !locationMap.getLayer("concept-hex-fill")) showHexLayer();
      if (activeBasemap === "buildings3d" && locationMap.getLayer("nyc-buildings-3d") && locationMap.isSourceLoaded("openmaptiles")) setMapViewStatus("");
      collapseMapAttribution();
    });
    locationMap.on("render", () => {
      collapseMapAttribution();
      const status = document.querySelector("#mapViewStatus");
      if (activeBasemap === "buildings3d" && !status.hidden && !status.classList.contains("is-error") &&
          locationMap.getLayer("nyc-buildings-3d") && locationMap.queryRenderedFeatures({layers: ["nyc-buildings-3d"]}).length) {
        setMapViewStatus("");
      }
    });
    locationMap.on("style.load", () => {
      if (activeLayer === "concept_demand") showHexLayer();
    });
    locationMap.on("error", event => {
      if (activeBasemap === "buildings3d" && (event.sourceId === "openmaptiles" || /openfreemap/i.test(event.error?.message || ""))) {
        fallbackToAerial("3D building tiles could not load. Aerial remains active.");
      }
    });
    locationMap.on("mousemove", (event) => {
      if (activeLayer !== "concept_demand") return;
      const feature = hexAtPoint(event.point);
      locationMap.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        hoveredHexId = null;
        mapPopup?.remove();
        return;
      }
      if (feature.properties.id === hoveredHexId) return;
      hoveredHexId = feature.properties.id;
      const {score, coverage, level, cell_count: count} = feature.properties;
      const detail = document.createElement("div");
      detail.className = "map-location-detail";
      detail.innerHTML = `<strong>${level === "sector" ? "Demand Sector" : "Local Demand Cell"}</strong><div><span>Concept Demand</span><b>${score}/100</b></div><div><span>Evidence Coverage</span><b>${coverage}%</b></div>${count ? `<small>${count} Local Cells</small>` : ""}`;
      mapPopup?.remove();
      mapPopup = new maplibregl.Popup({closeButton: false, closeOnClick: false, offset: 12, maxWidth: "230px"})
        .setLngLat(event.lngLat).setDOMContent(detail).addTo(locationMap);
    });
    locationMap.on("click", (event) => {
      const feature = hexAtPoint(event.point);
      if (feature?.properties.level === "sector") {
        const ring = feature.geometry.coordinates[0];
        const center = ring.slice(0, -1).reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0]).map(value => value / (ring.length - 1));
        locationMap.easeTo({center, zoom: 12, duration: 450});
      }
    });
    locationMap.on("mousemove", event => {
      if (activeBasemap !== "buildings3d" || activeLayer === "concept_demand" || pinned3DFeature) return;
      const feature = featureAtPoint(event.point);
      locationMap.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        hovered3DFeatureId = "";
        mapPopup?.remove();
        return;
      }
      const identity = `${feature.layer.id}:${feature.id ?? JSON.stringify(feature.geometry?.coordinates?.[0]?.[0] ?? feature.properties)}`;
      if (identity === hovered3DFeatureId) return;
      hovered3DFeatureId = identity;
      show3DFeature(feature, event.lngLat);
    });
    locationMap.on("click", event => {
      if (activeBasemap !== "buildings3d" || activeLayer === "concept_demand") return;
      const feature = featureAtPoint(event.point);
      if (feature) show3DFeature(feature, event.lngLat, true);
      else mapPopup?.remove();
    });
    const expand = document.createElement("button");
    expand.id = "expandMapButton";
    expand.className = "map-expand-button";
    expand.type = "button";
    expand.textContent = "⛶";
    expand.title = "Expand Map";
    expand.setAttribute("aria-label", "Expand Map");
    expand.addEventListener("click", () => toggleExpandedMap());
    document.querySelector("#mapStage").append(expand);
    const legend = document.createElement("div");
    legend.className = "map-legend";
    legend.innerHTML = '<span>0</span><i></i><span>100</span>';
    document.querySelector("#mapStage").append(legend);
  }
  mapPopup?.remove();
  pinned3DFeature = false;
  mapMarkers.forEach(marker => marker.remove());
  mapMarkers = [];
  if (activeLayer === "concept_demand") showHexLayer();
  else clearHexLayer();
  const locations = allLocations().filter(row => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
  if (activeLayer !== "concept_demand") locations.forEach((location) => {
    const selected = location.id === selectedId;
    const element = document.createElement("button");
    element.className = `map-score-marker${selected ? " is-selected" : ""}`;
    element.type = "button";
    element.style.backgroundColor = colorFor(activeMetric(location));
    element.title = `${location.name} · ${activeMetric(location) ?? "Unavailable"}`;
    element.setAttribute("aria-label", element.title);
    const showDetail = () => {
      mapPopup?.remove();
      const property = (dashboard.properties || []).find(row => row.geoid === location.geoid);
      const propertyLabel = property ? property.lead_type === "listing" ? "Nearby Property Listing" : "Nearby Storefront Record" : "Nearby Property";
      const detail = document.createElement("div");
      detail.className = "map-location-detail";
      detail.innerHTML = `
        <strong>${escapeHtml(location.name)}</strong>
        <div><span>Location Score</span><b>${location.opportunity}/100</b></div>
        <div><span>Business Draw</span><b>${location.business_draw}/100</b></div>
        <small>${propertyLabel}</small>
        <p>${property ? escapeHtml(property.address) : "No Property Record Matched"}</p>
        <div><span>${property?.transaction === "purchase" ? "Asking Price" : property?.transaction === "lease" ? "Asking Rent" : "Asking Price / Rent"}</span><b>${escapeHtml(property?.price_label || "Unavailable")}</b></div>
        <div><span>Broker / Owner</span><b>${escapeHtml(property?.broker_name || "Not In Source")}</b></div>
      `;
      mapPopup = new maplibregl.Popup({closeButton: false, closeOnClick: false, offset: 16, maxWidth: "270px"})
        .setLngLat([location.longitude, location.latitude]).setDOMContent(detail).addTo(locationMap);
    };
    element.addEventListener("mouseenter", showDetail);
    element.addEventListener("focus", showDetail);
    element.addEventListener("mouseleave", () => mapPopup?.remove());
    element.addEventListener("blur", () => mapPopup?.remove());
    element.addEventListener("click", () => {
      selectedId = location.id;
      renderAll();
      revealSelectedRanking();
    });
    mapMarkers.push(new maplibregl.Marker({element, anchor: "center"}).setLngLat([location.longitude, location.latitude]).addTo(locationMap));
  });
  const key = locations.map(row => row.id).join(",");
  if (key !== mapDataset && locations.length) {
    const latitudes = dashboard.locations.map(row => row.latitude);
    const longitudes = dashboard.locations.map(row => row.longitude);
    locationMap.fitBounds([[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]], {padding: 35, maxZoom: 14, duration: 0});
    mapDataset = key;
  }
  document.querySelector(".map-legend i").style.background = `linear-gradient(90deg, ${toneFor[activeLayer].join(",")})`;
}

function renderIntel() {
  const location = selectedLocation();
  document.querySelector("#selectedName").textContent = location.name;
  document.querySelector("#selectedMeta").textContent = `${location.borough} · ${titleCase(location.archetype)}`;
  document.querySelector("#selectedScore").textContent = location.opportunity;
  document.querySelector("#scoreOrb").style.background = `conic-gradient(${colorFor(location.opportunity, "opportunity")} 0 ${location.opportunity}%, rgba(33,54,77,.95) ${location.opportunity}% 100%)`;
  document.querySelector("#confidencePill").textContent = "Screening Estimate";
  document.querySelector("#walkabilityPair").innerHTML = `
    <div><span>Walkability</span><strong>${location.walkability ?? "--"}<small>/100</small></strong></div>
    <div title="Inverse Walkability: Relative Concept Fit, Not Predicted Visits"><span>Business Draw</span><strong>${location.business_draw}<small>/100</small></strong></div>
  `;

  document.querySelector("#barStack").innerHTML = [...location.score_components].sort((a, b) => b.score - a.score).slice(0, 3).map((component) => `
    <div class="bar-row">
      <div class="bar-line"><span>${component.label}</span><strong>${component.score}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${component.score}%;background:${colorFor(component.score, "opportunity")}"></div></div>
    </div>
  `).join("");

  const signals = [...location.score_components].sort((a, b) => b.score - a.score);
  document.querySelector("#driverList").innerHTML = `
    <li><span>Strongest Factor</span><strong>${escapeHtml(signals[0].label)}</strong></li>
    <li><span>Key Tradeoff</span><strong>${escapeHtml(signals[signals.length - 1].label)}</strong></li>
    <li><span>Cuisine Position</span><strong>${escapeHtml(location.concept_evidence.positioning)}</strong></li>
  `;
  document.querySelector("#selectedRecommendation").textContent = location.recommendation || "No decision summary available for this location.";
  const save = document.querySelector("#saveLocation");
  save.textContent = savedIds.includes(location.id) ? "Remove From Compare" : "Save To Compare";
  save.setAttribute("aria-pressed", String(savedIds.includes(location.id)));
}

function renderRanking() {
  const rows = dashboard.locations;
  const table = document.querySelector("#rankingTable");
  const previousTop = table.scrollTop;
  const previousLeft = table.scrollLeft;
  table.innerHTML = `
    <div class="table-row header">
      <span>#</span><span>Location</span><span>Score</span><span>Business Draw</span><span>Walkability</span><span>Cuisine Fit</span><span>Commercial Fit</span><span>Compare</span>
    </div>
    ${rows.map((row, index) => `
      <div class="table-row${row.id === selectedId ? " is-selected" : ""}" data-id="${row.id}" tabindex="0" role="row" aria-current="${row.id === selectedId ? "true" : "false"}">
        <button type="button">${index + 1}</button>
        <button class="place-name" type="button">${escapeHtml(row.name)}</button>
        <span class="${scoreClass(row.opportunity)}">${row.opportunity}</span>
        <span>${row.business_draw}</span>
        <span>${row.walkability ?? "--"}</span>
        <span>${row.score_components.find((item) => item.key === "market_gap").score}</span>
        <span>${row.score_components.find((item) => item.key === "economics").score}</span>
        <button class="save-row" type="button" data-save-id="${row.id}" aria-label="${savedIds.includes(row.id) ? "Remove" : "Save"} ${escapeHtml(row.name)} ${savedIds.includes(row.id) ? "from" : "to"} comparison" aria-pressed="${savedIds.includes(row.id)}">${savedIds.includes(row.id) ? "Saved" : "Save"}</button>
      </div>
    `).join("")}
  `;

  document.querySelectorAll(".table-row[data-id]").forEach((row) => {
    const choose = () => {
      selectedId = row.dataset.id;
      renderAll();
    };
    row.addEventListener("click", choose);
    row.addEventListener("keydown", event => {
      if (event.target === row && (event.key === "Enter" || event.key === " ")) {event.preventDefault(); choose();}
    });
  });
  document.querySelectorAll("[data-save-id]").forEach(button => button.addEventListener("click", event => {
    event.stopPropagation();
    toggleSavedLocation(button.dataset.saveId);
  }));
  table.scrollTop = previousTop;
  table.scrollLeft = previousLeft;
}

function revealSelectedRanking() {
  const table = document.querySelector("#rankingTable");
  const row = [...table.querySelectorAll(".table-row[data-id]")].find(item => item.dataset.id === selectedId);
  if (!row) return;
  const rowBounds = row.getBoundingClientRect();
  const tableBounds = table.getBoundingClientRect();
  const headerHeight = table.querySelector(".table-row.header")?.getBoundingClientRect().height || 0;
  if (rowBounds.top < tableBounds.top + headerHeight) table.scrollTop += rowBounds.top - tableBounds.top - headerHeight;
  else if (rowBounds.bottom > tableBounds.bottom) table.scrollTop += rowBounds.bottom - tableBounds.bottom;
}

function displayNumber(value) {
  return value === null || value === undefined ? "Unavailable" : Math.round(value).toLocaleString("en-US");
}

function renderMarketProfile() {
  const location = selectedLocation();
  const profile = location.market_profile || {};
  const measure = (label, value, basis) => `<div class="market-measure"><span>${label}</span><strong>${value}</strong><small>${basis}</small></div>`;
  document.querySelector("#scorecardBoard").innerHTML = `
    <div class="view-heading"><div><span class="eyebrow">${escapeHtml(location.borough)} / ${escapeHtml(profile.neighborhood || "NYC")}</span><h3>${escapeHtml(location.name)}</h3></div><button class="quiet-action" type="button" id="marketCompetition">View Competition</button></div>
    <div class="market-group"><h3>Local Customer Base</h3><div class="market-measures">
      ${measure("Residents", displayNumber(profile.population), "2020-2024 ACS five-year estimate")}
      ${measure("Jobs", displayNumber(profile.jobs), "2023 LODES workplace employment")}
      ${measure("Median Household Income", profile.median_household_income == null ? "Unavailable" : fmtDollar(profile.median_household_income), profile.income_margin_of_error == null ? "2020-2024 ACS five-year estimate" : `2020-2024 ACS five-year estimate · ±${fmtDollar(profile.income_margin_of_error)}`)}
    </div></div>
    <div class="market-group"><h3>Access And Movement</h3><div class="market-measures">
      ${measure("Walkability", location.walkability == null ? "Unavailable" : `${location.walkability}/100`, "EPA built-environment index")}
      ${measure("Nearest Subway", profile.subway_distance_miles == null ? "Unavailable" : `${Number(profile.subway_distance_miles).toFixed(2)} mi`, escapeHtml(profile.nearest_subway_station || "Nearest complex"))}
      ${measure("Subway Entries", displayNumber(profile.nearest_subway_weekly_ridership), escapeHtml(profile.subway_vintage || "Nearest station · one complete week"))}
      ${profile.nearest_subway_dayparts ? measure("Weekday Morning Entries", displayNumber(profile.nearest_subway_dayparts.morning), "7-10 AM · four sampled 2025 weeks") : ""}
      ${profile.nearest_subway_dayparts ? measure("Weekday Midday Entries", displayNumber(profile.nearest_subway_dayparts.midday), "11 AM-2 PM · four sampled 2025 weeks") : ""}
      ${profile.nearest_subway_dayparts ? measure("Weekday Evening Entries", displayNumber(profile.nearest_subway_dayparts.evening), "5-9 PM · four sampled 2025 weeks") : ""}
      ${measure("Citi Bike Departures", displayNumber(profile.bike_departures_latest_month ?? profile.bike_departures_august_2026), `Tract stations · ${profile.bike_activity_month ? new Date(`${profile.bike_activity_month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) : "August 2026"}`)}
      ${measure("Pedestrian Count", displayNumber(profile.pedestrian_counter_latest), profile.pedestrian_counter_distance_miles == null ? "Nearest monitor · observation date unavailable" : `Nearest monitor · ${Number(profile.pedestrian_counter_distance_miles).toFixed(2)} mi away · date unavailable`)}
    </div></div>
    <div class="market-group"><h3>Commercial Context</h3><div class="market-measures">
      ${measure("Recorded Restaurants", displayNumber(profile.active_restaurants), "DOHMH tract records")}
      ${measure("Reported Vacant Storefronts", displayNumber(profile.reported_vacant_storefronts), "Registry filings; availability unverified")}
      ${measure("Business Draw", `${location.business_draw}/100`, "Concept-specific screening index")}
    </div></div>
    <div class="catchment-result" id="catchmentResult"><button class="primary-action" type="button" id="analyzeCatchment">Analyze 10-Minute Walk</button><span>From Tract Centroid</span></div>
  `;
  document.querySelector("#marketCompetition").addEventListener("click", () => selectView("whitespace"));
  const cached = catchmentCache.get(`${location.id}:${dashboard.meta.concept.cuisine}`);
  if (cached) renderCatchmentResult(cached);
  else document.querySelector("#analyzeCatchment").addEventListener("click", analyzeSelectedCatchment);
}

function renderCatchmentResult(evidence) {
  const container = document.querySelector("#catchmentResult");
  container.innerHTML = evidence.status === "available" ? `<div class="market-measures">
    <div class="market-measure"><span>Reachable Restaurants</span><strong>${displayNumber(evidence.recorded_restaurants)}</strong><small>DOHMH records · 10-minute walk</small></div>
    <div class="market-measure"><span>Subway Stations</span><strong>${displayNumber(evidence.nearby_subway_stations)}</strong><small>Reachable from tract centroid</small></div>
    <div class="market-measure"><span>Same Cuisine</span><strong>${displayNumber(evidence.same_cuisine_restaurants)}</strong><small>Classified restaurants only</small></div>
  </div>` : `<span>Walking Network Unavailable For This Tract Centroid.</span>`;
}

async function analyzeSelectedCatchment() {
  const location = selectedLocation();
  const cuisine = dashboard.meta.concept.cuisine;
  const container = document.querySelector("#catchmentResult");
  container.innerHTML = "<span>Analyzing Walk Network...</span>";
  try {
    const response = await fetch("/api/sites/analyze", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({latitude: location.latitude, longitude: location.longitude, cuisine, profile: state.profile, dietary: state.dietary})});
    if (!response.ok) throw new Error("Catchment request failed");
    const result = await response.json();
    if (selectedId !== location.id) return;
    catchmentCache.set(`${location.id}:${cuisine}`, result.site_evidence);
    renderCatchmentResult(result.site_evidence);
  } catch {
    container.innerHTML = '<span>Walking Analysis Unavailable.</span><button class="quiet-action" type="button" id="retryCatchment">Retry</button>';
    document.querySelector("#retryCatchment").addEventListener("click", analyzeSelectedCatchment);
  }
}

function renderCompare() {
  const candidates = savedIds.map(id => allLocations().find(row => row.id === id)).filter(Boolean);
  const available = dashboard.locations.filter(row => !savedIds.includes(row.id));
  const addControl = savedIds.length < 4 ? `<select id="addComparison" aria-label="Add Location To Comparison"><option value="">Add Location</option>${available.map(row => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join("")}</select>` : "";
  if (!candidates.length) {
    document.querySelector("#compareBoard").innerHTML = `<div class="comparison-empty"><h3>No Saved Locations Yet</h3><p>Select locations from Explore or add one here.</p>${addControl}</div>`;
  } else {
    const rows = [
      ["Location Score", "opportunity"], ["Business Draw", "business_draw"],
      ["Customer Fit", "customer"], ["Cuisine Opportunity", "whitespace"],
      ["Walkability", "walkability"], ["Commercial Fit", "cost"],
      ["Evidence Strength", "confidence_score"],
    ];
    const leader = [...candidates].sort((a, b) => b.opportunity - a.opportunity)[0];
    const differential = candidates.length > 1 ? Math.max(...candidates.map(row => row.opportunity)) - Math.min(...candidates.map(row => row.opportunity)) : null;
    document.querySelector("#compareBoard").innerHTML = `
      <div class="comparison-toolbar"><span>${candidates.length} Of 4 Locations Saved</span>${addControl}</div>
      <div class="comparison-scroll"><table class="comparison-table"><thead><tr><th scope="col">Measure</th>${candidates.map(row => `<th scope="col"><button type="button" class="comparison-place" data-open-id="${row.id}">${escapeHtml(row.name)}</button><button type="button" class="comparison-remove" data-remove-id="${row.id}" aria-label="Remove ${escapeHtml(row.name)}">×</button></th>`).join("")}</tr></thead><tbody>
      ${rows.map(([label, key]) => {
        const values = candidates.map(row => row[key]).filter(value => value != null);
        const max = Math.max(...values);
        return `<tr><th scope="row">${label}</th>${candidates.map(row => `<td class="${row[key] != null && row[key] === max && candidates.length > 1 ? "comparison-best" : ""}">${row[key] ?? "--"}${key === "confidence_score" ? "%" : ""}</td>`).join("")}</tr>`;
      }).join("")}
      <tr><th scope="row">Recorded Restaurants</th>${candidates.map(row => `<td>${displayNumber(row.market_profile?.active_restaurants)}</td>`).join("")}</tr>
      <tr><th scope="row">Local Residents</th>${candidates.map(row => `<td>${displayNumber(row.market_profile?.population)}</td>`).join("")}</tr>
      <tr><th scope="row">Nearby Jobs</th>${candidates.map(row => `<td>${displayNumber(row.market_profile?.jobs)}</td>`).join("")}</tr>
      </tbody></table></div>
      <div class="comparison-summary"><strong>${escapeHtml(leader.name)}</strong><span>${candidates.length === 1 ? "Add Another Location For A Direct Comparison." : `${differential}-Point Spread In Location Scores. Compare The Underlying Customer, Access And Competition Measures Before Deciding.`}</span></div>`;
  }
  document.querySelector("#addComparison")?.addEventListener("change", event => {
    if (event.target.value) toggleSavedLocation(event.target.value);
  });
  document.querySelectorAll("[data-remove-id]").forEach(button => button.addEventListener("click", () => toggleSavedLocation(button.dataset.removeId)));
  document.querySelectorAll("[data-open-id]").forEach(button => button.addEventListener("click", () => {
    selectedId = button.dataset.openId;
    renderAll();
    selectView("scorecard");
  }));
}

function renderLease() {
  let candidates = dashboard.properties || [];
  document.querySelector("#propertyHeading").textContent = state.dealType === "purchase" ? "Purchase Properties" : state.dealType === "either" ? "Lease & Purchase Properties" : "Lease Properties";
  if (state.preferredArea) {
    candidates = candidates.filter((row) => row.borough === state.preferredArea);
  }
  const listingCount = candidates.filter(row => row.lead_type === "listing").length;
  const registryCount = candidates.length - listingCount;
  const filter = `<div class="property-toolbar"><span>${listingCount} Source-Linked Listings · ${registryCount} Storefront Records</span><div class="segmented-control" role="group" aria-label="Property Records"><button type="button" data-property-view="all" aria-pressed="${propertyView === "all"}">All</button><button type="button" data-property-view="listing" aria-pressed="${propertyView === "listing"}">Listings</button>${state.dealType !== "purchase" ? `<button type="button" data-property-view="registry_record" aria-pressed="${propertyView === "registry_record"}">Research Records</button>` : ""}</div></div>`;
  if (state.dealType === "purchase" && propertyView === "registry_record") propertyView = "all";
  if (propertyView !== "all") candidates = candidates.filter(row => row.lead_type === propertyView);
  if (!candidates.length) {
    const emptyTitle = state.dealType === "purchase" ? "No Current Purchase Listings" : propertyView === "listing" ? "No Current Lease Listings" : "No Current Property Records Found";
    document.querySelector("#leaseBoard").innerHTML = `
      ${filter}
      <article class="property-empty">
        <h3>${emptyTitle}</h3>
        <button class="quiet-action" type="button" onclick="openBrief()">Edit Search Brief</button>
      </article>
    `;
    bindPropertyFilters();
    return;
  }
  document.querySelector("#leaseBoard").innerHTML = filter + candidates.map((row) => {
    const priceLine = row.price_label || "Unavailable";
    const imageClass = row.image ? "property-image" : "property-image no-image";
    const imageStyle = row.image ? ` style="background-image:url('${escapeHtml(row.image.replaceAll("'", "%27"))}')"` : "";
    const badge = row.transaction_label || "Property Record";
    const sqft = row.sqft ? `${row.sqft.toLocaleString()} Sq Ft` : (row.sqft_label || "Sq Ft Not In Source");
    const contactUrl = row.broker_contact && /^https:\/\/[^\s]+$/i.test(row.broker_contact) ? row.broker_contact : null;
    return `
      <article class="property-card">
        <div class="${imageClass}"${imageStyle}>
          <span>${escapeHtml(badge)}</span>
          ${row.image ? "" : `<strong>Photo Unavailable</strong>`}
        </div>
        <div class="property-body">
          <div class="property-title">
            <div>
              <h3>${escapeHtml(row.title)}</h3>
              <p>${escapeHtml(row.address)}</p>
            </div>
            <div class="property-area-score"><span>Area Score</span><strong class="${scoreClass(row.fit_score)}">${row.fit_score}</strong></div>
          </div>
          <div class="property-specs">
            <span>${escapeHtml(row.location_name)}</span>
            ${row.sqft ? `<span>${sqft}</span>` : ""}
          </div>
          ${row.site_evidence?.status === "available" ? `<div class="kv"><span>Approx. 10-Minute Walk</span><strong>${row.site_evidence.recorded_restaurants.toLocaleString()} Restaurants · ${row.site_evidence.nearby_subway_stations} Subway Stations</strong></div>` : ""}
          ${row.site_evidence?.same_cuisine_restaurants != null ? `<div class="kv"><span>Recorded Same-Cuisine Restaurants</span><strong>${row.site_evidence.same_cuisine_restaurants}</strong></div>` : ""}
          ${row.site_evidence?.status === "unavailable" ? '<div class="kv"><span>Walking Catchment</span><strong>Unavailable</strong></div>' : ""}
          <div class="kv"><span>${row.transaction === "purchase" ? "Asking Price" : row.transaction === "lease" ? "Asking Rent" : "Asking Price / Rent"}</span><strong>${escapeHtml(priceLine)}</strong></div>
          <div class="kv"><span>Status</span><strong>${escapeHtml(row.availability)}</strong></div>
          ${row.checked_at ? `<div class="kv"><span>Source Checked</span><strong>${escapeHtml(row.checked_at)}</strong></div>` : ""}
          ${row.broker_name ? `<div class="kv"><span>Broker / Owner</span><strong>${escapeHtml(row.broker_name)}</strong></div>` : ""}
          ${row.broker_contact && !contactUrl ? `<div class="kv"><span>Leasing Contact</span><strong>${escapeHtml(row.broker_contact)}</strong></div>` : ""}
          <div class="kv"><span>${row.lead_type === "registry_record" ? "Reported Activity" : "Condition"}</span><strong>${escapeHtml(row.condition)}</strong></div>
          ${row.lead_type === "registry_record" ? '<div class="property-source-note">Registry Record · Transaction And Contact Unverified</div>' : ""}
          ${row.source_url ? `<a class="property-link" href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener noreferrer">Source Listing</a>` : ""}
          ${contactUrl ? `<a class="property-link" href="${escapeHtml(contactUrl)}" target="_blank" rel="noopener noreferrer">Contact Leasing Office</a>` : ""}
          <a class="property-link" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${row.address}, ${row.borough}, New York`)}" target="_blank" rel="noopener noreferrer">View Address</a>
        </div>
      </article>
    `;
  }).join("");
  bindPropertyFilters();
}

function bindPropertyFilters() {
  document.querySelectorAll("[data-property-view]").forEach(button => button.addEventListener("click", () => {
    propertyView = button.dataset.propertyView;
    renderLease();
  }));
}

function renderWhitespace() {
  const location = selectedLocation();
  const key = `${location.id}:${dashboard.meta.concept.cuisine}`;
  const market = competitionCache.get(key);
  const board = document.querySelector("#gapBoard");
  if (!market) {
    board.innerHTML = `<div class="comparison-empty"><h3>${escapeHtml(location.name)}</h3><p>Loading Restaurant Inventory...</p></div>`;
    return;
  }
  const evidence = location.concept_evidence;
  board.innerHTML = `
    <div class="view-heading"><div><span class="eyebrow">${escapeHtml(cuisineLabel())} / ${escapeHtml(market.neighborhood || location.borough)}</span><h3>${escapeHtml(location.name)}</h3></div><span class="card-status">${escapeHtml(evidence.positioning)}</span></div>
    <div class="market-measures">
      <div class="market-measure"><span>Restaurants In Tract</span><strong>${displayNumber(market.tract_restaurant_count)}</strong><small>Active DOHMH records</small></div>
      <div class="market-measure"><span>Same Cuisine In Tract</span><strong>${displayNumber(market.tract_same_cuisine_count)}</strong><small>DOHMH cuisine classification</small></div>
      <div class="market-measure"><span>Same Cuisine In Neighborhood</span><strong>${displayNumber(market.neighborhood_same_cuisine_count)}</strong><small>${escapeHtml(market.neighborhood || "NTA")}</small></div>
      <div class="market-measure"><span>Cuisine Label Coverage</span><strong>${evidence.cuisine_label_coverage}%</strong><small>Tract inventory</small></div>
    </div>
    <div class="restaurant-list"><div class="view-heading"><h3>Recorded Restaurants</h3><span id="restaurantCount">${market.restaurants.length} Shown</span></div>
      <input class="restaurant-search" id="restaurantSearch" type="search" placeholder="Search Restaurant, Cuisine Or Address" aria-label="Search Recorded Restaurants" />
      <div id="restaurantRows"></div>
    </div>`;
  const drawRows = (query = "") => {
    const needle = query.toLowerCase().trim();
    const rows = market.restaurants.filter(row => `${row.name} ${row.cuisine} ${row.address}`.toLowerCase().includes(needle));
    document.querySelector("#restaurantCount").textContent = `${rows.length} Of ${market.restaurants.length} Shown`;
    document.querySelector("#restaurantRows").innerHTML = rows.length ? rows.map(row => `<div class="restaurant-row"><div><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.address || "Address Unavailable")}</span></div><span>${escapeHtml(row.cuisine)}</span>${row.same_cuisine ? '<b>Same Cuisine</b>' : ""}</div>`).join("") : '<div class="comparison-empty">No Matching Restaurants.</div>';
  };
  document.querySelector("#restaurantSearch").addEventListener("input", event => drawRows(event.target.value));
  drawRows();
}

async function loadCompetition() {
  if (!dashboard || activeView !== "whitespace") return;
  const location = selectedLocation();
  const cuisine = dashboard.meta.concept.cuisine;
  const key = `${location.id}:${cuisine}`;
  if (competitionCache.has(key)) return renderWhitespace();
  const current = ++competitionRequest;
  renderWhitespace();
  try {
    const response = await fetch(`/api/locations/${encodeURIComponent(location.id)}/competition?cuisine=${encodeURIComponent(cuisine)}`);
    if (!response.ok) throw new Error("Competition request failed");
    const market = await response.json();
    competitionCache.set(key, market);
    if (current === competitionRequest && activeView === "whitespace" && selectedId === location.id) renderWhitespace();
  } catch {
    if (current === competitionRequest && activeView === "whitespace") {
      document.querySelector("#gapBoard").innerHTML = `<div class="comparison-empty"><h3>Restaurant Inventory Unavailable</h3><button class="quiet-action" id="retryCompetition" type="button">Retry</button></div>`;
      document.querySelector("#retryCompetition").addEventListener("click", loadCompetition);
    }
  }
}

function renderFinance() {
  const finance = dashboard.finance;
  document.querySelector("#financeScenarioForm").hidden = state.dealType === "purchase";
  if (state.dealType === "purchase") {
    const askingPrices = (dashboard.properties || []).filter(row => row.transaction === "purchase" && row.asking_price).map(row => row.asking_price);
    const lowestAskingPrice = askingPrices.length ? fmtPrice(Math.min(...askingPrices)) : "Unavailable";
    document.querySelector("#financeBoard").innerHTML = `
      <article class="finance-cell"><h3>Purchase Budget</h3><strong class="finance-figure">${fmtPrice(state.purchaseBudget)}</strong><span class="finance-basis">User Budget</span></article>
      <article class="finance-cell"><h3>Lowest Listed Asking Price</h3><strong class="finance-figure">${lowestAskingPrice}</strong><span class="finance-basis">${askingPrices.length ? `${askingPrices.length} Source-Linked Listing${askingPrices.length === 1 ? "" : "s"}` : "No Current Sale Listing"}</span></article>
    `;
    return;
  }
  const cells = [
    ["Monthly Rent Target", fmtDollar(finance.rent_target), "User Budget"],
    ["Guest Spend", fmtDollar(finance.guest_spend), state.priceMode === "tier" ? `${state.priceTier} Tier Assumption` : "User Estimate"],
  ];
  if (finance.status === "ready") {
    cells.push(["Required Monthly Sales", fmtDollar(finance.required_monthly_sales), "Entered Cost Scenario"]);
    cells.push(["Required Covers", `${finance.required_covers_per_day}/Day`, `${finance.operating_days} Operating Days`]);
  } else {
    cells.push(["Operating Scenario", "Pending", "Enter Cost Assumptions"]);
  }
  const rentBenchmarks = dashboard.rent_benchmarks || {};
  const tractRent = rentBenchmarks.by_geoid?.[selectedLocation().id];
  const reportedRent = tractRent?.reported_median_monthly_rent_psf;
  const rentContext = `<div class="finance-rent-benchmark">
    <span>${rentBenchmarks.reporting_year || "NYC"} Reported Occupied Rent</span>
    <strong>${reportedRent != null ? `${fmtDollar(reportedRent)}/SF/Month` : "Not Reported For This Tract"}</strong>
    <small>NYC DOF · Not An Asking Rent</small>
  </div>`;
  document.querySelector("#financeBoard").innerHTML = cells.map(([label, value, sub]) => `
    <article class="finance-cell">
      <h3>${label}</h3>
      <strong class="finance-figure">${value}</strong>
      <span class="finance-basis">${sub}</span>
    </article>
  `).join("") + (finance.status === "ready" ? `
    <section class="finance-sensitivity"><h3>Guest Spend Sensitivity</h3><div class="sensitivity-grid">
      ${[0.8, 1, 1.2].map((factor, index) => {
        const spend = finance.guest_spend * factor;
        const covers = Math.ceil((finance.rent_target + finance.other_fixed_costs) / (1 - finance.variable_cost_pct / 100) / spend / finance.operating_days);
        return `<div><span>${["20% Lower", "Entered Spend", "20% Higher"][index]}</span><strong>${covers} Covers / Day</strong><small>${fmtDollar(spend)} Per Guest</small></div>`;
      }).join("")}
    </div></section>` : "") + rentContext;
}

function renderReports() {
  const location = selectedLocation();
  const alternatives = savedIds.filter(id => id !== location.id).map(id => allLocations().find(row => row.id === id)).filter(Boolean);
  document.querySelector("#reportBoard").innerHTML = `
    <div class="report-toolbar"><span>Location Brief</span><button class="primary-action" id="printReport" type="button">Print / Save PDF</button></div>
    <article class="location-report">
      <header><span class="eyebrow">Groundwork / New York City</span><span>${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span></header>
      <h2>${escapeHtml(conceptName())}</h2>
      <p>${profileLabel(state.profile)} · ${escapeHtml(cuisineLabel())} · ${state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`} · ${dealLabel(state.dealType)} · ${state.dealType === "purchase" ? `${fmtPrice(state.purchaseBudget)} Purchase Budget` : `${fmtMoney(state.rentCap)}/Month Budget`}</p>
      <section class="report-recommendation"><div><span class="eyebrow">Selected Location</span><h3>${escapeHtml(location.name)}</h3><p>${escapeHtml(location.recommendation)}</p></div><strong>${location.opportunity}<small>/100</small></strong></section>
      ${alternatives.length ? `<h3>Saved Alternatives</h3><div class="report-factors">${alternatives.map(row => `<div class="kv"><span>${escapeHtml(row.name)}</span><strong>${row.opportunity}/100</strong></div>`).join("")}</div>` : ""}
      <h3>Location Factors</h3>
      <div class="report-factors">${location.score_components.map((item) => `<div class="kv"><span>${escapeHtml(item.label)}</span><strong>${item.score}/100</strong></div>`).join("")}</div>
      <h3>Due Diligence</h3><ul>${location.risk_flags.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")}</ul>
      <footer>${location.confidence_score}% Evidence Strength · Preliminary Tract-Level Screening<br>Walkability ${location.walkability ?? "Unavailable"}/100 · Business Draw ${location.business_draw}/100<br>Scores Are Relative Indicators, Not Visit Or Revenue Forecasts.<br>Property Availability, Asking Prices And Lease Terms Require Verification.</footer>
    </article>
  `;
  document.querySelector("#printReport").addEventListener("click", () => window.print());
}

function renderDataLayers() {
  document.querySelector("#layerBoard").innerHTML = `
    <div class="view-heading"><div><span class="eyebrow">Data Register</span><h3>Sources & Coverage</h3></div></div>
    <div class="source-table"><div class="source-row source-row--head"><span>Source</span><span>Vintage / Geography</span><span>Coverage</span></div>
    ${dashboard.feeds.map(row => `<div class="source-row"><strong>${row.url ? `<a href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(row.name)}</a>` : escapeHtml(row.name)}</strong><span>${escapeHtml(row.vintage)}<small>${escapeHtml(row.grain)}</small></span><span>${escapeHtml(row.coverage)}<small>${escapeHtml(row.purpose)}</small></span></div>`).join("")}</div>
    <div class="source-limitations"><h3>Not Available In This Search</h3><div>${dashboard.meta.unsupported_values.map(value => `<span>${escapeHtml(value)}</span>`).join("")}</div></div>`;
}

function menuKey() {
  return `groundwork-menu-v2:${JSON.stringify([window.GROUNDWORK_MENU_OWNER || "guest", normalizeConceptText(conceptName()), state.cuisine, state.profile, state.dietary])}`;
}

function syncSavedMenu() {
  const key = menuKey();
  if (key === menuSavedKey) return;
  menuSavedKey = key;
  try {
    const spend = state.priceMode === "tier" ? PRICE_DEFAULTS[state.priceTier] : state.averageCheck;
    const oldKey = `groundwork-menu-v1:${JSON.stringify([normalizeConceptText(conceptName()), state.cuisine, state.profile, state.dietary, spend])}`;
    const stored = JSON.parse(localStorage.getItem(key) || localStorage.getItem(oldKey) || "[]");
    savedMenu = Array.isArray(stored) ? stored.filter(item => item && typeof item.id === "string" &&
      typeof item.name === "string" && menuSections.includes(item.section)).slice(0, 100) : [];
    if (!localStorage.getItem(key) && savedMenu.length) localStorage.setItem(key, JSON.stringify(savedMenu));
  } catch {
    savedMenu = [];
  }
}

function persistMenu(message = "Saved On This Device") {
  try {
    localStorage.setItem(menuSavedKey, JSON.stringify(savedMenu));
    document.querySelector("#menuSaveStatus").textContent = accountOwner && workspaceReady ? "Saving To Account..." : message;
    queueWorkspaceSync();
  } catch {
    document.querySelector("#menuSaveStatus").textContent = "Browser Storage Is Unavailable. Export Your Menu Before Leaving.";
  }
}

async function loadMenuSuggestions() {
  syncSavedMenu();
  const key = menuKey();
  if (key === menuCatalogKey && menuCatalog) return renderMenu();
  const currentRequest = ++menuRequestId;
  menuCatalogKey = key;
  menuCatalog = null;
  renderMenu();
  try {
    const response = await fetch(`/api/menu/suggestions?${conceptParams()}`);
    if (!response.ok) throw new Error("Menu suggestions unavailable");
    const result = await response.json();
    if (currentRequest !== menuRequestId || key !== menuKey()) return;
    menuCatalog = result;
    renderMenu();
  } catch {
    if (currentRequest === menuRequestId) {
      menuCatalog = {status: "error", items: [], message: "Dish Ideas Are Temporarily Unavailable."};
      renderMenu();
    }
  }
}

function renderMenuSuggestions() {
  const container = document.querySelector("#menuSuggestions");
  if (!menuCatalog) {
    container.innerHTML = '<div class="menu-empty">Loading Dish Ideas...</div>';
    document.querySelector("#menuSuggestionCount").textContent = "";
    return;
  }
  const query = document.querySelector("#menuSearch").value.trim().toLowerCase();
  const section = document.querySelector("#menuSectionFilter").value;
  const items = (menuCatalog.items || []).filter(item => (section === "all" || item.section === section) && item.name.toLowerCase().includes(query));
  document.querySelector("#menuSuggestionCount").textContent = `${items.length} Ideas`;
  if (!items.length) {
    const message = menuCatalog.status === "unavailable" || menuCatalog.status === "error" ? menuCatalog.message : "No Matching Dishes";
    container.innerHTML = `<div class="menu-empty">${escapeHtml(message)}</div>`;
    return;
  }
  container.innerHTML = items.map(item => {
    const added = savedMenu.some(saved => saved.id === item.id);
    const review = item.review_signal;
    return `<div class="menu-idea">
      <div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.section)}${review ? ` · ${review.mention_count} Attributed Review Mentions` : ""}</span></div>
      <button type="button" class="menu-add" data-menu-add="${escapeHtml(item.id)}" ${added ? "disabled" : ""} aria-label="${added ? "Added" : "Add"} ${escapeHtml(item.name)} To Menu">${added ? "Added" : "+ Add"}</button>
    </div>`;
  }).join("");
}

function renderMenu() {
  if (activeView !== "menu") return;
  syncSavedMenu();
  const cuisine = state.cuisine;
  const label = cuisine === "any" ? profileLabel(state.profile) : `${titleCase(cuisine.replaceAll("_", " "))} · ${profileLabel(state.profile)}`;
  document.querySelector("#menuContext").textContent = label;
  document.querySelector("#menuItemCount").textContent = `${savedMenu.length} ${savedMenu.length === 1 ? "Item" : "Items"}`;
  document.querySelector("#menuExport").disabled = !savedMenu.length;
  document.querySelector("#menuPrint").disabled = !savedMenu.length;
  const priced = savedMenu.filter(item => Number(item.price) > 0);
  const costed = priced.filter(item => item.cost !== "" && item.cost != null && Number(item.cost) >= 0);
  const averagePrice = priced.length ? priced.reduce((sum, item) => sum + Number(item.price), 0) / priced.length : null;
  const averageMargin = costed.length ? costed.reduce((sum, item) => sum + (Number(item.price) - Number(item.cost)) / Number(item.price), 0) / costed.length : null;
  document.querySelector("#menuKpis").innerHTML = [
    ["Dishes", String(savedMenu.length)],
    ["Average Price", averagePrice == null ? "—" : money(averagePrice)],
    ["Costed Items", `${costed.length} / ${savedMenu.length}`],
    ["Average Item Margin", averageMargin == null ? "—" : `${Math.round(averageMargin * 100)}%`],
  ].map(([name, value]) => `<div class="menu-kpi"><span>${name}</span><strong>${value}</strong></div>`).join("");
  document.querySelector(".menu-workspace").hidden = menuView !== "plan";
  document.querySelector("#menuPreview").hidden = menuView !== "preview";
  document.querySelectorAll("[data-menu-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.menuView === menuView)));
  renderMenuSuggestions();
  const groups = menuSections.map(section => [section, savedMenu.filter(item => item.section === section)]).filter(([, items]) => items.length);
  document.querySelector("#menuSaved").innerHTML = groups.length ? groups.map(([section, items]) => `
    <div class="menu-saved-section"><h4>${section}</h4>${items.map(item => `<div class="menu-saved-item" data-menu-id="${escapeHtml(item.id)}">
      <label class="menu-item-name"><span class="sr-only">Dish Name</span><input data-menu-name maxlength="80" value="${escapeHtml(item.name)}" aria-label="Dish Name" /></label>
      <select data-menu-section aria-label="Section For ${escapeHtml(item.name)}">${menuSections.map(option => `<option${option === section ? " selected" : ""}>${option}</option>`).join("")}</select>
      <label class="menu-price"><small>Menu Price</small><span>$</span><input type="number" data-menu-price min="0" max="1000" step="0.01" value="${escapeHtml(item.price ?? "")}" placeholder="0.00" aria-label="Planned Price For ${escapeHtml(item.name)}" /></label>
      <label class="menu-price"><small>Ingredient Cost</small><span>$</span><input type="number" data-menu-cost min="0" max="1000" step="0.01" value="${escapeHtml(item.cost ?? "")}" placeholder="0.00" aria-label="Ingredient Cost Per Portion For ${escapeHtml(item.name)}" /></label>
      <span class="menu-margin">${Number(item.price) > 0 && item.cost !== "" && item.cost != null ? `${Math.round((Number(item.price) - Number(item.cost)) / Number(item.price) * 100)}% margin` : "—"}</span>
      <div class="menu-order"><button type="button" data-menu-move="up" aria-label="Move ${escapeHtml(item.name)} Up" title="Move Up">↑</button><button type="button" data-menu-move="down" aria-label="Move ${escapeHtml(item.name)} Down" title="Move Down">↓</button></div>
      <button type="button" class="menu-remove" data-menu-remove title="Remove ${escapeHtml(item.name)}" aria-label="Remove ${escapeHtml(item.name)}">×</button>
      <input class="menu-note" type="text" data-menu-note maxlength="200" value="${escapeHtml(item.note || "")}" placeholder="Description shown on menu" aria-label="Description For ${escapeHtml(item.name)}" />
    </div>`).join("")}</div>`).join("") : '<div class="menu-empty">No Dishes Added Yet.</div>';
  document.querySelector("#menuPreview").innerHTML = `<div class="menu-preview-head"><span>Groundwork Menu</span><h3>${escapeHtml(conceptName())}</h3><p>${escapeHtml(label)}</p></div>${groups.length ? groups.map(([section, items]) => `<section><h4>${section}</h4>${items.map(item => `<div class="menu-preview-item"><div><strong>${escapeHtml(item.name)}</strong>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}</div><span>${Number(item.price) > 0 ? money(Number(item.price)) : ""}</span></div>`).join("")}</section>`).join("") : '<div class="menu-empty">Add dishes to preview your menu.</div>'}`;
}

function money(value) { return `$${Number(value).toFixed(2)}`; }

function exportMenu() {
  if (!savedMenu.length) return;
  const quote = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [["section", "dish", "planned_price_usd", "ingredient_cost_usd", "item_margin_percent", "description", "source"],
    ...savedMenu.map(item => [item.section, item.name, item.price || "", item.cost ?? "",
      Number(item.price) > 0 && item.cost !== "" && item.cost != null ? Math.round((Number(item.price) - Number(item.cost)) / Number(item.price) * 100) : "",
      item.note || "", item.custom ? "custom" : "editorial_catalog"])];
  const csv = rows.map(row => row.map(quote).join(",")).join("\r\n") + "\r\n";
  const url = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${normalizeConceptText(conceptName()).replace(/[^a-z0-9]+/g, "-") || "groundwork"}-menu.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderPanels() {
  document.querySelector(".workspace")?.classList.toggle("is-discover", activeView === "discover");
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("is-hidden", panel.dataset.panel !== activeView);
  });
  if (activeView === "discover" && locationMap) requestAnimationFrame(() => locationMap.resize());
  if (activeView === "whitespace") loadCompetition();
}

function renderAll() {
  renderConceptChrome();
  renderLocationSelect();
  renderMetrics();
  renderMap();
  renderIntel();
  renderRanking();
  renderMarketProfile();
  renderCompare();
  renderLease();
  renderWhitespace();
  renderFinance();
  renderReports();
  renderDataLayers();
  renderPanels();
  renderMenu();
}

function renderConceptChrome() {
  const name = conceptName();
  document.querySelector("#workspaceTitle").textContent = activeView === "menu" ? `${name} Menu` : `${name} Location Search`;
  document.querySelector("#activeConceptName").textContent = name;
  document.querySelector("#activeFormat").textContent = `${dealLabel(state.dealType)} · ${profileLabel(state.profile)}`;
  document.querySelector("#activeCuisine").textContent = state.cuisine === "custom"
    ? (document.querySelector("#briefCustomCuisine").value.trim() || "Other Cuisine") : cuisineLabel();
  document.querySelector("#activePrice").textContent = state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`;
  document.querySelector("#activeArea").textContent = state.preferredArea || "Anywhere In NYC";
}

document.querySelectorAll(".feature-tab").forEach((button) => {
  button.addEventListener("click", () => {
    selectView(button.dataset.view);
    renderConceptChrome();
  });
});

document.querySelector("#menuSearch").addEventListener("input", renderMenuSuggestions);
document.querySelector("#menuSectionFilter").addEventListener("change", renderMenuSuggestions);
document.querySelector("#menuExport").addEventListener("click", exportMenu);
document.querySelector("#menuPrint").addEventListener("click", () => {
  menuView = "preview";
  renderMenu();
  window.print();
});
document.querySelectorAll("[data-menu-view]").forEach(button => button.addEventListener("click", () => {
  menuView = button.dataset.menuView;
  renderMenu();
}));
document.querySelector("#menuSuggestions").addEventListener("click", event => {
  const button = event.target.closest("[data-menu-add]");
  if (!button || !menuCatalog) return;
  const item = menuCatalog.items.find(candidate => candidate.id === button.dataset.menuAdd);
  if (!item || savedMenu.some(saved => saved.id === item.id) || savedMenu.length >= 100) return;
  savedMenu.push({id: item.id, name: item.name, section: item.section, price: "", cost: "", note: "", custom: false});
  persistMenu();
  renderMenu();
});
document.querySelector("#menuCustomForm").addEventListener("submit", event => {
  event.preventDefault();
  const input = document.querySelector("#menuCustomName");
  const name = input.value.trim();
  if (!name || savedMenu.length >= 100) return;
  if (savedMenu.some(item => item.name.toLowerCase() === name.toLowerCase())) {
    document.querySelector("#menuSaveStatus").textContent = "That Dish Is Already On Your Menu.";
    return;
  }
  savedMenu.push({id: `custom:${crypto.randomUUID()}`, name, section: document.querySelector("#menuCustomSection").value,
    price: "", cost: "", note: "", custom: true});
  input.value = "";
  persistMenu();
  renderMenu();
});
document.querySelector("#menuSaved").addEventListener("click", event => {
  const move = event.target.closest("[data-menu-move]");
  if (move) {
    const id = move.closest("[data-menu-id]")?.dataset.menuId;
    const current = savedMenu.findIndex(item => item.id === id);
    const sectionItems = savedMenu.map((item, index) => ({item, index})).filter(({item}) => item.section === savedMenu[current]?.section);
    const sectionPosition = sectionItems.findIndex(({index}) => index === current);
    const target = sectionItems[sectionPosition + (move.dataset.menuMove === "up" ? -1 : 1)];
    if (target) {
      [savedMenu[current], savedMenu[target.index]] = [savedMenu[target.index], savedMenu[current]];
      persistMenu();
      renderMenu();
    }
    return;
  }
  const button = event.target.closest("[data-menu-remove]");
  if (!button) return;
  const id = button.closest("[data-menu-id]")?.dataset.menuId;
  savedMenu = savedMenu.filter(item => item.id !== id);
  persistMenu();
  renderMenu();
});
document.querySelector("#menuSaved").addEventListener("change", event => {
  const id = event.target.closest("[data-menu-id]")?.dataset.menuId;
  const item = savedMenu.find(candidate => candidate.id === id);
  if (!item) return;
  if (event.target.matches("[data-menu-price]")) {
    const price = event.target.value;
    item.price = price && Number(price) > 0 && Number(price) <= 1000 ? price : "";
  } else if (event.target.matches("[data-menu-cost]")) {
    const cost = event.target.value;
    item.cost = cost !== "" && Number(cost) >= 0 && Number(cost) <= 1000 ? cost : "";
  } else if (event.target.matches("[data-menu-name]")) {
    const name = event.target.value.trim().slice(0, 80);
    if (!name) { renderMenu(); return; }
    item.name = name;
  } else if (event.target.matches("[data-menu-note]")) item.note = event.target.value.trim().slice(0, 200);
  else if (event.target.matches("[data-menu-section]")) item.section = event.target.value;
  persistMenu();
  renderMenu();
});

document.querySelector("#locationSelect").addEventListener("change", event => {
  selectedId = event.target.value;
  renderAll();
});

document.querySelector("#saveLocation").addEventListener("click", () => toggleSavedLocation(selectedId));

document.querySelectorAll(".layer").forEach((button) => {
  button.addEventListener("click", () => {
    setActiveLayer(button.dataset.layer);
  });
});

document.querySelectorAll(".mini-tab").forEach((button) => {
  button.addEventListener("click", () => {
    setActiveLayer(button.dataset.layer);
  });
});

function syncBriefControls() {
  document.querySelector("#briefCuisine").value = state.cuisine;
  document.querySelector("#briefAverageCheck").value = state.averageCheck;
  document.querySelector("#briefPriceTier").value = state.priceTier;
  document.querySelector("#briefDietary").value = state.dietary;
  document.querySelector("#briefDescription").value = state.description;
  document.querySelector("#briefPurchaseBudget").value = state.purchaseBudget;
  document.querySelector("#briefServiceStyle").value = state.serviceStyle;
  document.querySelector("#briefAudience").value = state.audience;
  document.querySelector("#briefDaypart").value = state.daypart;
  document.querySelector("#conceptInput").value = conceptName();
  document.querySelector("#briefConceptName").value = conceptName();
  document.querySelector("#profileSelect").value = state.profile;
  document.querySelector("#briefProfile").value = state.profile;
  document.querySelector("#dealSelect").value = state.dealType;
  document.querySelector("#briefDeal").value = state.dealType;
  document.querySelector("#briefBudget").value = String(state.rentCap);
  document.querySelector("#briefArea").value = state.preferredArea;
  document.querySelector("#rentRange").value = String(Math.round(state.rentCap / 1000));
  document.querySelector("#rentLabel").textContent = `$${Math.round(state.rentCap / 1000)}k`;
  document.querySelector("#financeFixedCosts").value = state.otherFixedCosts;
  document.querySelector("#financeVariableCosts").value = state.variableCostPct;
  document.querySelector("#financeOperatingDays").value = state.operatingDays;
  syncTransactionFields();
  syncPriceModeControls();
  updateConceptImage(state.cuisine);
  renderConceptChrome();
}

function closeBrief() {
  document.querySelector("#briefOverlay").classList.remove("is-open");
}

function openBrief() {
  syncBriefControls();
  document.querySelector("#briefOverlay").classList.add("is-open");
}

function applyBrief() {
  const ideaInput = document.querySelector("#briefConceptName");
  const suggestion = conceptSuggestionsFor(ideaInput.value)[0];
  if (suggestion && ideaInput.value.trim() !== state.conceptName &&
      document.querySelector("#briefCuisine").value === state.cuisine &&
      document.querySelector("#briefDietary").value === state.dietary &&
      document.querySelector("#briefProfile").value === state.profile) {
    chooseConceptSuggestion(suggestion, ideaInput, true);
  }
  state.cuisine = document.querySelector("#briefCuisine").value;
  state.priceTier = document.querySelector("#briefPriceTier").value;
  state.averageCheck = state.priceMode === "tier" ? PRICE_DEFAULTS[state.priceTier] : Number(document.querySelector("#briefAverageCheck").value);
  state.dietary = document.querySelector("#briefDietary").value;
  state.description = document.querySelector("#briefDescription").value.trim();
  state.purchaseBudget = Number(document.querySelector("#briefPurchaseBudget").value || 3000000);
  state.serviceStyle = document.querySelector("#briefServiceStyle").value;
  state.audience = document.querySelector("#briefAudience").value;
  state.daypart = document.querySelector("#briefDaypart").value;
  state.conceptName = document.querySelector("#briefConceptName").value.trim() || "Restaurant Concept";
  state.dealType = document.querySelector("#briefDeal").value;
  state.profile = document.querySelector("#briefProfile").value;
  state.preferredArea = document.querySelector("#briefArea").value;
  const budget = Number(document.querySelector("#briefBudget").value || 18000);
  state.rentCap = Math.max(8000, Math.min(35000, budget));
  selectedId = null;
  syncBriefControls();
  persistBrief();
  closeBrief();
  selectView("discover");
  loadDashboard();
}

document.querySelector("#dealSelect").addEventListener("change", (event) => {
  state.dealType = event.target.value;
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#briefDeal").addEventListener("change", (event) => {
  state.dealType = event.target.value;
  syncTransactionFields();
});

document.querySelector("#briefPriceTier").addEventListener("change", (event) => {
  if (state.priceMode === "tier") document.querySelector("#briefAverageCheck").value = PRICE_DEFAULTS[event.target.value];
});

document.querySelectorAll("[data-price-mode]").forEach(button => button.addEventListener("click", () => {
  state.priceMode = button.dataset.priceMode;
  syncPriceModeControls();
}));

document.querySelectorAll("[data-theme-choice]").forEach(button => button.addEventListener("click", () => setTheme(button.dataset.themeChoice)));

document.querySelectorAll("#conceptInput, #briefConceptName, #searchInput").forEach(input => {
  input.addEventListener("input", () => renderConceptSuggestions(input));
  input.addEventListener("focus", () => renderConceptSuggestions(input));
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeConceptSuggestions();
      return;
    }
    if (activeConceptInput !== input || !visibleSuggestions.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      selectedSuggestionIndex = (selectedSuggestionIndex + (event.key === "ArrowDown" ? 1 : -1) + visibleSuggestions.length) % visibleSuggestions.length;
      document.querySelectorAll(`#${input.getAttribute("aria-controls")} button`).forEach((button, index) => button.setAttribute("aria-selected", String(index === selectedSuggestionIndex)));
      input.setAttribute("aria-activedescendant", `${input.getAttribute("aria-controls")}Option${selectedSuggestionIndex}`);
    } else if (event.key === "Enter") {
      event.preventDefault();
      chooseConceptSuggestion(visibleSuggestions[selectedSuggestionIndex >= 0 ? selectedSuggestionIndex : 0], input);
    }
  });
  input.addEventListener("blur", () => {
    const query = input.value;
    setTimeout(() => {
      if (input.value !== query || !query.trim()) return;
      if (input.id === "briefConceptName" && !document.querySelector("#briefOverlay").classList.contains("is-open")) return;
      if (input.id === "searchInput") return;
      const suggestion = conceptSuggestionsFor(query)[0];
      if (suggestion) chooseConceptSuggestion(suggestion, input, true);
      else if (input.id === "conceptInput") {
        state.conceptName = query.trim();
        state.cuisine = "any";
        state.dietary = "none";
        selectedId = null;
        syncBriefControls();
        loadDashboard();
      }
    }, 120);
  });
});
document.addEventListener("click", event => {
  if (!event.target.closest(".concept-search")) closeConceptSuggestions();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.querySelector(".map-module.is-expanded")) toggleExpandedMap(false);
});

document.querySelector("#profileSelect").addEventListener("change", (event) => {
  state.profile = event.target.value;
  state.serviceStyle = defaultServiceStyle(state.profile);
  selectedId = null;
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#briefProfile").addEventListener("change", (event) => {
  document.querySelector("#briefServiceStyle").value = defaultServiceStyle(event.target.value);
});

document.querySelector("#briefCuisine").addEventListener("change", event => updateConceptImage(event.target.value));

document.querySelector("#rentRange").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  state.rentCap = value * 1000;
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#briefForm").addEventListener("submit", (event) => {
  event.preventDefault();
  applyBrief();
});

document.querySelector("#financeScenarioForm").addEventListener("submit", event => {
  event.preventDefault();
  state.otherFixedCosts = document.querySelector("#financeFixedCosts").value;
  state.variableCostPct = document.querySelector("#financeVariableCosts").value;
  state.operatingDays = document.querySelector("#financeOperatingDays").value;
  loadDashboard();
});

document.querySelector("#briefSkip").addEventListener("click", () => {
  closeBrief();
});

document.querySelector("#briefEditButton").addEventListener("click", () => {
  openBrief();
});

document.querySelector("#refreshButton").addEventListener("click", () => {
  loadDashboard();
});

document.querySelector("#viewAnalysis").addEventListener("click", () => selectView("scorecard"));
document.querySelector("#mapLayerSelect").addEventListener("change", event => setActiveLayer(event.target.value));
document.querySelector("#mapBasemapSelect").addEventListener("change", event => changeMapView(event.target.value));

document.querySelector("#savedBriefs").addEventListener("click", event => {
  const open = event.target.closest("[data-open-brief]");
  const remove = event.target.closest("[data-remove-brief]");
  const rows = readStoredBriefs();
  if (open && rows[Number(open.dataset.openBrief)]) {
    const brief = rows[Number(open.dataset.openBrief)];
    briefFields.forEach(key => { if (typeof brief[key] === typeof state[key]) state[key] = brief[key]; });
    selectedId = null;
    syncBriefControls();
    selectView("discover");
    loadDashboard();
  }
  if (remove && rows[Number(remove.dataset.removeBrief)]) {
    rows.splice(Number(remove.dataset.removeBrief), 1);
    localStorage.setItem(BRIEFS_STORAGE_KEY, JSON.stringify(rows));
    renderSavedBriefs();
    queueWorkspaceSync();
  }
});
document.querySelectorAll("[data-auth-mode]").forEach(button => button.addEventListener("click", () => {
  const signup = button.dataset.authMode === "signup";
  document.querySelector("#authForm").action = `/auth/${signup ? "signup" : "login"}`;
  document.querySelector("#confirmField").hidden = !signup;
  document.querySelector("#confirmField input").required = signup;
  document.querySelector("#authForm input[name=password]").autocomplete = signup ? "new-password" : "current-password";
  document.querySelector(".auth-submit").textContent = signup ? "Create Account" : "Log In";
  document.querySelectorAll("[data-auth-mode]").forEach(choice => choice.setAttribute("aria-pressed", String(choice === button)));
}));
document.querySelector(`[data-auth-mode="${document.querySelector("#authForm").action.endsWith("/signup") ? "signup" : "login"}"]`)?.click();
document.querySelectorAll("[data-auth-open]").forEach(button => button.addEventListener("click", () => {
  document.querySelector(`[data-auth-mode="${button.dataset.authOpen}"]`).click();
  document.querySelector("#welcomeOverlay").classList.add("is-open");
}));
document.querySelector("#closeAccessButton")?.addEventListener("click", () => document.querySelector("#welcomeOverlay").classList.remove("is-open"));
document.querySelectorAll("[data-logout]").forEach(button => button.addEventListener("click", () => document.querySelector("#logoutForm").submit()));
setTheme(dashboardThemeChoice, false);
updateConceptImage(state.cuisine);
loadConceptImages();
initializeWorkspace();
setActiveLayer(activeLayer);
