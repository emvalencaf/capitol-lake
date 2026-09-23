from capitol_lake.keys import bronze_key, bronze_meta_key, bronze_versioned_key, silver_key


def test_bronze_key_matches_layout():
    assert bronze_key("house", 2024, "20012345", "pdf") == "bronze/house/year=2024/20012345.pdf"


def test_bronze_versioned_key_matches_layout():
    assert (
        bronze_versioned_key("house", 2024, "20012345", "deadbeef12", "pdf")
        == "bronze/house/year=2024/20012345.deadbeef.pdf"
    )


def test_bronze_meta_key_appends_suffix():
    assert (
        bronze_meta_key("bronze/house/year=2024/20012345.pdf")
        == "bronze/house/year=2024/20012345.pdf.meta.json"
    )


def test_silver_key_matches_layout():
    assert (
        silver_key("transactions", "senate", 2024, "a1b2c3")
        == "silver/transactions/chamber=senate/year=2024/part-a1b2c3.parquet"
    )
