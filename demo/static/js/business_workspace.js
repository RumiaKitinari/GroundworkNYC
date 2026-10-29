let businessForecastResult = null;
let businessCharts = [];
let businessContextKey = null;
let businessRevision = 0;
let businessTimer = null;
const businessChecklistLabels = {
  property_visit: "Visit The Property", permitted_use: "Confirm Permitted Use",
  kitchen_ventilation: "Review Kitchen & Ventilation", permits_licenses: "Review Permits & Licenses",
  funding: "Confirm Funding", cost_review: "Review Costs With An Adviser"
};

function businessCsvCell(value) {
  const text = typeof value === "string" ? value.replace(/^[=+@\-\t\r]/, "'$&") : String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function clearBusinessCharts() {
  businessCharts.forEach(chart => chart.destroy()); businessCharts = [];
}

function renderBusinessChecklist() {
  const checklist = currentPlan().checklist || {};
  document.querySelector("#businessChecklistCount").textContent = `${Object.values(businessChecklistLabels).filter((_, i) => checklist[Object.keys(businessChecklistLabels)[i]]).length} / 6 Complete`;
  document.querySelector("#businessChecklist").innerHTML = Object.entries(businessChecklistLabels).map(([key, label]) =>
    `<label><input type="checkbox" data-business-check="${key}" ${checklist[key] ? "checked" : ""} />${label}</label>`).join("");
}

function renderBusinessForecast(result) {
  clearBusinessCharts();
  if (!result) return;
  const baseline = result.series[1], rows = baseline.rows.slice(1);
  const shortfall = baseline.first_shortfall_month === null ? "None Within Horizon" : `Month ${baseline.first_shortfall_month}`;
  document.querySelector("#businessPlanResults").innerHTML = `
    <div class="business-metrics">
      <div><span>Cash After Opening Costs</span><strong>${money(result.opening_after_startup)}</strong></div>
      <div><span>Ending Cash · Entered Volume</span><strong>${money(baseline.ending_cash)}</strong></div>
      <div><span>First Cash Shortfall</span><strong>${shortfall}</strong></div>
      <div><span>Additional Cash Required</span><strong>${money(baseline.additional_cash_needed)}</strong></div>
    </div>
    <div class="business-chart-grid"><section><h3>Cash Balance</h3><div class="business-chart"><canvas id="businessCashChart" role="img" aria-label="Month-end cash balance under three volume assumptions"></canvas></div></section>
    <section><h3>Monthly Cash In & Out</h3><div class="business-chart"><canvas id="businessFlowChart" role="img" aria-label="Monthly cash receipts and payments at entered volume"></canvas></div></section></div>
    ${result.series.some(series => series.capacity_capped) ? '<p class="planning-empty">Higher-Volume Scenarios Are Limited By Entered Capacity.</p>' : ""}
    <details class="planning-section"><summary>Monthly Detail · Entered Volume</summary><button type="button" class="quiet-action" id="businessExport">Export Cash Plan CSV</button><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>Month</th><th>Daily Guests</th><th>Cash In</th><th>Cash Out</th><th>Net Cash Flow</th><th>Cash Balance</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${row.month}</th><td>${displayNumber(row.average_daily_covers)}</td><td>${money(row.revenue)}</td><td>${money(row.cash_out)}</td><td>${money(row.net_cash_flow)}</td><td>${money(row.cash_balance)}</td></tr>`).join("")}</tbody></table></div></details>
    <details class="planning-section"><summary>Assumptions & Exclusions</summary><p>User-entered volume and costs; not a prediction of customer demand or profit.</p><ul>${result.assumptions.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul><p>Fixed costs include ${money(result.inputs.monthly_rent)} rent and ${money(result.inputs.monthly_fixed)} other monthly costs. Owner draw is included separately. Property purchase prices and financing are not added automatically.</p></details>`;
  const ink = getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || (currentTheme === "dark" ? "#dce6ee" : "#273c4a");
  const options = {responsive: true, maintainAspectRatio: false, plugins: {legend: {labels: {color: ink}}, tooltip: {callbacks: {label: context => `${context.dataset.label}: ${money(context.parsed.y)}`}}}, scales: {x: {ticks: {color: ink}, title: {display: true, text: "Month", color: ink}}, y: {beginAtZero: true, ticks: {color: ink, callback: value => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1}).format(value)}}}};
  businessCharts.push(new Chart(document.querySelector("#businessCashChart"), {type: "line", data: {
    labels: baseline.rows.map(row => row.month), datasets: result.series.map((series, i) => ({label: series.label, data: series.rows.map(row => row.cash_balance), borderColor: ["#cb6262", "#168a88", "#4a85cf"][i], borderWidth: 2, pointRadius: 2, tension: 0}))
      .concat([{label: "Zero Cash", data: baseline.rows.map(() => 0), borderColor: "#85949f", borderDash: [5, 5], pointRadius: 0, borderWidth: 1}])}, options}));
  businessCharts.push(new Chart(document.querySelector("#businessFlowChart"), {type: "bar", data: {labels: rows.map(row => row.month), datasets: [
    {label: "Cash In", data: rows.map(row => row.revenue), backgroundColor: "#168a88"},
    {label: "Cash Out", data: rows.map(row => row.cash_out), backgroundColor: "#c18a53"}]}, options}));
}

async function calculateBusinessPlan() {
  const revision = ++businessRevision, key = planKey();
  const form = document.querySelector("#businessPlanForm"), status = document.querySelector("#businessPlanStatus");
  clearBusinessCharts(); businessForecastResult = null;
  document.querySelector("#businessPlanResults").innerHTML = "";
  if (!form.checkValidity()) { status.textContent = "Enter Valid Planning Assumptions."; return; }
  const assumptions = Object.fromEntries(new FormData(form)), plan = currentPlan();
  const operating = assumptions.scenario_name ? plan.scenarios[assumptions.scenario_name] : plan.draft;
  if (!operating || !Object.keys(operating).length) {
    status.innerHTML = 'No Operating Assumptions Saved. <button type="button" class="quiet-action" data-business-economics>Open Economics</button>'; return;
  }
  status.textContent = "Calculating Cash Plan...";
  try {
    const response = await fetch("/api/planning/forecast", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({operating, assumptions})});
    const result = await response.json();
    if (revision !== businessRevision || key !== planKey() || activeView !== "workspace") return;
    if (!response.ok) throw new Error(result.error || "Cash Plan Unavailable.");
    businessForecastResult = result;
    const latest = currentPlan(); latest.planning_inputs = result.planning_inputs;
    status.textContent = savePlan(latest) ? "User-Assumed Scenario · Month-End Cash" : "Calculated · Unable To Save This Plan";
    renderBusinessForecast(result);
  } catch (error) { if (revision === businessRevision) status.textContent = error.message; }
}

function prepareBusinessWorkspace() {
  const plan = currentPlan(), form = document.querySelector("#businessPlanForm");
  const saved = plan.planning_inputs || {};
  const changed = businessContextKey !== planKey();
  if (changed) {
    businessContextKey = planKey(); form.reset();
    Object.entries(saved).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
  }
  const choice = changed ? saved.scenario_name || "" : form.elements.scenario_name.value;
  const names = Object.keys(plan.scenarios || {});
  form.elements.scenario_name.innerHTML = '<option value="">Current Economics Draft</option>' + names.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("") +
    (choice && !names.includes(choice) ? `<option value="${escapeHtml(choice)}">${escapeHtml(choice)} · Unavailable</option>` : "");
  form.elements.scenario_name.value = choice;
  const basket = basketSummary(plan);
  document.querySelector("#businessPlanContext").innerHTML = `<strong>${escapeHtml(state.conceptName || "Restaurant Plan")}</strong><div class="business-context-actions"><span>${savedMenu.length} Menu Items · ${plan.property_ids.length} Saved Properties${basket.priced ? ` · ${money(basket.price)} Guest Basket` : ""}</span><button type="button" class="quiet-action" data-business-economics>Economics</button><button type="button" class="quiet-action" data-business-menu>Menu Studio</button></div>`;
  renderBusinessChecklist(); calculateBusinessPlan();
}

function initializeBusinessWorkspace() {
  document.querySelector("#businessPlanForm").addEventListener("submit", event => { event.preventDefault(); clearTimeout(businessTimer); calculateBusinessPlan(); });
  document.querySelector("#businessPlanForm").addEventListener("input", () => {
    ++businessRevision; clearTimeout(businessTimer); businessForecastResult = null; clearBusinessCharts();
    document.querySelector("#businessPlanResults").innerHTML = "";
    document.querySelector("#businessPlanStatus").textContent = "Updating Assumptions...";
    businessTimer = setTimeout(calculateBusinessPlan, 400);
  });
  document.querySelector("[data-panel='workspace']").addEventListener("click", event => {
    if (event.target.closest("[data-business-economics]")) selectView("finance");
    if (event.target.closest("[data-business-menu]")) selectView("menu");
    if (event.target.closest("#businessExport") && businessForecastResult) {
      const result = businessForecastResult, plan = result.planning_inputs;
      const rows = [["volume_case", "month", "daily_guests", "cash_in_usd", "cash_out_usd", "net_cash_flow_usd", "cash_balance_usd", "starting_cash_usd", "opening_costs_usd", "owner_draw_usd_month", "month_one_volume_pct", "ramp_months", "operating_scenario", "assessment_type"],
        ...result.series.flatMap(series => series.rows.map(row => [series.label, row.month, row.average_daily_covers, row.revenue, row.cash_out, row.net_cash_flow, row.cash_balance, plan.opening_cash, plan.startup_cost, plan.owner_draw, plan.ramp_start_pct, plan.ramp_months, plan.scenario_name || "Current Economics Draft", result.assessment_type]))];
      const url = URL.createObjectURL(new Blob([rows.map(row => row.map(businessCsvCell).join(",")).join("\r\n") + "\r\n"], {type: "text/csv;charset=utf-8"}));
      const link = document.createElement("a"); link.href = url; link.download = "groundwork-cash-plan.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
  document.querySelector("#businessChecklist").addEventListener("change", event => {
    const key = event.target.dataset.businessCheck; if (!key) return;
    const plan = currentPlan(); plan.checklist = {...plan.checklist, [key]: event.target.checked}; savePlan(plan); renderBusinessChecklist();
  });
}
