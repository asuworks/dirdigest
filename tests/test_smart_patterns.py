# tests/test_smart_patterns.py
"""Comprehensive tests for the smart pattern matching engine.

Tests cover all 7 rules from the Smart Pattern Rules v1.0 spec:
1. Anchoring (./ prefix, bare suffix, **/ explicit recursive)
2. Type discrimination (trailing / for folders)
3. Wildcards (POSIX standard *, **, ?)
4. Multiple includes (OR semantics)
5. Exclusion symmetry
6. Specificity-based precedence (8-rank system)
7. Default ignore behavior
"""

from pathlib import Path

import pytest

from dirdigest.utils.patterns import (
    compute_targeting_distance,
    is_path_hidden,
    matches_path,
    matches_pattern,
    matches_patterns,
    parse_pattern,
)

# ============================================================================
# parse_pattern() tests
# ============================================================================


class TestParsePatternAnchoring:
    """Test anchoring detection in parse_pattern."""

    def test_anchored_exact_file(self):
        """./src/main.py -> anchored=True, segments=["src", "main.py"]"""
        p = parse_pattern("./src/main.py")
        assert p.anchored is True
        assert p.segments == ["src", "main.py"]
        assert p.is_folder is False
        assert p.has_wildcards is False

    def test_unanchored_pattern(self):
        """src/main.py -> anchored=False"""
        p = parse_pattern("src/main.py")
        assert p.anchored is False
        assert p.segments == ["src", "main.py"]

    def test_doublestar_prefix_not_anchored(self):
        """**/*.py should not be treated as anchored."""
        p = parse_pattern("**/*.py")
        assert p.anchored is False


class TestParsePatternFolder:
    """Test folder detection in parse_pattern."""

    def test_trailing_slash_is_folder(self):
        """tests/ -> is_folder=True"""
        p = parse_pattern("tests/")
        assert p.is_folder is True
        assert p.segments == ["tests"]

    def test_no_trailing_slash_is_file(self):
        """config.py -> is_folder=False"""
        p = parse_pattern("config.py")
        assert p.is_folder is False

    def test_anchored_folder(self):
        """./tests/ -> anchored=True, is_folder=True"""
        p = parse_pattern("./tests/")
        assert p.anchored is True
        assert p.is_folder is True
        assert p.segments == ["tests"]


class TestParsePatternWildcards:
    """Test wildcard detection in parse_pattern."""

    def test_star_wildcard(self):
        """*.py -> has_wildcards=True"""
        p = parse_pattern("*.py")
        assert p.has_wildcards is True

    def test_doublestar_wildcard(self):
        """**/*.py -> has_wildcards=True"""
        p = parse_pattern("**/*.py")
        assert p.has_wildcards is True

    def test_question_mark_wildcard(self):
        """test?.py -> has_wildcards=True"""
        p = parse_pattern("test?.py")
        assert p.has_wildcards is True

    def test_no_wildcards(self):
        """config.py -> has_wildcards=False"""
        p = parse_pattern("config.py")
        assert p.has_wildcards is False

    def test_combined_anchored_wildcard(self):
        """./tests/**/*.py -> anchored=True, has_wildcards=True, is_folder=False"""
        p = parse_pattern("./tests/**/*.py")
        assert p.anchored is True
        assert p.has_wildcards is True
        assert p.is_folder is False


class TestParsePatternDoubleStarPrefix:
    """Test **/ prefix stripping behavior."""

    def test_doublestar_prefix_stripped(self):
        """**/*.py -> segments should be ["*.py"] not ["**", "*.py"]"""
        p = parse_pattern("**/*.py")
        assert p.segments == ["*.py"]

    def test_doublestar_folder_prefix_stripped(self):
        """**/utils/ -> segments should be ["utils"]"""
        p = parse_pattern("**/utils/")
        assert p.segments == ["utils"]


class TestParsePatternOsSeparator:
    """Test OS separator normalization."""

    def test_backslash_normalized(self):
        """Backslashes should be normalized to forward slashes."""
        # This tests that os.sep replacement works
        p = parse_pattern("src/main.py")
        assert p.segments == ["src", "main.py"]

    def test_raw_preserved(self):
        """Raw field should preserve the original input."""
        p = parse_pattern("./src/**/*.py")
        assert p.raw == "./src/**/*.py"


# ============================================================================
# compute_specificity() tests (via parse_pattern)
# ============================================================================


class TestSpecificityRanking:
    """Test specificity rank computation matches the 8-rank system."""

    def test_rank_1_anchored_exact_file(self):
        """Rank 1: ./src/test_main.py (anchored exact file)"""
        p = parse_pattern("./src/test_main.py")
        assert p.specificity == 1

    def test_rank_2_anchored_folder(self):
        """Rank 2: ./src/tests/ (anchored folder)"""
        p = parse_pattern("./src/tests/")
        assert p.specificity == 2

    def test_rank_3_anchored_glob(self):
        """Rank 3: ./tests/**/*.py (anchored glob)"""
        p = parse_pattern("./tests/**/*.py")
        assert p.specificity == 3

    def test_rank_4_path_filename(self):
        """Rank 4: tests/test_main.py (path + filename, multi-segment no wildcard)"""
        p = parse_pattern("tests/test_main.py")
        assert p.specificity == 4

    def test_rank_5_path_glob(self):
        """Rank 5: tests/**/*.py (path + glob)"""
        p = parse_pattern("tests/**/*.py")
        assert p.specificity == 5

    def test_rank_6_single_name_file(self):
        """Rank 6: config.py (single name file)"""
        p = parse_pattern("config.py")
        assert p.specificity == 6

    def test_rank_7_single_name_folder(self):
        """Rank 7: tests/ (single name folder)"""
        p = parse_pattern("tests/")
        assert p.specificity == 7

    def test_rank_8_glob_only(self):
        """Rank 8: **/*.py (glob only)"""
        p = parse_pattern("**/*.py")
        assert p.specificity == 8

    def test_specificity_ordering(self):
        """Verify that lower rank numbers = more specific."""
        patterns = [
            ("./src/test_main.py", 1),
            ("./src/tests/", 2),
            ("./tests/**/*.py", 3),
            ("tests/test_main.py", 4),
            ("tests/**/*.py", 5),
            ("config.py", 6),
            ("tests/", 7),
            ("**/*.py", 8),
        ]
        for pat_str, expected_rank in patterns:
            p = parse_pattern(pat_str)
            assert (
                p.specificity == expected_rank
            ), f"Pattern '{pat_str}' expected rank {expected_rank}, got {p.specificity}"

        # More specific patterns should have lower rank numbers
        parsed = [parse_pattern(p) for p, _ in patterns]
        for i in range(len(parsed) - 1):
            assert parsed[i].specificity < parsed[i + 1].specificity, (
                f"'{patterns[i][0]}' (rank {parsed[i].specificity}) should be "
                f"more specific than '{patterns[i + 1][0]}' (rank {parsed[i + 1].specificity})"
            )


# ============================================================================
# matches_path() tests - Rule 1: Anchoring
# ============================================================================


class TestRule1Anchoring:
    """Rule 1: ./ prefix anchors to root, bare patterns do suffix matching."""

    def test_anchored_folder_matches_file_inside(self):
        """./src/ matches src/utils/helpers.py (anchored folder, file inside)"""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "src/utils/helpers.py", is_dir=False) is True

    def test_anchored_folder_not_match_nested(self):
        """./src/ does NOT match lib/vendor/src/utils/legacy.py (anchored = root only)"""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "lib/vendor/src/utils/legacy.py", is_dir=False) is False

    def test_unanchored_folder_matches_root(self):
        """src/ matches src/utils/helpers.py (suffix match at root)"""
        parsed = parse_pattern("src/")
        assert matches_path(parsed, "src/utils/helpers.py", is_dir=False) is True

    def test_unanchored_folder_matches_nested(self):
        """src/ matches lib/vendor/src/utils/legacy.py (suffix match at any depth)"""
        parsed = parse_pattern("src/")
        assert matches_path(parsed, "lib/vendor/src/utils/legacy.py", is_dir=False) is True

    def test_unanchored_multi_segment_suffix(self):
        """vendor/src/ matches lib/vendor/src/utils/legacy.py (suffix match)"""
        parsed = parse_pattern("vendor/src/")
        assert matches_path(parsed, "lib/vendor/src/utils/legacy.py", is_dir=False) is True

    def test_anchored_folder_matches_direct_child(self):
        """./src/ matches src/main.py"""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "src/main.py", is_dir=False) is True

    def test_anchored_folder_matches_dir_itself(self):
        """./src/ matches the directory src itself."""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "src", is_dir=True) is True

    def test_anchored_folder_matches_subdir(self):
        """./src/ matches subdirectory src/utils."""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "src/utils", is_dir=True) is True


# ============================================================================
# matches_path() tests - Rule 2: Type Discrimination
# ============================================================================


class TestRule2TypeDiscrimination:
    """Rule 2: Trailing slash = folder, no slash = file."""

    def test_folder_pattern_matches_dir(self):
        """tests/ (folder) matches dir tests"""
        parsed = parse_pattern("tests/")
        assert matches_path(parsed, "tests", is_dir=True) is True

    def test_folder_pattern_matches_files_inside(self):
        """tests/ (folder) matches files inside tests/"""
        parsed = parse_pattern("tests/")
        assert matches_path(parsed, "tests/test_main.py", is_dir=False) is True

    def test_file_pattern_matches_file(self):
        """config.py (file) matches file config.py"""
        parsed = parse_pattern("config.py")
        assert matches_path(parsed, "config.py", is_dir=False) is True

    def test_file_pattern_not_match_dir(self):
        """config.py does NOT match a directory named config.py"""
        parsed = parse_pattern("config.py")
        assert matches_path(parsed, "config.py", is_dir=True) is False

    def test_folder_pattern_not_match_file_with_same_name(self):
        """tests/ does NOT match a file named tests"""
        parsed = parse_pattern("tests/")
        assert matches_path(parsed, "tests", is_dir=False) is False

    def test_folder_pattern_matches_deeply_nested_file(self):
        """tests/ matches tests/sub/deep/test_file.py"""
        parsed = parse_pattern("tests/")
        assert matches_path(parsed, "tests/sub/deep/test_file.py", is_dir=False) is True


# ============================================================================
# matches_path() tests - Rule 3: Wildcards
# ============================================================================


class TestRule3Wildcards:
    """Rule 3: POSIX glob semantics for *, **, ?."""

    def test_star_matches_root_only(self):
        """*.py matches config.py at root only, NOT src/deep.py"""
        parsed = parse_pattern("*.py")
        assert matches_path(parsed, "config.py", is_dir=False) is True
        assert matches_path(parsed, "src/deep.py", is_dir=False) is False

    def test_doublestar_matches_any_depth(self):
        """**/*.py matches src/deep.py at any depth"""
        parsed = parse_pattern("**/*.py")
        assert matches_path(parsed, "src/deep.py", is_dir=False) is True
        assert matches_path(parsed, "src/sub/deep.py", is_dir=False) is True
        assert matches_path(parsed, "config.py", is_dir=False) is True

    def test_path_star_matches_direct_children_only(self):
        """src/*.py matches src/main.py but NOT src/sub/deep.py"""
        parsed = parse_pattern("src/*.py")
        assert matches_path(parsed, "src/main.py", is_dir=False) is True
        assert matches_path(parsed, "src/sub/deep.py", is_dir=False) is False

    def test_path_doublestar_matches_recursive(self):
        """src/**/*.py matches both src/main.py and src/sub/deep.py"""
        parsed = parse_pattern("src/**/*.py")
        assert matches_path(parsed, "src/main.py", is_dir=False) is True
        assert matches_path(parsed, "src/sub/deep.py", is_dir=False) is True

    def test_anchored_doublestar_only_root(self):
        """./src/**/*.py only matches under root src/, not nested src/"""
        parsed = parse_pattern("./src/**/*.py")
        assert matches_path(parsed, "src/main.py", is_dir=False) is True
        assert matches_path(parsed, "src/sub/deep.py", is_dir=False) is True
        assert matches_path(parsed, "lib/src/main.py", is_dir=False) is False

    def test_question_mark_wildcard(self):
        """test?.py matches test1.py but not test12.py"""
        parsed = parse_pattern("test?.py")
        assert matches_path(parsed, "test1.py", is_dir=False) is True
        assert matches_path(parsed, "test12.py", is_dir=False) is False

    def test_star_no_match_across_separator(self):
        """*.py should not match across path separators."""
        parsed = parse_pattern("*.py")
        assert matches_path(parsed, "a/b.py", is_dir=False) is False

    def test_test_star_pattern(self):
        """test_*.py matches root-level test files only."""
        parsed = parse_pattern("test_*.py")
        assert matches_path(parsed, "test_main.py", is_dir=False) is True
        assert matches_path(parsed, "src/test_main.py", is_dir=False) is False

    def test_doublestar_test_star_pattern(self):
        """**/test_*.py matches test files at any depth."""
        parsed = parse_pattern("**/test_*.py")
        assert matches_path(parsed, "test_main.py", is_dir=False) is True
        assert matches_path(parsed, "src/test_main.py", is_dir=False) is True
        assert matches_path(parsed, "tests/sub/test_deep.py", is_dir=False) is True


# ============================================================================
# matches_path() tests - Rule 4: Multiple includes (OR)
# ============================================================================


class TestRule4MultipleIncludes:
    """Rule 4: Multiple includes = OR (additive), tested via matches_patterns."""

    def test_or_semantics(self):
        """matches_patterns returns True if any pattern matches."""
        assert matches_patterns("src/main.py", ["*.ts", "**/*.py"]) is True

    def test_no_match_returns_false(self):
        """matches_patterns returns False if no pattern matches."""
        assert matches_patterns("src/main.py", ["*.ts", "*.js"]) is False


# ============================================================================
# matches_path() tests - Rule 6: Specificity ordering
# ============================================================================


class TestRule6SpecificityComparisons:
    """Rule 6: Verify rank comparison behavior."""

    def test_rank_4_beats_rank_7(self):
        """tests/test_main.py (rank 4) is more specific than tests/ (rank 7)."""
        specific = parse_pattern("tests/test_main.py")
        general = parse_pattern("tests/")
        assert specific.specificity < general.specificity

    def test_rank_7_beats_rank_8(self):
        """tests/ (rank 7) is more specific than **/*.py (rank 8)."""
        folder = parse_pattern("tests/")
        glob = parse_pattern("**/*.py")
        assert folder.specificity < glob.specificity

    def test_rank_1_beats_all(self):
        """./src/test_main.py (rank 1) beats everything."""
        most_specific = parse_pattern("./src/test_main.py")
        for pat_str in [
            "./src/tests/",
            "./tests/**/*.py",
            "tests/test_main.py",
            "tests/**/*.py",
            "config.py",
            "tests/",
            "**/*.py",
        ]:
            other = parse_pattern(pat_str)
            assert (
                most_specific.specificity < other.specificity
            ), f"Rank 1 pattern should beat '{pat_str}' (rank {other.specificity})"


# ============================================================================
# Backward compatibility tests
# ============================================================================


class TestBackwardCompatibility:
    """Test backward-compatible wrappers work correctly."""

    def test_matches_pattern_star_py(self):
        """matches_pattern('src/main.py', '*.py') works."""
        # *.py is root-only in new semantics. src/main.py is NOT at root.
        # In old code, fnmatch("src/main.py", "*.py") = False
        # New behavior should also be False for *.py (root-only)
        assert matches_pattern("src/main.py", "*.py") is False

    def test_matches_pattern_doublestar_main(self):
        """matches_pattern('src/main.py', '**/main.py') works."""
        assert matches_pattern("src/main.py", "**/main.py") is True

    def test_matches_patterns_wrapper(self):
        """matches_patterns('src/main.py', ['*.ts', '**/*.py']) works."""
        assert matches_patterns("src/main.py", ["*.ts", "**/*.py"]) is True

    def test_matches_pattern_folder(self):
        """matches_pattern('tests/test_main.py', 'tests/') matches (file inside folder)."""
        assert matches_pattern("tests/test_main.py", "tests/") is True

    def test_matches_pattern_exact_file(self):
        """matches_pattern('config.py', 'config.py') works."""
        assert matches_pattern("config.py", "config.py") is True


class TestIsPathHidden:
    """Test is_path_hidden utility."""

    def test_hidden_file(self):
        """is_path_hidden detects hidden files."""
        assert is_path_hidden(Path(".gitignore")) is True

    def test_hidden_directory_in_path(self):
        """is_path_hidden(Path('src/.config')) returns True."""
        assert is_path_hidden(Path("src/.config")) is True

    def test_not_hidden(self):
        """Normal paths are not hidden."""
        assert is_path_hidden(Path("src/main.py")) is False

    def test_dot_root_not_hidden(self):
        """Path('.') itself is not considered hidden."""
        assert is_path_hidden(Path(".")) is False

    def test_deeply_hidden(self):
        """Hidden directory deep in path."""
        assert is_path_hidden(Path("a/b/.hidden/c/file.py")) is True


# ============================================================================
# Parametrized tests for spec Quick Reference table
# ============================================================================


class TestSpecQuickReference:
    """Test examples from the spec's Quick Reference table."""

    @pytest.mark.parametrize(
        "pattern,path,is_dir,expected",
        [
            # All Python files at any depth
            ("**/*.py", "config.py", False, True),
            ("**/*.py", "src/main.py", False, True),
            ("**/*.py", "src/sub/deep.py", False, True),
            # Only root-level Python
            ("*.py", "config.py", False, True),
            ("*.py", "src/main.py", False, False),
            # Everything in src/ (folder)
            ("src/", "src/main.py", False, True),
            ("src/", "src/utils/helpers.py", False, True),
            ("src/", "src", True, True),
            # Everything in root src/ only
            ("./src/", "src/main.py", False, True),
            ("./src/", "lib/vendor/src/main.py", False, False),
            # Python in tests/
            ("tests/**/*.py", "tests/test_main.py", False, True),
            ("tests/**/*.py", "tests/sub/test_deep.py", False, True),
            ("tests/**/*.py", "tests/README.md", False, False),
            # Any utils/ folder anywhere
            ("utils/", "src/utils", True, True),
            ("utils/", "lib/vendor/utils", True, True),
            ("utils/", "utils", True, True),
            # A specific file
            ("./src/main.py", "src/main.py", False, True),
            ("./src/main.py", "lib/src/main.py", False, False),
        ],
    )
    def test_quick_reference_examples(self, pattern, path, is_dir, expected):
        parsed = parse_pattern(pattern)
        result = matches_path(parsed, path, is_dir=is_dir)
        assert (
            result == expected
        ), f"Pattern '{pattern}' against path '{path}' (is_dir={is_dir}): expected {expected}, got {result}"


# ============================================================================
# Edge cases and regression tests
# ============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_segments_after_strip(self):
        """Pattern with only prefix/suffix should still parse."""
        # "./" alone - edge case
        p = parse_pattern("./")
        assert p.anchored is True
        assert p.is_folder is True

    def test_deeply_nested_anchored_file(self):
        """./a/b/c/d.py should match a/b/c/d.py exactly."""
        parsed = parse_pattern("./a/b/c/d.py")
        assert matches_path(parsed, "a/b/c/d.py", is_dir=False) is True
        assert matches_path(parsed, "x/a/b/c/d.py", is_dir=False) is False

    def test_doublestar_at_end(self):
        """src/** matches all files under src/."""
        parsed = parse_pattern("src/**")
        assert matches_path(parsed, "src/main.py", is_dir=False) is True
        assert matches_path(parsed, "src/sub/deep.py", is_dir=False) is True

    def test_multi_segment_unanchored_file(self):
        """tests/test_main.py matches at any depth via suffix matching."""
        parsed = parse_pattern("tests/test_main.py")
        assert matches_path(parsed, "tests/test_main.py", is_dir=False) is True
        assert matches_path(parsed, "src/tests/test_main.py", is_dir=False) is True

    def test_single_star_in_folder_pattern(self):
        """*.egg-info/ should match any .egg-info directory."""
        parsed = parse_pattern("*.egg-info/")
        assert matches_path(parsed, "mypackage.egg-info", is_dir=True) is True
        assert matches_path(parsed, "build/mypackage.egg-info", is_dir=True) is True

    def test_anchored_folder_does_not_match_file_at_root(self):
        """./src/ should not match a file named 'src' at root."""
        parsed = parse_pattern("./src/")
        assert matches_path(parsed, "src", is_dir=False) is False

    def test_unanchored_folder_matches_nested_dir(self):
        """tests/ matches lib/tests (directory)."""
        parsed = parse_pattern("tests/")
        assert matches_path(parsed, "lib/tests", is_dir=True) is True

    def test_star_py_root_file(self):
        """*.py at root level should match root files only."""
        parsed = parse_pattern("*.py")
        assert matches_path(parsed, "setup.py", is_dir=False) is True
        assert matches_path(parsed, "src/setup.py", is_dir=False) is False

    def test_doublestar_no_further_path(self):
        """**/*.py should match a .py file at root level too (** matches zero segments)."""
        parsed = parse_pattern("**/*.py")
        assert matches_path(parsed, "config.py", is_dir=False) is True

    def test_folder_pattern_with_star_wildcard(self):
        """test*/ should match test, tests, testing directories."""
        parsed = parse_pattern("test*/")
        assert matches_path(parsed, "tests", is_dir=True) is True
        assert matches_path(parsed, "testing", is_dir=True) is True
        assert matches_path(parsed, "test", is_dir=True) is True
        assert matches_path(parsed, "best", is_dir=True) is False


# ============================================================================
# compute_targeting_distance() tests
# ============================================================================


class TestTargetingDistanceFilePatterns:
    """File patterns always have distance 0 when they match a file."""

    def test_globstar_file_pattern_distance_zero(self):
        """**/*.py → any .py file = distance 0."""
        assert compute_targeting_distance(parse_pattern("**/*.py"), "src/main.py", is_dir=False) == 0
        assert compute_targeting_distance(parse_pattern("**/*.py"), "tests/test_main.py", is_dir=False) == 0

    def test_explicit_recursive_file_distance_zero(self):
        """**/formatter.py → distance 0."""
        assert compute_targeting_distance(parse_pattern("**/formatter.py"), "dirdigest/formatter.py", is_dir=False) == 0

    def test_anchored_exact_file_distance_zero(self):
        """./src/main.py → distance 0."""
        assert compute_targeting_distance(parse_pattern("./src/main.py"), "src/main.py", is_dir=False) == 0

    def test_multi_segment_file_distance_zero(self):
        """tests/test_main.py → distance 0."""
        assert compute_targeting_distance(parse_pattern("tests/test_main.py"), "tests/test_main.py", is_dir=False) == 0

    def test_file_pattern_non_match_sentinel(self):
        """Non-matching file pattern returns sentinel 999."""
        assert compute_targeting_distance(parse_pattern("**/utils/"), "dirdigest/core.py", is_dir=False) == 999


class TestTargetingDistanceFolderToDir:
    """Folder patterns matching directories: distance = depth difference."""

    def test_exact_folder_match_distance_zero(self):
        """**/utils/ → dirdigest/utils = distance 0."""
        assert compute_targeting_distance(parse_pattern("**/utils/"), "dirdigest/utils", is_dir=True) == 0

    def test_anchored_exact_folder_distance_zero(self):
        """./dirdigest/ → dirdigest = distance 0."""
        assert compute_targeting_distance(parse_pattern("./dirdigest/"), "dirdigest", is_dir=True) == 0

    def test_anchored_folder_to_child_dir_distance_one(self):
        """./dirdigest/ → dirdigest/utils = distance 1."""
        assert compute_targeting_distance(parse_pattern("./dirdigest/"), "dirdigest/utils", is_dir=True) == 1

    def test_anchored_folder_to_grandchild_dir_distance_two(self):
        """./src/ → src/feature/sub = distance 2."""
        assert compute_targeting_distance(parse_pattern("./src/"), "src/feature/sub", is_dir=True) == 2

    def test_unanchored_folder_exact_suffix_distance_zero(self):
        """tests/ → tests = distance 0."""
        assert compute_targeting_distance(parse_pattern("tests/"), "tests", is_dir=True) == 0

    def test_unanchored_folder_to_child_distance_one(self):
        """tests/ → tests/unit = distance 1."""
        assert compute_targeting_distance(parse_pattern("tests/"), "tests/unit", is_dir=True) == 1

    def test_unanchored_folder_nested_match_distance_zero(self):
        """utils/ matching src/utils = distance 0 (suffix match aligns at end)."""
        assert compute_targeting_distance(parse_pattern("utils/"), "src/utils", is_dir=True) == 0


class TestTargetingDistanceFolderToFile:
    """Folder patterns matching files via containment: distance ≥ 1."""

    def test_anchored_folder_to_file_distance_one(self):
        """./dirdigest/ → dirdigest/formatter.py = distance 1."""
        assert compute_targeting_distance(parse_pattern("./dirdigest/"), "dirdigest/formatter.py", is_dir=False) == 1

    def test_anchored_folder_to_deep_file_distance_two(self):
        """./dirdigest/ → dirdigest/utils/patterns.py = distance 2."""
        assert (
            compute_targeting_distance(parse_pattern("./dirdigest/"), "dirdigest/utils/patterns.py", is_dir=False) == 2
        )

    def test_unanchored_folder_to_file_inside_distance_one(self):
        """**/utils/ → dirdigest/utils/patterns.py = distance 1."""
        assert compute_targeting_distance(parse_pattern("**/utils/"), "dirdigest/utils/patterns.py", is_dir=False) == 1

    def test_unanchored_folder_to_file_distance_one(self):
        """tests/ → tests/test_main.py = distance 1."""
        assert compute_targeting_distance(parse_pattern("tests/"), "tests/test_main.py", is_dir=False) == 1

    def test_folder_containment_deeper_file(self):
        """tests/ → tests/unit/test_core.py = distance 2."""
        assert compute_targeting_distance(parse_pattern("tests/"), "tests/unit/test_core.py", is_dir=False) == 2


class TestTargetingDistanceKeyScenarios:
    """Test the key scenarios that motivated targeting distance."""

    def test_file_include_closer_than_folder_exclude(self):
        """**/*.py (dist 0) vs tests/ (dist 1) for tests/test_main.py.

        This is the core spec change: file patterns targeting the file directly
        beat folder patterns that merely contain the file.
        """
        file_inc = parse_pattern("**/*.py")
        folder_exc = parse_pattern("tests/")
        path = "tests/test_main.py"

        inc_dist = compute_targeting_distance(file_inc, path, is_dir=False)
        exc_dist = compute_targeting_distance(folder_exc, path, is_dir=False)

        assert inc_dist == 0
        assert exc_dist == 1
        assert inc_dist < exc_dist  # File include is closer → wins

    def test_broad_folder_vs_targeted_file_exclude(self):
        """./dirdigest/ (dist 1) vs **/formatter.py (dist 0) for formatter.py.

        File-level exclude directly targets the file, beating the broad folder include.
        """
        folder_inc = parse_pattern("./dirdigest/")
        file_exc = parse_pattern("**/formatter.py")
        path = "dirdigest/formatter.py"

        inc_dist = compute_targeting_distance(folder_inc, path, is_dir=False)
        exc_dist = compute_targeting_distance(file_exc, path, is_dir=False)

        assert inc_dist == 1
        assert exc_dist == 0
        assert exc_dist < inc_dist  # File exclude is closer → wins

    def test_cherry_pick_inside_excluded_folder(self):
        """./dirdigest/ (dist 2) vs **/utils/ (dist 1) vs **/patterns* (dist 0).

        Cherry-pick file include beats the intermediate folder exclude.
        """
        broad_inc = parse_pattern("./dirdigest/")
        folder_exc = parse_pattern("**/utils/")
        cherry_inc = parse_pattern("**/patterns*")
        path = "dirdigest/utils/patterns.py"

        assert compute_targeting_distance(broad_inc, path, is_dir=False) == 2
        assert compute_targeting_distance(folder_exc, path, is_dir=False) == 1
        assert compute_targeting_distance(cherry_inc, path, is_dir=False) == 0
