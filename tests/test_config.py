from skrapkin import config


def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SKRAPKIN_HOME", str(tmp_path))
    monkeypatch.setattr(config, "keyring", None)  # force the private-file fallback


def test_settings_roundtrip_and_mongo_uri_stays_out_of_config_json(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    cfg = config.Config(min_likelihood=70, mongo_uri="mongodb+srv://user:pw@cluster.example.net")
    cfg.save()
    assert "pw" not in (tmp_path / "config.json").read_text()
    loaded = config.Config.load()
    assert loaded.min_likelihood == 70 and loaded.mongo_uri.endswith("cluster.example.net")


def test_defaults_when_nothing_saved(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    cfg = config.Config.load()
    assert cfg.mongo_uri == config.DEFAULT_MONGO_URI and cfg.max_credits_per_run == 100


def test_hunter_key_set_clear(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    assert config.get_hunter_key() is None
    config.set_hunter_key("  abc123  ")
    assert config.get_hunter_key() == "abc123"
    config.clear_hunter_key()
    assert config.get_hunter_key() is None


def test_unknown_keys_in_config_file_are_ignored(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    (tmp_path / "config.json").write_text('{"min_likelihood": 55, "from_the_future": 1}')
    assert config.Config.load().min_likelihood == 55
