"""Read-only site brief. The model can vary wording, never facts or decisions."""
from __future__ import annotations

import json
from hashlib import sha256
from http.client import HTTPException
from math import isfinite
from threading import Lock
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

MODEL = "qwen2.5:3b-instruct"
_OLLAMA = "http://127.0.0.1:11434"
_OPENER = build_opener(ProxyHandler({}))
_INFERENCE = Lock()


def _number(value, digits=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return f"{value:,.{digits}f}"


def evidence_version(evidence):
    return sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _source_catalog(dashboard):
    sources = []
    for row in dashboard.get("feeds") or []:
        url = row.get("url")
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            safe = bool(parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password)
        except ValueError:
            safe = False
        sources.append({"name": row.get("name") or "Source", "vintage": row.get("vintage") or "Not supplied",
                        "url": url if safe else None})
    return sources


def build_evidence(dashboard, saved_ids=()):
    """Select candidates and resolve metrics from the server's dashboard response."""
    ranked = dashboard.get("locations") or []
    by_id = {row["id"]: row for row in ranked + (dashboard.get("saved_locations") or [])}
    selected = [by_id[i] for i in dict.fromkeys(saved_ids) if i in by_id][:3] if saved_ids else ranked[:3]
    rent = dashboard.get("rent_benchmarks") or {}
    finance = dashboard.get("finance") or {}
    meta = dashboard.get("meta") or {}
    sites = []
    properties = dashboard.get("properties") or []
    concept = meta.get("concept") or {}
    sources = _source_catalog(dashboard)
    catalog = {item["name"]: item for item in sources}
    for row in selected:
        policy = row.get("assessment_policy") or {}
        market = row.get("market_profile") or {}
        cuisine = row.get("concept_evidence") or {}
        benchmark = (rent.get("by_geoid") or {}).get(row.get("geoid", row["id"])) or {}
        facts = []

        def add(key, label, value, basis, unit="", digits=0, source=None):
            formatted = _number(value, digits)
            if key == "income" and formatted is not None:
                formatted = "250,000+" if value == 250001 else formatted if value >= 0 else None
            facts.append({"id": key, "label": label, "value": f"{formatted}{unit}" if formatted is not None else None,
                          "basis": basis, "source": catalog.get(source)})

        add("score", "Dashboard location score", row.get("opportunity") if policy.get("recommendation_eligible") is not False else None,
            meta.get("assessment_type") or "Dashboard index", "/100")
        add("walk", "Walkability", row.get("walkability"), "Dashboard index", "/100")
        add("access", "Customer access", row.get("inverse_walkability"), "Modeled access index", "/100")
        add("population", "Local residents", market.get("population"), "Integrated area estimate", source="ACS demographics")
        add("jobs", "Nearby jobs", market.get("jobs"), "Integrated area estimate", source="LODES")
        add("income", "Median household income (USD)", market.get("median_household_income"), "Integrated area estimate", source="ACS income")
        add("transit", "Nearest subway distance", market.get("subway_distance_miles"), "Integrated transit evidence", " mi", 2)
        add("competition", "Recorded same-cuisine restaurants", cuisine.get("same_cuisine_count"), "Source inventory; incomplete coverage is possible")
        add("rent", "Reported median monthly rent", benchmark.get("reported_median_monthly_rent_psf"),
            f"Area benchmark ({rent.get('reporting_year') or 'year unavailable'}); not an asking rent", " USD/sq ft", 2)
        add("inventory", "Recorded restaurants", market.get("active_restaurants"),
            "Integrated inventory; not a live count")
        add("coverage", "Screening evidence strength", row.get("confidence_score"),
            "Evidence coverage indicator; not a probability of success", "/100")
        add("ridership", "Nearest station weekly ridership", market.get("nearest_subway_weekly_ridership"),
            str(market.get("subway_vintage") or "Integrated transit evidence"), source="MTA ridership")
        leads = [p for p in properties if p.get("location_id") == row["id"]]
        add("registry", "Matching registry records", sum(p.get("lead_type") == "registry_record" for p in leads),
            "Registry context only; not available listings")
        add("synthetic", "Matching synthetic property scenarios", sum(p.get("lead_type") == "synthetic" for p in leads),
            "Modeled inventory; not available listings")
        add("listings", "Matching sourced property leads", sum(p.get("lead_type") == "listing" for p in leads),
            "Recorded leads; confirm availability independently")
        fact_map = {item["id"]: item for item in facts}
        gaps = [fact_map[key]["label"] for key in ("access", "walk", "rent", "income", "competition", "transit")
                if fact_map[key]["value"] is None]
        cautions = []
        if policy.get("recommendation_eligible") is False:
            cautions.append("This saved location does not meet the dashboard’s evidence threshold for a recommendation.")
        if policy.get("cuisine_mode") not in (None, "cuisine_supply_supported"):
            cautions.append("Cuisine-specific evidence is limited; recorded supply does not establish demand.")
        if not any(p.get("lead_type") == "listing" for p in leads):
            cautions.append("This search returned no sourced property leads here. That does not establish market availability.")
        if any(p.get("lead_type") == "synthetic" for p in leads):
            cautions.append("Synthetic properties are examples, not premises to tour.")
        checks = ["Confirm the actual address, availability, asking terms and permitted restaurant use."]
        if any(key in policy.get("required_actions", []) for key in ("validate_concept_specific_demand", "obtain_affordability_evidence")) or gaps:
            checks.append("Verify local competitors and visit during your intended trading period.")
        sites.append({"id": row["id"], "name": row["name"], "facts": facts, "gaps": gaps,
                      "cautions": cautions, "checks": checks})
    covers = _number(finance.get("required_covers_per_day"))
    return {"sites": sites, "release": meta.get("data_release"),
            "scope": "Saved comparison" if saved_ids else "Dashboard shortlist",
            "sources": sources,
            "assumptions": {key: concept.get(key) for key in ("cuisine", "average_check", "daypart", "audience")},
            "coverage": {"customer_access": (dashboard.get("customer_access_model") or {}).get("status"),
                         "rent_benchmarks": rent.get("status"),
                         "survival": (dashboard.get("survival_model") or {}).get("status")},
            "economics": f"Scenario break-even: {covers} covers/day based on entered costs; not a demand forecast." if covers is not None else None}


def wording_choices(evidence):
    """Construct equivalent short sentences; their meaning is fixed by code."""
    options = {}
    for i, site in enumerate(evidence["sites"], 1):
        facts = {item["id"]: item for item in site["facts"]}
        core = [facts[k] for k in ("score", "access", "walk", "competition", "transit", "population") if facts[k]["value"] is not None][:3]
        name = site["name"]
        if core:
            phrases = ", ".join(f"{f['label'].lower()} {f['value']}" for f in core)
            options[f"site{i}"] = [f"{name}: {phrases}.", f"For {name}, the dashboard shows {phrases}."]
        else:
            options[f"site{i}"] = [f"Comparable measures are unavailable for {name}."]
    return options


def _request(path, payload=None, timeout=15):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(_OLLAMA + path, data=data, headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=timeout) as response:
        content = response.read(262145)
        if len(content) > 262144:
            raise ValueError("Ollama response exceeds the brief limit")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Invalid Ollama response")
        return result


def loaded_models():
    models = _request("/api/ps", timeout=2).get("models")
    if not isinstance(models, list) or any(not isinstance(model, dict) for model in models):
        raise ValueError("Invalid Ollama model status")
    return models


def local_summary(options, keep_alive="30s", timeout=15):
    # Ollama may evict other models to make room. Defer whenever any different model is loaded.
    with _INFERENCE:
        if any(m.get("name", m.get("model")) != MODEL for m in loaded_models()):
            raise RuntimeError("another_model_loaded")
        choices = {k: {chr(65 + i): sentence for i, sentence in enumerate(v)} for k, v in options.items()}
        schema = {"type": "object", "additionalProperties": False, "required": list(choices),
                  "properties": {k: {"type": "string", "enum": list(v)} for k, v in choices.items()}}
        result = _request("/api/chat", {
            "model": MODEL, "stream": False, "format": schema, "keep_alive": keep_alive,
            "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 64},
            "messages": [
                {"role": "system", "content": "Assemble a concise site brief. For each site, return only the letter of one supplied sentence. Prefer natural phrasing and avoid repetitive openings. Never add a claim."},
                {"role": "user", "content": json.dumps(choices, ensure_ascii=False)},
            ],
        }, timeout=timeout)
        if result.get("done_reason") == "length":
            raise ValueError("incomplete model output")
        reply = json.loads(result["message"]["content"])
        if not isinstance(reply, dict) or set(reply) != set(choices):
            raise ValueError("invalid sentence selection")
        return {key: choices[key][value] for key, value in reply.items()}, result


def site_brief(evidence, generate=local_summary, *, wording=True):
    options = wording_choices(evidence)
    chosen = [v[0] for v in options.values()]
    mode = "template"
    fallback = "no_locations" if not options else "model_busy" if wording else None
    if wording and options and _BRIEF.acquire(blocking=False):
        try:
            reply, _ = generate(options)
            if not isinstance(reply, dict) or set(reply) != set(options) or any(reply[k] not in v for k, v in options.items()):
                raise ValueError("unsupported model wording")
            chosen, mode, fallback = [reply[k] for k in options], "local_model", None
        except (OSError, HTTPException, KeyError, ValueError, TypeError, RuntimeError) as error:
            fallback = "another_model_loaded" if str(error) == "another_model_loaded" else "model_unavailable_or_invalid"
        finally:
            _BRIEF.release()
    return {**evidence, "evidence_version": evidence_version(evidence), "summary": " ".join(chosen), "mode": mode, "fallback_reason": fallback,
            "limitations": "Verify actual availability, asking rent and permitted use before touring or committing. This brief is for screening; it does not establish demand, profitability or restaurant survival."}


_BRIEF = Lock()


def scenario_arguments(baseline, changes):
    """Validate explicit changes; never let a model or client replace the ranking rules."""
    if not isinstance(changes, dict) or not changes or changes.keys() - {"average_check", "daypart"}:
        raise ValueError("Choose a guest spend or trading period to compare.")
    variant = baseline.copy()
    if "average_check" in changes:
        amount = changes["average_check"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 5 <= amount <= 250:
            raise ValueError("Guest spend must be between $5 and $250.")
        variant["average_check"] = str(amount)
        variant["price_mode"] = "exact"
    if "daypart" in changes:
        if changes["daypart"] not in ("all_day", "morning", "lunch", "evening"):
            raise ValueError("Choose a supported trading period.")
        variant["daypart"] = changes["daypart"]
    return variant


def _numeric(value):
    return _number(value) is not None


def screening_factor_changes(before, after):
    old = {row["key"]: row for row in before.get("score_components") or []}
    changes = []
    for current in after.get("score_components") or []:
        previous = old.get(current["key"])
        if not previous or not all(_numeric(row.get(field)) for row in (previous, current)
                                   for field in ("score", "coverage")):
            continue
        if min(previous["coverage"], current["coverage"]) <= 0:
            continue
        delta = round(current["score"] - previous["score"], 2)
        if delta:
            changes.append({"key": current["key"], "label": current["label"], "delta": delta,
                            "before": previous["score"], "after": current["score"],
                            "coverage_changed": previous["coverage"] != current["coverage"]})
    return sorted(changes, key=lambda row: (-abs(row["delta"]), row["key"]))[:2]


def _ranking_explanations(before, after, first, second, key, mode):
    old = {row["id"]: (i, row) for i, row in enumerate(before["locations"], 1)}
    new = {row["id"]: (i, row) for i, row in enumerate(after["locations"], 1)}
    explanations = []
    for site in {row["id"]: row for row in second + first}.values():
        old_rank, previous = old.get(site["id"], (None, {}))
        new_rank, current = new.get(site["id"], (None, {}))
        a, b = previous.get(key), current.get(key)
        delta = round(b - a, 2) if _numeric(a) and _numeric(b) else None
        factors = screening_factor_changes(previous, current) if key == "opportunity" and mode == "screening" else []
        if old_rank == new_rank and not delta and not factors:
            continue
        if not previous or not current:
            note = "This location has no comparable record in one of the results."
        elif key != "opportunity" or mode != "screening":
            note = "Factor changes are not available for this ranking method."
        elif not factors:
            note = "No change in the displayed screening factors with evidence in both runs."
        else:
            note = None
        if old_rank != new_rank and delta == 0:
            note = "Rank changed while the displayed score stayed the same. Rank also depends on other locations and ties."
        explanations.append({"id": site["id"], "name": site["name"], "before_rank": old_rank,
                             "after_rank": new_rank, "before_score": a, "after_score": b,
                             "score_delta": delta, "factors": factors, "note": note})
    return explanations


def compare_rankings(before, after):
    """Compare two ordered, server-produced shortlists without reordering either."""
    left_meta, right_meta = before.get("meta", {}), after.get("meta", {})
    if not before.get("locations") or not after.get("locations"):
        raise ValueError("One scenario has insufficient location evidence; no comparison was made.")
    basis = left_meta.get("sort_by") or "opportunity"
    if (left_meta.get("data_release") != right_meta.get("data_release") or
            basis != (right_meta.get("sort_by") or "opportunity") or
            before.get("scoring", {}).get("ranking_mode") != after.get("scoring", {}).get("ranking_mode")):
        raise ValueError("The data release or ranking method changed. Refresh and try again.")
    key = "inverse_walkability" if basis == "inverse_walkability" else "opportunity"

    def shortlist(result):
        return [{"id": r["id"], "name": r["name"], "rank": i, "score": r.get(key)}
                for i, r in enumerate(result["locations"][:3], 1)]

    first, second = shortlist(before), shortlist(after)
    first_by_id = {r["id"]: r for r in first}
    second_ids = {r["id"] for r in second}
    retained = [{"id": r["id"], "name": r["name"], "previous_rank": first_by_id[r["id"]]["rank"],
                 "current_rank": r["rank"]} for r in second if r["id"] in first_by_id]
    mode = before.get("scoring", {}).get("ranking_mode")
    return {"before": first, "after": second,
            "explanations": _ranking_explanations(before, after, first, second, key, mode),
            "entered": [r for r in second if r["id"] not in first_by_id],
            "left": [r for r in first if r["id"] not in second_ids], "retained": retained,
            "ranking_basis": "Customer access" if key == "inverse_walkability" else "Dashboard location score",
            "release": left_meta.get("data_release"),
            "scope": "Scenario comparison of the dashboard’s top three areas, not saved locations or property listings.",
            "limitations": "Changes reflect the ranking model under these assumptions, not measured changes in demand or survival."}


def published_sample(path, price):
    """Read one explicitly synthetic, previously scored public scenario."""
    import csv

    with path.open(newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream) if row["method"] == "screening"
                and row["cuisine_key"] == "italian" and float(row["average_check"]) == price]
    rows.sort(key=lambda row: int(row["rank"]))
    if len(rows) < 3:
        raise ValueError("The published sample is incomplete.")
    return {"locations": [{"id": row["property_id"], "name": row["neighborhood"] + " scenario",
                           "opportunity": float(row["selected_score"])} for row in rows[:3]],
            "properties": [{"location_id": row["property_id"], "lead_type": "synthetic"} for row in rows[:3]],
            "meta": {"data_release": "November 2 published screening sample",
                     "assessment_type": "Saved synthetic property screening score",
                     "concept": {"average_check": price, "daypart": "all_day"}}}
