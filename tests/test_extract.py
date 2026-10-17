from skrapkin.extract import contact_links, extract_emails, extract_name, extract_phones, same_site_emails

HTML = """
<html><head><title>Home | Acme Widgets</title></head><body>
<a href="mailto:Sales@acme.com?subject=hi">Email</a>
<p>Or reach owner@gmail.com, or support [at] acme [dot] com. Call (281) 555-0100.</p>
<img src="logo@2x.png">
<a href="/contact-us">Contact</a><a href="https://other.com/about">Other</a>
</body></html>
"""


def test_emails_include_free_mail_by_default_and_skip_images():
    assert extract_emails(HTML) == ["owner@gmail.com", "sales@acme.com", "support@acme.com"]


def test_emails_exclude_personal_on_request():
    assert extract_emails(HTML, include_personal=False) == ["sales@acme.com", "support@acme.com"]


def test_phone_and_name():
    assert extract_phones(HTML) == ["+12815550100"]
    assert extract_name(HTML) == "Acme Widgets"


def test_contact_links_same_domain_only():
    assert contact_links(HTML, "https://acme.com/") == ["https://acme.com/contact-us"]


def test_same_site_emails_drops_other_companies_but_keeps_free_mail():
    emails = {"a@acme.com", "b@mail.acme.com", "c@other.com", "d@yahoo.com", "e@outlook.com"}
    assert same_site_emails(emails, "https://www.acme.com/x") == {
        "a@acme.com", "b@mail.acme.com", "d@yahoo.com", "e@outlook.com"}


def test_contact_links_skip_branch_pages():
    html = '<a href="/locations">About our locations</a><a href="/contact">Contact</a>'
    assert contact_links(html, "https://acme.com/") == ["https://acme.com/contact"]
