# Groundwork NYC Flask Frontend Prototype

This is the Flask dashboard demo for the DS 440 capstone. The backend reads the integrated Groundwork dataset at `../data/integrated/restaurant_bar_location_data_ready/` and uses `master_tract_features.csv` as the primary source for NYC restaurant and bar location scoring.

## Data Setup

The integrated data package is intentionally not stored in GitHub. After downloading the private data folder, place it at this exact path from the repository root:

```text
data/integrated/restaurant_bar_location_data_ready/
```

The final layout should look like this:

```text
GroundworkNYC/
  demo/
    app.py
    templates/
    static/
  data/
    integrated/
      restaurant_bar_location_data_ready/
        README.md
        master_tract_features.csv
        data_dictionary.csv
        feature_readiness.csv
        source_catalog.csv
        entities/
        features/
        geography/
```

If the download arrives as a zip file, unzip it so the folder itself is named `restaurant_bar_location_data_ready`. The app expects `master_tract_features.csv` to be directly inside that folder, not one extra folder level deeper.

The current demo supports tract-level location recommendations, score explanations, source coverage, and Storefront Registry property leads. Exact asking rent, sale price, listing photos, confirmed lease or purchase availability, review sentiment, and mobile-phone foot traffic are not included in the uploaded data package.

Run it from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then visit `http://localhost:5001`.
