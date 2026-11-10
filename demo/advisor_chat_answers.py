"""Compose short Advisor responses from server-produced evidence and calculations."""

from math import isfinite


def _number(value):
    if type(value) not in (int, float) or not isfinite(value):
        return None
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _money(value):
    amount = _number(value)
    return f"${amount}" if amount is not None else None


def _name(card):
    return card.get("name") or card.get("label") or "This area"


def _names(values):
    items = list(values)
    if len(items) <= 1:
        return next(iter(items), "")
    if len(items) == 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _dossier(card):
    return card.get("dossier") or {}


def _rank_text(cards, basis, *, focused=False):
    scored = [(card, amount) for card in cards if (amount := _number(card.get("score"))) is not None]
    if not scored:
        return "This scope has no comparable area scores for the selected ranking method."
    values = _names(f"{_name(card)} ({amount})" for card, amount in scored)
    subject = "requested area" if len(cards) == 1 else "requested areas"
    if not focused:
        subject = "displayed leader" if len(cards) == 1 else "displayed leaders"
    verb = "is" if len(cards) == 1 else "are"
    text = f"Using the {basis}, the {subject} {verb} {values}."
    if len(scored) != len(cards):
        missing = _names(_name(card) for card in cards if _number(card.get("score")) is None)
        text += f" A comparable score is unavailable for {missing}."
    if len(scored) > 1 and scored[0][0].get("score") == scored[1][0].get("score"):
        text += f" {_names(_name(card) for card, _ in scored if card['score'] == scored[0][0]['score'])} share the same displayed score."
    return text


_TOPIC_FACTS = {
    "access": ("customer_access", "subway_distance", "walkability"),
    "transit": ("subway_distance", "subway_daypart", "subway_ridership"),
    "competition": ("competition", "competition_balance"),
    "demand": ("demand", "pedestrian_activity", "population"),
    "customer_fit": ("customer_fit", "median_household_income", "jobs"),
    "rent": ("rent",),
    "survival": ("survival",),
    "general": ("demand", "customer_fit", "competition_balance"),
}


def _fact_text(item):
    value = _number(item.get("value"))
    if value is None or item.get("status") not in {"observed", "modeled", "user_entered"}:
        return None
    if item.get("id") == "median_household_income" and item["value"] == 250001:
        return "the reported median household income is $250,000 or more"
    unit = item.get("unit") or ""
    value = f"{value}{unit}" if unit.startswith(("/", "%")) else f"{value} {unit}".strip()
    if item.get("id") == "competition":
        return f"the inspection inventory records {value} with this cuisine label in the tract"
    return f"{item['label'].lower()} is {value}"


def _fact_map(card):
    return {item["id"]: item for item in _dossier(card).get("evidence") or []}


def _evidence_text(cards, topic, basis):
    if not cards:
        return "Choose an area to review its evidence."
    if topic not in _TOPIC_FACTS or topic == "general":
        topic = "access" if "customer access" in basis.replace("-", " ") else "general"
    keys = _TOPIC_FACTS[topic]
    lines = []
    for card in cards[:3]:
        facts = _fact_map(card)
        details = [_fact_text(facts[key]) for key in keys if key in facts]
        details = [detail for detail in details if detail][:2 if len(cards) == 1 else 1]
        if details:
            if topic == "access" and not _fact_text(facts.get("customer_access", {})):
                lines.append(f"The modeled customer-access index is unavailable for {_name(card)}.")
            lines.append(f"For {_name(card)}, {_names(details)}.")
        elif topic == "survival" and facts.get("survival", {}).get("detail_status") == "awaiting_artifact":
            lines.append(f"The survival model is awaiting its trained artifact for {_name(card)}.")
        else:
            label = {"general": "supporting", "rent": "reported occupied-rent"}.get(topic, topic.replace("_", " "))
            lines.append(f"{label.capitalize()} evidence is unavailable for {_name(card)}.")
    if topic in {"general", "demand"}:
        if len(cards) == 1 and (cards[0].get("label") or "").startswith("Tied across ranks"):
            lines.append("This area shares its displayed score with another tract.")
        lines.append("The screening components use activity and fit proxies. Verify customer demand during your intended trading period.")
    if topic == "competition":
        lines.append("Cuisine counts describe the recorded labels and their coverage. A site visit can verify current competitors.")
    return " ".join(lines)


def _property_text(cards, topic):
    if not cards:
        return "There are no property results in the current inventory under these filters. Confirm availability and terms at a specific address."
    gates = [_dossier(card).get("property_gates") or {} for card in cards]
    for card, gate in zip(cards, gates):
        lead = gate.get("lead")
        if not lead:
            continue
        address = lead.get("address")
        label = address if address and address != "Address Pending" else lead.get("title") or "A storefront lead"
        asking_rent = _money(lead.get("asking_rent"))
        asking_price = _money(lead.get("asking_price"))
        quote = f" with a source-reported asking rent of {asking_rent} per month" if asking_rent else ""
        if not quote and asking_price:
            quote = f" with a source-reported asking price of {asking_price}"
        status = "Confirm availability and current terms with the listing source before arranging a tour."
        if lead.get("availability_verified") is True:
            status = "Confirm current terms, permitted use, and facilities before committing to the premises."
        budget = " The quoted amount fits the entered limit." if quote and lead.get("budget_evidence") == "within_entered_limit" else ""
        return f"{label} is a sourced lead in {_name(card)}{quote}.{budget} {status}"
    if topic == "property_search":
        first = "The search returned no source-reported listings across the screened tracts under these filters."
    else:
        first = f"The search returned no source-reported listings for {_names(_name(card) for card in cards)} under these filters."
    context = []
    if any(gate.get("registry_count") for gate in gates):
        context.append("historical registry records")
    if any(gate.get("synthetic_count") for gate in gates):
        context.append("synthetic scenarios")
    if context:
        first += f" {_names(context).capitalize()} are available as research context."
    if topic == "rent" and len(cards) == 1:
        reported = _fact_map(cards[0]).get("rent", {})
        rent = _money(reported.get("value")) if reported.get("status") == "observed" else None
        if rent is not None:
            first += f" The area's reported occupied-storefront median is {rent} per square foot per month."
    return f"{first} Find a real address and confirm availability, asking terms, and permitted use."


_FINANCE_LABELS = {"other_fixed_costs": "monthly fixed costs excluding rent", "variable_cost_pct": "variable cost percentage",
                   "operating_days": "operating days per month"}


def _finance_text(cards, finance):
    if finance is None:
        finance = next((item for card in cards if (item := _dossier(card).get("break_even"))), {})
    if finance.get("status") == "not_applicable":
        return "This break-even calculator uses a lease scenario. A purchase analysis needs financing and ongoing property costs."
    covers = _number(finance.get("required_covers_per_day"))
    sales = _money(finance.get("required_monthly_sales"))
    if finance.get("status") != "ready" or covers is None or sales is None:
        missing = [_FINANCE_LABELS[key] for key in finance.get("missing_inputs") or [] if key in _FINANCE_LABELS]
        return f"To calculate break-even, enter {_names(missing or list(_FINANCE_LABELS.values()))}."
    rent = _money(finance.get("rent_monthly", finance.get("rent_target")))
    rent_basis = "source-reported asking rent" if finance.get("basis") == "source_reported_asking_rent" else "assumed monthly rent"
    spending = _money(finance.get("guest_spend"))
    assumptions = [f"{rent_basis} of {rent}"] if rent else []
    if spending:
        assumptions.append(f"{spending} per guest")
    intro = f"With {_names(assumptions)}, break-even" if assumptions else "Break-even"
    return f"{intro} is {covers} covers per operating day and {sales} in monthly sales, based on the entered costs and operating days."


def _scenario_text(scenario):
    if not scenario:
        return "Give me a guest spend or trading period to compare against the current assumptions."
    before, after = scenario.get("before_label"), scenario.get("after_label")
    if before and before == after:
        return "That repeats the current assumptions. Give me a different spend or trading period to test."
    context = f"Comparing {before} with {after}. " if before and after else ""
    if scenario.get("comparison_unavailable"):
        return f"{context}Comparable rankings are unavailable for these scenarios with the selected method."
    if scenario.get("inert"):
        return f"{context}The selected ranking method is insensitive to this input. Use a ranking method that incorporates it to assess the change."
    entrants, departures = scenario.get("entrants") or [], scenario.get("departures") or []
    changes = []
    if entrants:
        changes.append(f"{_names(entrants)} {'joins' if len(entrants) == 1 else 'join'} the set that can make the top three by score.")
    if departures:
        changes.append(f"{_names(departures)} {'leaves' if len(departures) == 1 else 'leave'} that top-three set.")
    if not changes:
        changes.append("The comparison found no top-three membership change among tracts scored in both scenarios.")
        before_ids, after_ids = scenario.get("before_ids") or [], scenario.get("after_ids") or []
        if set(before_ids) == set(after_ids) and before_ids != after_ids:
            changes.append("The displayed order changed.")
    if scenario.get("tied_cutoff"):
        changes.append("At least one scenario has a tie spanning third place.")
    if scenario.get("matched") is False and before and after:
        changes.append("Guest spend and trading period changed together. Test one at a time to isolate each effect.")
    return f"{context}{' '.join(changes)}"


def compose_answer(intent, topic, cards, *, ranking_basis, finance=None, scenario=None):
    """Render only facts, ranks, and scenarios resolved by the server."""
    basis = (ranking_basis or "selected ranking method").lower()
    if intent == "recommend":
        return _rank_text(cards, basis, focused=topic == "focused_area")
    if intent == "compare":
        if topic in _TOPIC_FACTS and topic != "general":
            return _evidence_text(cards, topic, basis)
        return _rank_text(cards, basis, focused=True)
    if intent == "why" and topic == "next_check":
        return _property_text(cards, topic)
    if intent == "why":
        return _evidence_text(cards, topic, basis)
    if intent == "property":
        return _property_text(cards, topic)
    if intent == "break_even":
        return _finance_text(cards, finance)
    if intent == "what_if":
        return _scenario_text(scenario)
    return "Ask me to shortlist areas, compare them, explain the evidence, check property leads, or calculate break-even."
