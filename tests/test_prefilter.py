from skrapkin.prefilter import likelihood

OK = lambda d: "ok"
BAD = lambda d: "bad"
UNKNOWN = lambda d: "unknown"


def score(email, website="https://acme.com", source="site", mx=OK):
    return likelihood(email, website, source, mx=mx)


def test_own_domain_role_mailbox_scores_highest():
    v = score("info@acme.com")
    assert v.score >= 85 and not v.reject


def test_own_domain_person_passes_default_threshold():
    assert score("john.smith@acme.com").score >= 60


def test_other_company_domain_stays_below_threshold():
    assert score("sales@otherco.com").score < 60


def test_osm_published_email_passes_threshold():
    assert score("hello@acme.io", website="", source="osm").score >= 60


def test_rejects_with_reasons():
    assert "format" in score("not-an-email").reject
    assert "placeholder" in score("noreply@acme.com").reject
    assert "disposable" in score("bob@mailinator.com").reject
    assert "auto-generated" in score("xk3j9q2w7z4m@acme.com").reject
    assert "cannot receive" in score("info@acme.com", mx=BAD).reject


def test_webmail_is_flagged_not_rejected():
    v = score("owner@gmail.com")
    assert v.webmail and not v.reject


def test_inconclusive_dns_lowers_score_but_does_not_reject():
    assert score("info@acme.com", mx=UNKNOWN).score < score("info@acme.com").score
    assert not score("info@acme.com", mx=UNKNOWN).reject


def test_real_names_are_not_gibberish():
    for name in ["christopher", "strickland", "mcdonnell", "schwartz.t", "jhernandez"]:
        assert not score(f"{name}@acme.com").reject, name
