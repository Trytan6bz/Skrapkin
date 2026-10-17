import pytest

from skrapkin import cli, discover, regions
from skrapkin.extract import contact_links, extract_phones, same_site_emails
from skrapkin.prefilter import likelihood
from skrapkin.validate import chain_domains, is_aggregator, is_non_buyer, registered_domain


# ---- countries and regions -------------------------------------------------------------------------

def test_every_country_is_listed_with_regions_where_iso_defines_them():
    assert len(regions.countries()) >= 245
    for code, expected in {"US": 50, "CA": 13, "GB": 4, "DE": 16, "NG": 37, "IN": 36, "AU": 8, "BR": 27, "JP": 47}.items():
        assert len(regions.regions(code)) >= expected, code


def test_find_country_accepts_codes_names_and_common_aliases():
    assert regions.find_country("ng") == "NG" and regions.find_country("Nigeria") == "NG"
    assert regions.find_country("United Kingdom") == "GB" and regions.find_country("UK") == "GB"
    assert regions.find_country("Côte d'Ivoire") == "CI" or regions.find_country("ivory coast") == "CI"
    assert regions.find_country("Narnia") is None and regions.find_country("") is None


def test_find_region_by_code_or_name_ignoring_case_and_accents():
    assert regions.find_region("US", "texas")["code"] == "US-TX"
    assert regions.find_region("US", "US-TX")["name"] == "Texas"
    assert regions.find_region("DE", "Bayern")["code"] == "DE-BY"
    assert regions.find_region("NG", "lagos")["code"] == "NG-LA"
    assert regions.find_region("US", "Atlantis") is None and regions.find_region("US", "") is None
    assert regions.find_region("XX", "Texas") is None


def test_place_names_are_validated():
    assert regions.clean_place("  São   Paulo ") == "São Paulo"
    assert regions.clean_place("") == "" and regions.clean_place(None) == ""
    with pytest.raises(ValueError):
        regions.clean_place("x" * 81)
    assert regions.clean_place("Lagos\nIsland") == "Lagos Island"        # pasted line breaks become spaces
    for bad in ["Lagos\x00", "Lagos\x1b[31m"]:                          # real control characters are refused
        with pytest.raises(ValueError):
            regions.clean_place(bad)


# ---- Overpass query construction -------------------------------------------------------------------------

def test_query_scopes_to_country_region_and_place():
    q = discover.build_query("toys", "ng", regions.find_region("NG", "Lagos"), "Ikeja", cap=500)
    assert 'area["ISO3166-1"="NG"]->.c;' in q
    assert '["ISO3166-2"="NG-LA"]' in q and '["name"="Lagos"]' in q
    assert '["name"="Ikeja"]' in q and "area.r" in q
    assert q.rstrip().endswith("out tags center 500;")


def test_whole_country_query_has_no_region_clause_and_is_capped():
    q = discover.build_query("building", "DE", None, None, cap=800)
    assert "ISO3166-2" not in q and "(.c;)->.a;" in q and "center 800;" in q


def test_user_text_cannot_inject_overpass_statements():
    evil = 'x"];out;node(1);//'
    q = discover.build_query("toys", "US", None, evil)
    assert 'x\\"];out;node(1);//' in q          # the quote is escaped, so it stays inside the string
    assert q.count("out tags center") == 1
    with pytest.raises(ValueError):
        discover.build_query("toys", 'US"];out;', None, None)
    with pytest.raises(ValueError):
        discover.build_query("toys", "ZZ", None, None)


def test_unknown_region_is_rejected_before_any_request(monkeypatch):
    monkeypatch.setattr(discover.requests, "post", lambda *a, **k: pytest.fail("must not call the network"))
    with pytest.raises(ValueError, match="known region"):
        discover.discover("toys", "US", "Atlantis")


def test_discover_passes_a_cap_scaled_to_the_limit(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"elements": [{"tags": {"name": "Acme", "website": "https://acme.ng"}}]}

    monkeypatch.setattr(discover.requests, "post", lambda url, data, **k: sent.update(data) or Resp())
    leads = discover.discover("clothing", "NG", "NG-LA", None, limit=50)
    assert leads[0]["business"] == "Acme" and "center 400;" in sent["data"]


# ---- the CLI ------------------------------------------------------------------------------------------

def test_cli_discover_tags_seeds_with_country_and_region(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "discover", lambda category, country, region, place, limit: seen.update(
        country=country, region=region, place=place) or [{"business": "Acme", "website": "https://acme.com.ng",
                                                          "phone": "", "email": "", "city": "Ikeja", "brand": "",
                                                          "category": category}])
    out = tmp_path / "seeds.csv"
    cli.cmd_discover(cli.argparse.Namespace(country="Nigeria", region="lagos", place="Ikeja", category="toys",
                                            output=str(out), limit=None), log=lambda m: None)
    assert seen["country"] == "NG" and seen["region"]["code"] == "NG-LA" and seen["place"] == "Ikeja"
    text = out.read_text(encoding="utf-8-sig")
    assert "NG" in text and "Lagos" in text


def test_cli_requires_a_valid_country():
    with pytest.raises(ValueError, match="country"):
        cli.cmd_discover(cli.argparse.Namespace(country="Narnia", category="toys", output="x.csv"))


def test_old_area_flag_still_means_a_place_name(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "discover", lambda category, country, region, place, limit: seen.update(
        place=place) or [])
    cli.main(["discover", "--country", "US", "--area", "Houston", "--category", "toys", "-o", str(tmp_path / "s.csv")])
    assert seen["place"] == "Houston"


# ---- language and region handling elsewhere ---------------------------------------------------------------

def test_country_code_domains_keep_their_own_identity():
    assert registered_domain("https://www.acme.co.uk/x") == "acme.co.uk"
    assert registered_domain("https://shop.acme.com.ng") == "acme.com.ng"
    assert registered_domain("https://acme.com.br") == "acme.com.br"
    assert registered_domain("https://one.myshopify.com") != registered_domain("https://two.myshopify.com")


def test_uk_businesses_are_not_mistaken_for_one_chain():
    seeds = [{"website": f"https://shop{i}.co.uk"} for i in range(5)]
    assert chain_domains(seeds) == set()
    assert chain_domains(seeds + [{"website": "https://bigco.co.uk/a"}] * 3) == {"bigco.co.uk"}


def test_own_domain_emails_work_for_country_code_domains():
    emails = {"info@acme.co.uk", "sales@mail.acme.co.uk", "x@other.co.uk", "me@gmail.com", "a@gmx.de"}
    assert same_site_emails(emails, "https://www.acme.co.uk") == {"info@acme.co.uk", "sales@mail.acme.co.uk",
                                                                  "me@gmail.com", "a@gmx.de"}
    assert likelihood("info@acme.co.uk", "https://acme.co.uk", mx=lambda d: "ok").score >= 85


def test_international_webmail_is_recognised():
    for address in ["a@gmx.de", "b@mail.ru", "c@yahoo.co.uk", "d@qq.com", "e@web.de", "f@uol.com.br"]:
        assert likelihood(address, "https://acme.com", mx=lambda d: "ok").webmail, address


@pytest.mark.parametrize("region,text,expected", [
    ("NG", "Call us: 0802 123 4567", "+2348021234567"),
    ("GB", "Tel 020 7946 0958", "+442079460958"),
    ("DE", "Telefon: 030 901820", "+4930901820"),
    ("BR", "Fone (11) 91234-5678", "+5511912345678"),
    ("IN", "Phone: 098765 43210", "+919876543210"),
    ("US", "(281) 555-0100", "+12815550100"),
])
def test_local_phone_formats_are_read_per_country(region, text, expected):
    assert extract_phones(f"<p>{text}</p>", region)[0] == expected


def test_contact_pages_are_found_in_other_languages():
    html = ('<a href="/kontakt">Kontakt</a><a href="/de/ueber-uns">Über uns</a><a href="/es/contacto">x</a>'
            '<a href="/nous-contacter">x</a><a href="/chi-siamo">x</a><a href="/联系我们">联系我们</a>'
            '<a href="/standorte">Unsere Standorte</a>')
    found = contact_links(html, "https://acme.de/")
    assert len(found) == 6 and not any("standorte" in u for u in found)


def test_non_buyers_are_filtered_in_other_languages():
    for name in ["Gewerkschaft Bau", "Escuela Técnica", "École Primaire", "Scuola Media", "Igreja Batista"]:
        assert is_non_buyer(name), name
    assert not is_non_buyer("Ferretería López") and not is_non_buyer("Quincaillerie Dupont")


def test_regional_listing_sites_are_not_treated_as_business_sites():
    for url in ["https://www.justdial.com/x", "https://www.pagesjaunes.fr/y", "https://shop.business.site"]:
        assert is_aggregator(url), url
    assert not is_aggregator("https://acme.co.uk")
