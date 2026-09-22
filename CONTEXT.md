# Capitol Lake

A data lake of US congressional stock-trading disclosures from the House and the Senate, collected as raw files and refined into structured, queryable records.

## Language

### Disclosures

**PTR**:
A Periodic Transaction Report, the filing in which a member of Congress discloses securities transactions.
_Avoid_: Trade report, STOCK Act filing

**Filing**:
One submitted PTR document, identified by its chamber and document id.
_Avoid_: Report, disclosure (when meaning a single document)

**Transaction**:
One line of a Filing describing a single purchase, sale or exchange of an asset.
_Avoid_: Trade, row, record

**Owner**:
Whose account the Transaction belongs to: the member, their spouse, jointly, or a dependent child.
_Avoid_: Holder, beneficiary

**Value range**:
The bracket of dollar amounts a Transaction falls in, as reported; disclosures never give an exact amount.
_Avoid_: Amount, value, price

**Digital filing**:
A Filing submitted as a text-layer PDF, extractable directly without OCR.
_Avoid_: Native PDF

**Scanned filing**:
A Filing submitted as a scanned paper form, requiring OCR; some fields (transaction type, capital-gains flag) are unreliable to extract from these.
_Avoid_: Image filing, OCR filing

### Dates

**Notification date**:
The date the member was notified of the Transaction, as printed on the Filing line.
_Avoid_: Disclosure date

**Disclosure lag**:
The number of days between the Transaction date and the date the Filing was submitted.
_Avoid_: Delay, reporting delay

### Layers

**Bronze**:
The immutable layer holding source files exactly as collected.
_Avoid_: Raw, landing

**Silver**:
The layer of structured Filings and Transactions extracted from bronze, keeping every line and its provenance.
_Avoid_: Clean, curated
