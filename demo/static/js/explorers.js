// Selectively ported from origin/main d1005ee; existing Otis workflows are preserved.
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
const explorerCompetitionCache = new Map();
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

let explorerContext = "";
let explorerOwner;

function persistDashboardView() {
  const value = {profileComparisonId, profileExpanded, transitExpanded, competitionFilter,
    competitionBreakdownOpen, competitionComparisonOpen, storefrontArea, storefrontVacancy};
  try { localStorage.setItem(`groundwork-explorer-view:${accountOwner || "guest"}`,JSON.stringify(value)); } catch { /* View preferences are optional. */ }
}

function renderModelOutputSummary() {
  const target=document.querySelector("#modelOutputSummary");
  const prediction=selectedLocation().survival;
  const usable=prediction?.status === "available" && Number.isFinite(prediction.probability);
  target.hidden=!usable;
  target.innerHTML=usable ? `<div class="view-heading"><h3>${prediction.source_type === "atharv_tract_export" ? "Archive-Proxy Survival Estimate" : "Experimental Survival Estimate"}</h3><strong>${(prediction.probability*100).toFixed(1)}%</strong></div><small>Three-Year Horizon · ${escapeHtml(prediction.model_version)} · ${prediction.source_type === "atharv_tract_export" ? "Archive Disappearance Proxy; Not Verified Closure" : "Research Estimate; Not A Verified Success Forecast"}</small>` : "";
}

function renderTeamExplorers() {
  if (!dashboard) return;
  if (explorerOwner !== accountOwner) {
    explorerOwner=accountOwner;
    const saved=storedObject(`groundwork-explorer-view:${accountOwner || "guest"}`) || {};
    if (typeof saved.profileComparisonId === "string" && /^\d{11}$/.test(saved.profileComparisonId)) profileComparisonId=saved.profileComparisonId;
    for (const [key,value] of Object.entries(saved.profileExpanded || {})) if (key in profileExpanded && typeof value === "boolean") profileExpanded[key]=value;
    for (const [key,value] of Object.entries(saved.transitExpanded || {})) if (key in transitExpanded && typeof value === "boolean") transitExpanded[key]=value;
  }
  const context=`${dashboard.meta.data_release}:${conceptParams()}`;
  if (context !== explorerContext) {
    explorerContext=context; profileCache.clear(); profileResolved.clear(); profileAreasPromise=null; profileAreasResolved=null;
    transitCache.clear();explorerCompetitionCache.clear();competitionResolved.clear();storefrontPromise=null;storefrontData=null;
    profileRenderId++;transitRenderId++;competitionRenderId++;
  }
  if (activeView === "scorecard") {
    renderModelOutputSummary();
    if (document.querySelector("#residentDetails").open) renderResidentWorkerProfile();
    if (document.querySelector("#transitDetails").open) renderTransitActivity();
  }
  if (activeView === "whitespace") {
    renderWhitespace(); profileAreas().then(renderCompetitionExplorer,renderCompetitionExplorer);
  }
  if (activeView === "lease" && document.querySelector("#storefrontResearch").open) renderStorefrontExplorer();
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelector("#residentDetails").addEventListener("toggle",event=>{if(event.target.open)renderResidentWorkerProfile();});
  document.querySelector("#transitDetails").addEventListener("toggle",event=>{if(event.target.open)renderTransitActivity();});
  document.querySelector("#storefrontResearch").addEventListener("toggle",event=>{if(event.target.open)renderStorefrontExplorer();});
});

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
      <label>Compare Area<select id="competitionCompareArea"><option value="">No Comparison</option>${(profileAreasResolved || []).filter(row=>row.geoid!==market.geoid).map(row=>`<option value="${row.geoid}" ${row.geoid===profileComparisonId ? "selected" : ""}>${escapeHtml(row.name)} · ${escapeHtml(row.borough)}</option>`).join("")}</select></label>
    </div>
    <p class="competition-source">${escapeHtml(market.source)} · Latest Inspection: ${escapeHtml(market.latest_inspection_date || "Unavailable")}</p>
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
  target.querySelector("#competitionCompareArea").addEventListener("change",event=>{profileComparisonId=event.target.value;persistDashboardView();renderCompetitionExplorer();});
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
  if (!explorerCompetitionCache.has(key)) {
    const generation = requestId;
    const request = fetch(`/api/locations/${encodeURIComponent(id)}/competition?cuisine=${encodeURIComponent(cuisine)}`)
      .then(response => {if (!response.ok) throw new Error("Restaurant records unavailable"); return response.json();})
      .then(result => {if (generation === requestId) competitionResolved.set(key, result); return result;})
      .catch(error => {if (generation === requestId) explorerCompetitionCache.delete(key); throw error;});
    explorerCompetitionCache.set(key, request);
  }
  return explorerCompetitionCache.get(key);
}

async function renderCompetitionExplorer() {
  const target = document.querySelector("#competitionExplorer");
  if (!target || !dashboard || activeView !== "whitespace") return;
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
        profileComparisonId !== comparisonId || activeView !== "whitespace") return;
    paintCompetitionExplorer(target, market, comparison);
  } catch (error) {
    if (renderId !== competitionRenderId || !target.isConnected || activeView !== "whitespace") return;
    target.innerHTML = '<div class="competition-error" role="alert">Restaurant records could not load. <button type="button" class="competition-more">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderCompetitionExplorer);
  }
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
      <div class="storefront-field"><span class="storefront-mobile-label">Reported Status</span><span class="storefront-status ${row.vacancy_status === "reported_vacant" ? "is-reported" : "is-unknown"}">${row.vacancy_status === "reported_vacant" ? "Reported Vacant" : row.vacancy_status === "reported_not_vacant" ? "Reported Not Vacant" : "Unknown"}</span></div>
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
      <label>Reported vacancy<select id="storefrontVacancy"><option value="all">All registry records</option><option value="reported_vacant">Reported Vacant</option><option value="reported_not_vacant">Reported Not Vacant</option>
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
  if (!target || !dashboard || activeView !== "lease" || !document.querySelector("#storefrontResearch").open) return;
  if (storefrontData) {paintStorefrontExplorer(target); return;}
  target.innerHTML = '<div class="storefront-loading" role="status">Loading Storefront Registry records…</div>';
  try {
    if (!storefrontPromise) storefrontPromise = fetch("/api/storefronts")
      .then(response => {if (!response.ok) throw new Error("Storefront Registry unavailable"); return response.json();})
      .catch(error => {storefrontPromise = null; throw error;});
    const data = await storefrontPromise;
    storefrontData = data;
    if (target.isConnected && activeView === "lease" && document.querySelector("#storefrontResearch").open) paintStorefrontExplorer(target);
  } catch (_) {
    if (!target.isConnected || activeView !== "lease" || !document.querySelector("#storefrontResearch").open) return;
    target.innerHTML = '<div class="storefront-error" role="alert">Storefront Registry records could not load. <button type="button">Retry</button></div>';
    target.querySelector("button").addEventListener("click", renderStorefrontExplorer);
  }
}
