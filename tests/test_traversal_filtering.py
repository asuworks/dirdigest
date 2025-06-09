import pytest
import pathlib
from typing import List, Tuple, Dict, Any, Optional

from dirdigest.constants import OperationalMode, PathState, DEFAULT_IGNORE_PATTERNS, LogEvent
from dirdigest.core import process_directory_recursive
from dirdigest.utils.patterns import _get_pattern_properties, _compare_specificity # For specific test validation if needed

# Helper to create file system structure
def create_test_fs(base_path: pathlib.Path, structure: Dict[str, Any]):
    """
    Creates a directory and file structure under base_path.
    structure: {"filename": "content", "dirname/": {"subfile": "content"}}
    """
    for name, content in structure.items():
        path = base_path / name
        if name.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
            if isinstance(content, dict):
                create_test_fs(path, content)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content))


# Helper to run core processing and collect results
def run_core_processing_test(
    base_dir: pathlib.Path,
    operational_mode: OperationalMode,
    include_patterns: List[str],
    user_exclude_patterns: List[str],
    effective_app_exclude_patterns: Optional[List[str]] = None,
    no_default_ignore: bool = False,
    max_depth: Optional[int] = None,
    follow_symlinks: bool = False,
    max_size_kb: int = 1024,
    ignore_read_errors: bool = True,
) -> Tuple[List[pathlib.Path], List[LogEvent]]:
    final_effective_app_excludes = user_exclude_patterns if effective_app_exclude_patterns is None else effective_app_exclude_patterns

    processed_items_generator, stats, log_events = process_directory_recursive(
        base_dir_path=base_dir,
        operational_mode=operational_mode,
        include_patterns=include_patterns,
        user_exclude_patterns=user_exclude_patterns,
        effective_app_exclude_patterns=final_effective_app_excludes,
        no_default_ignore=no_default_ignore,
        max_depth=max_depth,
        follow_symlinks=follow_symlinks,
        max_size_kb=max_size_kb,
        ignore_read_errors=ignore_read_errors,
    )

    included_files_payloads = list(processed_items_generator)
    included_files = [item[0] for item in included_files_payloads]
    return included_files, log_events

# Helper to find a specific log event
def find_log_event(log_events: List[LogEvent], path_str: str) -> Optional[LogEvent]:
    for event in log_events:
        if event.get("path") == path_str:
            return event
    return None

# --- Test Cases Start Here ---

# Mode: OperationalMode.MODE_INCLUDE_FIRST
@pytest.mark.parametrize("fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"a.txt": "content a", "b.txt": "content b"},
        ["a.txt"], [], False,
        ["a.txt"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name, "msi": "a.txt"},
            "b.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name, "reason": "No matching include pattern (MODE_INCLUDE_FIRST)"}
        },
        id="IF_BasicMSI"
    ),
    pytest.param(
        {"a.log": "a", "b.log": "b"},
        ["*.log"], ["a.log"], False,
        ["b.log"],
        {
            "a.log": {"state": PathState.USER_EXCLUDED_BY_SPECIFICITY.name, "msi": "*.log", "mse": "a.log"},
            "b.log": {"state": PathState.FINAL_INCLUDED.name, "msi": "*.log"}
        },
        id="IF_MSEBeatsMSI"
    ),
    pytest.param(
        {"src/": {"important.h": "content", "temp.h": "content"}},
        ["src/important.h"], ["src/*.h"], False,
        ["src/important.h"],
        {
            "src/important.h": {"state": PathState.FINAL_INCLUDED.name, "msi": "src/important.h", "mse": "src/*.h"},
            "src/temp.h": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name, "mse": "src/*.h"}
        },
        id="IF_MSIBeatsMSE"
    ),
    pytest.param(
        {"main/": {".config": "secret"}},
        ["main/"], [], False,
        [],
        {
            "main/.config": {"state": PathState.DEFAULT_EXCLUDED.name, "msi": "main/", "default_rule": ".*"}
        },
        id="IF_DefaultBeatsMSI_Hidden"
    ),
    pytest.param(
        {".config": "secret"},
        [".config"], [], False,
        [".config"],
        {
            ".config": {"state": PathState.FINAL_INCLUDED.name, "msi": ".config", "default_rule": ".*"}
        },
        id="IF_MSIBeatsDefault_Hidden"
    ),
    pytest.param(
        {"main/": {".config": "secret"}},
        ["main/"], [], True,
        ["main/.config"],
        {
            "main/.config": {"state": PathState.FINAL_INCLUDED.name, "msi": "main/"}
        },
        id="IF_NoDefault_HiddenIncludedByMSI"
    ),
    pytest.param(
        {"conflict.txt": "content"},
        ["conflict.txt"], ["conflict.txt"], False,
        [],
        {
            "conflict.txt": {"state": PathState.ERROR_CONFLICTING_PATTERNS.name, "msi":"conflict.txt", "mse":"conflict.txt"}
        },
        id="IF_ConflictMSI_MSE"
    )
])
def test_mode_include_first(tmp_path: pathlib.Path, fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=OperationalMode.MODE_INCLUDE_FIRST,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"
    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"

# --- MODE_EXCLUDE_FIRST Tests ---
@pytest.mark.parametrize("fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"temp/": {"a.out": ""}, "src/": {"b.cpp": ""}},
        [], ["temp/"], False,
        ["src/b.cpp"],
        {
            "temp/a.out": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "temp/"},
            "src/b.cpp": {"state": PathState.FINAL_INCLUDED.name}
        },
        id="EF_BasicMSE"
    ),
    pytest.param(
        {"logs/": {"trace.log": "trace", "archive/": {"old.log": "old"}}},
        ["logs/archive/old.log"], ["logs/"], False,
        ["logs/archive/old.log"],
        {
            "logs/trace.log": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "logs/"},
            "logs/archive/old.log": {"state": PathState.FINAL_INCLUDED.name, "msi": "logs/archive/old.log", "mse": "logs/"}
        },
        id="EF_MSIRescuesFromMSE"
    ),
    pytest.param(
        {"data/": {"config.json": "conf", "output.json": "out"}},
        ["data/config.json"], ["data/*.json"], False,
        ["data/config.json"],
        {
            "data/output.json": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "data/*.json"},
            "data/config.json": {"state": PathState.FINAL_INCLUDED.name, "msi": "data/config.json", "mse": "data/*.json"}
        },
        id="EF_MSIBeatsMSE_ButOtherFileCaughtByMSE"
    ),
    pytest.param(
        {".git/": {"config": ""}, "README.md": "readme"},
        [], [], False,
        ["README.md"],
        {
            ".git/config": {"state": PathState.DEFAULT_EXCLUDED.name, "default_rule": ".*"},
            "README.md": {"state": PathState.FINAL_INCLUDED.name}
        },
        id="EF_DefaultExcludesNoMSI"
    ),
    pytest.param(
        {".env": "secret", "app.py": "code"},
        [".env"], [], False,
        [".env", "app.py"],
        {
            ".env": {"state": PathState.FINAL_INCLUDED.name, "msi": ".env", "default_rule": ".*"},
            "app.py": {"state": PathState.FINAL_INCLUDED.name}
        },
        id="EF_MSIOverridesDefault"
    ),
    pytest.param(
        {"a.txt": "", "b.txt": "", "src/": {"c.py": ""}},
        ["src/c.py"], [], False,
        ["src/c.py"],
        {
            "src/c.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "src/c.py"},
            "a.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name},
            "b.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name}
        },
        id="EF_ImplicitlyExcludedNoMSIMatch"
    ),
    pytest.param(
        {"a.txt": "", "b.txt": "", "log/": {"c.log": ""}},
        [], ["log/"], False,
        ["a.txt", "b.txt"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name},
            "b.txt": {"state": PathState.FINAL_INCLUDED.name},
            "log/c.log": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "log/"}
        },
        id="EF_IncludedNoUserIncludes"
    ),
     pytest.param(
        {"conflict.txt": "content"},
        ["conflict.txt"], ["conflict.txt"], False,
        [],
        {
            "conflict.txt": {"state": PathState.ERROR_CONFLICTING_PATTERNS.name, "msi":"conflict.txt", "mse":"conflict.txt"}
        },
        id="EF_ConflictMSI_MSE"
    )
])
def test_mode_exclude_first(tmp_path: pathlib.Path, fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=OperationalMode.MODE_EXCLUDE_FIRST,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"

    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"

# --- MODE_ONLY_INCLUDE Tests ---
@pytest.mark.parametrize("fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"a.txt": "content a", "b.txt": "content b", ".hidden": "hidden content"},
        ["a.txt"], [], False,
        ["a.txt"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name, "msi": "a.txt"},
            "b.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name, "reason": "No matching include pattern (MODE_ONLY_INCLUDE)"},
            ".hidden": {"state": PathState.DEFAULT_EXCLUDED.name, "default_rule": ".*"}
        },
        id="OI_Basic_WithDefaultExcludes"
    ),
    pytest.param(
        {"a.txt": "content a", "b.txt": "content b", ".hidden": "hidden content"},
        ["a.txt", ".hidden"], [], True,
        ["a.txt", ".hidden"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name, "msi": "a.txt"},
            "b.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name, "reason": "No matching include pattern (MODE_ONLY_INCLUDE)"},
            ".hidden": {"state": PathState.FINAL_INCLUDED.name, "msi": ".hidden"}
        },
        id="OI_NoDefault_HiddenIncludedByMSI"
    ),
    pytest.param(
        {"a.log": "a", "b.log": "b"},
        ["*.log"], ["a.log"], False,
        ["b.log"],
        {
            "a.log": {"state": PathState.USER_EXCLUDED_BY_SPECIFICITY.name, "msi": "*.log", "mse": "a.log"},
            "b.log": {"state": PathState.FINAL_INCLUDED.name, "msi": "*.log"}
        },
        id="OI_MSIvsMSE_MSEWins"
    ),
])
def test_mode_only_include(tmp_path: pathlib.Path, fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=OperationalMode.MODE_ONLY_INCLUDE,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"
    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"


# --- MODE_ONLY_EXCLUDE Tests ---
@pytest.mark.parametrize("fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"a.txt": "content a", "b.tmp": "temp content", ".hidden": "hidden content"},
        [], ["*.tmp"], False,
        ["a.txt"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name},
            "b.tmp": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "*.tmp"},
            ".hidden": {"state": PathState.DEFAULT_EXCLUDED.name, "default_rule": ".*"}
        },
        id="OE_Basic_WithDefaultExcludes"
    ),
    pytest.param(
        {"a.txt": "content a", "b.tmp": "temp content", ".hidden": "hidden content"},
        [], ["*.tmp"], True,
        ["a.txt", ".hidden"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name},
            "b.tmp": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "*.tmp"},
            ".hidden": {"state": PathState.FINAL_INCLUDED.name}
        },
        id="OE_NoDefault_HiddenIncluded"
    ),
    pytest.param(
        {"a.tmp": "temp", "b.tmp": "temp2"},
        ["a.tmp"], ["*.tmp"], False,
        ["a.tmp"],
        {
            "a.tmp": {"state": PathState.FINAL_INCLUDED.name, "msi": "a.tmp", "mse": "*.tmp"},
            "b.tmp": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "*.tmp"}
        },
        id="OE_MSIRescuesFromMSE"
    ),
])
def test_mode_only_exclude(tmp_path: pathlib.Path, fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=OperationalMode.MODE_ONLY_EXCLUDE,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"
    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"


# --- MODE_INCLUDE_ALL_DEFAULT Tests ---
@pytest.mark.parametrize("fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"a.txt": "content", ".git/": {"HEAD": "ref: master"}},
        [], [], False,
        ["a.txt"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name},
            ".git/HEAD": {"state": PathState.DEFAULT_EXCLUDED.name, "default_rule": ".*"}
        },
        id="IAD_DefaultIgnoreActive"
    ),
    pytest.param(
        {"a.txt": "content", ".git/": {"HEAD": "ref: master"}},
        [], [], True,
        ["a.txt", ".git/HEAD"],
        {
            "a.txt": {"state": PathState.FINAL_INCLUDED.name},
            ".git/HEAD": {"state": PathState.FINAL_INCLUDED.name}
        },
        id="IAD_NoDefaultIgnore"
    ),
])
def test_mode_include_all_default(tmp_path: pathlib.Path, fs_structure, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=OperationalMode.MODE_INCLUDE_ALL_DEFAULT,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"
    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"

# --- TRAVERSE_BUT_EXCLUDE_SELF Tests ---
@pytest.mark.parametrize("fs_structure, operational_mode, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"data/": {"raw/": {"secret.txt": "s"}, "processed/": {"public.txt": "p"}, "README.md": "r"}},
        OperationalMode.MODE_INCLUDE_FIRST,
        ["data/processed/public.txt"], ["data/raw/", "data/README.md"], False,
        ["data/processed/public.txt"],
        {
            "data": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name},
            "data/raw": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "data/raw/"},
            "data/raw/secret.txt": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "data/raw/"},
            "data/README.md": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "data/README.md"},
            "data/processed/public.txt": {"state": PathState.FINAL_INCLUDED.name, "msi": "data/processed/public.txt"}
        },
        id="TBES_IF_DirExcludedChildrenIncluded"
    ),
    pytest.param(
        {"temp/": {"work/": {"important.dat": "d"}, "junk.txt": "j"}, "app.py":"a"},
        OperationalMode.MODE_INCLUDE_FIRST,
        ["temp/work/important.dat", "app.py"], ["temp/"], False,
        ["app.py", "temp/work/important.dat"],
        {
            "temp": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "mse": "temp/"},
            "temp/junk.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name},
            "temp/work/important.dat": {"state": PathState.FINAL_INCLUDED.name, "msi": "temp/work/important.dat", "mse": "temp/"},
            "app.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "app.py"}
        },
        id="TBES_IF_DirExplicitlyExcludedButChildIncluded"
    ),
    pytest.param(
        {"output/": {"logs/": {"debug.log": "d"}, "results.txt": "r"}, "src/":{"main.py":"m"}},
        OperationalMode.MODE_EXCLUDE_FIRST,
        ["src/", "output/results.txt"], ["output/logs/"], False,
        ["src/main.py", "output/results.txt"],
        {
            "output": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name},
            "output/logs": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "output/logs/"},
            "output/logs/debug.log": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "mse": "output/logs/"},
            "output/results.txt": {"state": PathState.FINAL_INCLUDED.name, "msi": "output/results.txt"},
            "src": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "msi": "src/"},
            "src/main.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "src/"}
        },
        id="TBES_EF_Mixed"
    ),
])
def test_traverse_but_exclude_self(tmp_path: pathlib.Path, fs_structure, operational_mode, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=operational_mode,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"

    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"


# --- Non-Pattern Exclusion Tests ---
def test_max_depth_exclusion(tmp_path: pathlib.Path):
    fs_structure = {"d1/": {"file1.txt":"f1", "d2/": {"file2.txt":"f2", "d3/": {"file3.txt": "f3"}}}}
    create_test_fs(tmp_path, fs_structure)

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], max_depth=0)
    assert not included
    d1_log = find_log_event(logs, "d1")
    assert d1_log is not None and d1_log["state"] == PathState.FINAL_EXCLUDED.name
    assert d1_log["reason"] == "Exceeds max depth for traversal"

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], max_depth=1)
    assert sorted(included) == sorted([pathlib.Path("d1/file1.txt")])
    d2_log = find_log_event(logs, "d1/d2")
    assert d2_log is not None and d2_log["state"] == PathState.FINAL_EXCLUDED.name
    assert d2_log["reason"] == "Exceeds max depth for traversal"
    assert find_log_event(logs, "d1/file1.txt")["state"] == PathState.FINAL_INCLUDED.name

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], max_depth=2)
    assert sorted(included) == sorted([pathlib.Path("d1/file1.txt"), pathlib.Path("d1/d2/file2.txt")])
    d3_log = find_log_event(logs, "d1/d2/d3")
    assert d3_log is not None and d3_log["state"] == PathState.FINAL_EXCLUDED.name
    assert d3_log["reason"] == "Exceeds max depth for traversal"

def test_max_size_exclusion(tmp_path: pathlib.Path):
    fs_structure = {"small.txt": "abc", "large.txt": "a" * 2048}
    create_test_fs(tmp_path, fs_structure)

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], max_size_kb=1)
    assert sorted(included) == [pathlib.Path("small.txt")]
    large_log = find_log_event(logs, "large.txt")
    assert large_log is not None and large_log["state"] == PathState.FINAL_EXCLUDED.name
    assert "Exceeds max size" in large_log["reason"]
    assert find_log_event(logs, "small.txt")["state"] == PathState.FINAL_INCLUDED.name

def test_symlink_exclusion_and_following(tmp_path: pathlib.Path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "file.txt").write_text("content")
    link_dir = tmp_path / "link_dir"
    if not link_dir.exists(): # Check to prevent error if test reruns in same tmp_path somehow
      link_dir.symlink_to(real_dir, target_is_directory=True)

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], follow_symlinks=False)
    assert sorted(included) == [pathlib.Path("real_dir/file.txt")]
    link_dir_log = find_log_event(logs, "link_dir")
    assert link_dir_log is not None and link_dir_log["state"] == PathState.FINAL_EXCLUDED.name
    assert link_dir_log["reason"] == "Is a symlink (symlink following disabled)"

    included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], follow_symlinks=True)
    expected_files = sorted([pathlib.Path("real_dir/file.txt"), pathlib.Path("link_dir/file.txt")])
    assert sorted(included) == expected_files
    link_dir_log_followed = find_log_event(logs, "link_dir")
    assert link_dir_log_followed is not None and link_dir_log_followed["state"] == PathState.TRAVERSE_BUT_EXCLUDE_SELF.name
    assert find_log_event(logs, "link_dir/file.txt")["state"] == PathState.FINAL_INCLUDED.name


def test_read_error_handling(tmp_path: pathlib.Path):
    fs_structure = {"readable.txt": "content", "unreadable.txt": ""}
    create_test_fs(tmp_path, fs_structure)
    unreadable_file_path = tmp_path / "unreadable.txt"

    original_mode_stat = unreadable_file_path.stat().st_mode
    unreadable_file_path.chmod(0o000)

    try:
        included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], ignore_read_errors=False)
        assert included == [pathlib.Path("readable.txt")]
        unreadable_log = find_log_event(logs, "unreadable.txt")
        assert unreadable_log is not None and unreadable_log["state"] == PathState.FINAL_EXCLUDED.name
        assert "Read error (and ignore_read_errors=False)" in unreadable_log["reason"]

        included, logs = run_core_processing_test(tmp_path, OperationalMode.MODE_INCLUDE_ALL_DEFAULT, [], [], ignore_read_errors=True)
        assert sorted(included) == sorted([pathlib.Path("readable.txt"), pathlib.Path("unreadable.txt")])
        unreadable_log_ignored = find_log_event(logs, "unreadable.txt")
        assert unreadable_log_ignored is not None and unreadable_log_ignored["state"] == PathState.FINAL_INCLUDED.name
        # Check that the payload would have the error, not directly in this log event's "reason" if successfully "included"
        # The "reason" for inclusion would be default. The payload has the read_error.
        assert "No user/default rules matched" in unreadable_log_ignored.get("reason", "") or not unreadable_log_ignored.get("reason")

    finally:
        unreadable_file_path.chmod(original_mode_stat)


# --- Empty/No Match Scenarios ---
@pytest.mark.parametrize("fs_structure, operational_mode, includes, user_excludes, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"a.txt": "content"}, OperationalMode.MODE_INCLUDE_FIRST, ["*.py"], [], [],
        {"a.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name, "reason": "No matching include pattern (MODE_INCLUDE_FIRST)"}},
        id="Empty_IF_NoMSIMatch"
    ),
    pytest.param(
        {"a.txt": "content"}, OperationalMode.MODE_EXCLUDE_FIRST, [], ["*.py"], ["a.txt"],
        {"a.txt": {"state": PathState.FINAL_INCLUDED.name}},
        id="Empty_EF_NoMSEMatch"
    ),
])
def test_empty_or_no_matches(tmp_path: pathlib.Path, fs_structure, operational_mode, includes, user_excludes, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=operational_mode,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=True
    )
    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Expected included files: {expected_paths_resolved}, Got: {sorted(included_files)}"

    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: {path_str}\n Events: {log_events}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for {path_str}: {key}={event.get(key)}, expected {val}"


if __name__ == "__main__":
    pytest.main(["-v", __file__])

# --- Tests for "**/dirname/" specific patterns ---

@pytest.mark.parametrize("fs_structure, operational_mode, includes, user_excludes, no_default, expected_included_paths, expected_log_checks", [
    pytest.param(
        {"project/": {"src/": {"app.py": "app"}, "utils/": {"tools.py": "tools", "helpers/": {"string_utils.py": "strings"}}, "another_dir/": {"other.txt": "o"}}},
        OperationalMode.MODE_ONLY_INCLUDE,
        ["**/utils/"], [], False,
        ["project/utils/tools.py", "project/utils/helpers/string_utils.py"],
        {
            "project/utils": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "msi": "**/utils/"},
            "project/utils/tools.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"},
            "project/utils/helpers/string_utils.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"},
            "project/src/app.py": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name},
            "project/another_dir/other.txt": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name}
        },
        id="STARSTAR_UTILS_ONLY_INCLUDE_Basic"
    ),
    pytest.param(
        {"project/": {"utils/": {"tools.py": "t", ".hidden_util.py": "h"}, ".git/": {"config": "c"}}},
        OperationalMode.MODE_ONLY_INCLUDE,
        ["**/utils/"], [], False, # Default ignores active
        ["project/utils/tools.py"],
        {
            "project/utils": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "msi": "**/utils/"},
            "project/utils/tools.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"},
            "project/utils/.hidden_util.py": {"state": PathState.DEFAULT_EXCLUDED.name, "msi": "**/utils/", "default_rule": ".*"},
            ".git/config": {"state": PathState.DEFAULT_EXCLUDED.name, "default_rule": ".*"}
        },
        id="STARSTAR_UTILS_ONLY_INCLUDE_WithDefaults"
    ),
    pytest.param(
        {"project/": {"utils/": {"tools.py": "t", ".hidden_util.py": "h"}, ".git/": {"config": "c"}}},
        OperationalMode.MODE_ONLY_INCLUDE,
        ["**/utils/"], [], True, # No Default ignores
        ["project/utils/tools.py", "project/utils/.hidden_util.py"],
        {
            "project/utils": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "msi": "**/utils/"},
            "project/utils/tools.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"},
            "project/utils/.hidden_util.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"}
        },
        id="STARSTAR_UTILS_ONLY_INCLUDE_NoDefaults"
    ),
    pytest.param(
        {"project/": {"src/": {"app.py": "a"}, "utils/": {"tools.py": "t", "helpers/": {"string_utils.py": "s"}}}},
        OperationalMode.MODE_INCLUDE_FIRST,
        ["**/utils/", "project/src/app.py"], ["**/helpers/"], False,
        ["project/utils/tools.py", "project/src/app.py"],
        {
            "project/utils": {"state": PathState.TRAVERSE_BUT_EXCLUDE_SELF.name, "msi": "**/utils/"},
            "project/utils/tools.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/utils/"},
            "project/utils/helpers": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "msi": "**/utils/", "mse": "**/helpers/"},
            "project/utils/helpers/string_utils.py": {"state": PathState.USER_EXCLUDED_DIRECTLY.name, "msi": "**/utils/", "mse": "**/helpers/"},
            "project/src/app.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "project/src/app.py"}
        },
        id="STARSTAR_UTILS_INCLUDE_FIRST_WithExcludes"
    ),
    pytest.param(
        {"root/": {"common_utils/": {"cutil.py": "c"}, "feature_utils/": {"futil.py": "f"}, "app/": {"main.py": "m"}}},
        OperationalMode.MODE_ONLY_INCLUDE,
        ["**/common_utils/", "**/feature_utils/"], [], False,
        ["root/common_utils/cutil.py", "root/feature_utils/futil.py"],
        {
            "root/common_utils/cutil.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/common_utils/"},
            "root/feature_utils/futil.py": {"state": PathState.FINAL_INCLUDED.name, "msi": "**/feature_utils/"},
            "root/app/main.py": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name}
        },
        id="STARSTAR_UTILS_ONLY_INCLUDE_MultipleStarStar"
    ),
    pytest.param(
        {"project/": {"src/": {"app.py": "a"}, "utils/": {"tools.py": "t"}}},
        OperationalMode.MODE_ONLY_INCLUDE,
        ["**/nonexistent_utils/"], [], False,
        [], # No files included
        {
            "project/src/app.py": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name},
            "project/utils/tools.py": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name},
            "project/utils": {"state": PathState.IMPLICITLY_EXCLUDED_FINAL_STEP.name} # Also the dir
        },
        id="STARSTAR_UTILS_ONLY_INCLUDE_NoMatchingDir"
    ),
])
def test_starstar_dirname_patterns(tmp_path: pathlib.Path, fs_structure, operational_mode, includes, user_excludes, no_default, expected_included_paths, expected_log_checks):
    create_test_fs(tmp_path, fs_structure)
    # For these specific tests, effective_app_exclude_patterns can mirror user_excludes,
    # as we are primarily testing the include/exclude logic based on user patterns and default flag.
    included_files, log_events = run_core_processing_test(
        base_dir=tmp_path,
        operational_mode=operational_mode,
        include_patterns=includes,
        user_exclude_patterns=user_excludes,
        effective_app_exclude_patterns=user_excludes,
        no_default_ignore=no_default
    )

    expected_paths_resolved = sorted([pathlib.Path(p) for p in expected_included_paths])
    assert sorted(included_files) == expected_paths_resolved, f"Included files mismatch. Expected: {expected_paths_resolved}, Got: {sorted(included_files)}"

    for path_str, checks in expected_log_checks.items():
        event = find_log_event(log_events, path_str)
        assert event is not None, f"No log event found for path: '{path_str}'.\nAvailable log paths: {[e.get('path') for e in log_events]}"
        for key, val in checks.items():
            assert event.get(key) == val, f"Log event check failed for '{path_str}': {key}='{event.get(key)}', expected '{val}'"
