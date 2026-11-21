import numpy as np
import pandas as pd
from src.search.families import Ctx, FAMILIES, grid

IDX = pd.bdate_range("2015-01-01", periods=600)


def _ctx():
    rng = np.random.default_rng(0)
    cols = ["SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "TLT", "GLD", "SH"]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .01, (600, len(cols))), 0)),
                         index=IDX, columns=cols)
    return Ctx(close=close, members=None, liquid=None)


def test_no_lookahead_every_family():
    ctx = _ctx()
    for t in [t for t in grid() if t.params.get("universe") not in ("stocks", "crypto", "s2")][:60]:
        w1 = t.weights(ctx)
        c2 = ctx.close.copy()
        c2.iloc[400:] *= 1.5                      # change the future only
        w2 = t.weights(Ctx(c2, None, None))
        pd.testing.assert_frame_equal(w1.iloc[:400], w2.iloc[:400], check_dtype=False,
                                      obj=t.name)


def test_grid_is_large_and_unique():
    g = grid()
    assert len(g) >= 500
    assert len({t.name for t in g}) == len(g)
    assert {t.family for t in g} >= set(FAMILIES)
