# dirdigest/dirdigest/core.py
import os
import pathlib
from typing import Any, Dict, Generator, Iterator, List, Tuple, Optional

# Import OperationalMode and PathState from constants
from dirdigest.constants import DEFAULT_IGNORE_PATTERNS, OperationalMode, PathState
from dirdigest.utils.logger import logger  # Import the configured logger
# Import utility functions from patterns module
from dirdigest.utils.patterns import (
    determine_most_specific_pattern,
    is_path_hidden,
    matches_patterns,
    _get_pattern_properties,
    _compare_specificity
)
# Import LogEvent TypedDict and PatternProperties for type hinting
from dirdigest.constants import LogEvent # PatternProperties is used via utils.patterns
from dirdigest.utils.patterns import PatternProperties


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
    operational_mode: OperationalMode,
    include_patterns: List[str],
    user_exclude_patterns: List[str],
    effective_app_exclude_patterns: List[str],
    no_default_ignore: bool,
    max_depth: int | None,
    follow_symlinks: bool,
    max_size_kb: int,
    ignore_read_errors: bool,
) -> Tuple[Generator[ProcessedItem, None, None], TraversalStats, List[LogEvent]]:
    stats: TraversalStats = {"included_files_count": 0, "excluded_items_count": 0}
    log_events: List[LogEvent] = []
    max_size_bytes = max_size_kb * 1024

    logger.debug(f"Core: Operational Mode: {operational_mode.name}")
    logger.debug(f"Core: User include patterns count: {len(include_patterns)}")
    logger.debug(f"Core: User exclude patterns (for MSE): {len(user_exclude_patterns)}")
    logger.debug(f"Core: Effective app exclude patterns (for actual filtering): {len(effective_app_exclude_patterns)}")

    user_include_patterns_with_indices: List[Tuple[str, int]] = [(p, idx) for idx, p in enumerate(include_patterns)]
    user_exclude_patterns_with_indices: List[Tuple[str, int]] = [(p, idx) for idx, p in enumerate(user_exclude_patterns)]

    def _traverse() -> Generator[ProcessedItem, None, None]:

        # Helper to find the most specific *matching* default pattern properties
        # Moved to _traverse scope to be accessible by both file and dir logic
        def _get_most_specific_matching_default_pattern_props(
            relative_path_str_for_match: str,
            # path_is_dir: bool, # Not strictly needed if patterns like ".*" and ".*/" are distinct in DEFAULT_IGNORE_PATTERNS
            no_default_ignore_flag: bool,
            context_path_obj: pathlib.Path # Absolute path for _get_pattern_properties context
        ) -> Optional[PatternProperties]:
            if no_default_ignore_flag:
                return None

            # DEFAULT_IGNORE_PATTERNS already includes ".*" which covers is_path_hidden implicitly.
            default_patterns_to_check_with_indices: List[Tuple[str, int]] = [
                 (p_str, -20 - idx) for idx, p_str in enumerate(DEFAULT_IGNORE_PATTERNS) # Negative indices for defaults
            ]

            msdr_tuple = determine_most_specific_pattern(default_patterns_to_check_with_indices, relative_path_str_for_match)
            if msdr_tuple:
                return _get_pattern_properties(msdr_tuple[0], context_path_obj, msdr_tuple[1])
            return None

        for root, dirs_orig, files_orig in os.walk(str(base_dir_path), topdown=True, followlinks=follow_symlinks):
            current_root_path = pathlib.Path(root)
            relative_root_path = current_root_path.relative_to(base_dir_path)
            current_depth = len(relative_root_path.parts) if relative_root_path != pathlib.Path(".") else 0

            # --- Process Files first ---
            for file_name in files_orig:
                file_path_obj = current_root_path / file_name
                relative_file_path = relative_root_path / file_name
                relative_file_path_str = str(relative_file_path)

                msi_props_tuple = determine_most_specific_pattern(user_include_patterns_with_indices, relative_file_path_str)
                mse_props_tuple = determine_most_specific_pattern(user_exclude_patterns_with_indices, relative_file_path_str)

                msi_pattern_str = msi_props_tuple[0] if msi_props_tuple else None
                msi_original_idx = msi_props_tuple[1] if msi_props_tuple else -1
                msi_details = _get_pattern_properties(msi_pattern_str, file_path_obj, msi_original_idx)

                mse_pattern_str = mse_props_tuple[0] if mse_props_tuple else None
                mse_original_idx = mse_props_tuple[1] if mse_props_tuple else -1
                mse_details = _get_pattern_properties(mse_pattern_str, file_path_obj, mse_original_idx)

                logger.debug(f"File: {relative_file_path_str}, MSI: {msi_pattern_str}, MSE: {mse_pattern_str}, OpMode: {operational_mode.name}")

                current_path_state = PathState.PENDING_EVALUATION
                decision_reason = ""
                file_attributes: ProcessedItemPayload = {}
                logged_size_kb: Optional[float] = None

                final_relevant_default_rule_props = _get_most_specific_matching_default_pattern_props(
                    relative_file_path_str, no_default_ignore_flag=no_default_ignore, context_path_obj=file_path_obj
                )

                # Symlink check (non-traversal)
                if not follow_symlinks and file_path_obj.is_symlink():
                    current_path_state = PathState.FINAL_EXCLUDED
                    decision_reason = "Is a symlink (symlink following disabled)"

                if current_path_state == PathState.PENDING_EVALUATION:
                    # --- OPERATIONAL MODE LOGIC FOR FILES ---
                    if operational_mode == OperationalMode.MODE_INCLUDE_ALL_DEFAULT:
                        if final_relevant_default_rule_props:
                            current_path_state = PathState.DEFAULT_EXCLUDED
                            decision_reason = f"Matches default ignore rule: {final_relevant_default_rule_props.raw_pattern}"
                        else:
                            current_path_state = PathState.FINAL_INCLUDED
                            decision_reason = "Included by default"
                    elif operational_mode == OperationalMode.MODE_ONLY_INCLUDE:
                        if msi_details:
                            if final_relevant_default_rule_props and \
                               _compare_specificity(file_path_obj, msi_details, final_relevant_default_rule_props, False) < 0: # file path -> False
                                current_path_state = PathState.DEFAULT_EXCLUDED
                                decision_reason = f"MSI '{msi_details.raw_pattern}' overridden by Default Rule '{final_relevant_default_rule_props.raw_pattern}'"
                            else:
                                current_path_state = PathState.FINAL_INCLUDED
                                decision_reason = f"Matches MSI '{msi_details.raw_pattern}'"
                                if final_relevant_default_rule_props:
                                     decision_reason += f" (overrides Default Rule '{final_relevant_default_rule_props.raw_pattern}')"
                        else:
                            current_path_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                            decision_reason = "No matching include pattern (MODE_ONLY_INCLUDE)"
                    elif operational_mode == OperationalMode.MODE_ONLY_EXCLUDE:
                        if mse_details:
                            current_path_state = PathState.USER_EXCLUDED_DIRECTLY
                            decision_reason = f"Matches MSE '{mse_details.raw_pattern}'"
                        elif final_relevant_default_rule_props:
                            current_path_state = PathState.DEFAULT_EXCLUDED
                            decision_reason = f"Matches Default Rule '{final_relevant_default_rule_props.raw_pattern}'"
                        else:
                            current_path_state = PathState.FINAL_INCLUDED
                            decision_reason = "Not excluded by MSE or Default"
                    elif operational_mode == OperationalMode.MODE_INCLUDE_FIRST:
                        if not msi_details:
                            current_path_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                            decision_reason = "No matching MSI (MODE_INCLUDE_FIRST)"
                        else: # MSI exists
                            if mse_details:
                                comparison = _compare_specificity(file_path_obj, msi_details, mse_details, False) # file path -> False
                                if comparison == 0:
                                    current_path_state = PathState.ERROR_CONFLICTING_PATTERNS
                                    decision_reason = f"MSI '{msi_details.raw_pattern}' conflicts with MSE '{mse_details.raw_pattern}'"
                                elif comparison < 0: # MSE is more specific
                                    current_path_state = PathState.USER_EXCLUDED_BY_SPECIFICITY
                                    decision_reason = f"MSE '{mse_details.raw_pattern}' overrides MSI '{msi_details.raw_pattern}'"
                                # If MSI is more specific, it's still PENDING_EVALUATION for default rule check

                            if current_path_state == PathState.PENDING_EVALUATION: # MSI won against MSE or no MSE
                                if final_relevant_default_rule_props and \
                                   _compare_specificity(file_path_obj, msi_details, final_relevant_default_rule_props, False) < 0: # file path -> False
                                    current_path_state = PathState.DEFAULT_EXCLUDED
                                    decision_reason = f"MSI '{msi_details.raw_pattern}' overridden by Default Rule '{final_relevant_default_rule_props.raw_pattern}'"
                                else:
                                    current_path_state = PathState.FINAL_INCLUDED
                                    decision_reason = f"Matches MSI '{msi_details.raw_pattern}'"
                                    if final_relevant_default_rule_props: decision_reason += " (overrides Default Rule)"
                                    if mse_details: decision_reason += f" (and overrides MSE '{mse_details.raw_pattern}')"

                    elif operational_mode == OperationalMode.MODE_EXCLUDE_FIRST:
                        if mse_details:
                            if msi_details and _compare_specificity(file_path_obj, msi_details, mse_details, False) > 0: # MSI rescues # file path -> False
                                current_path_state = PathState.MATCHED_BY_USER_INCLUDE # Tentatively included by rescue
                                decision_reason = f"MSI '{msi_details.raw_pattern}' overrides MSE '{mse_details.raw_pattern}'"
                            elif msi_details and _compare_specificity(file_path_obj, msi_details, mse_details, False) == 0: # Conflict # file path -> False
                                current_path_state = PathState.ERROR_CONFLICTING_PATTERNS
                                decision_reason = f"MSE '{mse_details.raw_pattern}' conflicts with MSI '{msi_details.raw_pattern}'"
                            else: # MSE wins or no MSI
                                current_path_state = PathState.USER_EXCLUDED_DIRECTLY
                                decision_reason = f"Matches MSE '{mse_details.raw_pattern}'"

                        if current_path_state == PathState.PENDING_EVALUATION or current_path_state == PathState.MATCHED_BY_USER_INCLUDE:
                            # Was not excluded by user MSE, or was rescued by MSI. Check default.
                            is_rescued = current_path_state == PathState.MATCHED_BY_USER_INCLUDE
                            if final_relevant_default_rule_props:
                                if msi_details and _compare_specificity(file_path_obj, msi_details, final_relevant_default_rule_props, False) >= 0: # MSI overrides default # file path -> False
                                    current_path_state = PathState.FINAL_INCLUDED
                                    decision_reason += f"; MSI '{msi_details.raw_pattern}' overrides Default Rule '{final_relevant_default_rule_props.raw_pattern}'"
                                else: # Default rule applies (either no MSI, or MSI not specific enough)
                                    current_path_state = PathState.DEFAULT_EXCLUDED
                                    decision_reason += f"; Matches Default Rule '{final_relevant_default_rule_props.raw_pattern}'"
                                    if msi_details: decision_reason += " (MSI not specific enough)"
                            else: # No default rule to exclude
                                current_path_state = PathState.FINAL_INCLUDED
                                decision_reason += "; No default rule conflict"

                            if current_path_state == PathState.FINAL_INCLUDED and user_include_patterns_with_indices and not msi_details and not is_rescued:
                                # If -i flags were used, an item must ultimately match an include rule if it wasn't rescued from an exclude.
                                current_path_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                                decision_reason = "Implicitly excluded (EXCLUDE_FIRST with -i, but no MSI match)"

                if current_path_state == PathState.PENDING_EVALUATION: # Should be resolved by now
                    current_path_state = PathState.FINAL_EXCLUDED
                    decision_reason = "Fell through all logic, defaulted to exclude"

                # Non-pattern based exclusions (size, read errors) for files
                if current_path_state == PathState.FINAL_INCLUDED:
                    try:
                        logged_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                        if logged_size_kb * 1024 > max_size_bytes:
                            current_path_state = PathState.FINAL_EXCLUDED
                            decision_reason = f"Exceeds max size ({logged_size_kb:.1f}KB > {max_size_kb}KB)"
                        else:
                            file_attributes["size_kb"] = logged_size_kb
                    except OSError as e:
                        logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")
                        current_path_state = PathState.FINAL_EXCLUDED
                        decision_reason = f"Error stating file for size: {e}"
                        logged_size_kb = 0.0

                    if current_path_state == PathState.FINAL_INCLUDED:
                        try:
                            with open(file_path_obj, "r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                        except (OSError, UnicodeDecodeError) as e:
                            file_attributes["content"] = None
                            file_attributes["read_error"] = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                current_path_state = PathState.FINAL_EXCLUDED
                                decision_reason = f"Read error (and ignore_read_errors=False): {file_attributes['read_error']}"

                log_status_summary = "included" if current_path_state == PathState.FINAL_INCLUDED else "excluded"
                if current_path_state == PathState.FINAL_INCLUDED: stats["included_files_count"] += 1
                else: stats["excluded_items_count"] += 1

                event: LogEvent = {
                    "path": relative_file_path_str, "item_type": "file", "status": log_status_summary,
                    "state": current_path_state.name, "reason": decision_reason, "msi": msi_pattern_str,
                    "mse": mse_pattern_str, "default_rule": final_relevant_default_rule_props.raw_pattern if final_relevant_default_rule_props else None,
                }
                if logged_size_kb is not None: event["size_kb"] = logged_size_kb
                log_events.append(event)

                if current_path_state == PathState.FINAL_INCLUDED:
                    yield (relative_file_path, "file", file_attributes)

            # --- Filter directories for traversal control ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)

                msi_dir_props_tuple = determine_most_specific_pattern(user_include_patterns_with_indices, relative_dir_path_str)
                mse_dir_props_tuple = determine_most_specific_pattern(user_exclude_patterns_with_indices, relative_dir_path_str)

                msi_dir_pattern_str = msi_dir_props_tuple[0] if msi_dir_props_tuple else None
                msi_dir_original_idx = msi_dir_props_tuple[1] if msi_dir_props_tuple else -1
                msi_dir_details = _get_pattern_properties(msi_dir_pattern_str, dir_path_obj, msi_dir_original_idx)

                mse_dir_pattern_str = mse_dir_props_tuple[0] if mse_dir_props_tuple else None
                mse_dir_original_idx = mse_dir_props_tuple[1] if mse_dir_props_tuple else -1
                mse_dir_details = _get_pattern_properties(mse_dir_pattern_str, dir_path_obj, mse_dir_original_idx)

                logger.debug(f"Dir: {relative_dir_path_str}/, MSI: {msi_dir_pattern_str}, MSE: {mse_dir_pattern_str}, OpMode: {operational_mode.name}")

                current_dir_item_state = PathState.PENDING_EVALUATION
                dir_decision_reason = ""
                final_relevant_default_rule_props_dir = _get_most_specific_matching_default_pattern_props(
                    relative_dir_path_str, no_default_ignore_flag=no_default_ignore, context_path_obj=dir_path_obj
                )

                # Depth and symlink checks for directories (affect traversal)
                # current_depth is the depth of current_root_path. dir_path_obj is one level deeper.
                if max_depth is not None and current_depth >= max_depth :
                    current_dir_item_state = PathState.FINAL_EXCLUDED
                    dir_decision_reason = "Exceeds max depth for traversal (parent at max depth)"
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    current_dir_item_state = PathState.FINAL_EXCLUDED
                    dir_decision_reason = "Is a symlink (symlink following disabled)"

                if current_dir_item_state == PathState.PENDING_EVALUATION:
                    # --- OPERATIONAL MODE LOGIC FOR DIRECTORIES ---
                    if operational_mode == OperationalMode.MODE_INCLUDE_ALL_DEFAULT:
                        if final_relevant_default_rule_props_dir:
                            current_dir_item_state = PathState.DEFAULT_EXCLUDED
                            dir_decision_reason = f"Matches default ignore rule: {final_relevant_default_rule_props_dir.raw_pattern}"
                        else:
                            current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                            dir_decision_reason = "Traverse by default"
                    elif operational_mode == OperationalMode.MODE_ONLY_INCLUDE:
                        if msi_dir_details:
                            # Directory itself matches an include pattern.
                            if final_relevant_default_rule_props_dir and \
                               _compare_specificity(dir_path_obj, msi_dir_details, final_relevant_default_rule_props_dir, True) < 0: # dir path -> True
                                current_dir_item_state = PathState.DEFAULT_EXCLUDED
                                dir_decision_reason = f"MSI '{msi_dir_details.raw_pattern}' overridden by Default '{final_relevant_default_rule_props_dir.raw_pattern}'"
                            else:
                                current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF # MSI match implies traversal (directory itself might not be included if pattern is e.g. "dir/*.txt")
                                dir_decision_reason = f"Matches MSI '{msi_dir_details.raw_pattern}'"
                        else:
                            # Directory itself does not match an MSI. Should we traverse for children?
                            should_traverse_for_children = False
                            for p_str, _ in user_include_patterns_with_indices:
                                # If pattern contains '**', it could match anywhere below.
                                if "**" in p_str:
                                    should_traverse_for_children = True
                                    break
                                # If pattern has no slashes (e.g., "*.txt"), it could match files directly in this dir or subdirs.
                                if "/" not in p_str:
                                    should_traverse_for_children = True
                                    break
                                # If pattern starts with current relative path (e.g. current is "foo", pattern "foo/bar/**")
                                # The relative_dir_path_str is "foo", p_str is "foo/bar/**"
                                # Need to ensure we are checking for a subdirectory or content of current dir.
                                # Path("foo/bar/**").is_relative_to(Path("foo")) is not quite right.
                                # Check if relative_dir_path is an ancestor of p_str's directory part
                                # or if p_str is for a child of relative_dir_path.
                                # A simpler check: if p_str starts with (relative_dir_path_str + os.sep) or is for this dir.
                                # This was the original check: any(p_str.startswith(relative_dir_path_str + "/")
                                # This does not work for "**/utils/" when current dir is "project".

                                # Revised check for children:
                                # If the pattern could apply to children of this directory.
                                # This means the pattern is not anchored to a *different* root path.
                                # e.g., if current_dir = "src", pattern "docs/**" -> don't traverse src for this.
                                # pattern "src/utils/**" -> traverse src.
                                # pattern "common/**" -> traverse src, because "common" could be inside "src".
                                # pattern "*.py" -> traverse src.
                                # pattern "**/foo.py" -> traverse src.

                                # A directory should be traversed if any include pattern:
                                # 1. Is not anchored to a specific path (contains '**' or no '/')
                                # 2. Is anchored under the current directory path.
                                # This means, we prune if ALL include patterns are anchored elsewhere.

                                # Let's try a more permissive approach first: if any include pattern MIGHT match.
                                # Prune only if ALL include patterns are clearly for other unrelated branches.
                                pattern_parts = p_str.split('/')
                                current_dir_parts = relative_dir_path.parts if relative_dir_path != pathlib.Path(".") else []

                                if not pattern_parts: continue

                                if pattern_parts[0] == "**" or pattern_parts[0] == "*": # like **/* or *.txt
                                    should_traverse_for_children = True
                                    break

                                # If pattern is 'foo/bar.txt' and current_dir_parts is ('foo',)
                                # Then pattern_parts[0] ('foo') == current_dir_parts[0] ('foo')
                                # This means the pattern is for this directory or a subdirectory.
                                # If current_dir_parts is empty (we are at root), and pattern_parts[0] is not empty, traverse.
                                if not current_dir_parts and pattern_parts[0]: # e.g. current is root, pattern is "src/..."
                                     should_traverse_for_children = True
                                     break
                                if current_dir_parts and pattern_parts[0] == current_dir_parts[0]: # e.g. current is "src", pattern "src/..."
                                     should_traverse_for_children = True
                                     break
                                # Case: current_dir_parts = ('project',), pattern = 'utils/file.py'
                                # This should also traverse if 'utils' could be a child of 'project'.
                                # The most general way: if a pattern is not anchored to a *different* path from current.
                                # This means if pattern P is 'a/b' and current is 'x/y', prune.
                                # If pattern P is 'a/b' and current is 'a', traverse.
                                # If pattern P is '**/b' and current is 'x/y', traverse.

                            # Fallback to previous broader check for now, needs refinement if still failing.
                            # The original check was too strict. This is slightly less strict.
                            # A dir is traversed if any include pattern *could* apply to its descendants.
                            # This means the pattern is not anchored to a path that *cannot* be a descendant.
                            if not should_traverse_for_children: # if previous specific checks didn't confirm
                                for p_str, _ in user_include_patterns_with_indices:
                                    if "**" in p_str or "/" not in p_str: # Non-anchored or filename globs
                                        should_traverse_for_children = True
                                        break
                                    # If p_str is 'a/b/c' and relative_dir_path_str is 'a/b', then traverse.
                                    # If p_str is 'a/b/c' and relative_dir_path_str is 'a', then traverse.
                                    # If p_str is 'a/b/c' and relative_dir_path_str is 'd', then don't.
                                    # This is equivalent to: is relative_dir_path_str an ancestor of p_str's dir part?
                                    # Or, more simply, does p_str start with relative_dir_path_str? (for anchored parts)
                                    # Or, if relative_dir_path_str is ".", does p_str not contain unrelated root?
                                    if relative_dir_path_str == ".": # current dir is scan root
                                        should_traverse_for_children = True # Any anchored pattern is relevant from root
                                        break
                                    if p_str.startswith(relative_dir_path_str + "/"):
                                        should_traverse_for_children = True
                                        break

                            if should_traverse_for_children:
                                current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                                dir_decision_reason = "Traversing for potential child MSI match (MODE_ONLY_INCLUDE)"
                            else:
                                current_dir_item_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                                dir_decision_reason = "No MSI for dir or children, and no include pattern could apply to children (MODE_ONLY_INCLUDE)"
                    elif operational_mode == OperationalMode.MODE_ONLY_EXCLUDE:
                        if mse_dir_details:
                            current_dir_item_state = PathState.USER_EXCLUDED_DIRECTLY
                            dir_decision_reason = f"Matches MSE '{mse_dir_details.raw_pattern}'"
                        elif final_relevant_default_rule_props_dir:
                            current_dir_item_state = PathState.DEFAULT_EXCLUDED
                            dir_decision_reason = f"Matches Default Rule '{final_relevant_default_rule_props_dir.raw_pattern}'"
                        else:
                            current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                            dir_decision_reason = "Not excluded"
                    elif operational_mode == OperationalMode.MODE_INCLUDE_FIRST:
                        # Must have an MSI for the dir, or an MSI that could match a child.
                        should_traverse_for_children_if_if = False
                        if not msi_dir_details: # If dir itself isn't matched by an include
                            for p_str, _ in user_include_patterns_with_indices:
                                # Similar logic to MODE_ONLY_INCLUDE for child traversal potential
                                if "**" in p_str or "/" not in p_str:
                                    should_traverse_for_children_if_if = True
                                    break
                                if relative_dir_path_str == ".":
                                    should_traverse_for_children_if_if = True
                                    break
                                if p_str.startswith(relative_dir_path_str + "/"):
                                    should_traverse_for_children_if_if = True
                                    break

                            if should_traverse_for_children_if_if:
                                current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                                dir_decision_reason = "Traversing for child MSI (MODE_INCLUDE_FIRST)"
                            else:
                                current_dir_item_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                                dir_decision_reason = "No MSI for dir or children, and no include pattern could apply to children (MODE_INCLUDE_FIRST)"
                        else: # MSI for dir exists
                            if mse_dir_details:
                                comparison = _compare_specificity(dir_path_obj, msi_dir_details, mse_dir_details, True) # dir path -> True
                                if comparison == 0: current_dir_item_state = PathState.ERROR_CONFLICTING_PATTERNS
                                elif comparison < 0: current_dir_item_state = PathState.USER_EXCLUDED_BY_SPECIFICITY
                            if current_dir_item_state == PathState.PENDING_EVALUATION: # MSI won or no MSE
                                if final_relevant_default_rule_props_dir and \
                                   _compare_specificity(dir_path_obj, msi_dir_details, final_relevant_default_rule_props_dir, True) < 0: # dir path -> True
                                    current_dir_item_state = PathState.DEFAULT_EXCLUDED
                                else: current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                            dir_decision_reason = f"MSI: {msi_dir_pattern_str}, MSE: {mse_dir_pattern_str}, Default: {final_relevant_default_rule_props_dir.raw_pattern if final_relevant_default_rule_props_dir else 'N/A'}"
                    elif operational_mode == OperationalMode.MODE_EXCLUDE_FIRST:
                        temp_state = PathState.PENDING_EVALUATION
                        if mse_dir_details:
                            if msi_dir_details and _compare_specificity(dir_path_obj, msi_dir_details, mse_dir_details, True) > 0: # dir path -> True
                                temp_state = PathState.MATCHED_BY_USER_INCLUDE # Rescued
                            elif msi_dir_details and _compare_specificity(dir_path_obj, msi_dir_details, mse_dir_details, True) == 0: # dir path -> True
                                temp_state = PathState.ERROR_CONFLICTING_PATTERNS
                            else: temp_state = PathState.USER_EXCLUDED_DIRECTLY
                        if temp_state == PathState.PENDING_EVALUATION or temp_state == PathState.MATCHED_BY_USER_INCLUDE:
                            if final_relevant_default_rule_props_dir:
                                if msi_dir_details and _compare_specificity(dir_path_obj, msi_dir_details, final_relevant_default_rule_props_dir, True) >= 0: # dir path -> True
                                    current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                                else: current_dir_item_state = PathState.DEFAULT_EXCLUDED
                            else: current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                            if current_dir_item_state == PathState.TRAVERSE_BUT_EXCLUDE_SELF and user_include_patterns_with_indices and not msi_dir_details:
                                if not any(p_str.startswith(relative_dir_path_str + "/") for p_str, _ in user_include_patterns_with_indices):
                                    current_dir_item_state = PathState.IMPLICITLY_EXCLUDED_FINAL_STEP
                        else: current_dir_item_state = temp_state
                        dir_decision_reason = f"MSE: {mse_dir_pattern_str}, MSI: {msi_dir_pattern_str}, Default: {final_relevant_default_rule_props_dir.raw_pattern if final_relevant_default_rule_props_dir else 'N/A'}"

                if current_dir_item_state == PathState.PENDING_EVALUATION: # Fallback
                    current_dir_item_state = PathState.TRAVERSE_BUT_EXCLUDE_SELF
                    dir_decision_reason = "Defaulted to traverse (fallback)"

                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks)
                log_status_summary_dir = "traversed"
                should_prune_dir = False

                if current_dir_item_state not in [PathState.TRAVERSE_BUT_EXCLUDE_SELF, PathState.FINAL_INCLUDED, PathState.MATCHED_BY_USER_INCLUDE]:
                    should_prune_dir = True
                    log_status_summary_dir = "excluded"
                    if current_dir_item_state != PathState.ERROR_CONFLICTING_PATTERNS : # Don't double count if already error
                         stats["excluded_items_count"] += 1

                event_dir: LogEvent = {
                    "path": relative_dir_path_str, "item_type": "folder", "status": log_status_summary_dir,
                    "state": current_dir_item_state.name, "reason": dir_decision_reason, "msi": msi_dir_pattern_str,
                    "mse": mse_dir_pattern_str, "default_rule": final_relevant_default_rule_props_dir.raw_pattern if final_relevant_default_rule_props_dir else None,
                    "size_kb": dir_size_kb
                }
                log_events.append(event_dir)

                if should_prune_dir:
                    dirs_to_remove.append(dir_name)

            if dirs_to_remove:
                dirs_orig[:] = [d for d in dirs_orig if d not in dirs_to_remove]

    return _traverse(), stats, log_events

# ... (build_digest_tree remains the same)
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
                    (child for child in current_level_children if child["relative_path"] == str(current_path_so_far) and child["type"] == "folder"), None,
                )
                if not folder_node:
                    folder_node = {"relative_path": str(current_path_so_far), "type": "folder", "children": []}
                    current_level_children.append(folder_node)
                current_level_children = folder_node["children"]
            file_node: DigestItemNode = {
                "relative_path": str(relative_path), "type": "file", "size_kb": attributes.get("size_kb", 0.0),
            }
            if "content" in attributes: file_node["content"] = attributes["content"]
            if attributes.get("read_error"): file_node["read_error"] = attributes["read_error"]
            current_level_children.append(file_node)

    def sort_children_recursive(node: DigestItemNode):
        if node.get("type") == "folder" and "children" in node:
            folders = sorted([c for c in node["children"] if c["type"] == "folder"], key=lambda x: x["relative_path"])
            files = sorted([c for c in node["children"] if c["type"] == "file"], key=lambda x: x["relative_path"])
            node["children"] = folders + files
            for child in node["children"]: sort_children_recursive(child)
    sort_children_recursive(root_node)

    final_metadata = {
        "base_directory": str(base_dir_path.resolve()),
        "included_files_count": initial_stats.get("included_files_count", 0),
        "excluded_items_count": initial_stats.get("excluded_items_count", 0),
        "total_content_size_kb": round(current_total_content_size_kb, 3),
    }
    logger.debug(f"build_digest_tree returning metadata: {final_metadata}")
    return root_node, final_metadata
