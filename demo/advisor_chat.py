"""Parse bounded site-advisor questions into explicit, read-only operations."""

from collections import defaultdict
from functools import lru_cache
import re
from unicodedata import combining, normalize

from scoring import CUISINES, CUISINE_ALIASES


_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
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
    r"\b(?:recommend(?:ations?)?|shortlist|where (?:in [a-z][a-z ]{0,45} )?(?:should|could|would|can) (?:i|we) (?:look|start|open|"
    r"search|find)|best (?:places?|areas?|sites?|locations?|neighbou?rhoods?)|"
    r"(?:find|show|suggest) (?:me )?(?:a |some |the |good |potential )?(?:areas?|sites?|locations?|neighbou?rhoods?))\b"
)
_COMPARE = re.compile(r"\b(?:compare|versus|vs\.?|side.by.side|difference between)\b")
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
_ORDINAL = re.compile(r"\b(first|1st|top|second|2nd|third|3rd|fourth|4th|last)\b(?=\s+(?:one|area|site|tract|location|option)\b|\s+and\s+(?:the\s+)?(?:first|second|third|fourth|last)\b|[?.!]?$)")
_TOP_COUNT = re.compile(r"\b(?:first|top) (two|three|four|2|3|4)\b")
_TOP_COUNTS = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
_COORDINATOR = re.compile(r",?\s+(?:and|or|versus|vs\.?)\s+")


def _normalized(value):
    value = normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in value if not combining(char)).translate(
        str.maketrans({"’": "'", "–": "-", "—": "-", "−": "-"})).split())


def _tokens(value):
    return tuple(_TOKEN.findall(_normalized(value)))


def _alias_index(groups):
    return {_tokens(alias): label for label, aliases in groups.items() for alias in aliases}


_BOROUGH_INDEX = _alias_index(_BOROUGHS)
_DAYPART_INDEX = _alias_index(_DAYPARTS)
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
    for identifier, name, borough in candidates:
        aliases = {identifier, f"tract {identifier}"}
        label = re.split(r"\s+tract\s+", name, maxsplit=1, flags=re.IGNORECASE)
        if len(label) == 2:
            area, number = label
            aliases.add(f"tract {number}")
            parts = {area, re.sub(r"\s*\([^)]*\)", "", area), *re.split(r"[-–—/]", area)}
            for part in parts:
                aliases.update((part, f"{part} tract {number}", f"{part} {number}"))
                short = _SHORT_AREAS.get(_normalized(part))
                if short:
                    aliases.update((short, f"{short} tract {number}", f"{short} {number}"))
        elif name:
            aliases.add(name)
        for alias in aliases:
            phrase = _tokens(alias)
            if phrase and phrase not in _BOROUGH_INDEX:
                index[phrase][identifier] = borough
    return index


def _clarify(message):
    return {"intent": "clarify", "changes": {}, "candidate_ids": [], "topic": None, "clarification": message}


def _check_places(text, known):
    starts = {start for _, start, _ in known}
    for marker in _PLACE_PREFIX.finditer(text):
        tail = text[marker.end():]
        if marker[0].startswith("around") and re.match(r"\$?\d", tail):
            continue
        if marker.end() not in starts and tail and not _NON_PLACE.match(tail):
            return "Which NYC borough or exact tract do you mean? Use a tract name with its number for a specific area."
    return None


def _spending(text):
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
    prior_ids = list((previous or {}).get("candidate_ids") or ())
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
        if len(prior_ids) < count:
            return None, "I don’t have that many areas in the previous shortlist. Give me exact tract names."
        has_reference = True
        ids.extend(prior_ids[:count])
    for match in _ORDINAL.finditer(text):
        order = _ORDINALS[match[1]]
        if not prior_ids or order >= len(prior_ids):
            return None, "I don’t have that position in the previous shortlist. Give me an exact tract name."
        has_reference = True
        ids.append(prior_ids[order])
    if _PRIOR_GROUP.search(text) and not has_reference:
        if not prior_ids:
            return None, "Which areas do you mean? Give me exact tract names or choose your saved areas."
        has_reference = True
        ids.extend(prior_ids)
    if intent in {"compare", "why", "property", "break_even"} and _PRIOR_ONE.search(text) and not has_reference:
        if len(prior_ids) != 1:
            return None, "Which area do you mean? Use its tract name or say ‘the first area’ for the previous shortlist."
        has_reference = True
        ids.extend(prior_ids)
    if not has_reference and keep_focus and intent == "compare":
        ids.extend(prior_ids if len(prior_ids) >= 2 else selected_ids)
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
    if _UNSUPPORTED.search(text):
        return _clarify("I can change borough, cuisine, guest spend, trading period, or monthly rent here. Use the dashboard for other supported filters.")

    candidate_keys = tuple((row["id"], row.get("name") or "", row.get("borough")) for row in candidates)
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
    named_ids = []
    for matches, _, _ in area_matches:
        possible = [identifier for identifier, borough in matches.items()
                    if not current_borough or current_borough == "All NYC" or not borough or borough == current_borough]
        if len(possible) != 1:
            return _clarify("That area name is ambiguous or outside the current borough. Give the exact tract name and number, or change the borough.")
        named_ids.extend(possible)
    if re.search(r"\btract\s+\d", words):
        return _clarify("That tract could not be resolved. Give the exact name and number shown in the dashboard.")

    part_matches = list(_matches(words, _DAYPART_INDEX, 4))
    cuisine_matches = list(_matches(_masked(words, part_matches), _CUISINE_INDEX, 4))
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
        return _clarify("Choose one restaurant cuisine to use for this search.")
    if cuisines:
        changes["cuisine"] = next(iter(cuisines))
    elif re.search(r"\b(?:for\s+an?|an?) (?!new\b|existing\b|current\b|restaurant\b|site\b|property\b)\w+(?:[- ]\w+){0,2} (?:restaurant|cuisine|concept)\b", words):
        return _clarify("Which supported cuisine in the dashboard should I use for that concept?")
    dayparts = {part for part, _, _ in part_matches}
    if len(dayparts) > 1:
        return _clarify("Choose one trading period: all day, morning, lunch, or evening.")
    if dayparts:
        changes["daypart"] = next(iter(dayparts))
    words = " ".join(words.split())
    check, rent, problem = _spending(words)
    if problem:
        return _clarify(problem)
    if check is not None:
        changes["average_check"] = check
    if rent is not None:
        changes["rent_cap"] = rent

    topic = ("next_check" if _NEXT.search(words) else "competition" if _COMPETITION.search(words)
             else "access" if _ACCESS.search(words) else "rent" if _RENT_EVIDENCE.search(words) else None)
    intent = _intent(words, changes, topic)
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
    old_borough = assumptions.get("borough") or ""
    if old_borough == "All NYC":
        old_borough = ""
    new_scope = "borough" in changes and changes["borough"] != old_borough
    broad_property = intent == "property" and (rent is not None or _PROPERTY_SEARCH.search(words))
    ids, problem = _references(words, named_ids, selected_ids, map_selected_id, previous, intent,
                               keep_focus=not (new_scope or broad_property))
    if problem:
        return _clarify(problem)
    return {"intent": intent, "changes": changes, "candidate_ids": ids, "topic": topic, "clarification": None}
