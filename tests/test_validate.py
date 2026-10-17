from skrapkin.validate import (chain_domains, is_aggregator, is_junk_email, normalize_phone,
                                  registered_domain)


def test_junk_emails():
    assert is_junk_email("noreply@acme.com")
    assert is_junk_email("a1b2c3d4e5f6a7b8c9d0e1f2@sentry.io")
    assert is_junk_email("name@example.com")
    assert not is_junk_email("info@acme.com")


def test_phone_normalization_dedupes_formats():
    assert normalize_phone("(281) 548-3600") == normalize_phone("+1-281-548-3600") == "+12815483600"
    assert normalize_phone("555-123-4567") is None


def test_chain_detection():
    seeds = [{"website": f"https://www.bigchain.com/store/{i}"} for i in range(3)]
    seeds.append({"website": "https://localshop.com"})
    assert chain_domains(seeds) == {"bigchain.com"}


def test_aggregator_and_registered_domain():
    assert is_aggregator("https://www.facebook.com/somebiz")
    assert registered_domain("https://www.acme.com/x") == "acme.com"


def test_non_buyer_names():
    from skrapkin.validate import is_non_buyer
    assert is_non_buyer("Plumbers Local Union No. 68 Group Protection Plan")
    assert is_non_buyer("Electrical Training Center")
    assert not is_non_buyer("Houston Hardwoods")
