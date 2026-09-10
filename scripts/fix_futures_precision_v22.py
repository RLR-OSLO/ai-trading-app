from pathlib import Path

p = Path('trader/derivatives.py')
s = p.read_text(encoding='utf-8')
old = '''        qty = (notional / price / step).to_integral_value(rounding=ROUND_DOWN) * step\n        if qty < minimum:\n            raise BinanceError(f"Futures quantity below minimum for {symbol}")\n        return qty\n'''
new = '''        qty = (notional / price / step).to_integral_value(rounding=ROUND_DOWN) * step\n        if qty < minimum:\n            raise BinanceError(f"Futures quantity below minimum for {symbol}")\n        precision = int(row.get("quantityPrecision", max(0, -step.normalize().as_tuple().exponent)))\n        quantum = Decimal("1").scaleb(-precision)\n        return qty.quantize(quantum, rounding=ROUND_DOWN)\n'''
if new not in s:
    if old not in s:
        raise SystemExit('missing marker: quantity precision')
    s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8')
    print('patched: futures quantity precision')
else:
    print('already: futures quantity precision')
print('FIX_V22_OK')
