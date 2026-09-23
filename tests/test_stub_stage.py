from capitol_lake.stages.stub import process


def test_process_echoes_bronze_key():
    result = process("bronze/house/year=2024/20012345.pdf")

    assert result == {"bronze_key": "bronze/house/year=2024/20012345.pdf", "ok": True}
