let dashboard = null;
let selectedId = null;
let activeLayer = "opportunity";
let activeHeatMetric = "";
const heatmapTitles = {concept_demand:"Concept Demand",location_score:"Location Fit",demand:"Area Demand",customer_fit:"Customer Fit",access:"Accessibility",inverse_walkability:"Network Customer Access",walkability:"Walkability",competition_balance:"Competition Balance",market_gap:"Cuisine Supply",economics:"Commercial Fit"};
let economicsCharts = [];
let economicsRequestId = 0;
let economicsContext = "";
let economicsResult = null;
let economicsInputTimer = null;
let mapInventory = "properties";
let selectedPropertyId = null;
const OVERVIEW_RESULT_LIMIT = 5;
let propertyMapData = null;
let nycBoundaryData = null;
let nycBoundaryPending = false;
let nycBoundaryRetryAfter = 0;
let activeView = "discover";
let requestId = 0;
let locationMap = null;
let mapSizeObserver = null;
let mapMarkers = [];
let mapPopup = null;
let restaurantPopup = null;
let restaurantDataPromise = null;
let restaurantStyleRevision = 0;
let showExistingRestaurants = localStorage.getItem("groundwork-show-restaurants") === "true";
let mapDataset = "";
let mapViewRequestId = 0;
let hovered3DFeatureId = "";
let pinned3DFeature = false;
let activeBasemap = "streets";
const mapLimits = {
  streets: {bounds: [[-74.55, 40.43], [-73.37, 41.02]], minZoom: 10},
  aerial: {bounds: [[-74.30, 40.47], [-73.60, 41.00]], minZoom: 9.7},
  buildings3d: {bounds: [[-74.30, 40.47], [-73.60, 41.00]], minZoom: 9.7},
};
const systemTheme = matchMedia("(prefers-color-scheme: dark)");
let dashboardThemeChoice = ["light", "dark"].includes(localStorage.getItem("groundwork-theme")) ? localStorage.getItem("groundwork-theme") : "system";
let currentTheme = dashboardThemeChoice === "system" ? (systemTheme.matches ? "dark" : "light") : dashboardThemeChoice;
let savedIds = [];
let savedKey = "";
const competitionCache = new Map();
const catchmentCache = new Map();
const customerAccessCache = new Map();
let customerAccessRequest = 0;
let competitionRequest = 0;
let propertyView = "all";
let propertyVisible = 12;
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
  style.glyphs ||= `${window.location.origin}/static/fonts/{fontstack}/{range}.pbf`;
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
    glyphs: `${window.location.origin}/static/fonts/{fontstack}/{range}.pbf`,
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
  document.querySelectorAll(".nav-group").forEach(group => group.classList.toggle("has-active-tab", !!group.querySelector(".is-active")));
  document.querySelector(`.feature-tab[data-view="${view}"]`)?.scrollIntoView({block: "nearest", inline: "nearest"});
  if (dashboard) renderConceptChrome();
  renderPanels();
  if (view === "menu") loadMenuSuggestions();
  if (view === "access") renderCustomerAccess();
  if (view === "finance") prepareEconomicsLab();
  if (view === "reports" && dashboard) renderReports();
  if (dashboard) renderTeamExplorers();
  if (view === "workspace" && dashboard) prepareBusinessWorkspace();
}

function shortlistKey() {
  const parts = [normalizeConceptText(conceptName()), state.profile, state.cuisine, state.dietary];
  return `groundwork-shortlist:${JSON.stringify(accountOwner ? [accountOwner, ...parts] : parts)}`;
}

const accountOwner = window.GROUNDWORK_ACCESS === "account" ? window.GROUNDWORK_MENU_OWNER : null;
const BRIEF_STORAGE_KEY = accountOwner ? `groundwork-active-brief-v1:${accountOwner}` : "groundwork-active-brief-v1";
const BRIEFS_STORAGE_KEY = `groundwork-saved-briefs-v1:${accountOwner || "guest"}`;
const briefFields = ["conceptName", "profile", "rentCap", "dealType", "preferredArea", "cuisine", "averageCheck", "priceMode", "priceTier", "dietary", "description", "purchaseBudget", "otherFixedCosts", "variableCostPct", "operatingDays", "serviceStyle", "audience", "daypart", "sortBy"];

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
  sortBy: "opportunity",
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
let workspaceBaseline = null;

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
    plans: storedObject(`groundwork-plans:${accountOwner || "guest"}`) || {},
    profile: storedObject(`groundwork-profile:${accountOwner || "guest"}`) || {},
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
  localStorage.setItem(`groundwork-plans:${accountOwner || "guest"}`, JSON.stringify(workspace.plans || {}));
  localStorage.setItem(`groundwork-profile:${accountOwner || "guest"}`, JSON.stringify(workspace.profile || {}));
  const profileForm = document.querySelector("#businessProfileForm");
  if (profileForm) for (const field of ["display_name", "company"]) profileForm.elements.namedItem(field).value = workspace.profile?.[field] || "";
  savedKey = "";
  menuSavedKey = "";
}

function mergeWorkspaces(base, incoming) {
  const briefs = [...(incoming.briefs || []), ...(base.briefs || [])];
  const seen = new Set();
  return {
    active_brief: incoming.active_brief || base.active_brief || null,
    plans: {...base.plans, ...incoming.plans},
    profile: {...base.profile, ...incoming.profile},
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
    plans: Object.fromEntries(Object.entries(storedObject("groundwork-plans:guest") || {}).map(([key, value]) => {
      const parts = ownerOfStorageKey(key, "groundwork-menu-v2:");
      return [parts ? `groundwork-menu-v2:${JSON.stringify([accountOwner, ...parts.slice(1)])}` : key, value];
    })),
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
  workspaceEditVersion++;
  localStorage.setItem(`groundwork-workspace-dirty:${accountOwner}`, "1");
  if (!workspaceReady) { workspaceStatus("Saved On This Device; Account Sync Pending"); return; }
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
        payload = reconcileWorkspace(workspaceBaseline || {}, remote.workspace || {active_brief: null, briefs: [], shortlists: {}, menus: {}}, workspaceSnapshot());
        applyWorkspace(payload);
        continue;
      }
      if (!response.ok) throw new Error("Unable to save workspace.");
      workspaceRevision = (await response.json()).revision;
      workspaceBaseline = structuredClone(payload);
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
      workspaceBaseline = structuredClone(remote.workspace || blank);
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
  entryHasSavedBrief = hasSavedBrief;
  if (window.GROUNDWORK_ACCESS) openBrief();
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
  if (economicsResult && activeView === "finance") renderEconomicsCharts(economicsResult);
  if (activeView === "menu") renderAdvancedMenu();
  if (activeView === "workspace" && businessForecastResult) renderBusinessForecast(businessForecastResult);
}
systemTheme.addEventListener("change", () => {if (dashboardThemeChoice === "system") setTheme("system", false);});

const toneFor = {
  opportunity: ["#b6404a", "#df7653", "#e9b967", "#a8ca78", "#39ae88", "#087c78"],
  activity: ["#455c71", "#66849b", "#9bb2b2", "#c5ba83", "#e1a65d", "#b96a39"],
  whitespace: ["#725568", "#9a6b78", "#c28c87", "#c7ad7b", "#96bb8a", "#458a80"],
  cost: ["#a74b52", "#c47a5e", "#d5ab6f", "#b8c684", "#73af85", "#367d72"],
  walkability: ["#955158", "#c48261", "#d6b776", "#acc78c", "#6cac9a", "#337f90"],
  business_draw: ["#a34359", "#cf7968", "#deac70", "#b2c782", "#71b394", "#28878a"],
  inverse_walkability: ["#8d5261", "#bc8074", "#d2b17e", "#9fbc96", "#54a59b", "#167e88"],
  concept_demand: ["#ad4648", "#db7952", "#e9ba6e", "#a9c77b", "#49ad8c", "#087d82"],
  huff_demand: ["#ad4648", "#db7952", "#e9ba6e", "#a9c77b", "#49ad8c", "#087d82"],
};

const layerTitles = {
  opportunity: "Location Opportunities",
  activity: "Local Demand",
  whitespace: "Market Gaps",
  cost: "Commercial Suitability",
  walkability: "Area Walkability",
  business_draw: "Business Fit",
  inverse_walkability: "Customer Walking Access",
  concept_demand: "Concept Demand Index",
  huff_demand: "Huff Market Gaps (Scenario)",
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
  document.querySelector("#briefTierField").hidden = false;
  document.querySelector("#briefExactPriceField").hidden = true;
  document.querySelector("#briefAverageCheck").required = false;
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
  if (activeHeatMetric) { activeHeatMetric = ""; document.querySelector("#heatmapMetricSelect").value = ""; }
  if (layer !== activeLayer) { hexRequestId++; clearHexLayer(); }
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
    renderRanking();
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
  if (item.kind === "property") {
    openPlanProperty(item.id); input.value = ""; closeConceptSuggestions(); return;
  }
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
  const properties = input.id === "searchInput" && dashboard && query.length >= 2
    ? (dashboard.properties || []).filter(row => normalizeConceptText(`${row.id} ${row.address} ${row.location_name} ${row.borough}`).includes(query)).slice(0, 5)
      .map(row => ({kind: "property", id: row.id, title: `${row.address} · ${row.price_label}`})) : [];
  visibleSuggestions = properties.length || locations.length ? [...properties, ...locations] : conceptSuggestionsFor(input.value);
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
    sort_by: state.sortBy,
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
    if (currentRequest !== requestId) return false;
    if (!result.locations?.length) {
      status.textContent = "No Locations Found. Update Your Search Brief.";
      document.querySelector(".workspace").classList.add("has-no-results");
      return false;
    }
    dashboard = result;
    if (!selectedPropertyId) selectedPropertyId = currentPlan().selected_property_id || null;
    if (!(dashboard.properties || []).some(row => row.id === selectedPropertyId)) selectedPropertyId = null;
    updateHuffAvailability();
    hexCache.clear();
    hexRequestId++;
    clearHexLayer();
    competitionCache.clear();
    catchmentCache.clear();
    customerAccessCache.clear();
    customerAccessRequest++;
    persistBrief();
    document.querySelector(".workspace").classList.remove("has-no-results");
    selectedId = selectedId || dashboard.selected;
    if (mapInventory === "properties" && !selectedPropertyId) {
      const property = (dashboard.properties || []).find(row => row.lead_type === "synthetic");
      if (property) { selectedPropertyId = property.id; selectedId = property.location_id; }
    }
    if (!allLocations().some((location) => location.id === selectedId)) {
      selectedId = dashboard.selected;
    }
    syncSavedLocations();
    renderAll();
    if (activeView === "menu") loadMenuSuggestions();
    status.hidden = true;
    return true;
  } catch (error) {
    if (currentRequest === requestId) {
      status.textContent = "Unable To Update Locations. Select Refresh To Retry.";
    }
    return false;
  } finally {
    if (currentRequest === requestId) document.querySelector(".workspace").setAttribute("aria-busy", "false");
  }
}

function allLocations() {
  const rows = [...dashboard.locations];
  const existing = new Set(rows.map(row => row.id));
  for (const row of [...(dashboard.saved_locations || []), ...(dashboard.property_locations || [])]) {
    if (!existing.has(row.id)) { rows.push(row); existing.add(row.id); }
  }
  return rows;
}

function selectedLocation() {
  return allLocations().find((location) => location.id === selectedId) || dashboard.locations[0];
}

function overviewRecommendations(kind = mapInventory) {
  const rows = kind === "properties"
    ? (dashboard.properties || []).filter(row => row.lead_type !== "registry_record")
    : dashboard.locations;
  return rows.slice(0, OVERVIEW_RESULT_LIMIT);
}

function renderMetrics() {
  const best = dashboard.locations[0];
  const metrics = [
    ["Leading Location", best.name, dashboard.meta.sort_by === "inverse_walkability" ? `${best.inverse_walkability ?? "--"}/100 Customer Access` : `${best.opportunity}/100 Location Score`],
    [mapInventory === "properties" ? "Matching Properties" : "Areas Shortlisted", mapInventory === "properties" ? (dashboard.properties || []).filter(row => row.lead_type !== "registry_record").length : dashboard.locations.length, mapInventory === "properties" ? `${dashboard.property_search?.synthetic_matches ?? 0} Synthetic Scenarios` : state.preferredArea || "New York City"],
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
  for (const id of ["concept-hex-hover", "concept-hex-outline", "concept-hex-fill"]) {
    if (locationMap.getLayer(id)) locationMap.removeLayer(id);
  }
  if (locationMap.getSource("concept-hexes")) locationMap.removeSource("concept-hexes");
}

function paintHexLayer(data) {
  const status = document.querySelector("#dashboardStatus");
  if (data.meta?.status === "no_feature_coverage") {
    status.textContent = "No Recorded Coverage For This Feature And Concept."; status.hidden = false;
  } else if (status.textContent === "No Recorded Coverage For This Feature And Concept.") status.hidden = true;
  if (!isHexLayer() || !locationMap?.getStyle()) return;
  clearHexLayer();
  const vector = data.tiles && data.source_layer;
  locationMap.addSource("concept-hexes", vector ? {type: "vector", tiles: data.tiles, minzoom: 0, maxzoom: 18} : {type: "geojson", data});
  const sourceLayer = vector ? {"source-layer": data.source_layer} : {};
  const labelLayer = activeBasemap === "streets" && locationMap.getLayer("street-labels") ? "street-labels" :
    activeBasemap === "buildings3d" ? locationMap.getStyle().layers.find(layer => layer.type === "symbol")?.id : undefined;
  locationMap.addLayer({id: "concept-hex-fill", type: "fill", source: "concept-hexes", ...sourceLayer, paint: {
    "fill-color": ["interpolate", ["linear"], ["get", "score"], 0, "#b2182b", 25, "#ef8a62", 45, "#fddc7a", 60, "#a6dba0", 78, "#1b9e77", 100, "#006837"],
    "fill-opacity": ["interpolate", ["linear"], ["get", "coverage"], 0, .10, 35, .38, 70, .59, 100, .70],
  }}, labelLayer);
  locationMap.addLayer({id: "concept-hex-outline", type: "line", source: "concept-hexes", ...sourceLayer, paint: {
    "line-color": "#ffffff", "line-opacity": .48, "line-width": ["interpolate", ["linear"], ["zoom"], 9, .35, 14, .8],
  }}, labelLayer);
  locationMap.addLayer({id:"concept-hex-hover",type:"line",source:"concept-hexes",...sourceLayer,
    filter:["==",["get","id"],""],paint:{"line-color":"#153f5a","line-opacity":1,"line-width":2.2}},labelLayer);
  installNycBoundary();
}

function highlightHex(feature) {
  if (!locationMap.getLayer("concept-hex-hover")) return;
  if (!feature) { locationMap.setFilter("concept-hex-hover", ["==",1,0]); return; }
  const identity = String(feature?.properties?.cell_id ?? feature?.properties?.id ?? feature?.id ?? "");
  locationMap.setFilter("concept-hex-hover", ["any",
    ["==",["to-string",["coalesce",["get","cell_id"],["get","id"],""]],identity],
    ["==",["to-string",["id"]],identity]]);
}

function showHexDetails(feature, lngLat, pinned = false) {
  const {score, coverage, level, cell_count: count} = feature.properties;
  const detail = document.createElement("div");
  detail.className = "map-location-detail";
  if (activeLayer === "huff_demand") {
    const gap = Number(score), demand = Number(feature.properties.unserved_demand);
    detail.innerHTML = `<strong>Huff Market Gap Scenario</strong><div><span>Outside Option Share</span><b>${Number.isFinite(gap) ? gap.toFixed(1) : "--"}%</b></div><div><span>Unserved Demand Units</span><b>${Number.isFinite(demand) ? Math.round(demand).toLocaleString("en-US") : "--"}</b></div><small>Scenario estimate; weights and capacity require calibration.</small>`;
  } else {
    detail.innerHTML = `<strong>${heatmapTitles[activeHeatMetric || "concept_demand"]}</strong><div><span>${level === "sector" ? "Sector Score" : "Local Score"}</span><b>${score}/100</b></div><div><span>Evidence Coverage</span><b>${coverage}%</b></div><small>Tract-Based Estimate${count ? ` · ${count} Local Cells` : ""}</small>`;
  }
  mapPopup?.remove();
  mapPopup = new maplibregl.Popup({closeButton:pinned,closeOnClick:false,offset:12,maxWidth:"230px"})
    .setLngLat(lngLat).setDOMContent(detail).addTo(locationMap);
}

function isHexLayer() {
  return !!activeHeatMetric || activeLayer === "concept_demand" || activeLayer === "huff_demand";
}

async function updateHuffAvailability() {
  const option = document.querySelector('option[value="huff_demand"]');
  if (!option) return;
  try {
    const response = await fetch("/api/v1/spatial/huff");
    option.disabled = !response.ok;
    option.textContent = response.ok ? "Huff Market Gaps (Scenario)" : "Huff Market Gaps (Unavailable)";
  } catch {
    option.disabled = true;
  }
}

function hexLevel() {
  const zoom = locationMap.getZoom();
  return zoom >= 14 ? "fine" : zoom >= 11.5 ? "cell" : "sector";
}

async function showHexLayer() {
  if (!locationMap || !isHexLayer() || !dashboard) return;
  const level = hexLevel();
  const params = conceptParams();
  params.set("level", level);
  params.set("metric", activeHeatMetric || "concept_demand");
  const key = `${activeLayer}:${activeHeatMetric}:${dashboard.meta.data_release}:${params}`;
  const requestedLayer = activeLayer;
  const currentRequest = ++hexRequestId;
  if (hexCache.has(key)) {
    paintHexLayer(hexCache.get(key));
    return;
  }
  try {
    let data;
    if (window.GROUNDWORK_SPATIAL_BACKEND && (!activeHeatMetric || activeHeatMetric === "concept_demand")) {
      const resolution = level === "fine" ? "9" : level === "cell" ? "8" : "7";
      const endpoint = requestedLayer === "huff_demand" ? "/api/v1/spatial/huff" : `/api/v1/spatial/resolve?${params}`;
      const response = await fetch(endpoint);
      if (response.ok) {
        const manifest = await response.json();
        const tile = manifest.tiles?.[resolution];
        if (tile && manifest.source_layer && (requestedLayer === "huff_demand" || manifest.data_release === dashboard.meta.data_release)) {
          data = {tiles: [new URL(tile, window.location.origin).href.replace(/%7B/gi, "{").replace(/%7D/gi, "}")], source_layer: manifest.source_layer};
        }
      }
    }
    if (!data) {
      if (requestedLayer === "huff_demand") throw new Error("Huff surface unavailable");
      const response = await fetch(`/api/hex-demand?${params}`);
      if (!response.ok) throw new Error("Hex demand request failed");
      data = await response.json();
    }
    hexCache.set(key, data);
    if (currentRequest === hexRequestId && activeLayer === requestedLayer && level === hexLevel()) paintHexLayer(data);
  } catch {
    if (currentRequest === hexRequestId && activeLayer === requestedLayer) {
      clearHexLayer();
      const status = document.querySelector("#dashboardStatus");
      status.textContent = requestedLayer === "huff_demand" ? "Huff Market Gaps Are Temporarily Unavailable." : "Concept Demand Is Temporarily Unavailable.";
      status.hidden = false;
    }
  }
}

function hexAtPoint(point) {
  if (!isHexLayer() || !locationMap.getLayer("concept-hex-fill")) return null;
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
  syncRestaurantVisibility();
  locationMap.setStyle(mapStyle("aerial"));
  applyMapLimits("aerial");
  locationMap.easeTo({pitch: 0, bearing: 0, duration: 250});
  setMapViewStatus(message, true);
}

const RESTAURANT_LAYERS = ["restaurant-clusters", "restaurant-cluster-count", "restaurant-points"];

function syncRestaurantVisibility() {
  const in3D = activeBasemap === "buildings3d";
  document.querySelector(".restaurant-toggle").hidden = !in3D;
  if (isHexLayer()) document.querySelector(".restaurant-toggle").hidden = true;
  const legend = document.querySelector(".legend-restaurant-entry");
  if (legend) legend.hidden = !in3D || !showExistingRestaurants || isHexLayer();
  if (!locationMap) return;
  const visible = in3D && showExistingRestaurants && !isHexLayer();
  document.querySelector("#showRestaurantsToggle").disabled = isHexLayer();
  RESTAURANT_LAYERS.forEach(id => {
    if (locationMap.getLayer(id)) locationMap.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  });
  if (!visible) {
    restaurantPopup?.remove();
    restaurantPopup = null;
  }
}

function restaurantData() {
  if (!restaurantDataPromise) {
    restaurantDataPromise = fetch("/api/map/restaurants")
      .then(response => { if (!response.ok) throw new Error("Restaurant map data unavailable"); return response.json(); })
      .catch(error => { restaurantDataPromise = null; throw error; });
  }
  return restaurantDataPromise;
}

async function installRestaurantLayers(revision) {
  try {
    const data = await restaurantData();
    if (!locationMap || activeBasemap !== "buildings3d" || revision !== restaurantStyleRevision || locationMap.getSource("existing-restaurants")) return;
    locationMap.addSource("existing-restaurants", {type: "geojson", data, cluster: true, clusterRadius: 45, clusterMaxZoom: 13});
    locationMap.addLayer({id: "restaurant-clusters", type: "circle", source: "existing-restaurants", filter: ["has", "point_count"],
      paint: {"circle-color": "#1662c2", "circle-radius": ["step", ["get", "point_count"], 12, 100, 16, 1000, 21],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5, "circle-opacity": 1}});
    locationMap.addLayer({id: "restaurant-cluster-count", type: "symbol", source: "existing-restaurants", filter: ["has", "point_count"],
      layout: {"text-field": ["get", "point_count_abbreviated"], "text-font": ["Open Sans Regular"], "text-size": 11},
      paint: {"text-color": "#ffffff"}});
    locationMap.addLayer({id: "restaurant-points", type: "circle", source: "existing-restaurants", filter: ["!", ["has", "point_count"]],
      paint: {"circle-color": "#2487df", "circle-radius": 3.5, "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 0.8, "circle-opacity": 1}});
    syncRestaurantVisibility();
  } catch {
    setMapViewStatus("Existing restaurant locations could not load.", true);
  }
}

async function handleRestaurantClick(event) {
  if (activeBasemap !== "buildings3d" || !showExistingRestaurants || !locationMap?.getLayer("restaurant-points")) return false;
  const feature = locationMap.queryRenderedFeatures(event.point, {layers: ["restaurant-points", "restaurant-clusters"]})[0];
  if (!feature) return false;
  if (feature.properties.cluster) {
    const source = locationMap.getSource("existing-restaurants");
    try {
      const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
      if (activeBasemap === "buildings3d" && showExistingRestaurants && source === locationMap.getSource("existing-restaurants")) {
        locationMap.easeTo({center: feature.geometry.coordinates, zoom, duration: 400});
      }
    } catch (_) {}
    return true;
  }
  mapPopup?.remove();
  restaurantPopup?.remove();
  const details = document.createElement("div");
  details.className = "map-restaurant-detail";
  details.innerHTML = `<strong>${escapeHtml(feature.properties.name || "Name unavailable")}</strong>
    <div><span>Cuisine</span><b>${escapeHtml(feature.properties.cuisine || "Unavailable")}</b></div>
    <div><span>Address</span><b>${escapeHtml(feature.properties.address || "Unavailable")}</b></div>`;
  restaurantPopup = new maplibregl.Popup({closeButton: true, closeOnClick: true, offset: 10, maxWidth: "290px"})
    .setLngLat(feature.geometry.coordinates).setDOMContent(details).addTo(locationMap);
  return true;
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
  restaurantStyleRevision++;
  restaurantPopup?.remove();
  syncRestaurantVisibility();
  pinned3DFeature = false;
  hovered3DFeatureId = "";
  mapPopup?.remove();
  locationMap.setStyle(style || mapStyle(next));
  applyMapLimits(next);
  if (next === "buildings3d") {
    locationMap.easeTo({pitch: 54, bearing: -18, duration: 550});
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

function installNycBoundary() {
  if (!locationMap?.getStyle()) return;
  if (!nycBoundaryData) {
    if (nycBoundaryPending || Date.now() < nycBoundaryRetryAfter) return;
    nycBoundaryPending = true;
    fetch("/api/geography/nyc-boundary").then(response => {
      if (!response.ok) throw new Error("Boundary unavailable");
      return response.json();
    }).then(data => {
      if (data.type !== "FeatureCollection" || data.features?.length !== 3) throw new Error("Invalid city boundary");
      nycBoundaryData = data;
      installNycBoundary();
    }).catch(() => { nycBoundaryRetryAfter = Date.now() + 60000; })
      .finally(() => { nycBoundaryPending = false; });
    return;
  }
  if (!locationMap.isStyleLoaded()) return;
  const ids = ["nyc-context-mask", "nyc-boundary-halo", "nyc-boundary-line"];
  if (!locationMap.getSource("nyc-city-partition")) {
    locationMap.addSource("nyc-city-partition", {type:"geojson",data:nycBoundaryData});
    locationMap.addLayer({id:ids[0],type:"fill",source:"nyc-city-partition",filter:["==",["get","kind"],"outside"],paint:{"fill-color":"#102030","fill-opacity":.27}});
    locationMap.addLayer({id:ids[1],type:"line",source:"nyc-city-partition",filter:["==",["get","kind"],"outline"],paint:{"line-color":"#ffffff","line-opacity":.92,"line-width":["interpolate",["linear"],["zoom"],9,5,14,7]}});
    locationMap.addLayer({id:ids[2],type:"line",source:"nyc-city-partition",filter:["==",["get","kind"],"outline"],paint:{"line-color":"#2764d8","line-opacity":1,"line-width":["interpolate",["linear"],["zoom"],9,2.4,14,3.2]}});
  }
  const opacity = activeBasemap === "aerial" ? .38 : currentTheme === "dark" ? .4 : .23;
  if (locationMap.getPaintProperty(ids[0],"fill-opacity") !== opacity) locationMap.setPaintProperty(ids[0],"fill-opacity",opacity);
  // Keep the city partition above heatmaps, but below every interactive marker and label.
  const foreground = ["restaurant-clusters", "restaurant-points", "property-clusters", "property-points", "property-selection",
    "restaurant-cluster-count", "property-cluster-count", "property-rank-label", "property-selection-rank"].filter(id=>locationMap.getLayer(id));
  const ordered = [...ids, ...foreground];
  const last = locationMap.getStyle().layers.slice(-ordered.length).map(layer=>layer.id);
  if (ordered.some((id,index)=>last[index] !== id)) ordered.forEach(id=>locationMap.moveLayer(id));
}

function propertyFeatureAtPoint(point) {
  const layers = ["property-selection", "property-points", "property-clusters"].filter(id => locationMap.getLayer(id));
  return layers.length ? locationMap.queryRenderedFeatures(point, {layers})[0] : null;
}

function syncPropertyVisibility() {
  if (!locationMap?.getStyle()) return;
  const visible = mapInventory === "properties" && !isHexLayer();
  for (const id of ["property-clusters", "property-points", "property-cluster-count", "property-rank-label", "property-selection", "property-selection-rank"]) {
    if (!locationMap.getLayer(id)) continue;
    const next = visible || (id.startsWith("property-selection") && isHexLayer()) ? "visible" : "none";
    if (locationMap.getLayoutProperty(id,"visibility") !== next) locationMap.setLayoutProperty(id,"visibility",next);
  }
}

function installPropertyLayers() {
  syncPropertyVisibility();
  if (!locationMap.isStyleLoaded() || !propertyMapData) return;
  if (!locationMap.getSource("property-opportunities")) {
    locationMap.addSource("property-opportunities", {type: "geojson", data: propertyMapData, cluster: true, clusterMaxZoom: 12, clusterRadius: 35});
    locationMap.addLayer({id: "property-clusters", type: "circle", source: "property-opportunities", filter: ["has", "point_count"], paint: {"circle-color": "#246da5", "circle-opacity": 1, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2, "circle-radius": ["step", ["get", "point_count"], 13, 10, 18, 40, 24]}});
    locationMap.addLayer({id: "property-points", type: "circle", source: "property-opportunities", filter: ["!", ["has", "point_count"]], paint: {"circle-color": ["get", "color"], "circle-radius": ["case", ["get", "selected"], 16, 13], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}});
    const font = locationMap.getStyle().layers.find(layer => layer.type === "symbol" && Array.isArray(layer.layout?.["text-font"]))?.layout["text-font"] || ["Open Sans Regular"];
    locationMap.addLayer({id:"property-cluster-count",type:"symbol",source:"property-opportunities",filter:["has","point_count"],layout:{"text-field":["get","point_count_abbreviated"],"text-font":font,"text-size":12,"text-allow-overlap":true},paint:{"text-color":"#ffffff"}});
    locationMap.addLayer({id:"property-rank-label",type:"symbol",source:"property-opportunities",filter:["!",["has","point_count"]],layout:{"text-field":["to-string",["get","rank"]],"text-font":font,"text-size":10,"text-allow-overlap":true},paint:{"text-color":"#102a33","text-halo-color":"#ffffff","text-halo-width":.7}});
  }
  const selection = {type:"FeatureCollection", features:propertyMapData.features.filter(row => row.properties.selected)};
  if (!locationMap.getSource("property-selection")) {
    locationMap.addSource("property-selection", {type:"geojson", data:selection});
    locationMap.addLayer({id:"property-selection",type:"circle",source:"property-selection",paint:{"circle-color":["get","color"],"circle-radius":16,"circle-stroke-color":"#ffffff","circle-stroke-width":4}});
    const font = locationMap.getStyle().layers.find(layer => layer.type === "symbol" && Array.isArray(layer.layout?.["text-font"]))?.layout["text-font"] || ["Open Sans Regular"];
    locationMap.addLayer({id:"property-selection-rank",type:"symbol",source:"property-selection",layout:{"text-field":["to-string",["get","rank"]],"text-font":font,"text-size":11,"text-allow-overlap":true},paint:{"text-color":"#102a33","text-halo-color":"#ffffff","text-halo-width":1}});
  } else {
    const signature = JSON.stringify(selection);
    if (locationMap._groundworkSelection !== signature) { locationMap.getSource("property-selection").setData(selection); locationMap._groundworkSelection = signature; }
  }
  syncPropertyVisibility();
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
      if (isHexLayer()) showHexLayer();
    });
    mapSizeObserver = new ResizeObserver(() => requestAnimationFrame(() => {
      const bounds = document.querySelector("#mapStage").getBoundingClientRect();
      if (bounds.width && bounds.height) locationMap.resize();
    }));
    mapSizeObserver.observe(document.querySelector("#mapStage"));
    locationMap.on("load", () => {
      installNycBoundary();
      if (isHexLayer()) showHexLayer();
    });
    locationMap.on("idle", () => {
      installNycBoundary();
      installPropertyLayers();
      if (activeBasemap === "buildings3d" && !locationMap.getSource("existing-restaurants")) installRestaurantLayers(restaurantStyleRevision);
      if (isHexLayer() && !locationMap.getLayer("concept-hex-fill")) showHexLayer();
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
      installNycBoundary();
      installPropertyLayers();
      if (isHexLayer()) showHexLayer();
    });
    locationMap.on("error", event => {
      if (activeBasemap === "buildings3d" && (event.sourceId === "openmaptiles" || /openfreemap/i.test(event.error?.message || ""))) {
        fallbackToAerial("3D building tiles could not load. Aerial remains active.");
      }
    });
    locationMap.on("mousemove", (event) => {
      if (!isHexLayer()) return;
      const feature = hexAtPoint(event.point);
      locationMap.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        hoveredHexId = null;
        highlightHex(null);
        mapPopup?.remove();
        return;
      }
      const identity = feature.id ?? feature.properties.cell_id ?? feature.properties.id;
      if (identity === hoveredHexId) return;
      hoveredHexId = identity;
      highlightHex(feature);
      showHexDetails(feature,event.lngLat);
    });
    locationMap.on("mousemove", event => {
      if (mapInventory !== "properties" || isHexLayer()) return;
      const feature = propertyFeatureAtPoint(event.point);
      locationMap.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) { mapPopup?.remove(); return; }
      const detail = document.createElement("div"); detail.className = "map-location-detail";
      if (feature.properties.cluster) {
        detail.innerHTML = `<strong>${displayNumber(Number(feature.properties.point_count))} Property Scenarios / Leads</strong><small>Zoom In To View Individual Properties</small>`;
      } else {
        const property = dashboard.properties.find(row => row.id === feature.properties.property_id);
        if (!property) return;
        detail.innerHTML = `<strong>${escapeHtml(property.address)}</strong><small>${property.lead_type === "synthetic" ? "Synthetic Scenario · Approximate Location" : "Source-Reported Property Lead"}</small><div><span>${property.transaction === "purchase" ? "Purchase Price" : "Monthly Rent"}${property.lead_type === "synthetic" ? " (Modeled)" : ""}</span><b>${escapeHtml(property.price_label)}</b></div><div><span>Floor Area</span><b>${displayNumber(property.sqft)} Sq Ft</b></div><div><span>Area Score</span><b>${property.location_score}/100</b></div><div><span>Customer Access</span><b>${property.customer_access?.index == null ? "Unavailable" : `${property.customer_access.index}/100`}</b></div>${property.broker_name ? `<div><span>Broker / Owner</span><b>${escapeHtml(property.broker_name)}</b></div>` : ""}`;
      }
      mapPopup?.remove(); mapPopup = new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:14,maxWidth:"290px"}).setLngLat(feature.geometry.coordinates).setDOMContent(detail).addTo(locationMap);
    });
    locationMap.on("click", async event => {
      if (mapInventory !== "properties" || isHexLayer()) return;
      const feature = propertyFeatureAtPoint(event.point);
      if (!feature) return;
      if (feature.properties.cluster) {
        try {
          const source = locationMap.getSource("property-opportunities");
          const zoom = await source.getClusterExpansionZoom(Number(feature.properties.cluster_id));
          if (locationMap.getSource("property-opportunities") === source) locationMap.easeTo({center: feature.geometry.coordinates, zoom, duration: 400});
        } catch { /* A basemap change can replace the source while expansion is pending. */ }
      } else {
        const property = dashboard.properties.find(row => row.id === feature.properties.property_id);
        if (!property) return;
        selectedPropertyId = property.id; selectedId = property.location_id; renderAll();
      }
    });
    locationMap.on("click", (event) => {
      const feature = hexAtPoint(event.point);
      if (feature?.properties.level === "sector") {
        const ring = feature.geometry.coordinates[0];
        const center = ring.slice(0, -1).reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0]).map(value => value / (ring.length - 1));
        locationMap.easeTo({center, zoom: 12, duration: 450});
      } else if (feature) {
        highlightHex(feature);
        showHexDetails(feature,event.lngLat,true);
      }
    });
    locationMap.on("mousemove", event => {
      if (mapInventory === "properties" && propertyFeatureAtPoint(event.point)) return;
      if (activeBasemap !== "buildings3d" || isHexLayer() || pinned3DFeature) return;
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
      if (mapInventory === "properties" && propertyFeatureAtPoint(event.point)) return;
      if (activeBasemap !== "buildings3d" || isHexLayer()) return;
      if (showExistingRestaurants && locationMap.getLayer("restaurant-points") &&
          locationMap.queryRenderedFeatures(event.point, {layers: ["restaurant-points", "restaurant-clusters"]}).length) {
        handleRestaurantClick(event);
        return;
      }
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
    legend.innerHTML = '<div><b class="legend-recommendation-dot"></b><span>Recommended Area</span><span>0</span><i></i><span>100</span></div><div class="legend-restaurant-entry" hidden><b class="legend-restaurant-dot"></b><span>Existing Restaurant</span></div>';
    legend.insertAdjacentHTML("beforeend", '<div><b class="nyc-boundary-key"></b><span>NYC Boundary</span></div>');
    document.querySelector("#mapStage").append(legend);
    syncRestaurantVisibility();
  }
  mapPopup?.remove();
  pinned3DFeature = false;
  mapMarkers.forEach(marker => marker.remove());
  mapMarkers = [];
  if (isHexLayer()) showHexLayer();
  else clearHexLayer();
  const locationLookup = new Map(allLocations().map(row => [row.id, row]));
  const points = mapInventory === "properties"
    ? overviewRecommendations("properties").map((property,index) => ({
        property, location: locationLookup.get(property.location_id),
        latitude: Number(property.latitude), longitude: Number(property.longitude), id: property.id, rank: index + 1,
      }))
    : overviewRecommendations("areas")
      .map(location => ({location, latitude: location.latitude, longitude: location.longitude, id: location.id}));
  const locations = points.filter(row => row.location && Number.isFinite(row.latitude) && Number.isFinite(row.longitude) && row.latitude >= 40.45 && row.latitude <= 40.95 && row.longitude >= -74.3 && row.longitude <= -73.65);
  if (mapInventory === "properties") {
    propertyMapData = {type:"FeatureCollection",features:locations.map(point => ({type:"Feature",geometry:{type:"Point",coordinates:[point.longitude,point.latitude]},properties:{property_id:point.property.id,rank:point.rank,color:colorFor(activeLayer === "inverse_walkability" ? point.property.customer_access?.index : activeMetric(point.location)),selected:point.property.id === selectedPropertyId}}))};
    locationMap.getSource("property-opportunities")?.setData(propertyMapData);
  }
  installPropertyLayers();
  syncRestaurantVisibility();
  document.querySelector("#mapInventorySelect").disabled = isHexLayer();
  document.querySelector("#mapLayerSelect").disabled = !!activeHeatMetric;
  document.querySelector("#mapInventorySelect").hidden = isHexLayer();
  document.querySelector("#mapLayerSelect").hidden = !!activeHeatMetric;
  document.querySelector(".map-legend")?.classList.toggle("is-hex", isHexLayer());
  document.querySelector(".legend-recommendation-dot + span").textContent = mapInventory === "properties" && !isHexLayer() ? "Property Scenario / Lead" : "Recommended Area";
  if (!isHexLayer() && mapInventory === "areas") locations.forEach((point,index) => {
    const {location, property} = point;
    const selected = property ? property.id === selectedPropertyId : location.id === selectedId;
    const element = document.createElement("button");
    element.className = `map-score-marker${property ? " map-property-marker" : ""}${selected ? " is-selected" : ""}`;
    element.dataset.propertyId = property?.id || "";
    element.type = "button";
    element.textContent = String(index + 1);
    element.style.backgroundColor = colorFor(activeMetric(location));
    element.title = `${property?.address || location.name} · ${property?.price_label || `Area Score ${location.opportunity}`}`;
    element.setAttribute("aria-label", element.title);
    const showDetail = () => {
      mapPopup?.remove();
      const propertyLabel = property?.lead_type === "synthetic" ? "Synthetic Scenario · Approximate Location" : property ? "Source-Reported Property Lead" : "Area Assessment";
      const detail = document.createElement("div");
      detail.className = "map-location-detail";
      detail.innerHTML = `
        <strong>${escapeHtml(property?.address || location.name)}</strong>
        <div><span>Area Score</span><b>${location.opportunity}/100</b></div>
        <div><span>Customer Access</span><b>${(property ? property.customer_access?.index : location.inverse_walkability) ?? "Unavailable"}${(property ? property.customer_access?.index : location.inverse_walkability) != null ? "/100" : ""}</b></div>
        <small>${propertyLabel}</small>
        <p>${escapeHtml(location.name)}</p>
        ${property ? `<div><span>${property.transaction === "purchase" ? "Purchase Price" : "Monthly Rent"}${property.lead_type === "synthetic" ? " (Modeled)" : ""}</span><b>${escapeHtml(property.price_label || "Unavailable")}</b></div><div><span>Floor Area</span><b>${property.sqft ? `${displayNumber(property.sqft)} Sq Ft` : "Unavailable"}</b></div>` : `<div><span>Matching Scenarios</span><b>${(dashboard.properties || []).filter(row => row.geoid === location.geoid && row.lead_type === "synthetic").length}</b></div>`}
        ${property?.lead_type === "listing" ? `<div><span>Broker / Owner</span><b>${escapeHtml(property.broker_name || "Not In Source")}</b></div>` : ""}
      `;
      mapPopup = new maplibregl.Popup({closeButton: false, closeOnClick: false, offset: 16, maxWidth: "270px"})
        .setLngLat([point.longitude, point.latitude]).setDOMContent(detail).addTo(locationMap);
    };
    element.addEventListener("mouseenter", showDetail);
    element.addEventListener("focus", showDetail);
    element.addEventListener("mouseleave", () => mapPopup?.remove());
    element.addEventListener("blur", () => mapPopup?.remove());
    element.addEventListener("click", () => {
      selectedId = location.id;
      selectedPropertyId = property?.id || null;
      renderAll();
      revealSelectedRanking();
    });
    mapMarkers.push(new maplibregl.Marker({element, anchor: "center"}).setLngLat([point.longitude, point.latitude]).addTo(locationMap));
  });
  const key = `${mapInventory}:${dashboard.meta.data_release}:${locations.map(row => row.id).join(",")}`;
  if (key !== mapDataset && locations.length) {
    const latitudes = locations.map(row => row.latitude);
    const longitudes = locations.map(row => row.longitude);
    locationMap.fitBounds([[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]], {padding: 35, maxZoom: 14, duration: 0});
    mapDataset = key;
  }
  document.querySelector(".map-legend i").style.background = `linear-gradient(90deg, ${toneFor[activeLayer].join(",")})`;
  if (activeHeatMetric) {
    document.querySelector(".legend-recommendation-dot + span").textContent = `${heatmapTitles[activeHeatMetric]} · Relative Index`;
    document.querySelector(".map-legend i").style.background = "linear-gradient(90deg,#b2182b,#fddc7a,#1b9e77,#006837)";
  }
}

function assessmentBasis(location) {
  const mode = location.assessment_policy?.cuisine_mode;
  if (location.assessment_policy?.recommendation_eligible === false) return "Insufficient Evidence";
  if (mode === "cuisine_supply_supported") return "Cuisine-Supported Fit";
  if (mode === "pooled_cuisine_supply") return "Limited Cuisine Evidence";
  return "General Location Fit";
}

function renderIntel() {
  const location = selectedLocation();
  const property = (dashboard.properties || []).find(row => row.id === selectedPropertyId);
  const summary = document.querySelector("#selectedPropertySummary");
  summary.hidden = !property;
  summary.innerHTML = property ? `<span class="eyebrow">${property.lead_type === "synthetic" ? "Synthetic Property Scenario" : "Source-Reported Property Lead"}</span><strong>${escapeHtml(property.address)}</strong><div><span>${property.transaction === "purchase" ? "Purchase" : "Lease"}</span><b>${escapeHtml(property.price_label)}</b></div><div><span>Floor Area</span><b>${displayNumber(property.sqft)} Sq Ft</b></div><button type="button" class="quiet-action" id="inspectSelectedProperty">Property Details</button>` : "";
  document.querySelector("#inspectSelectedProperty")?.addEventListener("click", () => { propertyView = property.lead_type; propertyVisible = Math.max(12, (dashboard.properties || []).filter(row => row.lead_type === propertyView).findIndex(row => row.id === property.id) + 1); renderLease(); selectView("lease"); document.querySelector(`[data-property-card="${CSS.escape(property.id)}"]`)?.scrollIntoView({block:"center"}); });
  document.querySelector("#selectedName").textContent = location.name;
  document.querySelector("#selectedMeta").textContent = `${location.borough} · ${titleCase(location.archetype)}`;
  document.querySelector("#selectedScore").textContent = location.opportunity;
  document.querySelector("#scoreOrb").style.background = `conic-gradient(${colorFor(location.opportunity, "opportunity")} 0 ${location.opportunity}%, rgba(33,54,77,.95) ${location.opportunity}% 100%)`;
  document.querySelector("#confidencePill").textContent = location.ranking_components ? "Experimental Model Ranking" : "Screening Estimate";
  document.querySelector("#confidencePill").textContent += ` · ${assessmentBasis(location)}`;
  document.querySelector("#confidencePill").title = "Assessment basis, not a calibrated probability of success";
  document.querySelector("#walkabilityPair").innerHTML = `
    <div><span>Walkability</span><strong>${location.walkability ?? "--"}<small>/100</small></strong></div>
    <button class="access-insight-link" id="openCustomerAccess" type="button" title="Network-Based Customer Access; Not Predicted Visits"><span>${property ? "Property Access" : "Customer Access"}</span><strong>${(property ? property.customer_access?.index : location.inverse_walkability) ?? "--"}<small>/100</small></strong></button>
  `;
  document.querySelector("#openCustomerAccess").addEventListener("click", () => selectView("access"));

  const ranking = location.ranking_components;
  const scoreSignals = ranking ? [
    {label: "Survival Percentile", score: Math.round(100 * ranking.survival_percentile)},
    ranking.general_fit_index != null
      ? {label: "General Location Fit", score: ranking.general_fit_index}
      : {label: "H3 Cuisine Supply", score: Math.round(100 * ranking.cuisine_gap)},
  ] : location.score_components.filter((component) => component.coverage > 0);
  if (!scoreSignals.length) scoreSignals.push({label: "Insufficient Evidence", score: 0});
  document.querySelector("#barStack").innerHTML = [...scoreSignals].sort((a, b) => b.score - a.score).slice(0, 3).map((component) => `
    <div class="bar-row">
      <div class="bar-line"><span>${component.label}</span><strong>${component.score}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${component.score}%;background:${colorFor(component.score, "opportunity")}"></div></div>
    </div>
  `).join("");

  const signals = [...scoreSignals].sort((a, b) => b.score - a.score);
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
  const rows = overviewRecommendations("areas");
  const table = document.querySelector("#rankingTable");
  const previousTop = table.scrollTop;
  const previousLeft = table.scrollLeft;
  table.classList.toggle("is-property-ranking", mapInventory === "properties" && !isHexLayer());
  if (mapInventory === "properties" && !isHexLayer()) {
    const properties = overviewRecommendations("properties");
    const shown = properties;
    table.innerHTML = `<div class="table-row header"><span>#</span><span>Property / Scenario</span><span>Area Score</span><span>Customer Access</span><span>Transaction</span><span>Price</span><span>Floor Area</span><span>Details</span></div>${shown.map((row, index) => `<div class="table-row${row.id === selectedPropertyId ? " is-selected" : ""}" data-opportunity-property="${escapeHtml(row.id)}" tabindex="0"><span>${index + 1}</span><button class="place-name" type="button">${escapeHtml(row.address)}<small>${row.lead_type === "synthetic" ? "Synthetic Scenario" : "Source-Reported Lead"}</small></button><span>${row.location_score}</span><span>${row.customer_access?.index ?? "Unavailable"}</span><span>${row.transaction === "purchase" ? "Purchase" : "Lease"}</span><span>${escapeHtml(row.price_label)}</span><span>${displayNumber(row.sqft)} Sq Ft</span><button type="button" class="quiet-action">Select</button></div>`).join("")}${!properties.length ? '<div class="property-empty"><h3>No Properties Match This Brief</h3><button type="button" class="quiet-action" id="editOpportunityBrief">Edit Brief</button></div>' : ""}`;
    document.querySelector("#editOpportunityBrief")?.addEventListener("click", () => openBrief());
    document.querySelectorAll("[data-opportunity-property]").forEach(row => {
      const choose = () => {
        const property = properties.find(item => item.id === row.dataset.opportunityProperty);
        selectedPropertyId = property.id; selectedId = property.location_id;
        renderAll(); locationMap.flyTo({center: [Number(property.longitude), Number(property.latitude)], zoom: 14});
      };
      row.addEventListener("click", choose);
      row.addEventListener("keydown", event => { if (event.target === row && ["Enter", " "].includes(event.key)) { event.preventDefault(); choose(); } });
    });
    table.scrollTop = previousTop; table.scrollLeft = previousLeft;
    return;
  }
  table.innerHTML = `
    <div class="table-row header">
      <span>#</span><span>Location</span><span>Score</span><span>Customer Access</span><span>Walkability</span><span>Cuisine Supply</span><span>Commercial Fit</span><span>Compare</span>
    </div>
    ${rows.map((row, index) => `
      <div class="table-row${row.id === selectedId ? " is-selected" : ""}" data-id="${row.id}" tabindex="0" role="row" aria-current="${row.id === selectedId ? "true" : "false"}">
        <button type="button">${index + 1}</button>
        <button class="place-name" type="button">${escapeHtml(row.name)}</button>
        <span class="${scoreClass(row.opportunity)}">${row.opportunity}</span>
        <span>${row.inverse_walkability ?? "--"}</span>
        <span>${row.walkability ?? "--"}</span>
        <span>${row.score_components.find((item) => item.key === "market_gap").coverage > 0 ? row.score_components.find((item) => item.key === "market_gap").score : "Unavailable"}</span>
        <span>${row.score_components.find((item) => item.key === "economics").score}</span>
        <button class="save-row" type="button" data-save-id="${row.id}" aria-label="${savedIds.includes(row.id) ? "Remove" : "Save"} ${escapeHtml(row.name)} ${savedIds.includes(row.id) ? "from" : "to"} comparison" aria-pressed="${savedIds.includes(row.id)}">${savedIds.includes(row.id) ? "Saved" : "Save"}</button>
      </div>
    `).join("")}
  `;

  document.querySelectorAll(".table-row[data-id]").forEach((row) => {
    const choose = () => {
      selectedId = row.dataset.id;
      selectedPropertyId = null;
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
    <div class="market-group"><h3>Location Outlook</h3><div class="market-measures">
      ${measure("Estimated Three-Year Survival", location.survival?.status === "available" ? `${(100 * location.survival.probability).toFixed(1)}%` : "Unavailable", location.survival?.status === "available" ? `Experimental estimate · ${Math.round(100 * location.survival.feature_coverage)}% feature coverage` : "Not available for this assessment")}
      ${location.ranking_components ? measure("Ranking", "60% / 40%", location.ranking_components.general_fit_index != null ? "Survival percentile / general location fit; not a survival probability" : "Survival percentile / H3 cuisine supply; not a survival probability") : ""}
    </div></div>
    <div class="market-group"><h3>Local Customer Base</h3><div class="market-measures">
      ${measure("Residents", displayNumber(profile.population), "2020-2024 ACS five-year estimate")}
      ${measure("Jobs", displayNumber(profile.jobs), "2023 LODES workplace employment")}
      ${measure("Median Household Income", profile.median_household_income == null ? "Unavailable" : fmtDollar(profile.median_household_income), profile.income_margin_of_error == null ? "2020-2024 ACS five-year estimate" : `2020-2024 ACS five-year estimate · ±${fmtDollar(profile.income_margin_of_error)}`)}
    </div></div>
    <div class="market-group"><h3>Access And Movement</h3><div class="market-measures">
      ${measure("Walkability", location.walkability == null ? "Unavailable" : `${location.walkability}/100`, "EPA built-environment index")}
      ${measure("Customer Access", location.inverse_walkability == null ? "Unavailable" : `${location.inverse_walkability}/100`, "Network-based inverse walkability · relative index")}
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
      ${measure("Parcels With Reported Vacancy", displayNumber(profile.reported_vacant_storefronts), "DOF filings; availability unverified")}
      ${measure("Business Fit", `${location.business_draw}/100`, "Concept-specific screening index")}
    </div></div>
    <div class="catchment-result" id="catchmentResult"><button class="primary-action" type="button" id="analyzeCatchment">Analyze 10-Minute Walk</button><span>From Tract Centroid</span></div>
  `;
  document.querySelector("#marketCompetition").addEventListener("click", () => selectView("whitespace"));
  const cached = catchmentCache.get(`${location.id}:${dashboard.meta.concept.cuisine}`);
  if (cached) renderCatchmentResult(cached);
  else document.querySelector("#analyzeCatchment").addEventListener("click", analyzeSelectedCatchment);
}

function renderCustomerAccess() {
  const board = document.querySelector("#customerAccessBoard");
  if (!board || !dashboard) return;
  const location = selectedLocation();
  const access = location.customer_access || {};
  const property = (dashboard.properties || []).find(row => row.id === selectedPropertyId);
  const percentage = value => value == null ? "Unavailable" : `${Math.round(value * 100)}%`;
  const options = (values, selected) => values.map(([value, label]) => `<option value="${value}" ${value === selected ? "selected" : ""}>${label}</option>`).join("");
  const priceField = mode => mode === "tier"
    ? `<label class="control-field"><span>Price Range</span><select name="priceTier">${options(Object.entries(PRICE_DEFAULTS).map(([tier, price]) => [tier, `${tier} · About $${price} Per Guest`]), state.priceTier)}</select></label>`
    : `<label class="control-field"><span>Spend Per Guest ($)</span><input name="averageCheck" type="number" min="5" max="250" step="1" required value="${dashboard.meta.concept.average_check}" /></label>`;
  const measure = (label, value, caption) => `<div class="market-measure"><span>${label}</span><strong>${value}</strong><small>${caption}</small></div>`;
  board.innerHTML = `
    <div class="access-heading"><div><span class="eyebrow">${escapeHtml(location.borough)}</span><h3>${escapeHtml(location.name)}</h3></div><span class="access-status">${access.index == null ? "Limited Coverage" : "Network Assessment"}</span></div>
    ${property ? `<div class="selected-property-access"><div><span>${property.lead_type === "synthetic" ? "Synthetic Property Scenario" : "Source-Reported Lead"}</span><strong>${escapeHtml(property.address)}</strong></div><div><span>Property Access</span><strong>${property.customer_access?.index == null ? "Unavailable" : `${property.customer_access.index}/100`}</strong></div></div>` : ""}
    <form class="access-controls" id="customerAccessForm" data-price-mode="${state.priceMode}">
      <label class="control-field"><span>Dining Style</span><select name="serviceStyle">${options([["quick_service", "Quick Service"], ["casual", "Casual Dining"], ["fine_dining", "Fine Dining"]], state.serviceStyle)}</select></label>
      <label class="control-field"><span>Customer Focus</span><select name="audience">${options([["residents", "Local Residents"], ["workers", "Nearby Workers"], ["destination", "Destination Diners"]], state.audience)}</select></label>
      <label class="control-field"><span>Service Hours</span><select name="daypart">${options([["all_day", "All Day"], ["morning", "Morning"], ["lunch", "Lunch"], ["evening", "Evening"]], state.daypart)}</select></label>
      <div id="accessPriceValue">${priceField(state.priceMode)}</div>
      <div class="access-form-actions"><div class="segmented-control" role="group" aria-label="Customer Access Price Input"><button type="button" data-access-price="tier" aria-pressed="${state.priceMode === "tier"}">Price Tier</button><button type="button" data-access-price="exact" aria-pressed="${state.priceMode === "exact"}">Per Guest</button></div><button class="primary-action" type="submit">Update Assessment</button></div>
    </form>
    <div class="access-summary market-measures">
      ${measure("Area Inverse Walkability", access.index == null ? "Unavailable" : `${access.index}<small>/100</small>`, "Tract-Center Customer-Access Index")}
      ${measure("Resident Reach", displayNumber(access.resident_opportunities), "Distance-Weighted Resident Opportunities")}
      ${measure("Workplace Reach", displayNumber(access.worker_opportunities), "Distance-Weighted Job Opportunities")}
      ${measure("Reachable Origins", displayNumber(access.reachable_origin_tracts), `${access.max_walk_minutes || 30}-Minute Walking Catchment`)}
    </div>
    <div class="access-detail-grid"><section class="access-origins"><div class="access-section-head"><h3>Origin Areas</h3><button class="quiet-action" id="accessMapButton" type="button">View On Map</button></div><div id="accessOriginRows" aria-live="polite">${access.index == null ? '<p class="access-empty">Insufficient coverage for a customer-access ranking.</p>' : '<p class="access-empty">Loading Origin Areas...</p>'}</div></section>
    <aside class="access-coverage"><h3>Assessment Coverage</h3><div class="kv"><span>Walking Routes</span><strong>${percentage(access.routing_coverage)}</strong></div><div class="kv"><span>Resident Income</span><strong>${percentage(access.income_coverage)}</strong></div><div class="kv"><span>Area Walkability</span><strong>${location.walkability ?? "--"}/100</strong></div><div class="kv"><span>Travel Half-Life</span><strong>${access.travel_half_life_minutes ?? "--"} min</strong></div><div class="kv"><span>Assessment Date</span><strong>${escapeHtml(access.as_of || "Unavailable")}</strong></div>
    <details class="access-assumptions"><summary>Assessment Basis</summary><p>Local OSM walking routes, ACS residents and LODES jobs. Tract centroids represent origin areas. Travel and affordability settings are assumptions; transit journeys are not included.</p></details></aside></div>
    <div class="access-footer"><small>Relative access estimates, not predicted visits.</small><button class="quiet-action" id="accessRankButton" type="button">${state.sortBy === "inverse_walkability" ? "Restore Location Ranking" : "Rank Locations By Access"}</button></div>
  `;
  const form = document.querySelector("#customerAccessForm");
  form.querySelectorAll("[data-access-price]").forEach(button => button.addEventListener("click", () => {
    form.dataset.priceMode = button.dataset.accessPrice;
    form.querySelectorAll("[data-access-price]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
    document.querySelector("#accessPriceValue").innerHTML = priceField(form.dataset.priceMode);
  }));
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    state.serviceStyle = values.get("serviceStyle");
    state.audience = values.get("audience");
    state.daypart = values.get("daypart");
    state.priceMode = form.dataset.priceMode;
    if (state.priceMode === "tier") { state.priceTier = values.get("priceTier"); state.averageCheck = PRICE_DEFAULTS[state.priceTier]; }
    else state.averageCheck = Number(values.get("averageCheck"));
    syncBriefControls();
    loadDashboard();
  });
  document.querySelector("#accessMapButton").addEventListener("click", () => {setActiveLayer("inverse_walkability"); selectView("discover");});
  document.querySelector("#accessRankButton").addEventListener("click", async () => {
    const previous = state.sortBy;
    state.sortBy = state.sortBy === "inverse_walkability" ? "opportunity" : "inverse_walkability";
    if (!await loadDashboard()) { state.sortBy = previous; return; }
    setActiveLayer(state.sortBy === "inverse_walkability" ? "inverse_walkability" : "opportunity");
    selectView("discover");
  });
  if (activeView !== "access" || access.index == null) return;
  const params = conceptParams();
  params.set("geoid", location.geoid);
  const key = params.toString();
  const showOrigins = origins => {
    const target = document.querySelector("#accessOriginRows");
    if (!target) return;
    target.innerHTML = origins.length ? `<table class="access-origin-table"><thead><tr><th scope="col">Area</th><th scope="col">Walk</th><th scope="col">Weighted Reach</th></tr></thead><tbody>${origins.map(row => `<tr><th scope="row">${escapeHtml(row.name)}<small>Tract ${escapeHtml(row.geoid.slice(-6))}</small></th><td>${row.walking_minutes} min</td><td>${displayNumber(row.weighted_opportunities)}</td></tr>`).join("")}</tbody></table>` : '<p class="access-empty">No reachable origin areas recorded.</p>';
  };
  if (customerAccessCache.has(key)) {showOrigins(customerAccessCache.get(key)); return;}
  const revision = ++customerAccessRequest;
  fetch(`/api/customer-access?${params}`).then(response => {if (!response.ok) throw new Error("Unavailable"); return response.json();}).then(result => {
    if (revision !== customerAccessRequest || selectedId !== location.id || activeView !== "access") return;
    customerAccessCache.set(key, result.origins || []);
    showOrigins(result.origins || []);
  }).catch(() => {
    if (revision !== customerAccessRequest || activeView !== "access") return;
    document.querySelector("#accessOriginRows").innerHTML = '<p class="access-empty">Origin details are currently unavailable.</p><button class="quiet-action" id="retryAccessOrigins" type="button">Retry</button>';
    document.querySelector("#retryAccessOrigins").addEventListener("click", renderCustomerAccess);
  });
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
      ["Location Score", "opportunity"], ["Customer Access", "inverse_walkability"],
      ["Customer Fit", "customer"], ["Cuisine Supply", "whitespace"],
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
      <tr><th scope="row">Assessment Basis</th>${candidates.map(row => `<td>${assessmentBasis(row)}</td>`).join("")}</tr>
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
  const syntheticCount = candidates.filter(row => row.lead_type === "synthetic").length;
  const registryCount = candidates.filter(row => row.lead_type === "registry_record").length;
  const filter = `<div class="property-toolbar"><span>${listingCount} Sourced Leads · ${syntheticCount} Synthetic Scenarios · ${registryCount} Registry Records</span><div class="segmented-control" role="group" aria-label="Property Records"><button type="button" data-property-view="all" aria-pressed="${propertyView === "all"}">All</button><button type="button" data-property-view="listing" aria-pressed="${propertyView === "listing"}">Sourced</button><button type="button" data-property-view="synthetic" aria-pressed="${propertyView === "synthetic"}">Scenarios</button>${state.dealType !== "purchase" ? `<button type="button" data-property-view="registry_record" aria-pressed="${propertyView === "registry_record"}">Registry</button>` : ""}</div></div>`;
  if (state.dealType === "purchase" && propertyView === "registry_record") propertyView = "all";
  if (propertyView !== "all") candidates = candidates.filter(row => row.lead_type === propertyView);
  if (!candidates.length) {
    const emptyTitle = propertyView === "synthetic" ? "No Scenarios Match This Budget" : propertyView === "listing" ? "No Sourced Leads Match" : "No Property Records Found";
    document.querySelector("#leaseBoard").innerHTML = `
      ${filter}
      <article class="property-empty">
        <h3>${emptyTitle}</h3>
        <button class="quiet-action" type="button" onclick="openBrief()">Edit Search Brief</button>
      </article>
    `;
    bindPropertyFilters();
    renderPropertyShortlist();
    return;
  }
  const shown = candidates.slice(0, propertyVisible);
  document.querySelector("#leaseBoard").innerHTML = filter + shown.map((row) => {
    const priceLine = row.price_label || "Unavailable";
    const imageClass = row.image ? "property-image" : "property-image no-image";
    const imageStyle = row.image ? ` style="background-image:url('${escapeHtml(row.image.replaceAll("'", "%27"))}')"` : "";
    const badge = row.transaction_label || "Property Record";
    const sqft = row.sqft ? `${row.sqft.toLocaleString()} Sq Ft` : (row.sqft_label || "Sq Ft Not In Source");
    const contactUrl = row.broker_contact && /^https:\/\/[^\s]+$/i.test(row.broker_contact) ? row.broker_contact : null;
    return `
      <article data-property-card="${escapeHtml(row.id)}" class="property-card${row.lead_type === "synthetic" ? " synthetic-card" : ""}${row.id === selectedPropertyId ? " is-selected-property" : ""}">
        ${row.lead_type === "synthetic" ? "" : `<div class="${imageClass}"${imageStyle}>
          <span>${escapeHtml(badge)}</span>
          ${row.image ? "" : "<strong>Photo Unavailable</strong>"}
        </div>`}
        <div class="property-body">
          ${row.lead_type === "synthetic" ? '<span class="scenario-badge">Synthetic Scenario</span>' : ""}
          <div class="property-title">
            <div>
              <h3>${escapeHtml(row.title)}</h3>
              <p>${escapeHtml(row.address)}</p>
            </div>
            <div class="property-area-score"><span>Area Score</span><strong class="${scoreClass(row.fit_score)}">${row.fit_score}</strong></div>
          </div>
          <div class="property-specs">
            <span>${escapeHtml(row.lead_type === "synthetic" ? row.corridor_context.replace(" scenario", "") : row.location_name)}</span>
            ${row.sqft ? `<span>${sqft}</span>` : ""}
            ${row.lead_type === "synthetic" ? `<span>${escapeHtml(row.condition.replace(" (Simulated)", ""))}</span>` : ""}
          </div>
          ${row.site_evidence?.status === "available" ? `<div class="kv"><span>Approx. 10-Minute Walk</span><strong>${row.site_evidence.recorded_restaurants.toLocaleString()} Restaurants · ${row.site_evidence.nearby_subway_stations} Subway Stations</strong></div>` : ""}
          <div class="kv"><span>Customer Access</span><strong>${row.customer_access?.index == null ? "Unavailable" : `${row.customer_access.index}/100`}</strong></div>
          ${row.site_evidence?.same_cuisine_restaurants != null ? `<div class="kv"><span>Recorded Same-Cuisine Restaurants</span><strong>${row.site_evidence.same_cuisine_restaurants}</strong></div>` : ""}
          ${row.site_evidence?.status === "unavailable" && row.lead_type !== "synthetic" ? '<div class="kv"><span>Walking Catchment</span><strong>Unavailable</strong></div>' : ""}
          <div class="kv"><span>${row.lead_type === "synthetic" ? "Modeled Price" : row.transaction === "purchase" ? "Asking Price" : row.transaction === "lease" ? "Asking Rent" : "Asking Price / Rent"}</span><strong>${escapeHtml(priceLine)}</strong></div>
          ${row.lead_type === "synthetic" ? `<div class="kv"><span>${row.transaction === "purchase" ? "Modeled Price / SF" : "Modeled Annual Rent / SF"}</span><strong>${escapeHtml(fmtDollar(row.transaction === "purchase" ? row.asking_price_psf : row.annual_rent_psf))}</strong></div>
          <div class="property-source-note">Approximate area · Not an available listing</div>
          <details class="property-details"><summary>Space Details</summary>
            <div class="kv"><span>Setting</span><strong>${escapeHtml(row.corridor_context)}</strong></div>
            <div class="kv"><span>Building</span><strong>${escapeHtml(row.building_type)} · ${escapeHtml(row.floor)} Floor</strong></div>
            <div class="kv"><span>Kitchen</span><strong>${escapeHtml(row.kitchen_status)}</strong></div>
            <div class="kv"><span>Ventilation</span><strong>${escapeHtml(row.ventilation_status)}</strong></div>
            <div class="kv"><span>Outdoor Space</span><strong>${escapeHtml(row.outdoor_space_potential)}</strong></div>
          </details>` : ""}
          ${row.lead_type === "synthetic" ? "" : `<div class="kv"><span>Status</span><strong>${escapeHtml(row.availability)}</strong></div>`}
          ${row.checked_at ? `<div class="kv"><span>Source Checked</span><strong>${escapeHtml(row.checked_at)}</strong></div>` : ""}
          ${row.broker_name ? `<div class="kv"><span>Broker / Owner</span><strong>${escapeHtml(row.broker_name)}</strong></div>` : ""}
          ${row.broker_contact && !contactUrl ? `<div class="kv"><span>Leasing Contact</span><strong>${escapeHtml(row.broker_contact)}</strong></div>` : ""}
          ${row.lead_type === "synthetic" ? "" : `<div class="kv"><span>${row.lead_type === "registry_record" ? "Reported Activity" : "Condition"}</span><strong>${escapeHtml(row.condition)}</strong></div>`}
          ${row.lead_type === "registry_record" ? '<div class="property-source-note">Registry Record · Transaction And Contact Unverified</div>' : ""}
          ${row.source_url ? `<a class="property-link" href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener noreferrer">Source Listing</a>` : ""}
          ${contactUrl ? `<a class="property-link" href="${escapeHtml(contactUrl)}" target="_blank" rel="noopener noreferrer">Contact Leasing Office</a>` : ""}
          ${row.latitude && row.longitude ? `<button type="button" class="quiet-action" data-property-map="${escapeHtml(row.id)}">Show On Map</button>` : ""}
          <button type="button" class="quiet-action" data-save-property="${escapeHtml(row.id)}" aria-pressed="${currentPlan().property_ids.includes(row.id)}">${currentPlan().property_ids.includes(row.id) ? "Saved Property" : "Save Property"}</button>
          ${row.lead_type !== "synthetic" ? `<a class="property-link" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${row.address}, ${row.borough}, New York`)}" target="_blank" rel="noopener noreferrer">View Address</a>` : ""}
        </div>
      </article>
    `;
  }).join("") + (candidates.length > shown.length ? `<button class="quiet-action property-more" type="button" id="showMoreProperties">Show More · ${candidates.length - shown.length} Remaining</button>` : "");
  document.querySelector("#showMoreProperties")?.addEventListener("click", () => { propertyVisible += 12; renderLease(); });
  document.querySelectorAll("[data-property-map]").forEach(button => button.addEventListener("click", () => {
    const property = (dashboard.properties || []).find(row => row.id === button.dataset.propertyMap);
    if (!property) return;
    selectedId = property.location_id; selectedPropertyId = property.id;
    mapInventory = "properties"; document.querySelector("#mapInventorySelect").value = mapInventory;
    if (isHexLayer()) setActiveLayer("opportunity");
    renderAll(); selectView("discover");
    locationMap.flyTo({center: [Number(property.longitude), Number(property.latitude)], zoom: 15});
  }));
  bindPropertyFilters();
  renderPropertyShortlist();
}

function bindPropertyFilters() {
  document.querySelectorAll("[data-property-view]").forEach(button => button.addEventListener("click", () => {
    propertyView = button.dataset.propertyView;
    propertyVisible = 12;
    renderLease();
  }));
}

function renderWhitespace() {
  if (!document.querySelector("#competitionExplorer")) document.querySelector("#gapBoard").innerHTML = "<section id=\"competitionExplorer\" class=\"competition-explorer\"></section>";
}

async function loadCompetition() {
  renderWhitespace();
  await renderCompetitionExplorer();
}

function renderFinance() {
  const finance = dashboard.finance;
  document.querySelector("#financeScenarioForm").hidden = true;
  document.querySelector("#financeBoard").hidden = state.dealType !== "purchase";
  if (state.dealType === "purchase") {
    const verifiedPrices = (dashboard.properties || []).filter(row => row.transaction === "purchase" && row.lead_type === "listing" && row.asking_price).map(row => row.asking_price);
    const scenarioPrices = (dashboard.properties || []).filter(row => row.transaction === "purchase" && row.lead_type === "synthetic" && row.asking_price).map(row => row.asking_price);
    const askingPrices = verifiedPrices.length ? verifiedPrices : scenarioPrices;
    const lowestAskingPrice = askingPrices.length ? fmtPrice(Math.min(...askingPrices)) : "Unavailable";
    document.querySelector("#financeBoard").innerHTML = `
      <article class="finance-cell"><h3>Purchase Budget</h3><strong class="finance-figure">${fmtPrice(state.purchaseBudget)}</strong><span class="finance-basis">User Budget</span></article>
      <article class="finance-cell"><h3>${verifiedPrices.length ? "Lowest Listed Asking Price" : "Lowest Modeled Purchase Price"}</h3><strong class="finance-figure">${lowestAskingPrice}</strong><span class="finance-basis">${verifiedPrices.length ? `${verifiedPrices.length} Source-Linked Listing${verifiedPrices.length === 1 ? "" : "s"}` : scenarioPrices.length ? "Synthetic Scenarios · No Verified Sale Offer" : "No Sale Scenario In Budget"}</span></article>
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
  const property = (dashboard.properties || []).find(row => row.id === selectedPropertyId);
  const alternatives = savedIds.filter(id => id !== location.id).map(id => allLocations().find(row => row.id === id)).filter(Boolean);
  document.querySelector("#reportBoard").innerHTML = `
    <div class="report-toolbar"><span>Location Brief</span><button class="primary-action" id="printReport" type="button">Print / Save PDF</button></div>
    <article class="location-report">
      <header><span class="eyebrow">Groundwork / New York City</span><span>${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span></header>
      <h2>${escapeHtml(conceptName())}</h2>
      <p>${profileLabel(state.profile)} · ${escapeHtml(cuisineLabel())} · ${state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`} · ${dealLabel(state.dealType)} · ${state.dealType === "purchase" ? `${fmtPrice(state.purchaseBudget)} Purchase Budget` : `${fmtMoney(state.rentCap)}/Month Budget`}</p>
      <section class="report-recommendation"><div><span class="eyebrow">Selected Location</span><h3>${escapeHtml(location.name)}</h3><p>${escapeHtml(location.recommendation)}</p></div><strong>${location.opportunity}<small>/100</small></strong></section>
      ${property ? `<h3>Selected Property Scenario</h3><div class="report-factors"><div class="kv"><span>${escapeHtml(property.address)}</span><strong>${escapeHtml(property.price_label)}</strong></div><div class="kv"><span>${property.transaction === "purchase" ? "Purchase" : "Lease"} · ${displayNumber(property.sqft)} Sq Ft</span><strong>${property.lead_type === "synthetic" ? "Synthetic · Approximate Location" : "Source-Reported Lead"}</strong></div></div>` : ""}
      ${alternatives.length ? `<h3>Saved Alternatives</h3><div class="report-factors">${alternatives.map(row => `<div class="kv"><span>${escapeHtml(row.name)}</span><strong>${row.opportunity}/100</strong></div>`).join("")}</div>` : ""}
      <p>${assessmentBasis(location)} · ${location.ranking_components ? "Experimental Model Ranking" : "Screening Estimate"}</p>
      <h3>Location Factors</h3>
      <div class="report-factors">${location.score_components.map((item) => `<div class="kv"><span>${escapeHtml(item.label)}</span><strong>${item.coverage > 0 ? `${item.score}/100` : "Unavailable"}</strong></div>`).join("")}</div>
      <h3>Due Diligence</h3><ul>${location.risk_flags.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")}</ul>
      <footer>${location.confidence_score}% Evidence Strength · Preliminary Tract-Level Screening<br>Walkability ${location.walkability ?? "Unavailable"}/100 · Customer Access ${location.inverse_walkability ?? "Unavailable"}/100<br>Scores Are Relative Indicators, Not Visit Or Revenue Forecasts.<br>Property Availability, Asking Prices And Lease Terms Require Verification.</footer>
    </article>
  `;
  document.querySelector("#printReport").addEventListener("click", () => window.print());
  renderPlanReport();
}

function renderDataLayers() {
  document.querySelector("#layerBoard").innerHTML = `
    <div class="view-heading"><div><span class="eyebrow">Data Register</span><h3>Sources & Coverage</h3></div></div>
    <div class="assessment-status-strip"><div><span>Location Ranking</span><strong>${dashboard.survival_model?.ranking_mode?.startsWith("survival_") ? "Experimental Survival Ranking" : "Location-Fit Screening"}</strong></div><div><span>Survival Inference</span><strong>${dashboard.survival_model?.status === "available" ? "Experimental Artifact Connected" : "Not Deployed"}</strong></div><div><span>Customer Access</span><strong>${dashboard.customer_access_model?.status === "available" ? "Network-Based Scenario" : "Unavailable"}</strong></div><div><span>Property Inventory</span><strong>${dashboard.property_search?.synthetic_inventory_total ?? "--"} Synthetic Scenarios</strong></div></div>
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
  const key = `${menuKey()}:${conceptParams()}`;
  if (key === menuCatalogKey && menuCatalog && menuCatalog.status !== "error") return renderMenu();
  const currentRequest = ++menuRequestId;
  menuCatalogKey = key;
  menuCatalog = null;
  renderMenu();
  try {
    const response = await fetch(`/api/menu/suggestions?${conceptParams()}`);
    if (!response.ok) throw new Error("Menu suggestions unavailable");
    const result = await response.json();
    if (currentRequest !== menuRequestId || key !== `${menuKey()}:${conceptParams()}`) return;
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
    ["Ingredient Margin", averageMargin == null ? "—" : `${Math.round(averageMargin * 100)}%`],
  ].map(([name, value]) => `<div class="menu-kpi"><span>${name}</span><strong>${value}</strong></div>`).join("");
  const unpriced = savedMenu.filter(item => !(Number(item.price) > 0)).length;
  const underCost = costed.filter(item => Number(item.cost) >= Number(item.price)).length;
  document.querySelector("#menuReviewStatus").textContent = underCost ? `${underCost} Items At Or Below Ingredient Cost` : unpriced ? `${unpriced} Items Need Prices` : savedMenu.length ? "All Items Priced" : "";
  document.querySelector("#menuApplyPricing").disabled = !savedMenu.some(item => !(Number(item.price) > 0) && Number(item.cost) > 0);
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
      <span class="menu-margin" title="Menu price minus ingredient cost; excludes labor, rent and other expenses">${Number(item.price) > 0 && item.cost !== "" && item.cost != null ? `${money(Number(item.price) - Number(item.cost))} / Portion` : "—"}</span>
      <div class="menu-item-tools"><button type="button" data-recipe-edit="${escapeHtml(item.id)}" class="quiet-action">Recipe Cost</button><button type="button" data-menu-duplicate="${escapeHtml(item.id)}" class="quiet-action">Duplicate</button></div>
      <div class="menu-order"><button type="button" data-menu-move="up" aria-label="Move ${escapeHtml(item.name)} Up" title="Move Up">↑</button><button type="button" data-menu-move="down" aria-label="Move ${escapeHtml(item.name)} Down" title="Move Down">↓</button></div>
      <button type="button" class="menu-remove" data-menu-remove title="Remove ${escapeHtml(item.name)}" aria-label="Remove ${escapeHtml(item.name)}">×</button>
      <input class="menu-note" type="text" data-menu-note maxlength="200" value="${escapeHtml(item.note || "")}" placeholder="Description shown on menu" aria-label="Description For ${escapeHtml(item.name)}" />
    </div>`).join("")}</div>`).join("") : '<div class="menu-empty">No Dishes Added Yet.</div>';
  document.querySelector("#menuPreview").innerHTML = `<div class="menu-preview-head"><span>Groundwork Menu</span><h3>${escapeHtml(conceptName())}</h3><p>${escapeHtml(label)}</p></div>${groups.length ? groups.map(([section, items]) => `<section><h4>${section}</h4>${items.map(item => `<div class="menu-preview-item"><div><strong>${escapeHtml(item.name)}</strong>${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}</div><span>${Number(item.price) > 0 ? money(Number(item.price)) : ""}</span></div>`).join("")}</section>`).join("") : '<div class="menu-empty">Add dishes to preview your menu.</div>'}`;
  renderMenuPlanning();
  renderAdvancedMenu();
}

function money(value) { return new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Number(value)); }

function prepareEconomicsLab() {
  if (!dashboard || activeView !== "finance") return;
  const key = `groundwork-economics-v1:${menuKey()}:${state.dealType}`;
  const property = (dashboard.properties || []).find(row => row.id === selectedPropertyId);
  document.querySelector("#economicsUseProperty").disabled = !property || property.transaction !== "lease" || !(property.asking_rent > 0);
  if (economicsContext === key) return;
  economicsContext = key;
  const defaults = {monthly_rent: state.dealType === "purchase" ? 0 : state.rentCap,
    monthly_fixed: Number(state.otherFixedCosts) || 12000, operating_days: Number(state.operatingDays) || 26,
    price: dashboard.meta.concept.average_check, unit_cost: +(dashboard.meta.concept.average_check * .35).toFixed(2),
    daily_covers:100,capacity:200,elasticity:1.5,congestion_cost:5,profit_target:500};
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Use the labeled illustrative defaults. */ }
  saved = currentPlan().draft && Object.keys(currentPlan().draft).length ? currentPlan().draft : saved;
  const form = document.querySelector("#economicsLabForm");
  Object.entries(defaults).forEach(([name,value]) => { form.elements.namedItem(name).value = saved?.[name] ?? value; });
  calculateEconomics();
}

async function calculateEconomics() {
  const form = document.querySelector("#economicsLabForm");
  if (!form.reportValidity()) return;
  const request = ++economicsRequestId;
  const params = new URLSearchParams(new FormData(form));
  const status = document.querySelector("#economicsStatus");
  status.textContent = "Calculating Scenario...";
  try {
    const response = await fetch(`/api/economics/scenario?${params}`);
    const result = await response.json();
    if (request !== economicsRequestId) return;
    if (!response.ok) throw new Error(result.error || "Scenario unavailable");
    try {
      localStorage.setItem(economicsContext, JSON.stringify(Object.fromEntries(params)));
      const plan = currentPlan(); plan.draft = Object.fromEntries(params); savePlan(plan);
    } catch { /* Calculation does not require browser storage. */ }
    status.textContent = "Illustrative Demand Assumptions · Not A Sales Or Profit Forecast";
    renderEconomicsCharts(result);
    renderScenarioLibrary();
  } catch (error) {
    if (request !== economicsRequestId) return;
    economicsResult = null;
    status.textContent = error.message;
    economicsCharts.forEach(chart => chart.destroy()); economicsCharts = [];
    document.querySelector("#economicsResults").replaceChildren();
  }
}

function renderEconomicsCharts(result) {
  economicsResult = result;
  document.querySelector("#economicsResults").hidden = false;
  economicsCharts.forEach(chart => chart.destroy()); economicsCharts = [];
  const best = result.modeled_optimum;
  const kpis = [["Daily Operating Profit", money(result.current_daily_profit)],
    ["Break-Even Volume", result.break_even_covers == null ? "Not Feasible Within Capacity" : `${result.break_even_covers} Covers / Day`],
    ["Profit Target Volume", result.target_profit_covers == null ? "Not Feasible Within Capacity" : `${result.target_profit_covers} Covers / Day`],
    ["Capacity Utilization", `${Math.round(result.capacity_utilization*100)}%`]];
  document.querySelector("#economicsResults").innerHTML = `<div class="economics-kpis">${kpis.map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join("")}</div>
    <div class="economics-chart-grid">${[["econRevenue","Revenue & Total Cost","Daily Covers","USD / Day"],["econProfit","Daily Profit & Volume","Daily Covers","USD / Day"],["econMarginal","Demand, Marginal Revenue & Marginal Cost","Daily Covers","USD / Guest"],["econPricing","Price & Modeled Daily Profit","Spend Per Guest ($)","USD / Day"]].map(([id,title])=>`<section class="economics-chart-section"><h4>${title}</h4><div class="economics-chart"><canvas id="${id}" role="img" aria-label="${title}"></canvas></div></section>`).join("")}</div>
    <div class="economics-optimum"><div><span>Best Modeled Spend</span><strong>${money(best.price)}</strong></div><div><span>Best Modeled Covers</span><strong>${best.covers.toFixed(1)} / Day</strong></div><div><span>Best Modeled Daily Profit</span><strong>${money(best.daily_profit)}</strong></div><div><span>Capacity Constraint</span><strong>${best.capacity_binding ? "Binding" : "Not Binding"}</strong></div></div>
    <details class="economics-assumptions"><summary>Scenario Assumptions</summary><ul>${result.assumptions.map(value=>`<li>${escapeHtml(value)}</li>`).join("")}</ul><p>At an interior optimum, marginal revenue equals marginal cost. Capacity and zero-volume boundaries are included.</p></details>`;
  const colors = getComputedStyle(document.documentElement);
  const text = colors.getPropertyValue("--text").trim() || "#38515a";
  const line = colors.getPropertyValue("--line").trim() || "#d6e1e8";
  const series = (name,rows,x,y,color,dash=[])=>({label:name,data:rows.map(row=>({x:row[x],y:row[y]})),borderColor:color,backgroundColor:color,borderWidth:2,pointRadius:0,pointHitRadius:10,borderDash:dash,tension:0});
  const draw = (id,datasets,xTitle,yTitle) => {
    economicsCharts.push(new Chart(document.querySelector(`#${id}`),{type:"line",data:{datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{intersect:false,mode:"nearest"},plugins:{legend:{labels:{color:text,boxWidth:12,font:{size:11}}},tooltip:{callbacks:{label:context=>`${context.dataset.label}: ${money(context.parsed.y)}`}}},scales:{x:{type:"linear",title:{display:true,text:xTitle,color:text},ticks:{color:text,maxTicksLimit:6},grid:{color:line}},y:{title:{display:true,text:yTitle,color:text},ticks:{color:text,maxTicksLimit:6},grid:{color:line}}}}}));
  };
  const rows = result.volume_curve;
  draw("econRevenue",[series("Revenue",rows,"covers","revenue","#15836e"),series("Total Cost",rows,"covers","total_cost","#c44b55")],"Daily Covers","USD / Day");
  draw("econProfit",[series("Operating Profit",rows,"covers","profit","#246da5"),series("Break-Even",rows.map(row=>({...row,zero:0})),"covers","zero","#717982",[5,4]),series("Profit Target",rows.map(row=>({...row,target:result.inputs.profit_target})),"covers","target","#bb7b17",[5,4])],"Daily Covers","USD / Day");
  draw("econMarginal",[series("Demand Price",rows,"covers","demand_price","#246da5"),series("Marginal Revenue",rows,"covers","marginal_revenue","#b0609e"),series("Marginal Cost",rows,"covers","marginal_cost","#c44b55")],"Daily Covers","USD / Guest");
  draw("econPricing",[series("Demand-Adjusted Profit",result.price_curve,"price","profit","#15836e")],"Spend Per Guest ($)","USD / Day");
}

function exportMenu() {
  if (!savedMenu.length) return;
  const quote = value => `"${String(value ?? "").replace(/^[=+@\-\t\r]/, "'$&").replaceAll('"', '""')}"`;
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
  const section = ["lease", "finance", "menu"].includes(activeView) ? "lease" : ["workspace", "reports", "layers", "settings"].includes(activeView) ? "reports" : "discover";
  document.querySelectorAll("[data-section-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.sectionView === section)));
  document.querySelectorAll(".nav-group").forEach(group => group.classList.toggle("has-active-tab", !!group.querySelector(".is-active")));
  document.querySelector(".workspace")?.classList.toggle("is-discover", activeView === "discover");
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("is-hidden", panel.dataset.panel !== activeView);
  });
  if (activeView === "discover" && locationMap) requestAnimationFrame(() => locationMap.resize());
  if (activeView === "whitespace") loadCompetition();
}

function renderAll() {
  rememberPropertySelection();
  const modelStatus = document.querySelector("#survivalModelStatus");
  if (modelStatus) {
    const model = dashboard.survival_model;
    modelStatus.hidden = !model || !model.ranking_mode.startsWith("survival_");
    modelStatus.textContent = model ? (model.ranking_mode === "survival_general_fit" ? "Experimental Survival And General Location Fit" : "Experimental Survival And Cuisine Supply") : "";
  }
  renderConceptChrome();
  renderLocationSelect();
  renderMetrics();
  renderMap();
  renderIntel();
  renderRanking();
  renderMarketProfile();
  renderCustomerAccess();
  renderCompare();
  renderLease();
  renderWhitespace();
  renderFinance();
  renderReports();
  renderDataLayers();
  renderPanels();
  renderMenu();
  if (activeView === "finance") prepareEconomicsLab();
  renderTeamExplorers();
  if (activeView === "workspace") prepareBusinessWorkspace();
}

function renderConceptChrome() {
  const name = conceptName();
  const titles = {discover: "Location Search", scorecard: "Market Profile", access: "Customer Access", whitespace: "Competition", compare: "Location Comparison", lease: "Property Search", finance: "Operating Economics", menu: "Menu Studio", workspace: "Business Plan", reports: "Decision Report", layers: "Sources & Coverage", settings: "Workspace Settings"};
  document.querySelector("#workspaceTitle").textContent = `${name} ${titles[activeView] || "Location Search"}`;
  document.title = `${titles[activeView] || "Location Search"} | Groundwork NYC`;
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
function targetMenuPrice(cost, percentage) {
  const value = Number(cost), target = Number(percentage);
  if (!Number.isFinite(value) || value <= 0 || !Number.isFinite(target) || target < 10 || target > 70) return null;
  const price = Math.ceil(value / (target / 100) * 2) / 2;
  return price <= 1000 ? price : null;
}
document.querySelector("#menuApplyPricing").addEventListener("click", () => {
  const target = document.querySelector("#menuTargetCost");
  if (!target.reportValidity()) return;
  let changed = 0;
  for (const item of savedMenu) {
    const price = targetMenuPrice(item.cost, target.value);
    if (!(Number(item.price) > 0) && price != null) { item.price = price.toFixed(2); changed++; }
  }
  persistMenu(`${changed} Prices Set From Ingredient Costs`); renderMenu();
});
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
  rememberRemovedMenuItem(id);
  savedMenu = savedMenu.filter(item => item.id !== id);
  const plan = currentPlan(); delete plan.basket[id]; delete plan.menu_details[id]; savePlan(plan);
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
  selectedPropertyId = null;
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
  syncEntryFields();
}

function closeBrief() {
  document.querySelector("#briefOverlay").classList.remove("is-open");
}

function openBrief() {
  syncBriefControls();
  document.querySelector("#briefOverlay").classList.add("is-open");
}

function applyBrief() { submitEntryBrief(); }

document.querySelector("#dealSelect").addEventListener("change", (event) => {
  state.dealType = event.target.value;
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#briefDeal").addEventListener("change", (event) => {
  state.dealType = event.target.value || "lease";
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

document.querySelectorAll("#conceptInput, #searchInput").forEach(input => {
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
document.querySelector("#heatmapMetricSelect").addEventListener("change", event => {
  const status = document.querySelector("#dashboardStatus");
  if (status.textContent === "No Recorded Coverage For This Feature And Concept.") status.hidden = true;
  activeHeatMetric = event.target.value;
  mapPopup?.remove();
  if (activeLayer === "huff_demand" || activeLayer === "concept_demand") activeLayer = "opportunity";
  document.querySelector("#mapLayerSelect").value = activeLayer;
  hexRequestId++; clearHexLayer(); renderMap(); renderRanking();
  document.querySelector("#mapModeTitle").textContent = activeHeatMetric ? `${heatmapTitles[activeHeatMetric]} Heatmap` : "Location Opportunities";
});
document.querySelector("#economicsLabForm").addEventListener("submit", event => { event.preventDefault(); calculateEconomics(); });
document.querySelector("#economicsLabForm").addEventListener("input", () => {
  clearTimeout(economicsInputTimer);
  if (!document.querySelector("#economicsLabForm").checkValidity()) {
    economicsRequestId++; economicsResult = null;
    document.querySelector("#economicsResults").hidden = true;
    document.querySelector("#economicsStatus").textContent = "Enter Valid Scenario Inputs To Update Results.";
    return;
  }
  economicsInputTimer = setTimeout(() => { if (document.querySelector("#economicsLabForm").checkValidity()) calculateEconomics(); }, 450);
});
document.querySelector("#economicsUseProperty").addEventListener("click", () => {
  const property = (dashboard.properties || []).find(row => row.id === selectedPropertyId);
  if (property?.transaction === "lease" && property.asking_rent > 0) {
    document.querySelector('#economicsLabForm [name="monthly_rent"]').value = property.asking_rent;
    calculateEconomics();
  }
});
document.querySelector("#mapInventorySelect").addEventListener("change", event => { mapInventory = event.target.value; renderMap(); renderRanking(); renderMetrics(); });
document.querySelector("#mapBasemapSelect").addEventListener("change", event => changeMapView(event.target.value));
document.querySelectorAll("[data-section-view]").forEach(button => button.addEventListener("click", () => selectView(button.dataset.sectionView)));
document.querySelector("#showRestaurantsToggle").checked = showExistingRestaurants;
document.querySelector("#showRestaurantsToggle").addEventListener("change", event => {
  showExistingRestaurants = event.target.checked;
  localStorage.setItem("groundwork-show-restaurants", String(showExistingRestaurants));
  syncRestaurantVisibility();
});

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
document.querySelectorAll("[data-logout]").forEach(button => button.addEventListener("click", async () => {
  button.disabled = true;
  clearTimeout(workspaceSyncTimer);
  for (let attempt=0; workspaceSyncing && attempt<30; attempt++) await new Promise(resolve=>setTimeout(resolve,100));
  if (accountOwner && localStorage.getItem(`groundwork-workspace-dirty:${accountOwner}`)) await syncWorkspace();
  document.querySelector("#logoutForm").submit();
}));
setTheme(dashboardThemeChoice, false);
updateConceptImage(state.cuisine);
loadConceptImages();
initializeWorkspace();
initializePlanningControls();
initializeMenuLab();
initializeBusinessWorkspace();
setActiveLayer(activeLayer);
