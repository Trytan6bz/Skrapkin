import os
import uuid

import mongomock
import pytest

from skrapkin.db import Database

REAL_URI = os.environ.get("SKRAPKIN_TEST_MONGO_URI")  # e.g. mongodb://127.0.0.1:27018


@pytest.fixture(scope="session")
def _real_database():
    """One real database for the whole run. Creating and dropping a database per test exhausted MongoDB's
    open-file limit, so tests share this one and empty it between runs instead."""
    name = f"test_{uuid.uuid4().hex[:8]}"
    db = Database(REAL_URI, db_name=name)
    db.connect()
    real_close = db.close
    db.close = lambda: None   # code under test may close "its" connection; the shared one must stay open
    yield db
    db.client.drop_database(name)
    real_close()


@pytest.fixture(params=["mongomock"] + (["real-mongo"] if REAL_URI else []))
def database(request):
    if request.param == "mongomock":
        db = Database(None, client=mongomock.MongoClient())
        db.connect = lambda: None  # mongomock has no admin ping; indexes are covered by the real run
        yield db
        return
    db = request.getfixturevalue("_real_database")
    for name in db.db.list_collection_names():
        db.db[name].delete_many({})   # keep collections and indexes, drop the data
    yield db
