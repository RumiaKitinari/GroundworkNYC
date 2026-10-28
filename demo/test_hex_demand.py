import csv
import json
import tempfile
import unittest
from pathlib import Path

import h3
from shapely.geometry import box, mapping, shape

from hex_demand import CELL_RESOLUTION, SECTOR_RESOLUTION, boundary, concept_surface, grid, surface_weights
from scoring import Concept


RESTAURANT_WEIGHTS = {"demand": .24, "customer_fit": .18, "access": .16,
                      "market_gap": .16, "competition_balance": .12, "economics": .14}
COFFEE_WEIGHTS = {"demand": .22, "customer_fit": .16, "access": .24,
                  "market_gap": .12, "competition_balance": .10, "economics": .16}


class FakeModel:
    def evaluate(self, row, concept, weights, profile):
        value = row["signal"] + (10 if concept.cuisine == "korean" else 0)
        return {"components": {key: {"score": value, "coverage": 80}
                               for key in ("demand", "customer_fit", "access", "market_gap", "competition_balance")}}


class HexDemandTests(unittest.TestCase):
    def test_format_weights_exclude_commercial_component(self):
        restaurant = surface_weights(RESTAURANT_WEIGHTS)
        coffee = surface_weights(COFFEE_WEIGHTS)
        self.assertAlmostEqual(sum(restaurant.values()), 1)
        self.assertNotIn("economics", restaurant)
        self.assertGreater(coffee["access"], restaurant["access"])
        self.assertNotEqual(coffee["customer_fit"], restaurant["customer_fit"])

    def test_overlap_weights_parent_and_concept_response(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "geography").mkdir()
            cell = h3.latlng_to_cell(40.75, -73.97, CELL_RESOLUTION)
            polygon = shape(boundary(cell))
            split = polygon.centroid.x
            left = polygon.intersection(box(-74, 40, split, 41))
            right = polygon.intersection(box(split, 40, -73, 41))
            geoids = ("36061000100", "36061000200")
            rows = [{"geoid": geoid, "borough": "Manhattan", "eligible_for_location_screening": "True",
                     "centroid_latitude": str(part.representative_point().y),
                     "centroid_longitude": str(part.representative_point().x),
                     "nearest_subway_distance_miles": "0.1", "signal": value}
                    for geoid, part, value in zip(geoids, (left, right), (20, 80))]
            rows[0]["borough"] = "Staten Island"
            with (root / "master_tract_features.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[key for key in rows[0] if key != "signal"])
                writer.writeheader()
                writer.writerows({key: value for key, value in row.items() if key != "signal"} for row in rows)
            (root / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {"geoid": geoid}, "geometry": mapping(part)}
                    for geoid, part in zip(geoids, (left, right))]}))
            assignments = {item[0]: item for item in grid(str(root))}
            self.assertIn(cell, assignments)
            self.assertEqual(assignments[cell][2], h3.cell_to_parent(cell, SECTOR_RESOLUTION))
            shares = dict(assignments[cell][1])
            self.assertAlmostEqual(shares[geoids[0]], .5, delta=.02)
            package = {"tracts": rows, "screening_model": FakeModel(), "subway_stations": []}
            ordinary = concept_surface(package, root, Concept(cuisine="italian"), "restaurant", RESTAURANT_WEIGHTS, "")
            korean = concept_surface(package, root, Concept(cuisine="korean"), "restaurant", RESTAURANT_WEIGHTS, "")
            values = {feature["properties"]["id"]: feature["properties"]["score"] for feature in ordinary["cell"]}
            changed = {feature["properties"]["id"]: feature["properties"]["score"] for feature in korean["cell"]}
            self.assertEqual(values[cell], 50)
            island = concept_surface(package, root, Concept(cuisine="italian"), "restaurant", RESTAURANT_WEIGHTS, "Staten Island")
            self.assertTrue(island["cell"])
            self.assertTrue(all(item["properties"]["borough"] == "Staten Island" for item in island["cell"]))
            self.assertEqual(changed[cell], 60)
            demand_only = concept_surface(package, root, Concept(cuisine="italian"), "restaurant", RESTAURANT_WEIGHTS, "", metric="demand")
            self.assertEqual(next(item["properties"]["score"] for item in demand_only["cell"] if item["properties"]["id"] == cell), 50)
            self.assertEqual(demand_only["cell"][0]["properties"]["metric"], "demand")
            with self.assertRaises(ValueError):
                concept_surface(package, root, Concept(), "restaurant", RESTAURANT_WEIGHTS, metric="not_a_signal")
            self.assertTrue(all(feature["properties"]["coverage"] == 80 for feature in ordinary["cell"]))
            parent = h3.cell_to_parent(cell, SECTOR_RESOLUTION)
            sector = next(feature for feature in ordinary["sector"] if feature["properties"]["id"] == parent)
            children = [feature["properties"] for feature in ordinary["cell"] if feature["properties"]["parent_id"] == parent]
            weighted = round(sum(child["score"] * child["land_share"] for child in children) /
                             sum(child["land_share"] for child in children))
            self.assertEqual(sector["properties"]["score"], weighted)

            finer = {item[0]: item for item in grid(str(root), 9, 8)}
            self.assertTrue(finer)
            self.assertTrue(all(item[2] == h3.cell_to_parent(cell_id, 8) for cell_id, item in finer.items()))
            fine_surface = concept_surface(package, root, Concept(cuisine="korean"), "restaurant",
                                           RESTAURANT_WEIGHTS, "", cell_resolution=9)
            self.assertTrue(fine_surface["cell"])
            self.assertTrue(all(h3.get_resolution(item["properties"]["id"]) == 9
                                for item in fine_surface["cell"]))

    def test_fine_hex_api_has_resolution_nine(self):
        from app import app

        with app.test_client() as client:
            response = client.get("/api/hex-demand?level=fine&borough=Manhattan")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["meta"]["resolution"], 9)
            self.assertTrue(response.json["features"])
            self.assertEqual(h3.get_resolution(response.json["features"][0]["properties"]["id"]), 9)
            self.assertEqual(client.get("/api/hex-demand?level=unknown").status_code, 400)


if __name__ == "__main__":
    unittest.main()
