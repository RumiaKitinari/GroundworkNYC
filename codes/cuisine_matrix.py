r"""
Cuisine substitution matrix (50 x 50, symmetric, values 0-1).

M[a, b] = how much a restaurant of cuisine b competes with one of cuisine a.
    1.0  same cuisine (diagonal)
    0.6+ near-substitutes (Indian vs Pakistani/Bangladeshi)
    0.3  overlapping customers / dishes
    0.1  weak overlap
    0    independent (most pairs)

Usage:
    python cuisine_matrix.py            -> writes outputs\cuisine_matrix.csv
    from cuisine_matrix import build_matrix
"""
import pandas as pd
from label_cuisines import CUISINES_50
from paths import OUTPUTS, ensure_dirs

PAIRS = [
    # South Asian
    ("Indian", "Pakistani / Bangladeshi", 0.80),
    ("Pakistani / Bangladeshi", "Middle Eastern", 0.15),
    ("Persian / Iranian", "Pakistani / Bangladeshi", 0.15),
    ("Persian / Iranian", "Indian", 0.10),

    # East Asian
    ("Chinese", "Taiwanese", 0.60),
    ("Chinese", "Korean", 0.20),
    ("Chinese", "Japanese", 0.15),
    ("Japanese", "Korean", 0.25),
    ("Taiwanese", "Japanese", 0.10),
    ("Taiwanese", "Korean", 0.10),

    # Southeast Asian
    ("Thai", "Vietnamese", 0.35),
    ("Thai", "Indonesian / Malaysian", 0.40),
    ("Vietnamese", "Indonesian / Malaysian", 0.25),
    ("Filipino", "Indonesian / Malaysian", 0.20),
    ("Chinese", "Thai", 0.20),
    ("Chinese", "Vietnamese", 0.15),
    ("Chinese", "Indonesian / Malaysian", 0.15),

    # Noodle shops overlap with the cuisines that sell noodles
    ("Noodles", "Chinese", 0.40),
    ("Noodles", "Japanese", 0.40),
    ("Noodles", "Vietnamese", 0.40),
    ("Noodles", "Taiwanese", 0.30),
    ("Noodles", "Thai", 0.20),
    ("Noodles", "Korean", 0.15),

    # Middle East / Mediterranean
    ("Middle Eastern", "Mediterranean", 0.70),
    ("Middle Eastern", "Turkish", 0.60),
    ("Mediterranean", "Greek", 0.60),
    ("Mediterranean", "Turkish", 0.50),
    ("Persian / Iranian", "Middle Eastern", 0.50),
    ("Greek", "Turkish", 0.40),
    ("Persian / Iranian", "Turkish", 0.40),
    ("Middle Eastern", "Greek", 0.30),
    ("Persian / Iranian", "Mediterranean", 0.30),
    ("Mediterranean", "Italian", 0.20),
    ("Mediterranean", "Spanish", 0.20),
    ("Mediterranean", "Salads / Bowls", 0.15),

    # European
    ("Italian", "Pizza", 0.50),
    ("Spanish", "Portuguese", 0.50),
    ("German / Central European", "Eastern European", 0.40),
    ("Portuguese", "Brazilian", 0.30),
    ("Italian", "French", 0.20),
    ("Italian", "Spanish", 0.15),
    ("French", "Spanish", 0.15),

    # American formats
    ("Diner", "Breakfast / Brunch", 0.60),
    ("American", "Diner", 0.50),
    ("Southern / Soul Food", "Cajun / Creole", 0.50),
    ("American", "Burgers", 0.40),
    ("Southern / Soul Food", "Barbecue", 0.40),
    ("American", "Southern / Soul Food", 0.30),
    ("American", "Barbecue", 0.30),
    ("American", "Breakfast / Brunch", 0.30),
    ("Diner", "Burgers", 0.30),
    ("Cajun / Creole", "Seafood", 0.30),
    ("Steakhouse", "Brazilian", 0.30),   # churrascaria
    ("American", "Steakhouse", 0.20),
    ("American", "Sandwiches / Deli", 0.20),
    ("Burgers", "Sandwiches / Deli", 0.20),
    ("Barbecue", "Steakhouse", 0.20),
    ("Steakhouse", "Seafood", 0.20),
    ("American", "Pizza", 0.15),
    ("Burgers", "Pizza", 0.15),
    ("American", "Seafood", 0.10),

    # Cafe / bakery / quick formats
    ("Coffee / Tea", "Bakery / Pastries", 0.50),
    ("Bakery / Pastries", "Desserts / Ice Cream", 0.50),
    ("Salads / Bowls", "Health-Focused", 0.60),
    ("Coffee / Tea", "Breakfast / Brunch", 0.30),
    ("Coffee / Tea", "Taiwanese", 0.30),       # bubble tea
    ("Sandwiches / Deli", "Salads / Bowls", 0.30),
    ("Coffee / Tea", "Desserts / Ice Cream", 0.20),
    ("Coffee / Tea", "Sandwiches / Deli", 0.20),
    ("Bakery / Pastries", "Breakfast / Brunch", 0.20),
    ("Coffee / Tea", "Health-Focused", 0.15),

    # Latin American
    ("Dominican", "Puerto Rican", 0.70),
    ("Colombian", "Venezuelan", 0.60),
    ("Dominican", "Cuban", 0.50),
    ("Puerto Rican", "Cuban", 0.50),
    ("Colombian", "Dominican", 0.30),
    ("Colombian", "Peruvian", 0.30),
    ("Venezuelan", "Dominican", 0.20),
    ("Venezuelan", "Peruvian", 0.20),
    ("Colombian", "Puerto Rican", 0.20),
    ("Cuban", "Venezuelan", 0.20),
    ("Peruvian", "Brazilian", 0.15),
    ("Mexican", "Colombian", 0.15),
    ("Mexican", "Dominican", 0.15),
    ("Colombian", "Brazilian", 0.10),
    ("Mexican", "Peruvian", 0.10),
    ("Mexican", "Venezuelan", 0.10),
    ("Mexican", "Puerto Rican", 0.10),
    ("Mexican", "Cuban", 0.10),

    # Caribbean / African
    ("Jamaican", "Haitian", 0.40),
    ("Haitian", "Dominican", 0.20),
    ("Ethiopian / Eritrean", "West African", 0.20),
    ("West African", "Jamaican", 0.15),
    ("West African", "Haitian", 0.15),
    ("Jamaican", "Dominican", 0.10),
    ("Jamaican", "Puerto Rican", 0.10),
    ("Haitian", "Puerto Rican", 0.10),
    ("Jamaican", "Southern / Soul Food", 0.10),
    ("West African", "Southern / Soul Food", 0.10),
    ("Ethiopian / Eritrean", "Middle Eastern", 0.10),
]


def build_matrix():
    m = pd.DataFrame(0.0, index=CUISINES_50, columns=CUISINES_50)
    for c in CUISINES_50:
        m.loc[c, c] = 1.0
    for a, b, v in PAIRS:
        assert a in m.index and b in m.index, (a, b)
        assert 0 <= v <= 1
        m.loc[a, b] = m.loc[b, a] = v
    return m


if __name__ == "__main__":
    m = build_matrix()
    ensure_dirs()
    m.to_csv(OUTPUTS / "cuisine_matrix.csv")
    nz = (m.values > 0).sum() - 50
    print(f"50x50 matrix, {nz} nonzero off-diagonal cells "
          f"({nz / (50 * 49):.1%} of pairs); rest are 0")
