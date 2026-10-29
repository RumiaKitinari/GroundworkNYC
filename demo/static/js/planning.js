/* Concept-scoped plans use the existing private, revisioned account workspace. */
let scenarioComparisonChart = null;
let scenarioComparisonRevision = 0;

function reconcileWorkspace(base, remote, local) {
  // Three-way comparison preserves remote-only edits and intentional local deletions.
  const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  if (same(local, base)) return remote;
  if (same(remote, base) || same(remote, local)) return local;
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  if (object(remote) && object(local) && (object(base) || base === undefined)) {
    const keys = new Set([...Object.keys(base || {}), ...Object.keys(remote), ...Object.keys(local)]);
    return Object.fromEntries([...keys].map(key => [key, reconcileWorkspace(base?.[key], remote[key], local[key])]).filter(([, value]) => value !== undefined));
  }
  return local;
}

function planKey() {
  const prefix = "groundwork-menu-v2:";
  return prefix + JSON.stringify([...JSON.parse(menuKey().slice(prefix.length)), state.dealType]);
}

function currentPlan() {
  const plans = storedObject(`groundwork-plans:${accountOwner || "guest"}`) || {};
  return {property_ids: [], scenarios: {}, draft: {}, basket: {}, menu_details: {}, ...plans[planKey()]};
}

function savePlan(plan) {
  const key = `groundwork-plans:${accountOwner || "guest"}`;
  const plans = storedObject(key) || {};
  if (!plans[planKey()] && Object.keys(plans).length >= 50) {
    workspaceStatus("Workspace Limit Reached: Export Or Remove An Older Plan.");
    return false;
  }
  plans[planKey()] = plan;
  try { localStorage.setItem(key, JSON.stringify(plans)); queueWorkspaceSync(); return true; }
  catch { workspaceStatus("Storage Unavailable: Export Your Work Before Leaving."); return false; }
}

function openPlanProperty(id) {
  const property = (dashboard.properties || []).find(row => row.id === id);
  if (!property) return;
  selectedPropertyId = id; selectedId = property.location_id;
  const plan = currentPlan(); plan.selected_property_id = id; savePlan(plan);
  mapInventory = "properties"; document.querySelector("#mapInventorySelect").value = "properties";
  if (isHexLayer()) setActiveLayer("opportunity");
  renderAll(); selectView("discover");
  if (property.latitude && property.longitude) locationMap.flyTo({center: [+property.longitude, +property.latitude], zoom: 15});
}

function renderPropertyShortlist() {
  let board = document.querySelector("#propertyShortlist");
  if (!board) {
    board = document.createElement("section"); board.id = "propertyShortlist"; board.className = "planning-section";
    document.querySelector("#leaseBoard").before(board);
  }
  const ids = currentPlan().property_ids;
  board.innerHTML = `<div class="view-heading"><h3>Property Shortlist</h3><span>${ids.length} / 4 Saved</span></div>` + (ids.length ?
    `<div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>Property</th><th>Price</th><th>Area</th><th>Kitchen</th><th>Access</th><th>Area Score</th><th>Actions</th></tr></thead><tbody>${ids.map(id => {
      const row = dashboard.properties.find(item => item.id === id);
      return `<tr><th scope="row">${escapeHtml(row?.address || id)}<small>${row ? row.lead_type === "synthetic" ? "Synthetic Scenario" : "Source-Reported Record" : "Outside Current Search"}</small></th><td>${escapeHtml(row?.price_label || "Unavailable")}</td><td>${row?.sqft ? `${displayNumber(row.sqft)} SF` : "Unavailable"}</td><td>${escapeHtml(row?.kitchen_status || "Unavailable")}</td><td>${row?.customer_access?.index ?? "Unavailable"}</td><td>${row?.fit_score ?? "Unavailable"}</td><td>${row ? `<button type="button" class="quiet-action" data-open-property="${escapeHtml(id)}">Open</button>` : ""}<button type="button" class="quiet-action" data-save-property="${escapeHtml(id)}" aria-label="Remove Saved Property ${escapeHtml(id)}">Remove</button></td></tr>`;
    }).join("")}</tbody></table></div>` : '<p class="planning-empty">No Saved Properties</p>');
  document.querySelectorAll("[data-save-property]").forEach(button => {
    if (!ids.includes(button.dataset.saveProperty) && ids.length >= 4) button.disabled = true;
  });
}

function rememberPropertySelection() {
  if (!dashboard || !selectedPropertyId) return;
  const plan = currentPlan();
  if (plan.selected_property_id !== selectedPropertyId) { plan.selected_property_id = selectedPropertyId; savePlan(plan); }
}

function basketSummary(plan = currentPlan()) {
  syncSavedMenu();
  const items = savedMenu.filter(item => (plan.basket[item.id] || 0) > 0);
  const quantity = items.reduce((sum, item) => sum + plan.basket[item.id], 0);
  const priced = items.length > 0 && items.every(item => Number(item.price) > 0);
  const costed = items.length > 0 && items.every(item => item.cost !== "" && item.cost != null && Number.isFinite(Number(item.cost)));
  return {items, quantity, priced, costed,
    price: items.reduce((sum, item) => sum + Number(item.price || 0) * plan.basket[item.id], 0),
    cost: items.reduce((sum, item) => sum + Number(item.cost || 0) * plan.basket[item.id], 0)};
}

function renderMenuPlanning() {
  const board = document.querySelector("#menuPlanning");
  const plan = currentPlan(), basket = basketSummary(plan);
  const ingredientCounts = new Map();
  for (const item of savedMenu) {
    const ingredients = new Set((plan.menu_details[item.id]?.ingredients || "").split(",").map(value => value.trim().toLowerCase()).filter(Boolean));
    for (const ingredient of ingredients) ingredientCounts.set(ingredient, (ingredientCounts.get(ingredient) || 0) + 1);
  }
  const shared = [...ingredientCounts].filter(([, count]) => count > 1).sort((a,b) => b[1]-a[1]);
  board.innerHTML = `<div class="view-heading"><h3>Menu Composition</h3><span>${savedMenu.filter(item => plan.menu_details[item.id]?.complexity === "complex").length} Complex Dishes</span></div>
    <div class="section-balance">${menuSections.map(section => { const count = savedMenu.filter(item => item.section === section).length;
      return `<div><span>${section}</span><meter min="0" max="${Math.max(1,savedMenu.length)}" value="${count}" aria-label="${section} Share"></meter><b>${count}</b></div>`; }).join("")}</div>
    <details><summary>Ingredients & Preparation</summary><div class="planning-item-grid">${savedMenu.map(item => {
      const detail = plan.menu_details[item.id] || {};
      return `<div><strong>${escapeHtml(item.name)}</strong><label>Ingredients<input data-plan-ingredients="${escapeHtml(item.id)}" maxlength="300" value="${escapeHtml(detail.ingredients || "")}" placeholder="Tomato, basil, olive oil" /></label><label>Preparation<select data-plan-complexity="${escapeHtml(item.id)}">${["simple","standard","complex"].map(value => `<option value="${value}" ${value === (detail.complexity || "standard") ? "selected" : ""}>${titleCase(value)}</option>`).join("")}</select></label></div>`;
    }).join("") || '<p class="planning-empty">No Dishes Added</p>'}</div><p>Shared Ingredients: ${shared.length ? shared.map(([name,count]) => `${escapeHtml(name)} (${count})`).join(" · ") : "None Recorded"}</p></details>
    <details><summary>Guest Basket · ${basket.priced ? money(basket.price) : "Not Priced"}</summary><div class="planning-basket">${savedMenu.map(item => `<label><span>${escapeHtml(item.name)}</span><input data-basket-qty="${escapeHtml(item.id)}" type="number" min="0" max="10" step="1" value="${plan.basket[item.id] || 0}" aria-label="${escapeHtml(item.name)} Portions Per Guest" /></label>`).join("")}</div><div class="kv"><span>Spend Per Guest</span><strong>${basket.priced ? money(basket.price) : "Prices Required"}</strong></div><div class="kv"><span>Ingredient Cost Per Guest</span><strong>${basket.costed ? money(basket.cost) : "Costs Required"}</strong></div><button type="button" class="quiet-action" data-use-menu-basket ${!basket.priced || basket.price > 1000 ? "disabled" : ""}>Use Basket In Economics</button></details>`;
}

function useMenuBasket() {
  const basket = basketSummary();
  if (!basket.priced || basket.price > 1000) return;
  selectView("finance"); prepareEconomicsLab();
  const form = document.querySelector("#economicsLabForm");
  form.elements.price.value = basket.price.toFixed(2);
  // Ingredient cost is not the complete variable cost; preserve the user's operating assumption.
  document.querySelector("#economicsStatus").textContent = "Menu Spend Applied. Review Variable Costs Including Labor And Packaging.";
  calculateEconomics();
}

async function renderScenarioLibrary() {
  const board = document.querySelector("#scenarioLibrary");
  const entries = Object.entries(currentPlan().scenarios);
  board.innerHTML = entries.length ? `<div class="planning-scenarios">${entries.map(([name]) => `<div><strong>${escapeHtml(name)}</strong><button type="button" class="quiet-action" data-load-scenario="${escapeHtml(name)}">Load</button><button type="button" class="quiet-action" data-remove-scenario="${escapeHtml(name)}" aria-label="Remove ${escapeHtml(name)} Scenario">Remove</button></div>`).join("")}</div>` : '<p class="planning-empty">No Saved Scenarios</p>';
  document.querySelector("#economicsUseBasket").disabled = !basketSummary().priced;
  const revision = ++scenarioComparisonRevision;
  scenarioComparisonChart?.destroy(); scenarioComparisonChart = null;
  document.querySelector("#scenarioComparisonWrap").hidden = true;
  if (!entries.length) return;
  try {
    const results = await Promise.all(entries.map(async ([name,inputs]) => {
      const response = await fetch(`/api/economics/scenario?${new URLSearchParams(inputs)}`);
      if (!response.ok) throw new Error("Saved Scenario Unavailable");
      return {name, result: await response.json()};
    }));
    if (revision !== scenarioComparisonRevision) return;
    const colors = ["#246da5", "#15836e", "#bb7b17", "#b0609e"];
    board.insertAdjacentHTML("beforeend", `<div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>Scenario</th><th>Daily Profit</th><th>Break-Even Covers</th><th>Capacity</th><th>Loss At Expected Volume</th></tr></thead><tbody>${results.map(({name,result}) => `<tr><th scope="row">${escapeHtml(name)}</th><td>${money(result.current_daily_profit)}</td><td>${result.break_even_covers ?? "Not Feasible"}</td><td>${Math.round(result.capacity_utilization*100)}%</td><td>${result.current_daily_profit < 0 ? "Yes" : "No"}</td></tr>`).join("")}</tbody></table></div>`);
    document.querySelector("#scenarioComparisonWrap").hidden = false;
    scenarioComparisonChart = new Chart(document.querySelector("#scenarioComparison"), {type:"line",data:{datasets:results.map(({name,result},index) => ({label:name,data:result.volume_curve.map(row=>({x:row.covers,y:row.profit})),borderColor:colors[index%colors.length],borderWidth:2,pointRadius:0}))},options:{responsive:true,maintainAspectRatio:false,animation:false,scales:{x:{type:"linear",title:{display:true,text:"Daily Covers"}},y:{title:{display:true,text:"Operating Profit ($ / Day)"}}}}});
  } catch { if (revision === scenarioComparisonRevision) board.insertAdjacentHTML("beforeend", '<p role="status">Scenario Comparison Unavailable. Reload A Saved Scenario To Retry.</p>'); }
}

function renderPlanReport() {
  const report = document.querySelector(".location-report");
  if (!report) return;
  syncSavedMenu();
  const plan = currentPlan();
  const basket = basketSummary(plan);
  const properties = plan.property_ids.map(id => dashboard.properties.find(row => row.id === id));
  report.insertAdjacentHTML("beforeend", `<section class="report-plan"><h3>Property Alternatives</h3>${plan.property_ids.length ? plan.property_ids.map((id,index) => { const row=properties[index]; return `<div class="kv"><span>${escapeHtml(row?.address || id)}</span><strong>${escapeHtml(row?.price_label || "Outside Current Search")}</strong></div>`; }).join("") : '<p>No Saved Property Alternatives</p>'}
    <h3>Menu Plan</h3>${savedMenu.length ? `<table class="comparison-table"><thead><tr><th>Dish</th><th>Section</th><th>Price</th><th>Ingredient Cost</th></tr></thead><tbody>${savedMenu.map(item=>`<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.section)}</td><td>${Number(item.price)>0 ? money(item.price) : "Unavailable"}</td><td>${item.cost !== "" && item.cost != null ? money(item.cost) : "Unavailable"}</td></tr>`).join("")}</tbody></table>` : '<p>No Menu Saved</p>'}
    <p>Guest Basket: ${basket.priced ? `${money(basket.price)} / Guest` : "Not Configured"}</p>
    <h3>Operating Assumptions</h3>${Object.entries(plan.draft).map(([name,value])=>`<div class="kv"><span>${escapeHtml(titleCase(name.replaceAll("_"," ")))}</span><strong>${escapeHtml(value)}</strong></div>`).join("") || '<p>No Financial Scenario Saved</p>'}
    <div id="reportScenarioResults" aria-live="polite"></div><h3>Outstanding Checks</h3><ul><li>Confirm property availability, permitted use and occupancy costs.</li><li>Verify kitchen, ventilation, accessibility and licensing requirements.</li><li>Validate demand assumptions and full operating costs.</li></ul><p>Integrated Release: ${escapeHtml(dashboard.meta.data_release || "Unavailable")}. Synthetic properties are scenarios, not verified offers. Financial results use user assumptions, not estimated restaurant demand.</p></section>`);
  const reportContext = menuKey();
  const entries = Object.entries(plan.scenarios);
  if (Object.keys(plan.draft).length) entries.unshift(["Current Draft",plan.draft]);
  const print = document.querySelector("#printReport");
  print.disabled = entries.length > 0;
  Promise.all(entries.map(async ([name,inputs]) => { const response = await fetch(`/api/economics/scenario?${new URLSearchParams(inputs)}`); if (!response.ok) throw new Error(); return [name,await response.json()]; })).then(results => {
    if (menuKey() !== reportContext || !report.isConnected) return;
    const target = report.querySelector("#reportScenarioResults");
    target.innerHTML = results.length ? `<h3>Scenario Results</h3>${results.map(([name,result])=>`<div class="kv"><span>${escapeHtml(name)}</span><strong>${money(result.current_daily_profit)} / Day · Break-Even ${result.break_even_covers ?? "Not Feasible"}</strong></div>`).join("")}<h4>Daily Profit By Volume</h4><div class="report-profit-plot">${results[0][1].volume_curve.filter((_,index)=>index%10===0).map(row=>`<div><span>${Math.round(row.covers)} Covers</span><meter min="${Math.min(...results[0][1].volume_curve.map(row=>row.profit))-1}" max="${Math.max(...results[0][1].volume_curve.map(row=>row.profit))+1}" value="${row.profit}" aria-label="Profit At ${row.covers} Covers"></meter><strong>${money(row.profit)}</strong></div>`).join("")}</div>` : "";
    print.disabled = false;
  }).catch(()=> { if (report.isConnected) { report.querySelector("#reportScenarioResults").textContent="Financial Results Unavailable"; print.disabled=false; } });
}

function initializePlanningControls() {
  const settings = document.querySelector('[data-panel="settings"]');
  const profile = storedObject(`groundwork-profile:${accountOwner || "guest"}`) || {};
  settings.insertAdjacentHTML("beforeend", `<section class="planning-section"><h3>Business Profile</h3><form id="businessProfileForm" class="planning-toolbar"><label>Your Name<input name="display_name" maxlength="100" value="${escapeHtml(profile.display_name || "")}" autocomplete="name" /></label><label>Company<input name="company" maxlength="100" value="${escapeHtml(profile.company || "")}" autocomplete="organization" /></label><button class="quiet-action" type="submit">Save Profile</button></form><p id="profileStatus" role="status">${accountOwner ? "Private Account Workspace" : "Guest Workspace · This Device Only"}</p></section>`);
  document.querySelector("#businessProfileForm").addEventListener("submit", event=> {
    event.preventDefault(); localStorage.setItem(`groundwork-profile:${accountOwner || "guest"}`, JSON.stringify(Object.fromEntries(new FormData(event.target)))); queueWorkspaceSync();
    document.querySelector("#profileStatus").textContent = accountOwner ? "Profile Updated" : "Profile Saved On This Device";
  });
  document.querySelector("#saveScenarioForm").addEventListener("submit", event=> {
    event.preventDefault(); if (!economicsResult || !document.querySelector("#economicsLabForm").reportValidity()) return;
    const values=Object.fromEntries(new FormData(document.querySelector("#economicsLabForm")));
    if (Object.entries(values).some(([key,value])=>Number(value)!==economicsResult.inputs[key])) {
      document.querySelector("#economicsStatus").textContent="Calculate Valid Scenario Inputs Before Saving."; return;
    }
    const name = document.querySelector("#scenarioName").value.trim(); if (!name) return;
    const plan=currentPlan(); if (!plan.scenarios[name] && Object.keys(plan.scenarios).length>=12) { workspaceStatus("Maximum 12 Scenarios Per Concept"); return; }
    plan.scenarios[name]=values; savePlan(plan); renderScenarioLibrary();
  });
  document.querySelector("#economicsUseBasket").addEventListener("click", useMenuBasket);
  document.addEventListener("click", event=> {
    const save=event.target.closest("[data-save-property]");
    if (save) { const plan=currentPlan(), id=save.dataset.saveProperty; if (plan.property_ids.includes(id)) plan.property_ids=plan.property_ids.filter(value=>value!==id); else if (plan.property_ids.length<4) plan.property_ids.push(id); savePlan(plan); renderLease(); renderReports(); }
    const open=event.target.closest("[data-open-property]"); if (open) openPlanProperty(open.dataset.openProperty);
    const load=event.target.closest("[data-load-scenario]"); if (load) { const values=currentPlan().scenarios[load.dataset.loadScenario]; Object.entries(values).forEach(([key,value])=> { document.querySelector("#economicsLabForm").elements.namedItem(key).value=value; }); document.querySelector("#scenarioName").value=load.dataset.loadScenario; calculateEconomics(); }
    const remove=event.target.closest("[data-remove-scenario]"); if (remove) { const plan=currentPlan(); delete plan.scenarios[remove.dataset.removeScenario]; savePlan(plan); renderScenarioLibrary(); }
    if (event.target.closest("[data-use-menu-basket]")) useMenuBasket();
  });
  document.querySelector("#menuPlanning").addEventListener("change", event=> {
    const plan=currentPlan(), input=event.target;
    if (input.dataset.basketQty) { if (!input.reportValidity()) return; plan.basket[input.dataset.basketQty]=Number(input.value); }
    else {
      const id=input.dataset.planIngredients || input.dataset.planComplexity; if (!id) return;
      const detail=plan.menu_details[id] || {}; if (input.dataset.planIngredients) detail.ingredients=input.value.trim().slice(0,300); else detail.complexity=input.value;
      plan.menu_details[id]=detail;
    }
    const openDetails=[...document.querySelectorAll("#menuPlanning details")].map(item=>item.open);
    savePlan(plan); renderMenuPlanning(); document.querySelectorAll("#menuPlanning details").forEach((item,index)=>item.open=openDetails[index]);
  });
  window.addEventListener("online", ()=> { if (accountOwner) { if (!workspaceReady) initializeWorkspace(); else syncWorkspace(); } });
  document.addEventListener("visibilitychange", ()=> { if (document.visibilityState === "hidden" && accountOwner && workspaceReady) syncWorkspace(); });
}
