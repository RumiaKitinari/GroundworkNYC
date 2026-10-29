"""Extract reviewed concept photos from the team's Word file into private local data."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data" / "concept_images"
KEYS = (
    "american", "southern_soul", "cajun_creole", "italian", "french", "spanish", "portuguese",
    "greek", "german_central", "eastern_european", "mexican", "peruvian", "brazilian",
    "colombian", "venezuelan", "cuban", "dominican", "puerto_rican", "jamaican", "haitian",
    "ethiopian", "west_african", "indian", "pakistani_bangladeshi", "chinese", "japanese",
    "korean", "taiwanese", "thai", "vietnamese", "filipino", "indonesian_malaysian",
    "middle_eastern", "mediterranean", "turkish", "persian_iranian", "steakhouse", "seafood",
    "barbecue", "pizza", "burgers", "sandwiches_deli", "bakery_pastries", "coffee_tea",
    "desserts_ice_cream", "salads_bowls", "breakfast_brunch", "noodles", "general", "health_focused",
)
# Excludes low-resolution, visibly blurry, branded, or off-concept images.
APPROVED = {1, 9, 10, 14, 16, 17, 18, 20, 21, 22, 23, 24, 25, 27, 28,
            31, 33, 35, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50}
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.document) as document:
        rels = ET.fromstring(document.read("word/_rels/document.xml.rels"))
        targets = {node.attrib["Id"]: node.attrib.get("Target", "") for node in rels}
        root = ET.fromstring(document.read("word/document.xml"))
        pairs, current_label = [], None
        for paragraph in root.findall(f".//{{{W}}}p"):
            label = "".join(node.text or "" for node in paragraph.findall(f".//{{{W}}}t")).strip()
            if label:
                current_label = label
            for image in paragraph.findall(f".//{{{A}}}blip"):
                target = targets[image.attrib[f"{{{R}}}embed"]]
                pairs.append((current_label, target))
        if len(pairs) != len(KEYS):
            raise ValueError(f"Expected {len(KEYS)} labeled images; found {len(pairs)}")
        manifest = []
        for (label, target), key in zip(pairs, KEYS):
            name = Path(target).name
            if int(Path(name).stem.removeprefix("image")) not in APPROVED:
                continue
            if Path(name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            destination = DESTINATION / f"{key}{Path(name).suffix.lower()}"
            destination.write_bytes(document.read("word/" + target))
            manifest.append({"cuisine": key, "document_label": label, "embedded_image": name,
                             "local_file": destination.name, "license_status": "unverified"})
    (DESTINATION / "manifest.json").write_text(json.dumps({
        "source_document": args.document.name, "usage": "local demo only; verify creator/source/license before public distribution",
        "images": manifest,
    }, indent=2) + "\n")
    print(f"Imported {len(manifest)} reviewed images to {DESTINATION}")


if __name__ == "__main__":
    main()
