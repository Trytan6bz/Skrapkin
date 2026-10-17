"""User settings, kept outside the project folder. Secrets (Hunter key, Mongo URI) go in the OS keychain."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # keychain support is optional; secrets fall back to a private file
    keyring = None
    KeyringError = Exception

SERVICE = "SKrapkin"
DEFAULT_MONGO_URI = "mongodb://localhost:27017"


def config_dir():
    return Path(os.environ.get("SKRAPKIN_HOME") or Path.home() / ".skrapkin")


def _secrets_file():
    return config_dir() / "secrets.json"


def _read_secrets_file():
    try:
        return json.loads(_secrets_file().read_text())
    except (OSError, ValueError):
        return {}


def _write_secrets_file(data):
    path = _secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows ignores POSIX modes


def get_secret(name):
    if keyring is not None:
        try:
            value = keyring.get_password(SERVICE, name)
            if value:
                return value
        except KeyringError:
            pass
    return _read_secrets_file().get(name)


def set_secret(name, value):
    if keyring is not None:
        try:
            keyring.set_password(SERVICE, name, value)
            data = _read_secrets_file()
            if data.pop(name, None) is not None:
                _write_secrets_file(data)
            return "keychain"
        except KeyringError:
            pass
    data = _read_secrets_file()
    data[name] = value
    _write_secrets_file(data)
    return "file"


def delete_secret(name):
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE, name)
        except KeyringError:
            pass
    data = _read_secrets_file()
    if data.pop(name, None) is not None:
        _write_secrets_file(data)


@dataclass
class Config:
    db_name: str = "skrapkin"
    min_likelihood: int = 60        # emails scoring below this never reach Hunter
    max_credits_per_run: int = 100  # hard cap on Hunter lookups in one verification run
    recheck_days: int = 30          # reuse a stored Hunter result for this long
    save_to_database: bool = True
    verify_after_search: bool = False
    mongo_uri: str = DEFAULT_MONGO_URI  # stored in the keychain, not config.json

    @classmethod
    def load(cls):
        try:
            raw = json.loads((config_dir() / "config.json").read_text())
        except (OSError, ValueError):
            raw = {}
        known = {f.name for f in fields(cls)} - {"mongo_uri"}
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        # Environment first: containers have no keychain and configure everything through env vars.
        cfg.mongo_uri = os.environ.get("SKRAPKIN_MONGO_URI") or get_secret("mongo_uri") or DEFAULT_MONGO_URI
        return cfg

    def save(self):
        data = {k: v for k, v in asdict(self).items() if k != "mongo_uri"}
        path = config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        if self.mongo_uri == os.environ.get("SKRAPKIN_MONGO_URI"):
            return  # came from the environment: don't copy it into the keychain
        if self.mongo_uri and self.mongo_uri != DEFAULT_MONGO_URI:
            set_secret("mongo_uri", self.mongo_uri)
        else:
            delete_secret("mongo_uri")


def get_hunter_key():
    return os.environ.get("HUNTER_API_KEY") or get_secret("hunter_api_key")


def set_hunter_key(key):
    return set_secret("hunter_api_key", key.strip())


def clear_hunter_key():
    delete_secret("hunter_api_key")
