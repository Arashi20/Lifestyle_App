"""Drift check: run from the repo root, with the main app's requirements installed.

The connector deploys standalone, so it keeps its own copy of the tables it
reads and of the goodness-score logic. This reports any table or column that
has been renamed or retyped in the main app's models, and any change to
app/services/watchlist.py that has not been mirrored into mcp/scoring.py.

    python mcp/check_drift.py
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import app.models as main_models  # noqa: E402

spec = importlib.util.spec_from_file_location('mirror_models', HERE / 'models.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)

ok = True

# --- Schema -------------------------------------------------------------
main_tables = {t.name: t for t in main_models.db.metadata.sorted_tables}
for table in mirror.db.metadata.sorted_tables:
    if table.name not in main_tables:
        print('MISSING TABLE:', table.name)
        ok = False
        continue
    src = main_tables[table.name]
    for col in table.columns:
        if col.name not in src.columns:
            print(f'MISSING COLUMN: {table.name}.{col.name}')
            ok = False
            continue
        a, b = type(col.type).__name__, type(src.columns[col.name].type).__name__
        if a != b:
            print(f'TYPE MISMATCH: {table.name}.{col.name}: mirror={a} main={b}')
            ok = False
    extra = set(src.columns.keys()) - set(table.columns.keys())
    print(f'{table.name}: {len(table.columns)} mirrored, not mirrored: {sorted(extra) or "none"}')

# --- Scoring ------------------------------------------------------------
MARKER = '# --- mirrored from app/services/watchlist.py below this line ---\n'
main_scoring = (ROOT / 'app' / 'services' / 'watchlist.py').read_text()
mirror_scoring = (HERE / 'scoring.py').read_text().split(MARKER, 1)[-1]
expected = main_scoring.replace('from app.models import WatchlistItem',
                                'from models import WatchlistItem')
if mirror_scoring == expected:
    print('scoring.py: identical to app/services/watchlist.py')
else:
    print('SCORING DRIFT: mcp/scoring.py no longer matches app/services/watchlist.py.')
    print('  Re-copy it, keeping the header and changing only the import line.')
    ok = False

print('\nNO DRIFT' if ok else '\nDRIFT FOUND')
sys.exit(0 if ok else 1)
