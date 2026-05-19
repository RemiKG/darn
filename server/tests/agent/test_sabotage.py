"""GitHubSabotage: patch.json loading, robust repo-root resolution, pre-sabotage
originals captured from GitHub, ONE real commit, clean revert."""

from __future__ import annotations

import json

import pytest

from app.agent.sabotage import GitHubSabotage, SabotageError, find_repo_root, load_patch
from app.models import Incident

PATCH = {
    "files": [
        {"path": "shop/app/checkout.py", "sabotaged_content": "def total(c):\n    return c.items\n"}
    ],
    "commit_message": "chore: simplify checkout maths",
    "davis_expectation": "error-rate spike on POST /api/checkout",
}


class FakeGitHub:
    repo = "remikg/loose-threads"

    def __init__(self):
        self.files = {"shop/app/checkout.py": "def total(c):\n    if c is None:\n        return 0\n"}
        self.commits: list[tuple[dict, str, str]] = []
        self.merged: list[int] = []
        self.closed: list[int] = []

    async def get_repo_default_branch(self):
        return "main"

    async def get_file(self, path, ref=None):
        return {"content": self.files[path], "sha": "blob"}

    async def commit_files(self, files, message, branch):
        self.commits.append((dict(files), message, branch))
        return f"sha-{len(self.commits)}"

    async def revert_via_restore(self, originals, message, branch):
        return await self.commit_files(originals, message, branch)

    async def get_commit(self, sha):
        return {"sha": sha, "parents": ["parent-sha"], "message": "m", "date": "", "files": []}

    async def merge_pr(self, number, method="squash"):
        self.merged.append(number)
        return {"merged": True, "sha": "merge-sha"}

    async def close_pr(self, number):
        self.closed.append(number)


@pytest.fixture
def repo_root(tmp_path):
    defect_dir = tmp_path / "shop" / "defects" / "checkout-null"
    defect_dir.mkdir(parents=True)
    (defect_dir / "patch.json").write_text(json.dumps(PATCH), encoding="utf-8")
    return tmp_path


def test_find_repo_root_walks_up(repo_root):
    deep = repo_root / "server" / "app" / "agent"
    deep.mkdir(parents=True)
    assert find_repo_root(deep / "sabotage.py") == repo_root


def test_load_patch_unknown_defect_raises(repo_root):
    with pytest.raises(SabotageError) as exc:
        load_patch("not-a-defect", repo_root)
    assert "not-a-defect" in str(exc.value)


@pytest.mark.asyncio
async def test_commit_defect_one_commit_with_innocent_message(repo_root):
    github = FakeGitHub()
    backend = GitHubSabotage(github, repo_root=repo_root)
    out = await backend.commit_defect("checkout-null")
    assert out["sha"] == "sha-1"
    assert out["message"] == "chore: simplify checkout maths"  # innocent, from patch.json
    assert out["files"] == ["shop/app/checkout.py"]
    assert len(github.commits) == 1  # ONE real commit
    files, message, branch = github.commits[0]
    assert branch == "main"
    assert files["shop/app/checkout.py"] == PATCH["files"][0]["sabotaged_content"]


@pytest.mark.asyncio
async def test_revert_restores_pre_sabotage_originals(repo_root):
    github = FakeGitHub()
    backend = GitHubSabotage(github, repo_root=repo_root)
    original = github.files["shop/app/checkout.py"]
    await backend.commit_defect("checkout-null")
    incident = Incident(defect_key="checkout-null", sabotage_sha="sha-1")
    sha = await backend.revert(incident)
    assert sha == "sha-2"
    files, message, _ = github.commits[1]
    assert files["shop/app/checkout.py"] == original  # exactly what production had
    assert message == 'Revert "chore: simplify checkout maths"'


@pytest.mark.asyncio
async def test_revert_after_restart_recovers_originals_from_parent(repo_root):
    github = FakeGitHub()
    backend = GitHubSabotage(github, repo_root=repo_root)  # fresh: no stored originals
    incident = Incident(defect_key="checkout-null", sabotage_sha="sab-sha")
    sha = await backend.revert(incident)
    assert sha == "sha-1"
    files, _, _ = github.commits[0]
    # originals were re-read from the sabotage commit's parent
    assert files["shop/app/checkout.py"] == github.files["shop/app/checkout.py"]


@pytest.mark.asyncio
async def test_merge_and_close_pr(repo_root):
    github = FakeGitHub()
    backend = GitHubSabotage(github, repo_root=repo_root)
    incident = Incident(defect_key="checkout-null", pr_number=48)
    await backend.merge_pr(incident)
    assert github.merged == [48]
    await backend.close_pr(incident)
    assert github.closed == [48]
    with pytest.raises(SabotageError):
        await backend.merge_pr(Incident(defect_key="checkout-null"))
