from utils_symbols import list_tradeable_symbols
from utils_account import get_symbol_suffix
_all_tradeables = list_tradeable_symbols()
if _all_tradeables:
    SYMBOLS = {sym: sym for sym in _all_tradeables}
account_suffix = get_symbol_suffix()