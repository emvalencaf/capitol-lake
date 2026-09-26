# Domain vocabulary

Sourced from `CONTEXT.md` at the repository root.

# Disclosures

* [PTR](ptr.md) - A Periodic Transaction Report, the filing type members disclose transactions in.
* [Filing](filing.md) - One submitted PTR document, identified by chamber and document id.
* [Transaction](transaction.md) - One line of a Filing describing a single purchase, sale or exchange.
* [Exchange](exchange.md) - A Transaction where one asset is given up and a different one received.
* [Owner](owner.md) - Whose account a Transaction belongs to.
* [Value range](value-range.md) - The bracket of dollar amounts a Transaction falls in.
* [Digital filing](digital-filing.md) - A text-layer PDF Filing, extractable without OCR.
* [Scanned filing](scanned-filing.md) - A scanned paper-form Filing, requiring OCR.

# Dates

* [Notification date](notification-date.md) - The date the member was notified of the Transaction.
* [Disclosure lag](disclosure-lag.md) - Days between the Transaction date and the Filing's submission.

# Layers

* [Bronze](bronze.md) - The immutable layer holding source files exactly as collected.
* [Silver](silver.md) - The layer of structured Filings and Transactions extracted from Bronze.
