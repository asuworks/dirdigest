# dirdigest/dirdigest/core.py
import os
import pathlib
from typing import Any, Dict, Generator, Iterator, List, Tuple

from dirdigest.constants import DEFAULT_IGNORE_PATTERNS
from dirdigest.utils.logger import logger  # Import the configured logger
from dirdigest.utils.patterns import (
    ParsedPattern,
    compute_targeting_distance,
    is_path_hidden,
    matches_path,
    matches_patterns,
    parse_pattern,
)

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


def resolve_pattern_conflicts(
    rel_path: str,
    is_dir: bool,
    include_parsed: list[ParsedPattern],
    exclude_parsed: list[ParsedPattern],
) -> tuple[bool, str]:
    """Determine if a path should be included based on specificity.

    Compares matching include and exclude patterns, resolving conflicts
    by specificity rank (lower = more specific = wins). On tie, exclude wins.

    This function only handles user-specified -i and -x patterns.
    Default ignore patterns are handled separately.
    """
    # Find all matching include patterns with their targeting distance and rank.
    # Resolution uses (distance, rank) tuples — lower distance wins first,
    # then lower rank breaks ties. This ensures that a pattern directly targeting
    # the item (distance 0) beats an ancestor folder pattern (distance N).
    matching_includes: list[tuple[ParsedPattern, int, int]] = []
    for pp in include_parsed:
        if matches_path(pp, rel_path, is_dir=is_dir):
            distance = compute_targeting_distance(pp, rel_path, is_dir)
            matching_includes.append((pp, distance, pp.specificity))

    # Find all matching exclude patterns with their targeting distance and rank
    matching_excludes: list[tuple[ParsedPattern, int, int]] = []
    for pp in exclude_parsed:
        if matches_path(pp, rel_path, is_dir=is_dir):
            distance = compute_targeting_distance(pp, rel_path, is_dir)
            matching_excludes.append((pp, distance, pp.specificity))

    has_includes = len(include_parsed) > 0
    has_matching_includes = len(matching_includes) > 0
    has_matching_excludes = len(matching_excludes) > 0

    # Case 1: Neither match
    if not has_matching_includes and not has_matching_excludes:
        if has_includes:
            if is_dir:
                # Allow directories through for traversal when include patterns
                # could match files or subdirectories deeper in the tree.
                # Without this, os.walk prunes parent dirs and never reaches matches.
                # e.g., -i '**/*.py' needs src/ traversed for src/main.py
                # e.g., -i '**/utils/' needs src/ traversed for src/utils/
                has_file_only_includes = any(not pp.is_folder for pp in include_parsed)
                has_deep_folder_includes = any(
                    pp.is_folder and (not pp.anchored or pp.explicit_recursive) for pp in include_parsed
                )
                if has_file_only_includes or has_deep_folder_includes:
                    return (True, "Directory allowed for traversal")
            return (False, "Does not match any include pattern")
        else:
            return (True, "No patterns specified")

    # Case 2: Only includes match
    if has_matching_includes and not has_matching_excludes:
        best_include = min(matching_includes, key=lambda x: (x[1], x[2]))
        return (True, f"Included by pattern: {best_include[0].raw}")

    # Case 3: Only excludes match
    if not has_matching_includes and has_matching_excludes:
        best_exclude = min(matching_excludes, key=lambda x: (x[1], x[2]))
        return (False, f"Excluded by pattern: {best_exclude[0].raw}")

    # Case 4: Both match -> compare best (distance, rank) tuples
    best_include = min(matching_includes, key=lambda x: (x[1], x[2]))
    best_exclude = min(matching_excludes, key=lambda x: (x[1], x[2]))

    inc_key = (best_include[1], best_include[2])
    exc_key = (best_exclude[1], best_exclude[2])

    if inc_key < exc_key:
        return (True, f"Included by pattern: {best_include[0].raw} (more specific than {best_exclude[0].raw})")
    elif exc_key < inc_key:
        return (False, f"Excluded by pattern: {best_exclude[0].raw} (more specific than {best_include[0].raw})")
    else:
        # Tie -> exclude wins
        return (False, f"Excluded by pattern: {best_exclude[0].raw} (tie with {best_include[0].raw})")


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

    # Parse user patterns ONCE before traversal for specificity resolution
    include_parsed = [parse_pattern(p) for p in include_patterns]
    exclude_parsed = [parse_pattern(p) for p in exclude_patterns]

    logger.debug(f"Core: User include patterns: {len(include_parsed)}, exclude patterns: {len(exclude_parsed)}")
    logger.debug(f"Core: Max size KB: {max_size_kb}, Ignore read errors: {ignore_read_errors}")
    logger.debug(f"Core: Follow symlinks: {follow_symlinks}, No default ignore: {no_default_ignore}")

    # Warn if an include pattern would match something covered by default ignores
    if not no_default_ignore and include_parsed:
        for inc_pp in include_parsed:
            for default_pat in DEFAULT_IGNORE_PATTERNS:
                default_parsed = parse_pattern(default_pat)
                # Simple heuristic: if the include pattern's segments overlap with default ignore
                if inc_pp.raw == default_pat or (
                    inc_pp.is_folder and default_parsed.is_folder and inc_pp.segments == default_parsed.segments
                ):
                    logger.warning(
                        f"Pattern '{inc_pp.raw}' matches a default-ignored path. Use --no-default-ignore to include it."
                    )
                    break

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
                reason_file_excluded = ""
                current_file_size_kb = 0.0

                try:
                    if not follow_symlinks and file_path_obj.is_symlink():
                        current_file_size_kb = 0.0
                    else:
                        current_file_size_kb = round(file_path_obj.stat().st_size / 1024, 3)
                except OSError as e:
                    logger.warning(f"Could not stat file {relative_file_path_str} for size: {e}")

                # Pre-specificity checks: symlinks, hidden files, default ignores
                if not follow_symlinks and file_path_obj.is_symlink():
                    reason_file_excluded = "Is a symlink (symlink following disabled)"
                elif is_path_hidden(relative_file_path) and not no_default_ignore:
                    reason_file_excluded = "Is a hidden file"
                elif not no_default_ignore and matches_patterns(relative_file_path_str, DEFAULT_IGNORE_PATTERNS):
                    reason_file_excluded = "Matches default ignore pattern"

                # If not excluded by pre-checks, use specificity-based resolution
                if not reason_file_excluded:
                    included, conflict_reason = resolve_pattern_conflicts(
                        relative_file_path_str,
                        is_dir=False,
                        include_parsed=include_parsed,
                        exclude_parsed=exclude_parsed,
                    )
                    if not included:
                        reason_file_excluded = conflict_reason

                if reason_file_excluded:
                    stats["excluded_items_count"] += 1
                    log_events.append(
                        {
                            "path": relative_file_path_str,
                            "item_type": "file",
                            "status": "excluded",
                            "size_kb": current_file_size_kb,
                            "reason": reason_file_excluded,
                        }
                    )
                    continue

                file_attributes["size_kb"] = current_file_size_kb
                if current_file_size_kb * 1024 > max_size_bytes:
                    reason_max_size = f"Exceeds max size ({current_file_size_kb:.1f}KB > {max_size_kb}KB)"
                    stats["excluded_items_count"] += 1
                    log_events.append(
                        {
                            "path": relative_file_path_str,
                            "item_type": "file",
                            "status": "excluded",
                            "size_kb": current_file_size_kb,
                            "reason": reason_max_size,
                        }
                    )
                    continue

                try:
                    with open(file_path_obj, "r", encoding="utf-8", errors="strict") as f:
                        file_attributes["content"] = f.read()
                    file_attributes["read_error"] = None
                except (OSError, UnicodeDecodeError) as e:
                    error_reason = f"{type(e).__name__}: {e}"
                    if not ignore_read_errors:
                        stats["excluded_items_count"] += 1
                        log_events.append(
                            {
                                "path": relative_file_path_str,
                                "item_type": "file",
                                "status": "excluded",
                                "size_kb": current_file_size_kb,
                                "reason": error_reason,
                            }
                        )
                        continue
                    file_attributes["content"] = None
                    file_attributes["read_error"] = error_reason

                stats["included_files_count"] += 1
                log_events.append(
                    {
                        "path": relative_file_path_str,
                        "item_type": "file",
                        "status": "included",
                        "size_kb": current_file_size_kb,
                        "reason": None,
                    }
                )
                yield (relative_file_path, "file", file_attributes)

            # --- Now, filter directories for traversal control ---
            dirs_to_remove = []
            for dir_name in dirs_orig:
                dir_path_obj = current_root_path / dir_name
                relative_dir_path = relative_root_path / dir_name
                relative_dir_path_str = str(relative_dir_path)
                reason_dir_excluded = ""
                dir_size_kb = _get_dir_size(dir_path_obj, follow_symlinks)

                # Pre-specificity checks: max-depth, symlinks, hidden, default ignores
                if max_depth is not None and current_depth >= max_depth:
                    reason_dir_excluded = "Exceeds max depth"
                elif not follow_symlinks and dir_path_obj.is_symlink():
                    reason_dir_excluded = "Is a symlink (symlink following disabled)"
                elif is_path_hidden(relative_dir_path) and not no_default_ignore:
                    reason_dir_excluded = "Is a hidden directory"
                elif not no_default_ignore and matches_patterns(relative_dir_path_str, DEFAULT_IGNORE_PATTERNS):
                    reason_dir_excluded = "Matches default ignore pattern"

                # If not excluded by pre-checks, use specificity-based resolution
                # For directories, we track whether to prune from os.walk separately
                # from whether to log as excluded. A dir excluded by -x should still
                # be traversed if a more specific -i pattern could match files inside.
                should_prune = False
                if not reason_dir_excluded:
                    included, conflict_reason = resolve_pattern_conflicts(
                        relative_dir_path_str,
                        is_dir=True,
                        include_parsed=include_parsed,
                        exclude_parsed=exclude_parsed,
                    )
                    if not included:
                        reason_dir_excluded = conflict_reason
                        # With targeting distance, file-level includes at distance 0
                        # always beat folder excludes at distance ≥1 for files inside.
                        # Don't prune if any file include could match inside this dir.
                        should_prune = True
                        for inc_pp in include_parsed:
                            if not inc_pp.is_folder:
                                if inc_pp.anchored and "**" not in inc_pp.segments:
                                    # Anchored file include without **: only relevant
                                    # if its path starts within this directory
                                    inc_prefix = "/".join(inc_pp.segments[:-1]) if len(inc_pp.segments) > 1 else ""
                                    if inc_prefix and not inc_prefix.startswith(relative_dir_path_str):
                                        continue  # Can't match inside this dir
                                # Unanchored, recursive, or prefix-matching file pattern
                                # could match files inside → don't prune
                                should_prune = False
                                break
                            else:
                                # Folder include that could target something inside
                                # the excluded dir (e.g., -x 'tests/' -i 'tests/unit/')
                                if inc_pp.anchored:
                                    inc_path = "/".join(inc_pp.segments)
                                    if inc_path.startswith(relative_dir_path_str + "/"):
                                        should_prune = False
                                        break
                                elif not inc_pp.anchored:
                                    # Unanchored folder could match inside → don't prune
                                    should_prune = False
                                    break
                    else:
                        should_prune = False
                else:
                    # Pre-check exclusions (hidden, default ignore) always prune
                    should_prune = True

                if reason_dir_excluded:
                    stats["excluded_items_count"] += 1
                    log_events.append(
                        {
                            "path": relative_dir_path_str,
                            "item_type": "folder",
                            "status": "excluded",
                            "size_kb": dir_size_kb,
                            "reason": reason_dir_excluded,
                        }
                    )
                    if should_prune:
                        dirs_to_remove.append(dir_name)
                else:
                    # Only log directories that were genuinely matched by an
                    # include pattern. Dirs allowed purely for traversal (so
                    # os.walk can reach deeper matches) are not user-visible results.
                    if not conflict_reason.startswith("Directory allowed"):
                        log_events.append(
                            {
                                "path": relative_dir_path_str,
                                "item_type": "folder",
                                "status": "included",
                                "size_kb": dir_size_kb,
                                "reason": conflict_reason,
                            }
                        )

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
