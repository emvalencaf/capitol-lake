"""House PTR form constants shared by the digital and scanned extractors.

Both `digital_extract` and `scanned_extract` read the same paper form's
owner-code column and asset-type/ticker suffix (`... (AMGN) [ST]`); this
module is the one place that mapping lives, so a new asset-type code or
owner code is added once rather than in both extractors.
"""

from __future__ import annotations

import re

from shared.schema import AssetType, Owner

OWNER_RE = re.compile(r"^(?P<owner>SP|JT|DC)\s+")
OWNERS = {"": Owner.SELF, "SP": Owner.SPOUSE, "JT": Owner.JOINT, "DC": Owner.DEPENDENT_CHILD}

ASSET_TYPE_CODE_RE = re.compile(r"\[(?P<code>[A-Z0-9]{2})\]\s*$", re.IGNORECASE)

# House asset-type codes (fd.house.gov/reference/asset-type-codes.aspx) the
# silver enum distinguishes; every other code is `OTHER`.
ASSET_TYPES = {
    "ST": AssetType.STOCK,
    "EF": AssetType.ETF,
    "MF": AssetType.MUTUAL_FUND,
    "GS": AssetType.BOND,
    "CS": AssetType.BOND,
    "OP": AssetType.OPTION,
    "CT": AssetType.CRYPTOCURRENCY,
    "RP": AssetType.REAL_ESTATE,
}

# The parenthesized token right before the asset-type code, e.g. "(AMGN)" in
# "Amgen Inc. - Common Stock (AMGN) [ST]". Only meaningful for stock/ETF
# lines: for every other asset type this same shape holds a CUSIP or other
# identifier, never a ticker.
PRINTED_SYMBOL_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9.\-/]{0,9})\)\s*\[[A-Za-z0-9]{2}\]\s*$")
