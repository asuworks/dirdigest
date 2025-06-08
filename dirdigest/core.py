# dirdigest/dirdigest/core.py
import os
import pathlib
from typing import Any, Dict, Generator, Iterator, List, Tuple

from dirdigest.constants import DEFAULT_IGNORE_PATTERNS
from dirdigest.utils.logger import logger  # Import the configured logger
from dirdigest.utils.patterns import is_path_hidden, matches_patterns

# Type hints for clarity
LogEvent = Dict[str, Any]  # Added type hint for log events
DigestItemNode = Dict[str, Any]
ProcessedItemPayload = Dict[str, Any]
ProcessedItem = Tuple[pathlib.Path, str, ProcessedItemPayload]
TraversalStats = Dict[str, int]


def _get_dir_size(dir_path_obj: pathlib.Path, follow_symlinks: bool) -> float:
    """Recursively calculates the total size of all files within a given directory."""
    total_size_bytes = 0
    try:
        for root, _, files in os.walk(str(dir_path_obj), topdown=True, followlinks=follow_symlinks):
            for name in files:
                file_path = pathlib.Path(root) / name
                # Check if it's a symlink and if we are not following them
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
) -> Tuple[Generator[ProcessedItem, None, None], TraversalStats, List[LogEvent]]:  # Modified return type
    """
    Recursively traverses a directory, filters files and folders,
    and yields processed file items along with collected traversal statistics
    and a list of log events.
    """
    stats: TraversalStats = {
        "included_files_count": 0,
        "excluded_items_count": 0,
    }
    log_events: List[LogEvent] = []  # Initialize log_events list

    max_size_bytes = max_size_kb * 1024
    effective_exclude_patterns = list(exclude_patterns)  # Start with user-defined excludes
    if not no_default_ignore:
        effective_exclude_patterns.extend(DEFAULT_IGNORE_PATTERNS)

    logger.debug(f"Core: Effective exclude patterns count: {len(effective_exclude_patterns)}")
    logger.debug(f"Core: Max size KB: {max_size_kb}, Ignore read errors: {ignore_read_errors}")
    logger.debug(f"Core: Follow symlinks: {follow_symlinks}, No default ignore: {no_default_ignore}")

    def _traverse() -> Generator[ProcessedItem, None, None]:
        """Nested generator function to handle the actual traversal and yielding."""
        for root, dirs_orig, files_orig in os.walk(str(base_dir_path), topdown=True, followlinks=follow_symlinks):
            current_root_path = pathlib.Path(root)
            relative_root_path = current_root_path.relative_to(base_dir_path)
            current_depth = len(relative_root_path.parts) if relative_root_path != pathlib.Path(".") else 0

            # --- Process Files first for the current directory ---
            for file_name in files_orig:
                file_path_obj = current_root_path / file_name
                relative_file_path = relative_root_path / file_name
                relative_file_path_str = str(relative_file_path)
                file_attributes: ProcessedItemPayload = {}
                current_file_size_kb = 0.0
                is_included = False  # Default to excluded
                reason = ""

                try:
                    # Symlink size is 0 if not followed, otherwise actual size
                    if file_path_obj.is_symlink() and not follow_symlinks:
                        current_file_size_kb = 0.0
                    else:
                        # For actual files or followed symlinks, get their size
                        current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")
                    # If stat fails, treat as 0 size for now, exclusion reason will be set later if applicable
                    current_file_size_kb = 0.0


                # 1. Calculate all matching conditions first
                matches_user_include_original = matches_patterns(relative_file_path_str, include_patterns)
                matches_user_include = matches_user_include_original
                if not matches_user_include and include_patterns:
                    for p in include_patterns:
                        if p.endswith('/') and relative_file_path_str.startswith(p):
                            matches_user_include = True
                            break

                matches_user_exclude = matches_patterns(relative_file_path_str, exclude_patterns)
                is_symlink_and_not_followed = not follow_symlinks and file_path_obj.is_symlink()
                is_hidden_and_not_default_ignored = is_path_hidden(relative_file_path) and not no_default_ignore
                matches_default_exclude = not no_default_ignore and matches_patterns(
                    relative_file_path_str, DEFAULT_IGNORE_PATTERNS
                )

                is_hidden_and_not_default_ignored = is_path_hidden(relative_file_path) and not no_default_ignore
                matches_default_exclude = not no_default_ignore and matches_patterns(
                    relative_file_path_str, DEFAULT_IGNORE_PATTERNS
                )

                # 2. Apply new precedence rules
                if matches_user_include:
                    is_included = True
                    reason = "Matches user-specified include pattern"
                elif is_symlink_and_not_followed:
                    is_included = False
                    reason = "Is a symlink (symlink following disabled)"
                elif matches_user_exclude:
                    is_included = False
                    reason = "Matches user-specified exclude pattern"
                elif is_hidden_and_not_default_ignored:
                    is_included = False
                    reason = "Is a hidden file"
                elif matches_default_exclude:
                    is_included = False
                    reason = "Matches default ignore pattern"
                elif include_patterns: # User provided include patterns, but this file didn't match any
                    is_included = False
                    reason = "Does not match any include pattern"
                else: # Default include (no include patterns provided, and not excluded by other rules)
                    is_included = True
                    # No specific reason needed for default inclusion unless overridden by include_patterns
                    reason = "Default inclusion" if not include_patterns else None


                # 3. Handle outcome (size checks, read errors, and logging)
                if is_included:
                    file_attributes["size_kb"] = current_file_size_kb
                    if current_file_size_kb * 1024 > max_size_bytes:
                        is_included = False
                        reason = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB)"
                    else:
                        try:
                            # For symlinks, if follow_symlinks is true, file_path_obj.open() will open the target.
                            # If follow_symlinks is false, symlinks are already excluded by is_symlink_and_not_followed.
                            with file_path_obj.open("r", encoding="utf-8", errors="strict") as f:
                                file_attributes["content"] = f.read()
                            file_attributes["read_error"] = None
                            # reason remains as why it was included (e.g. "Matches user-specified include pattern")
                        except (OSError, UnicodeDecodeError) as e:
                            error_reason_str = f"{type(e).__name__}: {e}"
                            if not ignore_read_errors:
                                is_included = False
                                reason = error_reason_str
                            else:
                                # Included, but with read error noted
                                file_attributes["content"] = None
                                file_attributes["read_error"] = error_reason_str
                                # reason might still be "Matches user-specified include pattern", which is fine.

                if is_included:
                    stats["included_files_count"] += 1
                    log_events.append(
                        {
                            "path": relative_file_path_str,
                            "item_type": "file",
                            "status": "included",
                            "size_kb": current_file_size_kb,
                            # Reason here should reflect why it was included, or None if default
                            "reason": reason if reason != "Default inclusion" else None,
                        }
                    )
                    yield (relative_file_path, "file", file_attributes)
                else:
                    stats["excluded_items_count"] += 1
                    log_events.append(
                        {
                            "path": relative_file_path_str,
                            "item_type": "file",
                            "status": "excluded",
                            "size_kb": current_file_size_kb,
                            "reason": reason,
                        }
                    )
                    # The 'continue' is implicit as we won't yield if not included

            # --- Now, filter directories for traversal control ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks) # Calculate size regardless
                is_included_for_traversal = False  # Default to not traverse
                reason_dir_activity = "" # Can be reason for inclusion or exclusion

                # 1. Calculate all matching conditions
                # Note: For directories, include_patterns matching means "allow traversal further, and also explicitly include this dir if it were a file"
                # Exclude patterns for dirs mean "do not traverse and explicitly exclude".
                matches_user_include_dir = matches_patterns(relative_dir_path_str, include_patterns)
                matches_user_exclude_dir_raw = matches_patterns(relative_dir_path_str, exclude_patterns) # Using specific user excludes
                exceeds_max_depth = max_depth is not None and current_depth >= max_depth
                is_symlink_dir_and_not_followed = not follow_symlinks and dir_path_obj.is_symlink()
                is_hidden_dir_and_not_default_ignored = is_path_hidden(relative_dir_path) and not no_default_ignore
                matches_default_exclude_dir = not no_default_ignore and matches_patterns(
                    relative_dir_path_str, DEFAULT_IGNORE_PATTERNS
                )

                # 2. Apply new precedence rules for directory traversal
                if matches_user_include_dir:
                    is_included_for_traversal = True
                    reason_dir_activity = "Matches user-specified include pattern (traversal allowed)"
                elif exceeds_max_depth:
                    # is_included_for_traversal remains False
                    reason_dir_activity = "Exceeds max depth"
                elif is_symlink_dir_and_not_followed:
                    # is_included_for_traversal remains False
                    reason_dir_activity = "Is a symlink (symlink following disabled)"
                elif matches_user_exclude_dir_raw:
                    # If the directory itself matches a user exclude, check if any user include pattern
                    # targets a descendant. If so, we must traverse this directory.
                    should_traverse_for_descendant_include = False
                    if include_patterns: # Only relevant if there are include patterns
                        # Convert relative_dir_path to Path object for easier comparison
                        current_dir_path_obj_for_check = pathlib.Path(relative_dir_path_str)
                        for inc_pattern_str in include_patterns:
                            # Check if inc_pattern_str is a descendant of relative_dir_path_str
                            # A simple way: check if inc_pattern_str starts with relative_dir_path_str + "/"
                            # Or if inc_pattern_str is a direct file/subdir in relative_dir_path_str
                            # pathlib.Path(inc_pattern_str).parent can be tricky if inc_pattern_str is like "file.txt" (parent is '.')
                            # A robust check: is current_dir_path_obj_for_check an ancestor of pathlib.Path(inc_pattern_str)?
                            inc_path_obj = pathlib.Path(inc_pattern_str)
                            if current_dir_path_obj_for_check in inc_path_obj.parents:
                                should_traverse_for_descendant_include = True
                                break
                            # Also handle if include pattern is for the dir itself, e.g. "config/" and current dir is "config"
                            # This case should already be handled by `matches_user_include_dir` taking precedence.
                            # This check is specifically for *descendants*.

                    if should_traverse_for_descendant_include:
                        is_included_for_traversal = True # Override exclusion to find included descendant
                        # Reason indicates it's traversed to find specific includes, but otherwise excluded.
                        # Files/subdirs within will then be re-evaluated.
                        # The directory itself won't be "included" in the output digest unless it also matches an include pattern.
                        reason_dir_activity = (
                            f"Traversal allowed to find descendants matching include patterns, "
                            f"though directory itself matches exclude pattern: {relative_dir_path_str}"
                        )
                    else:
                        # is_included_for_traversal remains False
                        reason_dir_activity = "Matches user-specified exclude pattern"
                elif is_hidden_dir_and_not_default_ignored:
                    # is_included_for_traversal remains False
                    reason_dir_activity = "Is a hidden directory"
                elif matches_default_exclude_dir:
                    # is_included_for_traversal remains False
                    reason_dir_activity = "Matches default ignore pattern"
                elif include_patterns:  # Check for "implied exclude" for directories
                    has_glob_include = any("*" in p or "?" in p or "[" in p for p in include_patterns)
                    # The 'matches_user_include_dir' check is implicitly part of the 'if/elif' chain already.
                    # If matches_user_include_dir was true, we wouldn't be in this elif branch.
                    if not has_glob_include:
                        # is_included_for_traversal remains False by default if not previously set true
                        reason_dir_activity = "Does not match any include pattern (directory)"
                    else:
                        # If there's a glob include, we don't prune here by "Does not match..."
                        # It might still be False if not set by a preceding rule.
                        # If no other rule has set is_included_for_traversal to True or False with a reason,
                        # and we have glob includes, we default to traversing.
                        if not reason_dir_activity and not is_included_for_traversal: # only if no decision made yet
                           is_included_for_traversal = True
                           reason_dir_activity = "Traversal allowed due to active glob include patterns"
                        # If is_included_for_traversal is already True (e.g. from descendant include logic overriding user_exclude_dir_raw),
                        # keep that decision and its reason.

                else:  # Default include for traversal (no include_patterns provided)
                    is_included_for_traversal = True
                    reason_dir_activity = "Traversal allowed by default"

                # 3. Handle outcome
                if not is_included_for_traversal:
                    stats["excluded_items_count"] += 1
                    log_events.append({
                        "path": relative_dir_path_str,
                        "item_type": "folder",
                        "status": "excluded",
                        "size_kb": dir_size_kb,
                        "reason": reason_dir_activity, # This is the exclusion reason
                    })
                    dirs_to_remove.append(dir_name)
                else:
                    # Logged as "included" meaning it's included for traversal
                    log_events.append({
                        "path": relative_dir_path_str,
                        "item_type": "folder",
                        "status": "included",
                        "size_kb": dir_size_kb,
                        "reason": reason_dir_activity, # This is the inclusion reason
                    })

            # Prune directories from os.walk traversal by modifying dirs_orig in-place
            if dirs_to_remove:
                dirs_orig[:] = [d for d in dirs_orig if d not in dirs_to_remove]

    return _traverse(), stats, log_events


def build_digest_tree(
    base_dir_path: pathlib.Path,
    processed_items_generator: Iterator[ProcessedItem],
    initial_stats: TraversalStats,
    # log_events: List[LogEvent] # Potentially pass log_events if needed here
) -> Tuple[DigestItemNode, Dict[str, Any]]:
    """
    Builds the hierarchical tree structure from the flat list of processed file items
    and combines traversal statistics into final metadata.
    """
    root_node: DigestItemNode = {"relative_path": ".", "type": "folder", "children": []}
    current_total_content_size_kb = 0.0

    for relative_path, item_type, attributes in processed_items_generator:
        # This function currently only processes "file" items from the generator
        # to build the tree. Directories are implicitly created.
        if item_type == "file":
            if attributes.get("size_kb") is not None:
                current_total_content_size_kb += attributes["size_kb"]

            parts = list(relative_path.parts)
            current_level_children = root_node["children"]
            current_path_so_far = pathlib.Path(".")

            # Create parent directory nodes as needed
            for i, part_name in enumerate(parts[:-1]):
                current_path_so_far = current_path_so_far / part_name
                folder_node = next(
                    (
                        child
                        for child in current_level_children
                        if child["relative_path"] == str(current_path_so_far) and child["type"] == "folder"
                    ),
                    None,
                )
                if not folder_node:
                    folder_node = {
                        "relative_path": str(current_path_so_far),
                        "type": "folder",
                        "children": [],
                    }
                    current_level_children.append(folder_node)
                current_level_children = folder_node["children"]

            # Add the file node
            file_node: DigestItemNode = {
                "relative_path": str(relative_path),
                "type": "file",
                "size_kb": attributes.get("size_kb", 0.0),
            }
            if "content" in attributes:  # Content could be None
                file_node["content"] = attributes["content"]
            if attributes.get("read_error"):
                file_node["read_error"] = attributes["read_error"]

            current_level_children.append(file_node)

    def sort_children_recursive(node: DigestItemNode):
        """Sorts children of a node by type (folders then files), then by relative_path."""
        if node.get("type") == "folder" and "children" in node:
            # Separate children into folders and files to sort them independently
            folders = sorted(
                [c for c in node["children"] if c["type"] == "folder"],
                key=lambda x: x["relative_path"],
            )
            files = sorted(
                [c for c in node["children"] if c["type"] == "file"],
                key=lambda x: x["relative_path"],
            )

            # Combine them, folders first, then files
            node["children"] = folders + files

            for child in node["children"]:
                sort_children_recursive(child)

    sort_children_recursive(root_node)

    # Prepare final metadata for output formatters
    final_metadata = {
        "base_directory": str(base_dir_path.resolve()),
        "included_files_count": initial_stats.get("included_files_count", 0),
        "excluded_items_count": initial_stats.get("excluded_items_count", 0),
        "total_content_size_kb": round(current_total_content_size_kb, 3),
    }
    logger.debug(f"build_digest_tree returning metadata: {final_metadata}")

    return root_node, final_metadata
