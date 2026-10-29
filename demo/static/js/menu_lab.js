/* Explicit recipe assumptions and ingredient contribution, never inferred sales. */
let menuAnalysisChart = null;
let removedMenuItem = null;
let recipeState = null;
let recipeRequest = 0;
let recipeTimer = null;

function menuContribution(items) {
  return items.filter(item=>Number(item.price)>0 && item.cost !== "" && item.cost != null && Number.isFinite(Number(item.cost)))
    .map(item=>({...item,contribution:Number(item.price)-Number(item.cost),cost_pct:Number(item.cost)/Number(item.price)*100}))
    .sort((a,b)=>b.contribution-a.contribution);
}

function duplicateDishName(name, items) {
  for (let index=1;index<=101;index++) {
    const suffix=index===1 ? " (Copy)" : ` (Copy ${index})`;
    const candidate=name.slice(0,80-suffix.length)+suffix;
    if (!items.some(item=>item.name.toLowerCase()===candidate.toLowerCase())) return candidate;
  }
  return null;
}

function rememberRemovedMenuItem(id) {
  const index=savedMenu.findIndex(item=>item.id===id);
  if (index<0) return;
  const plan=currentPlan();
  removedMenuItem={key:planKey(),index,item:structuredClone(savedMenu[index]),detail:structuredClone(plan.menu_details[id] || {}),quantity:plan.basket[id]};
}

function renderAdvancedMenu() {
  document.querySelector("#menuPlanning").hidden=menuView!=="plan";
  document.querySelector(".menu-pricing-toolbar").hidden=menuView!=="plan";
  document.querySelector("#menuUndoNotice").hidden=!removedMenuItem || removedMenuItem.key!==planKey();
  const target=document.querySelector("#menuAnalysis");
  target.hidden=menuView!=="analysis";
  menuAnalysisChart?.destroy();menuAnalysisChart=null;
  if (menuView!=="analysis") return;
  const rows=menuContribution(savedMenu), basket=basketSummary();
  const unpriced=savedMenu.filter(item=>!(Number(item.price)>0)).length;
  const uncosted=savedMenu.filter(item=>item.cost==="" || item.cost==null).length;
  target.innerHTML=`<div class="view-heading"><h3>Menu Economics</h3><span>${rows.length} / ${savedMenu.length} Items Costed And Priced</span></div>
    <div class="economics-kpis"><div><span>Guest Basket</span><strong>${basket.priced ? money(basket.price) : "Not Configured"}</strong></div><div><span>Basket Ingredient Cost</span><strong>${basket.costed ? money(basket.cost) : "Incomplete"}</strong></div><div><span>Price Less Ingredients</span><strong>${basket.priced && basket.costed ? money(basket.price-basket.cost) : "Unavailable"}</strong></div><div><span>Items Needing Review</span><strong>${savedMenu.filter(item=>!(Number(item.price)>0) || item.cost==="" || item.cost==null || Number(item.cost)>=Number(item.price)).length}</strong></div></div>
    ${rows.length ? `<h4>Price Less Ingredient Cost / Portion</h4><div class="menu-analysis-chart"><canvas id="menuContributionChart" role="img" aria-label="Menu Price Less Ingredient Cost Per Portion"></canvas></div><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>Dish</th><th>Price</th><th>Ingredient Cost</th><th>Ingredient Cost %</th><th>Difference</th></tr></thead><tbody>${rows.map(item=>`<tr><th scope="row">${escapeHtml(item.name)}</th><td>${money(item.price)}</td><td>${money(item.cost)}</td><td>${item.cost_pct.toFixed(1)}%</td><td>${money(item.contribution)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="menu-empty">Add Prices And Ingredient Costs To Analyze Your Menu.</div>'}
    <div class="menu-analysis-review"><span>${unpriced} Unpriced</span><span>${uncosted} Without Ingredient Costs</span><span>${rows.filter(item=>item.contribution<=0).length} At Or Below Ingredient Cost</span></div>
    <small class="financial-qualification">Ingredient-only differences exclude labor, rent, packaging and other operating expenses.</small>`;
  if (!rows.length) return;
  const shown=rows.slice(0,20), color=getComputedStyle(document.documentElement).getPropertyValue("--text").trim();
  document.querySelector(".menu-analysis-chart").style.height=`${Math.max(180,shown.length*32+70)}px`;
  menuAnalysisChart=new Chart(document.querySelector("#menuContributionChart"), {
    type:"bar",
    data:{labels:shown.map(item=>item.name),datasets:[{label:"Price Less Ingredients",data:shown.map(item=>item.contribution),backgroundColor:shown.map(item=>item.contribution>0 ? "#168773" : "#c04c58"),borderRadius:3,maxBarThickness:24}]},
    options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{callbacks:{label:context=>money(context.parsed.x)}}},
      scales:{x:{beginAtZero:true,title:{display:true,text:"USD / Portion",color},ticks:{color}},
        y:{ticks:{color,autoSkip:false,callback:function(value) {
          const label=this.getLabelForValue(value);
          return label.length>30 ? label.slice(0,27)+"..." : label;
        }}}}
    }
  });
}

function recipeFromForm() {
  const form=document.querySelector("#recipeForm");
  return {portions:form.elements.portions.value,waste_pct:form.elements.waste_pct.value,
    lines:[...document.querySelectorAll("[data-recipe-line]")].map(row=>Object.fromEntries([...row.querySelectorAll("input")].map(input=>[input.dataset.recipeField,input.value.trim()])))};
}

function renderRecipeLines(recipe) {
  document.querySelector("#recipeLines").innerHTML=recipe.lines.map((line,index)=>`<div data-recipe-line="${index}" class="recipe-line"><label>Ingredient<input data-recipe-field="name" maxlength="80" value="${escapeHtml(line.name)}" required /></label><label>Quantity<input data-recipe-field="quantity" type="number" min="0.001" max="1000000" step="any" value="${escapeHtml(line.quantity)}" required /></label><label>Unit<input data-recipe-field="unit" maxlength="20" value="${escapeHtml(line.unit)}" required /></label><label>Cost / Unit ($)<input data-recipe-field="unit_cost" type="number" min="0" max="10000" step="any" value="${escapeHtml(line.unit_cost)}" required /></label><button type="button" data-remove-recipe-line="${index}" class="quiet-action" aria-label="Remove Ingredient ${index+1}">×</button></div>`).join("");
  document.querySelector("#recipeAddLine").disabled=recipe.lines.length>=30;
}

async function calculateRecipe() {
  const form=document.querySelector("#recipeForm"), revision=++recipeRequest;
  document.querySelector("#recipeApply").disabled=true;
  if (!form.checkValidity()) {document.querySelector("#recipeStatus").textContent="Complete The Recipe Quantities And Unit Costs.";return null;}
  const recipe=recipeFromForm();
  try {
    const response=await fetch("/api/menu/recipe-cost",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(recipe)});
    const result=await response.json();if(revision!==recipeRequest || !document.querySelector("#recipeDialog").open)return null;
    if(!response.ok)throw new Error(result.error || "Recipe Cost Unavailable");
    document.querySelector("#recipeTotals").innerHTML=[["Ingredient Purchase Cost",result.purchase_cost],["Waste-Adjusted Batch Cost",result.batch_cost],["Ingredient Cost / Portion",result.cost_per_portion]].map(([label,value])=>`<div><span>${label}</span><strong>${money(value)}</strong></div>`).join("");
    document.querySelector("#recipeStatus").textContent="Ingredient Costs Only · Quantity And Unit Price Must Use The Same Unit";
    document.querySelector("#recipeApply").disabled=false;
    return {recipe,result};
  }catch(error){if(revision===recipeRequest)document.querySelector("#recipeStatus").textContent=error.message;return null;}
}

function openRecipe(id) {
  syncSavedMenu();const item=savedMenu.find(row=>row.id===id);if(!item)return;
  recipeState={id,key:planKey()};
  const recipe=currentPlan().menu_details[id]?.recipe || {portions:1,waste_pct:0,lines:[{name:"",quantity:1,unit:"each",unit_cost:""}]};
  document.querySelector("#recipeTitle").textContent=`Recipe Cost · ${item.name}`;
  const form=document.querySelector("#recipeForm");form.elements.portions.value=recipe.portions;form.elements.waste_pct.value=recipe.waste_pct;
  renderRecipeLines(recipe);document.querySelector("#recipeTotals").replaceChildren();
  document.querySelector("#recipeDialog").showModal();calculateRecipe();
}

function initializeMenuLab() {
  document.body.insertAdjacentHTML("beforeend",`<dialog id="recipeDialog" class="recipe-dialog" aria-labelledby="recipeTitle"><form id="recipeForm"><header><h2 id="recipeTitle">Recipe Cost</h2><button type="button" id="recipeClose" class="quiet-action" aria-label="Close Recipe">×</button></header><div class="recipe-yield"><label>Batch Yield (Portions)<input name="portions" type="number" min="1" max="2000" step="1" value="1" required /></label><label>Ingredient Waste (%)<input name="waste_pct" type="number" min="0" max="50" step="any" value="0" required /></label></div><div id="recipeLines"></div><button type="button" id="recipeAddLine" class="quiet-action">Add Ingredient</button><div id="recipeTotals" class="recipe-totals"></div><div id="recipeStatus" role="status"></div><footer><button type="button" id="recipeCancel" class="quiet-action">Cancel</button><button type="submit" id="recipeApply" class="primary-action" disabled>Apply Ingredient Cost</button></footer></form></dialog>`);
  document.querySelector("#recipeClose").addEventListener("click",()=>document.querySelector("#recipeDialog").close());
  document.querySelector("#recipeCancel").addEventListener("click",()=>document.querySelector("#recipeDialog").close());
  document.querySelector("#recipeDialog").addEventListener("close",()=>{recipeRequest++;clearTimeout(recipeTimer);document.querySelector(`[data-recipe-edit="${CSS.escape(recipeState?.id || "")}"]`)?.focus();});
  document.querySelector("#recipeAddLine").addEventListener("click",()=>{const recipe=recipeFromForm();if(recipe.lines.length<30){recipe.lines.push({name:"",quantity:1,unit:"each",unit_cost:""});renderRecipeLines(recipe);calculateRecipe();}});
  document.querySelector("#recipeLines").addEventListener("click",event=>{const button=event.target.closest("[data-remove-recipe-line]");if(!button)return;const recipe=recipeFromForm();recipe.lines.splice(Number(button.dataset.removeRecipeLine),1);renderRecipeLines(recipe);calculateRecipe();});
  document.querySelector("#recipeForm").addEventListener("input",()=>{recipeRequest++;document.querySelector("#recipeApply").disabled=true;clearTimeout(recipeTimer);recipeTimer=setTimeout(calculateRecipe,250);});
  document.querySelector("#recipeForm").addEventListener("submit",async event=>{
    event.preventDefault();clearTimeout(recipeTimer);const calculated=await calculateRecipe();if(!calculated || recipeState.key!==planKey())return;
    const item=savedMenu.find(row=>row.id===recipeState.id);if(!item)return;
    const plan=currentPlan();plan.menu_details[item.id]={...plan.menu_details[item.id],recipe:calculated.recipe,ingredients:calculated.recipe.lines.map(line=>line.name).join(", ").slice(0,300)};
    if(!savePlan(plan))return;item.cost=calculated.result.cost_per_portion.toFixed(2);persistMenu();document.querySelector("#recipeDialog").close();renderMenu();
  });
  document.querySelector("#menuSaved").addEventListener("click",event=>{
    const recipe=event.target.closest("[data-recipe-edit]");if(recipe)openRecipe(recipe.dataset.recipeEdit);
    const duplicate=event.target.closest("[data-menu-duplicate]");if(!duplicate || savedMenu.length>=100)return;
    const item=savedMenu.find(row=>row.id===duplicate.dataset.menuDuplicate);if(!item)return;
    const name=duplicateDishName(item.name,savedMenu);if(!name)return;const id=`custom:${crypto.randomUUID()}`;
    savedMenu.push({...item,id,name,custom:true});const plan=currentPlan();if(plan.menu_details[item.id])plan.menu_details[id]=structuredClone(plan.menu_details[item.id]);savePlan(plan);persistMenu();renderMenu();
  });
  document.querySelector("#menuUndoRemove").addEventListener("click",()=>{
    const undo=removedMenuItem;if(!undo || undo.key!==planKey() || savedMenu.length>=100 || savedMenu.some(item=>item.id===undo.item.id))return;
    savedMenu.splice(Math.min(undo.index,savedMenu.length),0,undo.item);const plan=currentPlan();plan.menu_details[undo.item.id]=undo.detail;if(undo.quantity!=null)plan.basket[undo.item.id]=undo.quantity;savePlan(plan);removedMenuItem=null;persistMenu();renderMenu();
  });
}
