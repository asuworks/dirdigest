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
                    # INFO log removed
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
                    # INFO log removed
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
                        # INFO log removed
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
                        # INFO log removed
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
                        # INFO log removed
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
                # INFO log removed
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
            "path": str(rel_path), # Convert pathlib.Path object to string for stable sorting
            "type": item_type, # "file" or "folder"
            "status": status,  # "included" or "excluded"
            "size_kb": payload.get("size_kb", 0.0),
            "reason_excluded": payload.get("reason_excluded"),
        }
        output_list.append(item_dict)

    # Define sort value getters
    def status_sort_val(item): return 0 if item['status'] == 'excluded' else 1 # excluded first
    def type_sort_val(item): return 0 if item['type'] == 'folder' else 1     # folder first
    def path_sort_val(item): return item['path']
    def size_sort_val(item): return item['size_kb']

    # Apply sorting based on sort_options
    if sort_options == ['status'] or sort_options == ['status', 'path']:
        # Sort by: (status_sort_val, type_sort_val, path_sort_val)
        # Excluded items first, then Included. Within each, Folders first, then Files. Then by Path.
        output_list.sort(key=lambda item: (
            status_sort_val(item),
            type_sort_val(item),
            path_sort_val(item)
        ))
    elif sort_options == ['size']:
        # Sort key for an item:
        # If type is folder (0): (status, type, path, 0) (path for folders, 0 for size part)
        # If type is file (1): (status, type, -size, path) (-size for descending, path for tie-breaking)
        # This means: Excluded Folders by Path, Excluded Files by Size DESC,
        #             Included Folders by Path, Included Files by Size DESC
        output_list.sort(key=lambda item: (
            status_sort_val(item),
            type_sort_val(item),
            path_sort_val(item) if item['type'] == 'folder' else -size_sort_val(item), # Path for folders, -Size for files
            path_sort_val(item) if item['type'] == 'file' else 0 # Path for files (tie-breaker), 0 for folders
        ))
    elif sort_options == ['path']:
        # Sort by: (path_sort_val)
        # Primary sort by path. Type can be secondary if items can have same path (e.g. dir and file named 'foo')
        # but with full relative paths, this is unlikely. Using type as secondary for stability.
        output_list.sort(key=lambda item: (
            path_sort_val(item),
            type_sort_val(item) # Ensure folders list before files if paths are somehow identical/related
        ))
    elif sort_options == ['status', 'size']: # Default
        # Sort key for an item (same as ['size'] logic, as status is the primary sort component)
        # Excluded items first, then Included.
        # Within status: Folders first (by path), then Files (by size desc, then path).
        output_list.sort(key=lambda item: (
            status_sort_val(item), # status is primary
            type_sort_val(item),   # then type
            # For folders, sort by path. For files, sort by -size.
            path_sort_val(item) if item['type'] == 'folder' else -size_sort_val(item),
            # Tie-breaker for files is path. For folders, this component is not really used as path is primary for them here.
            path_sort_val(item) if item['type'] == 'file' else 0
        ))
    elif sort_options == ['size', 'path']:
        # Sort key for an item:
        # If type is folder (0): (type, path, 0) (No status grouping)
        # If type is file (1): (type, -size, path) (No status grouping)
        # This means: All Folders by Path, then All Files by Size DESC then Path.
        output_list.sort(key=lambda item: (
            type_sort_val(item), # type is primary
            path_sort_val(item) if item['type'] == 'folder' else -size_sort_val(item),
            path_sort_val(item) if item['type'] == 'file' else 0
        ))
    else:
        # Fallback to a default sort if an unexpected combination is passed, though CLI restricts choices.
        # This is the original general sort key builder.
        # status_order = 0 if item["status"] == "included" else 1 # included first
        # type_order = 0 if item["type"] == "folder" else 1 # folders first
        # size_for_sort = -item["size_kb"] if item["type"] == "file" else 0
        # path_for_sort = item["path"]
        # key_components = []
        # for option in sort_options: # Build key from options in order
        #     if option == "status": key_components.append(status_order)
        #     elif option == "size": key_components.append(size_for_sort)
        #     elif option == "path": key_components.append(path_for_sort)
        # # Default tie-breakers
        # if "status" not in sort_options: key_components.append(status_order)
        # if "type" not in sort_options: key_components.append(type_order) # Implicitly handled by size_for_sort usually
        # if "size" not in sort_options: key_components.append(size_for_sort)
        # if "path" not in sort_options: key_components.append(path_for_sort)
        # output_list.sort(key=lambda item_lambda: tuple(k(item_lambda) if callable(k) else k for k in key_components_template))
        # For safety, let's just use the default sort ['status', 'size'] if unhandled combo
        logger.warning(f"Core: Unhandled sort_options combination: {sort_options}. Falling back to default sort.")
        output_list.sort(key=lambda item: (
            status_sort_val(item),
            type_sort_val(item),
            path_sort_val(item) if item['type'] == 'folder' else -size_sort_val(item),
            path_sort_val(item) if item['type'] == 'file' else 0
        ))

    logger.info(f"Core: Prepared and sorted output list with {len(output_list)} items using sort options: {sort_options}")
    return output_list


def build_digest_tree(
    base_dir_path: pathlib.Path,
    # The generator is converted to a list in cli.py and then passed.
    all_processed_items: List[ProcessedItemPayload], # Changed type to List[ProcessedItemPayload] as per previous definition, but should be List[ProcessedItem]
                                                     # Correcting to List[ProcessedItem] which is Tuple[pathlib.Path, str, str, ProcessedItemPayload]
    initial_stats_from_traversal: TraversalStats,
) -> Tuple[DigestItemNode, Dict[str, Any]]: # No longer returns sorted_output_list
    """
    Builds the hierarchical tree structure for included files and compiles final metadata.
    The `all_processed_items` list is expected to be pre-populated (e.g., from `process_directory_recursive`).
    Sorting for the "Processing Log" is now handled by `prepare_output_list` called directly from `cli.py`.
    """
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
    # logger.debug(f"Initial stats from traversal: {initial_stats_from_traversal}") # initial_stats can be used or overridden
    # logger.debug(f"Recalculated included files from all_processed_items: {actual_included_files_count}")
    # logger.debug(f"Recalculated excluded items from all_processed_items: {actual_excluded_items_count}")

    # Prepare final metadata for output formatters
    # Counts are now based on iterating `all_processed_items`.
    final_metadata = {
        "base_directory": str(base_dir_path.resolve()),
        "included_files_count": actual_included_files_count,
        "excluded_items_count": actual_excluded_items_count, # This count is from iterating all_processed_items
        "total_content_size_kb": round(current_total_content_size_kb, 3),
        # "sort_options_used" is removed from here, will be added by cli.py to the metadata given to formatter
    }
    logger.debug(f"Core: build_digest_tree returning metadata: {final_metadata}")

    return root_node, final_metadata
