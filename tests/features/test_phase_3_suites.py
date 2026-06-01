import pytest
import os
import yaml
from src.core.config_loader import load_task_suite
from src.core.models import TaskConfig

def test_load_task_suite(tmp_path):
    # Create a dummy task file
    task_file = tmp_path / "test_task.yaml"
    task_content = {
        "name": "test_task",
        "description": "desc",
        "test_cmd": "pytest"
    }
    with open(task_file, "w") as f:
        yaml.dump(task_content, f)
        
    # Create a suite manifest
    suite_file = tmp_path / "suite.yaml"
    suite_content = {
        "name": "test_suite",
        "tasks": [
            {"file": str(task_file), "category": "test_cat"}
        ]
    }
    with open(suite_file, "w") as f:
        yaml.dump(suite_content, f)
        
    tasks = load_task_suite(str(suite_file))
    
    assert len(tasks) == 1
    assert tasks[0].name == "test_task"
    assert tasks[0].category == "test_cat"

def test_load_task_suite_missing_file(tmp_path):
    suite_file = tmp_path / "suite_missing.yaml"
    suite_content = {
        "name": "test_suite",
        "tasks": [
            {"file": "non_existent.yaml", "category": "none"}
        ]
    }
    with open(suite_file, "w") as f:
        yaml.dump(suite_content, f)
        
    with pytest.raises(FileNotFoundError):
        load_task_suite(str(suite_file))
