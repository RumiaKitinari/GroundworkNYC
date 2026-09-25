import unittest

from app import app


class ConceptApiTests(unittest.TestCase):
    def test_resolution_returns_structured_concept(self):
        with app.test_client() as client:
            response = client.post("/api/concepts/resolve", json={"concept_name": "Vegan Mexican Bistro", "price_mode": "tier"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["concept"]["cuisine"], "mexican")
        self.assertEqual(response.json["concept"]["dietary"], "vegan")

    def test_invalid_format_is_rejected(self):
        with app.test_client() as client:
            response = client.post("/api/concepts/resolve", json={"profile": "hotel"})
        self.assertEqual(response.status_code, 400)

    def test_site_coordinate_is_validated_before_data_load(self):
        with app.test_client() as client:
            response = client.post("/api/sites/analyze", json={"latitude": 0, "longitude": 0})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
