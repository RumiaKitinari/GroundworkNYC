let dashboard = null;
let selectedId = null;
let activeLayer = "opportunity";
let activeView = "discover";

const state = {
  conceptName: "Modern Bistro",
  profile: "restaurant",
  rentCap: 18000,
  dealType: "lease",
  preferredArea: "",
};

const toneFor = {
  opportunity: ["#fb7185", "#fbbf24", "#34d399", "#2dd4bf"],
  activity: ["#64748b", "#f59e0b", "#fbbf24", "#fde68a"],
  whitespace: ["#64748b", "#818cf8", "#a78bfa", "#c4b5fd"],
  cost: ["#fb7185", "#fbbf24", "#86efac", "#34d399"],
};

const layerTitles = {
  opportunity: "NYC Score Surface",
  activity: "Demand Surface",
  whitespace: "Market Gap Surface",
  cost: "Property Fit Surface",
};

function fmtMoney(value) {
  if (!Number.isFinite(Number(value))) return "--";
  return `$${Math.round(value / 1000)}k`;
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
  return "Sit-Down Restaurant";
}

function scoreClass(value) {
  if (value >= 82) return "score-good";
  if (value >= 68) return "score-mid";
  return "score-low";
}

function colorFor(value, layer = activeLayer) {
  const colors = toneFor[layer] || toneFor.opportunity;
  if (value >= 86) return colors[3];
  if (value >= 76) return colors[2];
  if (value >= 62) return colors[1];
  return colors[0];
}

function setActiveLayer(layer) {
  activeLayer = layer;
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
  return location[activeLayer] ?? location.opportunity;
}

function rentDisplay(row) {
  return row.rent_label || fmtMoney(row.rent);
}

function conceptName() {
  return state.conceptName.trim() || "Restaurant Concept";
}

async function loadDashboard() {
  const params = new URLSearchParams({
    concept_name: conceptName(),
    profile: state.profile,
    rent_cap: String(state.rentCap),
    deal_type: state.dealType,
    borough: state.preferredArea,
  });
  const response = await fetch(`/api/dashboard?${params}`);
  dashboard = await response.json();
  selectedId = selectedId || dashboard.selected;
  if (!dashboard.locations.some((location) => location.id === selectedId)) {
    selectedId = dashboard.selected;
  }
  renderAll();
}

function selectedLocation() {
  return dashboard.locations.find((location) => location.id === selectedId) || dashboard.locations[0];
}

function renderMetrics() {
  const best = dashboard.locations[0];
  const metrics = [
    ["Concept", conceptName(), profileLabel(state.profile)],
    ["Top Score", best.opportunity, best.name],
    ["Evidence", dashboard.scoring.avg_confidence, "Coverage"],
    ["Search", dealLabel(state.dealType), state.preferredArea || "Open To NYC"],
    ["Break Even", fmtMoney(dashboard.finance.break_even_revenue), `${dashboard.finance.orders_per_day} Orders/Day`],
  ];

  document.querySelector("#metricRibbon").innerHTML = metrics.map(([label, value, sub]) => `
    <article class="metric">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div>
      <div class="metric-sub">${sub}</div>
    </article>
  `).join("");
}

function renderMap() {
  const layer = document.querySelector("#hexLayer");
  layer.innerHTML = dashboard.locations.map((location) => {
    const value = activeMetric(location);
    const active = location.id === selectedId ? " is-active" : "";
    return `
      <button
        class="hex-cell${active}"
        type="button"
        data-id="${location.id}"
        title="${location.name}"
        style="left:${location.x}%;top:${location.y}%;background:${colorFor(value)}"
      >${value}</button>
    `;
  }).join("");

  layer.querySelectorAll(".hex-cell").forEach((button) => {
    button.addEventListener("click", () => {
      selectedId = button.dataset.id;
      renderAll();
    });
  });
}

function renderIntel() {
  const location = selectedLocation();
  document.querySelector("#selectedName").textContent = location.name;
  const sqftLabel = location.sqft ? `${location.sqft.toLocaleString()} Sq Ft` : "Sq Ft Not In Source";
  document.querySelector("#selectedMeta").textContent = `${location.borough} - ${titleCase(location.archetype)} - ${sqftLabel}`;
  document.querySelector("#selectedScore").textContent = location.opportunity;
  document.querySelector("#scoreOrb").style.background = `conic-gradient(${colorFor(location.opportunity, "opportunity")} 0 ${location.opportunity}%, rgba(33,54,77,.95) ${location.opportunity}% 100%)`;
  document.querySelector("#confidencePill").textContent = `${titleCase(location.confidence)} Evidence`;

  document.querySelector("#barStack").innerHTML = location.score_components.map((component) => `
    <div class="bar-row">
      <div class="bar-line"><span>${component.label}</span><strong>${component.score}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${component.score}%;background:${colorFor(component.score, "opportunity")}"></div></div>
    </div>
  `).join("");

  const topSignals = [...location.score_components].sort((a, b) => b.score - a.score).slice(0, 4);
  document.querySelector("#driverList").innerHTML = topSignals.map((item) => `<li><span>${item.label}</span><strong>${item.score}</strong></li>`).join("");
}

function renderRanking() {
  const rows = dashboard.locations;
  document.querySelector("#rankingTable").innerHTML = `
    <div class="table-row header">
      <span>#</span><span>Location</span><span>Score</span><span>Conf</span><span>Demand</span><span>Gap</span><span>Econ</span><span>Rent</span>
    </div>
    ${rows.map((row, index) => `
      <div class="table-row" data-id="${row.id}">
        <button type="button">${index + 1}</button>
        <button class="place-name" type="button">${row.name}</button>
        <span class="${scoreClass(row.opportunity)}">${row.opportunity}</span>
        <span>${row.confidence_score}</span>
        <span>${row.score_components.find((item) => item.key === "demand").score}</span>
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
          <span>Weight ${component.weight}%</span>
          <div class="bar-track weight"><div class="bar-fill" style="width:${component.weight * 3.2}%;background:var(--blue)"></div></div>
        </div>
        <div>
          <span>Evidence ${component.coverage}%</span>
          <div class="bar-track evidence"><div class="bar-fill" style="width:${component.coverage}%;background:var(--cyan)"></div></div>
        </div>
      </div>
    </article>
  `).join("");

  document.querySelector("#scorecardBoard").innerHTML = `
    <section class="scorecard-hero">
      <div>
        <span class="card-status">Selected Location</span>
        <h3>${conceptName()} · ${location.name}</h3>
        <p>${location.recommendation}</p>
      </div>
      <div class="scorecard-orbs">
        <div><strong>${location.opportunity}</strong><span>Score</span></div>
        <div><strong>${location.confidence_score}</strong><span>Confidence</span></div>
      </div>
    </section>
    <section class="scorecard-layout">
      <div class="component-grid">${components}</div>
      <aside class="risk-panel">
        <h3>Decision Notes</h3>
        <ul>${risks}</ul>
        <div class="kv"><span>Concept Fit</span><strong>${titleCase(location.archetype)}</strong></div>
        <div class="kv"><span>Asking Rent</span><strong>${rentDisplay(location)}</strong></div>
        <div class="kv"><span>Budget Scenario</span><strong>${fmtMoney(dashboard.finance.rent_cap)}/Month</strong></div>
      </aside>
    </section>
  `;
}

function renderFeeds() {
  const statusLabel = {
    mapped: "Live",
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
      <div class="kv"><span>Confidence</span><strong>${row.confidence_score}</strong></div>
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
      <span class="card-status">${titleCase(row.confidence)} Confidence</span>
      <h3>${row.name}</h3>
      <div class="score-line">
        <strong class="${scoreClass(row.opportunity)}">${row.opportunity}</strong>
        <span>${row.borough} - ${rentDisplay(row)} Rent</span>
      </div>
      <div class="kv"><span>Customer Fit</span><strong>${row.customer}</strong></div>
      <div class="kv"><span>Foot Traffic</span><strong>${row.activity}</strong></div>
      <div class="kv"><span>Transit</span><strong>${row.transit}</strong></div>
      <div class="kv"><span>Market Gap</span><strong>${row.whitespace}</strong></div>
      <div class="kv"><span>Competition</span><strong>${row.competition}</strong></div>
      <div class="kv"><span>Cost Fit</span><strong>${row.cost}</strong></div>
    </article>
  `).join("");
}

function renderLease() {
  let candidates = dashboard.properties || [];
  if (state.preferredArea) {
    candidates = candidates.filter((row) => row.borough === state.preferredArea);
  }
  if (!candidates.length) {
    document.querySelector("#leaseBoard").innerHTML = `
      <article class="property-empty">
        <h3>No Matching Properties Available</h3>
        <p>Adjust The Search Type Or Preferred Area To Expand Available Property Matches.</p>
      </article>
    `;
    return;
  }

  document.querySelector("#leaseBoard").innerHTML = candidates.map((row) => {
    const priceLine = row.price_label || (row.transaction === "purchase" ? fmtPrice(row.asking_price) : `${fmtMoney(row.asking_rent)}/Month`);
    const basisLine = row.monthly_basis_label || (row.transaction === "purchase" ? `${fmtMoney(row.monthly_basis)}/Month Estimated Carrying Cost` : `${fmtMoney(row.monthly_basis)}/Month Lease Basis`);
    const imageClass = row.image ? "property-image" : "property-image no-image";
    const imageStyle = row.image ? ` style="background-image:url('${row.image}')"` : "";
    const badge = row.transaction_label || (row.transaction === "purchase" ? "For Purchase" : "For Lease");
    const sqft = row.sqft ? `${row.sqft.toLocaleString()} Sq Ft` : (row.sqft_label || "Sq Ft Not In Source");
    return `
      <article class="property-card">
        <div class="${imageClass}"${imageStyle}>
          <span>${badge}</span>
          ${row.image ? "" : `<strong>${row.image_label || "Listing Photo Not In Source"}</strong>`}
        </div>
        <div class="property-body">
          <div class="property-title">
            <div>
              <h3>${row.title}</h3>
              <p>${row.address}</p>
            </div>
            <strong class="${scoreClass(row.fit_score)}">${row.fit_score}</strong>
          </div>
          <div class="property-specs">
            <span>${row.location_name}</span>
            <span>${sqft}</span>
            <span>${titleCase(row.frontage)}</span>
          </div>
          <div class="kv"><span>${row.transaction === "purchase" ? "Asking Price" : "Asking Rent"}</span><strong>${priceLine}</strong></div>
          <div class="kv"><span>Budget Basis</span><strong>${basisLine}</strong></div>
          <div class="kv"><span>Condition</span><strong>${titleCase(row.condition)}</strong></div>
        </div>
      </article>
    `;
  }).join("");
}

function renderWhitespace() {
  document.querySelector("#gapBoard").innerHTML = dashboard.whitespace.map((row) => `
    <div class="gap-row">
      <strong>${row.category}</strong>
      <span>${row.current_label || `Current ${row.current}`}</span>
      <span>${row.expected_label || `Expected ${row.expected}`}</span>
      <span>${row.gap_label || `Gap ${row.gap > 0 ? "+" : ""}${row.gap}`}</span>
      <span class="${scoreClass(row.score)}">${row.score}</span>
    </div>
  `).join("");
}

function renderFinance() {
  const finance = dashboard.finance;
  const cells = [
    ["Break-Even Revenue", fmtMoney(finance.break_even_revenue), "Monthly Target"],
    ["Required Orders", `${finance.orders_per_day}/Day`, "$28 Average Ticket"],
    ["Cash Runway", `${finance.runway_months} Months`, "Fixed-Cost Scenario"],
    ["Capture Rate", finance.capture_rate, "Estimated Range"],
  ];
  document.querySelector("#financeBoard").innerHTML = cells.map(([label, value, sub]) => `
    <article class="finance-cell">
      <h3>${label}</h3>
      <div class="kv"><span>Estimate</span><strong>${value}</strong></div>
      <div class="kv"><span>Basis</span><strong>${titleCase(sub)}</strong></div>
    </article>
  `).join("");
}

function renderNow() {
  document.querySelector("#nowBoard").innerHTML = dashboard.vendor_windows.map((row) => `
    <article class="now-card">
      <h3>${titleCase(row.concept)}</h3>
      <div class="kv"><span>Window</span><strong>${row.window}</strong></div>
      <div class="kv"><span>Demand</span><strong>${row.demand}</strong></div>
      <div class="kv"><span>Eligibility</span><strong>${titleCase(row.eligibility)}</strong></div>
      <div class="kv"><span>Signal</span><strong>${titleCase(row.note)}</strong></div>
    </article>
  `).join("");
}

function renderReports() {
  document.querySelector("#reportBoard").innerHTML = dashboard.reports.map((row) => `
    <article class="report-card">
      <span class="card-status">${titleCase(row.status)}</span>
      <h3>${row.name}</h3>
      <div class="kv"><span>Audience</span><strong>${titleCase(row.audience)}</strong></div>
      <div class="kv"><span>Includes</span><strong>${titleCase(row.includes)}</strong></div>
      <button class="quiet-action" type="button">Preview Export</button>
    </article>
  `).join("");
}

function renderDataLayers() {
  const signals = Object.values(dashboard.scoring.signals);
  document.querySelector("#layerBoard").innerHTML = signals.map((row) => `
    <article class="layer-card">
      <span class="card-status">${row.coverage}% Evidence</span>
      <h3>${row.label}</h3>
      <div class="feed-meter"><span style="width:${row.coverage}%"></span></div>
      <div class="kv"><span>Status</span><strong>${row.coverage >= 80 ? "Strong" : row.coverage >= 68 ? "Decision-Ready" : "Developing"}</strong></div>
    </article>
  `).join("");
}

function renderPanels() {
  document.querySelector(".workspace")?.classList.toggle("is-discover", activeView === "discover");
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("is-hidden", panel.dataset.panel !== activeView);
  });
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

document.querySelector("#conceptInput").addEventListener("change", (event) => {
  state.conceptName = event.target.value.trim() || "Restaurant Concept";
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#dealSelect").addEventListener("change", (event) => {
  state.dealType = event.target.value;
  syncBriefControls();
  loadDashboard();
});

document.querySelector("#profileSelect").addEventListener("change", (event) => {
  state.profile = event.target.value;
  selectedId = null;
  syncBriefControls();
  loadDashboard();
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

document.querySelector("#briefSkip").addEventListener("click", () => {
  closeBrief();
});

document.querySelector("#briefEditButton").addEventListener("click", () => {
  openBrief();
});

document.querySelector("#refreshButton").addEventListener("click", () => {
  loadDashboard();
});

document.querySelector("#searchInput").addEventListener("input", (event) => {
  if (!dashboard) return;
  const query = event.target.value.trim().toLowerCase();
  const match = dashboard.locations.find((row) => row.name.toLowerCase().includes(query) || row.borough.toLowerCase().includes(query));
  if (query && match) {
    selectedId = match.id;
    renderAll();
  }
});

loadDashboard();
syncBriefControls();
setActiveLayer(activeLayer);
