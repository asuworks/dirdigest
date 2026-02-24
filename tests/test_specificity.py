# tests/test_specificity.py
"""Tests for specificity-based pattern conflict resolution.

Tests cover:
- ParsedPattern dataclass and parse_pattern()
- compute_specificity() ranking
- matches_path() matching
- resolve_pattern_conflicts() in core.py
- Integration with _traverse() via process_directory_recursive()
"""

from dirdigest.core import resolve_pattern_conflicts
from dirdigest.utils.patterns import (
    matches_path,
    parse_pattern,
)

# ============================================================
# Tests for parse_pattern()
# ============================================================


class TestParsePattern:
    """Test that parse_pattern creates correct ParsedPattern instances."""

    def test_parse_glob_star_extension(self):
        """Pattern like '**/*.py' should be parsed correctly."""
        pp = parse_pattern("**/*.py")
        assert pp.raw == "**/*.py"
        assert pp.is_folder is False

    def test_parse_directory_pattern(self):
        """Pattern like 'tests/' should be recognized as directory pattern."""
        pp = parse_pattern("tests/")
        assert pp.raw == "tests/"
        assert pp.is_folder is True

    def test_parse_exact_file(self):
        """Pattern like 'tests/test_main.py' should be recognized as exact path."""
        pp = parse_pattern("tests/test_main.py")
        assert pp.raw == "tests/test_main.py"
        assert pp.is_folder is False

    def test_parse_globstar_directory(self):
        """Pattern like '**/tests/' should be parsed as dir pattern."""
        pp = parse_pattern("**/tests/")
        assert pp.raw == "**/tests/"
        assert pp.is_folder is True

    def test_parse_simple_wildcard(self):
        """Pattern like '*.txt' should be parsed."""
        pp = parse_pattern("*.txt")
        assert pp.raw == "*.txt"


# ============================================================
# Tests for compute_specificity()
# ============================================================


class TestComputeSpecificity:
    """Test specificity ranking: lower number = more specific = wins conflicts.

    Ranking (from most specific to least):
    - Exact file path (e.g. 'src/main.py') -> lowest rank
    - Exact file in dir (e.g. 'tests/test_main.py') -> low rank
    - Directory pattern (e.g. 'tests/') -> medium rank
    - Globstar extension (e.g. '**/*.py') -> high rank
    """

    def test_exact_file_more_specific_than_directory(self):
        """'tests/test_main.py' should be more specific than 'tests/'."""
        exact = parse_pattern("tests/test_main.py")
        directory = parse_pattern("tests/")
        assert exact.specificity < directory.specificity

    def test_directory_more_specific_than_globstar_ext(self):
        """'tests/' should be more specific than '**/*.py'."""
        directory = parse_pattern("tests/")
        globstar = parse_pattern("**/*.py")
        assert directory.specificity < globstar.specificity

    def test_exact_file_most_specific(self):
        """An exact file path should have the lowest (most specific) rank."""
        exact = parse_pattern("tests/test_main.py")
        globstar = parse_pattern("**/*.py")
        directory = parse_pattern("tests/")
        assert exact.specificity < directory.specificity
        assert exact.specificity < globstar.specificity

    def test_globstar_dir_less_specific_than_plain_dir(self):
        """'**/tests/' should be less specific than 'tests/'."""
        globstar_dir = parse_pattern("**/tests/")
        plain_dir = parse_pattern("tests/")
        assert plain_dir.specificity <= globstar_dir.specificity

    def test_simple_wildcard_specificity(self):
        """'*.py' and '**/*.py' are both glob-only patterns (rank 8).
        *.py only matches root-level files while **/*.py matches any depth,
        but both have the same specificity rank in the 8-level system."""
        root_wild = parse_pattern("*.py")
        globstar_wild = parse_pattern("**/*.py")
        assert root_wild.specificity == globstar_wild.specificity


# ============================================================
# Tests for matches_path()
# ============================================================


class TestMatchesPath:
    """Test that matches_path correctly determines if a pattern matches a path."""

    def test_globstar_ext_matches_nested_file(self):
        """'**/*.py' should match 'src/main.py'."""
        pp = parse_pattern("**/*.py")
        assert matches_path(pp, "src/main.py", is_dir=False) is True

    def test_globstar_ext_no_match_different_ext(self):
        """'**/*.py' should not match 'src/main.txt'."""
        pp = parse_pattern("**/*.py")
        assert matches_path(pp, "src/main.txt", is_dir=False) is False

    def test_directory_pattern_matches_dir(self):
        """'tests/' should match the directory 'tests'."""
        pp = parse_pattern("tests/")
        assert matches_path(pp, "tests", is_dir=True) is True

    def test_directory_pattern_matches_file_inside(self):
        """'tests/' should match 'tests/test_main.py' (file inside tests dir)."""
        pp = parse_pattern("tests/")
        assert matches_path(pp, "tests/test_main.py", is_dir=False) is True

    def test_exact_file_matches(self):
        """'tests/test_main.py' should match exactly that path."""
        pp = parse_pattern("tests/test_main.py")
        assert matches_path(pp, "tests/test_main.py", is_dir=False) is True

    def test_exact_file_no_match_different_path(self):
        """'tests/test_main.py' should not match 'src/test_main.py'."""
        pp = parse_pattern("tests/test_main.py")
        assert matches_path(pp, "src/test_main.py", is_dir=False) is False

    def test_globstar_dir_matches_nested(self):
        """'**/tests/' should match 'src/tests' directory."""
        pp = parse_pattern("**/tests/")
        assert matches_path(pp, "src/tests", is_dir=True) is True

    def test_globstar_dir_matches_file_inside_nested(self):
        """'**/tests/' should match 'src/tests/foo.py' (file inside nested tests)."""
        pp = parse_pattern("**/tests/")
        assert matches_path(pp, "src/tests/foo.py", is_dir=False) is True


# ============================================================
# Tests for resolve_pattern_conflicts()
# ============================================================


class TestResolvePatternConflicts:
    """Test the main conflict resolution function in core.py."""

    def test_include_only_matching(self):
        """-i '**/*.py' -> .py files included, others not."""
        includes = [parse_pattern("**/*.py")]
        excludes = []

        included, reason = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True

    def test_include_only_not_matching(self):
        """-i '**/*.py' -> .txt files NOT included."""
        includes = [parse_pattern("**/*.py")]
        excludes = []

        included, reason = resolve_pattern_conflicts(
            "src/readme.txt",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_exclude_only_matching(self):
        """-x 'tests/' -> tests/ excluded."""
        includes = []
        excludes = [parse_pattern("tests/")]

        included, reason = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=excludes,
            exclude_parsed=excludes,
        )
        # Oops, fix the args - include_parsed should be includes
        included, reason = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_exclude_only_not_matching(self):
        """-x 'tests/' -> src/main.py NOT excluded (included by default)."""
        includes = []
        excludes = [parse_pattern("tests/")]

        included, reason = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True

    def test_file_include_beats_folder_exclude_by_distance(self):
        """-i '**/*.py' -x 'tests/' -> tests/test_main.py INCLUDED.

        With targeting distance: **/*.py directly targets the file (distance 0),
        while tests/ is a folder ancestor (distance 1). Closer targeting wins.
        To exclude .py files in tests/, use -x 'tests/**/*.py'.
        """
        includes = [parse_pattern("**/*.py")]
        excludes = [parse_pattern("tests/")]

        included, reason = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True
        assert "**/*.py" in reason

    def test_override_with_higher_specificity_include(self):
        """-i 'tests/test_main.py' -x 'tests/' -> file included.

        Exact file path (tests/test_main.py) is more specific than
        directory pattern (tests/), so include wins.
        """
        includes = [parse_pattern("tests/test_main.py")]
        excludes = [parse_pattern("tests/")]

        included, reason = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True
        assert "tests/test_main.py" in reason

    def test_full_spec_example_with_targeting_distance(self):
        """-i '**/*.py' -x 'tests/' -i 'tests/test_main.py'

        With targeting distance:
        - src/main.py -> included (matches **/*.py, no exclude)
        - tests/test_other.py -> INCLUDED (**/*.py at distance 0 beats tests/ at distance 1)
        - tests/test_main.py -> included (exact path at distance 0 beats tests/ at distance 1)
        """
        includes = [parse_pattern("**/*.py"), parse_pattern("tests/test_main.py")]
        excludes = [parse_pattern("tests/")]

        # src/main.py: matches **/*.py include, no exclude matches
        inc1, _ = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc1 is True

        # tests/test_other.py: **/*.py (distance 0) beats tests/ (distance 1)
        inc2, reason2 = resolve_pattern_conflicts(
            "tests/test_other.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc2 is True

        # tests/test_main.py: exact path (distance 0) beats tests/ (distance 1)
        inc3, reason3 = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc3 is True

    def test_tiebreaker_exclude_wins(self):
        """When include and exclude have equal specificity, exclude wins."""
        # Both are directory patterns with same specificity
        includes = [parse_pattern("logs/")]
        excludes = [parse_pattern("logs/")]

        included, reason = resolve_pattern_conflicts(
            "logs/app.log",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False, "On tie, exclude should win"

    def test_no_patterns_everything_included(self):
        """No patterns specified -> everything included."""
        includes = []
        excludes = []

        included, reason = resolve_pattern_conflicts(
            "any/file.txt",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True

    def test_empty_include_with_exclude(self):
        """Empty include list with exclude -> only excludes applied.

        Files not matching exclude should be included.
        """
        includes = []
        excludes = [parse_pattern("tests/")]

        # File outside tests/ should be included
        inc1, _ = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc1 is True

        # File inside tests/ should be excluded
        inc2, _ = resolve_pattern_conflicts(
            "tests/test_main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc2 is False

    def test_directory_resolution(self):
        """Directories should also be resolved correctly."""
        includes = []
        excludes = [parse_pattern("tests/")]

        included, reason = resolve_pattern_conflicts(
            "tests",
            is_dir=True,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_include_dir_pattern(self):
        """Include with directory pattern should match dirs."""
        includes = [parse_pattern("src/")]
        excludes = []

        inc1, _ = resolve_pattern_conflicts(
            "src",
            is_dir=True,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc1 is True

        # File not in src/ should be excluded (include filter active)
        inc2, _ = resolve_pattern_conflicts(
            "README.md",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert inc2 is False

    def test_reason_cites_winning_pattern(self):
        """The reason string should reference the winning pattern."""
        includes = [parse_pattern("**/*.py")]
        excludes = []

        _, reason = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert "**/*.py" in reason

    def test_no_match_with_includes_specified(self):
        """If includes specified but path matches none, it should be excluded."""
        includes = [parse_pattern("**/*.py")]
        excludes = []

        included, reason = resolve_pattern_conflicts(
            "data/file.csv",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False
        assert "no include pattern" in reason.lower() or "not match" in reason.lower()


# ============================================================
# Tests for targeting distance integration with resolve_pattern_conflicts
# ============================================================


class TestTargetingDistanceResolution:
    """Test that resolve_pattern_conflicts uses (distance, rank) tuples correctly."""

    def test_broad_scope_plus_file_exclude(self):
        """-i './dirdigest/' -x '**/formatter.py' → formatter.py EXCLUDED.

        File exclude (distance 0) beats folder include (distance 1).
        """
        includes = [parse_pattern("./dirdigest/")]
        excludes = [parse_pattern("**/formatter.py")]

        included, reason = resolve_pattern_conflicts(
            "dirdigest/formatter.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False
        assert "formatter.py" in reason

    def test_broad_scope_plus_folder_exclude_plus_cherry_pick(self):
        """-i './dirdigest/' -x '**/utils/' -i '**/patterns*' → patterns.py INCLUDED.

        Cherry-pick file include (distance 0) beats folder exclude (distance 1).
        """
        includes = [parse_pattern("./dirdigest/"), parse_pattern("**/patterns*")]
        excludes = [parse_pattern("**/utils/")]

        included, reason = resolve_pattern_conflicts(
            "dirdigest/utils/patterns.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is True
        assert "patterns" in reason

    def test_folder_exclude_still_wins_for_directory(self):
        """-i './dirdigest/' -x '**/utils/' → utils/ dir itself EXCLUDED.

        For the directory itself: **/utils/ (distance 0) vs ./dirdigest/ (distance 1).
        Exclude at closer distance wins.
        """
        includes = [parse_pattern("./dirdigest/")]
        excludes = [parse_pattern("**/utils/")]

        included, reason = resolve_pattern_conflicts(
            "dirdigest/utils",
            is_dir=True,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_same_distance_same_rank_exclude_wins(self):
        """Two folder patterns at same distance → exclude wins tie."""
        includes = [parse_pattern("logs/")]
        excludes = [parse_pattern("logs/")]

        included, reason = resolve_pattern_conflicts(
            "logs/app.log",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_folder_exclude_beats_folder_include_same_distance(self):
        """-i 'src/' -x 'tests/' for tests dir → excluded (only tests/ matches)."""
        includes = [parse_pattern("src/")]
        excludes = [parse_pattern("tests/")]

        included, _ = resolve_pattern_conflicts(
            "tests",
            is_dir=True,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False

    def test_file_exclude_at_distance_zero_beats_file_include_by_rank(self):
        """-i '**/*.py' -x './src/main.py' → src/main.py EXCLUDED.

        Both at distance 0, but ./src/main.py (rank 1) beats **/*.py (rank 8).
        """
        includes = [parse_pattern("**/*.py")]
        excludes = [parse_pattern("./src/main.py")]

        included, reason = resolve_pattern_conflicts(
            "src/main.py",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False
        assert "src/main.py" in reason

    def test_multiple_scopes_with_narrowing(self):
        """-i './src/' -i './tests/' -x '**/fixtures/' for tests/fixtures/data.json.

        **/fixtures/ (distance 1) vs ./tests/ (distance 2). Closer exclude wins.
        """
        includes = [parse_pattern("./src/"), parse_pattern("./tests/")]
        excludes = [parse_pattern("**/fixtures/")]

        included, reason = resolve_pattern_conflicts(
            "tests/fixtures/data.json",
            is_dir=False,
            include_parsed=includes,
            exclude_parsed=excludes,
        )
        assert included is False
