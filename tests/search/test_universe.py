import pandas as pd
from src.search.universe import sp500_membership, top_liquid


def _fake_html(url):
    cur = pd.DataFrame({"Symbol": ["AAA", "BRK.B"]})
    ch = pd.DataFrame([["2020-06-01", "AAA", "A co", "OLD", "Old co", "x"]])
    return [cur, ch]


def test_membership_reconstructs_history():
    m = sp500_membership("2020-05-25", read_html=_fake_html, today="2020-06-05")
    assert m.loc["2020-05-29", "OLD"] and not m.loc["2020-05-29", "AAA"]
    assert m.loc["2020-06-01", "AAA"] and not m.loc["2020-06-01", "OLD"]
    assert m["BRK-B"].all()


def test_top_liquid_ranks_by_dollar_volume():
    idx = pd.bdate_range("2020-01-01", periods=80)
    close = pd.DataFrame({"A": 10.0, "B": 10.0, "C": 10.0}, index=idx)
    vol = pd.DataFrame({"A": 100.0, "B": 300.0, "C": 200.0}, index=idx)
    mem = pd.DataFrame(True, index=idx, columns=close.columns)
    mem["C"] = False
    t = top_liquid(close, vol, mem, n=1)
    assert t.iloc[-1].to_dict() == {"A": False, "B": True, "C": False}
