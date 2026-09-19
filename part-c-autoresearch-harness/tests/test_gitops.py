"""Git behaviour, because "revert" has to mean revert.

Two modes matter here: a task living inside somebody else's repository (which
must stay untouched) and a task that is meant to branch inside it.
"""

import pytest

from arh.engine import Harness, HarnessError
from arh.gitops import Git
from conftest import git, set_value, write_task


@pytest.fixture
def parent_repo(tmp_path):
    """A repository with one commit and a task directory inside it."""
    repo = tmp_path / "project"
    (repo / "tasks").mkdir(parents=True)
    (repo / "README.md").write_text("someone else's repository\n")
    write_task(repo / "tasks" / "toy")
    git(repo, "init", "--quiet", "-b", "main")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "initial")
    return repo


def test_isolated_mode_never_touches_the_enclosing_repo(parent_repo):
    task = parent_repo / "tasks" / "toy"
    before_head = git(parent_repo, "rev-parse", "HEAD").strip()

    harness = Harness.init(task, tag="test")  # isolated is the default
    harness.baseline()
    set_value(task, "4.0")
    assert harness.run("towards the target")["status"] == "keep"

    assert git(parent_repo, "rev-parse", "HEAD").strip() == before_head
    assert git(parent_repo, "branch", "--list").strip() == "* main"
    assert "autoresearch" not in git(parent_repo, "branch", "--all")
    assert (task / ".arh" / "git").is_dir(), "the history lives in the task's private repo"


def test_repo_mode_branches_inside_the_enclosing_repo(parent_repo):
    task = parent_repo / "tasks" / "toy"
    harness = Harness.init(task, tag="test", git_mode="repo")
    harness.baseline()
    assert git(parent_repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "autoresearch/test"

    set_value(task, "4.0")
    verdict = harness.run("towards the target")
    assert verdict["status"] == "keep"
    files = git(parent_repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert files == ["tasks/toy/train.py"], "a keep commits the editable file and nothing else"
    assert "someone else's repository" in (parent_repo / "README.md").read_text()


def test_repo_mode_refuses_a_dirty_task_directory(parent_repo):
    task = parent_repo / "tasks" / "toy"
    set_value(task, "7.0")
    with pytest.raises(HarnessError, match="commit or stash"):
        Harness.init(task, tag="test", git_mode="repo")


def test_repo_mode_reverts_only_the_task(parent_repo):
    task = parent_repo / "tasks" / "toy"
    harness = Harness.init(task, tag="test", git_mode="repo")
    harness.baseline()
    (parent_repo / "README.md").write_text("an unrelated edit by the human\n")
    set_value(task, "9.0")

    assert harness.run("a worse value")["status"] == "discard"
    assert "VALUE = 5.0" in (task / "train.py").read_text()
    assert "an unrelated edit" in (parent_repo / "README.md").read_text(), "work outside the task is not ours to revert"


def test_restore_brings_back_a_deleted_editable_file(harness):
    (harness.root / "train.py").unlink()
    verdict = harness.run("delete the trainer entirely")
    assert verdict["status"] == "crash"
    assert (harness.root / "train.py").is_file()


def test_changed_files_are_relative_to_the_task(parent_repo):
    task = parent_repo / "tasks" / "toy"
    Harness.init(task, tag="test", git_mode="repo")
    set_value(task, "4.0")
    tracked, untracked = Git(task, "repo").changed_files()
    assert tracked == ["train.py"] and untracked == []
