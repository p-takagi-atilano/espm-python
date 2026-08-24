from espm.models import Address, Property


def test_model_serialization_excludes_raw_recursively_by_default() -> None:
    property_record = Property(
        id=100,
        name="Test Property",
        address=Address(city="Seattle"),
        raw={
            "name": {"#text": "Test Property"},
            "nested": {"raw": {"unsupported": "value"}},
        },
    )

    result = property_record.to_dict()

    assert result["id"] == 100
    assert result["address"]["city"] == "Seattle"
    assert "raw" not in result
    assert "raw" not in result["address"]


def test_model_serialization_can_include_raw() -> None:
    property_record = Property(id=100, raw={"unsupported": {"#text": "value"}})

    result = property_record.to_dict(include_raw=True)

    assert result["raw"] == {"unsupported": {"#text": "value"}}
