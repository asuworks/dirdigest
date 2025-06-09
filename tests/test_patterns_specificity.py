import pytest
from pathlib import Path
from typing import List, Tuple, Optional

from dirdigest.utils.patterns import (
    determine_most_specific_pattern,
    _parse_pattern,
    _compare_specificity,
    PatternProperties,
    _get_pattern_properties # For default rule property creation if needed by tests directly
)

# Helper to get PatternProperties from a string for testing _compare_specificity
def props(pattern_str: str, original_index: int = 0) -> PatternProperties:
    # The path_obj context for _get_pattern_properties is not strictly necessary for parsing itself
    # but let's provide a dummy one.
    return _get_pattern_properties(pattern_str, Path("."), original_index) # type: ignore

# Test cases for _compare_specificity directly
@pytest.mark.parametrize(
    "path_str, p_a_str, p_b_str, expected_winner_str",
    [
        # Depth Wins
        ("docs/api/v1/endpoint.md", "docs/api/", "docs/*.md", "docs/api/"),
        ("src/app/components/button.js", "src/app/", "**/components/*", "src/app/"),
        ("data/raw/logs/2023/errors.txt", "data/raw/logs/", "data/**/*.txt", "data/raw/logs/"),
        ("a/b/c.txt", "a/b/", "a/", "a/b/"),
        ("a/b/c.txt", "a/", "*.txt", "a/"), # 'a/' has depth 1, '*.txt' has depth 0 for matching path components
        ("a/b.txt", "a/b.txt", "*.txt", "a/b.txt"), # Explicit file vs glob, depth also favors explicit here if path part matches

        # Explicit Name Wins Over Glob (assuming depths are equal or file part is decisive)
        ("debug.log", "debug.log", "*.log", "debug.log"),
        ("src/config/settings.ini", "src/config/settings.ini", "src/config/*", "src/config/settings.ini"),
        ("docs/README.md", "docs/README.md", "docs/", "docs/README.md"), # Explicit file vs dir pattern for a file path
        # For a directory path "build/"
        # Note: _compare_specificity needs path_obj. For "build/", Path("build/").is_dir() won't work if it doesn't exist.
        # The logic in _compare_specificity uses str(path_obj).endswith('/') to infer dir type.
        ("build/", "build/", "*", "build/"), # Explicit dir vs glob for a dir path
        ("build/", "build/", "**/build/", "build/"), # Explicit dir vs globby dir for a dir path

        # Suffix Proximity
        ("archive.tar.gz", "*.tar.gz", "*.gz", "*.tar.gz"),
        ("my.file.log.txt", "*.log.txt", "*.txt", "*.log.txt"),
        ("my.file.log.txt", "*.file.log.txt", "*.log.txt", "*.file.log.txt"),
        ("my.file.log.txt", "*.txt", "*.log", "*.txt"), # direct suffix vs less direct

        # Mixed cases:
        # Path: a/b/c/d/e.txt
        # Patterns: a/b/c/d/e.txt (explicit), a/b/**/e.txt (deep glob), **/d/e.txt (shallower glob), *.txt (general glob)
        ("a/b/c/d/e.txt", "a/b/c/d/e.txt", "a/b/**/e.txt", "a/b/c/d/e.txt"), # Explicit vs deep glob
        ("a/b/c/d/e.txt", "a/b/**/e.txt", "**/d/e.txt", "a/b/**/e.txt"),     # Deeper path glob vs shallower
        ("a/b/c/d/e.txt", "**/d/e.txt", "*.txt", "**/d/e.txt"),              # Path glob vs general file glob

        # Test case where one pattern is a file pattern and the other is a dir pattern for a file path
        ("foo/bar.txt", "foo/bar.txt", "foo/", "foo/bar.txt"), # File pattern vs Dir pattern for a file
        # Test case where one pattern is a file pattern and the other is a dir pattern for a dir path
        # This requires careful thought on how matches_pattern works for "foo/" vs "foo/bar.txt"
        # If path is "foo/", "foo/bar.txt" should not match.
        # If path is "foo/", "foo/" (dir pattern) vs "foo" (file pattern, if such a thing makes sense without extension)
        ("foo/", "foo/", "foo", "foo/"), # Dir pattern vs File pattern for a dir
    ],
)
def test_compare_specificity_rules(path_str: str, p_a_str: str, p_b_str: str, expected_winner_str: str):
    path_obj = Path(path_str)
    pattern_a_props = props(p_a_str, 0)
    pattern_b_props = props(p_b_str, 1)

    # Determine which pattern is expected to win
    # If A wins, result is 1. If B wins, result is -1.
    # If expected_winner_str is p_a_str, then result of _compare_specificity(path_obj, A, B) should be 1.
    # If expected_winner_str is p_b_str, then result of _compare_specificity(path_obj, A, B) should be -1.

    # Test A vs B
    ab_comparison = _compare_specificity(path_obj, pattern_a_props, pattern_b_props)
    # Test B vs A (should be inverse)
    ba_comparison = _compare_specificity(path_obj, pattern_b_props, pattern_a_props)

    if expected_winner_str == p_a_str:
        assert ab_comparison == 1, f"Expected '{p_a_str}' to be more specific than '{p_b_str}' for path '{path_str}'"
        assert ba_comparison == -1, f"Expected '{p_a_str}' (as B) to be more specific than '{p_b_str}' (as A) for path '{path_str}' - inverse check"
    elif expected_winner_str == p_b_str:
        assert ab_comparison == -1, f"Expected '{p_b_str}' to be more specific than '{p_a_str}' for path '{path_str}'"
        assert ba_comparison == 1, f"Expected '{p_b_str}' (as A) to be more specific than '{p_a_str}' (as B) for path '{path_str}' - inverse check"
    else:
        pytest.fail(f"Test setup error: expected_winner_str '{expected_winner_str}' must be one of p_a_str or p_b_str")

# Test cases for determine_most_specific_pattern
@pytest.mark.parametrize(
    "path_str, patterns_with_indices, expected_pattern_str",
    [
        # Basic depth
        ("docs/api/v1/endpoint.md", [("docs/api/", 0), ("docs/*.md", 1)], "docs/api/"),
        # Explicit over glob
        ("debug.log", [("*.log", 0), ("debug.log", 1)], "debug.log"),
        # Suffix proximity
        ("archive.tar.gz", [("*.gz", 0), ("*.tar.gz", 1)], "*.tar.gz"),
        # Tie-breaking by original index (if rules result in a tie)
        # For "*.txt" vs "*.txt", they are identical, so index 1 should win.
        ("file.txt", [("*.txt", 0), ("*.txt", 1)], ("*.txt", 1)),
        # More complex tie-breaking scenario - ensure this is a true tie by rules first
        # Example: "src/common.h", patterns: [("src/*.h", 0), ("**/common.h", 1)]
        # "**/common.h" is more explicit on filename, "src/*.h" matches depth of "src" (1).
        # "**/common.h" has effective depth 0 for path segments if just a filename glob.
        # "src/*.h" should win by depth if "**/common.h" is depth 0.
        # If "**/common.h" is considered to have path depth (e.g. if path is "foo/common.h"),
        # then it depends on how that's calculated.
        # Let's assume `_calculate_matching_depth` for "**/common.h" is 0.
        # `_calculate_matching_depth` for "src/*.h" on "src/common.h" is 1. So "src/*.h" wins.
        ("src/common.h", [("src/*.h", 0), ("**/common.h", 1)], "src/*.h"),
        # If "**/common.h" was parsed to match "common.h" part explicitly, making it more specific
        # than the glob "*.h", that rule (explicit name) would take precedence over depth of path.
        # Current logic: depth of matching path components -> explicit name -> suffix proximity.
        # For "src/common.h":
        # P_A ("src/*.h"): depth 1 (matches "src"). is_glob_file.
        # P_B ("**/common.h"): depth 0. is_explicit_file (if "common.h" has no globs).
        # Rule 1: P_A wins due to depth.

        # Test where P_B is more explicit and should win even if P_A has depth
        # Path: "src/explicit.h"
        # P_A: "src/" (depth 1, is_explicit_dir)
        # P_B: "src/explicit.h" (depth 1 for "src", is_explicit_file)
        # _compare_specificity for ("src/explicit.h", "src/", "src/explicit.h")
        # depth_a (src/) = 1, depth_b (src/explicit.h) = 1. Tie on depth.
        # Rule 2 (explicit): path is file-like. P_B is explicit_file. P_A is explicit_dir.
        # Final tie-breaker: file pattern P_B wins over dir pattern P_A for a file path. So P_B wins.
        ("src/explicit.h", [("src/", 0), ("src/explicit.h", 1)], "src/explicit.h"),

        # No matching patterns
        ("other/file.py", [("*.txt", 0), ("docs/", 1)], None),
        # One matching pattern
        ("image.jpg", [("*.jpg", 0), ("*.png", 1)], "*.jpg"),
        # All patterns from example
        (
            "a/b/c/d/e.txt",
            [
                ("*.txt", 0), ("**/d/e.txt", 1),
                ("a/b/**/e.txt", 2), ("a/b/c/d/e.txt", 3)
            ],
            ("a/b/c/d/e.txt",3) # Expect the most explicit full match
        ),
         # Ensure dir patterns are handled correctly
        ("docs/dev/guide.md", [("docs/", 0), ("docs/dev/", 1)], "docs/dev/"),
        ("docs/dev/guide.md", [("docs/**", 0), ("docs/dev/*", 1)], "docs/dev/*"), # More specific glob
    ],
)
def test_determine_most_specific_pattern(
    path_str: str,
    patterns_with_indices: List[Tuple[str, int]],
    expected_pattern_str: Optional[str] | Tuple[str, int],
):
    result_tuple = determine_most_specific_pattern(patterns_with_indices, path_str)

    if expected_pattern_str is None:
        assert result_tuple is None
    elif isinstance(expected_pattern_str, tuple):
        assert result_tuple is not None
        assert result_tuple[0] == expected_pattern_str[0]
        assert result_tuple[1] == expected_pattern_str[1]
    else: # Just string
        assert result_tuple is not None
        assert result_tuple[0] == expected_pattern_str
        # We don't assert original_index if only string is given, means any index is fine if pattern matches
        # However, for robust testing, better to expect (pattern, index) tuple.
        # For simplicity now, if it's a string, we just check pattern part.
        # This might need adjustment if multiple patterns could result from different indices.

# TODO: Add tests for _parse_pattern if its internal logic becomes more complex or has more edge cases.
# For now, its behavior is implicitly tested via _compare_specificity and determine_most_specific_pattern.

# Test cases for specific interactions or edge cases in _calculate_matching_depth
# (This is implicitly tested by depth tests above, but direct tests can be useful)

# Test cases that might lead to _compare_specificity returning 0 (equal primary rules)
# then rely on original_index from determine_most_specific_pattern
@pytest.mark.parametrize(
    "path_str, patterns_with_indices, expected_winner_tuple",
    [
        # Identical patterns, higher index should win
        ("file.txt", [("*.txt", 0), ("*.txt", 1)], ("*.txt", 1)),
        ("data/logs/app.log", [("data/logs/*", 0), ("data/logs/*.log", 1)], ("data/logs/*.log", 1)), # Suffix rule makes them not equal.
        # Need a case where primary rules (depth, explicit, suffix) are truly equal.
        # Example: Two globs with same depth, same suffix match length.
        # This is hard to construct without identical patterns.
        # If 'a*b.txt' and 'ab*.txt' for path 'axb.txt'.
        # Both depth 0, both glob_file, suffix 'txt' matches same.
        # Let's assume for now identical patterns are the main source of index tie-breaking.
    ]
)
def test_index_tie_breaking(path_str: str, patterns_with_indices: List[Tuple[str, int]], expected_winner_tuple: Tuple[str, int]):
    winner = determine_most_specific_pattern(patterns_with_indices, path_str)
    assert winner is not None
    assert winner[0] == expected_winner_tuple[0]
    assert winner[1] == expected_winner_tuple[1]

# Test that `matches_pattern` (the one from utils.patterns used by determine_most_specific_pattern) works as expected for dirs
@pytest.mark.parametrize("path_str, pattern_str, expected_match", [
    ("docs/file.txt", "docs/", True),
    ("docs/subdir/file.txt", "docs/", True),
    ("docs/", "docs/", True), # Matching the directory itself
    ("other/docs/file.txt", "docs/", False), # "docs/" is anchored unless it's like "**/docs/"
    ("other/docs/file.txt", "**/docs/", True),
    ("file.txt", "docs/", False),
    ("docs", "docs/", True), # Path("docs") vs pattern "docs/"
])
def test_matches_pattern_for_dirs(path_str, pattern_str, expected_match):
    assert matches_pattern(path_str, pattern_str) == expected_match

# Test for _get_pattern_properties to ensure it's callable
def test_get_pattern_properties_callable():
    # Just a basic check that it can be called and returns something or None
    props_obj = _get_pattern_properties("*.txt", Path("some_file.txt"), 0)
    assert props_obj is not None
    assert props_obj.raw_pattern == "*.txt"
    assert _get_pattern_properties(None, Path(".")) is None

# Test specific parsing results from _parse_pattern (via the _get_pattern_properties helper)
@pytest.mark.parametrize("pattern_str, expected_depth, expected_is_explicit_file, expected_is_glob_file, expected_is_explicit_dir, expected_is_glob_dir, expected_suffix_parts", [
    ("file.txt", 0, True, False, False, False, ["txt"]),
    ("*.txt", 0, False, True, False, False, ["txt"]),
    ("data/", 1, False, False, True, False, None), # "data/" -> depth 1 ("data")
    ("data*/*/", 1, False, False, False, True, None), # "data*/*/" -> depth 1 ("data*") for path part, then glob dir name
    ("foo/bar.txt", 1, True, False, False, False, ["txt"]),
    ("foo/*.txt", 1, False, True, False, False, ["txt"]),
    ("**/a.log", 0, False, True, False, False, ["log"]), # "**/a.log" -> depth 0. `is_explicit_file` is False due to `**`, `is_glob_file` is True.
    ("a/**/b.py", 2, False, True, False, False, ["py"]), # a, b -> depth 2. `is_explicit_file` is False due to `**`.
    ("a/b/", 2, False, False, True, False, None) # a, b -> depth 2
])
def test_parse_pattern_details(pattern_str, expected_depth, expected_is_explicit_file, expected_is_glob_file, expected_is_explicit_dir, expected_is_glob_dir, expected_suffix_parts):
    # Use a dummy path, it's not strictly used by _parse_pattern for these properties
    parsed_props = _get_pattern_properties(pattern_str, Path("dummy.txt"), 0)
    assert parsed_props is not None
    assert parsed_props.depth == expected_depth, f"Depth failed for {pattern_str}"
    assert parsed_props.is_explicit_file == expected_is_explicit_file, f"is_explicit_file failed for {pattern_str}"
    assert parsed_props.is_glob_file == expected_is_glob_file, f"is_glob_file failed for {pattern_str}"
    assert parsed_props.is_explicit_dir == expected_is_explicit_dir, f"is_explicit_dir failed for {pattern_str}"
    assert parsed_props.is_glob_dir == expected_is_glob_dir, f"is_glob_dir failed for {pattern_str}"
    assert parsed_props.suffix_parts == expected_suffix_parts, f"suffix_parts failed for {pattern_str}"

# Test pattern `**/foo` which caused issues in depth calculation for PatternProperties
def test_double_star_dirname_depth():
    # `os.path.dirname("**/foo")` is `**/` on POSIX, `**` on Windows.
    # `split('/')` on `**/` gives `['**', '']`. `seg and seg != '**'` filters to `['']` - wait, `''` is false.
    # So `[seg for seg in "**/".split('/') if seg and seg != '**']` is `[]`. Depth 0.
    # This is for pattern "**/foo/" (dir).
    # If pattern is "**/foo" (file), os.path.dirname is also "**/". Depth 0.
    # This seems correct as per my definition: "number of non-'**' segments before the filename part" or in the dir path.
    # "**/foo/" -> norm="**/foo/", path_part="**/foo", segments ["**","foo"], non-** = ["foo"], depth = 1.
    # "**/foo" -> norm="**/foo", path_part="**/", segments ["**"], non-** = [], depth = 0.

    props1 = _get_pattern_properties("**/foo/", Path("."), 0) # type: ignore
    assert props1 is not None
    assert props1.depth == 1 # for "foo"

    props2 = _get_pattern_properties("**/foo.txt", Path("."), 0) # type: ignore
    assert props2 is not None
    assert props2.depth == 0 # No explicit dir path part other than **

    props3 = _get_pattern_properties("a/**/foo/", Path("."), 0) # type: ignore
    assert props3 is not None
    assert props3.depth == 2 # for "a", "foo"

    props4 = _get_pattern_properties("a/**/foo.txt", Path("."), 0) # type: ignore
    assert props4 is not None
    assert props4.depth == 1 # for "a"
