from utils_account import mt5
def list_tradeable_symbols():
    """Lấy tất cả symbols có thể trade trong MT5 (không bị disabled)."""
    try:
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return []
        tradables = []
        for s in all_symbols:
            try:
                # SYMBOL_TRADE_MODE_DISABLED = 0
                if getattr(s, 'trade_mode', 0) != 0:
                    tradables.append(s.name)
            except Exception:
                continue
        return sorted(list(dict.fromkeys(tradables)))
    except Exception:
        return []