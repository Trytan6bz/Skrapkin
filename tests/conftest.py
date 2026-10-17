import os
import uuid

import mongomock
import pytest
from pymongo import MongoClient

from skrapkin.db import Database

REAL_URI = os.environ.get("SKRAPKIN_TEST_MONGO_URI")  # e.g. mongodb://127.0.0.1:27018


@pytest.fixture(params=["mongomock"] + (["real-mongo"] if REAL_URI else []))
def database(request):
    if request.param == "mongomock":
        db = Database(None, client=mongomock.MongoClient())
        db.connect = lambda: None  # mongomock has no admin ping; indexes are covered by the real run
        yield db
        return
    name = f"test_{uuid.uuid4().hex[:8]}"
    db = Database(REAL_URI, db_name=name)
    db.connect()
    yield db
    db.client.drop_database(name)
    db.close()
