# dirdigest/dirdigest/core.py
import os
import pathlib
from typing import Any, Dict, Generator, Iterator, List, Tuple, Optional

from dirdigest.constants import DEFAULT_IGNORE_PATTERNS
from dirdigest.utils.logger import logger
from dirdigest.utils.patterns import (
    is_path_hidden,
    matches_pattern, # Changed from matches_patterns to matches_pattern for single pattern checks
    get_most_specific_pattern,
    _calculate_specificity_score # Now imported for direct use
)

# Type hints
LogEvent = Dict[str, Any]
DigestItemNode = Dict[str, Any]
ProcessedItemPayload = Dict[str, Any]
ProcessedItem = Tuple[pathlib.Path, str, ProcessedItemPayload]
TraversalStats = Dict[str, int]


def _get_dir_size(dir_path_obj: pathlib.Path, follow_symlinks: bool) -> float:
    total_size_bytes = 0
    try:
        for root, _, files in os.walk(str(dir_path_obj), topdown=True, followlinks=follow_symlinks):
            for name in files:
                file_path = pathlib.Path(root) / name
                if not follow_symlinks and file_path.is_symlink():
                    continue
                try:
                    total_size_bytes += file_path.stat().st_size
                except OSError as e:
                    logger.warning(f"Could not get size for {file_path}: {e}")
    except OSError as e:
        logger.warning(f"Could not walk directory {dir_path_obj} for size calculation: {e}")
    return round(total_size_bytes / 1024, 3)


def process_directory_recursive(
    base_dir_path: pathlib.Path,
    include_patterns: List[str],
    exclude_patterns: List[str],
    no_default_ignore: bool,
    max_depth: int | None,
    follow_symlinks: bool,
    max_size_kb: int,
    ignore_read_errors: bool,
) -> Tuple[Generator[ProcessedItem, None, None], TraversalStats, List[LogEvent]]:
    stats: TraversalStats = {"included_files_count": 0, "excluded_items_count": 0}
    log_events: List[LogEvent] = []
    max_size_bytes = max_size_kb * 1024

    # For efficient lookups if needed, though get_most_specific_pattern works on lists
    # include_patterns_set = set(include_patterns)
    # exclude_patterns_set = set(exclude_patterns)

    logger.debug(f"Core: Max size KB: {max_size_kb}, Ignore read errors: {ignore_read_errors}")
    logger.debug(f"Core: Follow symlinks: {follow_symlinks}, No default ignore: {no_default_ignore}")

    def _traverse() -> Generator[ProcessedItem, None, None]:
        for root, dirs_orig, files_orig in os.walk(str(base_dir_path), topdown=True, followlinks=follow_symlinks):
            current_root_path = pathlib.Path(root)
            relative_root_path = current_root_path.relative_to(base_dir_path)
            current_depth = len(relative_root_path.parts) if relative_root_path != pathlib.Path(".") else 0

            # --- Process Files ---
            for file_name in files_orig:
                file_path_obj = current_root_path / file_name
                relative_file_path = relative_root_path / file_name
                relative_file_path_str = str(relative_file_path)

                # Initialization for file processing
                user_decision_is_include_file: Optional[bool] = None
                reason_file_activity: str = ""
                msi_pattern_str_file: Optional[str] = None
                mse_pattern_str_file: Optional[str] = None

                final_is_included_file: bool = False # Default to exclusion
                final_reason_file: str = ""
                current_file_size_kb = 0.0
                initial_check_excluded_file = False

                try:
                    # Size calculation should happen regardless of symlink status if follow_symlinks is true for symlinks
                    # However, if not following, symlink size is effectively 0 for content purposes here.
                    if file_path_obj.is_symlink() and not follow_symlinks:
                        current_file_size_kb = 0.0
                    else:
                        current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")
                    # If stat fails, treat as 0 size for now, might be excluded later if read error matters

                # 1. Initial Checks (File)
                if not follow_symlinks and file_path_obj.is_symlink():
                    final_is_included_file = False
                    final_reason_file = f"Is a symlink (symlink following disabled): {relative_file_path_str}"
                    initial_check_excluded_file = True

                if not initial_check_excluded_file:
                    # 2. Pattern Matching & MSI/MSE Determination (File)
                    matching_user_includes_file = [p for p in include_patterns if matches_pattern(relative_file_path_str, p)]
                    matching_user_excludes_file = [p for p in exclude_patterns if matches_pattern(relative_file_path_str, p)]
                    msi_pattern_str_file = get_most_specific_pattern(relative_file_path_str, matching_user_includes_file)
                    mse_pattern_str_file = get_most_specific_pattern(relative_file_path_str, matching_user_excludes_file)

                    # 3. User Rule Decision Logic (File)
                    # A. Exact Pattern Conflict
                    if msi_pattern_str_file is not None and msi_pattern_str_file == mse_pattern_str_file:
                        raise ValueError(f"Pattern '{msi_pattern_str_file}' is specified in both include and exclude rules for path '{relative_file_path_str}'.")

                    # B. Mixed Type Heuristic & Specificity Comparison
                    if msi_pattern_str_file and mse_pattern_str_file:
                        # For files, the "mixed type heuristic" (dir-like vs file-glob) is less direct.
                        # A pattern like "docs/" (dir-like) vs "*.md" (file-glob) for path "docs/README.md" is resolved by specificity.
                        # The prompt's heuristic seems more for when a dir include might interact with a file exclude for a file *within* that dir.
                        # Here, both msi_pattern_str_file and mse_pattern_str_file are patterns matched against a *file path*.
                        # The get_most_specific_pattern already handles depth and explicitness.
                        # The heuristic described (dir-like include vs file-glob exclude) is more about tree traversal decisions for parent dirs.
                        # For a file path, we directly compare the specificity of the patterns that matched it.

                        score_msi = _calculate_specificity_score(msi_pattern_str_file)
                        score_mse = _calculate_specificity_score(mse_pattern_str_file)

                        if score_msi > score_mse:
                            user_decision_is_include_file = True
                            reason_file_activity = f"Include pattern '{msi_pattern_str_file}' (score {score_msi}) is more specific than exclude pattern '{mse_pattern_str_file}' (score {score_mse})"
                        elif score_mse > score_msi:
                            user_decision_is_include_file = False
                            reason_file_activity = f"Exclude pattern '{mse_pattern_str_file}' (score {score_mse}) is more specific than include pattern '{msi_pattern_str_file}' (score {score_msi})"
                        else: # score_msi == score_mse
                            raise ValueError(f"Include pattern '{msi_pattern_str_file}' and exclude pattern '{mse_pattern_str_file}' have equal specificity for path '{relative_file_path_str}'. Please refine your rules.")
                    # C. Only MSI or MSE Exists
                    elif msi_pattern_str_file:
                        user_decision_is_include_file = True
                        reason_file_activity = f"Matches user-specified include pattern: {msi_pattern_str_file}"
                    elif mse_pattern_str_file:
                        user_decision_is_include_file = False
                        reason_file_activity = f"Matches user-specified exclude pattern: {mse_pattern_str_file}"

                    # 4. Default Ignore Logic & Final Decision (File)
                    final_is_included_file = user_decision_is_include_file
                    final_reason_file = reason_file_activity

                    if final_is_included_file is None: # No user pattern decided
                        if not no_default_ignore:
                            matching_default_excludes_file = []
                            is_hidden = is_path_hidden(relative_file_path)
                            if is_hidden:
                                matching_default_excludes_file.append(relative_file_path_str) # Hidden file is like an exact path default exclude
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_file_path_str, p_def):
                                    matching_default_excludes_file.append(p_def)

                            msde_pattern_str_file = get_most_specific_pattern(relative_file_path_str, matching_default_excludes_file)

                            if msde_pattern_str_file:
                                final_is_included_file = False
                                if msde_pattern_str_file == relative_file_path_str and is_hidden: # Check if it was the hidden self-match
                                    final_reason_file = f"Is a hidden file: {relative_file_path_str}"
                                else:
                                    final_reason_file = f"Matches default ignore pattern: {msde_pattern_str_file}"
                            else: # No user rules, no default ignores matched
                                if include_patterns:
                                    final_is_included_file = False
                                    final_reason_file = f"Does not match any user-specified include pattern: {relative_file_path_str}"
                                else:
                                    final_is_included_file = True
                                    final_reason_file = f"Included by default: {relative_file_path_str}"
                        else: # Default ignores are disabled
                            if include_patterns:
                                final_is_included_file = False
                                final_reason_file = f"Does not match any user-specified include pattern (default ignores disabled): {relative_file_path_str}"
                            else:
                                final_is_included_file = True
                                final_reason_file = f"Included by default (default ignores disabled): {relative_file_path_str}"
                    elif final_is_included_file is True: # User include decided, check if it overrides a default exclude
                        if not no_default_ignore and msi_pattern_str_file: # msi_pattern_str_file must exist if final_is_included_file was True from user rules
                            matching_default_excludes_file = []
                            is_hidden = is_path_hidden(relative_file_path)
                            if is_hidden:
                                matching_default_excludes_file.append(relative_file_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_file_path_str, p_def):
                                    matching_default_excludes_file.append(p_def)

                            msde_pattern_str_file_check = get_most_specific_pattern(relative_file_path_str, matching_default_excludes_file)

                            if msde_pattern_str_file_check:
                                score_msi = _calculate_specificity_score(msi_pattern_str_file)
                                score_msde = _calculate_specificity_score(msde_pattern_str_file_check)
                                if score_msde > score_msi:
                                    final_is_included_file = False
                                    final_reason_file = f"Default ignore pattern '{msde_pattern_str_file_check}' (score {score_msde}) overrides user include '{msi_pattern_str_file}' (score {score_msi})"
                                else:
                                    final_reason_file += f" (overrides default pattern: {msde_pattern_str_file_check})"
                # End of `if not initial_check_excluded_file:`

                # 5. Post-Decision Checks (Files)
                file_attributes: ProcessedItemPayload = {}
                if final_is_included_file: # Ensure it's boolean true
                    file_attributes["size_kb"] = current_file_size_kb
                    if current_file_size_kb * 1024 > max_size_bytes:
                        final_is_included_file = False
                        final_reason_file = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB): {relative_file_path_str}"
                    else:
                        try:
                            # Symlinks that are followed might still be broken, or other OS errors
                            if file_path_obj.is_symlink() and not file_path_obj.exists(): # Broken symlink after deciding to follow
                                raise OSError(f"Broken symbolic link: {relative_file_path_str}")
                            with file_path_obj.open("r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                        except (OSError, UnicodeDecodeError) as e:
                            error_reason_str = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                final_is_included_file = False
                                final_reason_file = f"Read error ({error_reason_str}): {relative_file_path_str}"
                            else:
                                file_attributes["content"] = None # Still "included" but content is null
                                file_attributes["read_error"] = error_reason_str
                                final_reason_file += f" (read error ignored: {error_reason_str})" # Append to existing reason

                # 6. Logging and Stats for Files
                if final_is_included_file:
                    stats["included_files_count"] += 1
                    log_events.append({
                        "path": relative_file_path_str, "item_type": "file", "status": "included",
                        "size_kb": current_file_size_kb, "reason": final_reason_file
                    })
                    yield (relative_file_path, "file", file_attributes)
                else:
                    stats["excluded_items_count"] += 1
                    log_events.append({
                        "path": relative_file_path_str, "item_type": "file", "status": "excluded",
                        "size_kb": current_file_size_kb, "reason": final_reason_file
                    })

            # --- Process Directories ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks) # Size for logging, not decision

                # Initialization for directory processing
                user_decision_is_include_dir: Optional[bool] = None
                reason_dir_activity: str = "" # This will be the user_reason for directory
                msi_pattern_str_dir: Optional[str] = None
                mse_pattern_str_dir: Optional[str] = None

                final_is_included_for_traversal: bool = False # Default to exclusion for traversal
                final_reason_dir_activity: str = ""
                initial_check_excluded_dir = False

                # 1. Initial Checks (Directory)
                if max_depth is not None and current_depth >= max_depth:
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Exceeds max depth: {relative_dir_path_str}"
                    initial_check_excluded_dir = True
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Is a symlink (symlink following disabled): {relative_dir_path_str}"
                    initial_check_excluded_dir = True

                if not initial_check_excluded_dir:
                    # 2. Pattern Matching & MSI/MSE Determination (Directory)
                    matching_user_includes_dir = [p for p in include_patterns if matches_pattern(relative_dir_path_str, p)]
                    matching_user_excludes_dir = [p for p in exclude_patterns if matches_pattern(relative_dir_path_str, p)]
                    msi_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_includes_dir)
                    mse_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_excludes_dir)

                    # 3. User Rule Decision Logic (Directory) - Simplified for directories as they don't have "file type"
                    # A. Exact Pattern Conflict
                    if msi_pattern_str_dir is not None and msi_pattern_str_dir == mse_pattern_str_dir:
                        raise ValueError(f"Pattern '{msi_pattern_str_dir}' is specified in both include and exclude rules for directory '{relative_dir_path_str}'.")

                    # B. Specificity Comparison (No Mixed Type Heuristic needed as patterns matching a dir are generally dir-like)
                    if msi_pattern_str_dir and mse_pattern_str_dir:
                        score_msi = _calculate_specificity_score(msi_pattern_str_dir)
                        score_mse = _calculate_specificity_score(mse_pattern_str_dir)
                        if score_msi > score_mse:
                            user_decision_is_include_dir = True
                            reason_dir_activity = f"Include pattern '{msi_pattern_str_dir}' (score {score_msi}) is more specific than exclude pattern '{mse_pattern_str_dir}' (score {score_mse})"
                        elif score_mse > score_msi:
                            user_decision_is_include_dir = False
                            reason_dir_activity = f"Exclude pattern '{mse_pattern_str_dir}' (score {score_mse}) is more specific than include pattern '{msi_pattern_str_dir}' (score {score_msi})"
                        else: # score_msi == score_mse
                            raise ValueError(f"Include pattern '{msi_pattern_str_dir}' and exclude pattern '{mse_pattern_str_dir}' have equal specificity for directory '{relative_dir_path_str}'. Please refine your rules.")
                    # C. Only MSI or MSE Exists
                    elif msi_pattern_str_dir:
                        user_decision_is_include_dir = True
                        reason_dir_activity = f"Matches user-specified include pattern: {msi_pattern_str_dir}"
                    elif mse_pattern_str_dir:
                        user_decision_is_include_dir = False
                        reason_dir_activity = f"Matches user-specified exclude pattern: {mse_pattern_str_dir}"

                    # 4. Default Ignore Logic & Final Decision (Directory)
                    final_is_included_for_traversal = user_decision_is_include_dir
                    final_reason_dir_activity = reason_dir_activity

                    if final_is_included_for_traversal is None: # No user pattern decided
                        if not no_default_ignore:
                            matching_default_excludes_dir = []
                            is_hidden = is_path_hidden(relative_dir_path)
                            if is_hidden:
                                matching_default_excludes_dir.append(relative_dir_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_dir_path_str, p_def):
                                    matching_default_excludes_dir.append(p_def)

                            msde_pattern_str_default_dir = get_most_specific_pattern(relative_dir_path_str, matching_default_excludes_dir)

                            if msde_pattern_str_default_dir:
                                final_is_included_for_traversal = False
                                if msde_pattern_str_default_dir == relative_dir_path_str and is_hidden:
                                    final_reason_dir_activity = f"Is a hidden directory: {relative_dir_path_str}"
                                else:
                                    final_reason_dir_activity = f"Matches default ignore pattern: {msde_pattern_str_default_dir}"
                            else: # No user rules, no default ignores matched
                                if include_patterns:
                                    should_traverse_dir = False
                                    current_dir_is_root = (relative_dir_path_str == ".")

                                    path_specific_include_found = False
                                    general_file_glob_include_found = False # Contains wildcards, no slashes
                                    exact_filename_for_root_found = False   # No wildcards, no slashes, for root dir

                                    for p_str in include_patterns:
                                        p_norm = p_str.replace(os.sep, "/")
                                        # Check for path-specific include (pattern refers to current dir or its children)
                                        # e.g., current="src", pattern="src/main.py" or "src/"
                                        # e.g., current=".", pattern="src/main.py" or "src/" (handeled by relative_dir_path_str being '.')
                                        if p_norm.startswith(relative_dir_path_str + ('/' if not current_dir_is_root else '')) or \
                                           p_norm == relative_dir_path_str:
                                            path_specific_include_found = True; break
                                        if not current_dir_is_root and pathlib.Path(relative_dir_path_str) in pathlib.Path(p_norm).parents:
                                            path_specific_include_found = True; break

                                    if not path_specific_include_found: # Only check these if no path-specific one already decided
                                        for p_str in include_patterns:
                                            p_norm = p_str.replace(os.sep, "/")
                                            if "/" not in p_norm and ("*" in p_norm or "?" in p_norm or "[" in p_norm):
                                                general_file_glob_include_found = True; break
                                        if current_dir_is_root and not general_file_glob_include_found:
                                            if any(("/" not in p.replace(os.sep, "/")) and not ("*" in p or "?" in p or "[" in p) for p in include_patterns):
                                                exact_filename_for_root_found = True

                                    should_traverse_dir = path_specific_include_found or general_file_glob_include_found or exact_filename_for_root_found

                                    if should_traverse_dir:
                                        final_is_included_for_traversal = True
                                        final_reason_dir_activity = f"Traversal allowed to check for include pattern matches: {relative_dir_path_str}"
                                    else:
                                        final_is_included_for_traversal = False
                                        final_reason_dir_activity = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                                else: # No include_patterns active
                                    final_is_included_for_traversal = True
                                    final_reason_dir_activity = f"Included by default (directory): {relative_dir_path_str}"
                        else: # Default ignores are disabled
                            if include_patterns:
                                should_traverse_dir_no_default = False
                                current_dir_is_root_nd = (relative_dir_path_str == ".")

                                path_specific_include_found_nd = False
                                general_file_glob_include_found_nd = False
                                exact_filename_for_root_found_nd = False

                                for p_str in include_patterns:
                                    p_norm = p_str.replace(os.sep, "/")
                                    if p_norm.startswith(relative_dir_path_str + ('/' if not current_dir_is_root_nd else '')) or \
                                       p_norm == relative_dir_path_str:
                                        path_specific_include_found_nd = True; break
                                    if not current_dir_is_root_nd and pathlib.Path(relative_dir_path_str) in pathlib.Path(p_norm).parents:
                                        path_specific_include_found_nd = True; break

                                if not path_specific_include_found_nd:
                                    for p_str in include_patterns:
                                        p_norm = p_str.replace(os.sep, "/")
                                        if "/" not in p_norm and ("*" in p_norm or "?" in p_norm or "[" in p_norm):
                                            general_file_glob_include_found_nd = True; break
                                    if current_dir_is_root_nd and not general_file_glob_include_found_nd:
                                        if any(("/" not in p.replace(os.sep, "/")) and not ("*" in p or "?" in p or "[" in p) for p in include_patterns):
                                            exact_filename_for_root_found_nd = True

                                should_traverse_dir_no_default = path_specific_include_found_nd or general_file_glob_include_found_nd or exact_filename_for_root_found_nd

                                if should_traverse_dir_no_default:
                                    final_is_included_for_traversal = True
                                    final_reason_dir_activity = f"Traversal allowed to check for include pattern matches (default ignores disabled): {relative_dir_path_str}"
                                else:
                                    final_is_included_for_traversal = False
                                    final_reason_dir_activity = f"Does not match any user-specified include pattern (directory, default ignores disabled): {relative_dir_path_str}"
                            else: # No -i, default ignores disabled
                                final_is_included_for_traversal = True
                                final_reason_dir_activity = f"Included by default (directory, default ignores disabled): {relative_dir_path_str}"
                    elif final_is_included_for_traversal is True: # User include decided, check if it overrides a default exclude
                        if not no_default_ignore and msi_pattern_str_dir:
                            matching_default_excludes_dir = []
                            is_hidden = is_path_hidden(relative_dir_path)
                            if is_hidden:
                                matching_default_excludes_dir.append(relative_dir_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_dir_path_str, p_def):
                                    matching_default_excludes_dir.append(p_def)

                            msde_pattern_str_default_dir_check = get_most_specific_pattern(relative_dir_path_str, matching_default_excludes_dir)
                            if msde_pattern_str_default_dir_check:
                                score_msi = _calculate_specificity_score(msi_pattern_str_dir)
                                score_msde = _calculate_specificity_score(msde_pattern_str_default_dir_check)
                                if score_msde > score_msi:
                                    final_is_included_for_traversal = False
                                    final_reason_dir_activity = f"Default ignore pattern '{msde_pattern_str_default_dir_check}' (score {score_msde}) overrides user include '{msi_pattern_str_dir}' (score {score_msi})"
                                else:
                                    final_reason_dir_activity += f" (overrides default pattern: {msde_pattern_str_default_dir_check})"
                # End of `if not initial_check_excluded_dir:` block

                # Directory Pruning Refinement
                if user_decision_is_include_dir is False and mse_pattern_str_dir:
                    should_traverse_for_descendant_include = False
                    if include_patterns:
                        for inc_p_str in include_patterns:
                            if inc_p_str.startswith(relative_dir_path_str + os.sep) or \
                               (pathlib.Path(inc_p_str).parent.as_posix() == relative_dir_path_str and "/" not in pathlib.Path(inc_p_str).name):
                                should_traverse_for_descendant_include = True
                                break
                    if should_traverse_for_descendant_include:
                        final_is_included_for_traversal = True
                        final_reason_dir_activity = f"Traversal allowed: directory '{relative_dir_path_str}' matches user exclude ('{mse_pattern_str_dir}'), but an include pattern targets a descendant."

                # 5. Logging and Pruning for Directories
                current_logged_status_dir = "included" if final_is_included_for_traversal else "excluded"
                current_logged_reason_dir = final_reason_dir_activity

                if final_is_included_for_traversal and \
                   include_patterns and \
                   user_decision_is_include_dir is None and \
                   not (msi_pattern_str_dir and reason_dir_activity.startswith("Matches user-specified include pattern")) and \
                   not (msi_pattern_str_dir and reason_dir_activity.startswith("Include pattern")) and \
                   not final_reason_dir_activity.startswith("Included by default"):

                    # Check if it would have been default excluded if not for the traversal rule allowing deeper checks.
                    # This ensures we don't incorrectly mark a directory as "Does not match..." if it was default excluded.
                    is_default_excluded_check = False
                    if not no_default_ignore:
                        _matching_default_excludes_for_log = []
                        if is_path_hidden(relative_dir_path): _matching_default_excludes_for_log.append(relative_dir_path_str)
                        for _p_def_log in DEFAULT_IGNORE_PATTERNS:
                            if matches_pattern(relative_dir_path_str, _p_def_log): _matching_default_excludes_for_log.append(_p_def_log)

                        _msde_log_check = get_most_specific_pattern(relative_dir_path_str, _matching_default_excludes_for_log)
                        if _msde_log_check:
                            is_default_excluded_check = True
                            # If it is default excluded, its reason should reflect that, not "Traversal allowed..."
                            # or "Does not match..." unless the default exclude is less specific than an include that caused traversal.
                            # This part of logic is already handled by final_reason_dir_activity if default exclude was primary.
                            # The purpose here is to ensure that if traversal was allowed due to general globs,
                            # but the dir itself isn't directly included or default included, it's logged as excluded for its own sake.
                            # However, if its final_reason_dir_activity ALREADY reflects a default exclude, we keep that.
                            if not final_reason_dir_activity.startswith("Matches default ignore pattern") and not final_reason_dir_activity.startswith("Is a hidden directory"):
                                current_logged_status_dir = "excluded"
                                current_logged_reason_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"

                    if not is_default_excluded_check: # If not default excluded, and conditions above met
                         current_logged_status_dir = "excluded"
                         current_logged_reason_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"

                if not final_is_included_for_traversal:
                    stats["excluded_items_count"] += 1
                    log_events.append({
                        "path": relative_dir_path_str, "item_type": "folder", "status": "excluded", # Always excluded if not traversed
                        "size_kb": dir_size_kb, "reason": final_reason_dir_activity, # Original reason for not traversing
                    })
                    dirs_to_remove.append(dir_name)
                else:
                    if current_logged_status_dir == "excluded" and final_is_included_for_traversal : # Traversed but its own status is excluded
                        # Avoid double counting if it was already counted by initial_check_excluded_dir or similar
                        # This counts directories that are traversed (so not initially excluded) but are not included themselves
                        # This is tricky. The excluded_items_count should reflect items not part of the digest.
                        # If a dir is traversed but logged as "excluded", it's not in the digest.
                        # Let's assume stats["excluded_items_count"] is for non-traversed or explicitly excluded by user/default rule.
                        # A directory that is traversed *only* to find children, and is not itself included,
                        # might not contribute to included_files_count but also isn't "excluded" in the pruning sense.
                        # For now, let's only increment if current_logged_status_dir is 'excluded' and it wasn't already handled by a hard "no traversal".
                        # This logic of stat counting might need review.
                        pass # The stat counting will be based on the final file list or explicit dir exclusions.

                    log_events.append({
                        "path": relative_dir_path_str, "item_type": "folder", "status": current_logged_status_dir,
                        "size_kb": dir_size_kb, "reason": current_logged_reason_dir,
                    })

            if dirs_to_remove:
                dirs_orig[:] = [d for d in dirs_orig if d not in dirs_to_remove]

    return _traverse(), stats, log_events


def build_digest_tree(
    base_dir_path: pathlib.Path,
    processed_items_generator: Iterator[ProcessedItem],
    initial_stats: TraversalStats,
) -> Tuple[DigestItemNode, Dict[str, Any]]:
    root_node: DigestItemNode = {"relative_path": ".", "type": "folder", "children": []}
    current_total_content_size_kb = 0.0

    for relative_path, item_type, attributes in processed_items_generator:
        if item_type == "file":
            if attributes.get("size_kb") is not None:
                current_total_content_size_kb += attributes["size_kb"]
            parts = list(relative_path.parts)
            current_level_children = root_node["children"]
            current_path_so_far = pathlib.Path(".")
            for i, part_name in enumerate(parts[:-1]):
                current_path_so_far = current_path_so_far / part_name
                folder_node = next(
                    (c for c in current_level_children if c["relative_path"] == str(current_path_so_far) and c["type"] == "folder"), None
                )
                if not folder_node:
                    folder_node = {"relative_path": str(current_path_so_far), "type": "folder", "children": []}
                    current_level_children.append(folder_node)
                current_level_children = folder_node["children"]
            file_node: DigestItemNode = {"relative_path": str(relative_path), "type": "file", "size_kb": attributes.get("size_kb", 0.0)}
            if "content" in attributes: file_node["content"] = attributes["content"]
            if attributes.get("read_error"): file_node["read_error"] = attributes["read_error"]
            current_level_children.append(file_node)

    def sort_children_recursive(node: DigestItemNode):
        if node.get("type") == "folder" and "children" in node:
            folders = sorted([c for c in node["children"] if c["type"] == "folder"], key=lambda x: x["relative_path"])
            files = sorted([c for c in node["children"] if c["type"] == "file"], key=lambda x: x["relative_path"])
            node["children"] = folders + files
            for child in node["children"]:
                sort_children_recursive(child)
    sort_children_recursive(root_node)

    final_metadata = {
        "base_directory": str(base_dir_path.resolve()),
        "included_files_count": initial_stats.get("included_files_count", 0),
        "excluded_items_count": initial_stats.get("excluded_items_count", 0),
        "total_content_size_kb": round(current_total_content_size_kb, 3),
    }
    logger.debug(f"build_digest_tree returning metadata: {final_metadata}")
    return root_node, final_metadata
