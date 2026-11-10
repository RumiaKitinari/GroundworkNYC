import pytest

from advisor_chat import parse_message


ELMHURST = "36081026901"
OTHER_ELMHURST = "36081026902"
LIC = "36081001902"
GREENWICH = "36061000061"
CANDIDATES = [
    {"id": ELMHURST, "name": "Elmhurst Tract 269.01", "borough": "Queens"},
    {"id": OTHER_ELMHURST, "name": "Elmhurst Tract 269.02", "borough": "Queens"},
    {"id": LIC, "name": "Long Island City-Hunters Point Tract 19.02", "borough": "Queens"},
    {"id": GREENWICH, "name": "Greenwich Village Tract 61", "borough": "Manhattan"},
]
ASSUMPTIONS = {"borough": "All NYC", "cuisine": "italian", "average_check": 35, "daypart": "evening", "deal_type": "lease"}
PREVIOUS = {"intent": "recommend", "changes": {"cuisine": "italian"}, "candidate_ids": [ELMHURST, LIC, GREENWICH]}


def parse(message, **options):
    return parse_message(message, options.pop("assumptions", ASSUMPTIONS), candidates=CANDIDATES, **options)


@pytest.mark.parametrize(("message", "intent", "changes", "topic"), [
    ("Where should I start looking?", "recommend", {}, None),
    ("Where in Queens should I open?", "recommend", {"borough": "Queens"}, None),
    ("Where should I look for a $35 Italian dinner spot in Queens?", "recommend",
     {"borough": "Queens", "cuisine": "italian", "average_check": 35, "daypart": "evening"}, None),
    ("What would change at $50 per guest for dinner?", "what_if", {"average_check": 50, "daypart": "evening"}, None),
    ("What if I charge $45?", "what_if", {"average_check": 45}, None),
    ("What if I charge around $45.50?", "what_if", {"average_check": 45.5}, None),
    ("What if we try breakfast service?", "what_if", {"daypart": "morning"}, None),
    ("What should I verify before touring?", "why", {}, "next_check"),
    ("How many covers per day to break even?", "break_even", {}, None),
    ("What if rent is $9,000?", "break_even", {"rent_cap": 9000}, "rent_scenario"),
    ("Any listings under $9k monthly rent?", "property", {"rent_cap": 9000}, None),
    ("Find a lease in Queens under $9,000.", "property", {"borough": "Queens", "rent_cap": 9000}, None),
    ("What's the reported rent?", "why", {}, "rent"),
    ("What data do you have for walking access?", "why", {}, "access"),
    ("Compare the number of same-cuisine competitors.", "compare", {}, "competition"),
])
def test_supported_intents_and_explicit_changes(message, intent, changes, topic):
    plan = parse(message, previous=PREVIOUS)
    assert plan["intent"] == intent
    assert plan["changes"] == changes
    assert plan["topic"] == topic
    assert plan["clarification"] is None


def test_followups_use_distinct_saved_map_and_previous_references():
    options = {"previous": PREVIOUS, "selected_ids": [LIC, OTHER_ELMHURST], "map_selected_id": GREENWICH}
    assert parse("Compare my saved areas.", **options)["candidate_ids"] == [LIC, OTHER_ELMHURST]
    assert parse("Why this area?", **options)["candidate_ids"] == [GREENWICH]
    assert parse("Why the first one?", **options)["candidate_ids"] == [ELMHURST]
    assert parse("Can I tour the first one?", **options)["candidate_ids"] == [ELMHURST]
    assert parse("Compare these areas.", **options)["candidate_ids"] == PREVIOUS["candidate_ids"]
    assert parse("Compare the first two.", **options)["candidate_ids"] == [ELMHURST, LIC]
    assert parse("Tell me about that area.", **options)["intent"] == "clarify"


def test_repeated_scope_does_not_inherit_changes_but_a_broad_search_resets_focus():
    assert parse("What about Brooklyn?", previous=PREVIOUS)["changes"] == {"borough": "Brooklyn"}
    assert parse("French in Queens?", previous=PREVIOUS)["changes"] == {"borough": "Queens", "cuisine": "french"}
    assert parse("Lunch?", previous=PREVIOUS)["changes"] == {"daypart": "lunch"}
    assert parse("Find a lease in Brooklyn under $9k.", previous=PREVIOUS)["candidate_ids"] == []
    assert parse("Show live listings.", previous=PREVIOUS)["candidate_ids"] == []
    single = {**PREVIOUS, "candidate_ids": [LIC]}
    assert parse("Can I tour it?", previous=single)["candidate_ids"] == [LIC]


def test_named_areas_resolve_exact_ids_and_avoid_neighborhood_guessing():
    assert parse("Compare Elmhurst Tract 269.01 and LIC Tract 19.02.")["candidate_ids"] == [ELMHURST, LIC]
    assert parse("Why is 36081026901 ranked here?")["candidate_ids"] == [ELMHURST]
    assert parse("Tell me about Elmhurst.")["intent"] == "clarify"
    assert parse("Explain Elmhurst Tract 269.99.")["intent"] == "clarify"
    assert parse("Explain Greenwich Village Tract 61.", assumptions={**ASSUMPTIONS, "borough": "Queens"})["intent"] == "clarify"
    assert parse("Explain Greenwich Village Tract 61 in Manhattan.", assumptions={**ASSUMPTIONS, "borough": "Queens"})["candidate_ids"] == [GREENWICH]


@pytest.mark.parametrize("message", [
    "Where should I open in Hoboken?", "What about a restaurant in Tokyo?", "Recommend in Queens or Saratoga.",
    "Find areas in Queens and Brooklyn.", "Would you recommend citywide or Queens?", "What about $90?",
    "What if I charge $45 or $65?", "What if we spend $35 per guest or $50 per guest?",
    "Can I lease for $150,000 monthly rent?", "Find a 2,000 square foot storefront in Queens.",
    "Where should I buy a property in Queens?", "What if lunch and dinner?", "What about Queens, excluding Elmhurst?",
    "What if not dinner?", "Where should I open a Scandinavian restaurant?", "Where should I open a Thai or Italian restaurant?",
    "Write a song about Brooklyn.", "Who eats lunch?", "Where can I start without an API key?", "x" * 501,
])
def test_ambiguous_or_unsupported_questions_clear_the_execution_plan(message):
    plan = parse(message, previous=PREVIOUS)
    assert plan["intent"] == "clarify"
    assert plan["changes"] == {}
    assert plan["candidate_ids"] == []
    assert plan["clarification"]


def test_lease_override_cannot_run_against_a_purchase_search():
    assert parse("Find a lease for $9k per month.", assumptions={**ASSUMPTIONS, "deal_type": "purchase"})["intent"] == "clarify"
    assert parse("Show storefronts for rent.", assumptions={**ASSUMPTIONS, "deal_type": "purchase"})["intent"] == "clarify"


def test_purchase_request_does_not_return_leases():
    assert parse("Show properties for purchase in Queens.")["intent"] == "clarify"
    both = {**ASSUMPTIONS, "deal_type": "either"}
    assert parse("Show properties for sale in Queens.", assumptions=both)["changes"]["deal_type"] == "purchase"
    assert parse("Show storefronts for rent in Queens.", assumptions=both)["changes"]["deal_type"] == "lease"
