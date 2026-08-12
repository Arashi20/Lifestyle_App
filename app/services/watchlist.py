import re

from app.models import WatchlistItem

# Matches the comma inside a chemical locant prefix like "1,2-Hexanediol" or
# "2,3-Butanediol", so it survives ingredient splitting instead of being
# treated as a separator between two fake ingredients ("1" and
# "2-Hexanediol"). Deliberately narrow — this can't perfectly parse every
# INCI list, but it handles the common case.
_LOCANT_COMMA = re.compile(r"(\d),(\d+-[A-Za-z])")


def _split_ingredients(ingredients_text):
    protected = _LOCANT_COMMA.sub(lambda m: m.group(1) + "\x00" + m.group(2), ingredients_text)
    return [part.replace("\x00", ",").strip() for part in protected.split(",") if part.strip()]


def _ingredient_position(ingredient_name, parts):
    """Index of the first split ingredient part containing ingredient_name,
    or None if it's not found there (shouldn't normally happen for an
    already-matched item, but stay defensive)."""
    name_lower = ingredient_name.lower()
    for idx, part in enumerate(parts):
        if name_lower in part.lower():
            return idx
    return None


def find_flagged_ingredients(ingredients_text, watchlist_items=None):
    """Watchlist entries whose ingredient_name appears in ingredients_text.

    Computed live rather than stored on the product, so a watchlist entry
    added after a product was saved still flags it immediately.
    """
    if not ingredients_text:
        return []
    if watchlist_items is None:
        watchlist_items = WatchlistItem.query.all()
    text = ingredients_text.lower()
    return [item for item in watchlist_items if item.ingredient_name.lower() in text]


def worst_severity(flagged_items):
    """Worst of the *concerning* (avoid/caution) matches, ignoring "good" ones.

    Used for the warning badge on product cards — a "good" match alone
    shouldn't trigger a warning.
    """
    concerning = [item for item in flagged_items if item.severity in ("avoid", "caution")]
    if not concerning:
        return None
    return "avoid" if any(item.severity == "avoid" for item in concerning) else "caution"


# Tunable weights for goodness_score — a judgment call, not a fixed formula.
# Retune here if it doesn't feel right against real products.
SCORE_BASE = 60
SCORE_GOOD_POINTS = 10
# Good matches beyond this don't add more bonus. Without a cap, a well-
# formulated product stacking many popular actives (increasingly common as
# the "good" watchlist grows) blows well past 100 before the length penalty
# can claw it back — e.g. a 9-good-match product hit 119 pre-clamp, which
# just looked identical to a barely-over-100 product once capped.
SCORE_GOOD_MATCH_CAP = 4
SCORE_CAUTION_PENALTY = 8
# Multiple caution matches are often the same underlying characteristic
# counted several times rather than independent concerns — e.g. "Fragrance"
# plus its own individually-disclosed components like Limonene/Linalool is
# really just one fragranced formulation, not three separate risks. Without
# this cap, a product that transparently discloses its fragrance allergens
# (as EU regulation requires above a small threshold) scores *worse* than a
# vaguer product that just says "Fragrance" with nothing broken out — the
# opposite of what should happen. No such cap on avoid: those entries are
# typically genuinely distinct concerns, and avoid stays fully penalized
# regardless by design.
SCORE_CAUTION_MATCH_CAP = 2
SCORE_AVOID_PENALTY = 16
SCORE_LENGTH_PENALTY_PER_INGREDIENT = 0.4

# INCI lists are legally ordered by descending concentration, but only
# strictly for ingredients above 1% — below that (where most "hero actives"
# actually sit), order isn't regulated, so we can't claim fine-grained
# position precision. A coarse early/late split is honest about that: a
# "good" match in the first half of the list gets full credit, one in the
# second half gets reduced credit (still some — a small amount isn't
# nothing). By request, this only applies to "good" matches — avoid/caution
# stay fully penalized regardless of position.
SCORE_GOOD_LATE_POSITION_THRESHOLD = 0.5
SCORE_GOOD_LATE_POSITION_WEIGHT = 0.5

SCORE_TIER_THRESHOLDS = (("good", 70), ("caution", 40))  # else "avoid"


def goodness_score(ingredients_text, watchlist_items=None):
    """0-100 heuristic: rewards matched "good" ingredients, penalizes
    avoid/caution matches (avoid worse than caution) and long ingredient
    lists. None when there's no ingredients text to score at all — a
    product we know nothing about shouldn't display a misleading number.
    """
    if not ingredients_text or not ingredients_text.strip():
        return None

    flagged = find_flagged_ingredients(ingredients_text, watchlist_items)
    parts = _split_ingredients(ingredients_text)
    ingredient_count = len(parts)
    caution_count = sum(1 for item in flagged if item.severity == "caution")
    avoid_count = sum(1 for item in flagged if item.severity == "avoid")

    good_weights = []
    for item in flagged:
        if item.severity != "good":
            continue
        position = _ingredient_position(item.ingredient_name, parts)
        is_late = (
            position is not None
            and ingredient_count
            and (position / ingredient_count) >= SCORE_GOOD_LATE_POSITION_THRESHOLD
        )
        good_weights.append(SCORE_GOOD_LATE_POSITION_WEIGHT if is_late else 1.0)

    # When capping, keep the highest-weight (earliest / full-credit) matches
    # first rather than an arbitrary subset.
    good_weights.sort(reverse=True)
    good_bonus_weight = sum(good_weights[:SCORE_GOOD_MATCH_CAP])

    score = (
        SCORE_BASE
        + good_bonus_weight * SCORE_GOOD_POINTS
        - min(caution_count, SCORE_CAUTION_MATCH_CAP) * SCORE_CAUTION_PENALTY
        - avoid_count * SCORE_AVOID_PENALTY
        - ingredient_count * SCORE_LENGTH_PENALTY_PER_INGREDIENT
    )
    return round(max(0, min(100, score)))


def goodness_tier(score):
    """Maps a score to the same avoid/caution/good vocabulary (and badge
    CSS) already used everywhere else in the app."""
    if score is None:
        return None
    for tier, threshold in SCORE_TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return "avoid"
