const locations = [
  {
    id: "williamsburg",
    name: "Williamsburg North",
    x: 48,
    y: 50,
    opportunity: 88,
    walkability: 86,
    activity: 82,
    whitespace: 78,
    transit: 84,
    customer: 91,
    competition: 63,
    cost: 68,
    confidence: "Medium high",
    reasons: [
      "Strong evening and weekend demand with dense nearby residents and nightlife destinations.",
      "Restaurant supply is high, but direct gastropub saturation is lower than comparable areas.",
      "Rent pressure is meaningful, so this cell works best for concepts with higher average ticket size."
    ]
  },
  {
    id: "lic",
    name: "Long Island City Core",
    x: 61,
    y: 42,
    opportunity: 84,
    walkability: 80,
    activity: 79,
    whitespace: 82,
    transit: 91,
    customer: 86,
    competition: 58,
    cost: 72,
    confidence: "Medium",
    reasons: [
      "Worker and resident density create a useful mix of lunch, dinner, and after-work demand.",
      "Transit access is one of the strongest signals in the current profile.",
      "Observed supply is still catching up with expected restaurant and bar demand."
    ]
  },
  {
    id: "astoria",
    name: "Astoria Broadway",
    x: 64,
    y: 33,
    opportunity: 81,
    walkability: 77,
    activity: 74,
    whitespace: 84,
    transit: 78,
    customer: 82,
    competition: 55,
    cost: 79,
    confidence: "Medium",
    reasons: [
      "Good customer fit and moderate rent pressure make the risk-adjusted score attractive.",
      "Competition is present but less concentrated than central Manhattan clusters.",
      "Pedestrian activity needs validation against transit and POI signals."
    ]
  },
  {
    id: "eastvillage",
    name: "East Village",
    x: 43,
    y: 44,
    opportunity: 79,
    walkability: 93,
    activity: 88,
    whitespace: 52,
    transit: 86,
    customer: 84,
    competition: 88,
    cost: 61,
    confidence: "High",
    reasons: [
      "Very strong activity and walkability, especially for evening demand.",
      "Dense competition lowers the WhiteSpace score for new restaurant concepts.",
      "Best suited for a differentiated concept rather than a generic sit-down format."
    ]
  },
  {
    id: "harlem",
    name: "Central Harlem",
    x: 40,
    y: 23,
    opportunity: 76,
    walkability: 79,
    activity: 71,
    whitespace: 80,
    transit: 82,
    customer: 78,
    competition: 49,
    cost: 83,
    confidence: "Medium",
    reasons: [
      "Lower cost pressure improves the risk-adjusted view for first-time owners.",
      "Market-gap signal is promising for casual dining and neighborhood bars.",
      "Additional validation is needed around time-of-day activity patterns."
    ]
  },
  {
    id: "downtownbk",
    name: "Downtown Brooklyn",
    x: 45,
    y: 62,
    opportunity: 83,
    walkability: 85,
    activity: 84,
    whitespace: 70,
    transit: 94,
    customer: 81,
    competition: 69,
    cost: 66,
    confidence: "Medium high",
    reasons: [
      "Excellent subway accessibility supports workers, residents, and event-driven demand.",
      "Competition is meaningful but offset by strong activity signals.",
      "Lease economics will decide whether the higher-rent cells remain viable."
    ]
  },
  {
    id: "flushing",
    name: "Flushing Main Street",
    x: 79,
    y: 35,
    opportunity: 80,
    walkability: 82,
    activity: 89,
    whitespace: 58,
    transit: 90,
    customer: 83,
    competition: 82,
    cost: 70,
    confidence: "Medium high",
    reasons: [
      "Activity and transit signals are extremely strong for food and beverage.",
      "High restaurant density lowers the market-gap score.",
      "Best interpreted as a high-demand, high-competition location."
    ]
  },
  {
    id: "sunsetpark",
    name: "Sunset Park",
    x: 40,
    y: 78,
    opportunity: 72,
    walkability: 68,
    activity: 63,
    whitespace: 85,
    transit: 70,
    customer: 73,
    competition: 45,
    cost: 88,
    confidence: "Low medium",
    reasons: [
      "Cost pressure and market gap look favorable for smaller operators.",
      "Pedestrian activity confidence is lower until mobility data is cleaned.",
      "Could be a strong candidate for a neighborhood-focused concept."
    ]
  }
];

const layerColors = {
  opportunity: ["#bd5f4a", "#d89a2b", "#6d9c58", "#1f7a4d"],
  walkability: ["#767d8f", "#5e98a1", "#317c85", "#155f6b"],
  activity: ["#9a6b48", "#c58b2c", "#d6a73c", "#8f6a10"],
  whitespace: ["#8d6571", "#bd5f4a", "#d9795d", "#9b3f38"]
};

const leases = [
  { name: "Bedford Ave storefront", rent: "$16.5k", sqft: "1,900", fit: 91, breakEven: "112 orders/day" },
  { name: "Court Sq corner unit", rent: "$18.8k", sqft: "2,300", fit: 88, breakEven: "126 orders/day" },
  { name: "Atlantic Ave shell", rent: "$13.2k", sqft: "1,650", fit: 84, breakEven: "94 orders/day" }
];

const whitespace = [
  { category: "Gastropub", current: 4, expected: 7.4, gap: "+3.4", score: 88 },
  { category: "Bakery cafe", current: 3, expected: 5.9, gap: "+2.9", score: 84 },
  { category: "Late-night dessert", current: 2, expected: 4.2, gap: "+2.2", score: 79 },
  { category: "Full-service Italian", current: 9, expected: 7.1, gap: "-1.9", score: 43 }
];

const nowItems = [
  { name: "Coffee cart", window: "7 AM-11 AM", demand: 93, condition: "Light rain", competition: 61 },
  { name: "Lunch truck", window: "11 AM-2 PM", demand: 86, condition: "Office peak", competition: 68 },
  { name: "Dessert cart", window: "6 PM-10 PM", demand: 81, condition: "Event nearby", competition: 72 }
];

let selected = locations[0];
let activeLayer = "opportunity";

const hexLayer = document.querySelector("#hexLayer");
const metricStack = document.querySelector("#metricStack");
const reasonList = document.querySelector("#reasonList");
const rankingTable = document.querySelector("#rankingTable");
const leaseGrid = document.querySelector("#leaseGrid");
const whitespaceList = document.querySelector("#whitespaceList");
const financeGrid = document.querySelector("#financeGrid");
const nowBoard = document.querySelector("#nowBoard");

function scoreColor(value, layer) {
  const colors = layerColors[layer];
  if (value >= 85) return colors[3];
  if (value >= 74) return colors[2];
  if (value >= 62) return colors[1];
  return colors[0];
}

function activeScore(location) {
  return location[activeLayer];
}

function renderHexes() {
  hexLayer.innerHTML = "";
  locations.forEach((location) => {
    const button = document.createElement("button");
    button.className = `hex${location.id === selected.id ? " active" : ""}`;
    button.type = "button";
    button.style.left = `${location.x}%`;
    button.style.top = `${location.y}%`;
    button.style.background = scoreColor(activeScore(location), activeLayer);
    button.textContent = activeScore(location);
    button.title = location.name;
    button.addEventListener("click", () => {
      selected = location;
      renderAll();
    });
    hexLayer.appendChild(button);
  });
}

function renderInsight() {
  document.querySelector("#selectedName").textContent = selected.name;
  document.querySelector("#scoreValue").textContent = selected.opportunity;
  document.querySelector("#confidenceValue").textContent = selected.confidence;
  document.querySelector("#scoreRing").style.background = `conic-gradient(${scoreColor(selected.opportunity, "opportunity")} 0 ${selected.opportunity}%, #dbe4da ${selected.opportunity}% 100%)`;

  const metrics = [
    ["Customer fit", selected.customer],
    ["Pedestrian activity", selected.activity],
    ["Transit access", selected.transit],
    ["WhiteSpace", selected.whitespace],
    ["Cost efficiency", selected.cost],
    ["Competition pressure", selected.competition]
  ];

  metricStack.innerHTML = metrics
    .map(([label, value]) => `
      <div class="metric-row">
        <div class="metric-label"><span>${label}</span><strong>${value}</strong></div>
        <div class="bar-track"><div class="bar-fill" style="width:${value}%;background:${scoreColor(value, "opportunity")}"></div></div>
      </div>
    `)
    .join("");

  reasonList.innerHTML = selected.reasons.map((reason) => `<li>${reason}</li>`).join("");
}

function renderRanking() {
  const rows = [...locations].sort((a, b) => b.opportunity - a.opportunity);
  rankingTable.innerHTML = `
    <div class="rank-row header">
      <span>#</span><span>Area</span><span>Score</span><span>Transit</span><span>Demand</span><span>Gap</span><span>Cost</span>
    </div>
    ${rows
      .map(
        (row, index) => `
          <button class="rank-row" type="button" data-id="${row.id}">
            <span>${index + 1}</span>
            <span class="place">${row.name}</span>
            <span>${row.opportunity}</span>
            <span>${row.transit}</span>
            <span>${row.activity}</span>
            <span>${row.whitespace}</span>
            <span>${row.cost}</span>
          </button>
        `
      )
      .join("")}
  `;

  rankingTable.querySelectorAll(".rank-row[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      selected = locations.find((location) => location.id === row.dataset.id);
      renderAll();
    });
  });
}

function renderLease() {
  leaseGrid.innerHTML = leases
    .map(
      (lease) => `
      <article class="lease-card">
        <h3>${lease.name}</h3>
        <dl>
          <div><dt>Monthly rent</dt><dd>${lease.rent}</dd></div>
          <div><dt>Square feet</dt><dd>${lease.sqft}</dd></div>
          <div><dt>Fit score</dt><dd>${lease.fit}</dd></div>
          <div><dt>Break-even</dt><dd>${lease.breakEven}</dd></div>
        </dl>
      </article>
    `
    )
    .join("");
}

function renderWhitespace() {
  whitespaceList.innerHTML = whitespace
    .map(
      (item) => `
      <div class="whitespace-item">
        <strong>${item.category}</strong>
        <span>Current ${item.current}</span>
        <span>Expected ${item.expected}</span>
        <span>Gap ${item.gap}</span>
        <strong>${item.score}</strong>
      </div>
    `
    )
    .join("");
}

function renderFinance() {
  const rent = Number(document.querySelector("#rentRange").value) * 1000;
  const dailyOrders = Math.round((rent * 3.2) / 30 / 28);
  const payroll = Math.round(rent * 1.65);
  const runway = Math.max(7, Math.round(18 - rent / 3000));

  const cards = [
    ["Break-even revenue", `$${Math.round((rent * 3.2) / 1000)}k/mo`, "Rent target drives this estimate"],
    ["Required orders", `${dailyOrders}/day`, "Assumes $28 average ticket"],
    ["Payroll planning", `$${Math.round(payroll / 1000)}k/mo`, "Early staffing scenario"],
    ["Cash runway", `${runway} months`, "Based on initial fixed costs"]
  ];

  financeGrid.innerHTML = cards
    .map(
      ([name, value, note]) => `
      <article class="finance-card">
        <h3>${name}</h3>
        <dl>
          <div><dt>Estimate</dt><dd>${value}</dd></div>
          <div><dt>Basis</dt><dd>${note}</dd></div>
        </dl>
      </article>
    `
    )
    .join("");
}

function renderNow() {
  nowBoard.innerHTML = nowItems
    .map(
      (item) => `
      <article class="now-card">
        <h3>${item.name}</h3>
        <dl>
          <div><dt>Window</dt><dd>${item.window}</dd></div>
          <div><dt>Demand</dt><dd>${item.demand}</dd></div>
          <div><dt>Condition</dt><dd>${item.condition}</dd></div>
          <div><dt>Competition</dt><dd>${item.competition}</dd></div>
        </dl>
      </article>
    `
    )
    .join("");
}

function renderAll() {
  renderHexes();
  renderInsight();
  renderRanking();
  renderLease();
  renderWhitespace();
  renderFinance();
  renderNow();
}

document.querySelectorAll(".layer-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".layer-button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeLayer = button.dataset.layer;
    renderHexes();
  });
});

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((pane) => pane.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}Pane`).classList.add("active");
  });
});

document.querySelector("#rentRange").addEventListener("input", (event) => {
  document.querySelector("#rentValue").textContent = `$${event.target.value}k`;
  renderFinance();
});

document.querySelector("#competitionRange").addEventListener("input", (event) => {
  document.querySelector("#competitionValue").textContent = event.target.value;
});

document.querySelector("#resetProfile").addEventListener("click", () => {
  document.querySelector("#conceptSelect").value = "restaurant";
  document.querySelector("#customerSelect").value = "mixed";
  document.querySelector("#rentRange").value = 18;
  document.querySelector("#competitionRange").value = 42;
  document.querySelector("#rentValue").textContent = "$18k";
  document.querySelector("#competitionValue").textContent = "42";
  selected = locations[0];
  renderAll();
});

document.querySelector("#exportButton").addEventListener("click", () => {
  const button = document.querySelector("#exportButton");
  const oldText = button.textContent;
  button.textContent = "Shortlist staged";
  setTimeout(() => {
    button.textContent = oldText;
  }, 1300);
});

document.querySelector("#searchInput").addEventListener("input", (event) => {
  const query = event.target.value.trim().toLowerCase();
  const match = locations.find((location) => location.name.toLowerCase().includes(query));
  if (query && match) {
    selected = match;
    renderAll();
  }
});

renderAll();
