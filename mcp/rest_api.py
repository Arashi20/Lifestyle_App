"""Plain REST view of the same data, for curl and scripts.

GET only - there is no route here that writes.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from auth import authenticate, token_required
from data import (
    DEFAULT_HAIRCUT_LIMIT,
    DEFAULT_PRODUCT_LIMIT,
    check_ingredients,
    clamp_int,
    clean_str,
    collect_haircuts,
    collect_overview,
    collect_products,
    collect_watchlist,
)
from models import PRODUCT_STATUSES, SEVERITIES

rest_api = Blueprint('rest_api', __name__, url_prefix='/api/v1')


def _flag(name):
    return request.args.get(name, '').lower() in ('1', 'true', 'yes')


def _enum(name, allowed):
    value = clean_str(request.args.get(name))
    return value if value in allowed else None


@rest_api.route('/overview', methods=['GET'])
@token_required
def overview_endpoint():
    return jsonify(collect_overview())


@rest_api.route('/products', methods=['GET'])
@token_required
def products_endpoint():
    product_id = request.args.get('id')
    return jsonify(collect_products(
        status=_enum('status', PRODUCT_STATUSES),
        category=clean_str(request.args.get('category')),
        search=clean_str(request.args.get('search')),
        product_id=clamp_int(product_id, None, maximum=2**31 - 1) if product_id else None,
        include_ingredients=_flag('include_ingredients'),
        limit=clamp_int(request.args.get('limit'), DEFAULT_PRODUCT_LIMIT, maximum=200)))


@rest_api.route('/haircuts', methods=['GET'])
@token_required
def haircuts_endpoint():
    min_rating = request.args.get('min_rating')
    return jsonify(collect_haircuts(
        limit=clamp_int(request.args.get('limit'), DEFAULT_HAIRCUT_LIMIT, maximum=200),
        min_rating=clamp_int(min_rating, None, maximum=10) if min_rating else None,
        search=clean_str(request.args.get('search'))))


@rest_api.route('/watchlist', methods=['GET'])
@token_required
def watchlist_endpoint():
    return jsonify(collect_watchlist(
        severity=_enum('severity', SEVERITIES),
        search=clean_str(request.args.get('search'))))


@rest_api.route('/check-ingredients', methods=['GET'])
@token_required
def check_ingredients_endpoint():
    ingredients = clean_str(request.args.get('ingredients'))
    if not ingredients:
        return jsonify({'error': 'bad_request',
                        'message': 'Pass the ingredient list as ?ingredients=...'}), 400
    return jsonify(check_ingredients(ingredients))


@rest_api.route('/ping', methods=['GET'])
def ping_endpoint():
    """Cheap authenticated check that a token works."""
    username, error = authenticate()
    if error is not None:
        return error
    return jsonify({
        'ok': True,
        'user': username,
        'scope': 'read',
        'server_time': datetime.now(timezone.utc).isoformat(),
    })
