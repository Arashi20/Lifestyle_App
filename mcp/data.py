"""The read queries behind every tool and endpoint.

Nothing in this module writes: it issues SELECTs and shapes the rows into JSON.
Both the MCP tools and the REST endpoints call these functions, so the two
surfaces can never drift apart.
"""

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from models import (
    PRODUCT_STATUSES,
    SEVERITIES,
    Haircut,
    Product,
    Profile,
    WatchlistItem,
)
from scoring import (
    _split_ingredients,
    find_flagged_ingredients,
    goodness_score,
    goodness_tier,
    worst_severity,
)

DEFAULT_PRODUCT_LIMIT = 50
DEFAULT_HAIRCUT_LIMIT = 20
MAX_LIMIT = 500
MAX_INGREDIENTS_TEXT = 10000

# Same threshold the home page uses for "Favorite haircuts".
FAVORITE_HAIRCUT_RATING = 8

SEVERITY_ORDER = {'avoid': 0, 'caution': 1, 'good': 2}


def iso(value):
    """Serialize a stored date, time or (naive UTC) datetime."""
    return value.isoformat() if value is not None else None


def clamp_int(raw, default, minimum=1, maximum=MAX_LIMIT):
    # bool is an int subclass; `true` is not a limit.
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def clean_str(raw):
    """A non-empty stripped string, or None for anything else."""
    if not isinstance(raw, str):
        return None
    return raw.strip() or None


def _contains(column, text):
    return column.ilike(f'%{text}%')


def _match_payload(item):
    return {
        'ingredient': item.ingredient_name,
        'severity': item.severity,
        'reason': item.reason,
    }


def _ingredient_analysis(ingredients_text, watchlist_items):
    """Watchlist matches and goodness score, exactly as the product pages show them."""
    flagged = find_flagged_ingredients(ingredients_text, watchlist_items)
    score = goodness_score(ingredients_text, watchlist_items)
    return {
        'goodness_score': score,
        'goodness_tier': goodness_tier(score),
        'warning': worst_severity(flagged),
        'concerning_matches': [_match_payload(i) for i in flagged
                               if i.severity in ('avoid', 'caution')],
        'good_matches': [_match_payload(i) for i in flagged if i.severity == 'good'],
    }


def _sleep_duration(profile):
    """Mirror of Profile.sleep_duration: bedtime rolls over to the next wake."""
    if not profile.sleep_time or not profile.wake_time:
        return None
    today = date.today()
    sleep_dt = datetime.combine(today, profile.sleep_time)
    wake_dt = datetime.combine(today, profile.wake_time)
    if wake_dt <= sleep_dt:
        wake_dt += timedelta(days=1)
    minutes = int((wake_dt - sleep_dt).total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    return {
        'minutes': minutes,
        'display': f'{hours}h {mins}m' if mins else f'{hours}h',
    }


def _profile_payload(profile):
    if profile is None:
        return None
    return {
        'skin_type': profile.skin_type,
        'preferred_brands': profile.preferred_brands,
        'preferred_ingredients': profile.preferred_ingredients,
        'notes': profile.notes,
        'sleep_schedule': {
            'sleep_time': profile.sleep_time.strftime('%H:%M') if profile.sleep_time else None,
            'wake_time': profile.wake_time.strftime('%H:%M') if profile.wake_time else None,
            'duration': _sleep_duration(profile),
        },
        'updated_at': iso(profile.updated_at),
    }


def _haircut_payload(cut):
    return {
        'id': cut.id,
        'date': iso(cut.date),
        'salon_or_barber': cut.salon_or_barber,
        'rating': cut.rating,
        'rating_scale': '1-10',
        'description': cut.description,
        'how_to_request': cut.how_to_request,
        'photo_url': cut.photo_url,
    }


def _product_payload(product, watchlist_items, include_ingredients):
    payload = {
        'id': product.id,
        'name': product.name,
        'brand': product.brand,
        'category': product.category,
        'status': product.status,
        'rating': product.rating,
        'rating_scale': '1-5',
        'skin_notes': product.skin_notes,
        'date_started': iso(product.date_started),
        'date_finished': iso(product.date_finished),
        'barcode': product.barcode,
        'photo_url': product.photo_url,
        'updated_at': iso(product.updated_at),
        'has_ingredients': bool(product.ingredients and product.ingredients.strip()),
    }
    payload.update(_ingredient_analysis(product.ingredients, watchlist_items))
    if include_ingredients:
        payload['ingredients'] = product.ingredients
    return payload


# --------------------------------------------------------------------------
# Collectors
# --------------------------------------------------------------------------

def collect_overview():
    """The home page: profile, product counts, favorite haircuts."""
    profile = Profile.query.order_by(Profile.id).first()

    status_counts = Counter(status for (status,) in Product.query.with_entities(Product.status))
    severity_counts = Counter(sev for (sev,) in WatchlistItem.query.with_entities(WatchlistItem.severity))

    current = (Product.query.filter_by(status='currently_using')
               .order_by(Product.category, Product.name).all())
    favorites = (Haircut.query.filter(Haircut.rating >= FAVORITE_HAIRCUT_RATING)
                 .order_by(Haircut.rating.desc(), Haircut.date.desc()).limit(3).all())
    latest_cut = Haircut.query.order_by(Haircut.date.desc(), Haircut.id.desc()).first()

    return {
        'profile': _profile_payload(profile),
        'product_counts': {status: status_counts.get(status, 0) for status in PRODUCT_STATUSES},
        'currently_using': [
            {'id': p.id, 'name': p.name, 'brand': p.brand, 'category': p.category,
             'rating': p.rating}
            for p in current
        ],
        'favorite_haircuts': [_haircut_payload(c) for c in favorites],
        'latest_haircut': _haircut_payload(latest_cut) if latest_cut else None,
        'days_since_last_haircut': (date.today() - latest_cut.date).days if latest_cut else None,
        'haircut_count': Haircut.query.count(),
        'watchlist_counts': {sev: severity_counts.get(sev, 0) for sev in SEVERITIES},
    }


def collect_products(status=None, category=None, search=None, product_id=None,
                     include_ingredients=False, limit=DEFAULT_PRODUCT_LIMIT):
    """Products with their watchlist matches and goodness score."""
    query = Product.query
    if product_id is not None:
        query = query.filter(Product.id == product_id)
    if status:
        query = query.filter(Product.status == status)
    if category:
        query = query.filter(_contains(Product.category, category))
    if search:
        query = query.filter(or_(_contains(Product.name, search),
                                 _contains(Product.brand, search)))

    total = query.count()
    products = query.order_by(Product.updated_at.desc(), Product.id.desc()).limit(limit).all()

    # One watchlist read for the whole list, as the products page does.
    watchlist_items = WatchlistItem.query.all()
    return {
        'filters': {'status': status, 'category': category, 'search': search,
                    'id': product_id},
        'total_matching': total,
        'returned': len(products),
        'products': [_product_payload(p, watchlist_items, include_ingredients)
                     for p in products],
        'score_note': ('goodness_score is the app\'s 0-100 heuristic from watchlist '
                       'matches and ingredient-list length (>=70 good, >=40 caution, '
                       'else avoid); null when the product has no ingredient list.'),
    }


def collect_haircuts(limit=DEFAULT_HAIRCUT_LIMIT, min_rating=None, search=None):
    query = Haircut.query
    if min_rating is not None:
        query = query.filter(Haircut.rating >= min_rating)
    if search:
        query = query.filter(or_(_contains(Haircut.salon_or_barber, search),
                                 _contains(Haircut.description, search),
                                 _contains(Haircut.how_to_request, search)))

    total = query.count()
    cuts = query.order_by(Haircut.date.desc(), Haircut.id.desc()).limit(limit).all()

    # Cadence is over every haircut, not just the filtered ones.
    dates = sorted({d for (d,) in Haircut.query.with_entities(Haircut.date)})
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    latest = dates[-1] if dates else None
    return {
        'filters': {'min_rating': min_rating, 'search': search},
        'total_matching': total,
        'returned': len(cuts),
        'haircuts': [_haircut_payload(c) for c in cuts],
        'days_since_last_haircut': (date.today() - latest).days if latest else None,
        'average_days_between_haircuts': round(sum(gaps) / len(gaps), 1) if gaps else None,
    }


def collect_watchlist(severity=None, search=None):
    query = WatchlistItem.query
    if severity:
        query = query.filter(WatchlistItem.severity == severity)
    if search:
        query = query.filter(or_(_contains(WatchlistItem.ingredient_name, search),
                                 _contains(WatchlistItem.reason, search)))
    items = query.all()
    items.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 99), i.ingredient_name.lower()))
    counts = Counter(i.severity for i in items)
    return {
        'filters': {'severity': severity, 'search': search},
        'counts': {sev: counts.get(sev, 0) for sev in SEVERITIES},
        'items': [{'id': i.id, **_match_payload(i)} for i in items],
        'matching_note': ('Matching is a case-insensitive substring check of each '
                          'ingredient_name against a product\'s ingredient list.'),
    }


def check_ingredients(ingredients_text):
    """Score an arbitrary ingredient list against the watchlist. Pure computation."""
    text = (ingredients_text or '')[:MAX_INGREDIENTS_TEXT]
    watchlist_items = WatchlistItem.query.all()
    result = _ingredient_analysis(text, watchlist_items)
    result['ingredient_count'] = len(_split_ingredients(text)) if text.strip() else 0
    return result
