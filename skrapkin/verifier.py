"""Verification pipeline: free local filtering first, so only likely-real emails cost Hunter credits."""

from dataclasses import dataclass, field

from .hunter import HunterError, InvalidKey, QuotaExceeded
from .prefilter import likelihood
from .validate import mx_status

# Hunter statuses -> the status shown on the lead
LEAD_STATUS = {"valid": "valid", "invalid": "invalid", "accept_all": "accept_all", "webmail": "webmail",
               "disposable": "invalid", "unknown": "unknown", "claimed": "claimed"}
MAX_CONSECUTIVE_ERRORS = 5


@dataclass
class Candidate:
    address: str
    likelihood: int
    lead_key: str
    business: str = ""
    website: str = ""
    reasons: list = field(default_factory=list)

    @property
    def domain(self):
        return self.address.split("@")[1]


@dataclass
class Plan:
    to_check: list = field(default_factory=list)   # [Candidate], best first
    filtered: list = field(default_factory=list)   # [(Candidate, reason)] never sent: not likely real
    webmail: list = field(default_factory=list)    # [Candidate] gmail etc: can't be confirmed by SMTP
    cached: list = field(default_factory=list)     # [(Candidate, stored Hunter doc)] already paid for
    inferred: list = field(default_factory=list)   # [Candidate] domain known to accept everything

    @property
    def saved(self):
        return len(self.filtered) + len(self.webmail) + len(self.cached) + len(self.inferred)

    def summary(self):
        return (f"{len(self.to_check)} to check with Hunter; skipping {self.saved} "
                f"({len(self.filtered)} unlikely to be real, {len(self.webmail)} webmail, "
                f"{len(self.cached)} already checked, {len(self.inferred)} on accept-all domains)")


def build_plan(db, cfg, mx=None):
    """Classify every unchecked email. Reads only: nothing is written or paid for here."""
    mx = mx or mx_status  # looked up at call time so tests can stub DNS
    plan = Plan()
    accept_all = db.accept_all_domains(cfg.recheck_days)
    seen = set()
    for lead, entry in db.unchecked_emails():
        address = entry["address"]
        if address in seen:
            continue
        seen.add(address)
        verdict = likelihood(address, lead.get("website", ""), entry.get("source", "site"), mx=mx)
        cand = Candidate(address, verdict.score, lead["key"], lead.get("business", ""),
                         lead.get("website", ""), verdict.reasons)
        if verdict.reject:
            plan.filtered.append((cand, verdict.reject))
        elif verdict.webmail:
            plan.webmail.append(cand)
        elif (stored := db.get_check(address, cfg.recheck_days)):
            plan.cached.append((cand, stored))
        elif cand.domain in accept_all:
            plan.inferred.append(cand)
        elif verdict.score < cfg.min_likelihood:
            plan.filtered.append((cand, f"unlikely to be real (score {verdict.score}/{cfg.min_likelihood})"))
        else:
            plan.to_check.append(cand)
    plan.to_check.sort(key=lambda c: -c.likelihood)
    return plan


def _apply(db, cand, status, result=None, note=""):
    db.set_email_status(cand.address, status, likelihood=cand.likelihood, note=note)
    if status == "valid":
        for lead in db.leads.find({"emails.address": cand.address}):
            db.upsert_verified(cand.address, lead, result or {})


def run_plan(db, client, plan, cfg, log=print, progress=lambda done, total: None,
             should_stop=lambda: False, budget=None):
    """Apply the free decisions, then spend Hunter lookups on to_check, best first."""
    for cand, reason in plan.filtered:
        _apply(db, cand, "filtered", note=reason)
    for cand in plan.webmail:
        _apply(db, cand, "webmail", note="webmail addresses can't be confirmed")
    for cand, stored in plan.cached:
        _apply(db, cand, LEAD_STATUS.get(stored["status"], "unknown"), stored, note="from an earlier check")
    for cand in plan.inferred:
        _apply(db, cand, "accept_all", note="domain accepts any address")

    limit = cfg.max_credits_per_run if budget is None else min(cfg.max_credits_per_run, budget)
    queue = plan.to_check[:limit]
    stats = {"checked": 0, "valid": 0, "invalid": 0, "accept_all": 0, "unknown": 0, "errors": 0,
             "skipped_free": plan.saved, "left_unchecked": 0, "stopped": ""}
    accept_all_now, errors_in_row, decided = set(), 0, 0
    for i, cand in enumerate(queue):
        if should_stop():
            stats["stopped"] = "stopped by you"
            break
        progress(i, len(queue))
        if cand.domain in accept_all_now:
            _apply(db, cand, "accept_all", note="domain accepts any address")
            stats["skipped_free"] += 1
            decided += 1
            continue
        try:
            result = client.verify(cand.address)
            errors_in_row = 0
        except QuotaExceeded as e:
            stats["stopped"] = str(e)
            break
        except InvalidKey:
            raise
        except HunterError as e:
            stats["errors"] += 1
            errors_in_row += 1
            log(f"could not verify {cand.address}: {e}")
            if errors_in_row >= MAX_CONSECUTIVE_ERRORS:
                stats["stopped"] = "too many errors in a row"
                break
            continue
        db.save_check(cand.address, result)
        status = LEAD_STATUS.get(result["status"], "unknown")
        _apply(db, cand, status, result)
        if result["status"] == "accept_all":
            accept_all_now.add(cand.domain)
        stats["checked"] += 1
        decided += 1
        bucket = status if status in stats else "unknown"
        stats[bucket] += 1
        log(f"{cand.address}: {result['status']}")
    progress(len(queue), len(queue))
    stats["left_unchecked"] = len(plan.to_check) - decided  # over budget, errored, or stopped early
    return stats
