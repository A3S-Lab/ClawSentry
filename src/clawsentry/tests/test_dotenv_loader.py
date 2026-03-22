"""Tests for .env.clawsentry auto-loader (G-6)."""

import os
from pathlib import Path

import pytest

from clawsentry.cli.dotenv_loader import load_dotenv


class TestDotenvLoader:

    def test_loads_env_vars(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("MY_TEST_VAR=hello\nMY_OTHER=world\n")
        monkeypatch.chdir(tmp_path)
        # Remove any pre-existing values
        monkeypatch.delenv("MY_TEST_VAR", raising=False)
        monkeypatch.delenv("MY_OTHER", raising=False)
        count = load_dotenv()
        assert count == 2
        assert os.environ["MY_TEST_VAR"] == "hello"
        assert os.environ["MY_OTHER"] == "world"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("MY_EXISTING=from-file\n")
        monkeypatch.setenv("MY_EXISTING", "from-shell")
        monkeypatch.chdir(tmp_path)
        load_dotenv()
        assert os.environ["MY_EXISTING"] == "from-shell"

    def test_skips_comments_and_empty_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("# comment\n\nVALID_KEY=valid_value\n  \n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VALID_KEY", raising=False)
        count = load_dotenv()
        assert count == 1
        assert os.environ["VALID_KEY"] == "valid_value"

    def test_missing_env_file_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        count = load_dotenv()
        assert count == 0

    def test_handles_values_with_equals(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("URL=ws://host:8080/path?key=val\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("URL", raising=False)
        load_dotenv()
        assert os.environ["URL"] == "ws://host:8080/path?key=val"

    def test_strips_quotes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text('QUOTED="my value"\nSINGLE=\'other\'\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("QUOTED", raising=False)
        monkeypatch.delenv("SINGLE", raising=False)
        load_dotenv()
        assert os.environ["QUOTED"] == "my value"
        assert os.environ["SINGLE"] == "other"

    def test_returns_loaded_count(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("A=1\nB=2\nC=3\n")
        monkeypatch.chdir(tmp_path)
        for k in "ABC":
            monkeypatch.delenv(k, raising=False)
        count = load_dotenv()
        assert count == 3

    def test_search_dir_parameter(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("SEARCH_DIR_VAR=found\n")
        monkeypatch.delenv("SEARCH_DIR_VAR", raising=False)
        count = load_dotenv(search_dir=tmp_path)
        assert count == 1
        assert os.environ["SEARCH_DIR_VAR"] == "found"
