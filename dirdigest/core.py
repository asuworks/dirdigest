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
        # Helper functions for pattern type determination
        def _is_dir_like_pattern(p_str: Optional[str]) -> bool:
            if p_str is None: return False
            # Considers patterns ending with '/', containing '/', or being '**' as directory-like
            return p_str.endswith("/") or "/" in p_str or p_str == "**"

        def _is_name_glob_pattern(p_str: Optional[str]) -> bool:
            if p_str is None: return False
            # Considers patterns without '/' and containing wildcards as name globs
            return "/" not in p_str and ("*" in p_str or "?" in p_str or "[" in p_str)

        for root, dirs_orig, files_orig in os.walk(str(base_dir_path), topdown=True, followlinks=follow_symlinks):
            current_root_path = pathlib.Path(root)
            relative_root_path = current_root_path.relative_to(base_dir_path)
            current_depth_of_root = len(relative_root_path.parts) if relative_root_path != pathlib.Path(".") else 0

            if max_depth is not None:
                if current_depth_of_root > max_depth:
                    dirs_orig[:] = []
                    continue
                if current_depth_of_root == max_depth:
                    dirs_orig[:] = []

            # --- Process Files ---
            for file_name in files_orig:
                file_path_obj = current_root_path / file_name
                relative_file_path = relative_root_path / file_name
                relative_file_path_str = str(relative_file_path)

                is_included: bool = False
                reason: str = ""
                current_file_size_kb = 0.0

                try:
                    if file_path_obj.is_symlink() and not follow_symlinks:
                        current_file_size_kb = 0.0
                    else:
                        current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")
                    current_file_size_kb = 0.0

                if not follow_symlinks and file_path_obj.is_symlink():
                    is_included = False
                    reason = f"Is a symlink (symlink following disabled): {relative_file_path_str}"
                else:
                    matching_user_includes_file = [p for p in include_patterns if matches_pattern(relative_file_path_str, p)]
                    matching_user_excludes_file = [p for p in exclude_patterns if matches_pattern(relative_file_path_str, p)]
                    msi_pattern_str_file = get_most_specific_pattern(relative_file_path_str, matching_user_includes_file)
                    mse_pattern_str_file = get_most_specific_pattern(relative_file_path_str, matching_user_excludes_file)

                    user_decision_is_include: Optional[bool] = None
                    user_reason: str = ""

                    if msi_pattern_str_file is not None and msi_pattern_str_file == mse_pattern_str_file:
                        raise ValueError(f"Pattern '{msi_pattern_str_file}' is specified in both include and exclude rules for path '{relative_file_path_str}'.")
                    elif msi_pattern_str_file and mse_pattern_str_file:
                        msi_is_dir = _is_dir_like_pattern(msi_pattern_str_file)
                        msi_is_name_glob_type = _is_name_glob_pattern(msi_pattern_str_file)
                        mse_is_dir = _is_dir_like_pattern(mse_pattern_str_file)
                        mse_is_name_glob_type = _is_name_glob_pattern(mse_pattern_str_file)

                        if msi_is_dir and mse_is_name_glob_type:
                            user_decision_is_include = False
                            user_reason = f"Name glob exclude '{mse_pattern_str_file}' filters directory include '{msi_pattern_str_file}' for path '{relative_file_path_str}'"
                        elif mse_is_dir and msi_is_name_glob_type:
                            user_decision_is_include = False
                            user_reason = f"Directory exclude '{mse_pattern_str_file}' overrides name glob include '{msi_pattern_str_file}' for path '{relative_file_path_str}'"
                        else:
                            score_msi = _calculate_specificity_score(msi_pattern_str_file)
                            score_mse = _calculate_specificity_score(mse_pattern_str_file)
                            if score_msi > score_mse:
                                user_decision_is_include = True
                                user_reason = f"Include pattern '{msi_pattern_str_file}' (score {score_msi}) is more specific than exclude pattern '{mse_pattern_str_file}' (score {score_mse}) for path '{relative_file_path_str}'"
                            elif score_mse > score_msi:
                                user_decision_is_include = False
                                user_reason = f"Exclude pattern '{mse_pattern_str_file}' (score {score_mse}) is more specific than include pattern '{msi_pattern_str_file}' (score {score_msi}) for path '{relative_file_path_str}'"
                            else:
                                raise ValueError(f"Include pattern '{msi_pattern_str_file}' and exclude pattern '{mse_pattern_str_file}' have equal specificity for path '{relative_file_path_str}'. Please refine your rules.")
                    elif msi_pattern_str_file:
                        user_decision_is_include = True
                        user_reason = f"Matches user-specified include pattern: {msi_pattern_str_file} for path '{relative_file_path_str}'"
                    elif mse_pattern_str_file:
                        user_decision_is_include = False
                        user_reason = f"Matches user-specified exclude pattern: {mse_pattern_str_file} for path '{relative_file_path_str}'"
                    else:
                        user_decision_is_include = None
                        user_reason = f"No user patterns matched for path '{relative_file_path_str}'"

                    if filter_mode == "default":
                        if user_decision_is_include is not None:
                            is_included = user_decision_is_include
                            reason = user_reason
                        else:
                            is_hidden = is_path_hidden(relative_file_path)
                            default_ignore_match_str = next((p_def for p_def in DEFAULT_IGNORE_PATTERNS if matches_pattern(relative_file_path_str, p_def)), None) if not no_default_ignore else None

                            if not no_default_ignore and is_hidden:
                                is_included = False
                                reason = f"Is a hidden file: {relative_file_path_str}"
                            elif default_ignore_match_str:
                                is_included = False
                                reason = f"Matches default ignore pattern: {default_ignore_match_str} for path '{relative_file_path_str}'"
                            else:
                                if include_patterns:
                                    is_included = False
                                    reason = f"Does not match any user-specified include pattern and not default excluded (mode: default): {relative_file_path_str}"
                                else:
                                    is_included = True
                                    reason = f"Included by default (mode: default): {relative_file_path_str}"

                    elif filter_mode == "include_first":
                        if user_decision_is_include is True:
                            is_included = True
                            reason = user_reason
                        elif user_decision_is_include is False:
                            is_included = False
                            reason = user_reason
                        else:
                            is_included = False
                            if include_patterns and not msi_pattern_str_file:
                                reason = f"Does not match any user-specified include pattern (mode: include_first): {relative_file_path_str}"
                            elif not include_patterns:
                                reason = f"No include patterns provided (mode: include_first implies exclusion unless item matches a user include rule): {relative_file_path_str}"
                            else:
                                reason = f"Controlling include pattern did not win precedence (mode: include_first): {relative_file_path_str}"


                    elif filter_mode == "exclude_first":
                        if user_decision_is_include is False:
                            is_included = False
                            reason = user_reason
                        else:
                            is_hidden = is_path_hidden(relative_file_path)
                            default_ignore_match_str = next((p_def for p_def in DEFAULT_IGNORE_PATTERNS if matches_pattern(relative_file_path_str, p_def)), None) if not no_default_ignore else None

                            if not no_default_ignore and is_hidden:
                                is_included = False
                                reason = f"Is a hidden file (mode: exclude_first): {relative_file_path_str}"
                                if user_decision_is_include is True:
                                    reason = f"Is a hidden file (overriding user include '{msi_pattern_str_file}' due to mode: exclude_first): {relative_file_path_str}"
                            elif default_ignore_match_str:
                                is_included = False
                                reason = f"Matches default ignore pattern: {default_ignore_match_str} (mode: exclude_first) for path '{relative_file_path_str}'"
                                if user_decision_is_include is True:
                                     reason = f"Matches default ignore pattern: {default_ignore_match_str} (overriding user include '{msi_pattern_str_file}' due to mode: exclude_first) for path '{relative_file_path_str}'"
                            else:
                                if user_decision_is_include is True:
                                    is_included = True
                                    reason = user_reason
                                elif include_patterns:
                                    is_included = False
                                    reason = f"Does not match any user-specified include pattern and not default excluded (mode: exclude_first): {relative_file_path_str}"
                                else:
                                    is_included = True
                                    reason = f"Included by default (mode: exclude_first): {relative_file_path_str}"

                file_attributes: ProcessedItemPayload = {}
                if is_included:
                    file_attributes["size_kb"] = current_file_size_kb
                    if current_file_size_kb * 1024 > max_size_bytes:
                        is_included = False
                        reason = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB): {relative_file_path_str}"
                    else:
                        try:
                            if file_path_obj.is_symlink() and not file_path_obj.exists():
                                raise OSError(f"Broken symbolic link: {relative_file_path_str}")
                            with file_path_obj.open("r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                        except (OSError, UnicodeDecodeError) as e:
                            error_reason_str = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                is_included = False
                                reason = f"Read error ({error_reason_str}): {relative_file_path_str}"
                            else:
                                file_attributes["content"] = None
                                file_attributes["read_error"] = error_reason_str
                                reason += f" (read error ignored: {error_reason_str})"

                if is_included:
                    stats["included_files_count"] += 1
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

                should_traverse_dir: bool = False
                log_status_for_dir: str = "excluded"
                reason_for_dir: str = ""

                if max_depth is not None and current_depth_of_root >= max_depth:
                    should_traverse_dir = False
                    log_status_for_dir = "excluded"
                    reason_for_dir = f"Parent directory at max depth ({current_depth_of_root}), not processing or traversing child '{relative_dir_path_str}'"
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    should_traverse_dir = False
                    log_status_for_dir = "excluded"
                    reason_for_dir = f"Is a symlink (symlink following disabled): {relative_dir_path_str}"
                else:
                    matching_user_includes_dir = [p for p in include_patterns if matches_pattern(relative_dir_path_str, p)]
                    matching_user_excludes_dir = [p for p in exclude_patterns if matches_pattern(relative_dir_path_str, p)]
                    msi_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_includes_dir)
                    mse_pattern_str_dir = get_most_specific_pattern(relative_dir_path_str, matching_user_excludes_dir)

                    user_decision_is_include_dir: Optional[bool] = None
                    user_reason_dir: str = ""

                    if msi_pattern_str_dir is not None and msi_pattern_str_dir == mse_pattern_str_dir:
                        raise ValueError(f"Pattern '{msi_pattern_str_dir}' is specified in both include and exclude rules for directory '{relative_dir_path_str}'.")
                    elif msi_pattern_str_dir and mse_pattern_str_dir:
                        score_msi_dir = _calculate_specificity_score(msi_pattern_str_dir)
                        score_mse_dir = _calculate_specificity_score(mse_pattern_str_dir)

                        if score_msi_dir > score_mse_dir:
                            user_decision_is_include_dir = True
                            user_reason_dir = f"Include pattern '{msi_pattern_str_dir}' (score {score_msi_dir}) is more specific than exclude pattern '{mse_pattern_str_dir}' (score {score_mse_dir}) for dir '{relative_dir_path_str}'"
                        elif score_mse_dir > score_msi_dir:
                            user_decision_is_include_dir = False
                            user_reason_dir = f"Exclude pattern '{mse_pattern_str_dir}' (score {score_mse_dir}) is more specific than include pattern '{msi_pattern_str_dir}' (score {score_msi_dir}) for dir '{relative_dir_path_str}'"
                        else:
                            raise ValueError(f"Include pattern '{msi_pattern_str_dir}' and exclude pattern '{mse_pattern_str_dir}' have equal specificity for dir '{relative_dir_path_str}'. Please refine your rules.")
                    elif msi_pattern_str_dir:
                        user_decision_is_include_dir = True
                        user_reason_dir = f"Matches user-specified include pattern: {msi_pattern_str_dir} for dir '{relative_dir_path_str}'"
                    elif mse_pattern_str_dir:
                        user_decision_is_include_dir = False
                        user_reason_dir = f"Matches user-specified exclude pattern: {mse_pattern_str_dir} for dir '{relative_dir_path_str}'"
                    else:
                        user_decision_is_include_dir = None
                        user_reason_dir = f"No user patterns matched for dir '{relative_dir_path_str}'"

                    current_dir_rules_imply_inclusion: bool = False

                    if filter_mode == "default":
                        if user_decision_is_include_dir is not None:
                            current_dir_rules_imply_inclusion = user_decision_is_include_dir
                            reason_for_dir = user_reason_dir
                        else:
                            is_hidden_dir = is_path_hidden(relative_dir_path)
                            default_ignore_match_str_dir = next((p_def for p_def in DEFAULT_IGNORE_PATTERNS if matches_pattern(relative_dir_path_str, p_def)), None) if not no_default_ignore else None
                            if not no_default_ignore and is_hidden_dir:
                                current_dir_rules_imply_inclusion = False
                                reason_for_dir = f"Is a hidden directory: {relative_dir_path_str}"
                            elif default_ignore_match_str_dir:
                                current_dir_rules_imply_inclusion = False
                                reason_for_dir = f"Matches default ignore pattern: {default_ignore_match_str_dir} for dir '{relative_dir_path_str}'"
                            else:
                                if include_patterns:
                                    current_dir_rules_imply_inclusion = False
                                    reason_for_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                                else:
                                    current_dir_rules_imply_inclusion = True
                                    reason_for_dir = f"Included by default (mode: default, dir): {relative_dir_path_str}"
                        log_status_for_dir = "included" if current_dir_rules_imply_inclusion else "excluded"

                    elif filter_mode == "include_first":
                        if user_decision_is_include_dir is True:
                            current_dir_rules_imply_inclusion = True
                            reason_for_dir = user_reason_dir
                        elif user_decision_is_include_dir is False:
                            current_dir_rules_imply_inclusion = False
                            reason_for_dir = user_reason_dir
                        else:
                            current_dir_rules_imply_inclusion = False
                            reason_for_dir = f"Does not match controlling include pattern (mode: include_first, dir): {relative_dir_path_str}"
                            if include_patterns and not msi_pattern_str_dir:
                                reason_for_dir = f"Does not match user-specified include pattern (mode: include_first, dir): {relative_dir_path_str}"
                            elif not include_patterns:
                                reason_for_dir = f"No include patterns provided (mode: include_first implies exclusion for dir): {relative_dir_path_str}"
                        log_status_for_dir = "included" if current_dir_rules_imply_inclusion else "excluded"

                    elif filter_mode == "exclude_first":
                        if user_decision_is_include_dir is False:
                            current_dir_rules_imply_inclusion = False
                            reason_for_dir = user_reason_dir
                        else:
                            is_hidden_dir = is_path_hidden(relative_dir_path)
                            default_ignore_match_str_dir = next((p_def for p_def in DEFAULT_IGNORE_PATTERNS if matches_pattern(relative_dir_path_str, p_def)), None) if not no_default_ignore else None
                            if not no_default_ignore and is_hidden_dir:
                                current_dir_rules_imply_inclusion = False
                                reason_for_dir = f"Is a hidden directory (mode: exclude_first, dir): {relative_dir_path_str}"
                                if user_decision_is_include_dir is True:
                                    reason_for_dir = f"Is a hidden directory (overriding user include '{msi_pattern_str_dir}' due to mode: exclude_first, dir): {relative_dir_path_str}"
                            elif default_ignore_match_str_dir:
                                current_dir_rules_imply_inclusion = False
                                reason_for_dir = f"Matches default ignore pattern: {default_ignore_match_str_dir} (mode: exclude_first, dir) for '{relative_dir_path_str}'"
                                if user_decision_is_include_dir is True:
                                    reason_for_dir = f"Matches default ignore pattern: {default_ignore_match_str_dir} (overriding user include '{msi_pattern_str_dir}' due to mode: exclude_first, dir) for '{relative_dir_path_str}'"
                            else:
                                if user_decision_is_include_dir is True:
                                    current_dir_rules_imply_inclusion = True
                                    reason_for_dir = user_reason_dir
                                elif include_patterns:
                                    current_dir_rules_imply_inclusion = False
                                    reason_for_dir = f"Does not match any user-specified include pattern (directory): {relative_dir_path_str}"
                                else:
                                    current_dir_rules_imply_inclusion = True
                                    reason_for_dir = f"Included by default (mode: exclude_first, dir): {relative_dir_path_str}"
                        log_status_for_dir = "included" if current_dir_rules_imply_inclusion else "excluded"

                    should_traverse_dir = current_dir_rules_imply_inclusion

                    if not should_traverse_dir and include_patterns:
                        needs_traversal_for_descendants = any(
                            p.startswith(relative_dir_path_str + os.sep) or
                            (not p.endswith('/') and ("*" in p or "?" in p or "[" in p) and "/" not in p)
                            for p in include_patterns
                        )
                        if needs_traversal_for_descendants:
                            should_traverse_dir = True
                            if log_status_for_dir == "excluded":
                                reason_for_dir += " (but traversed to find potential descendant matches)"

                    if not should_traverse_dir:
                        stats["excluded_items_count"] += 1
                        log_events.append({"path": relative_dir_path_str, "item_type": "folder", "status": "excluded", "size_kb": dir_size_kb, "reason": reason_for_dir})
                        dirs_to_remove.append(dir_name)
                    else:
                        log_events.append({"path": relative_dir_path_str, "item_type": "folder", "status": log_status_for_dir, "size_kb": dir_size_kb, "reason": reason_for_dir})

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
