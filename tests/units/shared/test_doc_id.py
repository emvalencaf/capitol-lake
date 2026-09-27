import pytest

from shared.doc_id import UnknownDocIdPrefixError, route_doc_id


@pytest.mark.parametrize(
    ("doc_id", "kind"),
    [
        ("20012345", "digital"),
        ("20099999", "digital"),
        ("8212345", "scanned"),
        ("9112345", "scanned"),
    ],
)
def test_route_doc_id_classifies_known_prefixes(doc_id, kind):
    assert route_doc_id(doc_id) == kind


def test_route_doc_id_raises_on_unknown_prefix():
    with pytest.raises(UnknownDocIdPrefixError):
        route_doc_id("77012345")
