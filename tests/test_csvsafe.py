import csv

from skrapkin import cli
from skrapkin.csvsafe import safe_cell, safe_row


def test_formula_payloads_are_neutralised():
    for bad in ['=HYPERLINK("http://evil","click")', "@SUM(1+1)", "+cmd|' /C calc'!A0", "-2+cmd", "\t=1+1"]:
        assert safe_cell(bad).startswith("'"), bad


def test_ordinary_values_and_phone_numbers_are_untouched():
    for ok in ["Acme Supply", "info@acme.com", "+17135550100", "+17135550100; +12815550111", "(713) 555-0100", "", None, 42]:
        assert safe_cell(ok) == ok


def test_rows_and_dicts():
    assert safe_row(["=1", "ok"]) == ["'=1", "ok"]
    assert safe_row({"a": "=1", "b": "ok"}) == {"a": "'=1", "b": "ok"}


def test_scrape_output_csv_is_safe(monkeypatch, tmp_path):
    seeds = tmp_path / "seeds.csv"
    seeds.write_text("category,business,website,phone,email,city,brand\nbuilding,=EVIL(),,+17135550100,,Houston,\n",
                     encoding="utf-8-sig")
    out = tmp_path / "leads.csv"
    cli.cmd_scrape(cli.argparse.Namespace(seeds=str(seeds), output=str(out), delay=0, max_pages=1,
                                          exclude_personal=False, any_domain=False, country="US",
                                          min_confidence="low", keep_chains=False), log=lambda m: None)
    row = list(csv.DictReader(open(out, encoding="utf-8-sig")))[0]
    assert row["business"] == "'=EVIL()" and row["phones"] == "+17135550100"
