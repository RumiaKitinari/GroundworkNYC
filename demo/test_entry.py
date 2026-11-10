from html.parser import HTMLParser

from app import app


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "script" and "src" in values:
            self.scripts.append(values["src"])


def test_jas_entry_preserves_dashboard_contracts():
    response = app.test_client().get("/")
    assert response.status_code == 200
    parsed = Elements()
    parsed.feed(response.text)
    assert len(parsed.ids) == len(set(parsed.ids))
    assert {"welcomeOverlay", "briefOverlay", "briefForm", "briefConceptName",
            "conceptSuggestions", "cuisineSearch", "cuisineSuggestions", "briefCustomIdea",
            "briefCustomCuisine", "briefPriceTier", "briefAverageCheck", "briefProfile",
            "heatmapMetricSelect", "businessPlanForm", "menuAnalysis"} <= set(parsed.ids)
    entry = next(index for index, src in enumerate(parsed.scripts) if "/entry.js?" in src)
    dashboard = next(index for index, src in enumerate(parsed.scripts) if "/dashboard.js?" in src)
    assert entry < dashboard


def test_entry_assets_are_served_without_changing_calculation_routes():
    client = app.test_client()
    assert client.get("/static/js/entry.js").status_code == 200
    assert client.get("/static/css/entry.css").status_code == 200
    assert client.post("/api/menu/recipe-cost", json={}).status_code == 400
    assert client.post("/api/planning/forecast", json={}).status_code == 400


def test_inverse_walkability_heatmap_label_is_explicit():
    client = app.test_client()
    assert '<option value="inverse_walkability">Inverse Walkability (Customer Access)</option>' in client.get("/").text
    assert 'inverse_walkability:"Inverse Walkability (Customer Access)"' in client.get("/static/js/dashboard.js").text
