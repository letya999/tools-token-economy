import glob
import os

from src.core.tools import BaseTool, ToolResult
from src.features.patch import PatchApplier

_BINARY_EXTENSIONS = frozenset({
    '.pyc', '.pyo', '.so', '.dll', '.exe', '.bin',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
    '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz',
    '.whl', '.egg', '.db', '.sqlite', '.lock',
})


class FileReadTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("read", "Reads content of a specific file")
        self.worktree_path = worktree_path

    def execute(self, file_path: str, start_line: int = 1, end_line: int = -1) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")

        try:
            with open(full_path, encoding="utf-8") as f:
                lines = f.readlines()

            start_line = max(start_line, 1)
            if end_line == -1 or end_line > len(lines):
                end_line = len(lines)

            selected_lines = lines[start_line - 1 : end_line]
            output = "".join(selected_lines)
            
            _MAX_CHARS = 20_000
            if len(output) > _MAX_CHARS:
                output = output[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED at {_MAX_CHARS} chars. Use start_line/end_line to read a specific section.]"
            
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error reading file: {e}")

class ReadAllTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("read_all", "Reads all files in the repository (Caution: high tokens!)")
        self.worktree_path = worktree_path

    def execute(self) -> ToolResult:
        output = []
        _MAX_FILES = 30
        _MAX_CHARS = 30_000
        _PER_FILE_CAP = 5_000
        
        files_read = 0
        for root, dirs, files in os.walk(self.worktree_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__', 'node_modules', '.git')]
            for file in files:
                if files_read >= _MAX_FILES:
                    output.append(f"\n[TRUNCATED: read_all limit of {_MAX_FILES} files reached. Use rg/read for remaining files.]")
                    break
                
                _, ext = os.path.splitext(file)
                if ext.lower() in _BINARY_EXTENSIONS:
                    continue
                rel_path = os.path.relpath(os.path.join(root, file), self.worktree_path)
                try:
                    with open(os.path.join(root, file), encoding="utf-8") as f:
                        content = f.read(_PER_FILE_CAP)
                        if len(content) >= _PER_FILE_CAP:
                            content += "\n[TRUNCATED: per-file cap reached]"
                        output.append(f"--- FILE: {rel_path} ---\n{content}")
                        files_read += 1
                except Exception:
                    continue
            else:
                continue
            break
        
        result = "\n\n".join(output)
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: read_all exceeded {_MAX_CHARS} chars]"
        return self.format_result(result)

class FileWriteTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("write", "Writes complete content to a file")
        self.worktree_path = worktree_path

    def execute(self, file_path: str, content: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")

        try:
            # Safety guard: reject writes that would destroy significant existing content.
            if os.path.isfile(full_path):
                with open(full_path, encoding="utf-8") as f:
                    orig_lines = f.readlines()
                new_lines = content.splitlines()
                if len(orig_lines) > 80 and len(new_lines) < 0.7 * len(orig_lines):
                    return self.format_result(
                        f"Error: Write rejected — would delete {len(orig_lines) - len(new_lines)} existing lines "
                        f"({len(new_lines)} new vs {len(orig_lines)} current).\n"
                        f"Options:\n"
                        f"  1. To MODIFY a specific function/block: use `edit` with the exact old text as old_string\n"
                        f"  2. To ADD new code at end of file: use `insert_after` with anchor=last unique line\n"
                        f"  3. To make targeted line changes: use `patch` with a unified diff\n"
                        f"  4. To replace the full file: read ALL sections first (use read with start_line/end_line), "
                        f"then rewrite with complete content ({len(orig_lines)} lines minimum expected)"
                    )

            os.makedirs(os.path.dirname(full_path) if os.path.dirname(full_path) else '.', exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return self.format_result(f"Successfully wrote to {file_path}")
        except Exception as e:
            return self.format_result(f"Error writing file: {e}")

class StrReplaceEditTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__(
            "edit",
            "Replaces an exact string in an existing file. "
            "Use to modify specific sections without touching the rest of the file. "
            "`old_string` must be a unique substring of the current file content. "
            "`new_string` replaces it exactly. Returns error if not found or not unique."
        )
        self.worktree_path = worktree_path

    def execute(self, file_path: str, old_string: str, new_string: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}. Use `write` to create new files.")

        try:
            with open(full_path, encoding="utf-8") as f:
                content = f.read()

            count = content.count(old_string)
            if count == 0:
                # Provide helpful context: show first 200 chars of file
                preview = content[:200].replace('\n', '↵')
                return self.format_result(
                    f"Error: `old_string` not found in {file_path}.\n"
                    f"File preview (first 200 chars): {preview}\n"
                    "Tip: Read the relevant section of the file first to get the exact text."
                )
            if count > 1:
                return self.format_result(
                    f"Error: `old_string` matches {count} locations in {file_path}. "
                    "Make `old_string` more specific by including more surrounding context."
                )

            new_content = content.replace(old_string, new_string, 1)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            lines_changed = abs(new_string.count('\n') - old_string.count('\n'))
            return self.format_result(
                f"Successfully edited {file_path} (+/-{lines_changed} lines net change)."
            )
        except Exception as e:
            return self.format_result(f"Error editing file: {e}")

class GlobTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("glob", "Finds files matching a glob pattern")
        self.worktree_path = worktree_path

    def execute(self, pattern: str) -> ToolResult:
        search_pattern = os.path.join(self.worktree_path, pattern)
        try:
            matches = glob.glob(search_pattern, recursive=True)
            worktree_real = os.path.realpath(self.worktree_path)
            matches = [
                m for m in matches
                if os.path.realpath(m).startswith(worktree_real + os.sep) or os.path.realpath(m) == worktree_real
            ]
            rel_matches = [os.path.relpath(m, self.worktree_path) for m in matches]
            output = "\n".join(rel_matches)
            if not output:
                output = "No matches found."
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error globbing: {e}")

class PatchApplierTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("patch", "Applies a git-style patch/diff")
        self.worktree_path = worktree_path
        self.applier = PatchApplier()

    def execute(self, patch: str) -> ToolResult:
        success, error_detail = self.applier.apply(self.worktree_path, patch)
        if success:
            return self.format_result("Patch applied successfully.")
        else:
            return self.format_result(f"Error: Failed to apply patch.\n{error_detail}")

class InsertAfterLineTool(BaseTool):
    """SWE-agent style insert: inserts new_code AFTER the specified line number.
    Read the file first to see line numbers, then insert after the correct line.
    """
    def __init__(self, worktree_path: str):
        super().__init__(
            "insert",
            "Inserts new_code after the given line_number in file_path. "
            "ALWAYS read the file first to see line numbers. "
            "Use to add new functions/tests after a specific line. "
            "Example: to add after the last line of a function at line 45, use line_number=45."
        )
        self.worktree_path = worktree_path

    def execute(self, file_path: str, line_number: int, new_code: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            n = len(lines)
            if line_number < 0 or line_number > n:
                return self.format_result(
                    f"Error: line_number {line_number} out of range (file has {n} lines). "
                    f"Read the file first to find the correct line number."
                )

            # Ensure new_code ends with newline
            if new_code and not new_code.endswith("\n"):
                new_code = new_code + "\n"
            # Insert a blank separator line before new code if last line isn't blank
            separator = "" if (not lines or lines[line_number - 1].strip() == "") else "\n"
            insertion = separator + new_code
            new_lines = lines[:line_number] + [insertion] + lines[line_number:]

            with open(full_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return self.format_result(
                f"Inserted {len(new_code.splitlines())} lines after line {line_number} in {file_path}."
            )
        except Exception as e:
            return self.format_result(f"Error inserting into file: {e}")


class AppendToFileTool(BaseTool):
    """Appends new_code to the very end of a file — no line number or anchor needed."""
    def __init__(self, worktree_path: str):
        super().__init__(
            "append",
            "Appends new_code to the end of file_path. "
            "Use to add new functions, tests, or blocks at the bottom of an existing file "
            "without touching anything else. No anchor or line number required."
        )
        self.worktree_path = worktree_path

    def execute(self, file_path: str, new_code: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                existing = f.read()

            # Ensure a blank line separator before new code
            separator = "\n" if existing and not existing.endswith("\n\n") else ""
            if existing and not existing.endswith("\n"):
                separator = "\n" + separator

            with open(full_path, "a", encoding="utf-8") as f:
                f.write(separator + new_code)
                if not new_code.endswith("\n"):
                    f.write("\n")

            return self.format_result(
                f"Appended {len(new_code.splitlines())} lines to end of {file_path}."
            )
        except Exception as e:
            return self.format_result(f"Error appending to file: {e}")


class InsertAfterTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__(
            "insert_after",
            "Inserts content after a specific line in an existing file. "
            "anchor_pattern is a unique substring of the line after which to insert. "
            "WARNING: anchoring to a function def line inserts INSIDE the function body. "
            "Prefer `insert` (with line_number) or `append` (for end of file) instead."
        )
        self.worktree_path = worktree_path

    def execute(self, file_path: str, anchor_pattern: str, content: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")
        
        with open(full_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Find anchor line (last occurrence if multiple)
        anchor_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if anchor_pattern in lines[i]:
                anchor_idx = i
                break
        
        if anchor_idx is None:
            # Fall back to append if anchor not found
            with open(full_path, "a", encoding="utf-8") as f:
                f.write("\n" + content + "\n")
            return self.format_result(f"Anchor '{anchor_pattern}' not found — content appended to end of {file_path}")
        
        # Insert after anchor
        insertion = "\n" + content + "\n"
        new_lines = lines[:anchor_idx + 1] + [insertion] + lines[anchor_idx + 1:]
        with open(full_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return self.format_result(f"Content inserted after line {anchor_idx + 1} in {file_path}")
