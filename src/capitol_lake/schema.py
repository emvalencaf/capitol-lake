"""Silver-layer schema: `Filing` and `Transaction` models.

Filing-level metadata (chamber, filer, filing date) lives once per `Filing`
and is never repeated on a `Transaction` line. Owner and transaction-type
keep both a canonical enum and the raw source text, since disclosures vary
in wording that the enum discards. A reported value is a `(min, max)`
bracket, never a fabricated point estimate, matching what PTRs actually
disclose. `member_id` is intentionally absent: identity resolution is
deferred to the gold layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from datetime import date
from enum import Enum


class Chamber(Enum):
    HOUSE = "house"
    SENATE = "senate"


class Owner(Enum):
    """Whose account a Transaction belongs to."""

    SELF = "self"
    SPOUSE = "spouse"
    JOINT = "joint"
    DEPENDENT_CHILD = "dependent_child"


class TransactionType(Enum):
    """Canonical House transaction types, plus Senate's `Exchange`."""

    PURCHASE = "purchase"
    SALE_FULL = "sale_full"
    SALE_PARTIAL = "sale_partial"
    EXCHANGE = "exchange"


class AssetType(Enum):
    """Broad asset category; ticker resolution is only attempted for stock/ETF."""

    STOCK = "stock"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    BOND = "bond"
    OPTION = "option"
    CRYPTOCURRENCY = "cryptocurrency"
    REAL_ESTATE = "real_estate"
    OTHER = "other"


def _check_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r}")


def _check_not_empty(name: str, value: str) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True)
class Provenance:
    """Where a row's data came from, for row-level auditability."""

    bronze_key: str
    extractor: str

    def __post_init__(self) -> None:
        if not self.bronze_key:
            raise ValueError("bronze_key must not be empty")
        if not self.extractor:
            raise ValueError("extractor must not be empty")


@dataclass(frozen=True)
class ValueRange:
    """The `(min, max)` bracket a Transaction's reported value falls in."""

    min: float
    max: float

    def __post_init__(self) -> None:
        if self.min < 0:
            raise ValueError(f"min must be >= 0, got {self.min!r}")
        if self.max < self.min:
            raise ValueError(f"max ({self.max!r}) must be >= min ({self.min!r})")


@dataclass(frozen=True)
class Filing:
    """One submitted PTR document, identified by its chamber and doc id."""

    doc_id: str
    chamber: Chamber
    filer_name: str
    filing_date: date
    year: int
    confidence: float
    provenance: Provenance

    def __post_init__(self) -> None:
        _check_not_empty("doc_id", self.doc_id)
        _check_not_empty("filer_name", self.filer_name)
        _check_confidence(self.confidence)


@dataclass(frozen=True)
class Transaction:
    """One line of a Filing describing a single purchase, sale or exchange.

    `filing_date` is consumed only to derive `disclosure_lag`; it is not
    stored on the row, since filing-level metadata lives on `Filing` and
    must not repeat per transaction line. Ticker resolution (attempted only
    for stock/ETF `asset_type`) lands in `ticker`, left null otherwise.

    `notification_date`, `filing_status`, `sub_owner` (the form's
    "Subholding Of" line) and `description` are optional per-line fields an
    extractor may or may not find. Each is null when not found, never
    guessed, and `field_confidence` records how sure the extractor is of
    each such field, so a null reads as "not found" rather than "unknown".
    `notification_date` is kept exactly as printed, even when it precedes
    `transaction_date` (a known source-side bug).
    """

    doc_id: str
    line_no: int
    owner: Owner
    owner_raw: str
    transaction_type: TransactionType
    transaction_type_raw: str
    asset_type: AssetType
    asset_description: str
    transaction_date: date
    filing_date: InitVar[date]
    value_range: ValueRange
    confidence: float
    provenance: Provenance
    ticker: str | None = None
    notification_date: date | None = None
    filing_status: str | None = None
    sub_owner: str | None = None
    description: str | None = None
    field_confidence: Mapping[str, float] = field(default_factory=dict)
    disclosure_lag: int = field(init=False)

    def __post_init__(self, filing_date: date) -> None:
        _check_not_empty("doc_id", self.doc_id)
        if self.line_no < 1:
            raise ValueError(f"line_no must be >= 1, got {self.line_no!r}")
        _check_not_empty("asset_description", self.asset_description)
        _check_confidence(self.confidence)
        for value in self.field_confidence.values():
            _check_confidence(value)
        object.__setattr__(self, "disclosure_lag", (filing_date - self.transaction_date).days)
