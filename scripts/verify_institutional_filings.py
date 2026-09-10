"""Verify what institutional trading firms actually file with the SEC.

Supporting evidence for ``research/institutional_landscape.md``. Matches firm
names against the full EDGAR filer registry, then pulls the actual form types
each filer has submitted.

Uses the bulk cik-lookup-data.txt (one download, every EDGAR filer -- roughly
1.06m entries) plus data.sec.gov's structured submissions API. No scraping of
HTML pages.

Two things to know before re-running this:

* **SEC blocks undeclared automated access.** Requests without a browser-like
  User-Agent return HTTP 403 with "Your Request Originates from an Undeclared
  Automated Tool" -- which parses as "this firm files nothing" unless you check
  the status code. The first run of this script produced zero matches for all
  53 firms for exactly that reason. A zero result here needs the same
  scepticism as a surprising positive one.
* **Name matching is noisy.** Substring matching on legal entity names produces
  false positives (a search for "Susquehanna" matches an unrelated radio
  holding company). Treat the output as a starting point for CIK-level
  confirmation, not as a finished answer.

Prerequisite: download the registry once, to the same directory as this
script::

    curl -A "Mozilla/5.0 (compatible; academic-research)" \\
        https://www.sec.gov/Archives/edgar/cik-lookup-data.txt \\
        -o cik_lookup.txt
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; academic-research)",
    "Accept-Encoding": "gzip, deflate",
}

HERE = Path(__file__).parent

FIRMS = [
    ("Jane Street", "hft_prop", ["JANE STREET"]),
    ("Citadel Securities", "hft_prop", ["CITADEL SECURITIES"]),
    ("Jump Trading", "hft_prop", ["JUMP TRADING", "JUMP FINANCIAL"]),
    ("Hudson River Trading", "hft_prop", ["HUDSON RIVER TRADING"]),
    ("Virtu Financial", "hft_prop", ["VIRTU FINANCIAL"]),
    ("DRW Holdings", "hft_prop", ["DRW HOLDINGS", "DRW SECURITIES"]),
    ("Optiver", "hft_prop", ["OPTIVER"]),
    ("IMC", "hft_prop", ["IMC CHICAGO", "IMC FINANCIAL", "INTERNATIONAL MARKETMAKERS"]),
    ("Susquehanna International", "hft_prop", ["SUSQUEHANNA"]),
    ("Tower Research Capital", "hft_prop", ["TOWER RESEARCH"]),
    ("XTX Markets", "hft_prop", ["XTX MARKETS"]),
    ("Flow Traders", "hft_prop", ["FLOW TRADERS"]),
    ("Two Sigma Securities", "hft_prop", ["TWO SIGMA SECURITIES"]),
    ("GTS", "hft_prop", ["GTS SECURITIES", "GLOBAL TRADING SYSTEMS"]),
    ("Wolverine Trading", "hft_prop", ["WOLVERINE TRADING", "WOLVERINE HOLDINGS"]),
    ("Akuna Capital", "hft_prop", ["AKUNA"]),
    ("Belvedere Trading", "hft_prop", ["BELVEDERE TRADING"]),
    ("Chicago Trading Company", "hft_prop", ["CHICAGO TRADING"]),
    ("Old Mission Capital", "hft_prop", ["OLD MISSION"]),
    ("Quantlab", "hft_prop", ["QUANTLAB"]),
    ("Radix Trading", "hft_prop", ["RADIX TRADING"]),
    ("Vatic", "hft_prop", ["VATIC"]),
    ("Headlands Technologies", "hft_prop", ["HEADLANDS"]),
    ("Tradebot", "hft_prop", ["TRADEBOT"]),
    ("PEAK6", "hft_prop", ["PEAK6", "PEAK 6"]),
    ("Renaissance Technologies", "quant_fund", ["RENAISSANCE TECHNOLOGIES"]),
    ("Two Sigma Investments", "quant_fund", ["TWO SIGMA INVESTMENTS"]),
    ("D. E. Shaw", "quant_fund", ["D. E. SHAW", "D E SHAW"]),
    ("Citadel Advisors", "quant_fund", ["CITADEL ADVISORS"]),
    ("Millennium Management", "quant_fund", ["MILLENNIUM MANAGEMENT"]),
    ("Point72", "quant_fund", ["POINT72", "POINT 72"]),
    ("Balyasny", "quant_fund", ["BALYASNY"]),
    ("ExodusPoint", "quant_fund", ["EXODUSPOINT"]),
    ("AQR Capital", "quant_fund", ["AQR CAPITAL"]),
    ("Bridgewater Associates", "quant_fund", ["BRIDGEWATER ASSOCIATES"]),
    ("Man Group", "quant_fund", ["MAN GROUP", "AHL PARTNERS", "MAN INVESTMENTS"]),
    ("PDT Partners", "quant_fund", ["PDT PARTNERS"]),
    ("WorldQuant", "quant_fund", ["WORLDQUANT"]),
    ("Voleon", "quant_fund", ["VOLEON"]),
    ("Squarepoint", "quant_fund", ["SQUAREPOINT"]),
    ("Marshall Wace", "quant_fund", ["MARSHALL WACE"]),
    ("Winton", "quant_fund", ["WINTON"]),
    ("Schonfeld", "quant_fund", ["SCHONFELD"]),
    ("Capula", "quant_fund", ["CAPULA"]),
    ("Qube Research", "quant_fund", ["QUBE RESEARCH"]),
    ("Acadian Asset Management", "factor_manager", ["ACADIAN ASSET"]),
    ("Dimensional Fund Advisors", "factor_manager", ["DIMENSIONAL FUND ADVISORS"]),
    ("Research Affiliates", "factor_manager", ["RESEARCH AFFILIATES"]),
    ("Arrowstreet Capital", "factor_manager", ["ARROWSTREET"]),
    ("Los Angeles Capital", "factor_manager", ["LOS ANGELES CAPITAL"]),
    ("Robeco", "factor_manager", ["ROBECO"]),
    ("Numerai", "factor_manager", ["NUMERAI"]),
    ("First Quadrant", "factor_manager", ["FIRST QUADRANT"]),
]


def load_registry() -> list[tuple[str, str]]:
    """Parse cik-lookup-data.txt into (NAME, CIK) pairs."""
    raw = (HERE / "cik_lookup.txt").read_text(encoding="latin-1")
    pairs = []
    for line in raw.splitlines():
        parts = line.rstrip(":").split(":")
        if len(parts) >= 2 and parts[-1].isdigit():
            pairs.append((parts[0].upper(), parts[-1]))
    return pairs


def forms_for(cik: str) -> tuple[list[str], str]:
    """Return (distinct form types, official EDGAR name) for a CIK."""
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return [], ""
        d = r.json()
        forms = d.get("filings", {}).get("recent", {}).get("form", [])
        seen, out = set(), []
        for f in forms:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out, d.get("name", "")
    except Exception:  # noqa: BLE001
        return [], ""


def main() -> None:
    registry = load_registry()
    print(f"EDGAR registry entries parsed: {len(registry):,}\n")

    results = []
    for display, category, patterns in FIRMS:
        matches = []
        for name, cik in registry:
            if any(p in name for p in patterns):
                matches.append({"edgar_name": name, "cik": cik})
        # dedupe by CIK, keep first few
        seen, uniq = set(), []
        for m in matches:
            if m["cik"] not in seen:
                seen.add(m["cik"])
                uniq.append(m)

        row = {
            "firm": display, "category": category,
            "edgar_match_count": len(uniq),
            "matches": uniq[:6],
            "forms": [],
        }
        if uniq:
            all_forms = set()
            for m in uniq[:3]:
                fl, official = forms_for(m["cik"])
                m["official_name"] = official
                m["forms"] = fl
                all_forms.update(fl)
                time.sleep(0.12)
            row["forms"] = sorted(all_forms)
        results.append(row)

        flag = ",".join(f for f in row["forms"] if f in
                        ("13F-HR", "10-K", "13F-NT", "SC 13G", "SC 13D", "X-17A-5"))
        print(f"{display:28} matches:{len(uniq):3}  key-forms: {flag or '(none)'}")

    (HERE / "firm_filings.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("\nWrote firm_filings.json")


if __name__ == "__main__":
    main()
