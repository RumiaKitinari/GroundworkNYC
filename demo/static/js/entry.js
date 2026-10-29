/* Jas's original entry controls, isolated from dashboard scoring and storage. */
let entryHasSavedBrief = false;
let entryHasSubmitted = false;
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
  updateConceptImage(item.value);
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

function syncEntryFields() {
  if (!entryHasSavedBrief && !entryHasSubmitted) {
    selectedIdea=null;ideaInput.value="";cuisineInput.value="";cuisineSelect.value="";
    document.querySelector("#briefPriceTier").value="";
    for (const id of ["briefBudget","briefPurchaseBudget","briefDeal","briefServiceStyle","briefAudience","briefDaypart"]) document.getElementById(id).value="";
    document.querySelector("#customIdeaField").hidden=true;
    document.querySelector("#customCuisineField").hidden=true;
    return;
  }
  const known = ideaOptions.find(item => item.label.toLowerCase() === state.conceptName.toLowerCase());
  selectedIdea = known || {...ideaOptions.find(item => item.value === "other"), profile:state.profile};
  ideaInput.value = selectedIdea.label;
  document.querySelector("#customIdeaField").hidden = selectedIdea.value !== "other";
  document.querySelector("#briefCustomIdea").value = known ? "" : state.conceptName;
  cuisineInput.value = cuisineSelect.selectedOptions[0]?.textContent || "";
  if (!cuisineSelect.value || cuisineSelect.value === "any") cuisineInput.value = "";
  document.querySelector("#customCuisineField").hidden = cuisineSelect.value !== "custom";
  const custom = state.cuisine === "custom" ? state.description.match(/(?:^|\. )Cuisine: (.*)$/) : null;
  document.querySelector("#briefCustomCuisine").value = custom?.[1] || "";
  if (custom) descriptionField.value = state.description.slice(0, custom.index);
  document.querySelector("#briefSkip").hidden = false;
}

function submitEntryBrief() {
  const price = document.querySelector("#briefPriceTier"), customIdea = document.querySelector("#briefCustomIdea"), customCuisine = document.querySelector("#briefCustomCuisine");
  const exactIdea = ideaOptions.find(item => normalizeConceptText(item.label) === normalizeConceptText(ideaInput.value));
  if (!selectedIdea && exactIdea) {selectedIdea=exactIdea;ideaInput.value=exactIdea.label;}
  const exactCuisine = [...cuisineSelect.options].find(option => option.value && normalizeConceptText(option.textContent) === normalizeConceptText(cuisineInput.value));
  if (!cuisineSelect.value && exactCuisine) cuisineSelect.value=exactCuisine.value;
  const checks = [["ideaError",Boolean(selectedIdea && ideaInput.value === selectedIdea.label)], ["cuisineError",Boolean(cuisineSelect.value && cuisineSelect.value !== "any")], ["priceError",Boolean(price.value)]];
  checks.forEach(([id,valid]) => document.getElementById(id).hidden=valid);
  customIdea.required=selectedIdea?.value === "other";customCuisine.required=cuisineSelect.value === "custom";
  customIdea.setCustomValidity(customIdea.required && !customIdea.value.trim() ? "Enter your restaurant idea." : "");
  customCuisine.setCustomValidity(customCuisine.required && !customCuisine.value.trim() ? "Enter your cuisine." : "");
  if (!checks.every(([,valid]) => valid)) {(!checks[0][1] ? ideaInput : !checks[1][1] ? cuisineInput : price).focus();return;}
  if (!document.querySelector("#briefForm").reportValidity()) return;
  const description=[descriptionField.value.trim(),cuisineSelect.value === "custom" ? `Cuisine: ${customCuisine.value.trim()}` : ""].filter(Boolean).join(". ");
  if (description.length>500) {descriptionField.setCustomValidity("Keep the concept and custom cuisine within 500 characters.");descriptionField.reportValidity();return;}
  Object.assign(state,{conceptName:selectedIdea.value === "other" ? customIdea.value.trim() : selectedIdea.label,
    profile:selectedIdea.profile,cuisine:cuisineSelect.value,priceTier:price.value,priceMode:"tier",averageCheck:PRICE_DEFAULTS[price.value],
    dietary:document.querySelector("#briefDietary").value || "none",description,
    dealType:document.querySelector("#briefDeal").value || "lease",preferredArea:document.querySelector("#briefArea").value,
    serviceStyle:document.querySelector("#briefServiceStyle").value || defaultServiceStyle(selectedIdea.profile),
    audience:document.querySelector("#briefAudience").value || "residents",daypart:document.querySelector("#briefDaypart").value || "all_day",
    rentCap:Number(document.querySelector("#briefBudget").value || 18000),purchaseBudget:Number(document.querySelector("#briefPurchaseBudget").value || 3000000)});
  entryHasSubmitted=true;selectedId=null;syncBriefControls();persistBrief();closeBrief();selectView("discover");loadDashboard();
}
