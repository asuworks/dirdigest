# dirdigest/dirdigest/core.py
import os
import pathlib
from typing import Any, Generator, Tuple, List, Dict

from dirdigest.constants import DEFAULT_IGNORE_PATTERNS
from dirdigest.utils.patterns import matches_patterns, is_path_hidden
from dirdigest.utils.logger import logger  # Import the configured logger

# Type hints for clarity
DigestItemNode = Dict[str, Any]
ProcessedItemPayload = Dict[str, Any] # Now may include status, reason_excluded
# ProcessedItem: relative_path, item_type, status, payload
ProcessedItem = Tuple[pathlib.Path, str, str, ProcessedItemPayload]
TraversalStats = Dict[str, int]


def process_directory_recursive(
    base_dir_path: pathlib.Path,
    include_patterns: List[str],
    exclude_patterns: List[str],
    no_default_ignore: bool,
    max_depth: int | None,
    follow_symlinks: bool,
    max_size_kb: int,
    ignore_read_errors: bool,
) -> Tuple[Generator[ProcessedItem, None, None], TraversalStats]:
    """
    Recursively traverses a directory, filters files and folders,
    and yields processed items (both included and excluded) along with collected traversal statistics.
    """
    stats: TraversalStats = {
        "included_files_count": 0, # Number of files successfully read and included
        "excluded_items_count": 0, # Number of files and directories explicitly excluded by a rule or error
        # Note: total_processed_items could be derived from len(list(generator_output)) if needed later.
    }

    max_size_bytes = max_size_kb * 1024
    effective_exclude_patterns = list(
        exclude_patterns
    )  # Start with user-defined excludes
    if not no_default_ignore:
        effective_exclude_patterns.extend(DEFAULT_IGNORE_PATTERNS)

    logger.debug(
        f"Core: Effective exclude patterns count: {len(effective_exclude_patterns)}"
    )
    logger.debug(
        f"Core: Max size KB: {max_size_kb}, Ignore read errors: {ignore_read_errors}"
    )
    logger.debug(
        f"Core: Follow symlinks: {follow_symlinks}, No default ignore: {no_default_ignore}"
    )

    def _traverse() -> Generator[ProcessedItem, None, None]:
        """Nested generator function to handle the actual traversal and yielding."""
        for root, dirs_orig, files_orig in os.walk(
            str(base_dir_path), topdown=True, followlinks=follow_symlinks
        ):
            current_root_path = pathlib.Path(root)
            relative_root_path = current_root_path.relative_to(base_dir_path)
            current_depth = (
                len(relative_root_path.parts)
                if relative_root_path != pathlib.Path(".")
                else 0
            )
            logger.debug(
                f"Walking: [log.path]{current_root_path}[/log.path], "
                f"Rel: [log.path]{relative_root_path}[/log.path], Depth: {current_depth}"
            )

            # --- Depth Filtering ---
            if max_depth is not None and current_depth >= max_depth:
                logger.info(
                    f"Max depth ({max_depth}) reached at [log.path]{relative_root_path}[/log.path], "
                    f"pruning its {len(dirs_orig)} subdirectories."
                )
                if dirs_orig:
                    for pruned_dir_name in dirs_orig:
                        pruned_dir_relative_path = relative_root_path / pruned_dir_name
                        logger.debug(
                            f"[log.excluded]Excluded directory (due to depth)[/log.excluded]: "
                            f"[log.path]{pruned_dir_relative_path}[/log.path] "
                            f"([log.reason]Exceeds max depth[/log.reason])"
                        )
                        stats["excluded_items_count"] += 1
                        yield (
                            pruned_dir_relative_path,
                            "folder",
                            "excluded",
                            {"reason_excluded": "Exceeds max depth", "size_kb": 0.0},
                        )
                dirs_orig[:] = []  # Prevent descent

            # --- Directory Filtering ---
            dirs_to_traverse_next = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                reason_dir_excluded = ""

                if not follow_symlinks and dir_path_obj.is_symlink():
                    reason_dir_excluded = "Is a symlink (symlink following disabled)"
                elif is_path_hidden(relative_dir_path) and not no_default_ignore:
                    reason_dir_excluded = "Is a hidden directory"
                elif matches_patterns(
                    relative_dir_path_str, effective_exclude_patterns
                ):
                    reason_dir_excluded = (
                        "Matches an exclude pattern"  # TODO: Log which pattern
                    )

                if reason_dir_excluded:
                    logger.info(
                        f"[log.excluded]Excluded directory[/log.excluded]: "
                        f"[log.path]{relative_dir_path_str}[/log.path] "
                        f"([log.reason]{reason_dir_excluded}[/log.reason])"
                    )
                    stats["excluded_items_count"] += 1
                    yield (
                        relative_dir_path,
                        "folder",
                        "excluded",
                        {"reason_excluded": reason_dir_excluded, "size_kb": 0.0},
                    )
                    continue
                dirs_to_traverse_next.append(dir_name)
            dirs_orig[:] = dirs_to_traverse_next

            # --- File Filtering and Content Reading ---
            for file_name in files_orig:
                file_path_obj = current_root_path / file_name
                relative_file_path = relative_root_path / file_name
                relative_file_path_str = str(relative_file_path)
                file_attributes: ProcessedItemPayload = {}
                reason_file_excluded = ""

                # Determine exclusion reason
                if not follow_symlinks and file_path_obj.is_symlink():
                    reason_file_excluded = "Is a symlink (symlink following disabled)"
                elif is_path_hidden(relative_file_path) and not no_default_ignore:
                    reason_file_excluded = "Is a hidden file"
                elif matches_patterns(
                    relative_file_path_str, exclude_patterns
                ):  # User excludes
                    reason_file_excluded = "Matches user-specified exclude pattern"  # TODO: specific pattern
                elif not no_default_ignore and matches_patterns(
                    relative_file_path_str,
                    DEFAULT_IGNORE_PATTERNS,  # Default excludes
                ):
                    reason_file_excluded = (
                        "Matches default ignore pattern"  # TODO: specific pattern
                    )
                elif include_patterns and not matches_patterns(
                    relative_file_path_str,
                    include_patterns,  # User includes
                ):
                    reason_file_excluded = "Does not match any include pattern"

                if reason_file_excluded:
                    logger.info(
                        f"[log.excluded]Excluded file[/log.excluded]: "
                        f"[log.path]{relative_file_path_str}[/log.path] "
                        f"([log.reason]{reason_file_excluded}[/log.reason])"
                    )
                    stats["excluded_items_count"] += 1
                    # Try to get size even for pattern-excluded files if possible
                    try:
                        excluded_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                    except OSError:
                        excluded_file_size_kb = 0.0
                    yield (
                        relative_file_path,
                        "file",
                        "excluded",
                        {
                            "reason_excluded": reason_file_excluded,
                            "size_kb": excluded_file_size_kb,
                        },
                    )
                    continue

                # Attempt to process file if not excluded by patterns
                try:
                    file_stat = file_path_obj.stat()  # Stat once
                    file_size_bytes = file_stat.st_size
                    actual_size_kb = round(file_size_bytes / 1024, 3)
                    file_attributes["size_kb"] = actual_size_kb

                    if file_size_bytes > max_size_bytes:
                        reason_max_size = f"Exceeds max size ({actual_size_kb:.1f}KB > {max_size_kb}KB)"
                        logger.info(
                            f"[log.excluded]Excluded file[/log.excluded]: "
                            f"[log.path]{relative_file_path_str}[/log.path] "
                            f"([log.reason]{reason_max_size}[/log.reason])"
                        )
                        stats["excluded_items_count"] += 1
                        yield (
                            relative_file_path,
                            "file",
                            "excluded",
                            {
                                "reason_excluded": reason_max_size,
                                "size_kb": actual_size_kb,
                            },
                        )
                        continue

                    logger.debug(
                        f"    Reading content for: [log.path]{relative_file_path_str}[/log.path]"
                    )
                    with open(
                        file_path_obj, "r", encoding="utf-8", errors="strict"
                    ) as f:
                        file_attributes["content"] = f.read()
                    file_attributes["read_error"] = None

                except OSError as e:
                    logger.warning(
                        f"Read error for [log.path]{relative_file_path_str}[/log.path]: {e}"
                    )
                    if not ignore_read_errors:
                        reason_os_error = (
                            f"OS read error (and ignore_errors=False): {e}"
                        )
                        logger.info(
                            f"[log.excluded]Excluded file[/log.excluded]: "
                            f"[log.path]{relative_file_path_str}[/log.path] "
                            f"([log.reason]{reason_os_error}[/log.reason])"
                        )
                        stats["excluded_items_count"] += 1
                        # Try to get size even for error-excluded files
                        try:
                            error_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                        except OSError:
                            error_file_size_kb = 0.0
                        yield (
                            relative_file_path,
                            "file",
                            "excluded",
                            {
                                "reason_excluded": reason_os_error,
                                "size_kb": error_file_size_kb,
                            },
                        )
                        continue
                    # If ignore_read_errors is True, we mark as included but with an error
                    file_attributes["content"] = None # No content available
                    file_attributes["read_error"] = str(e)
                    if "size_kb" not in file_attributes:  # if stat() also failed
                        try:
                            file_attributes["size_kb"] = round(
                                file_path_obj.stat().st_size / 1024, 3
                            )
                        except OSError:
                            file_attributes["size_kb"] = 0.0 # Default if size cannot be determined

                except UnicodeDecodeError as e:
                    logger.warning(
                        f"Unicode decode error for [log.path]{relative_file_path_str}[/log.path]. "
                        f"File may be binary or use an unexpected encoding."
                    )
                    if not ignore_read_errors:
                        reason_unicode_error = (
                            f"UnicodeDecodeError (and ignore_errors=False): {e}"
                        )
                        logger.info(
                            f"[log.excluded]Excluded file[/log.excluded]: "
                            f"[log.path]{relative_file_path_str}[/log.path] "
                            f"([log.reason]{reason_unicode_error}[/log.reason])"
                        )
                        stats["excluded_items_count"] += 1
                        try:
                            unicode_error_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                        except OSError:
                            unicode_error_file_size_kb = 0.0
                        yield (
                            relative_file_path,
                            "file",
                            "excluded",
                            {
                                "reason_excluded": reason_unicode_error,
                                "size_kb": unicode_error_file_size_kb,
                            },
                        )
                        continue
                    # If ignore_read_errors is True, we mark as included but with an error
                    file_attributes["content"] = None # No content available
                    file_attributes["read_error"] = f"UnicodeDecodeError: {e}"
                    if "size_kb" not in file_attributes:  # if stat() failed
                        try:
                            file_attributes["size_kb"] = round(
                                file_path_obj.stat().st_size / 1024, 3
                            )
                        except OSError:
                            file_attributes["size_kb"] = 0.0 # Default if size cannot be determined


                # If all checks passed and content (or error placeholder) is ready
                logger.info(
                    f"[log.included]Included file[/log.included]: "
                    f"[log.path]{relative_file_path_str}[/log.path] "
                    f"(Size: {file_attributes.get('size_kb', 0.0):.1f}KB "
                    f"{', Read error: ' + file_attributes['read_error'] if file_attributes.get('read_error') else ''})"
                )
                stats["included_files_count"] += 1
                yield (relative_file_path, "file", "included", file_attributes)

        logger.debug(
            f"Core _traverse generator finished. Final stats collected by _traverse: {stats}"
        )

    return _traverse(), stats


def prepare_output_list(
    processed_items_generator: Generator[ProcessedItem, None, None],
    sort_options: List[str],
) -> List[Dict[str, Any]]:
    """
    Consumes the generator of processed items, creates a flat list of dictionaries
    suitable for detailed output (like a log or manifest), and sorts this list.
    """
    output_list = []
    for rel_path, item_type, status, payload in processed_items_generator:
        item_dict = {
            "path": rel_path,
            "type": item_type,
            "status": status,
            "size_kb": payload.get("size_kb", 0.0),
            "reason_excluded": payload.get("reason_excluded"),
            # "read_error" could be added if needed for the log, from payload
        }
        output_list.append(item_dict)

    # Sorting logic
    def get_sort_key(item: Dict[str, Any]):
        # Default values for tie-breaking if a primary sort key is not in sort_options
        status_order = 0 if item["status"] == "included" else 1 # included first
        type_order = 0 if item["type"] == "folder" else 1 # folders first
        # Size: primary sort is descending for files, folders effectively 0 or handled by type_order
        # Negative size for descending sort of files. Folders get 0 or a value that groups them as desired.
        size_for_sort = -item["size_kb"] if item["type"] == "file" else 0
        path_for_sort = item["path"]

        key_components = []
        # Build key components based on sort_options, maintaining their order
        for option in sort_options:
            if option == "status":
                key_components.append(status_order)
            elif option == "size":
                key_components.append(size_for_sort)
            elif option == "path": # "path" implies type grouping first, then path
                key_components.append(path_for_sort)

        # Add default tie-breakers for options not explicitly listed in sort_options
        # This ensures stable sorting and covers all fields if not specified.
        # The order of these tie-breakers is fixed: status, type, size, path.
        if "status" not in sort_options:
            key_components.append(status_order)

        # Type order (folder vs file) is implicitly handled by how size_for_sort is defined
        # or can be added explicitly if more complex type sorting is needed beyond size.
        # For now, we'll ensure type (folder/file) is considered before path if path is a sort key.
        # If path is the primary sort, we still want folders grouped before files within the same path segment.
        # A simple way is to always include type_order if path is involved or as a general tie-breaker.
        # Let's refine this: type_order should be a standard tie-breaker.
        if "type" not in sort_options: # Assuming "type" itself is not a direct sort option from CLI
             # This ensures folders come before files if other primary keys are equal.
            key_components.append(type_order)


        if "size" not in sort_options:
            key_components.append(size_for_sort)
        if "path" not in sort_options:
            key_components.append(path_for_sort)

        return tuple(key_components)

    # Special case for size-only sort as per original requirement for specific ordering
    if sort_options == ["size"]:
        # Sort key: (item_type == 'folder', -size_kb if item_type == 'file' else 0, path)
        # This puts folders first (sorted by path), then files by size descending (then path).
        output_list.sort(key=lambda item: (item["type"] == "folder", -item["size_kb"] if item["type"] == "file" else 0, item["path"]), reverse=True)
        # The reverse=True with "type=='folder'" (False for files, True for folders) makes folders (True) come after files (False)
        # To make folders come first, it should be: (item["type"] == "file", ...)
        # Folders first: (item["type"]=="file") -> False for folders, True for files. So folders come first.
        # Then by size descending for files.
        # Then by path ascending.
        output_list.sort(key=lambda item: (
            item["type"] == "file", # Folders (False) before Files (True)
            -item["size_kb"] if item["type"] == "file" else 0, # Files by size desc, folders effectively 0
            item["path"] # Then by path asc
        ))
    else:
        output_list.sort(key=get_sort_key)

    logger.info(f"Core: Prepared and sorted output list with {len(output_list)} items using sort options: {sort_options}")
    return output_list


def build_digest_tree(
    base_dir_path: pathlib.Path,
    processed_items_generator: Generator[ProcessedItem, None, None],
    initial_stats_from_traversal: TraversalStats, # Renamed for clarity
    sort_options: List[str],
) -> Tuple[DigestItemNode, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Builds the hierarchical tree structure for included files,
    prepares a sorted list of all processed items (including excluded ones),
    and compiles final metadata.
    """
    # Consume generator once to get all items. This list will be used multiple times.
    all_processed_items = list(processed_items_generator)

    # Prepare the detailed, sorted list of all items (including excluded)
    # This now uses the `all_processed_items` list instead of consuming the generator directly
    sorted_output_list = prepare_output_list(iter(all_processed_items), sort_options)

    root_node: DigestItemNode = {"relative_path": ".", "type": "folder", "children": []}
    actual_included_files_count = 0
    actual_excluded_items_count = 0
    current_total_content_size_kb = 0.0 # Only for included files with content

    for relative_path, item_type, status, attributes in all_processed_items:
        if status == "excluded":
            actual_excluded_items_count +=1
            continue # Excluded items don't go into the hierarchical tree

        # Only "included" items contribute to the tree and content size
        if item_type == "file" and status == "included":
            actual_included_files_count += 1
            if attributes.get("size_kb") is not None and attributes.get("content") is not None: # Only sum size if content is present
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
                        if child["relative_path"] == str(current_path_so_far)
                        and child["type"] == "folder"
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
            if "content" in attributes : # Content could be None (e.g. if read_error and ignore_errors=True)
                file_node["content"] = attributes["content"]
            if attributes.get("read_error"):
                file_node["read_error"] = attributes["read_error"]

            current_level_children.append(file_node)
        # elif item_type == "folder" and status == "included":
            # Folders are implicitly created if they contain included files.
            # We don't need to explicitly add "included" empty folders to the tree display
            # unless requirements change. The sorted_output_list will show them.
            pass


    def sort_children_recursive(node: DigestItemNode):
        """Sorts children of a node by relative_path for consistent output of the digest tree."""
        if node.get("type") == "folder" and "children" in node:
            # Sort by type (folder then file), then by relative_path
            node["children"].sort(key=lambda x: (x["type"] == "file", x["relative_path"]))
            for child in node["children"]:
                sort_children_recursive(child)

    sort_children_recursive(root_node)

    # Verify counts from all_processed_items against initial_stats for robustness if desired
    # logger.debug(f"Initial stats from traversal: {initial_stats_from_traversal}")
    # logger.debug(f"Recalculated included files: {actual_included_files_count}, Recalculated excluded items: {actual_excluded_items_count}")

    # Prepare final metadata for output formatters
    final_metadata = {
        "base_directory": str(base_dir_path.resolve()),
        "included_files_count": actual_included_files_count, # Derived from iterating all_processed_items
        "excluded_items_count": actual_excluded_items_count, # Derived from iterating all_processed_items
        "total_content_size_kb": round(current_total_content_size_kb, 3),
        "sort_options_used": sort_options, # Add the sort options used
    }
    logger.debug(f"Core: build_digest_tree returning metadata: {final_metadata}")

    return root_node, sorted_output_list, final_metadata
