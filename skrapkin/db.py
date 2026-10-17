"""MongoDB storage.

Collections:
  leads            one document per business, with an `emails` list of {address, source, status, ...}
  email_checks     every Hunter result, so an address is never paid for twice
  verified_emails  only addresses Hunter confirmed as valid: the user-facing "verified results"
"""

import re
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

from .validate import registered_domain, site_key

# Statuses a stored Hunter result can be reused for. 'unknown' may be transient, so it is rechecked.
CACHEABLE = ("valid", "invalid", "accept_all", "disposable", "claimed")


def now():
    return datetime.now(timezone.utc)


def lead_key(row):
    return site_key(row.get("website"), row.get("phones"), row.get("business"))


def seed_key(seed):
    """Same identity as lead_key, for a discovery seed (which names its phone field 'phone')."""
    return site_key(seed.get("website"), seed.get("phone"), seed.get("business"))


# Outcomes that won't change soon. Failures and setting-dependent drops (site down, no contact found,
# below the chosen confidence) are retried sooner.
STABLE_OUTCOMES = ("lead", "chain", "non_buyer")


def _split(value):
    return [p.strip() for p in (value or "").split(";") if p.strip()]


def _text_filter(text, fields):
    if not text.strip():
        return {}
    rx = {"$regex": re.escape(text.strip()), "$options": "i"}
    return {"$or": [{f: rx} for f in fields]}


class Database:
    def __init__(self, uri, db_name="skrapkin", client=None, timeout_ms=3000):
        self.client = client or MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
        self.db = self.client[db_name]
        self.leads = self.db["leads"]
        self.checks = self.db["email_checks"]
        self.verified = self.db["verified_emails"]
        self.checked = self.db["checked_sites"]
        self.meta = self.db["meta"]

    def connect(self):
        """Raise if the server is unreachable; create indexes otherwise."""
        self.client.admin.command("ping")
        self.leads.create_index("key", unique=True)
        self.leads.create_index([("country", 1), ("region", 1), ("category", 1)])
        self.verified.create_index([("country", 1), ("region", 1), ("category", 1)])
        self.checks.create_index("domain")
        self.checked.create_index("checked_at")
        self.backfill_history()

    def close(self):
        self.client.close()

    # leads --------------------------------------------------------------

    def upsert_lead(self, row, search=None):
        """Insert or merge a scraped lead. Existing per-email statuses are preserved."""
        key = lead_key(row)
        sources = row.get("email_sources") or {}
        existing = self.leads.find_one({"key": key}) or {}
        emails = list(existing.get("emails", []))
        known = {e["address"] for e in emails}
        for address in _split(row.get("emails")):
            if address not in known:
                emails.append({"address": address, "source": sources.get(address, "site"),
                               "status": "unchecked", "likelihood": None, "note": ""})
        phones = sorted(set(existing.get("phones", [])) | set(_split(row.get("phones"))))
        doc = {
            "key": key,
            "business": row.get("business") or existing.get("business", ""),
            "website": row.get("website") or existing.get("website", ""),
            "category": row.get("category") or (search or {}).get("category") or existing.get("category", ""),
            "country": row.get("country") or (search or {}).get("country") or existing.get("country", ""),
            "region": row.get("region") or (search or {}).get("region") or existing.get("region", ""),
            "city": row.get("city") or existing.get("city", ""),
            "confidence": row.get("confidence", existing.get("confidence", "")),
            "source_pages": row.get("source_pages", existing.get("source_pages", "")),
            "phones": phones,
            "emails": emails,
            "updated_at": now(),
        }
        self.leads.update_one({"key": key}, {"$set": doc, "$setOnInsert": {"created_at": now()}}, upsert=True)
        return key

    def list_leads(self, text="", category=None, country=None, region=None, limit=2000):
        query = _text_filter(text, ["business", "website", "city", "emails.address", "phones"])
        extra = {k: v for k, v in (("category", category), ("country", country), ("region", region)) if v}
        if query and extra:
            query = {"$and": [query, extra]}
        else:
            query = query or extra
        return list(self.leads.find(query).sort("updated_at", -1).limit(limit))

    def delete_leads(self, keys):
        return self.leads.delete_many({"key": {"$in": list(keys)}}).deleted_count

    def unchecked_emails(self):
        """Every (lead, email entry) still awaiting a decision."""
        for lead in self.leads.find({"emails.status": "unchecked"}):
            for entry in lead["emails"]:
                if entry["status"] == "unchecked":
                    yield lead, entry

    def set_email_status(self, address, status, **extra):
        fields = {"emails.$.status": status, **{f"emails.$.{k}": v for k, v in extra.items()}}
        return self.leads.update_many({"emails.address": address}, {"$set": fields}).modified_count

    # search history: every business we have already decided about ----------

    def mark_checked(self, key, outcome, search=None):
        search = search or {}
        self.checked.update_one(
            {"_id": key},
            {"$set": {"outcome": outcome, "checked_at": now(), "country": search.get("country", ""),
                      "region": search.get("region", ""), "category": search.get("category", "")}},
            upsert=True)

    def backfill_history(self):
        """One time only: count leads saved before the search history existed as already checked, so
        'only new businesses' doesn't redo them. Clearing the history later is not undone by this."""
        if self.meta.find_one({"_id": "history_backfilled"}):
            return 0
        added = 0
        for lead in self.leads.find({}, {"key": 1, "country": 1, "region": 1, "category": 1, "updated_at": 1}):
            result = self.checked.update_one(
                {"_id": lead["key"]},
                {"$setOnInsert": {"outcome": "lead", "checked_at": lead.get("updated_at") or now(),
                                  "country": lead.get("country", ""), "region": lead.get("region", ""),
                                  "category": lead.get("category", "")}},
                upsert=True)
            added += bool(result.upserted_id)
        self.meta.insert_one({"_id": "history_backfilled", "at": now(), "added": added})
        return added

    def checked_map(self, stable_days=180, transient_days=30):
        """{key: {country, region}} for businesses not worth checking again yet."""
        stable_cutoff = now() - timedelta(days=stable_days)
        transient_cutoff = now() - timedelta(days=transient_days)
        query = {"$or": [{"outcome": {"$in": list(STABLE_OUTCOMES)}, "checked_at": {"$gte": stable_cutoff}},
                         {"outcome": {"$nin": list(STABLE_OUTCOMES)}, "checked_at": {"$gte": transient_cutoff}}]}
        return {d["_id"]: {"country": d.get("country", ""), "region": d.get("region", "")}
                for d in self.checked.find(query, {"country": 1, "region": 1})}

    def checked_count(self):
        return self.checked.count_documents({})

    def clear_checked(self):
        return self.checked.delete_many({}).deleted_count

    # hunter results -----------------------------------------------------

    def get_check(self, address, max_age_days):
        doc = self.checks.find_one({"_id": address})
        if not doc or doc["status"] not in CACHEABLE:
            return None
        checked = doc["checked_at"]
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return doc if now() - checked <= timedelta(days=max_age_days) else None

    def accept_all_domains(self, max_age_days):
        """Domains where Hunter found the server accepts any address (so per-mailbox checks are moot)."""
        cutoff = now() - timedelta(days=max_age_days)
        return set(self.checks.distinct("domain", {"status": "accept_all", "checked_at": {"$gte": cutoff}}))

    def save_check(self, address, result):
        doc = {**result, "domain": address.split("@")[1], "checked_at": now()}
        self.checks.replace_one({"_id": address}, doc, upsert=True)

    # verified results ---------------------------------------------------

    def upsert_verified(self, address, lead, result):
        doc = {
            "email": address,
            "business": lead.get("business", ""), "website": lead.get("website", ""),
            "category": lead.get("category", ""), "country": lead.get("country", ""),
            "region": lead.get("region", ""), "city": lead.get("city", ""), "phones": lead.get("phones", []),
            "score": result.get("score"), "verified_at": now(),
        }
        self.verified.replace_one({"_id": address}, doc, upsert=True)

    def list_verified(self, text="", category=None, country=None, region=None, limit=5000):
        query = _text_filter(text, ["email", "business", "website", "city"])
        extra = {k: v for k, v in (("category", category), ("country", country), ("region", region)) if v}
        if query and extra:
            query = {"$and": [query, extra]}
        else:
            query = query or extra
        return list(self.verified.find(query).sort("verified_at", -1).limit(limit))

    def delete_verified(self, addresses):
        return self.verified.delete_many({"_id": {"$in": list(addresses)}}).deleted_count

    def stats(self):
        status_counts = {}
        for lead in self.leads.find({}, {"emails.status": 1}):
            for e in lead.get("emails", []):
                status_counts[e["status"]] = status_counts.get(e["status"], 0) + 1
        return {"leads": self.leads.count_documents({}), "checked": self.checked.count_documents({}),
                "emails": sum(status_counts.values()),
                "by_status": status_counts, "verified": self.verified.count_documents({})}
