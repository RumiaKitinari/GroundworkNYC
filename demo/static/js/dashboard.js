let dashboard = null;
let selectedId = null;
let activeLayer = "opportunity";
let activeView = "discover";
let requestId = 0;
let profileComparisonId = "";
let profileRenderId = 0;
let profileAreasPromise = null;
const profileCache = new Map();
const profileResolved = new Map();
let profileAreasResolved = null;
const profileExpanded = {resident_age: true, job_age: true, job_earnings: true, job_industry: false};
const transitCache = new Map();
const transitExpanded = {subway: false, bike: false, pedestrian: false, taxi: false};
let transitRenderId = 0;
const competitionCache = new Map();
const competitionResolved = new Map();
let competitionRenderId = 0;
let competitionBreakdownOpen = true;
let competitionComparisonOpen = true;
let competitionFilter = "all";
let competitionQuery = "";
let competitionVisible = 10;
let competitionContext = "";
let storefrontPromise = null;
let storefrontData = null;
let storefrontArea = "all";
let storefrontVacancy = "all";
let storefrontQuery = "";
let storefrontVisible = 12;
let propertyTab = "research";
let locationMap = null;
let mapMarkers = [];
let mapPopup = null;
let restaurantPopup = null;
let restaurantDataPromise = null;
let restaurantStyleRevision = 0;
let showExistingRestaurants = true;
let mapDataset = "";
let mapViewRequestId = 0;
let activeBasemap = window.GROUNDWORK_HAS_STREET_TILES ? "streets" : "aerial";
// The inner box includes all five boroughs; the outer box leaves room at the edges.
const NYC_VIEW_BOUNDS = [[-74.27, 40.48], [-73.70, 40.92]];
const NYC_LIMIT_BOUNDS = [[-74.32, 40.43], [-73.65, 40.97]];
const systemTheme = matchMedia("(prefers-color-scheme: dark)");
let dashboardThemeChoice = ["light", "dark"].includes(localStorage.getItem("groundwork-theme")) ? localStorage.getItem("groundwork-theme") : "system";
let currentTheme = dashboardThemeChoice === "system" ? (systemTheme.matches ? "dark" : "light") : dashboardThemeChoice;
let hovered3DFeatureId = "";
let pinned3DFeature = false;
let savedIds = [];
let savedKey = "";
const catchmentCache = new Map();
let competitionRequest = 0;
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
  // Keep this view vector-only even if the provider adds a raster layer later.
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
  if (view === "scorecard" && dashboard) {
    renderResidentWorkerProfile();
    renderTransitActivity();
    renderCompetitionExplorer();
  }
  if (view === "lease" && dashboard) {
    syncPropertyTabs();
    if (propertyTab === "research") renderStorefrontExplorer();
  }
  if (view === "menu") loadMenuSuggestions();
  persistDashboardView();
}

function syncPropertyTabs() {
  const labels = {lease: "Lease Listings", purchase: "Purchase Listings", either: "Lease & Purchase Listings"};
  document.querySelector("#propertyTabListings").textContent = labels[state.dealType] || labels.lease;
  document.querySelectorAll("[data-property-tab]").forEach(button => {
    const selected = button.dataset.propertyTab === propertyTab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelector("#propertyPanelResearch").hidden = propertyTab !== "research";
  document.querySelector("#propertyPanelListings").hidden = propertyTab !== "listings";
}

function selectPropertyTab(tab, focus = false) {
  if (tab !== "research" && tab !== "listings") return;
  propertyTab = tab;
  syncPropertyTabs();
  if (propertyTab === "research" && dashboard) renderStorefrontExplorer();
  persistDashboardView();
  if (focus) document.querySelector(`[data-property-tab="${tab}"]`).focus();
}

function persistDashboardView() {
  if (!dashboard || !selectedId) return;
  sessionStorage.setItem("groundwork-dashboard-view", JSON.stringify({
    activeView, selectedId, comparisonId: profileComparisonId,
    profileExpanded, transitExpanded, competitionBreakdownOpen, competitionComparisonOpen,
    competitionContext, competitionFilter, competitionQuery, competitionVisible,
    storefrontArea, storefrontVacancy, storefrontQuery, storefrontVisible, propertyTab,
  }));
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
    hasSubmittedBrief = hasExplicitCuisine(state.cuisine);
    legacyCuisineRequired = !hasSubmittedBrief;
    return true;
  } catch {
    return false;
  }
}

function persistBrief() {
  if (!hasSubmittedBrief) return;
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
  if (hasSavedBrief && hasSubmittedBrief) closeBrief();
  if (legacyCuisineRequired) {
    document.querySelector("#cuisineError").hidden = false;
    document.querySelector("#briefSkip").hidden = true;
    document.querySelector("#briefOverlay").classList.add("is-open");
  }
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
  huff_demand: ["#ad4648", "#db7952", "#e9ba6e", "#a9c77b", "#49ad8c", "#087d82"],
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
  if (layer !== activeLayer) {hexRequestId++; clearHexLayer();}
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
  document.querySelectorAll("#conceptInput, #searchInput").forEach(input => {
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
    document.querySelector("#briefDietary").value = item.dietary;
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
    updateHuffAvailability();
    hexCache.clear();
    hexRequestId++;
    clearHexLayer();
    profileRenderId++; transitRenderId++; competitionRenderId++; competitionRequest++;
    profileAreasPromise = null; profileAreasResolved = null;
    profileCache.clear(); profileResolved.clear(); transitCache.clear();
    competitionCache.clear(); competitionResolved.clear();
    storefrontPromise = null; storefrontData = null;
    restaurantDataPromise = null;
    restaurantStyleRevision++;
    if (locationMap?.getSource("existing-restaurants")) {
      RESTAURANT_LAYERS.forEach(id => {if (locationMap.getLayer(id)) locationMap.removeLayer(id);});
      locationMap.removeSource("existing-restaurants");
    }
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
      if (activeView === "lease") {
        document.querySelector("#leaseBoard").innerHTML = '<article class="property-listings-empty property-listings-error" role="alert"><div><h3>Listings could not load</h3><p>The dashboard request failed. Retry to check the listing source again.</p><button type="button" class="quiet-action">Retry</button></div></article>';
        document.querySelector("#leaseBoard button").addEventListener("click", loadDashboard);
      }
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
  requestAnimationFrame(() => {locationMap?.resize(); updateNycConstraints();});
}

function updateNycConstraints() {
  if (!locationMap) return;
  const fit = locationMap.cameraForBounds(NYC_VIEW_BOUNDS, {padding: 0});
  const minimumZoom = Math.max(8.5, Math.min(11.4, (fit?.zoom ?? 9.6) - 0.15));
  locationMap.setMaxBounds(NYC_LIMIT_BOUNDS);
  locationMap.setMinZoom(minimumZoom);
}

function resetToNYC() {
  if (!locationMap) return;
  locationMap.resize();
  updateNycConstraints();
  const stage = document.querySelector("#mapStage");
  const padding = Math.max(12, Math.min(30, Math.round(Math.min(stage.clientWidth, stage.clientHeight) * .04)));
  locationMap.fitBounds(NYC_VIEW_BOUNDS, {padding, maxZoom: 11.5, duration: 300, bearing: 0, pitch: 0});
}


function fallbackToAerial(message) {
  if (!locationMap || activeBasemap !== "buildings3d") return;
  activeBasemap = "aerial";
  document.querySelector("#mapBasemapSelect").value = "aerial";
  syncRestaurantVisibility();
  locationMap.setStyle(mapStyle("aerial"));
  locationMap.easeTo({pitch: 0, bearing: 0, duration: 250});
  updateNycConstraints();
  setMapViewStatus(message, true);
}

const RESTAURANT_LAYERS = ["restaurant-clusters", "restaurant-cluster-count", "restaurant-points"];

function syncRestaurantVisibility() {
  const in3D = activeBasemap === "buildings3d";
  document.querySelector(".restaurant-toggle").hidden = !in3D;
  const legendEntry = document.querySelector(".legend-restaurant-entry");
  if (legendEntry) legendEntry.hidden = !in3D;
  if (!locationMap) return;
  const visible = in3D && showExistingRestaurants;
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
      .then(response => {if (!response.ok) throw new Error("Restaurant map data unavailable"); return response.json();})
      .catch(error => {restaurantDataPromise = null; throw error;});
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
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5, "circle-opacity": 0.9}});
    locationMap.addLayer({id: "restaurant-cluster-count", type: "symbol", source: "existing-restaurants", filter: ["has", "point_count"],
      layout: {"text-field": ["get", "point_count_abbreviated"], "text-font": ["Open Sans Regular"], "text-size": 11},
      paint: {"text-color": "#ffffff"}});
    locationMap.addLayer({id: "restaurant-points", type: "circle", source: "existing-restaurants", filter: ["!", ["has", "point_count"]],
      paint: {"circle-color": "#2487df", "circle-radius": 3.5, "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 0.8, "circle-opacity": 0.85}});
    syncRestaurantVisibility();
  } catch (error) {
    setMapViewStatus("Existing restaurant dots could not load.", true);
  }
}

function restaurantAtPoint(point) {
  if (activeBasemap !== "buildings3d" || !showExistingRestaurants || !locationMap?.getLayer("restaurant-points")) return null;
  return locationMap.queryRenderedFeatures(point, {layers: ["restaurant-points", "restaurant-clusters"]})[0] || null;
}

async function handleRestaurantClick(event) {
  const feature = restaurantAtPoint(event.point);
  if (!feature) return;
  if (feature.properties.cluster) {
    const source = locationMap.getSource("existing-restaurants");
    try {
      const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
      if (activeBasemap === "buildings3d" && showExistingRestaurants && source === locationMap.getSource("existing-restaurants")) {
        locationMap.easeTo({center: feature.geometry.coordinates, zoom, duration: 400});
      }
    } catch (_) {} // A background switch can remove the source while the zoom request is pending.
    return;
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
}

async function changeMapView(next) {
  const request = ++mapViewRequestId;
  if (!locationMap || !["streets", "aerial", "buildings3d"].includes(next)) return;
  if (next === activeBasemap) {setMapViewStatus(""); return;}
  let style;
  if (next === "buildings3d") {
    setMapViewStatus("Loading 3D street map…");
    try {
      style = await buildingMapStyle();
    } catch (_) {
      if (request !== mapViewRequestId) return;
      document.querySelector("#mapBasemapSelect").value = activeBasemap;
      setMapViewStatus("3D street map is unavailable. Aerial remains active.", true);
      return;
    }
  }
  if (request !== mapViewRequestId) return;
  try {
    activeBasemap = next;
    pinned3DFeature = false;
    hovered3DFeatureId = "";
    mapPopup?.remove();
    syncRestaurantVisibility();
    locationMap.setStyle(style || mapStyle(next));
    updateNycConstraints();
    if (next === "buildings3d") {
      setMapViewStatus("Loading 3D buildings…");
      locationMap.easeTo({pitch: 52, bearing: -18, duration: 450});
    } else {
      locationMap.easeTo({pitch: 0, bearing: 0, duration: 300});
      setMapViewStatus("");
    }
  } catch (_) {
    fallbackToAerial("3D building view could not load. Aerial remains active.");
  }
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
  if (!isHexLayer() || !locationMap?.getStyle()) return;
  clearHexLayer();
  const vector = data.tiles && data.source_layer;
  locationMap.addSource("concept-hexes", vector ? {type: "vector", tiles: data.tiles, minzoom: 0, maxzoom: 18} : {type: "geojson", data});
  const sourceLayer = vector ? {"source-layer": data.source_layer} : {};
  const labelLayer = activeBasemap === "streets" && locationMap.getLayer("street-labels") ? "street-labels" :
    activeBasemap === "buildings3d" ? locationMap.getStyle().layers.find(layer => layer.type === "symbol")?.id : undefined;
  locationMap.addLayer({id: "concept-hex-fill", type: "fill", source: "concept-hexes", ...sourceLayer, paint: {
    "fill-color": ["interpolate", ["linear"], ["get", "score"], 0, "#ad4648", 20, "#db7952", 40, "#e9ba6e", 60, "#a9c77b", 80, "#49ad8c", 100, "#087d82"],
    "fill-opacity": .57,
  }}, labelLayer);
  locationMap.addLayer({id: "concept-hex-outline", type: "line", source: "concept-hexes", ...sourceLayer, paint: {
    "line-color": "#f0f5ed", "line-opacity": .78, "line-width": ["interpolate", ["linear"], ["zoom"], 9, .5, 12, 1.1],
  }}, labelLayer);
}

function isHexLayer() {
  return ["concept_demand", "huff_demand"].includes(activeLayer);
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
  const key = `${activeLayer}:${dashboard.meta.data_release}:${params}`;
  const requestedLayer = activeLayer;
  const currentRequest = ++hexRequestId;
  if (hexCache.has(key)) {
    paintHexLayer(hexCache.get(key));
    return;
  }
  try {
    let data;
    const resolution = level === "fine" ? "9" : level === "cell" ? "8" : "7";
    const manifestResponse = await fetch(requestedLayer === "huff_demand" ? "/api/v1/spatial/huff" : `/api/v1/spatial/resolve?${params}`);
    if (manifestResponse.ok) {
      const manifest = await manifestResponse.json();
      if (manifest.tiles[resolution]) {
        data = {tiles: [new URL(manifest.tiles[resolution], window.location.origin).href.replace(/%7B/gi, "{").replace(/%7D/gi, "}")], source_layer: manifest.source_layer};
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
  if (!status) return;
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
    locationMap = new maplibregl.Map({container: "mapStage", style: mapStyle(activeBasemap), center: [-73.96, 40.73], zoom: 11, maxZoom: 19, maxBounds: NYC_LIMIT_BOUNDS, renderWorldCopies: false, attributionControl: false});
    locationMap.addControl(new maplibregl.NavigationControl({showCompass: true}), "top-left");
    locationMap.addControl(new maplibregl.AttributionControl({compact: true}), "bottom-right");
    const attribution = document.querySelector("#mapStage .maplibregl-ctrl-attrib");
    attribution.querySelector("summary").addEventListener("click", () => {
      attribution.dataset.userOpened = attribution.open ? "false" : "true";
    });
    collapseMapAttribution();
    locationMap.on("zoomend", () => {
      if (isHexLayer()) showHexLayer();
    });
    locationMap.on("load", () => {
      if (isHexLayer()) showHexLayer();
    });
    locationMap.on("idle", () => {
      installNycBoundary();
      if (activeBasemap === "buildings3d" && !locationMap.getSource("existing-restaurants")) installRestaurantLayers(++restaurantStyleRevision);
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
        mapPopup?.remove();
        return;
      }
      if (feature.properties.id === hoveredHexId) return;
      hoveredHexId = feature.properties.id;
      const {score, coverage, level, cell_count: count} = feature.properties;
      const detail = document.createElement("div");
      detail.className = "map-location-detail";
      if (activeLayer === "huff_demand") {
        const gap = Number(score);
        const demand = Number(feature.properties.unserved_demand);
        detail.innerHTML = `<strong>Huff Market Gap Scenario</strong><div><span>Outside Option Share</span><b>${Number.isFinite(gap) ? gap.toFixed(1) : "--"}%</b></div><div><span>Unserved Demand Units</span><b>${Number.isFinite(demand) ? Math.round(demand).toLocaleString("en-US") : "--"}</b></div><small>Scenario estimate; weights and capacity require calibration.</small>`;
      } else {
      detail.innerHTML = `<strong>${level === "sector" ? "Demand Sector" : "Local Demand Cell"}</strong><div><span>Concept Demand</span><b>${score}/100</b></div><div><span>Evidence Coverage</span><b>${coverage}%</b></div>${count ? `<small>${count} Local Cells</small>` : ""}`;
      }
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
      if (activeBasemap !== "buildings3d" || isHexLayer() || restaurantAtPoint(event.point)) return;
      const feature = featureAtPoint(event.point);
      if (feature) show3DFeature(feature, event.lngLat, true);
      else mapPopup?.remove();
    });
    updateNycConstraints();
    locationMap.on("resize", updateNycConstraints);
    locationMap.on("click", handleRestaurantClick);
    const expand = document.createElement("button");
    expand.id = "expandMapButton";
    expand.className = "map-expand-button";
    expand.type = "button";
    expand.textContent = "⛶";
    expand.title = "Expand Map";
    expand.setAttribute("aria-label", "Expand Map");
    expand.addEventListener("click", () => toggleExpandedMap());
    document.querySelector("#mapStage").append(expand);
    const reset = document.createElement("button");
    reset.id = "resetNycButton";
    reset.className = "map-reset-button";
    reset.type = "button";
    reset.textContent = "Reset to NYC";
    reset.addEventListener("click", resetToNYC);
    document.querySelector("#mapStage").append(reset);
    const viewStatus = document.createElement("div");
    viewStatus.id = "mapViewStatus";
    viewStatus.className = "map-view-status";
    viewStatus.setAttribute("role", "status");
    viewStatus.hidden = true;
    document.querySelector("#mapStage").append(viewStatus);
    const legend = document.createElement("div");
    legend.className = "map-legend";
    legend.innerHTML = '<div><b class="legend-recommendation-dot"></b><span>Recommended area</span><span>0</span><i></i><span>100</span></div><div class="legend-restaurant-entry" hidden><b class="legend-restaurant-dot"></b><span>Existing restaurant</span></div>';
    document.querySelector("#mapStage").append(legend);
  }
  mapPopup?.remove();
  pinned3DFeature = false;
  mapMarkers.forEach(marker => marker.remove());
  mapMarkers = [];
  if (isHexLayer()) showHexLayer();
  else clearHexLayer();
  const locations = allLocations().filter(row => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
  if (!isHexLayer()) locations.forEach((location) => {
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
    element.addEventListener("click", event => {
      event.stopPropagation();
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
        <span>${cuisineOpportunityDisplay(row)}</span>
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

const PROFILE_INDUSTRIES = [
  ["jobs_agriculture_forestry_fishing_hunting", "Agriculture, Forestry & Fishing"],
  ["jobs_mining_quarrying_oil_gas", "Mining, Quarrying & Oil and Gas"],
  ["jobs_utilities", "Utilities"], ["jobs_construction", "Construction"],
  ["jobs_manufacturing", "Manufacturing"], ["jobs_wholesale_trade", "Wholesale Trade"],
  ["jobs_retail_trade", "Retail Trade"], ["jobs_transportation_warehousing", "Transportation & Warehousing"],
  ["jobs_information", "Information"], ["jobs_finance_insurance", "Finance & Insurance"],
  ["jobs_real_estate_rental_leasing", "Real Estate & Leasing"],
  ["jobs_professional_scientific_technical", "Professional, Scientific & Technical"],
  ["jobs_management", "Management"], ["jobs_admin_support_waste_management", "Administrative Support & Waste Management"],
  ["jobs_educational_services", "Education"], ["jobs_health_care_social_assistance", "Health Care & Social Assistance"],
  ["jobs_arts_entertainment_recreation", "Arts, Entertainment & Recreation"],
  ["jobs_accommodation_food_services", "Accommodation & Food Services"],
  ["jobs_other_services", "Other Services"], ["jobs_public_administration", "Public Administration"],
];

function profileAreas() {
  if (!profileAreasPromise) {
    profileAreasPromise = fetch("/api/areas")
      .then(response => {if (!response.ok) throw new Error("Area list unavailable"); return response.json();})
      .then(result => {profileAreasResolved = result.areas; return result.areas;})
      .catch(error => {profileAreasPromise = null; throw error;});
  }
  return profileAreasPromise;
}

function areaProfile(geoid) {
  if (!profileCache.has(geoid)) {
    const request = fetch(`/api/areas/${encodeURIComponent(geoid)}/profile`)
      .then(response => {if (!response.ok) throw new Error("Area profile unavailable"); return response.json();})
      .then(result => {profileResolved.set(geoid, result); return result;})
      .catch(error => {profileCache.delete(geoid); throw error;});
    profileCache.set(geoid, request);
  }
  return profileCache.get(geoid);
}

function profileNumber(value, currency = false) {
  if (value === null || value === undefined) return "Unavailable";
  return currency ? fmtDollar(value) : Number(value).toLocaleString("en-US");
}

function profileMetric(title, source, first, second, currency = false, income = false) {
  const value = profile => profileNumber(profile?.market_profile?.[first], currency);
  const margin = profile => income && profile?.market_profile?.[first] != null
    ? `<small>${profile.market_profile.income_margin_of_error == null ? "Margin of error unavailable" : `±${fmtDollar(profile.market_profile.income_margin_of_error)} margin of error`}</small>` : "";
  return `<article class="rw-metric"><h4>${title}</h4><p>${source}</p>
    <div class="rw-metric-value"><span>${escapeHtml(first === "jobs" ? "Selected workplace" : "Selected area")}</span><strong>${value(second[0])}</strong>${margin(second[0])}</div>
    ${second[1] ? `<div class="rw-metric-value"><span>Comparison area</span><strong>${value(second[1])}</strong>${margin(second[1])}</div>` : ""}
  </article>`;
}

function profileBreakdown(title, source, group, fields, first, second, open = true) {
  const read = (profile, key) => profileNumber(profile?.market_profile?.[group]?.[key]);
  return `<details class="rw-breakdown" data-profile-group="${group}" ${profileExpanded[group] ?? open ? "open" : ""}><summary>${title}<small>${source}</small></summary>
    <div class="rw-table-scroll"><table><thead><tr><th scope="col">Measure</th><th scope="col">Selected area</th>${second ? "<th scope=\"col\">Comparison area</th>" : ""}</tr></thead>
    <tbody>${fields.map(([key, label]) => `<tr><th scope="row">${label}</th><td data-label="Selected area">${read(first, key)}</td>${second ? `<td data-label="Comparison area">${read(second, key)}</td>` : ""}</tr>`).join("")}</tbody></table></div>
  </details>`;
}

function cuisineOpportunityDisplay(location) {
  const component = location.score_components.find(item => item.key === "market_gap");
  return component?.coverage > 0 ? component.score : "Unavailable";
}

function cuisineOpportunityExplanation(location) {
  if (!location.concept_evidence?.cuisine || location.concept_evidence.cuisine === "any") {
    return "Choose a cuisine in Edit Brief to assess opportunity.";
  }
  if (location.concept_evidence.positioning === "Cuisine Not Separately Classified") {
    return "This cuisine is not separately classified in restaurant records.";
  }
  return "Supporting cuisine evidence is unavailable for this tract.";
}

async function renderResidentWorkerProfile() {
  const target = document.querySelector("#residentWorkerProfile");
  if (!target || !dashboard || activeView !== "scorecard") return;
  const geoid = selectedLocation().id;
  if (profileComparisonId === geoid) profileComparisonId = "";
  const comparison = profileComparisonId;
  const renderId = ++profileRenderId;
  if (!(profileAreasResolved && profileResolved.has(geoid) && (!comparison || profileResolved.has(comparison))))
    target.innerHTML = '<div class="rw-loading" role="status">Loading resident and worker records…</div>';
  try {
    const [areas, first, second] = await Promise.all([
      profileAreas(), areaProfile(geoid), comparison ? areaProfile(comparison) : Promise.resolve(null),
    ]);
    if (renderId !== profileRenderId || activeView !== "scorecard" || selectedLocation().id !== geoid) return;
    const options = [...areas].sort((a, b) => a.borough.localeCompare(b.borough) || a.name.localeCompare(b.name));
    target.innerHTML = `<div class="rw-heading"><div><h3>Resident and Worker Profile</h3><p>Recorded residents and workplace jobs are separate measures, not customer or revenue predictions.</p></div>
      <label for="rwCompareArea">Compare with another tract<select id="rwCompareArea"><option value="">Select a second area</option>
        ${options.filter(row => row.geoid !== geoid).map(row => `<option value="${row.geoid}" ${row.geoid === comparison ? "selected" : ""}>${escapeHtml(row.borough)} · ${escapeHtml(row.name)}</option>`).join("")}
      </select></label></div>
      <div class="rw-area-names"><div><span>Selected area</span><strong>${escapeHtml(first.name)}</strong><small>${escapeHtml(first.borough)} · 2020 census tract</small></div>
      ${second ? `<div><span>Comparison area</span><strong>${escapeHtml(second.name)}</strong><small>${escapeHtml(second.borough)} · 2020 census tract</small></div>` : ""}</div>
      <div class="rw-metrics">
        ${profileMetric("Resident population", "ACS 2024 five-year estimate", "population", [first, second])}
        ${profileMetric("Median household income", "ACS 2024 five-year estimate", "median_household_income", [first, second], true, true)}
        ${profileMetric("Workplace jobs", "LODES 2023", "jobs", [first, second])}
      </div>
      <div class="rw-breakdowns">
        ${profileBreakdown("Resident age groups", "ACS 2024 five-year estimates · groups shown are not exhaustive", "resident_age", [["population_under_18_2024", "Under 18"], ["population_65_plus_2024", "65 and over"]], first, second)}
        ${profileBreakdown("Workplace jobs by worker age", "LODES 2023 · jobs located in the tract", "job_age", [["jobs_age_29_or_younger", "29 or younger"], ["jobs_age_30_to_54", "30 to 54"], ["jobs_age_55_or_older", "55 or older"]], first, second)}
        ${profileBreakdown("Workplace jobs by monthly earnings", "LODES 2023 · jobs located in the tract", "job_earnings", [["jobs_earn_1250_or_less_monthly", "$1,250 or less"], ["jobs_earn_1251_to_3333_monthly", "$1,251–$3,333"], ["jobs_earn_more_than_3333_monthly", "More than $3,333"]], first, second)}
        ${profileBreakdown("Workplace jobs by industry", "LODES 2023 · jobs located in the tract", "job_industry", PROFILE_INDUSTRIES, first, second, false)}
      </div>`;
    target.querySelector("#rwCompareArea").addEventListener("change", event => {
      profileComparisonId = event.target.value;
      persistDashboardView();
      renderResidentWorkerProfile();
      renderCompetitionExplorer();
    });
    target.querySelectorAll("[data-profile-group]").forEach(details => details.addEventListener("toggle", () => {
      profileExpanded[details.dataset.profileGroup] = details.open;
      persistDashboardView();
    }));
  } catch (error) {
    if (renderId !== profileRenderId || !target.isConnected) return;
    target.innerHTML = '<div class="rw-error" role="alert">Resident and worker records could not load. <button class="quiet-action" type="button">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderResidentWorkerProfile);
  }
}

function transitValue(value, unit = "") {
  return value == null ? "Unavailable" : `${Number(value).toLocaleString("en-US", {maximumFractionDigits: unit === "mi" ? 2 : 0})}${unit ? ` ${unit}` : ""}`;
}

function transitRow(label, value, unit = "") {
  return `<div class="transit-row"><span>${escapeHtml(label)}</span><strong>${transitValue(value, unit)}</strong></div>`;
}

function paintTransitActivity(target, data) {
  const subway = data.subway, bike = data.bike, pedestrian = data.pedestrian, taxi = data.taxi;
  const card = (key, title, lead, source, period, coverage, rows) => `
    <details class="transit-card" data-transit-group="${key}" ${transitExpanded[key] ? "open" : ""}>
      <summary><span>${title}</span><strong>${lead}</strong></summary>
      <div class="transit-card-body"><p>${escapeHtml(source)} · ${escapeHtml(period || "Observation date unavailable")}</p>
      <p>${escapeHtml(coverage)}</p><div class="transit-rows">${rows}</div></div>
    </details>`;
  target.innerHTML = `<div class="transit-heading"><h3>Transit and Activity Profile</h3>
    <p>Recorded trips and monitored observations are separate measures, not unique visitors or customer forecasts.</p></div>
    <div class="transit-grid">
      ${card("subway", "Subway access and activity", `${transitValue(subway.nearest_distance_miles, "mi")} to nearest complex`, subway.source,
        subway.period, "Stations in the tract and the nearest station to the tract centroid; one complete week.",
        `${transitRow("Station complexes in tract", subway.station_count)}${transitRow("Entries at tract stations", subway.weekly_entries, "entries/week")}
         ${transitRow("Transfers at tract stations", subway.weekly_transfers, "transfers/week")}
         <div class="transit-row"><span>Nearest complex</span><strong>${escapeHtml(subway.nearest_name || "Unavailable")}</strong></div>
         ${transitRow("Nearest complex entries", subway.nearest_weekly_entries, "entries/week")}
         ${subway.nearest_dayparts ? Object.entries(subway.nearest_dayparts).map(([period, value]) => transitRow(`Weekday ${period} · sampled 2025 weeks`, value, "entries/day")).join("") : ""}
         ${subway.stations.length ? `<div class="transit-stations">${subway.stations.map(station => `<div>${escapeHtml(station.name)} <strong>${transitValue(station.weekly_entries)} entries/week</strong></div>`).join("")}</div>` : ""}`)}
      ${card("bike", "Citi Bike activity", `${transitValue(bike.departures, "departures")}`, bike.source,
        bike.period, "Trips begin or end at stations inside the tract; coverage depends on Citi Bike service.",
        `${transitRow("Stations in tract", bike.station_count)}${transitRow("Arrivals", bike.arrivals, "arrivals")}
         ${transitRow("Evening departures", bike.evening_departures, "departures")}${transitRow("Weekend departures", bike.weekend_departures, "departures")}
         <div class="transit-row"><span>Nearest station</span><strong>${escapeHtml(bike.nearest_name || "Unavailable")}</strong></div>
         ${transitRow("Nearest station distance", bike.nearest_distance_miles, "mi")}
         ${transitRow("Nearest station departures", bike.nearest_departures, "departures")}`)}
      ${card("pedestrian", "DOT pedestrian observation", `${transitValue(pedestrian.observed_total, "pedestrians")}`, pedestrian.source,
        pedestrian.period, "Nearest monitored site to the tract centroid; DOT observes selected sites, not every street.",
        `<div class="transit-row"><span>Nearest monitor</span><strong>${escapeHtml(pedestrian.monitor_name || "Unavailable")}</strong></div>
         ${transitRow("Monitor distance", pedestrian.distance_miles, "mi")}
         ${["AM", "MD", "PM"].map(period => transitRow(`${period} observation`, pedestrian.period_counts?.[period], "pedestrians")).join("")}`)}
      ${card("taxi", "Taxi-zone activity", `${transitValue(taxi.pickups, "pickups")}`, taxi.source,
        taxi.period, "HVFHV trips in the taxi zone containing the tract centroid; not a direct tract measurement.",
        `<div class="transit-row"><span>Assigned taxi zone</span><strong>${escapeHtml(taxi.zone || "Unavailable")}${taxi.zone_borough ? ` · ${escapeHtml(taxi.zone_borough)}` : ""}</strong></div>
         ${transitRow("Drop-offs", taxi.dropoffs, "drop-offs")}${transitRow("Active source days", taxi.active_days, "days")}`)}
    </div>`;
  target.querySelectorAll("[data-transit-group]").forEach(details => details.addEventListener("toggle", () => {
    transitExpanded[details.dataset.transitGroup] = details.open;
    persistDashboardView();
  }));
}

async function renderTransitActivity() {
  const target = document.querySelector("#transitActivityProfile");
  if (!target || !dashboard || activeView !== "scorecard") return;
  const geoid = selectedLocation().id;
  const renderId = ++transitRenderId;
  if (!transitCache.has(geoid)) target.innerHTML = '<div class="transit-loading" role="status">Loading transit and activity records…</div>';
  try {
    if (!transitCache.has(geoid)) {
      const request = fetch(`/api/areas/${encodeURIComponent(geoid)}/transit-activity`)
        .then(response => {if (!response.ok) throw new Error("Transit records unavailable"); return response.json();})
        .catch(error => {transitCache.delete(geoid); throw error;});
      transitCache.set(geoid, request);
    }
    const data = await transitCache.get(geoid);
    if (renderId !== transitRenderId || !target.isConnected || activeView !== "scorecard" || selectedLocation().id !== geoid) return;
    paintTransitActivity(target, data);
  } catch (_) {
    if (renderId !== transitRenderId || !target.isConnected || activeView !== "scorecard") return;
    target.innerHTML = '<div class="transit-error" role="alert">Transit and activity records could not load. <button type="button">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderTransitActivity);
  }
}

function competitionShare(count, total) {
  return total ? `${(count / total * 100).toFixed(1)}%` : "Unavailable";
}

function competitionSummary(market, comparison) {
  const card = (data, label) => `<div class="competition-area-card">
    <span>${label} · ${escapeHtml(data.borough)}</span><h4>${escapeHtml(data.tract_name)}</h4>
    <div><strong>${data.tract_restaurant_count.toLocaleString("en-US")}</strong><small>Recorded establishments</small></div>
    ${data.cuisine_supported ? `<p>My Cuisine: <strong>${data.same_cuisine_count.toLocaleString("en-US")}</strong>
      <span>${data.tract_restaurant_count ? `${competitionShare(data.same_cuisine_count, data.tract_restaurant_count)} of all recorded establishments` : "Share unavailable (zero establishments)"}</span></p>` : ""}
  </div>`;
  if (!comparison) return `<div class="competition-area-cards">${card(market, "Selected area")}</div>`;
  const firstCounts = new Map(market.cuisine_counts.map(item => [item.cuisine, item.count]));
  const secondCounts = new Map(comparison.cuisine_counts.map(item => [item.cuisine, item.count]));
  const cuisines = [...new Set([...firstCounts.keys(), ...secondCounts.keys()])]
    .sort((a, b) => ((firstCounts.get(b) || 0) + (secondCounts.get(b) || 0)) -
      ((firstCounts.get(a) || 0) + (secondCounts.get(a) || 0)) || a.localeCompare(b));
  const cell = (count, total) => `<strong>${count.toLocaleString("en-US")}</strong><small>${competitionShare(count, total)}</small>`;
  return `<div class="competition-area-cards">${card(market, "Selected area")}${card(comparison, "Comparison area")}</div>
    <details class="competition-comparison" ${competitionComparisonOpen ? "open" : ""}><summary>Cuisine comparison <span>${cuisines.length} classifications</span></summary>
      <p>Shares use each tract's full active, CAMIS-deduplicated establishment total before list filters or search.</p>
      <div class="competition-comparison-scroll"><table><thead><tr><th scope="col">Cuisine</th>
        <th scope="col">${escapeHtml(market.tract_name)}</th><th scope="col">${escapeHtml(comparison.tract_name)}</th></tr></thead>
        <tbody>${cuisines.length ? cuisines.map(label => `<tr><th scope="row">${escapeHtml(label)}</th>
          <td>${cell(firstCounts.get(label) || 0, market.tract_restaurant_count)}</td>
          <td>${cell(secondCounts.get(label) || 0, comparison.tract_restaurant_count)}</td></tr>`).join("") :
          '<tr><td colspan="3">No recorded establishments in either tract.</td></tr>'}</tbody></table></div>
    </details><p class="competition-caution">Fewer recorded competitors alone does not indicate a better location.</p>`;
}

function drawCompetitionRows(target, market) {
  const rows = market.restaurants.filter(row =>
    (competitionFilter === "all" || (competitionFilter === "mine" ? row.same_cuisine :
      row.cuisine === competitionFilter.slice("cuisine:".length))) &&
    `${row.name} ${row.cuisine} ${row.address}`.toLowerCase().includes(competitionQuery.toLowerCase().trim()));
  const shown = rows.slice(0, competitionVisible);
  target.querySelector("#competitionResultCount").textContent = `Showing ${shown.length} of ${rows.length} matching restaurants`;
  target.querySelector("#competitionRows").innerHTML = shown.length ? shown.map(row => `
    <div class="competition-row" role="row">
      <strong role="cell">${escapeHtml(row.name)}</strong>
      <span role="cell">${escapeHtml(row.cuisine)}</span>
      <span role="cell">${escapeHtml(row.address || "Address unavailable")}</span>
    </div>`).join("") : `<div class="competition-empty">${market.tract_restaurant_count === 0
      ? "No recorded establishments in this tract." : "No restaurants match this filter or search."}</div>`;
  const more = target.querySelector("#competitionMore");
  more.hidden = shown.length >= rows.length;
  target.querySelectorAll("[data-competition-filter]").forEach(button =>
    button.setAttribute("aria-pressed", String(button.dataset.competitionFilter === competitionFilter)));
  target.querySelectorAll("[data-competition-cuisine]").forEach(button =>
    button.setAttribute("aria-pressed", String(competitionFilter === `cuisine:${button.dataset.competitionCuisine}`)));
  const selectedCuisine = competitionFilter.startsWith("cuisine:") ? competitionFilter.slice("cuisine:".length) : "";
  target.querySelector("#competitionActiveFilter").textContent = selectedCuisine ? `Filtering list: ${selectedCuisine}` :
    competitionFilter === "mine" ? "Filtering list: My Cuisine" : "Filtering list: All Cuisines";
  target.querySelector("#competitionClearFilter").hidden = !selectedCuisine;
  persistDashboardView();
}

function paintCompetitionExplorer(target, market, comparison) {
  const topCount = market.cuisine_counts[0]?.count || 1;
  const supportNote = market.cuisine_supported ? "" : `
    <p class="competition-support-note">My Cuisine is unavailable because ${dashboard.meta.concept.cuisine === "any"
      ? "the brief has no selected cuisine" : "this cuisine is not separately classified in DOHMH records"}.
      <button type="button" id="competitionEditBrief">Choose a cuisine in Edit Brief</button>.</p>`;
  target.innerHTML = `
    <div class="competition-heading">
      <div><h3>Competition Explorer</h3><p>Recorded establishments, not a guaranteed live inventory.</p></div>
    </div>
    <p class="competition-source">${escapeHtml(market.source)} · Latest inspection in file: ${escapeHtml(market.latest_inspection_date || "Date unavailable")} · Extract date unavailable</p>
    ${competitionSummary(market, comparison)}
    ${supportNote}
    <div class="competition-content">
      <details class="competition-breakdown" ${competitionBreakdownOpen ? "open" : ""}><summary>Cuisine breakdown <span>${market.cuisine_counts.length} classifications</span></summary>
        <div class="competition-bars">${market.cuisine_counts.length ? market.cuisine_counts.map(item => `
          <button type="button" class="competition-bar" data-competition-cuisine="${escapeHtml(item.cuisine)}" aria-pressed="false"
            aria-label="Filter selected-area restaurants to ${escapeHtml(item.cuisine)}: ${item.count} recorded, ${competitionShare(item.count, market.tract_restaurant_count)} of all recorded establishments">
            <span class="competition-bar-label"><span>${escapeHtml(item.cuisine)}</span><strong>${item.count.toLocaleString("en-US")} · ${competitionShare(item.count, market.tract_restaurant_count)}</strong></span>
            <span class="competition-bar-track"><span style="width:${Math.max(2, item.count / topCount * 100)}%"></span></span></button>`).join("") :
          '<p class="competition-empty">No recorded establishments in this tract.</p>'}</div>
      </details>
      <div class="competition-list">
        <div class="competition-tools"><div class="competition-filter" role="group" aria-label="Restaurant cuisine filter">
          <button type="button" data-competition-filter="all">All Cuisines</button>
          <button type="button" data-competition-filter="mine" ${market.cuisine_supported ? "" : "disabled"}>My Cuisine${market.cuisine_supported ? ` (${market.same_cuisine_count})` : ""}</button>
        </div><label>Search restaurants<input id="competitionSearch" type="search" placeholder="Name, cuisine, or address" value="${escapeHtml(competitionQuery)}" /></label></div>
        <div class="competition-filter-state"><span id="competitionActiveFilter"></span><button type="button" id="competitionClearFilter" hidden>Clear cuisine filter</button></div>
        <div class="competition-results" id="competitionResultCount" role="status"></div>
        <div class="competition-table" role="table" aria-label="Recorded restaurants"><div class="competition-row competition-row-head" role="row"><strong role="columnheader">Restaurant</strong><strong role="columnheader">Cuisine</strong><strong role="columnheader">Address</strong></div><div id="competitionRows"></div></div>
        <button class="competition-more" id="competitionMore" type="button">Show More</button>
      </div>
    </div>`;
  target.querySelector("#competitionEditBrief")?.addEventListener("click", openBrief);
  target.querySelector(".competition-breakdown").addEventListener("toggle", event => {competitionBreakdownOpen = event.target.open; persistDashboardView();});
  target.querySelector(".competition-comparison")?.addEventListener("toggle", event => {competitionComparisonOpen = event.target.open; persistDashboardView();});
  target.querySelectorAll("[data-competition-filter]").forEach(button => button.addEventListener("click", () => {
    competitionFilter = button.dataset.competitionFilter;
    competitionVisible = 10;
    drawCompetitionRows(target, market);
  }));
  target.querySelectorAll("[data-competition-cuisine]").forEach(button => button.addEventListener("click", () => {
    const filter = `cuisine:${button.dataset.competitionCuisine}`;
    competitionFilter = competitionFilter === filter ? "all" : filter;
    competitionVisible = 10;
    drawCompetitionRows(target, market);
  }));
  target.querySelector("#competitionClearFilter").addEventListener("click", () => {
    competitionFilter = "all";
    competitionVisible = 10;
    drawCompetitionRows(target, market);
  });
  target.querySelector("#competitionSearch").addEventListener("input", event => {
    competitionQuery = event.target.value;
    competitionVisible = 10;
    drawCompetitionRows(target, market);
  });
  target.querySelector("#competitionMore").addEventListener("click", () => {
    competitionVisible += 10;
    drawCompetitionRows(target, market);
  });
  drawCompetitionRows(target, market);
}

function loadCompetitionData(id, cuisine) {
  const key = `${id}:${cuisine}`;
  if (!competitionCache.has(key)) {
    const generation = requestId;
    const request = fetch(`/api/locations/${encodeURIComponent(id)}/competition?cuisine=${encodeURIComponent(cuisine)}`)
      .then(response => {if (!response.ok) throw new Error("Restaurant records unavailable"); return response.json();})
      .then(result => {if (generation === requestId) competitionResolved.set(key, result); return result;})
      .catch(error => {if (generation === requestId) competitionCache.delete(key); throw error;});
    competitionCache.set(key, request);
  }
  return competitionCache.get(key);
}

async function renderCompetitionExplorer() {
  const target = document.querySelector("#competitionExplorer");
  if (!target || !dashboard || activeView !== "scorecard") return;
  const geoid = selectedLocation().id;
  const cuisine = dashboard.meta.concept.cuisine;
  if (profileComparisonId === geoid) profileComparisonId = "";
  const comparisonId = profileComparisonId;
  const key = `${geoid}:${cuisine}`;
  if (competitionContext !== key) {
    competitionContext = key;
    competitionFilter = "all";
    competitionQuery = "";
    competitionVisible = 10;
  }
  const renderId = ++competitionRenderId;
  if (!(competitionResolved.has(key) && (!comparisonId || competitionResolved.has(`${comparisonId}:${cuisine}`))))
    target.innerHTML = '<div class="competition-loading" role="status">Loading recorded restaurants…</div>';
  try {
    const [market, comparison] = await Promise.all([
      loadCompetitionData(geoid, cuisine), comparisonId ? loadCompetitionData(comparisonId, cuisine) : Promise.resolve(null),
    ]);
    if (renderId !== competitionRenderId || !target.isConnected || selectedLocation().id !== geoid ||
        profileComparisonId !== comparisonId || activeView !== "scorecard") return;
    paintCompetitionExplorer(target, market, comparison);
  } catch (error) {
    if (renderId !== competitionRenderId || !target.isConnected || activeView !== "scorecard") return;
    target.innerHTML = '<div class="competition-error" role="alert">Restaurant records could not load. <button type="button" class="competition-more">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderCompetitionExplorer);
  }
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
  const evidence = location.concept_evidence;
  const count = value => value === null ? "Unavailable" : Number(value).toLocaleString("en-US");
  const survival = location.survival;
  const survivalValue = survival?.status === "available" ? `${(100 * survival.probability).toFixed(1)}%` : "Unavailable";
  const survivalBasis = survival?.status === "available"
    ? `Experimental three-year estimate · ${Math.round(100 * survival.feature_coverage)}% feature coverage · ${escapeHtml(survival.model_version)}. Screening ranking is separate.`
    : `${escapeHtml(dashboard.survival_model?.label || "Survival model unavailable")}. Screening scores are not survival predictions.`;
  const risks = location.risk_flags.map((risk) => `<li>${titleCase(risk)}</li>`).join("");
  const components = location.score_components.map((component) => {
    const noCuisineEvidence = component.key === "market_gap" && component.coverage === 0;
    return `
    <article class="score-component">
      <div class="score-component__top">
        <div>
          <h3>${component.label}</h3>
        </div>
        <strong class="${noCuisineEvidence ? "score-component-unavailable" : scoreClass(component.score)}">${noCuisineEvidence ? "Unavailable" : component.score}</strong>
      </div>
      ${noCuisineEvidence ? `<p class="score-component-note">${cuisineOpportunityExplanation(location)}</p>` : ""}
      <div class="component-bars">
        ${noCuisineEvidence ? "" : `<div>
          <span>Score</span>
          <div class="bar-track"><div class="bar-fill" style="width:${component.score}%;background:${colorFor(component.score, "opportunity")}"></div></div>
        </div>`}
        <div>
          <span>Evidence Strength ${component.coverage}%</span>
          <div class="bar-track evidence"><div class="bar-fill" style="width:${component.coverage}%;background:var(--cyan)"></div></div>
        </div>
      </div>
    </article>
  `;
  }).join("");

  document.querySelector("#scorecardBoard").innerHTML = `
    <section class="scorecard-hero">
      <div>
        <span class="card-status">Screening Estimate</span>
        <h3>${escapeHtml(conceptName())} · ${location.name}</h3>
        <p>${location.recommendation}</p>
      </div>
      <div class="scorecard-orbs">
        <div><strong>${location.opportunity}</strong><span>Score</span></div>
        <div><strong>${location.confidence_score}%</strong><span>Evidence Strength</span></div>
      </div>
    </section>
    <section class="concept-evidence">
      <div class="concept-evidence-heading"><h3>${escapeHtml(evidence.positioning)}</h3><span>${escapeHtml(cuisineLabel())} · $${state.averageCheck} Per Guest</span></div>
      <div class="evidence-grid">
        <div><span>Walkability</span><strong>${location.walkability ?? "--"}/100</strong></div>
        <div><span>Business Draw</span><strong>${location.business_draw}/100</strong></div>
        <div><span>Same Cuisine In Tract</span><strong>${count(evidence.same_cuisine_count)}</strong></div>
        <div><span>Same Cuisine In Neighborhood</span><strong>${count(evidence.neighborhood_same_cuisine_count)}</strong></div>
      </div>
    </section>
    <section class="rw-profile" id="residentWorkerProfile" aria-label="Resident and worker profile"></section>
    <section class="transit-profile" id="transitActivityProfile" aria-label="Transit and activity profile"></section>
    <section class="competition-explorer" id="competitionExplorer" aria-label="Competition explorer"></section>
    <div class="market-group"><h3>Commercial Context</h3><div class="market-measures">
      ${measure("Estimated Three-Year Survival", survivalValue, survivalBasis)}
      ${measure("Recorded Restaurants", displayNumber(profile.active_restaurants), "DOHMH tract records")}
      ${measure("Reported Vacant Storefronts", displayNumber(profile.reported_vacant_storefronts), "Registry filings; availability unverified")}

    </div></div>
    <div class="catchment-result" id="catchmentResult"><button class="primary-action" type="button" id="analyzeCatchment">Analyze 10-Minute Walk</button><span>From Tract Centroid</span></div>
    <section class="scorecard-layout">
      <div class="component-grid">${components}</div>
      <aside class="risk-panel">
        <h3>Decision Notes</h3>
        <ul>${risks}</ul>
        <div class="kv"><span>Concept Fit</span><strong>${titleCase(location.archetype)}</strong></div>
        <div class="kv"><span>Asking Rent</span><strong>${rentDisplay(location)}</strong></div>
        <div class="kv"><span>Budget Target</span><strong>${fmtMoney(dashboard.finance.rent_target)}/Month</strong></div>
      </aside>
    </section>
  `;
  if (activeView === "scorecard") {
    renderResidentWorkerProfile();
    renderTransitActivity();
    renderCompetitionExplorer();
  }
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

function renderFeeds() {
  document.querySelector("#feedList").innerHTML = dashboard.feeds.map((feed) => `
    <article class="feed-row">
      <div class="feed-row__top">
        <span>${escapeHtml(feed.name)}</span>
        <span>${escapeHtml(feed.vintage)}</span>
      </div>
      <div class="feed-row__meta">
        <span>${escapeHtml(feed.grain)}</span>
        <span>${escapeHtml(feed.coverage)}</span>
      </div>
    </article>
  `).join("");
}

function renderShortlist() {
  const candidates = dashboard.locations.slice(0, 6);
  document.querySelector("#shortlistBoard").innerHTML = candidates.map((row, index) => `
    <article class="shortlist-card" data-id="${row.id}">
      <span class="card-status">Rank ${index + 1}</span>
      <h3>${row.name}</h3>
      <div class="score-line">
        <strong class="${scoreClass(row.opportunity)}">${row.opportunity}</strong>
        <span>${row.borough} - ${titleCase(row.archetype)}</span>
      </div>
      <div class="kv"><span>Best Use</span><strong>${titleCase(row.archetype)}</strong></div>
      <div class="kv"><span>Asking Rent</span><strong>${rentDisplay(row)}</strong></div>
      <div class="kv"><span>Business Draw</span><strong>${row.business_draw}/100</strong></div>
    </article>
  `).join("");

  document.querySelectorAll(".shortlist-card[data-id]").forEach((card) => {
    card.addEventListener("click", () => {
      selectedId = card.dataset.id;
      activeView = "discover";
      document.querySelectorAll(".feature-tab").forEach((item) => item.classList.toggle("is-active", item.dataset.view === "discover"));
      renderAll();
    });
  });
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
  let candidates = (dashboard.properties || []).filter(row => row.lead_type === "listing");
  document.querySelector("#propertyHeading").textContent = "Properties";
  syncPropertyTabs();
  if (state.preferredArea) {
    candidates = candidates.filter((row) => row.borough === state.preferredArea);
  }
  if (!candidates.length) {
    const sourceConnected = dashboard.listing_source_connected === true;
    const type = state.dealType === "purchase" ? "purchase" : state.dealType === "either" ? "lease or purchase" : "lease";
    document.querySelector("#leaseBoard").innerHTML = `
      <article class="property-listings-empty">
        <span class="property-empty-icon" aria-hidden="true">⌕</span>
        <div><h3>${sourceConnected ? `No matching ${type} listings` : "No listing source connected"}</h3>
        <p>${sourceConnected ? `The connected listing source has no verified ${type} records matching this search.` : "Verified lease and purchase listings are not connected in this preview."}</p></div>
      </article>
    `;
    return;
  }

  document.querySelector("#leaseBoard").innerHTML = `<div class="property-results-meta">${candidates.length} source-linked ${state.dealType === "purchase" ? "purchase" : state.dealType === "either" ? "lease or purchase" : "lease"} listing${candidates.length === 1 ? "" : "s"}</div>` + candidates.map((row) => {
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
}


function storefrontMatches(row) {
  const areaMatches = storefrontArea === "all" || (storefrontArea === "selected" ? row.geoid === selectedLocation().id : row.borough === storefrontArea);
  const vacancyMatches = storefrontVacancy === "all" ||
    (storefrontVacancy === "dec31" ? row.vacant_on_dec_31 :
      storefrontVacancy === "jun30" ? row.vacant_on_jun_30_or_sale : row.vacancy_status === storefrontVacancy);
  const needle = storefrontQuery.toLowerCase().trim();
  return areaMatches && vacancyMatches && (!needle || `${row.address || ""} ${row.reported_activity || ""}`.toLowerCase().includes(needle));
}

function drawStorefrontRows(target) {
  const rows = storefrontData.records.filter(storefrontMatches);
  const shown = rows.slice(0, storefrontVisible);
  target.querySelector("#storefrontCount").textContent = `${rows.length.toLocaleString("en-US")} matching records · Showing ${shown.length.toLocaleString("en-US")} of ${storefrontData.total.toLocaleString("en-US")} in source`;
  target.querySelector("#storefrontRows").innerHTML = shown.length ? shown.map(row => `
    <article class="storefront-record">
      <div class="storefront-field"><span class="storefront-mobile-label">Address</span><strong>${escapeHtml(row.address || "Unavailable")}</strong></div>
      <div class="storefront-field"><span class="storefront-mobile-label">Reported Status</span><span class="storefront-status ${row.vacancy_status === "reported_vacant" ? "is-reported" : "is-unknown"}">${row.vacancy_status === "reported_vacant" ? "Reported vacant" : "Unknown"}</span></div>
      <div class="storefront-field"><span class="storefront-mobile-label">Reported Activity</span><span>${escapeHtml(row.reported_activity || "Unavailable")}</span></div>
      <details class="storefront-details"><summary>View details</summary><dl>
        <div><dt>BBL</dt><dd>${escapeHtml(row.id || "Unavailable")}</dd></div>
        <div><dt>Borough / ZIP</dt><dd>${escapeHtml([row.borough, row.zip_code].filter(Boolean).join(" · ") || "Unavailable")}</dd></div>
        <div><dt>Unit</dt><dd>${escapeHtml(row.unit || "Unavailable")}</dd></div>
        <div><dt>Reporting year</dt><dd>${escapeHtml(row.reporting_year || "Unavailable")}</dd></div>
        <div><dt>Filing due date</dt><dd>${escapeHtml(row.filing_due_date || "Unavailable")}</dd></div>
        <div><dt>Vacant on Dec 31</dt><dd>${row.vacant_on_dec_31 ? "Marked yes" : "Not marked"}</dd></div>
        <div><dt>Vacant on Jun 30 or sale date</dt><dd>${row.vacant_on_jun_30_or_sale ? "Marked yes" : "Not marked"}</dd></div>
      </dl></details>
    </article>`).join("") :
      '<div class="storefront-empty">No registry records match these filters or search.</div>';
  target.querySelector("#storefrontMore").hidden = shown.length >= rows.length;
  persistDashboardView();
}

function paintStorefrontExplorer(target) {
  const year = storefrontData.reporting_years.join(", ") || "Unavailable";
  target.innerHTML = `<div class="storefront-heading"><div><h3>Storefront Research</h3>
    <p>Registry records for research. Availability and asking rent are not verified.</p></div>
    <span class="storefront-source">${escapeHtml(storefrontData.source)} · Reporting year ${escapeHtml(year)}</span></div>
    <div class="storefront-toolbar"><div class="storefront-controls">
      <label>Area<select id="storefrontArea"><option value="all">All boroughs</option><option value="selected">Selected tract · ${escapeHtml(selectedLocation().name)}</option>
        ${["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"].map(name => `<option value="${name}">${name}</option>`).join("")}</select></label>
      <label>Reported vacancy<select id="storefrontVacancy"><option value="all">All registry records</option><option value="reported_vacant">Reported vacant</option>
        <option value="dec31">Vacant on Dec 31</option><option value="jun30">Vacant on Jun 30 or sale date</option><option value="unknown">Unknown status</option></select></label>
      <label>Search address or activity<input id="storefrontSearch" type="search" placeholder="Address or reported activity" value="${escapeHtml(storefrontQuery)}" /></label>
    </div><div class="storefront-count" id="storefrontCount" role="status"></div></div>
    <div class="storefront-row-head"><span>Address</span><span>Reported Status</span><span>Reported Activity</span><span class="sr-only">Details</span></div>
    <div class="storefront-rows" id="storefrontRows"></div>
    <button type="button" class="storefront-more" id="storefrontMore">Show More</button>`;
  target.querySelector("#storefrontArea").value = storefrontArea;
  target.querySelector("#storefrontVacancy").value = storefrontVacancy;
  target.querySelector("#storefrontArea").addEventListener("change", event => {storefrontArea = event.target.value; storefrontVisible = 12; drawStorefrontRows(target);});
  target.querySelector("#storefrontVacancy").addEventListener("change", event => {storefrontVacancy = event.target.value; storefrontVisible = 12; drawStorefrontRows(target);});
  target.querySelector("#storefrontSearch").addEventListener("input", event => {storefrontQuery = event.target.value; storefrontVisible = 12; drawStorefrontRows(target);});
  target.querySelector("#storefrontMore").addEventListener("click", () => {storefrontVisible += 12; drawStorefrontRows(target);});
  drawStorefrontRows(target);
}

async function renderStorefrontExplorer() {
  const target = document.querySelector("#storefrontExplorer");
  if (!target || !dashboard || activeView !== "lease" || propertyTab !== "research") return;
  if (storefrontData) {paintStorefrontExplorer(target); return;}
  target.innerHTML = '<div class="storefront-loading" role="status">Loading Storefront Registry records…</div>';
  try {
    if (!storefrontPromise) storefrontPromise = fetch("/api/storefronts")
      .then(response => {if (!response.ok) throw new Error("Storefront Registry unavailable"); return response.json();})
      .catch(error => {storefrontPromise = null; throw error;});
    const data = await storefrontPromise;
    storefrontData = data;
    if (target.isConnected && activeView === "lease" && propertyTab === "research") paintStorefrontExplorer(target);
  } catch (_) {
    if (!target.isConnected || activeView !== "lease" || propertyTab !== "research") return;
    target.innerHTML = '<div class="storefront-error" role="alert">Storefront Registry records could not load. <button type="button">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderStorefrontExplorer);
  }
}

function renderWhitespace() {
  const location = selectedLocation();
  const key = `${location.id}:${dashboard.meta.concept.cuisine}`;
  const market = competitionResolved.get(key);
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
  if (competitionResolved.has(key)) return renderWhitespace();
  const current = ++competitionRequest;
  renderWhitespace();
  try {
    await loadCompetitionData(location.id, cuisine);
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
  if (activeView === "discover" && locationMap) requestAnimationFrame(() => {locationMap.resize(); updateNycConstraints();});
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
  renderFeeds();
  renderShortlist();
  renderCompare();
  renderLease();
  if (activeView === "lease" && propertyTab === "research") renderStorefrontExplorer();
  renderWhitespace();
  renderFinance();
  renderReports();
  renderDataLayers();
  renderPanels();
  persistDashboardView();
  renderMenu();
}

function renderConceptChrome() {
  const name = conceptName();
  document.querySelector("#workspaceTitle").textContent = activeView === "menu" ? `${name} Menu` : `${name} Location Search`;
  document.querySelector("#activeConceptName").textContent = name;
  document.querySelector("#activeCuisine").textContent = state.cuisine === "custom" ? (document.querySelector("#briefCustomCuisine").value.trim() || "Other cuisine") : cuisineLabel();
  document.querySelector("#activePrice").textContent = state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`;
  document.querySelector("#activeArea").textContent = state.preferredArea || "Anywhere in NYC";
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
  if (hasSubmittedBrief || legacyCuisineRequired) {
    const known = ideaOptions.find(item => item.label === state.conceptName);
    selectedIdea = known || {...ideaOptions.find(item => item.value === "other"), profile: state.profile};
    document.querySelector("#briefConceptName").value = selectedIdea.label;
    document.querySelector("#customIdeaField").hidden = selectedIdea.value !== "other";
    document.querySelector("#briefCustomIdea").value = known ? "" : state.conceptName;
    document.querySelector("#briefCuisine").value = hasExplicitCuisine(state.cuisine) ? state.cuisine : "";
    document.querySelector("#cuisineSearch").value = document.querySelector("#briefCuisine").selectedOptions[0]?.textContent || "";
    document.querySelector("#customCuisineField").hidden = state.cuisine !== "custom";
    const custom = state.cuisine === "custom" ? state.description.match(/(?:^|\. )Cuisine: (.*)$/) : null;
    document.querySelector("#briefCustomCuisine").value = custom?.[1] || "";
    document.querySelector("#briefDescription").value = custom ? state.description.slice(0, custom.index) : state.description;
    document.querySelector("#briefDeal").value = state.dealType;
    document.querySelector("#briefPurchaseBudget").value = state.purchaseBudget;
    document.querySelector("#briefServiceStyle").value = state.serviceStyle;
    document.querySelector("#briefAudience").value = state.audience;
    document.querySelector("#briefDaypart").value = state.daypart;
  }
  if (hasSubmittedBrief) document.querySelector("#briefCuisine").value = state.cuisine;
  if (hasSubmittedBrief) document.querySelector("#briefPriceTier").value = state.priceTier;
  if (hasSubmittedBrief) document.querySelector("#briefDietary").value = state.dietary;
  document.querySelector("#conceptInput").value = conceptName();
  if (hasSubmittedBrief && selectedIdea?.value !== "other") document.querySelector("#briefConceptName").value = conceptName();
  document.querySelector("#dealSelect").value = state.dealType;
  if (hasSubmittedBrief && rentWasEntered) document.querySelector("#briefBudget").value = String(state.rentCap);
  if (hasSubmittedBrief) document.querySelector("#briefArea").value = state.preferredArea;
  document.querySelector("#rentRange").value = String(Math.round(state.rentCap / 1000));
  document.querySelector("#rentLabel").textContent = `$${Math.round(state.rentCap / 1000)}k`;
  document.querySelector("#financeFixedCosts").value = state.otherFixedCosts;
  document.querySelector("#financeVariableCosts").value = state.variableCostPct;
  document.querySelector("#financeOperatingDays").value = state.operatingDays;
  syncTransactionFields();
  updateConceptImage(state.cuisine);
  renderConceptChrome();
}

function closeBrief() {
  document.querySelector("#briefOverlay").classList.remove("is-open");
  sessionStorage.setItem("groundwork-brief-open", "false");
}

function openBrief() {
  syncBriefControls();
  document.querySelector("#briefOverlay").classList.add("is-open");
  sessionStorage.setItem("groundwork-brief-open", "true");
}

function hasExplicitCuisine(value) {
  return Boolean(value && value !== "any" && [...document.querySelector("#briefCuisine").options].some(option => option.value === value));
}

function applyBrief() {
  const idea = document.querySelector("#briefConceptName");
  const cuisine = document.querySelector("#briefCuisine");
  const price = document.querySelector("#briefPriceTier");
  const customIdea = document.querySelector("#briefCustomIdea");
  const customCuisine = document.querySelector("#briefCustomCuisine");
  const validIdea = selectedIdea && (idea.value === selectedIdea.label);
  const checks = [
    ["ideaError", validIdea], ["cuisineError", hasExplicitCuisine(cuisine.value)], ["priceError", Boolean(price.value)],
  ];
  checks.forEach(([id, valid]) => document.getElementById(id).hidden = valid);
  customIdea.required = selectedIdea?.value === "other";
  customCuisine.required = cuisine.value === "custom";
  customIdea.setCustomValidity(customIdea.required && !customIdea.value.trim() ? "Enter your restaurant idea." : "");
  customCuisine.setCustomValidity(customCuisine.required && !customCuisine.value.trim() ? "Enter your cuisine." : "");
  document.querySelector("#briefDescription").setCustomValidity("");
  if (!checks.every(([, valid]) => valid)) {
    (validIdea ? (!hasExplicitCuisine(cuisine.value) ? document.querySelector("#cuisineSearch") : price) : idea).focus();
    return;
  }
  if (!document.querySelector("#briefForm").reportValidity()) return;
  state.conceptName = selectedIdea.value === "other" ? customIdea.value.trim() : selectedIdea.label;
  state.profile = selectedIdea.profile;
  state.cuisine = cuisine.value;
  state.priceTier = price.value;
  state.priceMode = "tier";
  state.averageCheck = PRICE_DEFAULTS[price.value];
  state.dietary = document.querySelector("#briefDietary").value || "none";
  const description = document.querySelector("#briefDescription").value.trim();
  const otherCuisine = cuisine.value === "custom" ? customCuisine.value.trim() : "";
  const combinedDescription = [description, otherCuisine ? `Cuisine: ${otherCuisine}` : ""].filter(Boolean).join(". ");
  if (combinedDescription.length > 500) {
    document.querySelector("#briefDescription").setCustomValidity("Shorten the description so your custom cuisine also fits within 500 characters.");
    document.querySelector("#briefDescription").reportValidity();
    return;
  }
  document.querySelector("#briefDescription").setCustomValidity("");
  state.description = combinedDescription;
  state.dealType = document.querySelector("#briefDeal").value || "lease";
  state.preferredArea = document.querySelector("#briefArea").value;
  state.serviceStyle = document.querySelector("#briefServiceStyle").value || defaultServiceStyle(state.profile);
  state.audience = document.querySelector("#briefAudience").value || "residents";
  state.daypart = document.querySelector("#briefDaypart").value || "all_day";
  const rent = document.querySelector("#briefBudget").value;
  rentWasEntered = Boolean(rent);
  state.rentCap = rent ? Number(rent) : 18000;
  const purchase = document.querySelector("#briefPurchaseBudget").value;
  state.purchaseBudget = purchase ? Number(purchase) : 3000000;
  if (rent && (state.rentCap < 8000 || state.rentCap > 35000)) {document.querySelector("#briefBudget").reportValidity(); return;}
  hasSubmittedBrief = true;
  legacyCuisineRequired = false;
  document.querySelector("#briefSkip").hidden = false;
  sessionStorage.setItem("groundwork-submitted-brief", JSON.stringify({state, selectedIdea: selectedIdea.value, rentWasEntered, fields: Object.fromEntries(draftIds.map(id => [id, document.getElementById(id).value]))}));
  sessionStorage.removeItem("groundwork-concept-draft");
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

document.querySelector("#headerEditBrief").addEventListener("click", () => {
  openBrief();
});
document.querySelector("#accountAccessButton")?.addEventListener("click", () => document.querySelector("#welcomeOverlay").classList.add("is-open"));
document.querySelector("#closeAccessButton")?.addEventListener("click", () => document.querySelector("#welcomeOverlay").classList.remove("is-open"));

document.querySelector("#refreshButton").addEventListener("click", () => {
  loadDashboard();
});

document.querySelector("#viewAnalysis").addEventListener("click", () => selectView("scorecard"));
document.querySelector("#mapLayerSelect").addEventListener("change", event => setActiveLayer(event.target.value));
document.querySelector("#mapBasemapSelect").addEventListener("change", event => changeMapView(event.target.value));
document.querySelector("#showRestaurantsToggle").addEventListener("change", event => {
  showExistingRestaurants = event.target.checked;
  syncRestaurantVisibility();
});

const ideaOptions = [
  ["restaurant", "Sit-Down Restaurant", "restaurant"], ["bar", "Bar or Gastropub", "bar"],
  ["coffee", "Coffee and Breakfast", "coffee"], ["fast_casual", "Fast Casual", "fast_casual"],
  ["counter_service", "Counter Service", "counter_service"], ["bakery", "Bakery or Pastry Shop", "bakery"],
  ["fine_dining", "Fine Dining", "fine_dining"], ["takeout_delivery", "Takeout and Delivery", "takeout_delivery"],
  ["cafe", "Café", "coffee"], ["bistro", "Bistro", "restaurant"], ["pizzeria", "Pizzeria", "restaurant"],
  ["dessert_shop", "Dessert Shop", "bakery"], ["food_truck", "Food Truck", "counter_service"],
  ["other", "Other", "restaurant"],
].map(([value, label, profile]) => ({value, label, profile}));
let selectedIdea = null;
let hasSubmittedBrief = false;
let rentWasEntered = false;

function setupChoice(input, list, options, onChoose) {
  let shown = [], active = -1;
  function render() {
    const query = normalizeConceptText(input.value);
    shown = options().filter(item => !query || normalizeConceptText(item.label).includes(query));
    list.replaceChildren();
    shown.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "option";
      button.id = `${list.id}-${index}`;
      button.textContent = item.label;
      button.addEventListener("mousedown", event => event.preventDefault());
      button.addEventListener("click", () => choose(item));
      list.append(button);
    });
    list.hidden = !shown.length;
    input.setAttribute("aria-expanded", String(Boolean(shown.length)));
    active = -1;
  }
  function choose(item) {
    input.value = item.label;
    onChoose(item);
    input.dispatchEvent(new Event("change", {bubbles: true}));
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }
  input.addEventListener("focus", render);
  input.addEventListener("input", render);
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") {list.hidden = true; input.setAttribute("aria-expanded", "false"); return;}
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) render();
      if (!shown.length) return;
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      list.querySelectorAll("button").forEach((button, index) => button.setAttribute("aria-selected", String(index === active)));
      input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
    } else if (event.key === "Enter" && !list.hidden && shown.length) {event.preventDefault(); choose(shown[Math.max(active, 0)]);}
  });
  input.addEventListener("blur", () => setTimeout(() => {list.hidden = true; input.setAttribute("aria-expanded", "false");}, 100));
}

const ideaInput = document.querySelector("#briefConceptName");
setupChoice(ideaInput, document.querySelector("#conceptSuggestions"), () => ideaOptions, item => {
  selectedIdea = item;
  document.querySelector("#customIdeaField").hidden = item.value !== "other";
  document.querySelector("#ideaError").hidden = true;
});
ideaInput.addEventListener("input", () => {selectedIdea = null; document.querySelector("#customIdeaField").hidden = true;});
const cuisineInput = document.querySelector("#cuisineSearch");
const cuisineSelect = document.querySelector("#briefCuisine");
setupChoice(cuisineInput, document.querySelector("#cuisineSuggestions"), () => [...cuisineSelect.options].filter(option => option.value).map(option => ({value: option.value, label: option.textContent})), item => {
  cuisineSelect.value = item.value;
  document.querySelector("#customCuisineField").hidden = item.value !== "custom";
  document.querySelector("#cuisineError").hidden = true;
});
cuisineInput.addEventListener("input", () => {cuisineSelect.value = ""; document.querySelector("#customCuisineField").hidden = true;});
document.querySelector("#briefPriceTier").addEventListener("change", () => document.querySelector("#priceError").hidden = true);
for (const id of ["briefCustomIdea", "briefCustomCuisine", "briefDescription"]) {
  document.getElementById(id).addEventListener("input", event => event.target.setCustomValidity(""));
}
const descriptionIdeas = [
  {text: "Seasonal pastries", terms: "cafe café coffee bakery pastry breakfast brunch seasonal"},
  {text: "Specialty coffee", terms: "cafe café coffee espresso breakfast"},
  {text: "Weekday breakfast", terms: "cafe café breakfast brunch bakery morning weekday"},
  {text: "Quick weekday lunches", terms: "lunch sandwich deli fast casual counter weekday"},
  {text: "Family dining", terms: "family dinner restaurant bistro neighborhood"},
  {text: "Late-night dining", terms: "late night bar dinner gastropub"},
  {text: "Vegetarian options", terms: "vegetarian vegan plant salad healthy"},
  {text: "Takeout and delivery", terms: "takeout delivery quick pizza"},
];
const descriptionField = document.querySelector("#briefDescription");
const descriptionList = document.querySelector("#descriptionSuggestions");
let activeDescriptionSuggestion = -1;
let visibleDescriptionSuggestions = [];
function closeDescriptionSuggestions() {
  descriptionList.hidden = true;
  descriptionField.setAttribute("aria-expanded", "false");
  activeDescriptionSuggestion = -1;
}
function renderDescriptionSuggestions() {
  const writing = descriptionField.value.toLowerCase();
  const context = `${ideaInput.value} ${writing}`.toLowerCase();
  const words = context.match(/[\p{L}]+/gu) || [];
  visibleDescriptionSuggestions = descriptionIdeas
    .filter(item => !writing.includes(item.text.toLowerCase()))
    .map(item => ({...item, score: words.reduce((score, word) => score + (word.length > 2 && item.terms.includes(word) ? 1 : 0), 0)}))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
  descriptionList.replaceChildren();
  visibleDescriptionSuggestions.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.text;
    button.setAttribute("aria-label", `Add ${item.text} to description`);
    button.addEventListener("mousedown", event => event.preventDefault());
    button.addEventListener("click", () => insertDescriptionSuggestion(index));
    descriptionList.append(button);
  });
  activeDescriptionSuggestion = -1;
  descriptionList.hidden = !visibleDescriptionSuggestions.length;
  descriptionField.setAttribute("aria-expanded", String(!descriptionList.hidden));
}
function insertDescriptionSuggestion(index) {
  const suggestion = visibleDescriptionSuggestions[index]?.text;
  if (!suggestion || descriptionField.value.toLowerCase().includes(suggestion.toLowerCase())) return;
  const existing = descriptionField.value.trimEnd();
  const separator = existing ? (/[.!?]$/.test(existing) ? " " : ". ") : "";
  if (existing.length + separator.length + suggestion.length > descriptionField.maxLength) return;
  descriptionField.value = existing + separator + suggestion;
  descriptionField.dispatchEvent(new Event("input", {bubbles: true}));
  closeDescriptionSuggestions();
  descriptionField.focus();
}
descriptionField.addEventListener("input", renderDescriptionSuggestions);
ideaInput.addEventListener("input", renderDescriptionSuggestions);
descriptionField.addEventListener("focus", renderDescriptionSuggestions);
descriptionField.addEventListener("keydown", event => {
  if (event.key === "Escape") {closeDescriptionSuggestions(); return;}
  if (descriptionList.hidden) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    activeDescriptionSuggestion = (activeDescriptionSuggestion + (event.key === "ArrowDown" ? 1 : -1) + visibleDescriptionSuggestions.length) % visibleDescriptionSuggestions.length;
    descriptionList.querySelectorAll("button").forEach((button, index) => button.setAttribute("aria-selected", String(index === activeDescriptionSuggestion)));
  } else if (event.key === "Enter" && activeDescriptionSuggestion >= 0) {
    event.preventDefault();
    insertDescriptionSuggestion(activeDescriptionSuggestion);
  }
});
descriptionField.addEventListener("blur", () => setTimeout(closeDescriptionSuggestions, 120));
function clearBriefSession() {
  ["groundwork-submitted-brief", "groundwork-concept-draft", "groundwork-brief-open", "groundwork-dashboard-view"].forEach(key => sessionStorage.removeItem(key));
}
document.querySelector("#logoutButton").addEventListener("click", () => {clearBriefSession(); document.querySelector("#logoutForm").submit();});
document.querySelector("#authForm").addEventListener("submit", clearBriefSession);
document.querySelector(".guest-form").addEventListener("submit", clearBriefSession);


document.querySelector("#savedBriefs").addEventListener("click", event => {
  const open = event.target.closest("[data-open-brief]");
  const remove = event.target.closest("[data-remove-brief]");
  const rows = readStoredBriefs();
  if (open && rows[Number(open.dataset.openBrief)]) {
    const brief = rows[Number(open.dataset.openBrief)];
    briefFields.forEach(key => { if (typeof brief[key] === typeof state[key]) state[key] = brief[key]; });
    selectedId = null;
    hasSubmittedBrief = hasExplicitCuisine(state.cuisine);
    legacyCuisineRequired = !hasSubmittedBrief;
    syncBriefControls();
    if (legacyCuisineRequired) openBrief();
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
document.querySelector(`[data-auth-mode="${document.querySelector("#authForm").action.endsWith("signup") ? "signup" : "login"}"]`).click();
const draftIds = ["briefConceptName", "briefCustomIdea", "cuisineSearch", "briefCuisine", "briefCustomCuisine", "briefPriceTier", "briefDietary", "briefDeal", "briefBudget", "briefPurchaseBudget", "briefArea", "briefDescription", "briefServiceStyle", "briefAudience", "briefDaypart"];
let savedFields = null;
let legacyCuisineRequired = false;
try {
  const saved = JSON.parse(sessionStorage.getItem("groundwork-submitted-brief") || "null");
  if (saved?.state && ideaOptions.some(item => item.value === saved.selectedIdea)) {
    Object.assign(state, saved.state);
    legacyCuisineRequired = !hasExplicitCuisine(saved.state.cuisine);
    hasSubmittedBrief = !legacyCuisineRequired;
    if (legacyCuisineRequired) state.cuisine = "any";
    selectedIdea = ideaOptions.find(item => item.value === saved.selectedIdea);
    rentWasEntered = Boolean(saved.rentWasEntered);
    savedFields = saved.fields;
  }
} catch (_) {}
syncBriefControls();
try {
  const draft = JSON.parse(sessionStorage.getItem("groundwork-concept-draft") || "null");
  const fields = hasSubmittedBrief ? savedFields : (draft || savedFields);
  if (fields) {
    draftIds.forEach(id => {if (fields[id] !== undefined) document.getElementById(id).value = fields[id];});
    if (!hasSubmittedBrief) selectedIdea = ideaOptions.find(item => item.value === draft?.selectedIdea) || selectedIdea;
    document.querySelector("#customIdeaField").hidden = selectedIdea?.value !== "other";
    document.querySelector("#customCuisineField").hidden = cuisineSelect.value !== "custom";
  }
} catch (_) {}
if (selectedIdea && !document.querySelector("#briefConceptName").value) document.querySelector("#briefConceptName").value = selectedIdea.label;
if ((hasSubmittedBrief || legacyCuisineRequired) && !document.querySelector("#briefPriceTier").value) document.querySelector("#briefPriceTier").value = state.priceTier;
if (legacyCuisineRequired) {
  if (!hasExplicitCuisine(cuisineSelect.value)) {
    cuisineSelect.value = "";
    cuisineInput.value = "";
  }
  document.querySelector("#cuisineError").textContent = "This saved brief needs a cuisine. Choose one from the list to continue.";
  document.querySelector("#cuisineError").hidden = false;
  document.querySelector("#briefSkip").hidden = true;
  document.querySelector("#briefOverlay").classList.add("is-open");
  sessionStorage.setItem("groundwork-brief-open", "true");
} else if (hasSubmittedBrief) {
  if (!hasExplicitCuisine(cuisineSelect.value)) cuisineSelect.value = state.cuisine;
  cuisineInput.value = cuisineSelect.selectedOptions[0]?.textContent || "";
  closeBrief();
}
if (hasSubmittedBrief || legacyCuisineRequired) {
  try {
    const view = JSON.parse(sessionStorage.getItem("groundwork-dashboard-view") || "null");
    if (view && [...document.querySelectorAll(".feature-tab")].some(button => button.dataset.view === view.activeView)) activeView = view.activeView;
    if (typeof view?.selectedId === "string" && /^\d{11}$/.test(view.selectedId)) selectedId = view.selectedId;
    if (typeof view?.comparisonId === "string" && /^\d{11}$/.test(view.comparisonId)) profileComparisonId = view.comparisonId;
    if (view?.profileExpanded && typeof view.profileExpanded === "object") {
      Object.keys(profileExpanded).forEach(group => {if (typeof view.profileExpanded[group] === "boolean") profileExpanded[group] = view.profileExpanded[group];});
    }
    if (view?.transitExpanded && typeof view.transitExpanded === "object") {
      Object.keys(transitExpanded).forEach(group => {if (typeof view.transitExpanded[group] === "boolean") transitExpanded[group] = view.transitExpanded[group];});
    }
    if (typeof view?.competitionBreakdownOpen === "boolean") competitionBreakdownOpen = view.competitionBreakdownOpen;
    if (typeof view?.competitionComparisonOpen === "boolean") competitionComparisonOpen = view.competitionComparisonOpen;
    if (typeof view?.competitionContext === "string") competitionContext = view.competitionContext;
    if (view?.competitionFilter === "all" || view?.competitionFilter === "mine" ||
        (typeof view?.competitionFilter === "string" && view.competitionFilter.startsWith("cuisine:"))) competitionFilter = view.competitionFilter;
    if (typeof view?.competitionQuery === "string") competitionQuery = view.competitionQuery.slice(0, 200);
    if (Number.isInteger(view?.competitionVisible) && view.competitionVisible >= 10 && view.competitionVisible <= 300) competitionVisible = view.competitionVisible;
    if (["all", "selected", "Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"].includes(view?.storefrontArea)) storefrontArea = view.storefrontArea;
    if (["all", "reported_vacant", "dec31", "jun30", "unknown"].includes(view?.storefrontVacancy)) storefrontVacancy = view.storefrontVacancy;
    if (typeof view?.storefrontQuery === "string") storefrontQuery = view.storefrontQuery.slice(0, 200);
    if (Number.isInteger(view?.storefrontVisible) && view.storefrontVisible >= 12 && view.storefrontVisible <= 300) storefrontVisible = view.storefrontVisible;
    if (["research", "listings"].includes(view?.propertyTab)) propertyTab = view.propertyTab;
  } catch (_) {}
}
document.querySelector("#briefForm").addEventListener("input", () => sessionStorage.setItem("groundwork-concept-draft", JSON.stringify(Object.fromEntries([...draftIds.map(id => [id, document.getElementById(id).value]), ["selectedIdea", selectedIdea?.value]]))));
document.querySelector("#briefForm").addEventListener("change", () => sessionStorage.setItem("groundwork-concept-draft", JSON.stringify(Object.fromEntries([...draftIds.map(id => [id, document.getElementById(id).value]), ["selectedIdea", selectedIdea?.value]]))));

syncRestaurantVisibility();
setTheme(dashboardThemeChoice, false);
document.querySelectorAll("[data-property-tab]").forEach(button => {
  button.addEventListener("click", () => selectPropertyTab(button.dataset.propertyTab));
  button.addEventListener("keydown", event => {
    const tabs = ["research", "listings"];
    const index = tabs.indexOf(button.dataset.propertyTab);
    const next = event.key === "ArrowRight" ? tabs[(index + 1) % tabs.length] :
      event.key === "ArrowLeft" ? tabs[(index + tabs.length - 1) % tabs.length] :
        event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : null;
    if (next) {event.preventDefault(); selectPropertyTab(next, true);}
  });
});
syncPropertyTabs();
selectView(activeView);
document.querySelectorAll("[data-auth-open]").forEach(button => button.addEventListener("click", () => {
  document.querySelector(`[data-auth-mode="${button.dataset.authOpen}"]`).click();
  document.querySelector("#welcomeOverlay").classList.add("is-open");
}));
document.querySelector("#closeAccessButton")?.addEventListener("click", () => document.querySelector("#welcomeOverlay").classList.remove("is-open"));
document.querySelectorAll("[data-logout]").forEach(button => button.addEventListener("click", () => {clearBriefSession(); document.querySelector("#logoutForm").submit();}));
setTheme(dashboardThemeChoice, false);
updateConceptImage(state.cuisine);
loadConceptImages();
initializeWorkspace();
setActiveLayer(activeLayer);

let nycBoundaryData = null;
let nycBoundaryPending = false;
let nycBoundaryRetryAfter = 0;

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
  const foreground = ["restaurant-clusters", "restaurant-points",
    "restaurant-cluster-count"].filter(id=>locationMap.getLayer(id));
  const ordered = [...ids, ...foreground];
  const last = locationMap.getStyle().layers.slice(-ordered.length).map(layer=>layer.id);
  if (ordered.some((id,index)=>last[index] !== id)) ordered.forEach(id=>locationMap.moveLayer(id));
}
