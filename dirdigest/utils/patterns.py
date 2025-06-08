# dirdigest/utils/patterns.py
import fnmatch
import os
from pathlib import Path
from typing import List, Optional


def _calculate_specificity_score(pattern_str: str) -> int:
    """
    Calculates a specificity score for a given pattern string.
    Higher score means more specific.
    Simple formula: length - wildcard_penalties + depth_bonus.
    """
    pattern = pattern_str.strip().replace(os.sep, "/") # Normalize separators

    score = len(pattern)
    score -= pattern.count("*") * 5
    score -= pattern.count("?") * 3
    score += pattern.count("/") * 10

    return score


def compare_specificity(pattern1_str: str, pattern2_str: str) -> int:
    """
    Compares two pattern strings for specificity using _calculate_specificity_score.
    Returns:
        1 if pattern1_str is more specific than pattern2_str.
        -1 if pattern2_str is more specific than pattern1_str.
        0 if they have equal specificity based on the scoring.
    """
    score1 = _calculate_specificity_score(pattern1_str)
    score2 = _calculate_specificity_score(pattern2_str)

    if score1 > score2:
        return 1
    elif score2 > score1:
        return -1
    else:
        return 0


def get_most_specific_pattern(path_str: str, patterns: List[str]) -> Optional[str]:
    """
    Given a path_str and a list of patterns, returns the most specific pattern that matches the path.
    1. Filters the input `patterns` to only those that actually match `path_str`.
    2. If the `path_str` itself is an exact match to one of these filtered patterns, it wins.
    3. Otherwise, the matching pattern with the highest specificity score wins.
    4. If scores are tied, the one appearing last in the *original* `patterns` list wins.
    """
    if not patterns:
        return None

    normalized_path_str = path_str.strip().replace(os.sep, "/")

    actual_matching_patterns_info = []
    for i, p_orig in enumerate(patterns):
        p_norm = p_orig.strip().replace(os.sep, "/")
        if matches_pattern(normalized_path_str, p_norm):
            actual_matching_patterns_info.append({
                "original": p_orig,
                "normalized": p_norm,
                "original_index": i,
                "score": _calculate_specificity_score(p_norm)
            })

    if not actual_matching_patterns_info:
        return None

    # Rule 2: Exact path string match is highest priority
    for entry in actual_matching_patterns_info:
        if entry["normalized"] == normalized_path_str:
            return entry["original"]

    # Rule 3 & 4: Find the highest scoring pattern, last one (by original index) wins on tie
    actual_matching_patterns_info.sort(key=lambda e: (e["score"], e["original_index"]), reverse=True)

    return actual_matching_patterns_info[0]["original"]


def matches_pattern(path_str: str, pattern_str: str) -> bool:
    """
    Checks if the given path_str matches the pattern_str.
    """
    path_obj = Path(path_str.replace(os.sep, "/")) # path_str is already normalized by caller
    norm_pattern = pattern_str.strip().replace(os.sep, "/") # pattern_str is already normalized by caller

    # Case 1: Pattern targets a directory (ends with "/")
    if norm_pattern.endswith("/"):
        dir_target_name_pattern = norm_pattern.rstrip("/")
        if path_str == dir_target_name_pattern or path_str.startswith(norm_pattern):
            return True
        if dir_target_name_pattern.startswith("**/"): # e.g. **/node_modules/
            actual_name_to_find_in_parts = dir_target_name_pattern[3:]
            for part in path_obj.parts:
                if fnmatch.fnmatch(part, actual_name_to_find_in_parts):
                    return True
        return False
    # Case 2: Pattern targets a file or a path not explicitly ending in "/"
    else:
        if norm_pattern.startswith("**/"): # e.g. "**/file.py" or "**/*.log"
            file_target_basename_pattern = norm_pattern[3:]
            return fnmatch.fnmatch(path_obj.name, file_target_basename_pattern)
        else: # e.g., "*.py", "file.py", "some_dir/*.txt"
            if "/" not in norm_pattern: # Simple pattern like "*.txt" or "file.py"
                return path_obj.match(norm_pattern) # Match against filename part
            else: # Pattern includes path separators, e.g., "dir/*.py"
                return fnmatch.fnmatch(path_str, norm_pattern) # Use path_str directly as it's already normalized


def matches_patterns(
    path_str: str, patterns: List[str]
) -> bool:
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
    return any(part.startswith(".") for part in path_obj.parts if part not in (".", os.sep))
