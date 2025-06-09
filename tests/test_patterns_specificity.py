import pytest
from pathlib import Path
from typing import List, Tuple, Optional

from dirdigest.utils.patterns import (
    determine_most_specific_pattern,
    _parse_pattern,
    _compare_specificity,
    PatternProperties,
    _get_pattern_properties,
    matches_pattern # Ensure this is imported
)

# Helper to get PatternProperties from a string for testing _compare_specificity
def props(pattern_str: str, original_index: int = 0) -> PatternProperties:
    return _get_pattern_properties(pattern_str, Path("."), original_index) # type: ignore

@pytest.mark.parametrize(
    "path_str, p_a_str, p_b_str, expected_winner_str",
    [
        ("docs/api/v1/endpoint.md", "docs/api/", "docs/*.md", "docs/api/"),
        ("src/app/components/button.js", "src/app/", "**/components/*", "src/app/"),
        ("data/raw/logs/2023/errors.txt", "data/raw/logs/", "data/**/*.txt", "data/raw/logs/"),
        ("a/b/c.txt", "a/b/", "a/", "a/b/"),
        ("a/b/c.txt", "a/", "*.txt", "a/"),
        ("a/b.txt", "a/b.txt", "*.txt", "a/b.txt"),
        ("debug.log", "debug.log", "*.log", "debug.log"),
        ("src/config/settings.ini", "src/config/settings.ini", "src/config/*", "src/config/settings.ini"),
        ("docs/README.md", "docs/README.md", "docs/", "docs/README.md"),
        ("build/", "build/", "*", "build/"),
        ("build/", "build/", "**/build/", "build/"), # Expect explicit 'build/' to win
        ("archive.tar.gz", "*.tar.gz", "*.gz", "*.tar.gz"),
        ("my.file.log.txt", "*.log.txt", "*.txt", "*.log.txt"),
        ("my.file.log.txt", "*.file.log.txt", "*.log.txt", "*.file.log.txt"),
        ("my.file.log.txt", "*.txt", "*.log", "*.txt"),
        ("a/b/c/d/e.txt", "a/b/c/d/e.txt", "a/b/**/e.txt", "a/b/c/d/e.txt"),
        ("a/b/c/d/e.txt", "a/b/**/e.txt", "**/d/e.txt", "a/b/**/e.txt"),
        ("a/b/c/d/e.txt", "**/d/e.txt", "*.txt", "**/d/e.txt"), # Expect path glob to win
        ("foo/bar.txt", "foo/bar.txt", "foo/", "foo/bar.txt"),
        ("foo/", "foo/", "foo", "foo/"),
    ],
)
def test_compare_specificity_rules(path_str: str, p_a_str: str, p_b_str: str, expected_winner_str: str):
    path_obj = Path(path_str)
    # Determine if the original path string indicated a directory.
    # This should mirror the logic in determine_most_specific_pattern.
    # IMPORTANT: Use os.sep for platform compatibility if creating test files,
    # but for pattern matching itself, patterns are normalized to '/'.
    # Here, path_str comes from test parameters which use '/', so checking for '/' is fine.
    path_is_known_dir = path_str.endswith('/')

    pattern_a_props = props(p_a_str, 0)
    pattern_b_props = props(p_b_str, 1)
    ab_comparison = _compare_specificity(path_obj, pattern_a_props, pattern_b_props, path_is_known_dir)
    ba_comparison = _compare_specificity(path_obj, pattern_b_props, pattern_a_props, path_is_known_dir)

    if expected_winner_str == p_a_str:
        assert ab_comparison == 1, f"Expected '{p_a_str}' > '{p_b_str}' for '{path_str}' (path_is_known_dir={path_is_known_dir}), got {ab_comparison}"
        assert ba_comparison == -1, f"Symmetry check: Expected '{p_b_str}' < '{p_a_str}' for '{path_str}' (path_is_known_dir={path_is_known_dir}), got {ba_comparison}"
    elif expected_winner_str == p_b_str:
        assert ab_comparison == -1, f"Expected '{p_b_str}' > '{p_a_str}' for '{path_str}' (path_is_known_dir={path_is_known_dir}), got {ab_comparison}"
        assert ba_comparison == 1, f"Symmetry check: Expected '{p_a_str}' < '{p_b_str}' for '{path_str}' (path_is_known_dir={path_is_known_dir}), got {ba_comparison}"
    else:
        pytest.fail("Test setup error: expected_winner_str must be one of p_a_str or p_b_str")

@pytest.mark.parametrize(
    "path_str, patterns_with_indices, expected_pattern_info", # Changed expected_pattern_str to expected_pattern_info
    [
        ("docs/api/v1/endpoint.md", [("docs/api/", 0), ("docs/*.md", 1)], ("docs/api/",0) ),
        ("debug.log", [("*.log", 0), ("debug.log", 1)], ("debug.log",1)),
        ("archive.tar.gz", [("*.gz", 0), ("*.tar.gz", 1)], ("*.tar.gz",1)),
        ("file.txt", [("*.txt", 0), ("*.txt", 1)], ("*.txt", 1)),
        ("src/common.h", [("src/*.h", 0), ("**/common.h", 1)], ("src/*.h",0)),
        ("src/explicit.h", [("src/", 0), ("src/explicit.h", 1)], ("src/explicit.h",1)),
        ("other/file.py", [("*.txt", 0), ("docs/", 1)], None),
        ("image.jpg", [("*.jpg", 0), ("*.png", 1)], ("*.jpg",0)),
        (
            "a/b/c/d/e.txt",
            [("*.txt", 0), ("**/d/e.txt", 1), ("a/b/**/e.txt", 2), ("a/b/c/d/e.txt", 3)],
            ("a/b/c/d/e.txt",3)
        ),
        ("docs/dev/guide.md", [("docs/", 0), ("docs/dev/", 1)], ("docs/dev/",1)),
        ("docs/dev/guide.md", [("docs/**", 0), ("docs/dev/*", 1)], ("docs/dev/*",1)),
    ],
)
def test_determine_most_specific_pattern(
    path_str: str,
    patterns_with_indices: List[Tuple[str, int]],
    expected_pattern_info: Optional[Tuple[str, int]], # Expect tuple or None
):
    result_tuple = determine_most_specific_pattern(patterns_with_indices, path_str)
    assert result_tuple == expected_pattern_info

@pytest.mark.parametrize(
    "path_str, patterns_with_indices, expected_winner_tuple",
    [
        ("file.txt", [("*.txt", 0), ("*.txt", 1)], ("*.txt", 1)),
        # This case is tricky, data/logs/*.log is more specific due to more parts in suffix
        ("data/logs/app.log", [("data/logs/*", 0), ("data/logs/*.log", 1)], ("data/logs/*.log", 1)),
    ]
)
def test_index_tie_breaking(path_str: str, patterns_with_indices: List[Tuple[str, int]], expected_winner_tuple: Tuple[str, int]):
    winner = determine_most_specific_pattern(patterns_with_indices, path_str)
    assert winner is not None
    assert winner[0] == expected_winner_tuple[0]
    assert winner[1] == expected_winner_tuple[1]

@pytest.mark.parametrize("path_str, pattern_str, expected_match", [
    ("docs/file.txt", "docs/", True),
    ("docs/subdir/file.txt", "docs/", True),
    ("docs/", "docs/", True),
    ("other/docs/file.txt", "docs/", False),
    ("other/docs/file.txt", "**/docs/", True),
    ("file.txt", "docs/", False),
    ("docs", "docs/", True),
])
def test_matches_pattern_for_dirs(path_str, pattern_str, expected_match):
    assert matches_pattern(path_str, pattern_str) == expected_match

def test_get_pattern_properties_callable():
    props_obj = _get_pattern_properties("*.txt", Path("some_file.txt"), 0)
    assert props_obj is not None
    assert props_obj.raw_pattern == "*.txt"
    assert _get_pattern_properties(None, Path(".")) is None

@pytest.mark.parametrize("pattern_str, expected_depth, expected_is_explicit_file, expected_is_glob_file, expected_is_explicit_dir, expected_is_glob_dir, expected_suffix_parts", [
        ("file.txt", 1, True, False, False, False, ["txt"]),      # Corrected depth
        ("*.txt", 1, False, True, False, False, ["txt"]),         # Corrected depth
    ("data/", 1, False, False, True, False, None),
        ("data*/*/", 2, False, False, False, True, None),
        ("foo/bar.txt", 2, True, False, False, False, ["txt"]),   # Corrected depth
        ("foo/*.txt", 2, False, True, False, False, ["txt"]),     # Corrected depth
        ("**/a.log", 1, False, True, False, False, ["log"]),      # Corrected depth
        ("a/**/b.py", 2, False, True, False, False, ["py"]),
    ("a/b/", 2, False, False, True, False, None)
])
def test_parse_pattern_details(pattern_str, expected_depth, expected_is_explicit_file, expected_is_glob_file, expected_is_explicit_dir, expected_is_glob_dir, expected_suffix_parts):
    parsed_props = _get_pattern_properties(pattern_str, Path("dummy.txt"), 0) # type: ignore
    assert parsed_props is not None
    assert parsed_props.depth == expected_depth, f"Depth failed for {pattern_str}"
    assert parsed_props.is_explicit_file == expected_is_explicit_file, f"is_explicit_file failed for {pattern_str}"
    assert parsed_props.is_glob_file == expected_is_glob_file, f"is_glob_file failed for {pattern_str}"
    assert parsed_props.is_explicit_dir == expected_is_explicit_dir, f"is_explicit_dir failed for {pattern_str}"
    assert parsed_props.is_glob_dir == expected_is_glob_dir, f"is_glob_dir failed for {pattern_str}"
    assert parsed_props.suffix_parts == expected_suffix_parts, f"suffix_parts failed for {pattern_str}"

def test_double_star_dirname_depth():
    props1 = _get_pattern_properties("**/foo/", Path("."), 0) # type: ignore
    assert props1 is not None
    assert props1.depth == 1
    props2 = _get_pattern_properties("**/foo.txt", Path("."), 0) # type: ignore
    assert props2 is not None
    assert props2.depth == 1
    props3 = _get_pattern_properties("a/**/foo/", Path("."), 0) # type: ignore
    assert props3 is not None
    assert props3.depth == 2
    props4 = _get_pattern_properties("a/**/foo.txt", Path("."), 0) # type: ignore
    assert props4 is not None
    # path_part for "a/**/foo.txt" is "a/**/foo" -> segments ['a', 'foo'] -> depth 2
    assert props4.depth == 2, f"Path part was {os.path.dirname(props4.normalized_pattern)}"
