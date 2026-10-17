from skrapkin.db import lead_key


def row(**kw):
    base = {"business": "Acme Supply", "website": "https://www.acme.com/contact", "emails": "info@acme.com",
            "phones": "+12815550100", "city": "Houston", "category": "building", "confidence": "high",
            "source_pages": "https://acme.com"}
    return {**base, **kw}


def test_lead_key_uses_site_domain_else_name_and_phone():
    assert lead_key(row()) == "acme.com"
    assert lead_key(row(website="", business="Joe's", phones="+1555; +1666")) == "joe's|+1555"


def test_upsert_merges_and_keeps_existing_email_status(database):
    database.upsert_lead(row(), {"country": "US", "region": "Texas"})
    database.set_email_status("info@acme.com", "valid", likelihood=90)
    database.upsert_lead(row(emails="info@acme.com; sales@acme.com", phones="+12815550111"), {"country": "US", "region": "Texas"})
    [lead] = database.list_leads()
    assert {e["address"]: e["status"] for e in lead["emails"]} == {"info@acme.com": "valid",
                                                                   "sales@acme.com": "unchecked"}
    assert lead["phones"] == ["+12815550100", "+12815550111"] and (lead["country"], lead["region"]) == ("US", "Texas")


def test_search_and_filters(database):
    database.upsert_lead(row(), {"country": "US", "region": "Texas"})
    database.upsert_lead(row(business="Bolt Toys", website="https://bolt.com", emails="x@bolt.com",
                             category="toys"), {"country": "US", "region": "Ohio"})
    assert [l["business"] for l in database.list_leads(text="bolt")] == ["Bolt Toys"]
    assert [l["business"] for l in database.list_leads(text="info@acme")] == ["Acme Supply"]
    assert [l["business"] for l in database.list_leads(region="Ohio", text="toys.")] == []  # regex-escaped
    assert [l["business"] for l in database.list_leads(category="toys", country="US", region="Ohio")] == ["Bolt Toys"]


def test_checks_are_reused_only_for_stable_results(database):
    database.save_check("a@acme.com", {"status": "valid", "score": 90})
    database.save_check("b@acme.com", {"status": "unknown"})
    assert database.get_check("a@acme.com", 30)["status"] == "valid"
    assert database.get_check("b@acme.com", 30) is None
    assert database.get_check("a@acme.com", 0) is None  # expired


def test_accept_all_domains(database):
    database.save_check("a@loose.com", {"status": "accept_all"})
    database.save_check("b@strict.com", {"status": "valid"})
    assert database.accept_all_domains(30) == {"loose.com"}


def test_verified_collection_roundtrip_and_delete(database):
    database.upsert_verified("info@acme.com", {"business": "Acme", "country": "US", "region": "Texas", "category": "building"},
                             {"score": 93})
    assert [v["email"] for v in database.list_verified(text="acme")] == ["info@acme.com"]
    assert database.delete_verified(["info@acme.com"]) == 1
    assert database.list_verified() == []


def test_stats(database):
    database.upsert_lead(row(emails="a@acme.com; b@acme.com"), {"country": "US", "region": "Texas"})
    database.set_email_status("a@acme.com", "valid")
    s = database.stats()
    assert s["leads"] == 1 and s["emails"] == 2 and s["by_status"] == {"valid": 1, "unchecked": 1}


def test_leads_are_filterable_by_country_and_region_worldwide(database):
    database.upsert_lead(row(business="Lagos Hardware", website="https://lagoshw.com.ng", emails="a@lagoshw.com.ng"),
                         {"country": "NG", "region": "Lagos"})
    database.upsert_lead(row(), {"country": "US", "region": "Texas"})
    assert [l["business"] for l in database.list_leads(country="NG")] == ["Lagos Hardware"]
    assert [l["business"] for l in database.list_leads(country="NG", region="Lagos")] == ["Lagos Hardware"]
    assert [l["business"] for l in database.list_leads(country="US")] == ["Acme Supply"]
    assert database.list_leads(country="NG", region="Texas") == []


def test_lead_key_separates_uk_and_nigerian_sites_that_share_a_public_suffix():
    assert lead_key(row(website="https://acme.co.uk")) == "acme.co.uk"
    assert lead_key(row(website="https://other.co.uk")) == "other.co.uk"
