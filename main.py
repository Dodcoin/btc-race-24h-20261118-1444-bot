"""Capitulation-catcher bot for the make.fun cbBTC 1-minute bars race.

Strategy in one paragraph: this market is quiet (the median one-minute move
is a few basis points) while a full round trip costs roughly twenty to
thirty basis points in fees, modelled slippage and pool impact, so trading
often is a slow way to go broke. The bot therefore sits in cash and waits
for one specific accident: a fast drop of at least DROP_BPS over the last
DROP_WIN minutes that has stopped falling -- the lowest close of the last
BASE_WIN bars is at least BASE_AGE bars old and the price has already
lifted LIFT_BPS off that low. It then buys with (nearly) all its cash,
because a trade that is worth taking at all is worth taking at the size
the impact model still prices kindly, and it leaves on a fixed plan: out
at +TAKE_BPS, out at -STOP_BPS, whichever the market offers first. Every
number comes from the bars and the account the harness sends; the bot
reads no clock, no file and no environment, so two runs over the same
window give byte-identical orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy constants (all thresholds in basis points) ---
DROP_WIN = 60        # minutes over which the capitulation drop is measured
DROP_BPS = 80        # the drop must be at least this deep
BASE_WIN = 45        # bars scanned for the post-drop low
BASE_AGE = 20        # that low must be at least this many bars old
LIFT_BPS = 5         # and the price must have lifted at least this off it
STOP_BPS = 50        # leave if the trade is worse than this
TAKE_BPS = 200       # leave if the trade is better than this
MAX_SLIP_BPS = 150   # slippage cap attached to every order
WINDOW_BARS = 1440   # the scored window is always 1,440 one-minute bars
ENTRY_CUTOFF = 1350  # no new position in the last 90 bars of the window:
                     # it could not run its plan before the forced flatten
MAX_HOLD = 720       # a position older than this has had its chance

_closes = []         # every CBBTC close so far, in arrival order
_hold = [0]          # batches spent in the current position


def _bps(num, den):
    """(num / den - 1) in basis points, integer arithmetic only."""
    return (num * 10000) // den - 10000


def _entry_price(state, pos):
    """The position's average entry price, recovered from its booked cost."""
    s = state.symbols[SYMBOL]
    quote_scale = state.hello["capital"]["quote_scale"]
    return pos.cost * 10 ** (s["qty_scale"] + s["price_scale"]) // (pos.qty * 10 ** quote_scale)


def _decide(state, batch):
    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            _closes.append(int(bar["c"]))
    if state.warming_up or not _closes:
        return []

    pos = state.positions.get(SYMBOL)
    holding = pos is not None and pos.qty > 0
    close = _closes[-1]

    if holding:
        _hold[0] += 1
        gain = _bps(close, _entry_price(state, pos))
        if gain <= -STOP_BPS or gain >= TAKE_BPS or _hold[0] >= MAX_HOLD:
            return [{"side": "sell", "symbol": SYMBOL, "qty": pos.qty,
                     "max_slippage_bps": MAX_SLIP_BPS}]
        return []

    # Flat: look for the capitulation pattern, but never so late in the
    # window that the end-of-window flatten would decide the exit for us.
    _hold[0] = 0
    if state.seq - state.warmup_bars >= ENTRY_CUTOFF:
        return []
    if len(_closes) < DROP_WIN + BASE_WIN + 2:
        return []
    if _bps(close, _closes[-1 - DROP_WIN]) > -DROP_BPS:
        return []
    seg = _closes[-(BASE_WIN + 1):]
    low = min(seg)
    if seg.index(low) < len(seg) - 1 - BASE_AGE:
        return []  # the low is too fresh: it may still be falling
    if _bps(close, low) < LIFT_BPS:
        return []  # no lift off the low yet
    notional = min(state.cash, state.weight_room(SYMBOL))
    if notional < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    return [{"side": "buy", "symbol": SYMBOL, "notional_quote_units": notional,
             "max_slippage_bps": MAX_SLIP_BPS}]


def on_batch(state, batch):
    try:
        return _decide(state, batch)
    except Exception:
        return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
