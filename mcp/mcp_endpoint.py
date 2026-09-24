"""Model Context Protocol endpoint.

Speaks the Streamable HTTP transport at ``POST /mcp`` in stateless mode: each
JSON-RPC request gets a plain JSON response, so there is no session held in
memory and the service can restart without breaking a connected client.

Every tool is a read. There is no tool that writes, the collectors in
``data.py`` only issue SELECTs, and the database connection itself is opened
read-only (see ``server.py``), so a connected chatbot cannot modify anything.
"""

import json

from flask import Blueprint, current_app, jsonify, request

import config
from auth import authenticate
from data import (
    DEFAULT_HAIRCUT_LIMIT,
    DEFAULT_PRODUCT_LIMIT,
    MAX_INGREDIENTS_TEXT,
    check_ingredients,
    clamp_int,
    clean_str,
    collect_haircuts,
    collect_overview,
    collect_products,
    collect_watchlist,
)
from models import PRODUCT_STATUSES, SEVERITIES

mcp_bp = Blueprint('mcp', __name__)

SERVER_NAME = 'lifestyle'
SERVER_VERSION = '1.0.0'

# Protocol revisions this server can speak, newest first.
SUPPORTED_PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

READ_ONLY_HINTS = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}

INSTRUCTIONS = (
    'Read-only access to a personal skincare & haircare tracker. get_overview '
    'is the home page (skin type, preferences, sleep schedule, what is in use, '
    'favorite haircuts); get_products lists products with their ingredient '
    'watchlist matches and 0-100 goodness score; get_haircuts is the haircut '
    'history with "how to request this again" notes; get_ingredient_watchlist '
    'is the personal avoid/caution/good ingredient list; check_ingredients '
    'scores any ingredient list against that watchlist without saving it. '
    'Nothing here can change the data.'
)

TOOLS = [
    {
        'name': 'get_overview',
        'title': 'Profile overview',
        'description': (
            'Read the home page: skin type, preferred brands and ingredients, '
            'personal notes, sleep schedule (bedtime, wake time, duration), how '
            'many products are in each status, the products currently in use, '
            'favorite haircuts (rated 8/10 or higher), the latest haircut and how '
            'many days ago it was, and watchlist size. Start here for any general '
            'question about the routine or preferences.'
        ),
        'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_products',
        'title': 'Skincare / haircare products',
        'description': (
            'Read the products page: each product with brand, category, status '
            '(currently_using, wishlist, finished, abandoned), 1-5 rating, skin '
            'notes on what worked or did not, dates, and the ingredient analysis '
            'the app shows - goodness score (0-100) and tier, warning level, and '
            'which watchlist ingredients it contains (concerning and good) with '
            'the reason for each. Newest updated first. The raw ingredient list '
            'is only included when include_ingredients is true, since it is long.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string', 'enum': PRODUCT_STATUSES,
                    'description': 'Only products in this status.',
                },
                'category': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring of the category, e.g. "serum", "SPF", "shampoo".',
                },
                'search': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring of the product name or brand.',
                },
                'id': {
                    'type': 'integer', 'minimum': 1,
                    'description': 'Return only the product with this id.',
                },
                'include_ingredients': {
                    'type': 'boolean',
                    'description': 'Set true to include each product\'s full ingredient list. Defaults to false.',
                },
                'limit': {
                    'type': 'integer', 'minimum': 1, 'maximum': 200,
                    'description': f'Maximum products to return (1-200, default {DEFAULT_PRODUCT_LIMIT}).',
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_haircuts',
        'title': 'Haircut history',
        'description': (
            'Read the haircuts page: each haircut with date, salon or barber, '
            '1-10 rating, description, the "how to request this again" notes and '
            'photo link, newest first - plus days since the last haircut and the '
            'average number of days between haircuts.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'limit': {
                    'type': 'integer', 'minimum': 1, 'maximum': 200,
                    'description': f'Maximum haircuts to return (1-200, default {DEFAULT_HAIRCUT_LIMIT}).',
                },
                'min_rating': {
                    'type': 'integer', 'minimum': 1, 'maximum': 10,
                    'description': 'Only haircuts rated at least this (1-10), e.g. 8 for favorites.',
                },
                'search': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring of the salon/barber, description or request notes, e.g. "fade".',
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'get_ingredient_watchlist',
        'title': 'Ingredient watchlist',
        'description': (
            'Read the personal ingredient watchlist: every ingredient flagged as '
            'avoid, caution or good, with the reason. These are what the goodness '
            'score and product warnings are computed from.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'severity': {
                    'type': 'string', 'enum': SEVERITIES,
                    'description': 'Only entries with this severity.',
                },
                'search': {
                    'type': 'string',
                    'description': 'Optional case-insensitive substring of the ingredient name or reason.',
                },
            },
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
    {
        'name': 'check_ingredients',
        'title': 'Check an ingredient list',
        'description': (
            'Score an ingredient list that is not saved in the app - e.g. a product '
            'being considered in a shop - against the personal watchlist, exactly '
            'the way the app scores saved products: goodness score (0-100) and tier, '
            'warning level, and which avoid/caution/good ingredients it contains. '
            'Nothing is saved.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'ingredients': {
                    'type': 'string', 'maxLength': MAX_INGREDIENTS_TEXT,
                    'description': 'The comma-separated INCI ingredient list, as printed on the packaging.',
                },
            },
            'required': ['ingredients'],
            'additionalProperties': False,
        },
        'annotations': READ_ONLY_HINTS,
    },
]


def _enum(raw, allowed):
    value = clean_str(raw)
    return value if value in allowed else None


def run_tool(name, arguments):
    """Dispatch a tool call to its read-only collector."""
    arguments = arguments or {}

    if name == 'get_overview':
        return collect_overview()

    if name == 'get_products':
        product_id = arguments.get('id')
        return collect_products(
            status=_enum(arguments.get('status'), PRODUCT_STATUSES),
            category=clean_str(arguments.get('category')),
            search=clean_str(arguments.get('search')),
            product_id=clamp_int(product_id, None, maximum=2**31 - 1) if product_id is not None else None,
            include_ingredients=arguments.get('include_ingredients') is True,
            limit=clamp_int(arguments.get('limit'), DEFAULT_PRODUCT_LIMIT, maximum=200))

    if name == 'get_haircuts':
        min_rating = arguments.get('min_rating')
        return collect_haircuts(
            limit=clamp_int(arguments.get('limit'), DEFAULT_HAIRCUT_LIMIT, maximum=200),
            min_rating=clamp_int(min_rating, None, maximum=10) if min_rating is not None else None,
            search=clean_str(arguments.get('search')))

    if name == 'get_ingredient_watchlist':
        return collect_watchlist(
            severity=_enum(arguments.get('severity'), SEVERITIES),
            search=clean_str(arguments.get('search')))

    if name == 'check_ingredients':
        ingredients = arguments.get('ingredients')
        if not isinstance(ingredients, str) or not ingredients.strip():
            raise ValueError('ingredients must be a non-empty string')
        return check_ingredients(ingredients)

    raise KeyError(name)


def _result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def handle_message(message):
    """Handle one JSON-RPC message; returns None for notifications."""
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, 'Request must be a JSON-RPC object')

    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params')
    if not isinstance(params, dict):
        params = {}

    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _result(request_id, {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
            'instructions': INSTRUCTIONS,
        })

    if method in ('notifications/initialized', 'notifications/cancelled'):
        return None

    if method == 'ping':
        return _result(request_id, {})

    if method == 'tools/list':
        return _result(request_id, {'tools': TOOLS})

    if method == 'tools/call':
        name = params.get('name')
        try:
            payload = run_tool(name, params.get('arguments'))
        except KeyError:
            return _error(request_id, INVALID_PARAMS, f'Unknown tool: {name}')
        except ValueError as exc:
            return _error(request_id, INVALID_PARAMS, str(exc))
        except Exception:
            current_app.logger.exception('MCP tool %s failed', name)
            # Tool failures are reported in-band so the model can react to them.
            return _result(request_id, {
                'content': [{'type': 'text', 'text': f'Failed to read {name}.'}],
                'isError': True,
            })
        return _result(request_id, {
            'content': [{'type': 'text', 'text': json.dumps(payload, indent=2, default=str)}],
            'structuredContent': payload,
            'isError': False,
        })

    if method in ('resources/list', 'prompts/list'):
        # Not declared in capabilities, but some clients probe anyway.
        return _error(request_id, METHOD_NOT_FOUND, f'{method} is not supported')

    if 'id' not in message:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f'Unknown method: {method}')


@mcp_bp.route('/mcp', methods=['POST'])
def mcp_endpoint():
    if not config.mcp_enabled():
        return jsonify({'error': 'disabled',
                        'message': 'Set MCP_ENABLED=1 to enable this endpoint'}), 404

    _, error = authenticate()
    if error is not None:
        return error

    message = request.get_json(silent=True)
    if message is None:
        return jsonify(_error(None, PARSE_ERROR, 'Request body must be JSON')), 400

    if isinstance(message, list):
        # Batches were dropped in the 2025-06-18 revision, but older clients
        # may still send one.
        responses = [r for r in (handle_message(m) for m in message) if r is not None]
        return jsonify(responses) if responses else ('', 202)

    response = handle_message(message)
    return jsonify(response) if response is not None else ('', 202)


@mcp_bp.route('/mcp', methods=['GET', 'DELETE'])
def mcp_no_stream():
    """No server-initiated stream, and no session state to delete."""
    if not config.mcp_enabled():
        return jsonify({'error': 'disabled'}), 404
    _, error = authenticate()
    if error is not None:
        return error
    if request.method == 'DELETE':
        return '', 204
    return jsonify(_error(None, METHOD_NOT_FOUND,
                          'This server is stateless; SSE streams are not offered')), 405
