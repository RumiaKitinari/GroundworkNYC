# Groundwork NYC Flask Frontend Prototype

This is the Flask dashboard demo for the DS 440 capstone. The backend reads the integrated Groundwork dataset at `../data/integrated/restaurant_bar_location_data_ready/` and uses `master_tract_features.csv` as the primary source for NYC restaurant and bar location scoring.

The integrated data package is intentionally not stored in GitHub. To run the data-backed demo locally, place the private dataset at `data/integrated/restaurant_bar_location_data_ready/` next to this `demo/` folder.

The current demo supports tract-level location recommendations, score explanations, source coverage, and Storefront Registry property leads. Exact asking rent, sale price, listing photos, confirmed lease or purchase availability, review sentiment, and mobile-phone foot traffic are not included in the uploaded data package.

Run it from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then visit `http://localhost:5001`.
