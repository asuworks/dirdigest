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
    filter_mode: str, # Added filter_mode
) -> Tuple[Generator[ProcessedItem, None, None], TraversalStats, List[LogEvent]]:
    stats: TraversalStats = {"included_files_count": 0, "excluded_items_count": 0}
    log_events: List[LogEvent] = []
    max_size_bytes = max_size_kb * 1024

    logger.debug(f"Core: Max size KB: {max_size_kb}, Ignore read errors: {ignore_read_errors}")
    logger.debug(f"Core: Follow symlinks: {follow_symlinks}, No default ignore: {no_default_ignore}")
    logger.debug(f"Core: Filter mode: {filter_mode}") # Added logger for filter_mode

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

                is_included: bool = False # Default to not included
                reason: str = ""
                current_file_size_kb = 0.0

                try:
                    # Calculate size for all files, even if potentially excluded early (for logging)
                    if file_path_obj.is_symlink() and not follow_symlinks:
                        current_file_size_kb = 0.0
                    else:
                        current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")
                    # If stat fails, treat as size 0 and potentially exclude later due to read error
                    current_file_size_kb = 0.0


                # 1. Calculate all matching conditions first
                # For user patterns, we just need to know if any match. Specificity is handled by precedence.
                matches_user_include = any(matches_pattern(relative_file_path_str, p) for p in include_patterns)
                matches_user_exclude = any(matches_pattern(relative_file_path_str, p) for p in exclude_patterns)

                is_symlink_and_not_followed = not follow_symlinks and file_path_obj.is_symlink()

                is_hidden = is_path_hidden(relative_file_path) # boolean
                is_hidden_and_not_default_ignored = is_hidden and not no_default_ignore

                # For default excludes, we also just need to know if any match.
                matches_default_exclude_patterns = not no_default_ignore and any(matches_pattern(relative_file_path_str, p) for p in DEFAULT_IGNORE_PATTERNS)

                # Combine hidden check with default exclude patterns for the purpose of matches_default_exclude
                # A hidden file is a form of default ignore, unless no_default_ignore is True.
                matches_default_exclude = (is_hidden and not no_default_ignore) or matches_default_exclude_patterns

                # 2. Apply new precedence rules to determine initial is_included and reason
                if matches_user_include:
                    is_included = True
                    reason = f"Matches user-specified include pattern: {relative_file_path_str}"
                elif is_symlink_and_not_followed:
                    is_included = False # Stays false
                    reason = f"Is a symlink (symlink following disabled): {relative_file_path_str}"
                elif matches_user_exclude:
                    is_included = False # Stays false
                    reason = f"Matches user-specified exclude pattern: {relative_file_path_str}"
                # Combined hidden and default exclude check:
                elif matches_default_exclude: # This covers is_hidden_and_not_default_ignored and matches_default_exclude_patterns
                    is_included = False # Stays false
                    if is_hidden and not no_default_ignore: # Prioritize "hidden" as reason if it's the cause
                         reason = f"Is a hidden file: {relative_file_path_str}"
                    else: # Otherwise, it's a default pattern match
                         reason = f"Matches default ignore pattern: {relative_file_path_str}"
                elif include_patterns: # User specified include patterns, but this file didn't match any
                    is_included = False # Stays false
                    reason = f"Does not match any user-specified include pattern: {relative_file_path_str}"
                else: # Default include (no include_patterns given, and not excluded by other rules)
                    is_included = True
                    reason = f"Included by default: {relative_file_path_str}"

                # 3. Handle the outcome: size checks and file reading (if included so far)
                file_attributes: ProcessedItemPayload = {}
                if is_included:
                    file_attributes["size_kb"] = current_file_size_kb
                    if current_file_size_kb * 1024 > max_size_bytes:
                        is_included = False # Now excluded
                        reason = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB): {relative_file_path_str}"
                    else:
                        try:
                            if file_path_obj.is_symlink() and not file_path_obj.exists(): # Check for broken symlink
                                raise OSError(f"Broken symbolic link: {relative_file_path_str}")
                            # Attempt to read content only if not a broken symlink or if it's a regular file
                            with file_path_obj.open("r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                            # If successfully included and read, the initial reason (e.g. "Matches user include") is kept.
                            # Or, if it was "Included by default", that's also fine.
                        except (OSError, UnicodeDecodeError) as e:
                            error_reason_str = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                is_included = False # Now excluded
                                reason = f"Read error ({error_reason_str}): {relative_file_path_str}"
                            else:
                                # Included, but with read error noted
                                file_attributes["content"] = None
                                file_attributes["read_error"] = error_reason_str
                                reason += f" (read error ignored: {error_reason_str})"

                # Log and yield based on final status
                if is_included:
                    stats["included_files_count"] += 1
                    # For included files, the reason might be "Matches user-specified include pattern", "Included by default",
                    # or "Included by default (read error ignored...)"
                    log_events.append({
                        "path": relative_file_path_str,
                        "item_type": "file",
                        "status": "included",
                        "size_kb": current_file_size_kb,
                        "reason": reason,
                    })
                    yield (relative_file_path, "file", file_attributes)
                else:
                    stats["excluded_items_count"] += 1
                    # Reason will be set by one of the exclusion conditions or subsequent size/read error.
                    log_events.append({
                        "path": relative_file_path_str,
                        "item_type": "file",
                        "status": "excluded",
                        "size_kb": current_file_size_kb,
                        "reason": reason,
                    })

            # --- Process Directories ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks)

                user_decision_is_include_dir: Optional[bool] = None
                reason_dir_activity: str = ""
                msi_pattern_str_dir: Optional[str] = None
                mse_pattern_str_dir: Optional[str] = None
                final_is_included_for_traversal: bool = False
                final_reason_dir_activity: str = ""
                initial_check_excluded_dir = False

                if max_depth is not None and current_depth >= max_depth:
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Exceeds max depth: {relative_dir_path_str}"
                    initial_check_excluded_dir = True
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Is a symlink (symlink following disabled): {relative_dir_path_str}"
                    initial_check_excluded_dir = True

                if not initial_check_excluded_dir:
                    matching_user_includes_dir = [p for p in include_patterns if matches_pattern(relative_dir_path_str, p)]
                    matching_user_excludes_dir = [p for p in exclude_patterns if matches_pattern(relative_dir_path_str, p)]
                    msi_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_includes_dir)
                    mse_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_excludes_dir)

                    if msi_pattern_str_dir is not None and msi_pattern_str_dir == mse_pattern_str_dir:
                        raise ValueError(f"Pattern '{msi_pattern_str_dir}' is specified in both include and exclude rules for directory '{relative_dir_path_str}'.")

                    if msi_pattern_str_dir and mse_pattern_str_dir:
                        score_msi = _calculate_specificity_score(msi_pattern_str_dir)
                        score_mse = _calculate_specificity_score(mse_pattern_str_dir)
                        if score_msi > score_mse:
                            user_decision_is_include_dir = True
                            reason_dir_activity = f"Include pattern '{msi_pattern_str_dir}' (score {score_msi}) is more specific than exclude pattern '{mse_pattern_str_dir}' (score {score_mse})"
                        elif score_mse > score_msi:
                            user_decision_is_include_dir = False
                            reason_dir_activity = f"Exclude pattern '{mse_pattern_str_dir}' (score {score_mse}) is more specific than include pattern '{msi_pattern_str_dir}' (score {score_msi})"
                        else:
                            raise ValueError(f"Include pattern '{msi_pattern_str_dir}' and exclude pattern '{mse_pattern_str_dir}' have equal specificity for directory '{relative_dir_path_str}'. Please refine your rules.")
                    elif msi_pattern_str_dir:
                        user_decision_is_include_dir = True; reason_dir_activity = f"Matches user-specified include pattern: {msi_pattern_str_dir}"
                    elif mse_pattern_str_dir:
                        user_decision_is_include_dir = False; reason_dir_activity = f"Matches user-specified exclude pattern: {mse_pattern_str_dir}"

                    final_is_included_for_traversal = user_decision_is_include_dir
                    final_reason_dir_activity = reason_dir_activity

                    if final_is_included_for_traversal is None:
                        if not no_default_ignore:
                            matching_default_excludes_dir = []
                            if is_path_hidden(relative_dir_path): matching_default_excludes_dir.append(relative_dir_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_dir_path_str, p_def): matching_default_excludes_dir.append(p_def)
                            msde_pattern_str_default_dir = get_most_specific_pattern(relative_dir_path_str, matching_default_excludes_dir)
                            if msde_pattern_str_default_dir:
                                final_is_included_for_traversal = False
                                final_reason_dir_activity = f"Is a hidden directory: {relative_dir_path_str}" if msde_pattern_str_default_dir == relative_dir_path_str and is_path_hidden(relative_dir_path) else f"Matches default ignore pattern: {msde_pattern_str_default_dir}"
                            else:
                                if include_patterns:
                                    should_traverse = False; current_dir_is_root = (relative_dir_path_str == ".")
                                    for p_str in include_patterns:
                                        p_norm = p_str.replace(os.sep, "/")
                                        path_prefix_to_check = relative_dir_path_str if not current_dir_is_root else ''
                                        if path_prefix_to_check and path_prefix_to_check != '.': path_prefix_to_check += '/'
                                        elif current_dir_is_root: path_prefix_to_check = ''
                                        if p_norm == relative_dir_path_str or \
                                           (path_prefix_to_check and p_norm.startswith(path_prefix_to_check)) or \
                                           (current_dir_is_root and "/" in p_norm and not p_norm.startswith(".") and not p_norm.startswith("/")) or \
                                           (not current_dir_is_root and pathlib.Path(relative_dir_path_str) in pathlib.Path(p_norm).parents):
                                            should_traverse = True; break
                                        if "/" not in p_norm and ("*" in p_norm or "?" in p_norm or "[" in p_norm): should_traverse = True; break
                                        if current_dir_is_root and "/" not in p_norm and not ("*" in p_norm or "?" in p_norm or "[" in p_norm): should_traverse = True; break
                                    if should_traverse: final_is_included_for_traversal = True; final_reason_dir_activity = f"Traversal allowed to check for include pattern matches: {relative_dir_path_str}"
                                    else: final_is_included_for_traversal = False; final_reason_dir_activity = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                                else: final_is_included_for_traversal = True; final_reason_dir_activity = f"Included by default (directory): {relative_dir_path_str}"
                        else:
                            if include_patterns:
                                should_traverse = False; current_dir_is_root_nd = (relative_dir_path_str == ".")
                                for p_str in include_patterns:
                                    p_norm = p_str.replace(os.sep, "/")
                                    path_prefix_to_check_nd = relative_dir_path_str if not current_dir_is_root_nd else ''
                                    if path_prefix_to_check_nd and path_prefix_to_check_nd != '.': path_prefix_to_check_nd += '/'
                                    elif current_dir_is_root_nd: path_prefix_to_check_nd = ''
                                    if p_norm == relative_dir_path_str or \
                                       (path_prefix_to_check_nd and p_norm.startswith(path_prefix_to_check_nd)) or \
                                       (current_dir_is_root_nd and "/" in p_norm and not p_norm.startswith(".") and not p_norm.startswith("/")) or \
                                       (not current_dir_is_root_nd and pathlib.Path(relative_dir_path_str) in pathlib.Path(p_norm).parents):
                                        should_traverse = True; break
                                    if "/" not in p_norm and ("*" in p_norm or "?" in p_norm or "[" in p_norm): should_traverse = True; break
                                    if current_dir_is_root_nd and "/" not in p_norm and not ("*" in p_norm or "?" in p_norm or "[" in p_norm): should_traverse = True; break
                                if should_traverse: final_is_included_for_traversal = True; final_reason_dir_activity = f"Traversal allowed to check for include pattern matches (default ignores disabled): {relative_dir_path_str}"
                                else: final_is_included_for_traversal = False; final_reason_dir_activity = f"Does not match any user-specified include pattern (directory, default ignores disabled): {relative_dir_path_str}"
                            else: final_is_included_for_traversal = True; final_reason_dir_activity = f"Included by default (directory, default ignores disabled): {relative_dir_path_str}"
                    elif final_is_included_for_traversal is True:
                        if not no_default_ignore and msi_pattern_str_dir:
                            matching_default_excludes_dir = []
                            if is_path_hidden(relative_dir_path): matching_default_excludes_dir.append(relative_dir_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_dir_path_str, p_def): matching_default_excludes_dir.append(p_def)
                            msde_pattern_str_default_dir_check = get_most_specific_pattern(relative_dir_path_str, matching_default_excludes_dir)
                            if msde_pattern_str_default_dir_check:
                                score_msi = _calculate_specificity_score(msi_pattern_str_dir)
                                score_msde = _calculate_specificity_score(msde_pattern_str_default_dir_check)
                                if score_msde > score_msi:
                                    final_is_included_for_traversal = False
                                    final_reason_dir_activity = f"Default ignore pattern '{msde_pattern_str_default_dir_check}' (score {score_msde}) overrides user include '{msi_pattern_str_dir}' (score {score_msi})"
                                else:
                                    final_reason_dir_activity += f" (overrides default pattern: {msde_pattern_str_default_dir_check})"

                if user_decision_is_include_dir is False and mse_pattern_str_dir:
                    should_traverse_for_descendant_include = False
                    if include_patterns:
                        for inc_p_str in include_patterns:
                            if inc_p_str.startswith(relative_dir_path_str + os.sep) or \
                               (pathlib.Path(inc_p_str).parent.as_posix() == relative_dir_path_str and "/" not in pathlib.Path(inc_p_str).name):
                                should_traverse_for_descendant_include = True; break
                    if should_traverse_for_descendant_include:
                        final_is_included_for_traversal = True
                        final_reason_dir_activity = f"Traversal allowed: directory '{relative_dir_path_str}' matches user exclude ('{mse_pattern_str_dir}'), but an include pattern targets a descendant."

                current_logged_status_dir = "included" if final_is_included_for_traversal else "excluded"
                current_logged_reason_dir = final_reason_dir_activity

                if final_is_included_for_traversal and \
                   include_patterns and \
                   user_decision_is_include_dir is None and \
                   not (msi_pattern_str_dir and reason_dir_activity.startswith("Matches user-specified include pattern")) and \
                   not (msi_pattern_str_dir and reason_dir_activity.startswith("Include pattern")) and \
                   not final_reason_dir_activity.startswith("Included by default"):
                    is_default_excluded_check = False
                    if not no_default_ignore:
                        _matching_default_excludes_for_log = []
                        if is_path_hidden(relative_dir_path): _matching_default_excludes_for_log.append(relative_dir_path_str)
                        for _p_def_log in DEFAULT_IGNORE_PATTERNS:
                            if matches_pattern(relative_dir_path_str, _p_def_log): _matching_default_excludes_for_log.append(_p_def_log)
                        _msde_log_check = get_most_specific_pattern(relative_dir_path_str, _matching_default_excludes_for_log)
                        if _msde_log_check:
                            is_default_excluded_check = True
                            if not final_reason_dir_activity.startswith("Matches default ignore pattern") and not final_reason_dir_activity.startswith("Is a hidden directory"):
                                current_logged_status_dir = "excluded"
                                current_logged_reason_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                    if not is_default_excluded_check:
                         current_logged_status_dir = "excluded"
                         current_logged_reason_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"

                if not final_is_included_for_traversal:
                    stats["excluded_items_count"] += 1
                    log_events.append({"path": relative_dir_path_str, "item_type": "folder", "status": "excluded", "size_kb": dir_size_kb, "reason": final_reason_dir_activity})
                    dirs_to_remove.append(dir_name)
                else:
                    if current_logged_status_dir == "excluded" and final_is_included_for_traversal :
                        pass
                    log_events.append({"path": relative_dir_path_str, "item_type": "folder", "status": current_logged_status_dir, "size_kb": dir_size_kb, "reason": current_logged_reason_dir})

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
