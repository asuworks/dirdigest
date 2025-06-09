# dirdigest/utils/patterns.py
import fnmatch
import os
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple
from dirdigest.utils.logger import logger

class PatternProperties(NamedTuple):
    raw_pattern: str
    normalized_pattern: str
    depth: int
    is_explicit_file: bool
    is_explicit_dir: bool
    is_glob_file: bool
    is_glob_dir: bool
    suffix_parts: Optional[List[str]]
    original_index: int
    pattern_dir_str: str # Directory part of the pattern, normalized (e.g. "." -> "")

def _parse_pattern(pattern_str: str, original_index: int) -> PatternProperties:
    raw_pattern = pattern_str
    normalized_pattern = pattern_str.replace(os.sep, "/")

    temp_pattern_for_depth = normalized_pattern
    if temp_pattern_for_depth.endswith('/'):
        temp_pattern_for_depth = temp_pattern_for_depth.rstrip('/')

    if not temp_pattern_for_depth: # Handles case of "/"
        depth = 0
    else:
        depth_segments = [seg for seg in temp_pattern_for_depth.split('/') if seg and seg != '**']
        depth = len(depth_segments)

    is_explicit_dir = False
    is_glob_dir = False
    is_explicit_file = False
    is_glob_file = False
    current_pattern_dir_str = ""

    if normalized_pattern.endswith("/"):
        # Pattern is for a directory, e.g., "foo/bar/" or "**/baz/"
        dir_part_for_glob_check = normalized_pattern.rstrip('/')
        has_glob_chars_in_dir_defining_part = any(g in dir_part_for_glob_check for g in ['*', '?', '['])
        is_explicit_dir = not has_glob_chars_in_dir_defining_part
        is_glob_dir = has_glob_chars_in_dir_defining_part
        current_pattern_dir_str = dir_part_for_glob_check
    else:
        # Pattern is for a file, e.g., "foo/bar.txt" or "*.log"
        has_glob_chars_in_full_pattern = any(g in normalized_pattern for g in ['*', '?', '['])
        is_explicit_file = not has_glob_chars_in_full_pattern
        is_glob_file = has_glob_chars_in_full_pattern

        parent_dir_str = str(Path(normalized_pattern).parent)
        current_pattern_dir_str = "" if parent_dir_str == "." else parent_dir_str


    suffix_parts = None
    if not normalized_pattern.endswith("/"): # File pattern
        filename_component = Path(normalized_pattern).name
        # Path("*.txt").suffixes -> ['.txt']
        # Path("file.tar.gz").suffixes -> ['.tar', '.gz']
        suffixes = Path(filename_component).suffixes
        if suffixes:
            suffix_parts = [s.lstrip('.') for s in reversed(suffixes)] # e.g. ['gz', 'tar']

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
        pattern_dir_str=current_pattern_dir_str
    )

def _calculate_matching_depth(path_obj: Path, pattern_props: PatternProperties) -> int:
    pattern_dir_str_from_props = pattern_props.pattern_dir_str

    if not pattern_dir_str_from_props: # Empty string means root or no specific dir (e.g. for "*.txt" or "/")
        return 0

    path_str_val = str(path_obj)

    # Determine the directory part of path_obj that we are comparing against.
    # If path_obj is 'a/b/c/', path_dir_to_check_obj is Path('a/b/c').
    # If path_obj is 'a/b/c.txt', path_dir_to_check_obj is Path('a/b').
    # If path_obj is 'file.txt' (root), path_dir_to_check_obj is Path('.').
    if path_str_val.endswith('/'):
        path_dir_to_check_obj = Path(path_str_val.rstrip('/'))
    else:
        path_dir_to_check_obj = path_obj.parent

    path_dir_to_check_str = str(path_dir_to_check_obj)

    if path_dir_to_check_str == '.': # Path itself is in root relative to scan base.
        # A non-empty pattern_dir_str_from_props (like "foo") cannot match directory "."
        return 0

    max_match_depth = 0
    path_parts = path_dir_to_check_obj.parts
    if not path_parts or (len(path_parts) == 1 and path_parts[0] == "."): # Should be caught by path_dir_to_check_str == '.'
        return 0

    # Iterate through prefixes of the path's directory part: e.g., for "a/b/c", check "a", then "a/b", then "a/b/c"
    for i in range(len(path_parts)):
        current_path_prefix_obj = Path(*path_parts[:i+1])
        current_path_prefix_str = str(current_path_prefix_obj)

        if fnmatch.fnmatchcase(current_path_prefix_str, pattern_dir_str_from_props):
            max_match_depth = len(current_path_prefix_obj.parts)
            # Optimization: if pattern_dir_str has no wildcards, this must be the only and longest match
            if not any(g in pattern_dir_str_from_props for g in ['*', '?', '[']):
                 break
    return max_match_depth

def _compare_specificity(path_obj: Path, pattern_a_props: PatternProperties, pattern_b_props: PatternProperties, path_is_known_dir: bool) -> int:
    # Targeted Rule 0: For files, '.*' (as a filename-level pattern) wins over directory-focused patterns.
    if not path_is_known_dir:  # Path is a file
        md_a_for_rule0 = _calculate_matching_depth(path_obj, pattern_a_props)
        md_b_for_rule0 = _calculate_matching_depth(path_obj, pattern_b_props)

        is_pattern_a_dotstar = pattern_a_props.raw_pattern == ".*"
        is_pattern_b_dotstar = pattern_b_props.raw_pattern == ".*"

        if is_pattern_a_dotstar and md_a_for_rule0 == 0 and md_b_for_rule0 > 0:
            logger.debug(f"Targeted Rule 0: PatA '{pattern_a_props.raw_pattern}' (as '.*') wins over PatB '{pattern_b_props.raw_pattern}' (dir-focused) for file '{path_obj}'")
            return 1
        if is_pattern_b_dotstar and md_b_for_rule0 == 0 and md_a_for_rule0 > 0:
            logger.debug(f"Targeted Rule 0: PatB '{pattern_b_props.raw_pattern}' (as '.*') wins over PatA '{pattern_a_props.raw_pattern}' (dir-focused) for file '{path_obj}'")
            return -1

    # --- "Logic Prime" rules follow ---
    md_a = _calculate_matching_depth(path_obj, pattern_a_props)
    md_b = _calculate_matching_depth(path_obj, pattern_b_props)

    # Rule 1 (LP): Path Match Depth
    if md_a != md_b:
        logger.debug(f"Rule 1 (Path Match Depth): PatA '{pattern_a_props.raw_pattern}' (md:{md_a}) vs PatB '{pattern_b_props.raw_pattern}' (md:{md_b}). Winner: {'A' if md_a > md_b else 'B'}")
        return 1 if md_a > md_b else -1

    # Rule 1.5 (LP - Explicitness of Directory Part):
    dir_str_a = pattern_a_props.pattern_dir_str
    dir_str_b = pattern_b_props.pattern_dir_str

    a_has_globstar_in_dir = "**" in dir_str_a
    b_has_globstar_in_dir = "**" in dir_str_b
    if a_has_globstar_in_dir != b_has_globstar_in_dir:
        logger.debug(f"Rule 1.5 (Dir Explicitness - Globstar): PatA '{pattern_a_props.raw_pattern}' (has_globstar:{a_has_globstar_in_dir}) vs PatB '{pattern_b_props.raw_pattern}' (has_globstar:{b_has_globstar_in_dir}). Winner: {'B' if a_has_globstar_in_dir else 'A'}")
        return -1 if a_has_globstar_in_dir else 1 # No globstar wins

    a_dir_glob_count = sum(dir_str_a.count(g) for g in ['*', '?'])
    b_dir_glob_count = sum(dir_str_b.count(g) for g in ['*', '?'])
    if a_dir_glob_count != b_dir_glob_count:
        logger.debug(f"Rule 1.5 (Dir Explicitness - Glob Count): PatA '{pattern_a_props.raw_pattern}' (glob_count:{a_dir_glob_count}) vs PatB '{pattern_b_props.raw_pattern}' (glob_count:{b_dir_glob_count}). Winner: {'B' if a_dir_glob_count > b_dir_glob_count else 'A'}")
        return -1 if a_dir_glob_count > b_dir_glob_count else 1 # Fewer globs win

    if len(dir_str_a) != len(dir_str_b): # Longer literal dir part wins
        logger.debug(f"Rule 1.5 (Dir Explicitness - Length): PatA '{pattern_a_props.raw_pattern}' (len:{len(dir_str_a)}) vs PatB '{pattern_b_props.raw_pattern}' (len:{len(dir_str_b)}). Winner: {'A' if len(dir_str_a) > len(dir_str_b) else 'B'}")
        return 1 if len(dir_str_a) > len(dir_str_b) else -1

    # Rule 2 (LP - was Rule 3): Structural Pattern Depth
    if pattern_a_props.depth != pattern_b_props.depth:
        logger.debug(f"Rule 2 (Structural Depth): PatA '{pattern_a_props.raw_pattern}' (pdepth:{pattern_a_props.depth}) vs PatB '{pattern_b_props.raw_pattern}' (pdepth:{pattern_b_props.depth}). Winner: {'A' if pattern_a_props.depth > pattern_b_props.depth else 'B'}")
        return 1 if pattern_a_props.depth > pattern_b_props.depth else -1

    # Rule 3 (LP - was Rule 4): Explicit final component vs Glob final component
    a_is_explicit_final_comp = pattern_a_props.is_explicit_dir if path_is_known_dir else pattern_a_props.is_explicit_file
    b_is_explicit_final_comp = pattern_b_props.is_explicit_dir if path_is_known_dir else pattern_b_props.is_explicit_file
    a_is_glob_final_comp = pattern_a_props.is_glob_dir if path_is_known_dir else pattern_a_props.is_glob_file
    b_is_glob_final_comp = pattern_b_props.is_glob_dir if path_is_known_dir else pattern_b_props.is_glob_file

    if a_is_explicit_final_comp and b_is_glob_final_comp:
        logger.debug(f"Rule 3 (Explicit Final Comp): PatA '{pattern_a_props.raw_pattern}' (explicit) wins over PatB '{pattern_b_props.raw_pattern}' (glob).")
        return 1
    if b_is_explicit_final_comp and a_is_glob_final_comp:
        logger.debug(f"Rule 3 (Explicit Final Comp): PatB '{pattern_b_props.raw_pattern}' (explicit) wins over PatA '{pattern_a_props.raw_pattern}' (glob).")
        return -1

    # Rule 4 (LP - was Rule 5): Suffix Proximity
    if not path_is_known_dir and (pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file) and \
       (pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file):
        if pattern_a_props.suffix_parts and not pattern_b_props.suffix_parts: return 1
        if not pattern_a_props.suffix_parts and pattern_b_props.suffix_parts: return -1
        if pattern_a_props.suffix_parts and pattern_b_props.suffix_parts:
            path_suffixes = [s.lstrip('.') for s in reversed(Path(path_obj.name).suffixes)]
            if path_suffixes:
                a_match_len = sum(1 for i in range(min(len(pattern_a_props.suffix_parts), len(path_suffixes))) if pattern_a_props.suffix_parts[i] == path_suffixes[i])
                b_match_len = sum(1 for i in range(min(len(pattern_b_props.suffix_parts), len(path_suffixes))) if pattern_b_props.suffix_parts[i] == path_suffixes[i])
                if a_match_len != b_match_len:
                    logger.debug(f"Rule 4 (Suffix Proximity by match len): PatA '{pattern_a_props.raw_pattern}' (len:{a_match_len}) vs PatB '{pattern_b_props.raw_pattern}' (len:{b_match_len}). Winner: {'A' if a_match_len > b_match_len else 'B'}")
                    return 1 if a_match_len > b_match_len else -1
            # If no path_suffixes or match lengths are equal, this rule doesn't decide.
            # The prompt's original suffix rule also considered length of suffix_parts list.
            if len(pattern_a_props.suffix_parts) != len(pattern_b_props.suffix_parts):
                logger.debug(f"Rule 4 (Suffix Proximity by num parts): PatA '{pattern_a_props.raw_pattern}' vs PatB '{pattern_b_props.raw_pattern}'. Winner: {'A' if len(pattern_a_props.suffix_parts) > len(pattern_b_props.suffix_parts) else 'B'}")
                return 1 if len(pattern_a_props.suffix_parts) > len(pattern_b_props.suffix_parts) else -1

    # Rule 5 (LP - was Rule 6): Pattern type vs. Path type
    is_a_dir_type = pattern_a_props.is_explicit_dir or pattern_a_props.is_glob_dir
    is_a_file_type = pattern_a_props.is_explicit_file or pattern_a_props.is_glob_file
    is_b_dir_type = pattern_b_props.is_explicit_dir or pattern_b_props.is_glob_dir
    is_b_file_type = pattern_b_props.is_explicit_file or pattern_b_props.is_glob_file

    if path_is_known_dir:
        if is_a_dir_type and not is_b_dir_type:
            logger.debug(f"Rule 5 (Type Match): PatA '{pattern_a_props.raw_pattern}' (dir-type) wins for dir path")
            return 1
        if not is_a_dir_type and is_b_dir_type:
            logger.debug(f"Rule 5 (Type Match): PatB '{pattern_b_props.raw_pattern}' (dir-type) wins for dir path")
            return -1
    else: # Path is a file
        if is_a_file_type and not is_b_file_type:
            logger.debug(f"Rule 5 (Type Match): PatA '{pattern_a_props.raw_pattern}' (file-type) wins for file path")
            return 1
        if not is_a_file_type and is_b_file_type:
            logger.debug(f"Rule 5 (Type Match): PatB '{pattern_b_props.raw_pattern}' (file-type) wins for file path")
            return -1

    logger.debug(f"All rules exhausted or equal for PatA '{pattern_a_props.raw_pattern}' vs PatB '{pattern_b_props.raw_pattern}'. Returning 0.")
    return 0

def determine_most_specific_pattern(
    patterns_with_indices: List[tuple[str, int]], path_str: str
) -> Optional[tuple[str, int]]:
    path_obj = Path(path_str)
    path_is_known_dir = path_str.endswith(os.sep) or path_str.endswith('/')

    is_target_path = "utils" in path_str or "common_utils" in path_str or "feature_utils" in path_str

    if is_target_path:
        logger.debug(f"[DMS_Target] Path: {path_str}, path_is_known_dir: {path_is_known_dir}")
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
        comparison_result = _compare_specificity(path_obj, most_specific_props, current_challenger_props, path_is_known_dir)
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
        base_name_pattern = norm_pattern.rstrip('/')
        if not base_name_pattern:
            return str(path_obj.parent) == "." or str(path_obj) == "."
        if path_obj.match(base_name_pattern):
            if is_debug_pattern: logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' matched AS DIR with '{base_name_pattern}' -> True")
            return True
        content_glob = ""
        if base_name_pattern == "**":
            content_glob = "**/*"
        elif base_name_pattern.endswith("/**"):
             content_glob = base_name_pattern + "*"
        else:
            content_glob = base_name_pattern + "/**"
        if is_debug_pattern:
             logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}', Testing contents with: '{content_glob}'")
        current_path_match_result = fnmatch.fnmatchcase(str(path_obj), content_glob)
        if current_path_match_result:
            if is_debug_pattern: logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' matched AS CONTENT with '{content_glob}' (using fnmatch) -> True")
            return True
        if is_debug_pattern:
             logger.debug(f"[MP_Debug:'{pattern_str}'] Path '{path_str}' FAILED both checks ('{base_name_pattern}', '{content_glob}' (using fnmatch for content)) -> False")
        return False
    else: # File pattern
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
