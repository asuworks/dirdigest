# dirdigest: Directory Digest Generator
`dirdigest` is a command-line tool that recursively processes directories and files to create a structured, human-readable digest. This digest can be used for various purposes, such as:

*   Providing context to Large Language Models (LLMs).
*   Generating project overviews for documentation.
*   Creating summaries for code reviews.
*   Archiving snapshots of directory structures and file contents.

**Key Features:**

*   **Customizable Traversal:** Filter by glob patterns (include/exclude), maximum file size, and maximum directory depth.
*   **Smart Filtering:** Comes with a comprehensive set of default ignore patterns for common nuisance files and directories (e.g., `.git`, `__pycache__`, `node_modules`, binary files), which can be disabled.
*   **Multiple Output Formats:** Generate digests in Markdown (default) or JSON.
*   **Clipboard Integration:** Automatically copy the generated digest to the system clipboard (can be disabled).
*   **Configuration File:** Define default settings and profiles in a `.dirdigest` YAML file for consistent behavior across projects.
*   **Error Handling:** Option to ignore file read errors and continue processing.
*   **Symlink Support:** Choose whether to follow symbolic links.
*   **Logging:** Controllable verbosity for console output, option to log detailed information to a file, and sortable processing logs.

## Table of Contents

- [Installation](#installation)
  - [For Development (from Source)](#for-development-from-source)
  - [System-Wide Installation (Making `dirdigest` command available globally)](#system-wide-installation-making-dirdigest-command-available-globally)
- [Quick Start](#quick-start)
- [CLI Usage Guide](#cli-usage-guide)
  - [Synopsis](#synopsis)
  - [Argument](#argument)
  - [Options and Configuration Keys](#options-and-configuration-keys)
- [Configuration File (`.dirdigest`)](#configuration-file-dirdigest)
  - [Format and Location](#format-and-location)
  - [Example Configuration](#example-configuration)
- [Use Case Examples](#use-case-examples)
- [Understanding the Verbose Output Log](#understanding-the-verbose-output-log)
- [Development Setup](#development-setup)
- [Contributing](#contributing)
- [License](#license)

## Installation

`dirdigest` requires Python 3.10 or higher and `uv`. Ensure `uv` is installed (e.g., `pip install uv` or see [uv installation guide](https://github.com/astral-sh/uv#installation)).

### For Development (from Source)

This method sets up a complete development environment for working on `dirdigest` itself.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/asuworks/dirdigest.git
    cd dirdigest
    ```
2.  **Set up the environment using Make:**
    ```bash
    make setup
    ```
    This will create a virtual environment, install all dependencies (main and development), and set up pre-commit hooks using `uv`.
3.  **Activate the virtual environment:**
    ```bash
    source .venv/bin/activate
    ```
    (On Windows, the activation script might be `.venv\Scripts\activate`)

    After this, `dirdigest` will be runnable from within the activated virtual environment. For more details on development workflows, see the [Development Setup](#development-setup) section.

### System-Wide Installation (Making `dirdigest` command available globally)

This method installs `dirdigest` directly into your system's Python environment, making the `dirdigest` command accessible from any terminal.

**Caution:** Installing packages directly into the system Python can lead to conflicts and is generally not recommended for all users. Prefer isolated environments (like those managed by `pipx` or project-specific virtual environments) for most use cases. This method is provided for users who specifically require a system-wide installation and understand the implications.

*   **From PyPI (once published):**
    To install the latest published version system-wide using `uv` (requires `sudo` or administrator privileges):
    ```bash
    sudo uv pip install --system dirdigest
    ```

*   **From local source (e.g., a cloned repository):**
    If you have cloned the repository and want to install that version system-wide (requires `sudo` or administrator privileges):
    ```bash
    cd path/to/dirdigest  # Navigate to the directory containing pyproject.toml
    sudo uv pip install --system .
    ```

    *(Note: The `--system` flag tells `uv` to install into the system's Python environment. Alternatively, setting the `UV_SYSTEM_PYTHON=1` environment variable achieves the same. Without this, `uv` typically prefers to manage its own isolated environments when outside an active virtual environment.)*

## Quick Start

Navigate to the directory you want to analyze and run:

```bash
dirdigest
```

This will process the current directory, apply default ignore patterns, and print a Markdown-formatted digest to your console. The digest will also be copied to your clipboard by default.

To save the output to a file:

```bash
dirdigest my_project_folder -o project_summary.md
```

To get a JSON output:

```bash
dirdigest . -f json -o project_data.json
```

## CLI Usage Guide

### Synopsis

```
dirdigest [OPTIONS] [DIRECTORY]
```

### Argument

*   `DIRECTORY`
    *   The path to the directory to process.
    *   If omitted, it defaults to the current working directory (`.`).
    *   Type: `Path (must be an existing, readable directory)`

### Options and Configuration Keys

The following table lists the command-line options and their corresponding keys for use in the `.dirdigest` configuration file.

| CLI Option / Argument         | Short | YAML Key (`.dirdigest`) | Description                                                                                                                                                             | Default (CLI)      |
| :---------------------------- | :---- | :---------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------- |
| `DIRECTORY`                   | N/A   | `directory`             | The path to the directory to process. If omitted, defaults to the current working directory (`.`).                                                                      | `.`                |
| `--output PATH`               | `-o`  | `output`                | Path to the output file. If omitted, the digest is written to standard output (stdout).                                                                                 | `None` (stdout)    |
| `--format [json\|markdown]`   | `-f`  | `format`                | Output format for the digest. Choices: `json`, `markdown`.                                                                                                              | `markdown`         |
| `--include PATTERN`           | `-i`  | `include`               | Glob pattern(s) for files/directories to INCLUDE. Behavior depends on the operational mode (see "Advanced Filtering"). Can be used multiple times or comma-separated.      | `None`             |
| `--exclude PATTERN`           | `-x`  | `exclude`               | Glob pattern(s) for files/directories to EXCLUDE. Behavior depends on the operational mode (see "Advanced Filtering"). Can be used multiple times or comma-separated.    | `None`             |
| `--max-size KB`               | `-s`  | `max_size`              | Maximum size (in KB) for individual files to be included. Larger files are excluded. This check is applied after pattern-based filtering.                               | `300`              |
| `--max-depth INT`             | `-d`  | `max_depth`             | Maximum depth of directories to traverse. Depth 0 processes only the starting directory's files. Set to `null` in YAML for unlimited.                               | `None` (unlimited) |
| `--no-default-ignore`         |       | `no_default_ignore`     | Disable all default ignore patterns (e.g., `.git`, `__pycache__`, `node_modules`, common binary/media files, hidden items like `.*`).                                     | `False`            |
| `--follow-symlinks`           |       | `follow_symlinks`       | Follow symbolic links to directories and files. By default, symlinks themselves are noted but not traversed/read.                                                       | `False`            |
| `--ignore-errors`             |       | `ignore_errors`         | Continue processing if an error occurs while reading a file (e.g., permission denied, decoding error). The file's content will be omitted or noted as an error.         | `False`            |
| `--clipboard / --no-clipboard`| `-c`  | `clipboard`             | Copy the generated digest (stdout) or output file's directory path (-o) to clipboard. WSL paths converted. Use `--no-clipboard` to disable.                             | `True`             |
| `--verbose`                   | `-v`  | `verbose`               | Increase verbosity. `-v` for INFO, `-vv` for DEBUG console output. YAML: 0 (WARNING), 1 (INFO), 2 (DEBUG).                                                            | `0` (WARNINGS)     |
| `--quiet`                     | `-q`  | `quiet`                 | Suppress all console output below ERROR level. Overrides `-v`.                                                                                                          | `False`            |
| `--log-file PATH`             |       | `log_file`              | Path to a file for detailed logging. All logs (including DEBUG level) will be written here, regardless of console verbosity.                                           | `None`             |
| `--config PATH`               |       | N/A                     | Specify configuration file path. If omitted, tries to load `./.dirdigest`. Not set within the config file itself.                                                        | `None`             |
| `--sort-output-log-by KEY`    |       | `sort_output_log_by`    | Sort the detailed item-by-item log output (shown with `-v` or `-vv`). Valid keys: `status`, `size`, `path`. Can be used multiple times for sub-sorting.                 | `status, size`     |
| `--version`                   |       | N/A                     | Show the version of `dirdigest` and exit.                                                                                                                               | N/A                |
| `--help`                      | `-h`  | N/A                     | Show this help message and exit.                                                                                                                                        | N/A                |

**Notes on Configuration File Keys:**
*   **YAML Key Naming:** In the `.dirdigest` YAML file, keys should generally match the Python attribute names used internally (e.g., `max_size` for `--max-size`, `no_default_ignore` for `--no-default-ignore`).
*   **List Values:** For options like `include`, `exclude`, and `sort_output_log_by`, the corresponding YAML key can take a list of strings. `include` and `exclude` also accept a single comma-separated string (e.g., `exclude: ["*.log", "tmp/"]` or `exclude: "*.log,tmp/"`).

**Glob Pattern Details (`--include`, `--exclude`):**

*   Patterns are applied to relative paths from the base directory.
*   Use standard glob syntax (e.g., `*.py`, `src/**/`, `data/*.csv`).
*   To match a directory specifically, ensure the pattern ends with a `/` (e.g., `docs/`).
*   Multiple patterns can be supplied by using the option multiple times (e.g., `-i '*.py' -i '*.md'`) or by providing a comma-separated list (e.g., `-x '*.log,tmp/,build/'`).
*   The interaction between include, exclude, and default ignore patterns is determined by the **Operational Mode** and **Pattern Specificity Rules**. See the "Advanced Filtering: Modes and Specificity" section for details.
*   Default ignore patterns (e.g., `.git/`, `__pycache__/`, `node_modules/`, hidden files/directories `.*`, common binary/media file extensions) are active unless `--no-default-ignore` is set. Their interaction with user-supplied patterns depends on the operational mode.

## Advanced Filtering: Modes and Specificity

`dirdigest` employs a sophisticated filtering system based on operational modes (determined by the presence and order of `-i`/`--include` and `-x`/`--exclude` flags) and pattern specificity.

### Operational Modes

The tool automatically determines one of five operational modes:

1.  **Include All (Default Mode)**: `MODE_INCLUDE_ALL_DEFAULT`
    *   Triggered when no `-i` or `-x` flags are specified by the user (neither on CLI nor in config).
    *   Logic: Includes all files and directories not matching a default ignore rule (unless `--no-default-ignore` is active).
2.  **Only Include Mode**: `MODE_ONLY_INCLUDE`
    *   Triggered when only `-i` flags are present.
    *   Logic:
        1. A path MUST match an include pattern (MSI). If not, it's excluded.
        2. If an MSI matches, the path is then checked against default ignore rules (unless `--no-default-ignore`). The MSI must be at least as specific as (or more specific than) any matching default ignore rule. If a default rule is more specific, the path is excluded.
        3. If all checks pass, the path is included.
3.  **Only Exclude Mode**: `MODE_ONLY_EXCLUDE`
    *   Triggered when only `-x` flags are present.
    *   Logic:
        1. If a path matches a user-defined exclude pattern (MSE), it's excluded. (This mode assumes no user `-i` flags, so no user MSI can rescue it from a user MSE).
        2. If not excluded by a user MSE, the path is checked against default ignore rules (unless `--no_default_ignore`). If a default rule matches, it's excluded.
        3. Otherwise (not excluded by user MSEs or default rules), the path is included.
4.  **Include First Mode**: `MODE_INCLUDE_FIRST`
    *   Triggered when both `-i` and `-x` flags are present, and the first such flag encountered in the command-line arguments is `-i` or `--include`.
    *   Logic (Strict Inclusion):
        1.  A path MUST match an include pattern (MSI). If not, it's excluded.
        2.  If an MSE also matches: The MSI MUST be strictly more specific than the MSE. If MSE is more or equally specific, the path is excluded.
        3.  If the path is still a candidate for inclusion (passed step 1 & 2): It's checked against default ignore rules (unless `--no-default-ignore`). If a default rule matches, the MSI MUST be at least as specific as (or more specific than) the default rule pattern. If the default rule is more specific, the path is excluded.
        4.  If all checks pass, the path is included.
5.  **Exclude First Mode**: `MODE_EXCLUDE_FIRST`
    *   Triggered when both `-i` and `-x` flags are present, and the first such flag encountered is `-x` or `--exclude` OR if both include and exclude patterns are present but their order cannot be determined from CLI flags (e.g., all from config file, in which case it defaults to Exclude First).
    *   Logic (Exclusion Priority, with Include "Rescue"):
        1.  If a path matches an exclude pattern (MSE):
            *   If it also matches an include pattern (MSI), the MSI MUST be strictly more specific than the MSE to "rescue" the path from exclusion. If MSI is not strictly more specific, the path is excluded.
            *   If there's no MSI, the path is excluded by the MSE.
        2.  If the path was not excluded by an MSE (either no MSE matched, or it was rescued by an MSI): It's checked against default ignore rules (unless `--no-default-ignore`).
            *   If a default rule matches:
                *   If an MSI also matches the path, the MSI must be at least as specific as (or more specific than) the default rule to keep the path included. If the default rule is more specific, the path is excluded.
                *   If no MSI matches the path, the default rule excludes it.
        3.  If the path is still a candidate for inclusion:
            *   If any include patterns (`-i`) were provided by the user *at all* (even if they didn't match this specific path initially but an MSE was overridden), the path MUST have ultimately been matched by an MSI to be included. If not, it's implicitly excluded.
            *   If no include patterns (`-i`) were provided by the user at all, the path is included at this point.
        4.  If all checks pass, the path is included.

### Pattern Specificity Rules

When multiple patterns (e.g., an include, an exclude, and a default ignore) match the same path, `dirdigest` determines which pattern takes precedence based on specificity. The general rules are:

1.  **Depth of Matching Pattern Wins**: A pattern that matches more leading components of a path is considered more specific.
    *   Example: For path `docs/api/v1/file.md`, pattern `docs/api/` is more specific than `docs/` or `*.md`.
2.  **Explicit Name Wins Over Glob**: A pattern that explicitly names a file or directory is more specific than a glob pattern, assuming they match at the same depth.
    *   Example: For path `debug.log`, pattern `debug.log` is more specific than `*.log`.
    *   Example: For path `src/config/`, pattern `src/config/` is more specific than `src/*/`.
3.  **Suffix Proximity (Filename Glob Tie-breaker)**: For file globs that are otherwise equal in specificity (e.g., same depth, both are globs), the one matching more parts of the file's suffix is more specific.
    *   Example: For path `archive.tar.gz`, pattern `*.tar.gz` is more specific than `*.gz`.

**Original Index Tie-Breaker**: If all other specificity rules result in a tie between two user-provided patterns of the same type (e.g., two include patterns), the pattern that appeared later in the input list (or later on the command line) is considered more specific. For default ignore patterns, they generally have a lower intrinsic priority than user-specified patterns.

This new filtering system provides fine-grained control over which files and directories are included in the digest. Understanding these rules can help in crafting precise include/exclude patterns.

## Configuration File (`.dirdigest`)

`dirdigest` can be configured using a YAML file, typically named `.dirdigest`, to set default behaviors. The available settings and their corresponding CLI options are detailed in the [Options and Configuration Keys](#options-and-configuration-keys) table above.

### Format and Location

*   **Default Name:** `.dirdigest`
*   **Default Location:** The tool looks for this file in the current working directory from where `dirdigest` is invoked.
*   **Custom Location:** You can specify a different configuration file path using the `--config PATH` CLI option.
*   **Format:** YAML.

The configuration file can be structured in two ways:

1.  **Flat Configuration:** A simple key-value mapping of settings at the root of the YAML file.
    ```yaml
    # .dirdigest (flat example)
    format: json
    max_size: 500 # Corresponds to --max-size
    exclude:
      - "*.log"
      - "temp/"
    ```

2.  **With a `default` Profile:** Settings are placed under a `default:` key. This is the primary way `dirdigest` currently uses profiles. If other top-level keys (potential future profiles) exist, they are ignored unless a `default` profile is explicitly defined.
    ```yaml
    # .dirdigest (with 'default' profile)
    default:
      format: markdown
      max_depth: 3
      no_default_ignore: true
      include: "*.py,*.md" # Can be a comma-separated string
      exclude: # Or a list of strings
        - "**/tests/"

    # other_profile: # Currently ignored by dirdigest
    #   format: json
    ```

**Precedence:** Command-line arguments, if explicitly set by the user, will always override settings from the configuration file. If a CLI option is not used, its default value from the configuration file (if present) will be applied, otherwise the tool's built-in default is used.

### Example Configuration

This example demonstrates various settings available in the `.dirdigest` file. Refer to the [Options and Configuration Keys](#options-and-configuration-keys) table for a full list of YAML keys.

```yaml
# .dirdigest
# This is a sample configuration file for dirdigest.

default:
  # Output settings
  format: "markdown"        # 'json' or 'markdown'
  # output: "my_digest.md" # Optional: specify default output file

  # Traversal and filtering settings
  # directory: "."          # Optional: specify default directory (usually CWD is fine)
  max_size: 250             # Max file size in KB
  max_depth: 5              # Max directory depth to traverse, null for unlimited
  follow_symlinks: false    # Set to true to follow symbolic links
  no_default_ignore: false  # Set to true to disable all default ignore patterns
                            # (e.g., .git, __pycache__, common binary/media files)

  # Include patterns: process only these if specified.
  # Exclusions are applied first.
  include:
    - "*.py"
    - "*.md"
    - "src/"
    # - "docs/**/*.rst" # Example of deeper pattern

  # Exclude patterns: always skip these. Takes precedence over includes.
  # Default ignores also apply unless no_default_ignore is true.
  exclude:
    - "*.log"
    - "tests/"
    - "**/__pycache__/" # More specific than default if needed
    - "node_modules/"
    - ".venv/"
    - "dist/"
    - "build/"

  # Content processing
  ignore_errors: false      # Set to true to include files with read errors (content will be null)

  # UI/UX settings
  clipboard: true           # false to disable copying; if true, copies content (stdout) or file path (-o) to clipboard
  verbose: 0                # Console verbosity: 0 (Warning), 1 (Info), 2 (Debug)
  quiet: false              # Suppress console output below ERROR, overrides verbose
  # log_file: "dirdigest.log" # Optional: path for detailed file logging (always DEBUG level)

  # Sort the verbose processing log. Keys: 'status', 'size', 'path'
  # sort_output_log_by: ["status", "path"]
```

## Use Case Examples

0.  **Generate a digest of the current project, excluding test directories and specific build artifacts, then save it:**
    ```bash
    dirdigest . -o digest.md -x "tests/,*.egg-info/,dist/,build/"
    ```
    *Assuming default mode (or Exclude First if includes were also in a config), this primarily uses excludes.*

1.  **Strictly include only Python files from the `src` directory and Markdown files from `docs`, ignoring everything else:**
    ```bash
    dirdigest . -i "src/**/*.py" -i "docs/**/*.md" -o project_src_docs.md
    ```
    *This will run in `MODE_ONLY_INCLUDE` if no exclude flags are used.*

2.  **Process a project, excluding log files and temporary directories, but ensure all Python files in `app/services` are included even if they were somehow part of a broader exclude or default ignore (e.g., if `app/services` was hidden).**
    Command assuming `-i` comes first to trigger `MODE_INCLUDE_FIRST`:
    ```bash
    dirdigest . -i "app/services/**/*.py" -x "*.log" -x "tmp/" -o app_focus.md
    ```
    If `app/services/` was hidden (e.g. `.app/services/`), you might also need `--no-default-ignore` or ensure `app/services/**/*.py` is specific enough to override the hidden rule.

3.  **Exclude a general pattern like `output/*` but rescue a specific subdirectory `output/critical_reports/` for inclusion.**
    Command assuming `-x` comes first to trigger `MODE_EXCLUDE_FIRST`:
    ```bash
    dirdigest . -x "output/*" -i "output/critical_reports/" -o main_digest.md
    ```
    In this `MODE_EXCLUDE_FIRST` scenario, `output/critical_reports/` will be included because its include pattern is more specific for paths within it than the exclude pattern `output/*`. Other items in `output/` will be excluded.

4.  **Use a project-specific `.dirdigest` file for common settings:**
    Create a `.dirdigest` file in your project root:
    ```yaml
    # my_project/.dirdigest
    default:
      exclude:
        - "dist/"
        - "build/"
        - "node_modules/"
        - ".DS_Store"
        - "*.pyc"
      include:
        - "src/**/*.js"
        - "public/"
      max_size: 500
      format: markdown
    ```
    Then simply run from the project root:
    ```bash
    dirdigest -o web_app_digest.md
    ```
    This will use settings from `.dirdigest` and save to `web_app_digest.md`.

5.  **Include a specific hidden file (e.g., `.envrc`) while keeping most default ignores active (this is tricky):**
    The most straightforward way to include a specific hidden file that would normally be ignored by `.*` or other hidden-file logic is to use `--no-default-ignore` and then explicitly include what you want, and explicitly exclude what you *don't* want from the usual defaults.
    ```bash
    dirdigest . --no-default-ignore \
        --include ".envrc,src/*.py,README.md" \
        --exclude ".git/,__pycache__/,*.log,node_modules/" \
        -o my_app_context.md
    ```
    This gives you fine-grained control when default behaviors for hidden files conflict with your needs.

6.  **Troubleshoot which files are being processed or ignored with verbose logging:**
    ```bash
    dirdigest . -vv --log-file processing_details.log
    ```
    Check `processing_details.log` for detailed DEBUG messages about each file and directory encountered.

7. **Inspect processing order with custom sorting:**
   To understand why certain files are included or excluded, use verbose logging and sort by path for a straightforward alphabetical view.
   ```bash
   dirdigest . -v --sort-output-log-by path
   ```

## Understanding the Verbose Output Log

When you use `-v` (INFO) or `-vv` (DEBUG) flags, `dirdigest` provides a detailed log of each file and folder it processes. This log has been enhanced:

*   **Item Sizes:** Each logged file and folder now displays its size in kilobytes (KB). For folders, this size represents the total sum of all included files within that folder and its subfolders.
    *   Example: `[log.included]Included file[/log.included]: [log.path]src/main.py[/log.path] (Size: 2.52KB)`
    *   Example: `[log.included]Included folder[/log.included]: [log.path]src/[/log.path] (Size: 120.75KB)`
*   **Default Sorting:** By default, this verbose log output is sorted to group excluded items before included items.
    *   Within each status group (excluded/included), folders are listed first (alphabetically), followed by files (sorted by size descending, then path).
*   **Headers:** When sorted by `status` or `size`, headers are printed:
    *   `--- EXCLUDED ITEMS ---` (style: bold yellow)
    *   `--- INCLUDED ITEMS ---` (style: bold green)
*   **Custom Sorting with `--sort-output-log-by`:**
    *   Use this option to change the sort order of the verbose log.
    *   Valid keys:
        *   `status`: Groups by status (excluded items first, then included, then errors).
        *   `size`: Sorts by size in descending order (largest first).
        *   `path`: Sorts alphabetically by relative path.
    *   You can specify multiple keys for hierarchical sorting. For example, `--sort-output-log-by status --sort-output-log-by size` is the default.
    *   If you sort *only* by `path` (e.g., `dirdigest . -v --sort-output-log-by path`), the "EXCLUDED ITEMS" and "INCLUDED ITEMS" headers will not be shown, and all items will be listed in a single block sorted by path.
*   **YAML Configuration for Sorting:** You can set default sort keys in your `.dirdigest` file:
    ```yaml
    # .dirdigest
    default:
      # ... other settings ...
      sort_output_log_by: ["path"] # Example: make path-only sort the default
    ```

**Example Verbose Output (default sort):**
```
$ dirdigest . -v
INFO     : Processing directory: .
INFO     : Output will be written to stdout
INFO     : Format: MARKDOWN
INFO     : Sorting item log by: ['status', 'size']
INFO     : [bold yellow]--- EXCLUDED ITEMS ---[/bold yellow]
INFO     : [log.excluded]Excluded folder[/log.excluded]: [log.path].git[/log.path] ([log.reason]Is a hidden directory[/log.reason]) (Size: 15.30KB)
INFO     : [log.excluded]Excluded file[/log.excluded]: [log.path]app.log[/log.path] ([log.reason]Matches default ignore pattern[/log.reason]) (Size: 12.40KB)
INFO     : [log.excluded]Excluded file[/log.excluded]: [log.path].env[/log.path] ([log.reason]Is a hidden file[/log.reason]) (Size: 0.02KB)
INFO     : [bold green]--- INCLUDED ITEMS ---[/bold green]
INFO     : [log.included]Included folder[/log.included]: [log.path]data[/log.path] (Size: 20.10KB)
INFO     : [log.included]Included folder[/log.included]: [log.path]src[/log.path] (Size: 8.75KB)
INFO     : [log.included]Included file[/log.included]: [log.path]data/big_file.dat[/log.path] (Size: 20.00KB)
INFO     : [log.included]Included file[/log.included]: [log.path]src/main.py[/log.path] (Size: 5.50KB)
INFO     : [log.included]Included file[/log.included]: [log.path]README.md[/log.path] (Size: 2.00KB)
INFO     : [log.included]Included file[/log.included]: [log.path]src/utils.py[/log.path] (Size: 1.25KB)
INFO     : [log.included]Included file[/log.included]: [log.path]data/small_file.txt[/log.path] (Size: 0.10KB)
INFO     : Building digest tree...
# Directory Digest: /path/to/your/project
... (rest of Markdown output) ...
INFO     : ------------------------------ SUMMARY ------------------------------
INFO     : Total files included: 4
INFO     : Total items excluded (files/dirs): 3
INFO     : Total content size: 28.85 KB
INFO     : Approx. Token Count: ...
INFO     : Execution time: ... seconds
INFO     : -------------------------------------------------------------------
```

## Development Setup

To contribute to `dirdigest` or set it up for local development, follow these steps. We use `uv` for dependency management and `make` for common development tasks.

**Prerequisites:**
*   Python 3.10 or higher.
*   [uv](https://github.com/astral-sh/uv) (Python package installer and resolver). You can install it via `pip install uv` or other methods described in its documentation.

**Steps:**

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/asuworks/dirdigest.git # Or your fork
    cd dirdigest
    ```

2.  **Set up the environment and install dependencies:**
    The recommended way is to use the `Makefile`:
    ```bash
    make setup
    ```
    This command will:
    *   Create a virtual environment (usually `.venv/`) using `uv`.
    *   Install all main and development dependencies using `uv sync --all-extras`.
    *   Install and activate pre-commit hooks.

    After running, activate the virtual environment:
    ```bash
    source .venv/bin/activate
    ```
    (On Windows, the activation script might be `.venv\Scripts\activate`)

    Alternatively, if you prefer manual steps (though `make setup` is simpler):
    ```bash
    # 1. Create and activate a virtual environment
    # python -m venv .venv
    # source .venv/bin/activate

    # 2. Install dependencies
    uv sync --all-extras

    # 3. Install and activate pre-commit hooks
    make activate-pre-commit # Uses uv to install pre-commit and then pre-commit install
    ```

**Common Development Tasks (using `Makefile`):**

The `Makefile` provides convenient targets for common development workflows:

*   `make format`: Format code using Ruff.
*   `make lint`: Lint code using Ruff (with auto-fix).
*   `make mypy`: Run type checking with Mypy.
*   `make test`: Run tests using Pytest (this also handles setting up test directory fixtures).
*   `make validate`: Run all checks (format, lint, mypy, test). This is highly recommended before committing or pushing changes.
*   `make install-deps`: Install/sync dependencies (equivalent to `uv sync --all-extras`).
*   `make update-deps`: Update dependencies to their latest compatible versions using `uv sync`.
*   `make clean`: Clean up build artifacts and cache files (e.g., `__pycache__`, `.pytest_cache`, `.uv_cache`).

Run `make help` to see all available commands and their descriptions.

## Contributing

Contributions are welcome! Please open an issue to discuss your ideas or submit a pull request.

**Before submitting a Pull Request:**

1.  **Set up your development environment:** Please follow the instructions in the [Development Setup](#development-setup) section.
2.  **Ensure all checks pass:** Run `make validate` to format, lint, type-check, and test your changes.
    If `make validate` fails, you can run individual checks to pinpoint the issue:
    *   `make format`
    *   `make lint`
    *   `make mypy`
    *   `make test`
3.  **Add tests:** If you're adding a new feature or fixing a bug, please include relevant tests that cover your changes.
4.  **Update documentation:** If your changes affect user-facing behavior, add new options, or modify existing ones, please update this `README.md` or other relevant documentation (like test READMEs or comments in the code if applicable).
5.  **Keep your branch up-to-date:** Rebase your branch on the latest main/master branch before submitting.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
