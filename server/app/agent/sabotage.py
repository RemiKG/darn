"""SabotageBackend — ships a pre-authored defect as ONE real commit to the
public repo's default branch, and can cleanly revert it.

Defect patches live in the monorepo at ``shop/defects/<key>/patch.json``:
``{"files": [{"path", "sabotaged_content"}], "commit_message", "davis_expectation"}``.
Pre-sabotage originals are captured from GitHub (not from disk) right before
the commit, so revert restores exactly what production had.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from ..integrations.github_client import GitHubClient
from ..models import Incident

log = logging.getLogger("darn.agent.sabotage")


class SabotageError(RuntimeError):
    pass


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from this file (server/app/agent/) looking for shop/defects.

    Layout: repo/server/app/agent/sabotage.py -> repo is parents[3]. We still
    walk the whole ancestry so a vendored/copied layout keeps working.
    """
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "shop" / "defects").is_dir():
            return candidate
    return None


def load_patch(defect_key: str, repo_root: Optional[Path] = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    if root is None:
        raise SabotageError(
            "Could not locate the repo root (no shop/defects directory above "
            f"{Path(__file__).resolve()})"
        )
    patch_path = root / "shop" / "defects" / defect_key / "patch.json"
    if not patch_path.is_file():
        raise SabotageError(f"Unknown defect '{defect_key}' (no {patch_path})")
    with open(patch_path, "r", encoding="utf-8") as fh:
        patch = json.load(fh)
    if not patch.get("files"):
        raise SabotageError(f"Defect '{defect_key}' patch.json has no files")
    return patch


class GitHubSabotage:
    """Implements the SabotageBackend seam:

    - ``commit_defect(defect_key) -> {sha, message, files}``
    - ``revert(incident) -> sha``
    - ``merge_pr(incident)`` / ``close_pr(incident)``
    """

    def __init__(self, github: GitHubClient, *, repo_root: Optional[Path] = None):
        self._github = github
        self._repo_root = repo_root
        # pre-sabotage originals, keyed by defect: {path: original content}
        self._originals: dict[str, dict[str, str]] = {}
        self._messages: dict[str, str] = {}

    async def commit_defect(self, defect_key: str) -> dict[str, Any]:
        patch = load_patch(defect_key, self._repo_root)
        branch = await self._github.get_repo_default_branch()
        files: dict[str, str] = {}
        originals: dict[str, str] = {}
        for entry in patch["files"]:
            path = entry["path"]
            current = await self._github.get_file(path, ref=branch)
            originals[path] = current["content"]
            files[path] = entry["sabotaged_content"]
        # Capture originals BEFORE committing so revert is always possible.
        self._originals[defect_key] = originals
        message = patch.get("commit_message") or f"chore: update {', '.join(files)}"
        self._messages[defect_key] = message
        sha = await self._github.commit_files(files, message, branch)
        log.info("sabotage %s committed as %s (%d files)", defect_key, sha[:7], len(files))
        return {"sha": sha, "message": message, "files": sorted(files.keys())}

    async def revert(self, incident: Incident) -> str:
        defect_key = incident.defect_key or ""
        originals = self._originals.get(defect_key)
        if not originals:
            # Process restarted mid-incident: recover originals from git history
            # (the parent of the sabotage commit holds the pre-sabotage content).
            if not incident.sabotage_sha:
                raise SabotageError(
                    f"No stored originals and no sabotage sha for incident {incident.id}"
                )
            commit = await self._github.get_commit(incident.sabotage_sha)
            parent = commit["parents"][0] if commit["parents"] else None
            if parent is None:
                raise SabotageError("Sabotage commit has no parent to restore from")
            patch = load_patch(defect_key, self._repo_root)
            originals = {}
            for entry in patch["files"]:
                originals[entry["path"]] = (
                    await self._github.get_file(entry["path"], ref=parent)
                )["content"]
        branch = await self._github.get_repo_default_branch()
        message = f'Revert "{self._messages.get(defect_key, defect_key)}"'
        sha = await self._github.revert_via_restore(originals, message, branch)
        self._originals.pop(defect_key, None)
        return sha

    async def merge_pr(self, incident: Incident) -> None:
        if not incident.pr_number:
            raise SabotageError(f"Incident {incident.id} has no PR to merge")
        result = await self._github.merge_pr(incident.pr_number, method="squash")
        if not result.get("merged"):
            raise SabotageError(f"PR #{incident.pr_number} did not merge")

    async def close_pr(self, incident: Incident) -> None:
        if not incident.pr_number:
            return
        await self._github.close_pr(incident.pr_number)
