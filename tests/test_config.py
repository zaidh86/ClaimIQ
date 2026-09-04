"""Config/.env loader tests — covering how Windows tools actually write .env files."""

import os

from claimiq.config import _load_dotenv


def _load(tmp_path, monkeypatch, raw_bytes: bytes, var: str = "CLAIMIQ_TEST_KEY"):
    monkeypatch.delenv(var, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_bytes(raw_bytes)
    _load_dotenv(env_file)
    return os.environ.get(var)


def test_plain_utf8_env(tmp_path, monkeypatch):
    assert _load(tmp_path, monkeypatch, b"CLAIMIQ_TEST_KEY=abc123\n") == "abc123"


def test_utf8_bom_env(tmp_path, monkeypatch):
    # PowerShell `>` redirection writes a UTF-8 BOM
    raw = b"\xef\xbb\xbfCLAIMIQ_TEST_KEY=bom-value\n"
    assert _load(tmp_path, monkeypatch, raw) == "bom-value"
    assert chr(0xFEFF) + "CLAIMIQ_TEST_KEY" not in os.environ  # no BOM-corrupted name


def test_utf16_env(tmp_path, monkeypatch):
    # Older Windows PowerShell Out-File default
    raw = "CLAIMIQ_TEST_KEY=utf16-value\n".encode("utf-16")  # includes BOM
    assert _load(tmp_path, monkeypatch, raw) == "utf16-value"


def test_export_prefix_and_quotes(tmp_path, monkeypatch):
    raw = b"export CLAIMIQ_TEST_KEY='quoted-value'\n"
    assert _load(tmp_path, monkeypatch, raw) == "quoted-value"


def test_empty_file_loads_nothing(tmp_path, monkeypatch):
    assert _load(tmp_path, monkeypatch, b"") is None


def test_comments_and_blanks_skipped(tmp_path, monkeypatch):
    raw = b"# comment\n\nCLAIMIQ_TEST_KEY=x\n"
    assert _load(tmp_path, monkeypatch, raw) == "x"


def test_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMIQ_TEST_KEY", "from-real-env")
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"CLAIMIQ_TEST_KEY=from-file\n")
    _load_dotenv(env_file)
    assert os.environ["CLAIMIQ_TEST_KEY"] == "from-real-env"


def test_missing_file_is_fine(tmp_path):
    _load_dotenv(tmp_path / "does-not-exist.env")  # must not raise
