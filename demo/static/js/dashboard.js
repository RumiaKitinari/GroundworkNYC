let dashboard = null;
let selectedId = null;
let activeLayer = "opportunity";
let activeView = "discover";
let requestId = 0;
let locationMap = null;
let mapMarkers = [];
let mapPopup = null;
let mapDataset = "";
let activeBasemap = "streets";
let currentTheme = localStorage.getItem("groundwork-theme") === "light" ? "light" : "dark";

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

function setTheme(theme) {
  currentTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = currentTheme;
  localStorage.setItem("groundwork-theme", currentTheme);
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === currentTheme));
  });
  if (locationMap && activeBasemap === "streets") locationMap.setStyle(mapStyle("streets"));
}

const toneFor = {
  opportunity: ["#b6404a", "#df7653", "#e9b967", "#a8ca78", "#39ae88", "#087c78"],
  activity: ["#455c71", "#66849b", "#9bb2b2", "#c5ba83", "#e1a65d", "#b96a39"],
  whitespace: ["#725568", "#9a6b78", "#c28c87", "#c7ad7b", "#96bb8a", "#458a80"],
  cost: ["#a74b52", "#c47a5e", "#d5ab6f", "#b8c684", "#73af85", "#367d72"],
  walkability: ["#955158", "#c48261", "#d6b776", "#acc78c", "#6cac9a", "#337f90"],
  business_draw: ["#a34359", "#cf7968", "#deac70", "#b2c782", "#71b394", "#28878a"],
};

const layerTitles = {
  opportunity: "Location Opportunities",
  activity: "Local Demand",
  whitespace: "Market Gaps",
  cost: "Commercial Suitability",
  walkability: "Area Walkability",
  business_draw: "Business Draw",
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
  return styles.map((style, index) => ({
    title: `${baseName} ${style.name}`,
    cuisine: match?.value || "vegetarian_vegan",
    dietary,
    profile: style.profile,
    priority: remaining && normalizeConceptText(style.name).includes(remaining) ? 100 - index : -index,
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

function chooseConceptSuggestion(item, input) {
  if (input.id === "briefConceptName") {
    input.value = item.title;
    document.querySelector("#briefCuisine").value = item.cuisine;
    document.querySelector("#briefDietary").value = item.dietary;
    document.querySelector("#briefProfile").value = item.profile;
    document.querySelector("#briefServiceStyle").value = defaultServiceStyle(item.profile);
  } else {
    state.conceptName = item.title;
    state.cuisine = item.cuisine;
    state.dietary = item.dietary;
    state.profile = item.profile;
    state.serviceStyle = defaultServiceStyle(item.profile);
    state.description = "";
    selectedId = null;
    if (input.id === "searchInput") input.value = "";
    syncBriefControls();
    loadDashboard();
  }
  closeConceptSuggestions();
}

function renderConceptSuggestions(input) {
  if (activeConceptInput && activeConceptInput !== input) closeConceptSuggestions();
  activeConceptInput = input;
  const list = document.querySelector(`#${input.getAttribute("aria-controls")}`);
  visibleSuggestions = conceptSuggestionsFor(input.value);
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
  list.hidden = !visibleSuggestions.length;
  input.setAttribute("aria-expanded", String(Boolean(visibleSuggestions.length)));
}

async function loadDashboard() {
  const currentRequest = ++requestId;
  const status = document.querySelector("#dashboardStatus");
  status.hidden = false;
  status.textContent = "Updating Locations...";
  document.querySelector(".workspace").setAttribute("aria-busy", "true");
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
    document.querySelector(".workspace").classList.remove("has-no-results");
    selectedId = selectedId || dashboard.selected;
    if (!dashboard.locations.some((location) => location.id === selectedId)) {
      selectedId = dashboard.selected;
    }
    renderAll();
    status.hidden = true;
  } catch (error) {
    if (currentRequest === requestId) {
      status.textContent = "Unable To Update Locations. Select Refresh To Retry.";
    }
  } finally {
    if (currentRequest === requestId) document.querySelector(".workspace").setAttribute("aria-busy", "false");
  }
}

function selectedLocation() {
  return dashboard.locations.find((location) => location.id === selectedId) || dashboard.locations[0];
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

function renderMap() {
  if (!locationMap) {
    locationMap = new maplibregl.Map({container: "mapStage", style: mapStyle(activeBasemap), center: [-73.96, 40.73], zoom: 11, maxZoom: 19, attributionControl: true});
    locationMap.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-left");
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
  mapMarkers.forEach(marker => marker.remove());
  mapMarkers = [];
  const locations = dashboard.locations.filter(row => Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
  locations.forEach((location) => {
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
    });
    mapMarkers.push(new maplibregl.Marker({element, anchor: "center"}).setLngLat([location.longitude, location.latitude]).addTo(locationMap));
  });
  const key = locations.map(row => row.id).join(",");
  if (key !== mapDataset && locations.length) {
    const latitudes = locations.map(row => row.latitude);
    const longitudes = locations.map(row => row.longitude);
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
}

function renderRanking() {
  const rows = dashboard.locations;
  document.querySelector("#rankingTable").innerHTML = `
    <div class="table-row header">
      <span>#</span><span>Location</span><span>Score</span><span>Business Draw</span><span>Walkability</span><span>Cuisine Fit</span><span>Commercial Fit</span><span>Asking Rent</span>
    </div>
    ${rows.map((row, index) => `
      <div class="table-row${row.id === selectedId ? " is-selected" : ""}" data-id="${row.id}">
        <button type="button">${index + 1}</button>
        <button class="place-name" type="button">${row.name}</button>
        <span class="${scoreClass(row.opportunity)}">${row.opportunity}</span>
        <span>${row.business_draw}</span>
        <span>${row.walkability ?? "--"}</span>
        <span>${row.score_components.find((item) => item.key === "market_gap").score}</span>
        <span>${row.score_components.find((item) => item.key === "economics").score}</span>
        <span>${rentDisplay(row)}</span>
      </div>
    `).join("")}
  `;

  document.querySelectorAll(".table-row[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedId = row.dataset.id;
      renderAll();
    });
  });
}

function renderScorecard() {
  const location = selectedLocation();
  const evidence = location.concept_evidence;
  const count = value => value === null ? "Unavailable" : Number(value).toLocaleString("en-US");
  const risks = location.risk_flags.map((risk) => `<li>${titleCase(risk)}</li>`).join("");
  const components = location.score_components.map((component) => `
    <article class="score-component">
      <div class="score-component__top">
        <div>
          <h3>${component.label}</h3>
        </div>
        <strong class="${scoreClass(component.score)}">${component.score}</strong>
      </div>
      <div class="component-bars">
        <div>
          <span>Score</span>
          <div class="bar-track"><div class="bar-fill" style="width:${component.score}%;background:${colorFor(component.score, "opportunity")}"></div></div>
        </div>
        <div>
          <span>Evidence Strength ${component.coverage}%</span>
          <div class="bar-track evidence"><div class="bar-fill" style="width:${component.coverage}%;background:var(--cyan)"></div></div>
        </div>
      </div>
    </article>
  `).join("");

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
        <div><span>Median Household Income</span><strong>${evidence.median_household_income === null ? "Unavailable" : fmtMoney(evidence.median_household_income)}</strong></div>
        <div><span>Local Residents</span><strong>${count(evidence.population)}</strong></div>
      </div>
    </section>
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
}

function renderFeeds() {
  const statusLabel = {
    mapped: "Available",
    cleaning: "In Review",
    review: "Needs QA",
    dedupe: "In Review",
    queued: "Coming Soon",
  };
  document.querySelector("#feedList").innerHTML = dashboard.feeds.map((feed) => `
    <article class="feed-row">
      <div class="feed-row__top">
        <span>${feed.name}</span>
        <span>${statusLabel[feed.status] || feed.status}</span>
      </div>
      <div class="feed-row__meta">
        <span>${titleCase(feed.records)}</span>
        <span>${feed.signal}% Coverage</span>
      </div>
      <div class="feed-meter"><span style="width:${feed.signal}%"></span></div>
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
  const candidates = dashboard.locations.slice(0, 4);
  document.querySelector("#compareBoard").innerHTML = candidates.map((row) => `
    <article class="compare-card">
      <span class="card-status">${row.confidence_score}% Evidence Strength</span>
      <h3>${row.name}</h3>
      <div class="score-line">
        <strong class="${scoreClass(row.opportunity)}">${row.opportunity}</strong>
        <span>${row.borough} - ${rentDisplay(row)} Rent</span>
      </div>
      <div class="kv"><span>Customer Fit</span><strong>${row.customer}</strong></div>
      <div class="kv"><span>Walkability</span><strong>${row.walkability ?? "--"}</strong></div>
      <div class="kv"><span>Business Draw</span><strong>${row.business_draw}</strong></div>
      <div class="kv"><span>Activity Index</span><strong>${row.activity}</strong></div>
      <div class="kv"><span>Transit</span><strong>${row.transit}</strong></div>
      <div class="kv"><span>Cuisine Fit</span><strong>${row.whitespace}</strong></div>
      <div class="kv"><span>Competition</span><strong>${row.competition}</strong></div>
      <div class="kv"><span>Commercial Fit</span><strong>${row.cost}</strong></div>
    </article>
  `).join("");
}

function renderLease() {
  let candidates = dashboard.properties || [];
  document.querySelector("#propertyHeading").textContent = state.dealType === "purchase" ? "Purchase Properties" : state.dealType === "either" ? "Lease & Purchase Properties" : "Lease Properties";
  if (state.preferredArea) {
    candidates = candidates.filter((row) => row.borough === state.preferredArea);
  }
  if (!candidates.length) {
    const emptyTitle = state.dealType === "purchase" ? "No Verified Purchase Listings" : "No Current Property Leads Found";
    document.querySelector("#leaseBoard").innerHTML = `
      <article class="property-empty">
        <h3>${emptyTitle}</h3>
        <button class="quiet-action" type="button" onclick="openBrief()">Edit Search Brief</button>
      </article>
    `;
    return;
  }

  const listingCount = candidates.filter(row => row.lead_type === "listing").length;
  const registryCount = candidates.length - listingCount;
  document.querySelector("#leaseBoard").innerHTML = `<div class="property-results-meta">${listingCount} Listings · ${registryCount} Storefront Records</div>` + candidates.map((row) => {
    const priceLine = row.price_label || "Unavailable";
    const imageClass = row.image ? "property-image" : "property-image no-image";
    const imageStyle = row.image ? ` style="background-image:url('${escapeHtml(row.image.replaceAll("'", "%27"))}')"` : "";
    const badge = row.transaction_label || "Property Record";
    const sqft = row.sqft ? `${row.sqft.toLocaleString()} Sq Ft` : (row.sqft_label || "Sq Ft Not In Source");
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
          ${row.broker_name ? `<div class="kv"><span>Broker / Owner</span><strong>${escapeHtml(row.broker_name)}</strong></div>` : ""}
          <div class="kv"><span>${row.lead_type === "registry_record" ? "Reported Activity" : "Condition"}</span><strong>${escapeHtml(row.condition)}</strong></div>
          ${row.lead_type === "registry_record" ? '<div class="property-source-note">Registry Record · Transaction And Contact Unverified</div>' : ""}
          ${row.source_url ? `<a class="property-link" href="${escapeHtml(row.source_url)}" target="_blank" rel="noopener noreferrer">Source Listing</a>` : ""}
          <a class="property-link" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${row.address}, ${row.borough}, New York`)}" target="_blank" rel="noopener noreferrer">View Address</a>
        </div>
      </article>
    `;
  }).join("");
}

function renderWhitespace() {
  const location = selectedLocation();
  const evidence = location.concept_evidence;
  document.querySelector("#gapBoard").innerHTML = `
    <section class="concept-evidence">
      <div class="concept-evidence-heading"><h3>${escapeHtml(location.name)}</h3><span>${escapeHtml(cuisineLabel())} · ${escapeHtml(evidence.positioning)}</span></div>
      <div class="evidence-grid">
        <div><span>Recorded In Tract</span><strong>${evidence.same_cuisine_count ?? "--"}</strong></div>
        <div><span>Recorded In Neighborhood</span><strong>${evidence.neighborhood_same_cuisine_count ?? "--"}</strong></div>
        <div><span>Cuisine Labels Available</span><strong>${evidence.cuisine_label_coverage}%</strong></div>
        <div><span>Cuisine Gap Index</span><strong>${evidence.cuisine_gap_index ?? "--"}</strong></div>
        <div><span>Dining Ecosystem Index</span><strong>${evidence.cuisine_ecosystem_index ?? "--"}</strong></div>
        <div><span>Inventory Reference</span><strong>${evidence.cuisine_inventory_count} Restaurants</strong></div>
      </div>
    </section>
  `;
}

function renderFinance() {
  const finance = dashboard.finance;
  document.querySelector("#financeScenarioForm").hidden = state.dealType === "purchase";
  if (state.dealType === "purchase") {
    const askingPrices = (dashboard.properties || []).filter(row => row.transaction === "purchase" && row.asking_price).map(row => row.asking_price);
    const lowestAskingPrice = askingPrices.length ? fmtPrice(Math.min(...askingPrices)) : "Unavailable";
    document.querySelector("#financeBoard").innerHTML = `
      <article class="finance-cell"><h3>Purchase Budget</h3><strong class="finance-figure">${fmtPrice(state.purchaseBudget)}</strong><span class="finance-basis">User Budget</span></article>
      <article class="finance-cell"><h3>Lowest Listed Asking Price</h3><strong class="finance-figure">${lowestAskingPrice}</strong><span class="finance-basis">${askingPrices.length ? `${askingPrices.length} Verified Listing${askingPrices.length === 1 ? "" : "s"}` : "No Confirmed Sale Listing"}</span></article>
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
  document.querySelector("#financeBoard").innerHTML = cells.map(([label, value, sub]) => `
    <article class="finance-cell">
      <h3>${label}</h3>
      <strong class="finance-figure">${value}</strong>
      <span class="finance-basis">${sub}</span>
    </article>
  `).join("");
}

function renderNow() {
  document.querySelector("#nowBoard").innerHTML = `<div class="property-empty"><h3>Hourly Demand Unavailable</h3><p>Trading Hours Assessment Pending.</p></div>`;
}

function renderReports() {
  const location = selectedLocation();
  document.querySelector("#reportBoard").innerHTML = `
    <div class="report-toolbar"><span>Location Brief</span><button class="primary-action" id="printReport" type="button">Print / Save PDF</button></div>
    <article class="location-report">
      <header><span class="eyebrow">Groundwork / New York City</span><span>${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span></header>
      <h2>${escapeHtml(conceptName())}</h2>
      <p>${profileLabel(state.profile)} · ${escapeHtml(cuisineLabel())} · ${state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`} · ${dealLabel(state.dealType)} · ${state.dealType === "purchase" ? `${fmtPrice(state.purchaseBudget)} Purchase Budget` : `${fmtMoney(state.rentCap)}/Month Budget`}</p>
      <section class="report-recommendation"><div><span class="eyebrow">Selected Location</span><h3>${escapeHtml(location.name)}</h3><p>${escapeHtml(location.recommendation)}</p></div><strong>${location.opportunity}<small>/100</small></strong></section>
      <h3>Location Factors</h3>
      <div class="report-factors">${location.score_components.map((item) => `<div class="kv"><span>${escapeHtml(item.label)}</span><strong>${item.score}/100</strong></div>`).join("")}</div>
      <h3>Due Diligence</h3><ul>${location.risk_flags.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")}</ul>
      <footer>${location.confidence_score}% Evidence Strength · Preliminary Tract-Level Screening<br>Walkability ${location.walkability ?? "Unavailable"}/100 · Business Draw ${location.business_draw}/100<br>Scores Are Relative Indicators, Not Visit Or Revenue Forecasts.<br>Property Availability, Asking Prices And Lease Terms Require Verification.</footer>
    </article>
  `;
  document.querySelector("#printReport").addEventListener("click", () => window.print());
}

function renderDataLayers() {
  const signals = selectedLocation().score_components;
  document.querySelector("#layerBoard").innerHTML = signals.map((row) => `
    <article class="layer-card">
      <span class="card-status">${row.coverage}% Evidence Strength</span>
      <h3>${row.label}</h3>
      <div class="feed-meter"><span style="width:${row.coverage}%"></span></div>
      <div class="kv"><span>Evidence</span><strong>${row.coverage >= 80 ? "High" : row.coverage >= 68 ? "Partial" : "Limited"}</strong></div>
    </article>
  `).join("");
}

function renderPanels() {
  document.querySelector(".workspace")?.classList.toggle("is-discover", activeView === "discover");
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("is-hidden", panel.dataset.panel !== activeView);
  });
  if (activeView === "discover" && locationMap) requestAnimationFrame(() => locationMap.resize());
}

function renderAll() {
  renderConceptChrome();
  renderMetrics();
  renderMap();
  renderIntel();
  renderRanking();
  renderScorecard();
  renderFeeds();
  renderShortlist();
  renderCompare();
  renderLease();
  renderWhitespace();
  renderFinance();
  renderNow();
  renderReports();
  renderDataLayers();
  renderPanels();
}

function renderConceptChrome() {
  const name = conceptName();
  document.querySelector("#workspaceTitle").textContent = `${name} Location Search`;
  document.querySelector("#activeConceptName").textContent = name;
  document.querySelector("#activeConceptMeta").textContent = `${dealLabel(state.dealType)} · ${profileLabel(state.profile)} · ${state.preferredArea || "Open To NYC"}`;
  const dietary = dashboard?.meta?.concept?.dietary;
  document.querySelector("#activeConceptMeta").textContent += ` · ${state.priceMode === "tier" ? `${state.priceTier} Price Range` : `$${state.averageCheck} Per Guest`}${dietary && dietary !== "none" ? ` · ${titleCase(dietary.replace("_", "-"))}` : ""}`;
}

document.querySelectorAll(".feature-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".feature-tab").forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    activeView = button.dataset.view;
    renderPanels();
  });
});

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
  syncTransactionFields();
  syncPriceModeControls();
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
    chooseConceptSuggestion(suggestion, ideaInput);
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
  closeBrief();
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
      const suggestion = conceptSuggestionsFor(query)[0];
      if (suggestion) chooseConceptSuggestion(suggestion, input);
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
document.querySelector("#mapBasemapSelect").addEventListener("change", event => {
  const next = event.target.value;
  if (!locationMap || !["streets", "aerial"].includes(next) || next === activeBasemap) return;
  activeBasemap = next;
  locationMap.setStyle(mapStyle(activeBasemap));
});

document.querySelector("#searchInput").addEventListener("input", (event) => {
  if (!dashboard) return;
  const query = event.target.value.trim().toLowerCase();
  if (conceptSuggestionsFor(query).length) return;
  const match = dashboard.locations.find((row) => row.name.toLowerCase().includes(query) || row.borough.toLowerCase().includes(query));
  if (query && match) {
    selectedId = match.id;
    renderAll();
  }
});

setTheme(currentTheme);
loadDashboard();
syncBriefControls();
setActiveLayer(activeLayer);
