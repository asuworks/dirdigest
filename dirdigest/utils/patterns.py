# dirdigest/utils/patterns.py
import fnmatch
import os
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
    path_part = os.path.dirname(normalized_pattern)
    depth = 0
    if path_part:
        depth = len([seg for seg in path_part.split('/') if seg and seg != '**'])

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
    return match_depth

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
    is_debug_pattern = pattern_str == "**/utils/"

    if is_debug_pattern: # Top-level log for the specific pattern
        logger.debug(f"[matches_pattern DEBUG Top] Testing path '{path_str}' against pattern '{pattern_str}' (norm: '{norm_pattern}')")

    if norm_pattern == ".":
        return str(path_obj) == "."

    if norm_pattern.endswith("/"):
        base_pattern_for_dir_itself = norm_pattern.rstrip("/")
        pattern_for_contents = ""

        if not base_pattern_for_dir_itself : # Original pattern was "/" or "**/", etc.
            if norm_pattern == "/": # Specifically the root pattern "/"
                # Path("foo").match("/") is False. Path(".").match("/") is False.
                # This should match items *directly* in the root.
                # path_obj.parent == Path(".") means it's directly in root.
                # str(path_obj) == "." means it *is* the root.
                # This logic seems more aligned with typical expectations for "/" pattern.
                # However, Path.match doesn't have a direct way for this.
                # `path_obj.match("*")` and `len(path_obj.parts) == 1` (or `str(path_obj.parent) == '.'`)
                # For now, let's keep it simple: "/" matches the root dir "." and its direct children.
                # The previous logic was: `is_in_root = (str(path_obj.parent) == "."); is_root_itself = (str(path_obj) == "."); return is_in_root or is_root_itself`
                # Let's use Path.match for consistency if possible.
                # `Path("file.txt").match("*")` is True. `Path("dir/file.txt").match("*")` is False.
                # This means `pattern = "*"` for direct children.
                # And `Path(".").match(".")` for root itself.
                # This is complex. The `base_dir_pattern + "/**"` approach is more general.
                # If pattern is just "/", base_pattern_for_dir_itself is "". pattern_for_contents would be "/**"
                # Path("foo").match("/**") is True. Path(".").match("/**") is True. This is too broad for "/".
                # Reverting to specific check for "/"
                if pattern_str == "/" or pattern_str == os.sep :
                    is_direct_child_of_root = len(path_obj.parts) == 1 and path_obj.name != "."
                    is_root_itself = str(path_obj) == "."
                    res = is_direct_child_of_root or is_root_itself
                    if is_debug_pattern: logger.debug(f"[matches_pattern DEBUG '**/utils/' -> (should be /)] Special case '/': result={res} for path '{path_str}'")
                    return res
                else: # Was likely "**/"
                    base_pattern_for_dir_itself = "**" # Treat as matching any directory name
                    pattern_for_contents = "**" # And any content within

        elif base_pattern_for_dir_itself == "**": # From pattern "**/"
             pattern_for_contents = "**" # Match anything if base is already globstar
        elif base_pattern_for_dir_itself.endswith("/**"): # e.g. from "foo/**/"
            pattern_for_contents = base_pattern_for_dir_itself
        else:
            pattern_for_contents = base_pattern_for_dir_itself + "/**"

        if is_debug_pattern: # This is for pattern_str == "**/utils/"
            logger.debug(f"[matches_pattern DEBUG for '**/utils/'] Path: '{path_str}', Testing dir itself with: '{base_pattern_for_dir_itself}', Testing contents with: '{pattern_for_contents}'")

        # Case 1: Path IS the directory itself.
        # Path("dirdigest/utils").match("**/utils") should be True.
        match_as_dir_itself = path_obj.match(base_pattern_for_dir_itself)
        if match_as_dir_itself:
            if is_debug_pattern: logger.debug(f"[matches_pattern DEBUG for '**/utils/'] Path: '{path_str}' matched AS DIR with '{base_pattern_for_dir_itself}' -> True")
            return True

        # Case 2: Path is INSIDE the directory.
        # Path("dirdigest/utils/patterns.py").match("**/utils/**") should be True.
        match_as_content = path_obj.match(pattern_for_contents)
        if match_as_content:
            if is_debug_pattern: logger.debug(f"[matches_pattern DEBUG for '**/utils/'] Path: '{path_str}' matched AS CONTENT with '{pattern_for_contents}' -> True")
            return True

        if is_debug_pattern:
            logger.debug(f"[matches_pattern DEBUG for '**/utils/'] Path: '{path_str}' did NOT match dir ('{base_pattern_for_dir_itself}' -> {match_as_dir_itself}) or contents ('{pattern_for_contents}' -> {match_as_content}) -> False")
        return False
    else: # Regular file pattern
        if pattern_str == "**/utils/": # Should not happen for "**/utils/" as it ends with /
             logger.warning(f"[matches_pattern DEBUG '**/utils/'] Anomaly: pattern ends with / but reached non-dir logic. Path: '{path_str}'")
        return path_obj.match(norm_pattern)

def matches_patterns(
    path_str: str, patterns: List[str]
) -> bool:
    for pattern_item in patterns:
        if matches_pattern(path_str, pattern_item):
            return True
    return False

def is_path_hidden(path_obj: Path) -> bool:
    return any(part.startswith(".") for part in path_obj.parts if part not in (".", os.sep))

def _get_pattern_properties(pattern_str: Optional[str], path_obj: Path, original_index: int = -1) -> Optional[PatternProperties]:
    if pattern_str is None: return None
    return _parse_pattern(pattern_str, original_index)
