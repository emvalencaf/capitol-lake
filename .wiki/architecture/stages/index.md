# Pipeline stages

* [Stage 1: Collect (Bronze)](collect.md) - House and Senate collectors write raw filings into Bronze.
* [Stage 2: Extract, by chamber and filing kind](extract.md) - Raw bytes become structured Filing/Transaction rows.
* [Stage 3: Ticker resolution and LLM fallback](ticker-resolution.md) - Resolves null tickers and, selectively, other null fields.
* [Stage 4: Quality gate](quality-gate.md) - Pure checks that can veto a Silver overwrite; not yet wired in.
* [Stage 5: Silver write](silver-write.md) - Serializes rows to Hive-partitioned Parquet in Silver.
