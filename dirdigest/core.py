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

                final_is_included = False # Default to exclusion
                final_reason = ""
                current_file_size_kb = 0.0

                try:
                    if file_path_obj.is_symlink() and not follow_symlinks: # Handled by pre-check
                        current_file_size_kb = 0.0
                    else:
                         current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")

                # 1. Initial Checks (Pre-User-Pattern-Logic)
                if not follow_symlinks and file_path_obj.is_symlink():
                    final_is_included = False
                    final_reason = f"Is a symlink (symlink following disabled): {relative_file_path_str}"
                else:
                    # 2. Collect Matching User Patterns
                    matching_user_includes = [p for p in include_patterns if matches_pattern(relative_file_path_str, p)]
                    matching_user_excludes = [p for p in exclude_patterns if matches_pattern(relative_file_path_str, p)]

                    # 3. Determine Most Specific User Include/Exclude
                    msi_pattern_str = get_most_specific_pattern(relative_file_path_str, matching_user_includes)
                    mse_pattern_str = get_most_specific_pattern(relative_file_path_str, matching_user_excludes)

                    # 4. Handle Exact Pattern Conflict (MSI and MSE are identical strings)
                    if msi_pattern_str is not None and msi_pattern_str == mse_pattern_str:
                        # This specific error might be too aggressive if a user genuinely wants to override a broad include with a more specific exclude that happens to be the same string for an item.
                        # However, the prompt asks for it.
                        # A more nuanced approach would be to let specificity scores decide, and if scores are equal, define precedence (e.g., exclude wins).
                        # For now, following prompt for identical strings.
                        # This check is only for user include vs user exclude.
                         raise ValueError(f"Pattern '{msi_pattern_str}' is specified in both user include and user exclude rules for path '{relative_file_path_str}'. This is ambiguous.")

                    # 5. User Pattern Decision Logic
                    user_decision_is_include: Optional[bool] = None
                    user_reason = ""

                    if msi_pattern_str and mse_pattern_str: # Both an include and an exclude rule match
                        msi_score = _calculate_specificity_score(msi_pattern_str)
                        mse_score = _calculate_specificity_score(mse_pattern_str)
                        if msi_score > mse_score:
                            user_decision_is_include = True
                            user_reason = f"Matches more specific include pattern: {msi_pattern_str} (score {msi_score}, over exclude: {mse_pattern_str} score {mse_score})"
                        elif mse_score > msi_score:
                            user_decision_is_include = False
                            user_reason = f"Matches more specific exclude pattern: {mse_pattern_str} (score {mse_score}, over include: {msi_pattern_str} score {msi_score})"
                        else: # Equal scores
                            # Per prompt, raise error. .gitignore: last one wins.
                            raise ValueError(f"Include pattern '{msi_pattern_str}' and exclude pattern '{mse_pattern_str}' have equal specificity for path '{relative_file_path_str}'. Please refine your rules.")
                    elif msi_pattern_str:
                        user_decision_is_include = True
                        user_reason = f"Matches user-specified include pattern: {msi_pattern_str}"
                    elif mse_pattern_str:
                        user_decision_is_include = False
                        user_reason = f"Matches user-specified exclude pattern: {mse_pattern_str}"

                    # 6. Default Ignore Logic (If no user rule decided)
                    if user_decision_is_include is not None:
                        final_is_included = user_decision_is_include
                        final_reason = user_reason
                    else: # No user patterns matched or resolved to a decision
                        if not no_default_ignore:
                            matching_default_excludes = []
                            is_hidden = is_path_hidden(relative_file_path)
                            if is_hidden: # Hidden files are treated as if they match an exact path default exclude
                                matching_default_excludes.append(relative_file_path_str)

                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_file_path_str, p_def):
                                    matching_default_excludes.append(p_def)

                            msde_pattern_str = get_most_specific_pattern(relative_file_path_str, matching_default_excludes)

                            if msde_pattern_str:
                                final_is_included = False
                                if msde_pattern_str == relative_file_path_str and is_hidden:
                                    final_reason = f"Is a hidden file: {relative_file_path_str}"
                                else:
                                    final_reason = f"Matches default ignore pattern: {msde_pattern_str}"
                            else: # No user rules, no default ignores matched
                                if include_patterns: # User specified -i, so only include what matches them
                                    final_is_included = False
                                    final_reason = f"Does not match any user-specified include pattern: {relative_file_path_str}"
                                else: # No -i, no user excludes, no default excludes
                                    final_is_included = True
                                    final_reason = f"Included by default: {relative_file_path_str}"
                        else: # Default ignores are disabled
                            if include_patterns: # User specified -i
                                final_is_included = False # Must match an include if -i is used
                                final_reason = f"Does not match any user-specified include pattern (default ignores disabled): {relative_file_path_str}"
                            else: # No -i, no default ignores, no user patterns matched
                                final_is_included = True
                                final_reason = f"Included by default (default ignores disabled): {relative_file_path_str}"

                # 7. Post-Decision Checks (Files)
                file_attributes: ProcessedItemPayload = {}
                if final_is_included:
                    file_attributes["size_kb"] = current_file_size_kb
                    if current_file_size_kb * 1024 > max_size_bytes:
                        final_is_included = False
                        final_reason = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB): {relative_file_path_str}"
                    else:
                        try:
                            with file_path_obj.open("r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                        except (OSError, UnicodeDecodeError) as e:
                            error_reason_str = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                final_is_included = False
                                final_reason = f"Read error ({error_reason_str}): {relative_file_path_str}"
                            else:
                                file_attributes["content"] = None
                                file_attributes["read_error"] = error_reason_str

                # 8. Logging and Stats for Files
                if final_is_included:
                    stats["included_files_count"] += 1
                    log_events.append({
                        "path": relative_file_path_str, "item_type": "file", "status": "included",
                        "size_kb": current_file_size_kb, "reason": final_reason
                    })
                    yield (relative_file_path, "file", file_attributes)
                else:
                    stats["excluded_items_count"] += 1
                    log_events.append({
                        "path": relative_file_path_str, "item_type": "file", "status": "excluded",
                        "size_kb": current_file_size_kb, "reason": final_reason
                    })

            # --- Process Directories ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks)

                final_is_included_for_traversal = False # Default to exclusion, will be set by logic below
                final_reason_dir_activity = ""

                user_decision_is_include_dir: Optional[bool] = None
                user_reason_dir = ""
                msi_pattern_str_dir: Optional[str] = None # ensure it's defined for all paths
                mse_pattern_str_dir: Optional[str] = None

                initial_check_excluded = False

                # 1. Initial Checks (Pre-User-Pattern-Logic)
                if max_depth is not None and current_depth >= max_depth:
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Exceeds max depth: {relative_dir_path_str}"
                    initial_check_excluded = True
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    final_is_included_for_traversal = False
                    final_reason_dir_activity = f"Is a symlink (symlink following disabled): {relative_dir_path_str}"
                    initial_check_excluded = True

                if not initial_check_excluded:
                    # 2. Collect Matching User Patterns
                    matching_user_includes_dir = [p for p in include_patterns if matches_pattern(relative_dir_path_str, p)]
                    matching_user_excludes_dir = [p for p in exclude_patterns if matches_pattern(relative_dir_path_str, p)]

                    # 3. Determine Most Specific User Include/Exclude
                    msi_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_includes_dir)
                    mse_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_excludes_dir)

                    # 4. Handle Exact Pattern Conflict
                    if msi_pattern_str_dir is not None and msi_pattern_str_dir == mse_pattern_str_dir:
                         raise ValueError(f"Pattern '{msi_pattern_str_dir}' is specified in both user include and user exclude rules for directory '{relative_dir_path_str}'. This is ambiguous.")

                    # 5. User Pattern Decision Logic
                    # user_decision_is_include_dir is already initialized above
                    # msi_pattern_str_dir and mse_pattern_str_dir were initialized to None above

                    if msi_pattern_str_dir and mse_pattern_str_dir:
                        msi_score = _calculate_specificity_score(msi_pattern_str_dir)
                        mse_score = _calculate_specificity_score(mse_pattern_str_dir)
                        if msi_score > mse_score:
                            user_decision_is_include_dir = True
                            user_reason_dir = f"Matches more specific include pattern (traversal allowed): {msi_pattern_str_dir} (score {msi_score}, over exclude: {mse_pattern_str_dir} score {mse_score})"
                        elif mse_score > msi_score:
                            user_decision_is_include_dir = False
                            user_reason_dir = f"Matches more specific exclude pattern: {mse_pattern_str_dir} (score {mse_score}, over include: {msi_pattern_str_dir} score {msi_score})"
                        else: # Equal scores
                             raise ValueError(f"Include pattern '{msi_pattern_str_dir}' and exclude pattern '{mse_pattern_str_dir}' have equal specificity for directory '{relative_dir_path_str}'. Please refine your rules.")
                    elif msi_pattern_str_dir:
                        user_decision_is_include_dir = True
                        user_reason_dir = f"Matches user-specified include pattern (traversal allowed): {msi_pattern_str_dir}"
                    elif mse_pattern_str_dir:
                        user_decision_is_include_dir = False
                        user_reason_dir = f"Matches user-specified exclude pattern: {mse_pattern_str_dir}"

                    # 6. Default Ignore Logic for Directories
                    if user_decision_is_include_dir is not None:
                        final_is_included_for_traversal = user_decision_is_include_dir
                        final_reason_dir_activity = user_reason_dir
                    else: # No user patterns matched or resolved
                        if not no_default_ignore:
                            matching_default_excludes_dir = []
                            is_hidden = is_path_hidden(relative_dir_path)
                            if is_hidden:
                                matching_default_excludes_dir.append(relative_dir_path_str)
                            for p_def in DEFAULT_IGNORE_PATTERNS:
                                if matches_pattern(relative_dir_path_str, p_def):
                                    matching_default_excludes_dir.append(p_def)

                            msde_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_default_excludes_dir)

                            if msde_pattern_str_dir:
                                final_is_included_for_traversal = False
                                if msde_pattern_str_dir == relative_dir_path_str and is_hidden:
                                    final_reason_dir_activity = f"Is a hidden directory: {relative_dir_path_str}"
                                else:
                                    final_reason_dir_activity = f"Matches default ignore pattern: {msde_pattern_str_dir}"
                            else: # No user rules, no default ignores matched
                                if include_patterns:
                                    # If any include pattern could potentially match a descendant, allow traversal.
                                    # This is a simplified check; a more robust one would involve checking if any include pattern starts with relative_dir_path_str + '/'
                                    # or if a glob pattern could match something inside.
                                    # The current `process_directory_recursive` structure with `topdown=True` means pruning here prevents any descendant check.
                                    # The logic from previous iteration to handle this:
                                    should_traverse_for_any_include = False
                                    if include_patterns:
                                        current_dir_path_obj_for_check = pathlib.Path(relative_dir_path_str)
                                        for inc_pattern_str in include_patterns:
                                            # Check if inc_pattern implies this dir or a descendant
                                            if inc_pattern_str.startswith(relative_dir_path_str) or \
                                               (current_dir_path_obj_for_check in pathlib.Path(inc_pattern_str).parents) or \
                                               ("*" in inc_pattern_str or "?" in inc_pattern_str or "[" in inc_pattern_str) : # Simplistic glob check
                                                should_traverse_for_any_include = True
                                                break
                                    if should_traverse_for_any_include:
                                        final_is_included_for_traversal = True
                                        final_reason_dir_activity = f"Traversal allowed to check for include pattern matches: {relative_dir_path_str}"
                                    else:
                                        final_is_included_for_traversal = False
                                        final_reason_dir_activity = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                                else: # No -i, no user excludes, no default excludes
                                    final_is_included_for_traversal = True
                                    # final_reason_dir_activity will be "Traversal allowed by default" only if not overridden by refinement.
                                    final_reason_dir_activity = f"Traversal allowed by default: {relative_dir_path_str}" # Ensure it's set before refinement
                        else: # Default ignores are disabled
                            if include_patterns:
                                should_traverse_for_any_include_no_default = False
                                if include_patterns:
                                    current_dir_path_obj_for_check = pathlib.Path(relative_dir_path_str)
                                    for inc_pattern_str in include_patterns:
                                        if inc_pattern_str.startswith(relative_dir_path_str) or \
                                           (current_dir_path_obj_for_check in pathlib.Path(inc_pattern_str).parents) or \
                                           ("*" in inc_pattern_str or "?" in inc_pattern_str or "[" in inc_pattern_str) :
                                            should_traverse_for_any_include_no_default = True
                                            break
                                if should_traverse_for_any_include_no_default:
                                     final_is_included_for_traversal = True
                                     final_reason_dir_activity = f"Traversal allowed to check for include pattern matches (default ignores disabled): {relative_dir_path_str}"
                                else:
                                    final_is_included_for_traversal = False
                                    final_reason_dir_activity = f"Does not match any user-specified include pattern (directory, default ignores disabled): {relative_dir_path_str}"
                            else: # No -i, no default ignores, no user patterns matched
                                final_is_included_for_traversal = True
                                final_reason_dir_activity = f"Traversal allowed by default (default ignores disabled): {relative_dir_path_str}" # Ensure it's set

                    # Directory Pruning Refinement:
                    # This block should only run if a user exclude pattern was the definitive reason for exclusion.
                    if user_decision_is_include_dir is False and mse_pattern_str_dir:
                        should_traverse_for_descendant_include = False
                        if include_patterns:
                            current_dir_path_obj_for_check = pathlib.Path(relative_dir_path_str)
                        for inc_pattern_str in include_patterns:
                            inc_path_obj = pathlib.Path(inc_pattern_str)
                            if current_dir_path_obj_for_check != inc_path_obj and current_dir_path_obj_for_check in inc_path_obj.parents:
                                should_traverse_for_descendant_include = True
                                break
                        if should_traverse_for_descendant_include: # This 'if' must be inside the parent 'if user_decision_is_include_dir...'
                            final_is_included_for_traversal = True # Override pruning
                            final_reason_dir_activity = ( # This will overwrite previous final_reason_dir_activity
                            f"Traversal allowed: item matches user exclude ('{mse_pattern_str_dir}'), but an include pattern targets a descendant."
                        )
                # End of 'if not initial_check_excluded:' block

                # Logging and Pruning for Directories
                if not final_is_included_for_traversal: # This uses the final decision
                    stats["excluded_items_count"] += 1
                    log_events.append({
                        "path": relative_dir_path_str, "item_type": "folder", "status": "excluded",
                        "size_kb": dir_size_kb, "reason": final_reason_dir_activity,
                    })
                    dirs_to_remove.append(dir_name)
                else:
                    log_events.append({
                        "path": relative_dir_path_str, "item_type": "folder", "status": "included",
                        "size_kb": dir_size_kb, "reason": final_reason_dir_activity,
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
