import pytest

from advisor_chat import parse_message, resolve_pending


ELMHURST = "36081026901"
OTHER_ELMHURST = "36081026902"
LIC = "36081001902"
OTHER_LIC = "36081002000"
GREENWICH = "36061000061"
ASTORIA_CENTRAL = "36081006300"
ASTORIA_NORTH = "36081009500"
CANDIDATES = [
    {"id": ELMHURST, "name": "Elmhurst Tract 269.01", "borough": "Queens"},
    {"id": OTHER_ELMHURST, "name": "Elmhurst Tract 269.02", "borough": "Queens"},
    {"id": LIC, "name": "Long Island City-Hunters Point Tract 19.02", "borough": "Queens"},
    {"id": OTHER_LIC, "name": "Long Island City-Hunters Point Tract 20", "borough": "Queens"},
    {"id": GREENWICH, "name": "Greenwich Village Tract 61", "borough": "Manhattan"},
    {"id": ASTORIA_CENTRAL, "name": "Astoria (Central) Tract 63", "borough": "Queens", "neighborhood": "Astoria (Central)"},
    {"id": ASTORIA_NORTH, "name": "Astoria (North)-Ditmars-Steinway Tract 95", "borough": "Queens",
     "neighborhood": "Astoria (North)-Ditmars-Steinway"},
]
ASSUMPTIONS = {"borough": "All NYC", "cuisine": "italian", "average_check": 35, "daypart": "evening", "deal_type": "lease"}
PREVIOUS = {"intent": "recommend", "changes": {"cuisine": "italian"}, "candidate_ids": [ELMHURST, LIC, GREENWICH]}


def parse(message, **options):
    return parse_message(message, options.pop("assumptions", ASSUMPTIONS),
                         candidates=options.pop("candidates", CANDIDATES), **options)


@pytest.mark.parametrize(("message", "intent"), [
    ("Apply this scenario.", "apply_scenario"), ("Keep that preview", "apply_scenario"),
    ("Discard this preview.", "discard_scenario"), ("Go back to the baseline", "discard_scenario"),
    ("Undo the applied scenario.", "undo_scenario"), ("Undo", "undo_scenario"),
])
def test_scenario_controls_are_explicit_bounded_commands(message, intent):
    result = parse(message)
    assert result["intent"] == intent
    assert result["changes"] == {} and result["candidate_ids"] == []
    assert parse(message + " and set the rent to $9,000")["intent"] == "clarify"


def test_what_if_can_target_the_single_active_tract_without_using_the_map():
    result = parse("What if I charge $45 there?", previous={**PREVIOUS, "candidate_ids": [LIC]})
    assert result["intent"] == "what_if" and result["candidate_ids"] == [LIC]
    assert parse("What if I charge $45 there?", previous=PREVIOUS)["intent"] == "clarify"


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


def test_followups_keep_the_shortlist_after_a_single_tract_answer():
    previous = {**PREVIOUS, "candidate_ids": [ELMHURST], "shortlist_ids": PREVIOUS["candidate_ids"]}
    assert parse("Why the second one?", previous=previous)["candidate_ids"] == [LIC]
    assert parse("Compare the first two.", previous=previous)["candidate_ids"] == [ELMHURST, LIC]
    assert parse("Compare those areas.", previous=previous)["candidate_ids"] == PREVIOUS["candidate_ids"]
    assert parse("Can I tour it?", previous=previous)["candidate_ids"] == [ELMHURST]


def test_repeated_scope_does_not_inherit_changes_but_a_broad_search_resets_focus():
    assert parse("What about Brooklyn?", previous=PREVIOUS)["changes"] == {"borough": "Brooklyn"}
    assert parse("French in Queens?", previous=PREVIOUS)["changes"] == {"borough": "Queens", "cuisine": "french"}
    assert parse("Lunch?", previous=PREVIOUS)["changes"] == {"daypart": "lunch"}
    assert parse("Find a lease in Brooklyn under $9k.", previous=PREVIOUS)["candidate_ids"] == []
    assert parse("Show live listings.", previous=PREVIOUS)["candidate_ids"] == []
    single = {**PREVIOUS, "candidate_ids": [LIC]}
    assert parse("Can I tour it?", previous=single)["candidate_ids"] == [LIC]


def test_named_tracts_resolve_exact_ids():
    assert parse("Compare Elmhurst Tract 269.01 and LIC Tract 19.02.")["candidate_ids"] == [ELMHURST, LIC]
    assert parse("Why is 36081026901 ranked here?")["candidate_ids"] == [ELMHURST]
    assert parse("Explain Elmhurst Tract 269.99.")["intent"] == "clarify"
    assert parse("Explain Greenwich Village Tract 61.", assumptions={**ASSUMPTIONS, "borough": "Queens"})["intent"] == "clarify"
    assert parse("Explain Greenwich Village Tract 61 in Manhattan.", assumptions={**ASSUMPTIONS, "borough": "Queens"})["candidate_ids"] == [GREENWICH]


def test_neighborhood_search_uses_all_matching_tracts_without_guessing_a_representative():
    astoria = [{"label": "Astoria", "ids": [ASTORIA_CENTRAL, ASTORIA_NORTH]}]
    result = parse("Where in Astoria should I look for a $35 Italian dinner spot?")
    assert result["intent"] == "recommend"
    assert result["candidate_ids"] == []
    assert result["area_groups"] == astoria
    assert result["changes"] == {"cuisine": "italian", "average_check": 35, "daypart": "evening"}
    assert parse("What if I charge $45 in Astoria?")["area_groups"] == astoria
    assert parse("Tell me about Elmhurst.")["area_groups"] == [{"label": "Elmhurst", "ids": [ELMHURST, OTHER_ELMHURST]}]


def test_neighborhood_field_can_supply_aliases_without_a_tract_display_name():
    candidates = [{"id": identifier, "borough": "Queens", "neighborhood": "Astoria"}
                  for identifier in (ASTORIA_CENTRAL, ASTORIA_NORTH)]
    assert parse("Where should I look in Astoria?", candidates=candidates)["area_groups"] == [
        {"label": "Astoria", "ids": [ASTORIA_CENTRAL, ASTORIA_NORTH]},
    ]


def test_neighborhood_comparison_supports_neighborhoods_and_exact_tracts():
    result = parse("Compare Astoria and Long Island City.")
    assert result["intent"] == "compare"
    assert result["candidate_ids"] == []
    assert result["area_groups"] == [
        {"label": "Astoria", "ids": [ASTORIA_CENTRAL, ASTORIA_NORTH]},
        {"label": "Long Island City", "ids": [LIC, OTHER_LIC]},
    ]
    result = parse("Compare LIC and Elmhurst Tract 269.01.")
    assert result["area_groups"][0]["label"] == "Long Island City"
    assert result["area_groups"][1] == {"label": "Elmhurst Tract 269.01", "ids": [ELMHURST]}


def test_neighborhood_name_shared_by_boroughs_requires_scope():
    candidates = [*CANDIDATES, {"id": "36047009500", "name": "Astoria Tract 95", "borough": "Brooklyn"}]
    assert parse("Where should I look in Astoria?", candidates=candidates)["intent"] == "clarify"
    result = parse("Where should I look in Astoria, Queens?", candidates=candidates)
    assert result["area_groups"][0]["ids"] == [ASTORIA_CENTRAL, ASTORIA_NORTH]


@pytest.mark.parametrize("message", [
    "Compare Astoria and Astoria (Central).",
    "Compare Astoria and Long Island City in Manhattan.",
    "Compare Astoria, Elmhurst, and Long Island City.",
    "Compare Astoria 999 and Long Island City.",
    "Where should I look near Astoria?",
    "Where should I look, but not in Astoria?",
    "How many covers do I need to break even in Astoria?",
])
def test_neighborhood_scope_fails_closed_for_conflicting_or_unsupported_requests(message):
    result = parse(message)
    assert result["intent"] == "clarify"
    assert result["changes"] == {}
    assert "area_groups" not in result


def test_neighborhood_group_size_is_bounded():
    candidates = [{"id": f"36081{index:06d}", "name": f"Astoria Tract {index}", "borough": "Queens"}
                  for index in range(121)]
    assert parse("Where should I look in Astoria?", candidates=candidates)["intent"] == "clarify"


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


@pytest.mark.parametrize('message', [
    'Where should I look anywhere but Manhattan?',
    "Where should I look? I don't want Manhattan.",
    'Where should I open a non-halal restaurant?',
    'Where should I look in Queens with no bars nearby?',
    'Find a commercial lease in Queens that is step-free and has a hood.',
    'Find me a place under 5 minutes from a subway.',
    'Find areas in Queens with a 40-50 per guest check.',
    'What if I charge $35.001 per guest?',
])
def test_requirements_are_never_silently_dropped(message):
    result = parse(message)
    assert result['intent'] == 'clarify'
    assert result['changes'] == {}
    assert result['candidate_ids'] == []


def test_dietary_identity_and_exact_cuisines_survive_chat_parsing():
    result = parse('Where should I open a halal Thai restaurant in Queens?')
    assert result['changes'] == {'borough': 'Queens', 'dietary': 'halal', 'cuisine': 'thai'}
    result = parse('Where should I open a gluten-free pizza place in Queens?')
    assert result['changes']['dietary'] == 'gluten_free'
    assert result['changes']['cuisine'] == 'pizza'
    assert parse('Where should I open a Pakistani restaurant?')['changes']['cuisine'] == 'pakistani'


def test_clarification_replies_complete_the_original_question():
    original = parse('Where should I look for an Italian or Thai dinner spot in Queens?')
    assert len(original['actions']) == 2
    question = resolve_pending('Italian', original['pending'])
    result = parse(question)
    assert result['changes'] == {'borough': 'Queens', 'cuisine': 'italian', 'daypart': 'evening'}
    original = parse('Where should I look for an Italian restaurant in Queens with $90?')
    question = resolve_pending('$45 per guest', original['pending'])
    assert parse(question)['changes'] == {'borough': 'Queens', 'cuisine': 'italian', 'average_check': 45}
    assert resolve_pending('Show me Brooklyn instead.', original['pending']) is None


def test_neighborhood_property_search_and_comparison_followups():
    result = parse('Find a lease in Astoria under $9k per month.')
    assert result['intent'] == 'property'
    assert result['changes']['rent_cap'] == 9000
    assert result['area_groups'][0]['ids'] == [ASTORIA_CENTRAL, ASTORIA_NORTH]
    assert parse('Which of those is better?', previous=PREVIOUS)['intent'] == 'compare'
    assert parse('Compare the first with the second.', previous=PREVIOUS)['candidate_ids'] == [ELMHURST, LIC]
