# dirdigest/utils/patterns.py
"""Smart pattern matching engine for dirdigest include/exclude filters.

Implements 7 rules from the Smart Pattern Rules v1.0 spec:
1. Anchoring: ./ = exact from root, bare = suffix match, **/ = explicit recursive
2. Type discrimination: trailing / = folders, no slash = files
3. Wildcards: POSIX standard (*, **, ?)
4. Multiple includes = OR (additive)
5. Exclusion symmetry: -x follows same rules as -i
6. Specificity precedence: 8-rank system, most specific wins
7. Default ignores always apply unless --no-default-ignore
"""

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List


@dataclass(frozen=True)
class ParsedPattern:
    """A parsed pattern with metadata for specificity ranking."""

    raw: str  # Original user input
    anchored: bool  # True if starts with "./"
    is_folder: bool  # True if ends with "/"
    has_wildcards: bool  # True if contains *, **, ?
    explicit_recursive: bool  # True if had **/ prefix (match at any depth)
    segments: list[str]  # Path segments after stripping prefix/suffix
    glob_expr: str  # Normalized glob expression for matching
    specificity: int  # Pre-computed specificity rank 1-8


def parse_pattern(pattern: str) -> ParsedPattern:
    """Parse a raw pattern string into structured metadata.

    Handles:
    - "./" prefix → anchored to project root
    - Trailing "/" → folder pattern
    - "**/" prefix → explicit recursive (treated same as unanchored)
    - Wildcard detection (*, **, ?)
    """
    raw = pattern
    norm = pattern.replace(os.sep, "/")

    # Determine anchoring
    anchored = norm.startswith("./")
    if anchored:
        norm = norm[2:]  # Strip "./" prefix

    # Determine type (folder vs file)
    # Check before stripping, so "./" (which becomes "") is detected as folder
    # since the original had a trailing "/"
    is_folder = norm.endswith("/") or (anchored and norm == "")
    if norm.endswith("/"):
        norm = norm.rstrip("/")

    # Handle **/ prefix (explicit recursive = same as unanchored)
    explicit_recursive = False
    if norm.startswith("**/"):
        explicit_recursive = True
        norm = norm[3:]

    # Detect wildcards
    has_wildcards = any(c in norm for c in ("*", "?"))

    # Split into segments
    segments = [s for s in norm.split("/") if s]

    # Build glob expression for matching
    glob_expr = norm

    # Compute specificity rank (1 = most specific, 8 = least)
    specificity = _compute_specificity(
        anchored=anchored,
        is_folder=is_folder,
        has_wildcards=has_wildcards,
        segments=segments,
        explicit_recursive=explicit_recursive,
    )

    return ParsedPattern(
        raw=raw,
        anchored=anchored,
        is_folder=is_folder,
        has_wildcards=has_wildcards,
        explicit_recursive=explicit_recursive,
        segments=segments,
        glob_expr=glob_expr,
        specificity=specificity,
    )


def _compute_specificity(
    anchored: bool,
    is_folder: bool,
    has_wildcards: bool,
    segments: list[str],
    explicit_recursive: bool,
) -> int:
    """Compute specificity rank 1-8 (1 = most specific).

    Ranking:
    1. Anchored + exact filename   (./src/test_main.py)
    2. Anchored + folder           (./src/tests/)
    3. Anchored + glob             (./tests/**/*.py)
    4. Path + filename             (tests/test_main.py)  — multi-segment, no wildcards, file
    5. Path + glob                 (tests/**/*.py)       — multi-segment with wildcards
    6. Single name (file)          (config.py, **/config.py) — single segment, file
    7. Single name (folder)        (tests/, **/tests/)     — single segment, folder
    8. Glob only                   (**/*.py)               — has wildcards
    """
    multi_segment = len(segments) > 1

    if anchored and not has_wildcards and not is_folder:
        return 1  # Anchored exact filename
    if anchored and not has_wildcards and is_folder:
        return 2  # Anchored folder
    if anchored and has_wildcards:
        return 3  # Anchored glob

    if not explicit_recursive and multi_segment and not has_wildcards and not is_folder:
        return 4  # Path + filename
    if not explicit_recursive and multi_segment and has_wildcards:
        return 5  # Path + glob

    if not has_wildcards and not is_folder and not multi_segment:
        return 6  # Single name file (config.py or **/config.py)
    if not has_wildcards and is_folder and not multi_segment:
        return 7  # Single name folder (tests/ or **/tests/)

    return 8  # Glob only (**/*.py)


def matches_path(parsed: ParsedPattern, rel_path: str, is_dir: bool) -> bool:
    """Check if a parsed pattern matches a relative path.

    Args:
        parsed: A ParsedPattern from parse_pattern()
        rel_path: Relative path from project root (e.g., "src/utils/helpers.py")
        is_dir: True if the path is a directory
    """
    # Type discrimination: folder patterns only match dirs, file patterns only match files
    if parsed.is_folder and not is_dir:
        # Folder pattern can match files INSIDE the folder
        # e.g., "tests/" should match "tests/test_main.py"
        return _path_is_under_folder_pattern(parsed, rel_path)
    if parsed.is_folder and is_dir:
        return _matches_folder(parsed, rel_path)
    if not parsed.is_folder and is_dir:
        return False  # File patterns never match directories

    # File pattern matching a file
    return _matches_file(parsed, rel_path)


def compute_targeting_distance(parsed: ParsedPattern, rel_path: str, is_dir: bool) -> int:
    """Compute how directly a pattern targets a specific path.

    Returns the number of directory levels between the pattern's match
    point and the target item. Lower = more targeted.

    - 0: Pattern directly names this item (file→file or folder→exact folder)
    - N: Pattern names an ancestor folder N levels above the target

    Precondition: pattern should already match path (via matches_path).
    Returns 999 if the pattern does not match (sentinel, sorts last in min()).
    """
    if not matches_path(parsed, rel_path, is_dir):
        return 999

    path_parts = PurePosixPath(rel_path.replace(os.sep, "/")).parts

    # File pattern matching a file: always distance 0 (directly targets the file)
    if not parsed.is_folder and not is_dir:
        return 0

    # File pattern cannot match a directory — matches_path returns False above
    # so we only have folder patterns from here

    # Folder pattern matching a directory
    if parsed.is_folder and is_dir:
        if parsed.anchored:
            # Anchored: distance = how much deeper the path is than the pattern
            return len(path_parts) - len(parsed.segments)
        else:
            # Unanchored/recursive: find where the pattern matched
            pos = _suffix_match_folder_position(parsed.segments, path_parts, must_have_child=False)
            if pos is not None:
                # Distance = remaining path parts after the matched region
                return len(path_parts) - (pos + len(parsed.segments))
            return 999  # Should not happen if matches_path was True

    # Folder pattern matching a file (containment)
    if parsed.is_folder and not is_dir:
        if parsed.anchored:
            # Anchored: file is inside the folder, distance = depth beyond folder
            return len(path_parts) - len(parsed.segments)
        else:
            # Unanchored: find where the folder matched
            pos = _suffix_match_folder_position(parsed.segments, path_parts, must_have_child=True)
            if pos is not None:
                return len(path_parts) - (pos + len(parsed.segments))
            return 999  # Should not happen if matches_path was True

    return 999  # Unreachable


def _path_is_under_folder_pattern(parsed: ParsedPattern, rel_path: str) -> bool:
    """Check if a file path is inside a folder matched by this folder pattern."""
    path_parts = PurePosixPath(rel_path.replace(os.sep, "/")).parts

    if parsed.anchored:
        # Anchored folder: path must start with the pattern segments
        if len(path_parts) <= len(parsed.segments):
            return False
        for i, seg in enumerate(parsed.segments):
            if not fnmatch.fnmatch(path_parts[i], seg):
                return False
        return True
    else:
        # Unanchored folder (suffix match): find the segments anywhere in path
        return _suffix_match_folder(parsed.segments, path_parts, must_have_child=True)


def _matches_folder(parsed: ParsedPattern, rel_path: str) -> bool:
    """Check if a directory path matches a folder pattern."""
    path_parts = PurePosixPath(rel_path.replace(os.sep, "/")).parts

    if parsed.anchored:
        # Anchored: exact match from root
        if len(path_parts) != len(parsed.segments):
            # Also match if path is a subdirectory of the pattern
            if len(path_parts) > len(parsed.segments):
                for i, seg in enumerate(parsed.segments):
                    if not fnmatch.fnmatch(path_parts[i], seg):
                        return False
                return True
            return False
        return all(fnmatch.fnmatch(p, s) for p, s in zip(path_parts, parsed.segments))
    else:
        # Unanchored: suffix match — path ends with pattern segments
        return _suffix_match_folder(parsed.segments, path_parts, must_have_child=False)


def _suffix_match_folder_position(
    pattern_segments: list[str], path_parts: tuple[str, ...], must_have_child: bool
) -> int | None:
    """Find the start index where pattern_segments match within path_parts.

    Returns the start index of the first matching position, or None if no match.

    For folder patterns, we check if any contiguous subsequence of path_parts
    matches the pattern_segments.

    If must_have_child is True, there must be at least one more path component
    after the matched segments (i.e., the file is inside the folder).
    """
    n_pat = len(pattern_segments)
    n_path = len(path_parts)

    if must_have_child:
        # Need at least n_pat segments for folder + 1 for child
        if n_path <= n_pat:
            return None
        search_limit = n_path - n_pat  # Don't include last segment (the file name)
    else:
        if n_path < n_pat:
            return None
        search_limit = n_path - n_pat + 1

    for start in range(search_limit):
        if all(fnmatch.fnmatch(path_parts[start + i], pattern_segments[i]) for i in range(n_pat)):
            return start
    return None


def _suffix_match_folder(pattern_segments: list[str], path_parts: tuple[str, ...], must_have_child: bool) -> bool:
    """Check if path_parts contain a suffix match for pattern_segments.

    Thin wrapper around _suffix_match_folder_position() for backward compatibility.
    """
    return _suffix_match_folder_position(pattern_segments, path_parts, must_have_child) is not None


def _matches_file(parsed: ParsedPattern, rel_path: str) -> bool:
    """Check if a file path matches a file pattern."""
    norm_path = rel_path.replace(os.sep, "/")
    path_parts = PurePosixPath(norm_path).parts

    if parsed.anchored:
        # Anchored: match from root
        if "**" in parsed.segments:
            # Anchored with **: use doublestar matcher anchored to root
            return _match_doublestar_file(parsed.segments, path_parts)
        # Exact match: segment count must match exactly
        if len(path_parts) != len(parsed.segments):
            return False
        return all(fnmatch.fnmatch(p, s) for p, s in zip(path_parts, parsed.segments))

    # Check for ** in segments (recursive glob)
    if "**" in parsed.segments:
        if parsed.anchored:
            return _match_doublestar_file(parsed.segments, path_parts)
        # Unanchored: try suffix matching from each start position
        # e.g., tests/**/*.py should match src/feature/tests/test_module.py
        for start in range(len(path_parts)):
            if _match_segments(parsed.segments, 0, path_parts, start):
                return True
        return False

    if len(parsed.segments) == 1:
        if parsed.explicit_recursive or not parsed.has_wildcards:
            # Match basename at any depth:
            # - explicit_recursive: **/ prefix was stripped (e.g., **/*.py → *.py)
            # - literal name: suffix match per Rule 1 (e.g., "config.py" matches "src/config.py")
            return fnmatch.fnmatch(path_parts[-1], parsed.segments[0])
        else:
            # Wildcarded single segment without **/: root-only per Rule 3
            # e.g., *.py matches root-level only, **/*.py matches any depth
            if len(path_parts) != 1:
                return False
            return fnmatch.fnmatch(path_parts[0], parsed.segments[0])

    # Multi-segment: suffix match against path
    n_pat = len(parsed.segments)
    n_path = len(path_parts)
    if n_path < n_pat:
        return False

    # Try suffix matching: align pattern segments to end of path
    for start in range(n_path - n_pat + 1):
        if all(fnmatch.fnmatch(path_parts[start + i], parsed.segments[i]) for i in range(n_pat)):
            return True
    return False


def _match_doublestar_file(pattern_segments: list[str], path_parts: tuple[str, ...]) -> bool:
    """Match a file pattern containing ** against path parts.

    ** matches zero or more directory levels.
    """
    return _match_segments(pattern_segments, 0, path_parts, 0)


def _match_segments(pat_segs: list[str], pi: int, path_parts: tuple[str, ...], pp: int) -> bool:
    """Recursive segment matcher supporting ** wildcards."""
    while pi < len(pat_segs) and pp < len(path_parts):
        if pat_segs[pi] == "**":
            # ** can match zero or more segments
            pi += 1
            if pi >= len(pat_segs):
                return True  # ** at end matches everything
            # Try matching remaining pattern at every position
            for skip in range(pp, len(path_parts)):
                if _match_segments(pat_segs, pi, path_parts, skip):
                    return True
            return False
        elif fnmatch.fnmatch(path_parts[pp], pat_segs[pi]):
            pi += 1
            pp += 1
        else:
            return False

    # Skip trailing ** patterns
    while pi < len(pat_segs) and pat_segs[pi] == "**":
        pi += 1

    return pi >= len(pat_segs) and pp >= len(path_parts)


# --- Backward-compatible wrappers ---


def matches_pattern(path_str: str, pattern_str: str) -> bool:
    """Check if path matches pattern (backward-compatible wrapper).

    For use by code that hasn't migrated to the ParsedPattern API.
    """
    parsed = parse_pattern(pattern_str)
    # Determine if this is a directory by checking if the path appears to be one
    # When called from core.py, directories have trailing separator or are known dirs
    # For backward compat, we try both file and dir matching
    norm_path = path_str.replace(os.sep, "/")

    if parsed.is_folder:
        # Folder pattern: try matching as if path is a dir, or as a file inside the folder
        if matches_path(parsed, norm_path, is_dir=True):
            return True
        if matches_path(parsed, norm_path, is_dir=False):
            return True
        return False
    else:
        # File pattern: match as file
        return matches_path(parsed, norm_path, is_dir=False)


def matches_patterns(path_str: str, patterns: List[str]) -> bool:
    """Check if path matches any of the provided patterns (backward-compatible wrapper)."""
    for pattern_item in patterns:
        if matches_pattern(path_str, pattern_item):
            return True
    return False


def is_path_hidden(path_obj: Path) -> bool:
    """Check if any part of the path starts with a '.' character,
    excluding the root '.' itself.
    """
    return any(part.startswith(".") for part in path_obj.parts if part not in (".", os.sep))
