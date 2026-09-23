from capitol_lake.keys import bronze_key, silver_key


def test_bronze_key_matches_layout():
    assert bronze_key("house", 2024, "20012345", "pdf") == "bronze/house/year=2024/20012345.pdf"


def test_silver_key_matches_layout():
    assert (
        silver_key("transactions", "senate", 2024, "a1b2c3")
        == "silver/transactions/chamber=senate/year=2024/part-a1b2c3.parquet"
    )
