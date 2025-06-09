# dirdigest/utils/patterns.py
import fnmatch
import os
import fnmatch # Ensure fnmatch is imported, though it was already
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple
from dirdigest.utils.logger import logger # Import the logger


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

    # Depth calculation
    # Effective pattern for depth: strip trailing slash for dirs, then split
    # "a/b/c.txt" -> ["a", "b", "c.txt"] -> depth 3
    # "a/b/" -> "a/b" -> ["a", "b"] -> depth 2
    # "file.txt" -> ["file.txt"] -> depth 1
    # "**/file.txt" -> ["**", "file.txt"] -> filter "**" -> ["file.txt"] -> depth 1
    # "a/**/b.py" -> ["a", "**", "b.py"] -> filter "**" -> ["a", "b.py"] -> depth 2
    # "a/**/foo/" -> "a/**/foo" -> ["a", "**", "foo"] -> filter "**" -> ["a", "foo"] -> depth 2
    # "/" -> "" -> [] -> depth 0 (special case, matches root items)
    # "**/" -> "**" -> ["**"] -> filter "**" -> [] -> depth 0 (matches anything, no specific depth)
    temp_pattern_for_depth = normalized_pattern
    if temp_pattern_for_depth.endswith('/'):
        temp_pattern_for_depth = temp_pattern_for_depth.rstrip('/')

    if not temp_pattern_for_depth: # Handles case of "/" or multiple "///"
        depth = 0 # Or 1 if we consider root itself a level? Tests imply 0 for generic "**/"
    else:
        depth_segments = [seg for seg in temp_pattern_for_depth.split('/') if seg and seg != '**']
        depth = len(depth_segments)

    if normalized_pattern.endswith("/"):
        dir_part_for_glob_check = normalized_pattern.rstrip('/')
        has_glob_chars_in_dir_defining_part = any(g in dir_part_for_glob_check for g in ['*', '?', '['])
        is_explicit_dir = not has_glob_chars_in_dir_defining_part
        is_glob_dir = has_glob_chars_in_dir_defining_part
        is_explicit_file = False
        is_glob_file = False
    else:
        has_glob_chars_in_full_pattern = any(g in normalized_pattern for g in ['*', '?', '['])
        is_explicit_file = not has_glob_chars_in_full_pattern
        is_glob_file = has_glob_chars_in_full_pattern
        is_explicit_dir = False
        is_glob_dir = False

    suffix_parts = None
    if not normalized_pattern.endswith("/"):
        filename_component = Path(normalized_pattern).name
        suffixes = Path(filename_component).suffixes
        if suffixes:
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
    pattern_dir_str = os.path.dirname(pattern_props.normalized_pattern)
    if not pattern_dir_str: return 0
    pattern_dir_segments = [seg for seg in pattern_dir_str.split('/') if seg and seg != '**']
    if not pattern_dir_segments: return 0
    path_segments = path_obj.parts
    match_depth = 0
    for i in range(min(len(pattern_dir_segments), len(path_segments))):
        if pattern_dir_segments[i] == path_segments[i]:
            match_depth += 1
        else:
            break
    # Example: path 'a/d/d', pattern '**/d'.
    # current_path_prefix 'a' -> fnmatch('a', '**/d') -> F
    # current_path_prefix 'a/d' -> fnmatch('a/d', '**/d') -> T, max_match_depth = 2
    # current_path_prefix 'a/d/d' -> fnmatch('a/d/d', '**/d') -> T, max_match_depth = 3. This is correct.
    return max_match_depth

def _calculate_matching_depth(path_obj: Path, pattern_props: PatternProperties) -> int:
    # Rule 1: Depth of Matching Pattern Wins.
    # A pattern is "deeper" if it matches more leading components of the path_obj's directory part.
    # Example: path_obj = Path("docs/api.md"), pattern "docs/"
    #   pattern_dir_str for "docs/" is "docs".
    #   path_dir_to_check_str for "docs/api.md" is "docs".
    #   "docs" matches "docs". Depth = 1.
    # Example: path_obj = Path("docs/api.md"), pattern "*.md"
    #   pattern_dir_str for "*.md" is ".". Depth = 0.
    # So "docs/" wins.

    if pattern_props.normalized_pattern.endswith('/'):
        # For "docs/", pattern_dir_str should be "docs".
        # For "/", pattern_dir_str should be "" (special case for root).
        # For "**/foo/", pattern_dir_str should be "**/foo".
        pattern_dir_str = pattern_props.normalized_pattern.rstrip('/')
    else: # File pattern
        # For "*.txt", pattern_dir_str should be ".".
        # For "foo/bar.txt", pattern_dir_str should be "foo/bar".
        pattern_dir_str = str(Path(pattern_props.normalized_pattern).parent)

    # If pattern_dir_str is "." (e.g., from "*.txt") or "" (e.g. from "/"),
    # it means the pattern does not specify any path directories to match against path components.
    # So, its contribution to matching depth based on path components is 0.
    if pattern_dir_str == '.' or not pattern_dir_str:
        return 0

    # Determine the directory part of path_obj to compare against pattern_dir_str.
    # If path_obj is 'a/b/c.txt', path_dir_to_check_str is 'a/b'.
    # If path_obj is 'a/b/c/', path_dir_to_check_str is 'a/b/c'.
    # If path_obj is 'file.txt', path_dir_to_check_str is '.'.
    # If path_obj is 'dir/', path_dir_to_check_str is 'dir'.
    path_str = str(path_obj)
    if path_str.endswith('/'):
        path_dir_to_check_obj = Path(path_str.rstrip('/'))
    else:
        path_dir_to_check_obj = path_obj.parent

    path_dir_to_check_str = str(path_dir_to_check_obj)

    # If the path's directory part is '.', it means the path is in the current/root directory.
    # For pattern_dir_str to match this, it must also effectively be empty or match '.'.
    # However, we've already returned 0 if pattern_dir_str is '.' or empty.
    # So, if path_dir_to_check_str is '.', no non-empty pattern_dir_str can match it.
    if path_dir_to_check_str == '.': # path_obj is in root, e.g. "file.txt" -> parent is "."
        # If pattern_dir_str was 'foo', fnmatch.fnmatchcase(".", "foo") would be False.
        return 0

    max_match_depth = 0
    # Path parts for path_dir_to_check_obj. e.g., Path("a/b") -> ("a", "b")
    path_parts = path_dir_to_check_obj.parts
    if not path_parts or path_parts == ('.',): # Should be covered by path_dir_to_check_str == '.'
        return 0

    # Iterate through prefixes of the path's directory part: "a", "a/b", "a/b/c"
    # and see if pattern_dir_str (e.g., "**/b" or "a/b") matches.
    for i in range(len(path_parts)):
        current_path_prefix_obj = Path(*path_parts[:i+1])
        current_path_prefix_str = str(current_path_prefix_obj)

        if fnmatch.fnmatchcase(current_path_prefix_str, pattern_dir_str):
            # If it matches, the depth is the number of segments in current_path_prefix_str
            max_match_depth = len(current_path_prefix_obj.parts)
            # Small optimization: if pattern_dir_str contains no wildcards,
            # and we found a match, this must be the *only* and longest possible match on path prefixes.
            if not any(g in pattern_dir_str for g in ['*', '?', '[']):
                 break
    return max_match_depth

def _compare_specificity(path_obj: Path, pattern_a_props: PatternProperties, pattern_b_props: PatternProperties) -> int:
    depth_a = _calculate_matching_depth(path_obj, pattern_a_props)
    depth_b = _calculate_matching_depth(path_obj, pattern_b_props)
    if depth_a > depth_b: return 1
    if depth_b > depth_a: return -1

    path_str_for_type_check = str(path_obj)
    path_represents_dir = path_str_for_type_check.endswith(os.sep) or path_str_for_type_check.endswith('/')

    if path_represents_dir:
        if pattern_a_props.is_explicit_dir and pattern_b_props.is_glob_dir: return 1
        if pattern_b_props.is_explicit_dir and pattern_a_props.is_glob_dir: return -1
    else:
        if pattern_a_props.is_explicit_file and pattern_b_props.is_glob_file: return 1
        if pattern_b_props.is_explicit_file and pattern_a_props.is_glob_file: return -1

    if not path_represents_dir and pattern_a_props.is_glob_file and pattern_b_props.is_glob_file:
        if pattern_a_props.suffix_parts and pattern_b_props.suffix_parts:
            path_suffixes = [s.lstrip('.') for s in reversed(Path(path_obj.name).suffixes)]
            if not path_suffixes: return 0
            a_match_len = sum(1 for i in range(min(len(pattern_a_props.suffix_parts), len(path_suffixes))) if pattern_a_props.suffix_parts[i] == path_suffixes[i])
            b_match_len = sum(1 for i in range(min(len(pattern_b_props.suffix_parts), len(path_suffixes))) if pattern_b_props.suffix_parts[i] == path_suffixes[i])
            if a_match_len > b_match_len: return 1
            if b_match_len > a_match_len: return -1

    if path_represents_dir:
        if (pattern_a_props.is_explicit_dir or pattern_a_props.is_glob_dir) and \
           (pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file): return 1
        if (pattern_b_props.is_explicit_dir or pattern_b_props.is_glob_dir) and \
           (pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file): return -1
    else:
        if (pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file) and \
           (pattern_b_props.is_explicit_dir or pattern_b_props.is_glob_dir): return 1
        if (pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file) and \
           (pattern_a_props.is_explicit_dir or pattern_a_props.is_glob_dir): return -1
    return 0

def determine_most_specific_pattern(
    patterns_with_indices: List[tuple[str, int]], path_str: str
) -> Optional[tuple[str, int]]:
    path_obj = Path(path_str)
    is_target_path = "dirdigest/utils" in path_str

    if is_target_path:
        logger.debug(f"[DMS_Target] Path: {path_str}")
        logger.debug(f"[DMS_Target] Checking patterns: {patterns_with_indices}")

    matching_pattern_props_list: List[PatternProperties] = []
    for p_str, p_idx in patterns_with_indices:
        match_result = matches_pattern(str(path_obj), p_str)
        if match_result:
            props = _parse_pattern(p_str, p_idx)
            matching_pattern_props_list.append(props)
            if is_target_path: logger.debug(f"[DMS_Target] Pattern '{p_str}' MATCHED. Properties: {props}")
        elif is_target_path and p_str == "**/utils/":
             logger.debug(f"[DMS_Target] Pattern '{p_str}' DID NOT MATCH {path_str}.")

    if not matching_pattern_props_list:
        if is_target_path: logger.debug(f"[DMS_Target] No patterns matched {path_str}.")
        return None
    if len(matching_pattern_props_list) == 1:
        winner_props = matching_pattern_props_list[0]
        if is_target_path: logger.debug(f"[DMS_Target] Single match for {path_str}: {winner_props.raw_pattern}")
        return (winner_props.raw_pattern, winner_props.original_index)

    most_specific_props = matching_pattern_props_list[0]
    if is_target_path: logger.debug(f"[DMS_Target] Initial most specific for {path_str}: {most_specific_props.raw_pattern}")

    for i in range(1, len(matching_pattern_props_list)):
        current_challenger_props = matching_pattern_props_list[i]
        if is_target_path: logger.debug(f"[DMS_Target] Comparing '{most_specific_props.raw_pattern}' with '{current_challenger_props.raw_pattern}' for {path_str}")
        comparison_result = _compare_specificity(path_obj, most_specific_props, current_challenger_props)
        if is_target_path: logger.debug(f"[DMS_Target] Comparison result: {comparison_result}")
        if comparison_result == -1:
            most_specific_props = current_challenger_props
            if is_target_path: logger.debug(f"[DMS_Target] New most specific: {most_specific_props.raw_pattern} (challenger won)")
        elif comparison_result == 0 and current_challenger_props.original_index > most_specific_props.original_index:
            most_specific_props = current_challenger_props
            if is_target_path: logger.debug(f"[DMS_Target] New most specific: {most_specific_props.raw_pattern} (challenger won by index)")
        elif is_target_path and comparison_result != 0 : logger.debug(f"[DMS_Target] Challenger not more specific.")
        elif is_target_path : logger.debug(f"[DMS_Target] Challenger not more specific by index.")

    if is_target_path: logger.debug(f"[DMS_Target] Final MSI for {path_str}: {most_specific_props.raw_pattern}")
    return (most_specific_props.raw_pattern, most_specific_props.original_index)

def matches_pattern(path_str: str, pattern_str: str) -> bool:
    path_obj = Path(path_str)
    norm_pattern = pattern_str.replace(os.sep, "/")
    is_debug_pattern = (pattern_str == "**/utils/" or pattern_str == "docs/")


    if is_debug_pattern:
        logger.debug(f"[MP_Debug Top] Path: '{path_str}', Pattern: '{pattern_str}' (Norm: '{norm_pattern}')")

    if norm_pattern == ".":
        return str(path_obj) == "."

    if norm_pattern.endswith("/"):
        # Dir pattern: "foo/" or "**/foo/"
        base_name_pattern = norm_pattern.rstrip('/') # "foo" or "**/foo"

        # Handle special cases for base_name_pattern if it's empty or "**"
        if not base_name_pattern: # Original pattern was "/"
            # "/" should match items directly in root.
            # Path("file.txt").parent is Path(".") -> True
            # Path("dir/file.txt").parent is Path("dir") -> False
            # Path(".").parent is Path(".") -> True (matches itself)
            # This is a bit tricky. Path(".").match("*") is False.
            # For a pattern of just "/", we match if path_obj has no parent beyond current dir, or is "."
            return str(path_obj.parent) == "." or str(path_obj) == "."

        # Pattern to match the directory itself
        # Path("foo").match("foo") -> True
        # Path("some/foo").match("**/foo") -> True
        if path_obj.match(base_name_pattern):
            if is_debug_pattern: logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' matched AS DIR with '{base_name_pattern}' -> True")
            return True

        # Pattern to match contents within such a directory
        # For "foo/", content_glob is "foo/**"
        # For "**/foo/", content_glob is "**/foo/**"
        # For "**/" (if base_name_pattern became "**"), content_glob is "**/*" or just "**"
        content_glob = ""
        if base_name_pattern == "**": # from pattern like "**/"
            content_glob = "**/*" # Match any item within any directory. Path.match("**") is often too broad.
        elif base_name_pattern.endswith("/**"): # from pattern like "foo/**/"
             content_glob = base_name_pattern + "*" # e.g. foo/**/*
        else:
            content_glob = base_name_pattern + "/**"

        if is_debug_pattern:
             logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}', Testing contents with: '{content_glob}'")

        # current_path_match_result = path_obj.match(content_glob) # Original problematic line
        current_path_match_result = fnmatch.fnmatchcase(str(path_obj), content_glob)

        # Specific debug for failing test cases
        if pattern_str == "docs/" and str(path_obj) == "docs/subdir/file.txt":
            logger.critical(f"SPECIAL_DEBUG Case 1 (expected True): path_obj='{str(path_obj)}', pattern='{pattern_str}', content_glob='{content_glob}', fnmatch.fnmatchcase result='{current_path_match_result}'")
        if pattern_str == "docs/" and str(path_obj) == "other/docs/file.txt":
            logger.critical(f"SPECIAL_DEBUG Case 2 (expected False): path_obj='{str(path_obj)}', pattern='{pattern_str}', content_glob='{content_glob}', fnmatch.fnmatchcase result='{current_path_match_result}'")

        if current_path_match_result:
            if is_debug_pattern: logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' matched AS CONTENT with '{content_glob}' (using fnmatch) -> True")
            if is_debug_pattern: logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' matched AS CONTENT with '{content_glob}' (using fnmatch) -> True")
            return True

        if is_debug_pattern:
             logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' FAILED both checks ('{base_name_pattern}', '{content_glob}' (using fnmatch for content)) -> False")
        return False
    else:
        # File pattern
        # Specific debug for a pattern that might be misbehaving if it's not caught by endswith("/")
        if pattern_str == "docs" and str(path_obj) == "docs/subdir/file.txt": # if pattern was 'docs' not 'docs/'
            path_match_docs_direct = path_obj.match(norm_pattern)
            logger.critical(f"SPECIAL_DEBUG Case 3 (pattern 'docs'): path_obj='{str(path_obj)}', norm_pattern='{norm_pattern}', Path.match result='{path_match_docs_direct}'")

        if is_debug_pattern: # Should not happen if pattern_str is "**/utils/"
             logger.warning(f"[MP_Debug:'{pattern_str}'] Anomaly: pattern ends with / but in file logic. Path: '{path_str}'")
        return path_obj.match(norm_pattern)

def matches_patterns(
    path_str: str, patterns: List[str]
) -> bool:
    for pattern_item in patterns:
        if matches_pattern(path_str, pattern_item):
            return True
    return False

def is_path_hidden(path_obj: Path) -> bool:
    # For is_path_hidden, it should operate on the parts of the path *relative to the scan root*
    # If path_obj is absolute, this might give incorrect results if e.g. /app/.hidden/file
    # but scan root is /app. So, ensure path_obj is relative before checking parts.
    # However, the way it's called in core.py, it receives a relative path object.
    return any(part.startswith(".") for part in path_obj.parts if part not in (".", os.sep))

def _get_pattern_properties(pattern_str: Optional[str], path_obj: Path, original_index: int = -1) -> Optional[PatternProperties]:
    if pattern_str is None: return None
    # path_obj context for _parse_pattern is not strictly used by _parse_pattern for all its fields,
    # but can be relevant for future enhancements or more complex parsing.
    return _parse_pattern(pattern_str, original_index)
