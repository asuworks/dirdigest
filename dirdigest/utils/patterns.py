# dirdigest/utils/patterns.py
import fnmatch
import os
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple


class PatternProperties(NamedTuple):
    """Properties of a parsed pattern for specificity comparison."""
    raw_pattern: str
    normalized_pattern: str
    depth: int
    is_explicit_file: bool
    is_explicit_dir: bool
    is_glob_file: bool
    is_glob_dir: bool
    suffix_parts: Optional[List[str]]
    original_index: int


def _parse_pattern(pattern_str: str, original_index: int) -> PatternProperties:
    """Parses a pattern string and extracts its properties."""
    raw_pattern = pattern_str
    normalized_pattern = pattern_str.replace(os.sep, "/")

    # Depth: count non-"**" segments
    segments = [seg for seg in normalized_pattern.split("/") if seg]
    depth = 0
    # If a pattern is just "**/foo.txt" or "/**/", segments could be ["**", "foo.txt"] or ["**"]
    # If it's "foo/bar", segments are ["foo", "bar"]
    # If it's "foo/", segments are ["foo"]
    # A simple count of segments after stripping trailing "" from "foo/"
    # For "**/a/b", segments are ["**", "a", "b"] depth should be 2 (a,b)
    # For "a/b/**/c", segments are ["a", "b", "**", "c"] depth should be 3 (a,b,c)
    # For "a/b", depth is 2
    # For "a/", depth is 1
    # For "*.txt", depth is 0 (or 1 if we consider filename a segment) - let's say 0 for non-path patterns.
    # Let's define depth as the number of directory segments explicitly mentioned.
    # If the pattern ends with '/', the last part is a directory.
    # If not, the last part is a filename/fileglob.
    # Example: "foo/bar/*.txt" -> segments ["foo", "bar", "*.txt"]. Depth is 2.
    # Example: "foo/bar/" -> segments ["foo", "bar"]. Depth is 2.
    # Example: "*.txt" -> segments ["*.txt"]. Depth is 0.
    # Example: "**/foo/*.txt" -> segments ["**", "foo", "*.txt"]. Effective depth for "foo" is 1.

    temp_segments = [s for s in normalized_pattern.split('/') if s and s != '**']
    # if normalized_pattern.endswith('/'): # e.g. "foo/bar/"
    #     depth = len(temp_segments)
    # elif not '/' in normalized_pattern and any(g in normalized_pattern for g in ['*', '?', '[']): # e.g. "*.txt"
    #     depth = 0
    # elif not '/' in normalized_pattern: # e.g. "file.txt"
    #     depth = 0 # or 1? Let's be consistent: number of DIR segments.
    # else: # e.g. "foo/file.txt" or "foo/*.txt"
    #     depth = len(temp_segments) -1 # Subtract the file part

    # Simpler depth: number of actual path components.
    # "a/b/*.txt" -> depth 2 ("a", "b")
    # "a/b/" -> depth 2 ("a", "b")
    # "*.txt" -> depth 0
    # "file.txt" -> depth 0
    # "**/a/b.txt" -> depth 1 ("a") - this is tricky. Let's use number of non-'**' segments before the filename part.
    path_part = os.path.dirname(normalized_pattern) # "a/b" for "a/b/c.txt", "a" for "a/b/" if ends with /
    if path_part:
        depth = len([seg for seg in path_part.split('/') if seg and seg != '**'])
    else:
        depth = 0

    # Determine pattern type flags
    if normalized_pattern.endswith("/"):
        # Directory Pattern
        dir_part_for_glob_check = normalized_pattern.rstrip('/')
        has_glob_chars_in_dir_defining_part = any(g in dir_part_for_glob_check for g in ['*', '?', '['])

        is_explicit_dir = not has_glob_chars_in_dir_defining_part
        is_glob_dir = has_glob_chars_in_dir_defining_part
        is_explicit_file = False
        is_glob_file = False
    else:
        # File Pattern
        # is_explicit_file means NO globs anywhere in the pattern string.
        # is_glob_file means there IS a glob somewhere in the pattern string.
        has_glob_chars_in_full_pattern = any(g in normalized_pattern for g in ['*', '?', '['])

        is_explicit_file = not has_glob_chars_in_full_pattern
        is_glob_file = has_glob_chars_in_full_pattern
        is_explicit_dir = False
        is_glob_dir = False

    suffix_parts = None
    # Suffix parts are relevant for file patterns (explicit or glob) for Rule 3 (Suffix Proximity)
    if not normalized_pattern.endswith("/"):
        # Get the filename component, e.g., "file.log.txt" from "foo/file.log.txt" or "*.log.txt"
        filename_component = Path(normalized_pattern).name

        # Path(filename_component).suffixes gives ['.log', '.txt'] for "file.log.txt" or "*.log.txt"
        suffixes = Path(filename_component).suffixes
        if suffixes:
            # Store as ['txt', 'log'] for "file.log.txt"
            suffix_parts = [s.lstrip('.') for s in reversed(suffixes)]

    return PatternProperties(
        raw_pattern=raw_pattern,
        normalized_pattern=normalized_pattern,
        depth=depth,
        is_explicit_file=is_explicit_file,
        is_explicit_dir=is_explicit_dir,
        is_glob_file=is_glob_file,
        is_glob_dir=is_glob_dir,
        suffix_parts=suffix_parts,
        original_index=original_index,
    )


def _calculate_matching_depth(path_obj: Path, pattern_props: PatternProperties) -> int:
    """
    Calculates how many leading components of path_obj are matched by the directory part of pattern_props.
    Example: path_obj="a/b/c.txt", pattern_props for "a/" -> matching_depth = 1
             path_obj="a/b/c.txt", pattern_props for "a/b/" -> matching_depth = 2
             path_obj="a/b/c.txt", pattern_props for "*.txt" -> matching_depth = 0
             path_obj="a/b/c.txt", pattern_props for "b/c.txt" (if path rooted at a) -> matching_depth = 0 (pattern isn't anchored at start)
                                                                                                      -> or should be path "a/b/c.txt" vs pattern "b/c.txt" -> 0
             path_obj="a/b/c.txt", pattern_props for "**/b/*.txt" -> matching_depth for "b" component = 1
             path_obj="a/b/c.txt", pattern_props for "a/**/c.txt" -> matching_depth for "a" component = 1
    This relies on the pattern.depth which is the number of explicit dir segments in the pattern.
    The "matching depth" is how many of those pattern directory segments match the path from the start.

    Let's simplify: "matching depth" is the number of directory segments in the pattern
    that appear contiguously at the start of the path being tested.
    If pattern is "foo/bar/" and path is "foo/bar/baz/file.txt", matching depth is 2.
    If pattern is "bar/" and path is "foo/bar/baz/file.txt", matching depth is 0 (as "bar" is not at the start).
    This means patterns are assumed to be relative to the root of iteration.

    Consider pattern "src/" for path "src/utils/file.py".
    Pattern normalized: "src/"
    Pattern dir parts: ["src"]
    Path parts: ["src", "utils", "file.py"]
    Match: "src" == "src". Depth = 1.

    Consider pattern "data/raw/" for path "data/raw/file.csv".
    Pattern dir parts: ["data", "raw"]
    Path parts: ["data", "raw", "file.csv"]
    Match: "data" == "data", "raw" == "raw". Depth = 2.

    Consider pattern "*.txt" for path "data/raw/file.csv".
    Pattern dir parts: []. Depth = 0.

    Consider pattern "**/docs/" for path "project/sub/docs/readme.md"
    Pattern dir parts: ["docs"] (after removing **).
    This needs to be handled by fnmatch for the directory part.
    The "depth" of "**/docs/" is 1 (for "docs").
    When matching "project/sub/docs/readme.md":
        Does "project" match "docs"? No.
        Does "sub" match "docs"? No.
        Does "docs" match "docs"? Yes.
        This means the "docs/" part of the pattern matches at depth 3 of the path.
        This is different from "pattern depth".

    Rule 1: "A pattern is 'deeper' if it matches more leading components of the path_obj."
    This means we take the pattern's directory structure (e.g., "a/b/" from "a/b/*.py")
    and see how many of its components match the path from the beginning.
    "a/b/" against "a/b/c/d.py" -> match depth 2.
    "a/" against "a/b/c/d.py" -> match depth 1.
    "*.py" against "a/b.py" -> match depth 0 (no leading path components in pattern).
    "foo/**/bar.txt" against "foo/x/y/bar.txt". Pattern dir components "foo". Match depth 1.
    "**/bar.txt" against "foo/x/y/bar.txt". Pattern dir components []. Match depth 0 by this rule.

    If pattern is "a/b/", its `normalized_pattern` is "a/b/". `os.path.dirname("a/b/")` is "a/b". `split('/')` -> ["a", "b"].
    If pattern is "a/b/*.txt", `os.path.dirname("a/b/*.txt")` is "a/b". `split('/')` -> ["a", "b"].
    If pattern is "*.txt", `os.path.dirname("*.txt")` is "". `split('/')` -> [].
    These are the `pattern_dir_segments`.
    """
    pattern_dir_str = os.path.dirname(pattern_props.normalized_pattern)
    if not pattern_dir_str: # Handles patterns like "*.txt" or "file.txt"
        return 0

    # For "**/foo/", dirname is "**/foo". We only want "foo".
    # For "a/**/foo/", dirname is "a/**/foo". We want "a", "foo".
    pattern_dir_segments = [seg for seg in pattern_dir_str.split('/') if seg and seg != '**']

    if not pattern_dir_segments: # Handles "**/", or after stripping "**", nothing is left.
        return 0

    path_segments = path_obj.parts
    match_depth = 0
    # Example: pattern_dir_segments = ["a", "b"], path_segments = ("a", "b", "c.txt") -> match_depth = 2
    # Example: pattern_dir_segments = ["a", "b"], path_segments = ("a", "x", "c.txt") -> match_depth = 1
    # Example: pattern_dir_segments = ["a", "b"], path_segments = ("z", "b", "c.txt") -> match_depth = 0
    for i in range(min(len(pattern_dir_segments), len(path_segments))):
        if pattern_dir_segments[i] == path_segments[i]:
            match_depth += 1
        else:
            break # Must be leading components
    return match_depth


def _compare_specificity(path_obj: Path, pattern_a_props: PatternProperties, pattern_b_props: PatternProperties) -> int:
    """
    Compares specificity of two patterns for a given path.
    Returns 1 if a is more specific, -1 if b is more specific, 0 if equal by primary rules.
    """
    # Rule 1: Depth of Matching Pattern Wins
    # "A pattern is 'deeper' if it matches more leading components of the path_obj."
    depth_a = _calculate_matching_depth(path_obj, pattern_a_props)
    depth_b = _calculate_matching_depth(path_obj, pattern_b_props)

    if depth_a > depth_b: return 1
    if depth_b > depth_a: return -1

    # Determine if the path string conceptually represents a directory or a file.
    # This is used to apply Rule 2 and the file/dir tie-breaker correctly,
    # especially when the path doesn't physically exist yet.
    path_str_for_type_check = str(path_obj)
    path_represents_dir = path_str_for_type_check.endswith(os.sep) or \
                          path_str_for_type_check.endswith('/')


    # Rule 2: Explicit File/Folder Name Wins Over Regex (Glob)
    # This rule applies based on the conceptual type of the path.
    if path_represents_dir:
        # Path is conceptually a directory
        if pattern_a_props.is_explicit_dir and pattern_b_props.is_glob_dir: return 1
        if pattern_b_props.is_explicit_dir and pattern_a_props.is_glob_dir: return -1
    else:
        # Path is conceptually a file
        if pattern_a_props.is_explicit_file and pattern_b_props.is_glob_file: return 1
        if pattern_b_props.is_explicit_file and pattern_a_props.is_glob_file: return -1

    # What if A is explicit file and B is explicit dir? (e.g. "foo.txt" vs "foo/") for path "foo.txt"
    # Such cases should ideally be filtered out before comparison if both cannot match the same path_obj.
    # If matches_pattern is robust, "foo/" won't match "foo.txt", and "foo.txt" won't match "foo/" (as a dir).
    # So, we assume that if we reach here, both patterns are valid candidates for the path's type.

    # Rule 3: Suffix Proximity (Filename Glob Tie-breaker)
    # Only if path represents a file, both are file globs, and other specificities are equal.
    if not path_represents_dir and pattern_a_props.is_glob_file and pattern_b_props.is_glob_file:
        if pattern_a_props.suffix_parts and pattern_b_props.suffix_parts:
            path_suffixes = [s.lstrip('.') for s in reversed(Path(path_obj.name).suffixes)]
            if not path_suffixes:
                return 0 # Path has no suffix, rule doesn't apply further.

            a_match_len = 0
            for i in range(min(len(pattern_a_props.suffix_parts), len(path_suffixes))):
                if pattern_a_props.suffix_parts[i] == path_suffixes[i]:
                    a_match_len += 1
                else:
                    break

            b_match_len = 0
            for i in range(min(len(pattern_b_props.suffix_parts), len(path_suffixes))):
                if pattern_b_props.suffix_parts[i] == path_suffixes[i]:
                    b_match_len += 1
                else:
                    break

            if a_match_len > b_match_len: return 1
            if b_match_len > a_match_len: return -1

    # Final Tie-breaking: Pattern type (file/dir) matching the path type (file/dir)
    # This applies if depths are equal, and explicit/glob comparison (Rule 2) didn't resolve.
    # Example: path "foo/bar.txt" (file-like)
    # P_A: "foo/" (dir pattern, depth 1)
    # P_B: "foo/*.txt" (file pattern, depth 1)
    # Here, P_B (file pattern) should win for a file-like path.
    if path_represents_dir:
        if (pattern_a_props.is_explicit_dir or pattern_a_props.is_glob_dir) and \
           (pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file):
            return 1 # Dir pattern A is more specific for a dir-like path
        if (pattern_b_props.is_explicit_dir or pattern_b_props.is_glob_dir) and \
           (pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file):
            return -1 # Dir pattern B is more specific for a dir-like path
    else: # path represents a file
        if (pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file) and \
           (pattern_b_props.is_explicit_dir or pattern_b_props.is_glob_dir):
            return 1 # File pattern A is more specific for a file-like path
        if (pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file) and \
           (pattern_a_props.is_explicit_dir or pattern_a_props.is_glob_dir):
            return -1 # File pattern B is more specific for a file-like path

    return 0 # Equal by primary rules


def determine_most_specific_pattern(
    patterns_with_indices: List[tuple[str, int]], path_str: str
) -> Optional[tuple[str, int]]:
    """
    Determines the most specific pattern that matches the given path_str.

    Args:
        patterns_with_indices: A list of tuples, where each tuple contains a
                               pattern string and its original_index.
        path_str: The path string to match against.

    Returns:
        A tuple containing the most specific pattern string and its original_index,
        or None if no patterns match.
    """
    path_obj = Path(path_str)

    matching_pattern_props_list: List[PatternProperties] = []
    for p_str, p_idx in patterns_with_indices:
        if matches_pattern(str(path_obj), p_str): # Use str(path_obj) for consistency with matches_pattern
            props = _parse_pattern(p_str, p_idx)
            matching_pattern_props_list.append(props)

    if not matching_pattern_props_list:
        return None

    if len(matching_pattern_props_list) == 1:
        winner_props = matching_pattern_props_list[0]
        return (winner_props.raw_pattern, winner_props.original_index)

    # Multiple patterns match, determine the most specific one.
    # Sort first by specificity rules, then by original_index as tie-breaker.
    # We need a custom comparison function for sort.
    # Python's sort is stable, which is good if _compare_specificity returns 0 often.

    # Start with the first matching pattern as the current "most specific"
    most_specific_props = matching_pattern_props_list[0]

    for i in range(1, len(matching_pattern_props_list)):
        current_challenger_props = matching_pattern_props_list[i]

        comparison_result = _compare_specificity(
            path_obj, most_specific_props, current_challenger_props
        )

        if comparison_result == -1: # Challenger is more specific
            most_specific_props = current_challenger_props
        elif comparison_result == 0: # Equal by primary rules, use original_index
            # Larger original index wins (appears later in CLI/config)
            if current_challenger_props.original_index > most_specific_props.original_index:
                most_specific_props = current_challenger_props

    return (most_specific_props.raw_pattern, most_specific_props.original_index)


def matches_pattern(path_str: str, pattern_str: str) -> bool:
    """
    Checks if the given path_str matches the pattern_str using Path.match semantics.
    Handles directory patterns (ending with '/') by matching the directory or its contents.
    """
    path_obj = Path(path_str)
    # Normalize pattern to use / for consistency with Path.match on POSIX-like paths
    # and to simplify pattern adjustments.
    norm_pattern = pattern_str.replace(os.sep, "/")

    # Ensure path_obj is also represented with forward slashes for matching if needed,
    # though Path.match should handle OS-native paths.
    # Forcing path_obj to a string with forward slashes might be more robust for edge cases
    # if Path.match behavior with mixed slashes is not perfectly consistent.
    # However, Path(path_str) should inherently normalize.

    if norm_pattern == ".": # Special case: matches only if path_str is also "."
        return str(path_obj) == "."

    if norm_pattern.endswith("/"):
        # Directory pattern: should match the directory itself or anything inside it.
        # Example: "docs/" should match "docs" or "docs/file.txt" or "docs/subdir/file.txt"
        # Example: "**/docs/" should match "path/to/docs" or "path/to/docs/file.txt"

        base_dir_pattern = norm_pattern.rstrip('/')

        # To match the directory itself OR its contents, we can use "/**"
        # Path.match('foo/bar', 'foo/bar/**') -> True (if ** matches zero elements)
        # Path.match('foo/bar/baz.txt', 'foo/bar/**') -> True
        # Path.match('foo/bar/', 'foo/bar/**') might need path_obj to be "foo/bar" not "foo/bar/"
        # Let's ensure path_obj for a directory doesn't have a trailing slash for match consistency.
        # No, Path objects don't store trailing slashes in their string representation unless it's root.
        # Path("docs/").name is "docs". Path("docs/").__str__() is "docs". Path("docs/file").__str__() is "docs/file"

        # Pattern `base_dir_pattern` should match `path_obj` if `path_obj` IS that directory.
        # Pattern `base_dir_pattern/**` should match `path_obj` if `path_obj` is INSIDE that directory or IS the directory.

        # If base_dir_pattern is empty (e.g. pattern was "/"), it means match root and everything under.
        # Path(".").match("/**") -> True. Path("foo").match("/**") -> True
        if not base_dir_pattern: # Original pattern was "/" or "**/", treat as matching everything.
             # However, "/" typically means root of the scan. "/**" is more explicit for Path.match.
             # If pattern_str was just "/", it means match files directly in root, or root itself.
             # This needs careful definition. For dirdigest, "/" as exclude usually means ignore files in root.
             # Let's assume "/" means "match the root directory and its direct contents".
             # A pattern like "/**" is more general for "match everything".
             # Given current tool, "/" is likely not a common pattern. Let's stick to general logic.
             # If pattern_str is just "/", norm_pattern is "/", base_dir_pattern is "".
             # Path("file.txt").match("**") -> True.
             # Path(".").match("**") -> True
             # This seems too broad. Let's refine for specific cases.
            if pattern_str == "/" or pattern_str == os.sep:
                # A path is in root if its parent is "."
                # It also matches if path_obj is "." (the root itself)
                is_in_root = (str(path_obj.parent) == ".")
                is_root_itself = (str(path_obj) == ".")
                return is_in_root or is_root_itself

        # Logic for other directory patterns (e.g., "docs/", "**/logs/", "build/**/")
        if base_dir_pattern == "**": # Original pattern was "**/"
            adjusted_pattern = "**"  # Matches everything
        elif base_dir_pattern.endswith("/**"): # Original pattern was e.g. "foo/**/"
            adjusted_pattern = base_dir_pattern # Already correctly a glob for contents
        else:
            # General case: "docs/" -> "docs/**", "**/data/" -> "**/data/**"
            adjusted_pattern = base_dir_pattern + "/**"

        return path_obj.match(adjusted_pattern)
    else:
        # File pattern (does not end with /): use Path.match directly.
        # Example: "*.py", "**/file.log", "LICENSE", "data/config.json"
        return path_obj.match(norm_pattern)


def matches_patterns(
    path_str: str, patterns: List[str]
) -> bool:  # Changed from list[str] to List[str] for older Pythons if needed
    """Checks if the path_str matches any of the provided patterns."""
    for pattern_item in patterns:
        if matches_pattern(path_str, pattern_item):
            return True
    return False


def is_path_hidden(path_obj: Path) -> bool:
    """
    Checks if any part of the path starts with a '.' character,
    excluding the root '.' itself if path_obj is Path(".").
    """
    # Path(".").parts is ('.',), Path(".git").parts is ('.git',)
    # Path("src/.config").parts is ("src", ".config")
    return any(part.startswith(".") for part in path_obj.parts if part not in (".", os.sep))


def _get_pattern_properties(pattern_str: Optional[str], path_obj: Path, original_index: int = -1) -> Optional[PatternProperties]:
    """
    Helper to parse a single pattern string (if not None) and return its PatternProperties.
    The path_obj is currently not used in _parse_pattern but might be in future refinements
    or for context, so it's passed. original_index defaults to -1 for non-user patterns.
    """
    if pattern_str is None:
        return None
    # _parse_pattern expects a path_obj for context, but it's not strictly used by _parse_pattern itself.
    # We pass it along. For default patterns, original_index can be a placeholder like -1 or a specific negative range.
    return _parse_pattern(pattern_str, original_index)
