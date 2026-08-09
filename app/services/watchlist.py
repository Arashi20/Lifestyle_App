from app.models import WatchlistItem


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
SCORE_GOOD_POINTS = 9
SCORE_CAUTION_PENALTY = 8
SCORE_AVOID_PENALTY = 16
SCORE_LENGTH_PENALTY_PER_INGREDIENT = 0.4

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
    good_count = sum(1 for item in flagged if item.severity == "good")
    caution_count = sum(1 for item in flagged if item.severity == "caution")
    avoid_count = sum(1 for item in flagged if item.severity == "avoid")
    ingredient_count = len([part for part in ingredients_text.split(",") if part.strip()])

    score = (
        SCORE_BASE
        + good_count * SCORE_GOOD_POINTS
        - caution_count * SCORE_CAUTION_PENALTY
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
