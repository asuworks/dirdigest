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

## TLDR;

**dirdigest** — CLI tool that recursively scans a directory and outputs a structured digest (Markdown or JSON) of its contents.
Useful for feeding project context to LLMs, documentation, or code reviews. Just run dirdigest in any project folder.
Configurable via .dirdigest YAML file. Copies output path to clipboard by default.
Pattern matching works in 3 moves:

- Scope — pick what's in: `dirdigest -i './src/'`
- Carve — cut what's out: `dirdigest -i './src/' -x '**/tests/'`
- Cherry-pick — add back exceptions: `dirdigest -i './src/' -x '**/tests/' -i '**/test_main.py'`

When patterns conflict, the most specific one wins — a file pattern beats a folder pattern. Preview with --dry-run before committing.


## Table of Contents

- [dirdigest: Directory Digest Generator](#dirdigest-directory-digest-generator)
  - [TLDR;](#tldr)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [For Development (from Source)](#for-development-from-source)
    - [System-Wide Installation (Making `dirdigest` command available globally)](#system-wide-installation-making-dirdigest-command-available-globally)
  - [Quick Start](#quick-start)
  - [Smart Pattern Matching](#smart-pattern-matching)
  - [CLI Usage Guide](#cli-usage-guide)
    - [Synopsis](#synopsis)
    - [Argument](#argument)
    - [Options and Configuration Keys](#options-and-configuration-keys)
  - [Configuration File (`.dirdigest`)](#configuration-file-dirdigest)
    - [Format and Location](#format-and-location)
    - [Example Configuration](#example-configuration)
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

This will process the current directory, apply default ignore patterns, and save a Markdown-formatted digest to a file named `<CURRENT_DIR_NAME>-digest.md` in the current directory. The path to the *directory containing* this output file will be copied to your clipboard by default.

To save the output to a specific file:

```bash
dirdigest my_project_folder -o project_summary.md
```

To get a JSON output:

```bash
dirdigest . -f json -o project_data.json
```

## Smart Pattern Matching

You have 3 moves:

**1. Scope/Include (-i)** — pick what's in
```bash
dirdigest -i './src/'
```

**2. Carve/Exclude (-x)** — cut what's out
```bash
dirdigest -i './src/' -x '**/tests/'
```

**3. Cherry-pick** — add back the exception
```bash
dirdigest -i './src/' -x '**/tests/' -i '**/test_main.py'
```

That's it. When patterns conflict, the one that names the file most directly wins. `**/test_main.py` names the file — beats `tests/` which only names the folder.

To exclude files by type inside a folder, name the files:
```bash
-x 'tests/**/*.py'    # excludes .py files in tests/
-x 'tests/'           # excludes the folder (but file patterns still match inside)
```

**Quick patterns:**
```
**/*.py     all Python files, any depth
*.py        Python files at root only
./src/      root src/ folder (anchored)
src/        any src/ folder (anywhere)
config.py   a specific file
```

**Preview before running:**
```bash
dirdigest --dry-run -i '**/*.py' -x 'tests/'
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

| CLI Option / Argument         | Short | YAML Key (`.dirdigest`) | Description                                                                                                                                                             | Default (CLI)             |
| :---------------------------- | :---- | :---------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------ |
| `DIRECTORY`                   | N/A   | `directory`             | The path to the directory to process. If omitted, defaults to the current working directory (`.`).                                                                      | `.`                       |
| `--output PATH`               | `-o`  | `output`                | Path to the output file. If omitted, defaults to `<TARGET_DIR_NAME>-digest.md` in the target directory. Use `-` for stdout.                                           | `<DIR_NAME>-digest.md`    |
| `--format [json\|markdown]`   | `-f`  | `format`                | Output format for the digest. Choices: `json`, `markdown`.                                                                                                              | `markdown`                |
| `--include PATTERN`           | `-i`  | `include`               | Glob pattern(s) for files/directories to INCLUDE. If specified, only items matching these patterns are processed. Can be used multiple times or comma-separated.      | `None`                    |
| `--exclude PATTERN`           | `-x`  | `exclude`               | Glob pattern(s) for files/directories to EXCLUDE. Takes precedence over include patterns. Can be used multiple times or comma-separated. Default ignores also apply.    | `None`                    |
| `--max-size KB`               | `-s`  | `max_size`              | Maximum size (in KB) for individual files to be included. Larger files are excluded.                                                                                    | `300`                     |
| `--max-depth INT`             | `-d`  | `max_depth`             | Maximum depth of directories to traverse. Depth 0 processes only the starting directory's files. Set to `null` in YAML for unlimited.                               | `None` (unlimited)        |
| `--no-default-ignore`         |       | `no_default_ignore`     | Disable all default ignore patterns (e.g., `.git`, `__pycache__`, `node_modules`, common binary/media files, hidden items like `.*`).                                     | `False`                   |
| `--follow-symlinks`           |       | `follow_symlinks`       | Follow symbolic links to directories and files. By default, symlinks themselves are noted but not traversed/read.                                                       | `False`                   |
| `--ignore-errors`             |       | `ignore_errors`         | Continue processing if an error occurs while reading a file (e.g., permission denied, decoding error). The file's content will be omitted or noted as an error.         | `False`                   |
| `--clipboard / --no-clipboard`| `-c`  | `clipboard`             | Copy the generated digest (if output to stdout using `-o -`) or the output file's directory path (if outputting to a file) to clipboard. WSL paths converted. Use `--no-clipboard` to disable. | `True`                    |
| `--verbose`                   | `-v`  | `verbose`               | Increase verbosity. `-v` for INFO, `-vv` for DEBUG console output. YAML: 0 (WARNING), 1 (INFO), 2 (DEBUG).                                                            | `0` (WARNINGS)            |
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
*   Trailing `/` means folder pattern (e.g., `docs/`), no slash means file pattern (e.g., `*.py`).
*   `./` prefix anchors to the project root; bare patterns use suffix matching at any depth.
*   `*` matches within one directory level, `**` matches across levels, `?` matches one character.
*   Multiple patterns can be supplied by using the option multiple times (e.g., `-i '*.py' -i '*.md'`) or by providing a comma-separated list (e.g., `-x '*.log,tmp/,build/'`).
*   When `-i` and `-x` conflict, the pattern that most directly targets the path wins. See [Smart Pattern Matching](#smart-pattern-matching) for details.
*   Default ignore patterns are applied *in addition* to user-specified excludes unless `--no-default-ignore` is set. These include common VCS directories (`.git/`), build artifacts (`build/`, `dist/`, `__pycache__/`, `node_modules/`), hidden files/directories (`.*`), and common binary/media file extensions.

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
  # output: "my_digest.md" # Optional: specify output file. Defaults to <DIR_NAME>-digest.md if not set. Use "-" for stdout.

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
  clipboard: true           # false to disable copying; if true, copies stdout content or output file's directory path to clipboard
  verbose: 0                # Console verbosity: 0 (Warning), 1 (Info), 2 (Debug)
  quiet: false              # Suppress console output below ERROR, overrides verbose
  # log_file: "dirdigest.log" # Optional: path for detailed file logging (always DEBUG level)

  # Sort the verbose processing log. Keys: 'status', 'size', 'path'
  # sort_output_log_by: ["status", "path"]
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
