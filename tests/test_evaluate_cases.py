"""Parametrized pytest tests driven by test_cases.yaml.

Each YAML test case becomes a pytest test. Each file verdict becomes
an assertion with a clear error message showing expected vs actual.
"""

import pathlib

import pytest
import yaml

from dirdigest import core

TEST_CASES_FILE = pathlib.Path(__file__).resolve().parent / "test_cases.yaml"

ALL_FILES = [
    "README.md",
    "setup.py",
    ".env",
    ".gitignore",
    "src/main.py",
    "src/config.py",
    "src/utils/helpers.py",
    "src/utils/__init__.py",
    "src/utils/vendor/lib.py",
    "src/feature/module.py",
    "src/feature/tests/test_module.py",
    "tests/conftest.py",
    "tests/test_main.py",
    "tests/test_utils.py",
    "tests/fixtures/data.json",
    "tests/fixtures/sample.csv",
    "docs/index.md",
    "docs/api.md",
    "scripts/deploy.sh",
    "node_modules/package/index.js",
    "data/output.csv",
    "data/cache/temp.dat",
]


@pytest.fixture(scope="module")
def project_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Create the sample project tree once for all test cases."""
    base = tmp_path_factory.mktemp("tc-project")
    for f in ALL_FILES:
        fp = base / f
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("content\n")
    return base


def _load_cases() -> list[dict]:
    with open(TEST_CASES_FILE) as f:
        return yaml.safe_load(f)


def _case_ids() -> list[str]:
    return [f"{tc['id']}: {tc['description']}" for tc in _load_cases()]


@pytest.mark.parametrize("tc", _load_cases(), ids=_case_ids())
def test_yaml_case(tc: dict, project_dir: pathlib.Path) -> None:
    flags = tc.get("flags", [])
    no_default_ignore = tc.get("no_default_ignore", False)
    verdicts = tc.get("verdicts", {})

    includes = []
    excludes = []
    for flag in flags:
        flag = flag.strip()
        if flag.startswith("-i "):
            includes.append(flag[3:].strip().strip("'\""))
        elif flag.startswith("-x "):
            excludes.append(flag[3:].strip().strip("'\""))

    gen, _stats, log_events = core.process_directory_recursive(
        base_dir_path=project_dir,
        include_patterns=includes,
        exclude_patterns=excludes,
        no_default_ignore=no_default_ignore,
        max_depth=None,
        follow_symlinks=False,
        max_size_kb=300,
        ignore_read_errors=False,
    )
    list(gen)  # consume generator

    actual_included: set[str] = set()
    for event in log_events:
        if event.get("item_type") == "folder":
            continue
        if event.get("status") == "included":
            actual_included.add(event.get("path", ""))

    mismatches = []
    for file_path, expected_raw in verdicts.items():
        expected = expected_raw.split("#")[0].strip().upper()
        actual = "INCLUDED" if file_path in actual_included else "EXCLUDED"
        if actual != expected:
            comment = expected_raw.split("#")[1].strip() if "#" in expected_raw else ""
            mismatches.append(f"  {file_path}: expected {expected}, got {actual}  # {comment}")

    assert not mismatches, f"{tc['id']} — {len(mismatches)} verdict(s) wrong:\n" + "\n".join(mismatches)
