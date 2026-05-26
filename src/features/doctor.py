"""
Doctor: diagnostic and self-repair tool for the benchmark infrastructure.
"""
import logging
import os
import sys
import tempfile
import shutil
from src.features.tool_registry.registry import ToolRegistry
from src.features.tool_registry.base import ValidationResult

_log = logging.getLogger(__name__)


class Doctor:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.registry = ToolRegistry(repo_path)
        self.platform = self._get_normalized_platform()

    def _is_wsl(self) -> bool:
        if sys.platform != "linux": return False
        try:
            with open("/proc/version") as f:
                return "microsoft" in f.read().lower()
        except Exception:
            return False

    def _get_normalized_platform(self) -> str:
        if self._is_wsl():
            return "wsl"
        p = sys.platform
        if p == "win32": return "windows"
        if p == "darwin": return "mac"
        return p

    def check_all(self, auto_fix: bool = False):
        """Run all diagnostic checks."""
        print(f"\n--- Benchmark Doctor ({self.platform}) ---")
        tools = self.registry.list_tools() + ["serena", "semble"]
        
        all_passed = True
        
        # Create a real temporary directory for smoke tests to avoid mutating the target repo.
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Seed the tmp_dir with a dummy file for tools to find
            with open(os.path.join(tmp_dir, "smoke_test_file.txt"), "w") as f:
                f.write("hello_world\nbenchmark_test\n")
            
            for name in tools:
                print(f"\n[{name}]")
                validator = self.registry.get_validator(name)
                
                # 1. Installation check
                res = validator.check_installed()
                self._print_res("Installation", res)
                
                if not res.passed and auto_fix:
                    print(f"  Attempting auto-fix for {name}...")
                    fix_res = validator.install(self.platform)
                    self._print_res("Auto-fix", fix_res)
                    if fix_res.passed:
                        res = validator.check_installed() # Re-check
                
                if not res.passed:
                    all_passed = False
                    continue

                # 2. Smoke test (using isolated tmp_dir)
                smoke_res = validator.smoke_test(tmp_dir)
                self._print_res("Smoke Test", smoke_res)
                if not smoke_res.passed: all_passed = False

                # 3. Agno registration
                reg_res = validator.validate_agno_registration(tmp_dir)
                self._print_res("Agno Integration", reg_res)
                if not reg_res.passed: all_passed = False

        print("\n" + "="*40)
        if all_passed:
            print("RESULT: Infrastructure is HEALTHY.")
        else:
            print("RESULT: Infrastructure has ISSUES. See details above.")
        print("="*40 + "\n")
        return all_passed

        print("\n" + "="*40)
        if all_passed:
            print("RESULT: Infrastructure is HEALTHY.")
        else:
            print("RESULT: Infrastructure has ISSUES. See details above.")
        print("="*40 + "\n")
        return all_passed

    def _print_res(self, label: str, res: ValidationResult):
        status = "PASSED" if res.passed else "FAILED"
        if res.skipped: status = "SKIPPED"
        print(f"  {label:<18}: {status} ({res.detail})")
