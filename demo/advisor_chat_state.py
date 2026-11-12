"""Explicit previews and one-step undo for server-signed Advisor conversations."""


def active_view(state):
    view = state.get("preview") or state
    return view.get("changes", {}), view.get("areas", [])


def transition(state, plan):
    """Keep applied settings separate from the view used to answer a question."""
    updated = {key: value for key, value in state.items() if key != "pending"}
    applied = state.get("changes", {})
    applied_areas = state.get("areas", [])
    changes, areas = active_view(state)
    previous = state.get("previous", {})
    preview = state.get("preview")
    command = plan["intent"]
    notice = None
    if command in {"apply_scenario", "discard_scenario", "undo_scenario"}:
        if command == "apply_scenario" and state.get("temporary_calculation"):
            return updated, changes, areas, previous, (
                "Rent what-ifs are temporary calculations. Test the guest spend or trading period as a site scenario before applying it."), False
        if command == "apply_scenario" and preview:
            updated.update(changes=changes, areas=areas,
                           undo={"changes": applied, "areas": applied_areas, "previous": preview["previous"]})
            updated.pop("preview", None)
            notice = "Scenario applied to this conversation."
        elif preview and command in {"discard_scenario", "undo_scenario"}:
            changes, areas, previous = applied, applied_areas, preview["previous"]
            updated.pop("preview", None)
            notice = "Preview discarded. Restored the conversation’s applied settings."
        elif command == "undo_scenario" and state.get("undo"):
            restored = state["undo"]
            changes, areas, previous = restored["changes"], restored["areas"], restored["previous"]
            updated.update(changes=changes, areas=areas)
            updated.pop("undo", None)
            notice = "Undid the applied scenario and restored the previous settings."
        else:
            notice = ("There is no applied scenario to undo." if command == "undo_scenario"
                      else "There is no scenario preview to apply." if command == "apply_scenario"
                      else "There is no scenario preview to discard.")
            return updated, changes, areas, previous, notice, False
        updated["previous"] = previous
    elif command == "what_if":
        changes = {**changes, **plan["changes"]}
        areas = plan.get("area_groups") or ([] if "borough" in plan["changes"] else areas)
        updated["preview"] = {"changes": changes, "areas": areas,
                              "previous": preview["previous"] if preview else previous}
    elif plan.get("topic") == "rent_scenario":
        # The operating-cost calculation is temporary, including any paired guest spend.
        changes = {**changes, **{key: value for key, value in plan["changes"].items() if key != "rent_cap"}}
        updated["temporary_calculation"] = True
        notice = "These assumptions apply only to this rent calculation."
    elif plan["changes"] or plan.get("area_groups"):
        changes = {**applied, **plan["changes"]}
        areas = plan.get("area_groups") or ([] if "borough" in plan["changes"] else applied_areas)
        updated.update(changes=changes, areas=areas)
        updated.pop("preview", None)
        updated.pop("undo", None)
        if preview:
            notice = "Started a new search from the applied settings."
    if plan.get("topic") != "rent_scenario":
        updated.pop("temporary_calculation", None)
    return updated, changes, areas, previous, notice, True


def scenario_actions(state):
    if state.get("temporary_calculation"):
        return []
    if state.get("preview"):
        return [{"label": "Apply scenario", "prompt": "Apply this scenario."},
                {"label": "Discard preview", "prompt": "Discard this preview."}]
    if state.get("undo"):
        return [{"label": "Undo applied scenario", "prompt": "Undo the applied scenario."}]
    return []
