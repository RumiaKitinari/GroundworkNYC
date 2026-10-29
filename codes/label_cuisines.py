r"""
Label NYC DOHMH restaurants into the 50-cuisine taxonomy.

Usage:
    python label_cuisines.py
    (reads data\current_restaurants.csv, writes outputs\restaurants_labeled.csv;
     pass two paths to override)

Adds three columns:
    cuisine_50        one of the 50 labels, or "Unclassified"
    label_source      how the label was assigned:
                        direct   - DOHMH code maps 1:1
                        keyword  - restaurant name matched a keyword rule
                        default  - vague DOHMH code, no keyword hit, best-guess default
                        weak_keyword - blank code, name only says "grill/bar/kitchen" -> American
                        none     - nothing to go on (Unclassified)
    cuisine_dohmh     original DOHMH cuisine_description (copy, for reference)
"""
import re
import sys
import pandas as pd

from paths import OUTPUTS, ensure_dirs, find

CUISINES_50 = [
    "American", "Southern / Soul Food", "Cajun / Creole", "Italian", "French",
    "Spanish", "Portuguese", "Greek", "German / Central European", "Eastern European",
    "Mexican", "Peruvian", "Brazilian", "Colombian", "Venezuelan",
    "Cuban", "Dominican", "Puerto Rican", "Jamaican", "Haitian",
    "Ethiopian / Eritrean", "West African", "Indian", "Pakistani / Bangladeshi", "Chinese",
    "Japanese", "Korean", "Taiwanese", "Thai", "Vietnamese",
    "Filipino", "Indonesian / Malaysian", "Middle Eastern", "Mediterranean", "Turkish",
    "Persian / Iranian", "Steakhouse", "Seafood", "Barbecue", "Pizza",
    "Burgers", "Sandwiches / Deli", "Bakery / Pastries", "Coffee / Tea", "Desserts / Ice Cream",
    "Salads / Bowls", "Breakfast / Brunch", "Noodles", "Diner", "Health-Focused",
]

# --------------------------------------------------------------------------
# 1. DOHMH codes that map cleanly (still subject to specialty overrides below)
# --------------------------------------------------------------------------
DIRECT = {
    "American": "American", "New American": "American", "Californian": "American",
    "Southwestern": "American", "Continental": "American", "English": "American",
    "Irish": "American", "Australian": "American", "Polynesian": "American",
    "Hotdogs": "American", "Hotdogs/Pretzels": "American", "Fusion": "American",
    "Soul Food": "Southern / Soul Food",
    "Cajun": "Cajun / Creole", "Creole": "Cajun / Creole", "Creole/Cajun": "Cajun / Creole",
    "Italian": "Italian",
    "French": "French", "New French": "French", "Haute Cuisine": "French",
    "Tapas": "Spanish", "Basque": "Spanish",
    "Portuguese": "Portuguese", "Greek": "Greek",
    "German": "German / Central European", "Czech": "German / Central European",
    "Scandinavian": "German / Central European",
    "Eastern European": "Eastern European", "Russian": "Eastern European",
    "Polish": "Eastern European",
    "Mexican": "Mexican", "Tex-Mex": "Mexican",
    "Peruvian": "Peruvian", "Chilean": "Peruvian", "Brazilian": "Brazilian",
    "Chimichurri": "Steakhouse",
    "Ethiopian": "Ethiopian / Eritrean",
    "Indian": "Indian",
    "Bangladeshi": "Pakistani / Bangladeshi", "Pakistani": "Pakistani / Bangladeshi",
    "Chinese": "Chinese", "Chinese/Cuban": "Chinese", "Chinese/Japanese": "Chinese",
    "Japanese": "Japanese", "Korean": "Korean", "Thai": "Thai",
    "Filipino": "Filipino", "Indonesian": "Indonesian / Malaysian",
    "Middle Eastern": "Middle Eastern", "Lebanese": "Middle Eastern",
    "Egyptian": "Middle Eastern", "Moroccan": "Middle Eastern", "Armenian": "Middle Eastern",
    "Mediterranean": "Mediterranean", "Turkish": "Turkish",
    "Iranian": "Persian / Iranian", "Afghan": "Persian / Iranian",
    "Steakhouse": "Steakhouse", "Seafood": "Seafood", "Barbecue": "Barbecue",
    "Pizza": "Pizza", "Hamburgers": "Burgers",
    "Sandwiches": "Sandwiches / Deli", "Sandwiches/Salads/Mixed Buffet": "Sandwiches / Deli",
    "Soups/Salads/Sandwiches": "Sandwiches / Deli", "Soups": "Sandwiches / Deli",
    "Bakery Products/Desserts": "Bakery / Pastries", "Donuts": "Bakery / Pastries",
    "Bagels/Pretzels": "Bakery / Pastries",
    "Coffee/Tea": "Coffee / Tea", "Bottled Beverages": "Coffee / Tea",
    "Frozen Desserts": "Desserts / Ice Cream", "Nuts/Confectionary": "Desserts / Ice Cream",
    "Salads": "Salads / Bowls", "Hawaiian": "Salads / Bowls",
    "Pancakes/Waffles": "Breakfast / Brunch",
    "Juice, Smoothies, Fruit Salads": "Health-Focused", "Vegan": "Health-Focused",
    "Vegetarian": "Health-Focused", "Fruits/Vegetables": "Health-Focused",
}

# Vague DOHMH codes: try keywords first, then fall back to this default.
VAGUE_DEFAULT = {
    "Latin American": "Dominican",       # most common unspecified Latin cuisine in NYC
    "Spanish": "Dominican",              # DOHMH "Spanish" = mostly Latino in NYC
    "Caribbean": "Jamaican",
    "Chicken": "American",
    "Asian/Asian Fusion": "Chinese",
    "Southeast Asian": "Indonesian / Malaysian",
    "African": "West African",
    "Jewish/Kosher": "Sandwiches / Deli",
    "Other": None,
    "Not Listed/Not Applicable": None,
}

# --------------------------------------------------------------------------
# 2. Name keyword rules. Order matters: first match wins.
#    Nationality rules come before food-format rules.
# --------------------------------------------------------------------------
NATIONALITY_RULES = [
    (r"DOMINICAN|QUISQUEYA|CIBAO|JARABACOA|\b809\b|PICA ?POLLO|PICAPOLLO|SANTO DOMINGO", "Dominican"),
    (r"PUERTO RIC|BORICUA|BORINQUEN|LECHONERA|LECHONERIA|MOFONGO|PIRAGUA", "Puerto Rican"),
    (r"CUBAN|CUBANO|HAVANA|HABANA", "Cuban"),
    (r"COLOMBIA|ANTIOQU|PAISA|\bPARCE\b|LLANER|BANDEJA|PANDEBONO", "Colombian"),
    (r"VENEZUEL|AREPA|CARACAS", "Venezuelan"),
    (r"PERU|POLLO A LA BRASA|CEVICH|LIMA\b|INKA|\bINCA\b|ECUADOR|ECUATORIAN|QUITO|ECUAPOLLO|HORNADO|BOLIVIA|CHILE", "Peruvian"),
    (r"BRAZIL|BRASIL|CHURRASC|RODIZIO|ACAI|AÇAI", "Brazilian"),
    (r"SALVADOR|PUPUS|GUATEMAL|CHAPIN|QUETZAL|HONDUR|CATRACH|TAQUER|TACO|BURRITO|CANTINA|MEXIC|OAXAC|PUEBLA|TORTILL|TAMAL|ANTOJITOS MEX|BIRRIA|ELOTE|CHIPOTLE|QDOBA", "Mexican"),
    (r"HAITI|KREYOL|CREOLE HAIT|AYITI|PAP CHEN|SAK PASE|GRIOT", "Haitian"),
    (r"JAMAICA|JERK|YAAD|YARD FOOD|GOLDEN KRUST|PATTY|PATTIES|ROTI|TRINI|GUYAN|DHAL PURI|DOUBLES|WEST INDIAN", "Jamaican"),
    (r"ETHIOP|ERITRE|ABYSSINIA|INJERA|HABESHA|AWASH|ADDIS", "Ethiopian / Eritrean"),
    (r"NIGERI|GHANA|SENEGAL|DAKAR|TERANGA|LAGOS|ACCRA|SUYA|JOLLOF|JOLOFF|BAOBAB|KEUR|IVOIR|MALI\b|GUINEA|AFRICA|BUKA", "West African"),
    (r"PAKISTAN|BANGLA|DHAKA|KARACHI|LAHORE|BIRYANI HOUSE|HALAL BIRYANI", "Pakistani / Bangladeshi"),
    (r"INDIA|TANDOOR|MASALA|MASAALA|CURRY|BIRYANI|DOSA|NEPAL|HIMALAYA|TIBET|MOMO|DARJEELING|KATHMANDU|PUNJAB|APNA|DESI|CHAAT|SAMOSA", "Indian"),
    (r"TAIWAN|BOBA|BUBBLE TEA|KUNG FU TEA|GONG CHA|CHATIME|TIGER SUGAR|YAYA TEA|NOM TEA|MILK TEA|COCO FRESH|XING FU|WIN SON|BAFANG", "Taiwanese"),
    (r"KOREA|SEOUL|BIBIMBAP|BULGOGI|KIMCHI|TOPOKKI|TTEOK|BONCHON|BBQ CHICKEN|KYOCHON|POCHA|SOJU|GIMBAP|KBBQ|K-BBQ|HANSIK|KKINI", "Korean"),
    (r"JAPAN|SUSHI|RAMEN|IZAKAYA|OMAKASE|HIBACHI|TERIYAKI|TEMPURA|UDON|SOBA\b|YAKITORI|TOKYO|OSAKA|KYOTO|SAKE|NORI|DONBURI|KATSU|ONIGIRI|SAKURA|MATCHA|TONKOTSU|WASABI|BENTO", "Japanese"),
    (r"VIET|SAIGON|HANOI|HA NOI|\bPHO\b|PHO |BANH ?MI|BANHMI|MEKONG|NHA TRANG", "Vietnamese"),
    (r"THAI|BANGKOK|SIAM|PAD SEE|LAAB|ISAN|SRI PRAPHAI|BAYON|CAMBOD|KHMER|LAO\b|LAOS", "Thai"),
    (r"FILIPIN|PINOY|MANILA|JOLLIBEE|LECHON KAWALI|ADOBO|KABAYAN|PHILIPPIN", "Filipino"),
    (r"MALAYSIA|INDONESIA|JAKARTA|BALI\b|KUALA|LAKSA|NASI|SATAY|RENDANG|BURMA|BURMESE|MYANMAR|SINGAPOR|BELACAN|KELANG|RASA\b", "Indonesian / Malaysian"),
    (r"CHINA|CHINESE|SZECHUAN|SICHUAN|HUNAN|CANTON|HONG KONG|DIM SUM|DUMPLING|WOK|PANDA|DRAGON|GOLDEN|JADE|LUCKY|FORTUNE|PEKING|SHANGHAI|BEIJING|FUZHOU|HOT ?POT|MALA|DONG|WONTON|XIAO|NOODLE HOUSE|LANZHOU|YUNNAN|BAO\b", "Chinese"),
    (r"PERSIA|IRAN|TEHRAN|KABOB|AFGHAN|KABUL|ARIANA", "Persian / Iranian"),
    (r"TURK|ISTANBUL|ANKARA|DONER|DÖNER|KEBAB|UZBEK|SAMARKAND|PIDE|LAHMACUN|BAKLAVA", "Turkish"),
    (r"GREEK|GYRO|SOUVLAKI|ATHENS|HELLAS|HELLENIC|TAVERNA|SPARTA|OLYMP|MYKONOS|SANTORINI|ESTIATORIO", "Greek"),
    (r"LEBAN|SYRIA|EGYPT|MOROCC|YEMEN|ARAB|SHAWARMA|FALAFEL|HUMMUS|MANOUSH|ZAATAR|ZA'ATAR|HALAL|PALESTIN|JERUSALEM|ISRAEL|TEL AVIV|BEIRUT|CAIRO|KNAFEH|MANDI", "Middle Eastern"),
    (r"MEDITERR|MEZZE|MEZE", "Mediterranean"),
    (r"ITALIA|TRATTORIA|OSTERIA|RISTORANTE|PASTA|ENOTECA|NONNA|PANINI|SALUMERIA|AMORE|BELLA|GELATO", "Italian"),
    (r"FRENCH|BRASSERIE|BRASSARIE|PATISSERIE|BOULANGERIE|CREPE|CRÊPE|PARIS|\bLE |LA MAISON|CHEZ |BOUCHON", "French"),
    (r"TAPAS|ESPAÑ|ESPANA|SPAIN|BARCELONA|MADRID|PAELLA|SOCARRAT|BASQUE|IBERI|ANDALUC|SEVILLA|TOLEDO|GALICIA", "Spanish"),
    (r"PORTUG|LISBOA|LISBON|PORTO\b|NATA\b", "Portuguese"),
    (r"GERMAN|BAVARIA|BIERGARTEN|BEER GARDEN|BEER HALL|HAUS\b|BRAUHAUS|SCHNITZEL|WURST|AUSTRIA|SWISS|HUNGAR|CZECH|NORDIC|DANISH|SWEDISH", "German / Central European"),
    (r"RUSSIA|UKRAIN|POLISH|POLSKA|GEORGIA|KHACHAPURI|PIEROG|PIEROGI|VARENIKI|BALKAN|SERBIA|CROATI|ROMANIA|BULGAR|ALBANIA|BOSNIA|BUREK|BORSCHT|ODESSA|KIEV|KYIV|TBILISI|BUKHAR|LAGMAN", "Eastern European"),
    (r"SOUL FOOD|SOUTHERN|DOWN SOUTH|SYLVIA|CHICKEN AND WAFFLE|CHICKEN & WAFFLE|GRITS|COLLARD|AFRICAN AMERICAN", "Southern / Soul Food"),
    (r"CAJUN|CREOLE|LOUISIANA KITCHEN|NOLA|NEW ORLEANS|GUMBO|JAMBALAYA|CRAWFISH|BOIL", "Cajun / Creole"),
]

# Food-format rules: applied to generic codes (American, Other, blank, Chicken, etc.)
# and also used to pull specialty formats out of Italian/French when obvious.
FORMAT_RULES = [
    (r"STEAKHOUSE|STEAK HOUSE|CHOPHOUSE|CHOP HOUSE|PRIME\b|STEAK\b|\bCUT\b|PETER LUGER|WOLFGANG", "Steakhouse"),
    (r"BBQ|BAR-B-Q|BARBECUE|BARBEQUE|SMOKEHOUSE|SMOKE HOUSE|BRISKET|PIT\b", "Barbecue"),
    (r"SEAFOOD|OYSTER|LOBSTER|FISH|CRAB|SHRIMP|CLAM|POKE|SUSHI\b", "Seafood"),
    (r"PIZZ|SLICE|DOMINO'?S|PAPA JOHN|LITTLE CAESAR", "Pizza"),
    (r"BURGER|SHAKE SHACK|FIVE GUYS|WENDY|MCDONALD|WHITE CASTLE|SMASH", "Burgers"),
    (r"DINER|LUNCHEONETTE|COFFEE SHOP RESTAURANT", "Diner"),
    (r"BRUNCH|BREAKFAST|PANCAKE|WAFFLE|IHOP|EGG", "Breakfast / Brunch"),
    (r"NOODLE|RAMEN|UDON|PHO\b|LO MEIN", "Noodles"),
    (r"SWEETGREEN|SALAD|CHOPT|BOWL|JUST SALAD|CAVA\b|DIG\b|POKE", "Salads / Bowls"),
    (r"JUICE|SMOOTHIE|VEGAN|VEGETARIAN|PLANT|ORGANIC|PROTEIN|HEALTH|ACAI|KALE\b|EARTHBAR|JUICE PRESS|FRUIT|GLUTEN", "Health-Focused"),
    (r"ICE CREAM|GELATO|FROZEN YOGURT|FROYO|YOGURT|DESSERT|SWEETS|CANDY|CHOCOLATE|COOKIE|CRUMBL|CHIP CITY|BASKIN|CARVEL|DAIRY QUEEN|MILK BAR|MOCHI|CHURRO|CREAMERY|SCOOP|SUNDAE|CAKE", "Desserts / Ice Cream"),
    (r"BAKERY|BAKE|BAKED|PASTRY|PASTRIES|DONUT|DOUGHNUT|DUNKIN|BAGEL|BREAD|CROISSANT|MUFFIN|PANADERIA|PANADERÍA|BOULANGER|PATISSER", "Bakery / Pastries"),
    (r"COFFEE|CAFE\b|CAFÉ|ESPRESSO|STARBUCKS|ROAST|BREW|LATTE|TEA\b|TEA HOUSE|TEAHOUSE|BLUE BOTTLE|JOE\b|BLANK STREET|PRET\b|ROASTER|CAFECITO", "Coffee / Tea"),
    (r"DELI|SANDWICH|SUBWAY|JERSEY MIKE|JIMMY JOHN|POTBELLY|HERO\b|BODEGA|SUBS\b|GROCERY|GOURMET|MARKET|LUNCH", "Sandwiches / Deli"),
    (r"CHICKEN|WING|POPEYE|KFC|CHICK-FIL-A|CHICK'N|CHICKN|CRISP|FRIED", "American"),
]
# Very generic words: only used for blank/Other codes, and flagged as "weak"
WEAK_RULES = [
    (r"GRILL|TAVERN|PUB\b|BAR\b|LOUNGE|SALOON|BAR &|& BAR|KITCHEN|RESTAURANT|EATERY|BISTRO", "American"),
]

NAT_RE = [(re.compile(p), c) for p, c in NATIONALITY_RULES]
FMT_RE = [(re.compile(p), c) for p, c in FORMAT_RULES]
WEAK_RE = [(re.compile(p), c) for p, c in WEAK_RULES]

# Specialty formats that may override a generic "American" code
AMERICAN_SPECIALTIES = {"Steakhouse", "Barbecue", "Seafood", "Pizza", "Burgers", "Diner",
                        "Breakfast / Brunch", "Salads / Bowls", "Health-Focused",
                        "Desserts / Ice Cream", "Bakery / Pastries", "Coffee / Tea",
                        "Sandwiches / Deli", "Southern / Soul Food", "Cajun / Creole"}


def first_match(name, rules):
    for rx, label in rules:
        if rx.search(name):
            return label
    return None


def label_row(dohmh, name):
    name = str(name).upper() if pd.notna(name) else ""
    dohmh = dohmh if pd.notna(dohmh) else None

    # Generic American: pull out specialty formats (diner, deli, steakhouse, soul food...)
    if dohmh in ("American", "New American"):
        nat = first_match(name, NAT_RE)
        if nat in ("Southern / Soul Food", "Cajun / Creole"):
            return nat, "keyword"
        fmt = first_match(name, FMT_RE)
        if fmt in AMERICAN_SPECIALTIES:
            return fmt, "keyword"
        return "American", "direct"

    # Italian / French that are really pizzerias or bakeries
    if dohmh == "Italian" and re.search(r"PIZZ", name):
        return "Pizza", "keyword"
    if dohmh == "French" and re.search(r"BAKERY|BOULANGER|PATISSER|CROISSANT", name):
        return "Bakery / Pastries", "keyword"

    if dohmh in DIRECT:
        return DIRECT[dohmh], "direct"

    # Vague codes and blanks: nationality keywords, then format keywords, then default
    nat = first_match(name, NAT_RE)
    if dohmh in ("Latin American", "Spanish", "Caribbean"):
        # Only accept nationality hits that make sense for these codes
        latin_ok = {"Dominican", "Puerto Rican", "Cuban", "Colombian", "Venezuelan",
                    "Peruvian", "Brazilian", "Mexican", "Haitian", "Jamaican", "Spanish",
                    "Southern / Soul Food"}
        if nat in latin_ok:
            return nat, "keyword"
        fmt = first_match(name, FMT_RE)
        if fmt in {"Bakery / Pastries", "Pizza", "Seafood", "Steakhouse"}:
            return fmt, "keyword"
        return VAGUE_DEFAULT[dohmh], "default"

    if nat:
        return nat, "keyword"
    fmt = first_match(name, FMT_RE)
    if fmt:
        return fmt, "keyword"
    if dohmh in VAGUE_DEFAULT and VAGUE_DEFAULT[dohmh]:
        return VAGUE_DEFAULT[dohmh], "default"
    weak = first_match(name, WEAK_RE)
    if weak:
        return weak, "weak_keyword"
    return "Unclassified", "none"


def main(src, dst):
    df = pd.read_csv(src)
    labels = [label_row(c, n) for c, n in zip(df["cuisine_description"], df["dba"])]
    df["cuisine_50"] = [l for l, _ in labels]
    df["label_source"] = [s for _, s in labels]
    df["cuisine_dohmh"] = df["cuisine_description"]
    bad = set(df["cuisine_50"]) - set(CUISINES_50) - {"Unclassified"}
    assert not bad, f"labels outside taxonomy: {bad}"
    df.to_csv(dst, index=False)

    print(df["label_source"].value_counts().to_string(), "\n")
    print(df["cuisine_50"].value_counts().to_string())


if __name__ == "__main__":
    ensure_dirs()
    main(sys.argv[1] if len(sys.argv) > 1 else find("current_restaurants.csv"),
         sys.argv[2] if len(sys.argv) > 2 else OUTPUTS / "restaurants_labeled.csv")
