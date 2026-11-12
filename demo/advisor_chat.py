"""Parse bounded site-advisor questions into explicit, read-only operations."""

from collections import defaultdict
from functools import lru_cache
import re
from unicodedata import combining, normalize

from scoring import CUISINES, CUISINE_ALIASES


_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_SCENARIO_COMMANDS = {
    "apply_scenario": re.compile(r"(?:apply|use|keep|adopt) (?:this |that |the )?(?:scenario|preview)(?: settings)?[.!?]?"),
    "discard_scenario": re.compile(r"(?:(?:discard|cancel|exit) (?:this |that |the )?(?:scenario|preview)|(?:go |switch )?back to (?:the )?(?:baseline|applied settings))[.!?]?"),
    "undo_scenario": re.compile(r"(?:undo|revert)(?: (?:the |that |my |last )?(?:applied scenario|scenario|change))?[.!?]?"),
}
_BOROUGHS = {
    "Bronx": ("bronx", "bronx county"),
    "Brooklyn": ("brooklyn", "kings county"),
    "Manhattan": ("manhattan", "new york county"),
    "Queens": ("queens", "queens county"),
    "Staten Island": ("staten island", "richmond county"),
    "": ("nyc", "new york city", "all nyc", "all of nyc", "citywide", "five boroughs", "all boroughs"),
}
_DAYPARTS = {
    "all_day": ("all day", "whole day", "throughout the day"),
    "morning": ("morning", "mornings", "breakfast service"),
    "lunch": ("lunch", "lunchtime", "lunch service", "midday"),
    "evening": ("dinner", "dinners", "evening", "evenings", "dinner service", "supper"),
}
_SHORT_AREAS = {"long island city": "lic", "upper west side": "uws", "upper east side": "ues"}
_DIETARY = {"vegan": ("vegan", "plant based", "plant-based"), "vegetarian": ("vegetarian",),
            "halal": ("halal",), "kosher": ("kosher",), "gluten_free": ("gluten free", "gluten-free")}
_EXCLUSION = re.compile(r"\b(?:anywhere but|everywhere but|other than|apart from|outside (?:of )?|leave out|omit)\b|\b(?:don't|do not|never)\s+(?:want|show|include|recommend|search|use|consider)\b|\b(?:no|without)\s+(?:nearby\s+)?(?:bars?|competitors?|restaurants?)\b")
_FACILITIES = re.compile(r"\b(?:step[- ]free|wheelchair|accessible entrance|ada compliant|hood|ventilation|outdoor patio|patio|outdoor seating)\b")
_DISTANCE_REQUIREMENT = re.compile(r"\b(?:under|within|less than|at most|no more than)\s+\d+(?:\.\d+)?\s*(?:minutes?|blocks?|miles?|meters?|metres?|feet)\b")
_OUTSIDE_NYC = re.compile(
    r"\b(?:outside (?:of )?(?:nyc|new york city|the five boroughs)|new jersey|jersey city|hoboken|newark|"
    r"yonkers|westchester|long island(?! city)|nassau county|suffolk county|boston|miami|philadelphia|"
    r"los angeles|san francisco|austin|chicago|seattle|toronto)\b"
)
_UNSUPPORTED = re.compile(
    r"\b(?:exclude|excluding|except|avoid|weekends?|weekdays?|late[- ]night|after midnight|brunch only|"
    r"buying|purchase budget|buy (?:a |the )?(?:site|property|space|location)|sq\.?\s*ft\b|square f(?:eet|oot)|"
    r"seating capacity|\d+\s+seats|food trucks?|ghost kitchens?|delivery only|takeout only|outdoor seating|"
    r"fine[- ]dining|fast[- ]casual|quick[- ]service|counter[- ]service|cocktail bar|tourists?|office workers|"
    r"audience|income threshold|school ratings?|crime|safest|safe (?:area|site|neighbou?rhood)|safety ratings?|guarantee(?:d)?|"
    r"forecast (?:profits?|sales|revenue)|opening (?:at|after|before)|\d\s*(?:a\.?m\.?|p\.?m\.?)\b|"
    r"(?:prioriti[sz]e|optimi[sz]e|sort|rank) (?:by|for)|(?:least|lowest) competition|highest foot traffic|"
    r"stop serving|not (?:in |at |for |the )?(?:bronx|brooklyn|manhattan|queens|staten island|lunch|dinner|morning|evening)|"
    r"ignore (?:your |all |the |previous )?(?:instructions|rules)|system prompt|api key|shell command)\b"
)
_PLACE_PREFIX = re.compile(r"\b(?:in|near|around|within)\s+(?:(?:the|both|all of)\s+)?")
_NON_PLACE = re.compile(
    r"(?:this|that|these|those|my|our|your|here|there|morning|evening|lunch|dinner|budget|range|data|"
    r"results|shortlist|ranking|model|report|list|order|scope|sales|revenue|covers|rent|person|common|"
    r"general|practice|terms|comparison|detail|current search|the first|top three|\d+ (?:ways?|scenarios?))\b"
)
_MONEY = re.compile(r"(?<![\w$.,])(?P<currency>\$\s*)?(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)(?P<scale>\s*[km])?(?!\w|[.,]\d)")
_GUEST_LEFT = re.compile(r"\b(?:average (?:guest )?(?:spend|check)|avg\.? (?:spend|check)|guest spend|check size|per guest)\b(?:\s+(?:of|at|to|from|is|be))*\s*[:=]?\s*$")
_GUEST_RIGHT = re.compile(r"\s*(?:(?:dollars?|bucks)\s+)?(?:(?:per|a|/)\s*(?:guest|person|head|diner)|each\b|(?:for|at) (?:dinner|lunch|breakfast)\b|(?:average )?check\b)")
_CHARGE_LEFT = re.compile(r"\bcharg(?:e|es|ing)\s+(?:(?:about|around|roughly|approximately)\s+)?$")
_FOOD_RIGHT = re.compile(r"\b(?:restaurant|concept|spot|menu|dinner|lunch|breakfast)\b")
_DIRECT_SCENARIO = re.compile(r"(?:and |at |for )?(?:all.day|morning|lunch|midday|dinner|evening|supper|\$?[\d.,]+\s+(?:per|a)\s+(?:guest|person|head|diner))\s*[?.!]?")
_RENT_LEFT = re.compile(r"\b(?:(?:monthly )?rent(?: cap| budget)?|lease budget|monthly budget)\b(?:\s+(?:of|at|to|from|is|be|were|under|below|up to))*\s*[:=]?\s*$")
_RENT_RIGHT = re.compile(r"\s*(?:(?:for|in|on) (?:monthly )?)?(?:monthly rent\b|rent\b|lease budget\b)")
_MONTH_RIGHT = re.compile(r"\s*(?:(?:per|a|/)\s*(?:month|mo\b)|monthly\b)")
_RENT_WORD = re.compile(r"\b(?:rent|lease|monthly budget)\b")
_CAP = re.compile(r"\b(?:under|below|up to|at most|no more than|max(?:imum)?|cap|budget)\b")
_PRICE_CAP = re.compile(r"\b(?:under|below|up to|at most|no more than|max(?:imum)?)\s*$")
_WHAT_IF = re.compile(r"\b(?:what if|what would change|how would (?:it|that|this|the shortlist) change|what about|how about|instead|suppose)\b")
_FIND = re.compile(
    r"\b(?:recommend(?:ations?)?|shortlist|where (?:in (?:[a-z][a-z ]{0,45} )?)?(?:should|could|would|can) (?:i|we) (?:look|start|open|"
    r"search|find)|best (?:places?|areas?|sites?|locations?|neighbou?rhoods?)|"
    r"(?:find|show|suggest) (?:me )?(?:a |some |the |good |potential )?(?:areas?|sites?|locations?|neighbou?rhoods?))\b"
)
_COMPARE = re.compile(r"\b(?:compare|versus|vs\.?|side.by.side|difference between|which (?:one|of (?:these|those|them)) (?:is |are |would be )?better)\b")
_PURCHASE_TRANSACTION = re.compile(r"\b(?:for (?:purchase|sale)|purchase (?:options?|listings?|properties|price))\b")
_LEASE_TRANSACTION = re.compile(r"\b(?:leas(?:e|es|ing)|for rent|rental properties|asking rent)\b")
_PROPERTY = re.compile(r"\b(?:leas(?:e|es|ing)|listings?|storefronts?|tour(?:ing)?|asking rent|available (?:space|properties)|rental properties|(?:find|show|any) (?:commercial |available )?properties|for (?:purchase|sale|rent))\b")
_PROPERTY_SEARCH = re.compile(r"\b(?:(?:find|show|search for|look for|any) (?:me )?(?:a |an |the )?(?:(?:available|commercial|live|verified|sourced) )?(?:leases?|spaces?|storefronts?|listings?|properties)|(?:what|where) can (?:i|we) lease)\b")
_BREAK_EVEN = re.compile(r"\b(?:break[ -]?even|covers? per (?:day|night)|how many (?:covers|customers)|operating economics|(?:sales|revenue) (?:needed|required|to cover))\b")
_WHY = re.compile(r"\b(?:why|evidence|rationale|explain|what supports|how (?:good|strong|reliable)|where (?:does|did) .+ come from|sources?|tell me (?:more )?about)\b")
_NEXT = re.compile(r"\b(?:next (?:step|check)|verify|due diligence|before (?:i |we )?(?:tour|sign|visit)|what should (?:i|we) check|permits?|zoning)\b")
_COMPETITION = re.compile(r"\b(?:competitors?|competition|saturation|same.cuisine)\b")
_ACCESS = re.compile(r"\b(?:customer access|walkability|walking|transit|subway|foot traffic|pedestrian access)\b")
_RENT_EVIDENCE = re.compile(r"\b(?:rent benchmarks?|reported rent|average rent|typical rent|market rent|how much is (?:the )?rent|what is (?:the )?rent|rent evidence|rent data|affordable)\b")
_SAVED = re.compile(r"\b(?:saved (?:areas?|sites?|tracts?|locations?|places?|options?)|(?:my|our) saves)\b")
_MAP = re.compile(r"\b(?:(?:this|selected|highlighted|current|map.selected) (?:area|site|location|tract|one)|map selection)\b")
_PRIOR_GROUP = re.compile(r"\b(?:these|those|them|previous (?:shortlist|areas?|options?|results?)|earlier (?:shortlist|areas?|options?|results?))\b")
_PRIOR_ONE = re.compile(r"\b(?:there|it|that (?:area|site|location|tract|one))\b")
_ORDINALS = {"first": 0, "1st": 0, "top": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
             "fourth": 3, "4th": 3, "last": -1}
_ORDINAL = re.compile(r"\b(first|1st|top|second|2nd|third|3rd|fourth|4th|last)\b(?=\s+(?:one|area|site|tract|location|option)\b|\s+(?:and|with|versus)\s+(?:the\s+)?(?:first|second|third|fourth|last)\b|[?.!]?$)")
_TOP_COUNT = re.compile(r"\b(?:first|top) (two|three|four|2|3|4)\b")
_TOP_COUNTS = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
_COORDINATOR = re.compile(r",?\s+(?:and|or|versus|vs\.?)\s+")
_AREA_EXCLUSION = re.compile(r"\b(?:not|without|rather than|instead of)\s+(?:(?:in|near|around|within)\s+)?(?:the\s+)?$")
_UNRESOLVED_TRACT_SUFFIX = re.compile(r"\s+\d+(?:\.\d+)?(?=$|[?.!,]|\s+(?:and|or|versus|vs\.?|with)\b)")
_GENERIC_AREA_FRAGMENTS = {"co", "green", "park", "unknown"}
_NEIGHBORHOOD_LIMIT = 120
_MONEY_RANGE = re.compile(r"(?<![\w.])\$?\d+(?:\.\d+)?\s*(?:-|to|through)\s*\$?\d+(?:\.\d+)?")


def _normalized(value):
    value = normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in value if not combining(char)).translate(
        str.maketrans({"’": "'", "–": "-", "—": "-", "−": "-"})).split())


def _tokens(value):
    return tuple(_TOKEN.findall(_normalized(value)))


def _alias_index(groups):
    index = {_tokens(alias): label for label, aliases in groups.items() for alias in aliases}
    # Explicit catalog names take precedence over aliases shared with broader categories.
    index.update({_tokens(label.replace("_", " ")): label for label in groups if label})
    return index


_BOROUGH_INDEX = _alias_index(_BOROUGHS)
_DAYPART_INDEX = _alias_index(_DAYPARTS)
_DIETARY_INDEX = _alias_index(_DIETARY)
_CUISINE_INDEX = _alias_index({key: (key.replace("_", " "), *CUISINE_ALIASES.get(key, ()))
                               for key in CUISINES if key not in {"any", "custom", "vegan", "vegetarian"}})


def _matches(text, index, width):
    words = list(_TOKEN.finditer(text))
    tokens = tuple(word.group() for word in words)
    start = 0
    while start < len(words):
        for stop in range(min(start + width, len(words)), start, -1):
            phrase = tokens[start:stop]
            if phrase in index:
                yield index[phrase], words[start].start(), words[stop - 1].end()
                start = stop
                break
        else:
            start += 1


def _masked(text, matches):
    letters = list(text)
    for _, start, stop in matches:
        letters[start:stop] = " " * (stop - start)
    return "".join(letters)


@lru_cache(maxsize=2)
def _candidate_index(candidates):
    index = defaultdict(dict)
    for identifier, name, borough, neighborhood in candidates:
        aliases = {identifier, f"tract {identifier}"}
        areas = {}
        label = re.split(r"\s+tract\s+", name, maxsplit=1, flags=re.IGNORECASE)
        number = label[1] if len(label) == 2 else None
        if number:
            aliases.add(f"tract {number}")
        area = neighborhood or (label[0] if number else None)
        if area:
            parts = {area, *re.split(r"[-–—/]", area)}
            parts.update(re.sub(r"\s*\([^)]*\)", "", part) for part in tuple(parts))
            for part in sorted(parts):
                part = part.strip()
                phrase = _tokens(part)
                if not phrase or _normalized(part) in _GENERIC_AREA_FRAGMENTS:
                    continue
                areas[phrase] = part
                short = _SHORT_AREAS.get(_normalized(part))
                if short:
                    areas[_tokens(short)] = part
                if number:
                    aliases.update((f"{part} tract {number}", f"{part} {number}"))
                    if short:
                        aliases.update((f"{short} tract {number}", f"{short} {number}"))
        if name:
            aliases.add(name)
        for phrase, area in areas.items():
            if phrase not in _BOROUGH_INDEX:
                index[phrase][identifier] = (borough, name, area)
        for alias in aliases:
            phrase = _tokens(alias)
            if phrase and phrase not in _BOROUGH_INDEX:
                index[phrase][identifier] = (borough, name, None)
    return index


def _clarify(message, pending=None):
    plan = {"intent": "clarify", "changes": {}, "candidate_ids": [], "topic": None, "clarification": message}
    if pending:
        plan["pending"] = pending
        if pending["slot"] == "cuisine":
            plan["actions"] = [{"label": cuisine.replace("_", " ").title(),
                                "prompt": _resolved_question(pending, cuisine.replace("_", " "))}
                               for cuisine in pending["choices"][:3]]
    return plan


def _resolved_question(pending, replacement):
    return pending["message"][:pending["start"]] + replacement + pending["message"][pending["end"]:]


def _pending_amount(text):
    span = _MONEY_RANGE.search(text)
    if span is None:
        mentions = [match for match in _MONEY.finditer(text) if match["currency"]
                    or _GUEST_RIGHT.match(text[match.end():]) or _RENT_RIGHT.match(text[match.end():])]
        if len(mentions) != 1:
            return None
        span = mentions[0]
    unit = _GUEST_RIGHT.match(text[span.end():]) or _RENT_RIGHT.match(text[span.end():]) or _MONTH_RIGHT.match(text[span.end():])
    return {"slot": "money", "message": text, "start": span.start(),
            "end": span.end() + (unit.end() if unit else 0)}


def resolve_pending(message, pending):
    """Complete a signed clarification only when the reply supplies its missing value."""
    if not pending:
        return None
    text = _normalized(message)
    if pending["slot"] == "cuisine":
        matches = list(_matches(text, _CUISINE_INDEX, 4))
        remainder = re.sub(r"\b(?:please|use|choose|the)\b|[.!?]", "", _masked(text, matches)).strip()
        choices = {choice for choice, _, _ in matches}
        if not remainder and len(choices) == 1 and choices <= set(pending["choices"]):
            return _resolved_question(pending, next(iter(choices)).replace("_", " "))
    if pending["slot"] == "money" and re.fullmatch(r"[\d$.,\s/]+(?:per guest|per person|monthly rent|per month|a month)[.!?]?", text):
        check, rent, problem = _spending(text)
        if problem is None and (check is not None or rent is not None):
            replacement = f"${check:g} per guest" if check is not None else f"${rent} monthly rent"
            return _resolved_question(pending, replacement)
    return None


def _check_places(text, known):
    starts = {start for _, start, _ in known}
    for marker in _PLACE_PREFIX.finditer(text):
        tail = text[marker.end():]
        if marker[0].startswith("around") and re.match(r"\$?\d", tail):
            continue
        if marker.end() not in starts and tail and not _NON_PLACE.match(tail):
            return "Which NYC borough, neighborhood, or exact tract do you mean?"
    return None


def _named_areas(text, area_matches, borough):
    areas = []
    for matches, start, stop in area_matches:
        if _AREA_EXCLUSION.search(text[:start]):
            return None, "Name the area you want to include. The Advisor does not apply neighborhood exclusions."
        possible = {identifier: place for identifier, place in matches.items()
                    if not borough or borough == "All NYC" or not place[0] or place[0] == borough}
        if any(place[2] for place in possible.values()) and _UNRESOLVED_TRACT_SUFFIX.match(text[stop:]):
            return None, "That tract could not be resolved. Give the exact name and number shown in the dashboard."
        if len(possible) == 1:
            identifier, (_, name, area) = next(iter(possible.items()))
            areas.append({"label": name or area or identifier, "ids": [identifier]})
            continue
        locations = {place[0] for place in possible.values()}
        if not possible or len(locations) != 1 or None in locations or any(not place[2] for place in possible.values()):
            return None, "That area is ambiguous or outside the current borough. Specify a borough or give an exact tract name and number."
        if len(possible) > _NEIGHBORHOOD_LIMIT:
            return None, "That neighborhood matches too many tracts. Name a smaller neighborhood or an exact tract."
        if re.search(r"\b(?:near|around)\s+(?:the\s+)?$", text[:start]):
            return None, "I can screen tracts labeled with a neighborhood. For this search, name the neighborhood directly or give an exact tract."
        label = next(iter(possible.values()))[2]
        areas.append({"label": label, "ids": sorted(possible)})
    return areas, None


def _spending(text):
    price_range = _MONEY_RANGE.search(text)
    if price_range and ("$" in price_range[0] or _GUEST_RIGHT.match(text[price_range.end():]) or _RENT_WORD.search(text)):
        return None, None, "Choose one average spend per guest or one monthly rent to test."
    checks, rents = set(), set()
    recognized_dollars = 0
    for mention in _MONEY.finditer(text):
        left, right = text[:mention.start()], text[mention.end():]
        guest = _GUEST_LEFT.search(left) or _GUEST_RIGHT.match(right)
        rent = (_RENT_LEFT.search(left) or _RENT_RIGHT.match(right)
                or (_MONTH_RIGHT.match(right) and _RENT_WORD.search(text))
                or (_RENT_WORD.search(left) and _CAP.search(left) and (mention["currency"] or mention["scale"])))
        if (not guest and not rent and mention["currency"] and not mention["scale"] and text.count("$") == 1
                and not _RENT_WORD.search(text) and not _PROPERTY.search(text)):
            guest = _CHARGE_LEFT.search(left) or (_FIND.search(text) and _FOOD_RIGHT.search(right[:45]))
        if not guest and not rent:
            continue
        if guest and rent:
            return None, None, "Is that amount per guest or for monthly rent?"
        if left.rstrip().endswith("-") and not re.search(r"\d\s*-\s*$", left):
            return None, None, "Enter a positive guest spend or monthly rent."
        recognized_dollars += bool(mention["currency"])
        multiplier = {"k": 1000, "m": 1_000_000}.get((mention["scale"] or "").strip(), 1)
        amount = float(mention["value"].replace(",", "")) * multiplier
        if guest:
            if not 5 <= amount <= 250:
                return None, None, "Choose one spend between $5 and $250 per guest."
            if amount != round(amount, 2):
                return None, None, "Enter guest spend in dollars and cents, such as $35 or $35.50."
            if _PRICE_CAP.search(left):
                return None, None, "Give an exact average guest spend to test, such as $45 per guest."
            checks.add(amount)
        else:
            if not 2000 <= amount <= 100000 or not amount.is_integer():
                return None, None, "Choose a whole-dollar monthly rent from $2,000 to $100,000."
            rents.add(int(amount))
    if len(checks) > 1 or len(rents) > 1:
        return None, None, "Which single guest spend or monthly rent should I use?"
    if text.count("$") > recognized_dollars:
        return None, None, "Label each amount and give one value per input, such as $45 per guest or $9,000 monthly rent."
    return next(iter(checks), None), next(iter(rents), None), None


def _intent(text, changes, topic):
    what_if = _WHAT_IF.search(text)
    if _BREAK_EVEN.search(text) or ("rent_cap" in changes and what_if and not _CAP.search(text)):
        return "break_even"
    if _COMPARE.search(text):
        return "compare"
    if topic in {"next_check", "rent"} or _WHY.search(text):
        return "why"
    if _PROPERTY.search(text):
        return "property"
    if ("average_check" in changes or "daypart" in changes) and (what_if or _DIRECT_SCENARIO.fullmatch(text)):
        return "what_if"
    if _FIND.search(text) or (changes and what_if):
        return "recommend"
    if topic:
        return "why"
    return None


def _references(text, named_ids, selected_ids, map_selected_id, previous, intent, *, keep_focus=True):
    previous = previous or {}
    prior_ids = list(previous.get("candidate_ids") or ())
    shortlist_ids = list(previous.get("shortlist_ids", prior_ids) or ())
    ids = list(named_ids)
    has_reference = bool(ids)
    if _SAVED.search(text):
        if not selected_ids:
            return None, "Save an area in the dashboard first, or tell me its exact tract name."
        has_reference = True
        ids.extend(selected_ids)
    if _MAP.search(text):
        if not map_selected_id:
            return None, "Select an area on the map or give me its exact tract name."
        has_reference = True
        ids.append(map_selected_id)
    group = _TOP_COUNT.search(text)
    if group and intent != "recommend":
        count = _TOP_COUNTS[group[1]]
        if len(shortlist_ids) < count:
            return None, "I don’t have that many areas in the previous shortlist. Give me exact tract names."
        has_reference = True
        ids.extend(shortlist_ids[:count])
    for match in _ORDINAL.finditer(text):
        order = _ORDINALS[match[1]]
        if not shortlist_ids or order >= len(shortlist_ids):
            return None, "I don’t have that position in the previous shortlist. Give me an exact tract name."
        has_reference = True
        ids.append(shortlist_ids[order])
    if _PRIOR_GROUP.search(text) and not has_reference:
        if not shortlist_ids:
            return None, "Which areas do you mean? Give me exact tract names or choose your saved areas."
        has_reference = True
        ids.extend(shortlist_ids)
    if intent in {"compare", "why", "property", "break_even", "what_if"} and _PRIOR_ONE.search(text) and not has_reference:
        if len(prior_ids) != 1:
            return None, "Which area do you mean? Use its tract name or say ‘the first area’ for the previous shortlist."
        has_reference = True
        ids.extend(prior_ids)
    if not has_reference and keep_focus and intent == "compare":
        ids.extend(shortlist_ids if len(shortlist_ids) >= 2 else selected_ids)
    if not has_reference and keep_focus and intent in {"why", "property", "break_even"}:
        ids.extend(prior_ids or ([map_selected_id] if map_selected_id else []))
    ids = list(dict.fromkeys(ids))
    if intent == "compare" and len(ids) < 2:
        return None, "Which two areas should I compare? Give exact tract names or save both in the dashboard."
    if len(ids) > 4:
        return None, "Choose up to four areas for this comparison."
    return ids, None


def parse_message(message, assumptions, *, candidates=(), selected_ids=(), map_selected_id=None, previous=None):
    """Return one intent plus new explicit changes. The server applies the current assumptions."""
    if not isinstance(message, str) or not message.strip() or len(message) > 500:
        return _clarify("Enter a site-selection question of 1 to 500 characters.")
    text = _normalized(message)
    for intent, pattern in _SCENARIO_COMMANDS.items():
        if pattern.fullmatch(text):
            return {"intent": intent, "changes": {}, "candidate_ids": [], "topic": None, "clarification": None}
    if _EXCLUSION.search(text):
        return _clarify("Choose the areas to include directly. Exclusions and competitor-avoidance requirements need a more specific search.")
    if _FACILITIES.search(text):
        return _clarify("Step-free access, kitchen ventilation and outdoor space require confirmation for a specific address. Name a tract to review its property leads and verification steps.")
    if _DISTANCE_REQUIREMENT.search(text):
        return _clarify("A maximum walking distance or time needs a verified address and routing evidence. Name a tract to review the available access evidence.")
    if _UNSUPPORTED.search(text):
        return _clarify("I can change borough, cuisine, guest spend, trading period, or monthly rent here. Use the dashboard for other supported filters.")

    candidate_keys = tuple((row["id"], row.get("name") or "", row.get("borough"), row.get("neighborhood")) for row in candidates)
    area_matches = list(_matches(text, _candidate_index(candidate_keys), 14))
    words = _masked(text, area_matches)
    if _OUTSIDE_NYC.search(words):
        return _clarify("Groundwork covers NYC’s five boroughs. Which NYC borough or tract should I use?")
    borough_matches = list(_matches(words, _BOROUGH_INDEX, 4))
    boroughs = {value for value, _, _ in borough_matches if value}
    if len(boroughs) > 1 or (boroughs and re.search(r"\b(?:all nyc|citywide|all boroughs)\b", words)):
        return _clarify("Choose one borough or the all-NYC scope for this search.")
    problem = _check_places(text, [*area_matches, *borough_matches])
    if problem:
        return _clarify(problem)
    changes = {}
    if borough_matches:
        changes["borough"] = next(iter(boroughs), "")
    current_borough = changes.get("borough", assumptions.get("borough"))
    areas, problem = _named_areas(text, area_matches, current_borough)
    if problem:
        return _clarify(problem)
    if re.search(r"\btract\s+\d", words):
        return _clarify("That tract could not be resolved. Give the exact name and number shown in the dashboard.")

    dietary_matches = list(_matches(words, _DIETARY_INDEX, 3))
    dietary_values = {diet for diet, _, _ in dietary_matches}
    if any(re.search(r"\b(?:not |without |no |non-)$", text[:start]) for _, start, _ in dietary_matches):
        return _clarify("Choose the dietary focus to include directly, or update it in the dashboard.")
    if len(dietary_values) > 1:
        return _clarify("Choose one dietary focus to apply to this search.")
    if dietary_values:
        changes["dietary"] = next(iter(dietary_values))
    part_matches = list(_matches(words, _DAYPART_INDEX, 4))
    cuisine_matches = list(_matches(_masked(words, [*part_matches, *dietary_matches]), _CUISINE_INDEX, 4))
    starts = {start for _, start, _ in [*area_matches, *borough_matches, *part_matches, *cuisine_matches]}
    borough_starts = {start: borough for borough, start, _ in borough_matches}
    for _, start, stop in [*area_matches, *borough_matches]:
        conjunction = _COORDINATOR.match(text, stop)
        if conjunction and start in borough_starts and conjunction.end() in borough_starts:
            return _clarify("Choose one borough or the all-NYC scope for this search.")
        if conjunction and conjunction.end() not in starts and not re.match(r"\$?\d", text[conjunction.end():]):
            return _clarify("Name one NYC scope, or give both exact tract names if you want to compare areas.")
    cuisines = {cuisine for cuisine, _, _ in cuisine_matches}
    if any(re.search(r"\b(?:not |without |non-)$", text[:start]) for _, start, _ in cuisine_matches):
        return _clarify("Choose one cuisine directly, or set cuisine in the dashboard.")
    if len(cuisines) > 1:
        pending = {"slot": "cuisine", "message": text, "start": min(start for _, start, _ in cuisine_matches),
                   "end": max(stop for _, _, stop in cuisine_matches), "choices": sorted(cuisines)}
        return _clarify("Choose one restaurant cuisine to use for this search.", pending)
    if cuisines:
        changes["cuisine"] = next(iter(cuisines))
    elif not dietary_values and re.search(r"\b(?:for\s+an?|an?) (?!new\b|existing\b|current\b|restaurant\b|site\b|property\b)\w+(?:[- ]\w+){0,2} (?:restaurant|cuisine|concept)\b", words):
        return _clarify("Which supported cuisine in the dashboard should I use for that concept?")
    dayparts = {part for part, _, _ in part_matches}
    if len(dayparts) > 1:
        return _clarify("Choose one trading period: all day, morning, lunch, or evening.")
    if dayparts:
        changes["daypart"] = next(iter(dayparts))
    words = " ".join(words.split())
    check, rent, problem = _spending(words)
    if problem:
        return _clarify(problem, _pending_amount(text))
    if check is not None:
        changes["average_check"] = check
    if rent is not None:
        changes["rent_cap"] = rent

    topic = ("next_check" if _NEXT.search(words) else "competition" if _COMPETITION.search(words)
             else "access" if _ACCESS.search(words) else "rent" if _RENT_EVIDENCE.search(words) else None)
    intent = _intent(words, changes, topic)
    if intent is None and area_matches and (_FIND.search(text) or _WHAT_IF.search(words) or not words.strip("?.!, ")):
        intent = "recommend"
    if intent is None and previous and (borough_matches or cuisine_matches):
        remainder = _masked(text, [*area_matches, *borough_matches, *cuisine_matches])
        remainder = re.sub(r"\b(?:in|for|and|the|only)\b|[?.!,]", "", remainder)
        if not remainder.strip():
            intent = "recommend"
    if intent is None:
        return _clarify("I can shortlist areas, compare saved or named tracts, explain evidence, test guest spend or trading hours, and check leases or break-even. Which would you like?")
    if intent == "break_even" and rent is not None:
        topic = "rent_scenario"
    deal_type = assumptions.get("deal_type")
    wants_lease = rent is not None or _LEASE_TRANSACTION.search(words) is not None
    wants_purchase = _PURCHASE_TRANSACTION.search(words) is not None
    if wants_purchase and wants_lease:
        return _clarify("Choose lease or purchase for this request.")
    if deal_type == "purchase" and wants_lease:
        return _clarify("The current search is for purchases. Switch the dashboard to lease to use rent or lease filters.")
    if deal_type == "lease" and wants_purchase:
        return _clarify("The current search is for leases. Switch the dashboard to purchase to look for sale listings.")
    if deal_type == "either" and intent == "property" and (wants_lease or wants_purchase):
        changes["deal_type"] = "lease" if wants_lease else "purchase"
    if any(len(area["ids"]) > 1 for area in areas):
        if intent == "compare":
            if len(areas) != 2 or any(pattern.search(words) for pattern in (_SAVED, _MAP, _TOP_COUNT, _ORDINAL, _PRIOR_GROUP)):
                return _clarify("Name two neighborhoods or exact tracts to compare.")
            if set(areas[0]["ids"]) & set(areas[1]["ids"]):
                return _clarify("Those areas include some of the same tracts. Name two areas that do not overlap.")
        elif intent not in {"recommend", "why", "what_if", "property"} or len(areas) != 1:
            return _clarify("Choose one neighborhood to screen, or give an exact tract for a property or rent question.")
        return {"intent": intent, "changes": changes, "candidate_ids": [], "area_groups": areas,
                "topic": topic, "clarification": None}
    old_borough = assumptions.get("borough") or ""
    if old_borough == "All NYC":
        old_borough = ""
    new_scope = "borough" in changes and changes["borough"] != old_borough
    broad_property = intent == "property" and (rent is not None or _PROPERTY_SEARCH.search(words))
    ids, problem = _references(words, [area["ids"][0] for area in areas], selected_ids, map_selected_id, previous, intent,
                               keep_focus=not (new_scope or broad_property))
    if problem:
        return _clarify(problem)
    return {"intent": intent, "changes": changes, "candidate_ids": ids, "topic": topic, "clarification": None}
