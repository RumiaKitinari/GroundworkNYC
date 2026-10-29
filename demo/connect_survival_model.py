"""Validate and atomically connect a temporal AFT run to the local dashboard."""
import argparse
from datetime import date
import json
from pathlib import Path

from survival_inference import DEFAULT_CONFIG, ROOT, TemporalSurvivalInference


def connect(model_dir, snapshots, data_dir, config=DEFAULT_CONFIG):
    engine = TemporalSurvivalInference(model_dir, snapshots, data_dir, date.today().isoformat())
    payload = {"model_dir": str(Path(model_dir).resolve()),
               "snapshots": [str(Path(p).resolve()) for p in snapshots],
               "data_dir": str(Path(data_dir).resolve())}
    config = Path(config)
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(config)
    return {"status": "connected", "model_version": engine.model_id, "config": str(config),
            "restart_required": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, action="append", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        result = connect(args.model_dir, args.snapshots, args.data_dir, args.config)
    except (OSError, ValueError, KeyError, ImportError) as error:
        parser.exit(2, f"Model not connected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
