"""GitHub REST v3 client (httpx, async). Two auth modes:

- **App** (preferred when configured): PyJWT RS256 app JWT → installation
  access token (cached, refreshed before expiry).
- **PAT**: plain token header.
- **Anonymous**: no Authorization header — read-only public endpoints only
  (used by the live smoke harness, never in production writes).

Multi-file sabotage/fix commits use the Git Data API (blobs → tree → commit →
update ref) so one defect or one fix is always exactly ONE real commit.
"""

from __future__ import annotations

import base64
import time
from typing import Any, Callable, Optional

import httpx

API_VERSION = "2022-11-28"


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None, raw: Any = None):
        super().__init__(message)
        self.status = status
        self.raw = raw


class GitHubClient:
    def __init__(
        self,
        repo: str,
        *,
        token: str = "",
        app_id: str = "",
        app_private_key_b64: str = "",
        app_installation_id: str = "",
        base_url: str = "https://api.github.com",
        http: Optional[httpx.AsyncClient] = None,
        on_call: Optional[Callable[..., None]] = None,
        timeout: float = 30.0,
    ):
        self.repo = repo
        self._token = token
        self._app_id = app_id
        self._app_key_b64 = app_private_key_b64
        self._app_installation_id = app_installation_id
        self._base_url = base_url.rstrip("/")
        self._own_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self._on_call = on_call
        self._installation_token: str = ""
        self._installation_token_expires: float = 0.0
        self._default_branch: Optional[str] = None

    # ------------------------------------------------------------------ auth

    @property
    def mode(self) -> str:
        if self._app_id and self._app_key_b64:
            return "app"
        if self._token:
            return "pat"
        return "anonymous"

    def _app_jwt(self) -> str:
        import jwt  # PyJWT

        pem = base64.b64decode(self._app_key_b64)
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
            pem,
            algorithm="RS256",
        )

    async def _get_installation_token(self) -> str:
        if self._installation_token and time.time() < self._installation_token_expires - 120:
            return self._installation_token
        if not self._app_installation_id:
            raise GitHubError("GitHub App mode requires GITHUB_APP_INSTALLATION_ID")
        resp = await self._http.post(
            f"{self._base_url}/app/installations/{self._app_installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        if resp.status_code >= 400:
            raise GitHubError(
                f"Installation token request failed: HTTP {resp.status_code}",
                status=resp.status_code,
                raw=resp.text[:500],
            )
        payload = resp.json()
        self._installation_token = payload["token"]
        # expires_at: "2026-06-11T12:34:56Z"
        expires_at = payload.get("expires_at", "")
        try:
            from datetime import datetime, timezone

            self._installation_token_expires = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, AttributeError):
            self._installation_token_expires = time.time() + 50 * 60
        return self._installation_token

    async def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self.mode == "app":
            headers["Authorization"] = f"Bearer {await self._get_installation_token()}"
        elif self.mode == "pat":
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # --------------------------------------------------------------- requests

    async def _req(self, method: str, path: str, *, label: str = "", **kw) -> Any:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        started = time.monotonic()
        ok = False
        try:
            resp = await self._http.request(method, url, headers=await self._headers(), **kw)
            if resp.status_code >= 400:
                message = ""
                try:
                    message = resp.json().get("message", "")
                except Exception:
                    message = resp.text[:200]
                raise GitHubError(
                    f"GitHub {method} {path} -> HTTP {resp.status_code}: {message}",
                    status=resp.status_code,
                    raw=message,
                )
            ok = True
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()
        finally:
            if self._on_call is not None:
                try:
                    self._on_call(label or f"github {method} {path.split('?')[0]}",
                                  time.monotonic() - started, ok=ok)
                except Exception:
                    pass

    # ----------------------------------------------------------------- repos

    async def get_repo_default_branch(self) -> str:
        if self._default_branch is None:
            data = await self._req("GET", f"/repos/{self.repo}", label="github get repo")
            self._default_branch = data.get("default_branch", "main")
        return self._default_branch

    async def get_branch_sha(self, branch: str) -> str:
        data = await self._req("GET", f"/repos/{self.repo}/git/ref/heads/{branch}", label="github get ref")
        return data["object"]["sha"]

    async def get_file(self, path: str, ref: Optional[str] = None) -> dict[str, str]:
        """Returns {"content": <decoded text>, "sha": <blob sha>}."""
        q = f"?ref={ref}" if ref else ""
        data = await self._req("GET", f"/repos/{self.repo}/contents/{path}{q}", label="github get file")
        content = base64.b64decode(data.get("content", "") or "").decode("utf-8")
        return {"content": content, "sha": data.get("sha", "")}

    async def put_file(
        self, path: str, content: str, message: str, branch: str, sha: Optional[str] = None
    ) -> str:
        """Single-file commit via the Contents API. Returns the commit sha."""
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        data = await self._req(
            "PUT", f"/repos/{self.repo}/contents/{path}", json=body, label="github put file"
        )
        return data.get("commit", {}).get("sha", "")

    async def create_branch(self, from_sha: str, name: str) -> str:
        """Create refs/heads/<name> at from_sha; force-updates it if it exists."""
        try:
            await self._req(
                "POST",
                f"/repos/{self.repo}/git/refs",
                json={"ref": f"refs/heads/{name}", "sha": from_sha},
                label="github create branch",
            )
        except GitHubError as e:
            if e.status == 422:  # already exists
                await self._req(
                    "PATCH",
                    f"/repos/{self.repo}/git/refs/heads/{name}",
                    json={"sha": from_sha, "force": True},
                    label="github update branch",
                )
            else:
                raise
        return name

    async def compare(self, base: str, head: str) -> dict[str, Any]:
        data = await self._req(
            "GET", f"/repos/{self.repo}/compare/{base}...{head}", label="github compare"
        )
        commits = [
            {
                "sha": c.get("sha", ""),
                "message": c.get("commit", {}).get("message", ""),
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
            }
            for c in data.get("commits", [])
        ]
        files = [
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": f.get("patch", ""),
            }
            for f in data.get("files", [])
        ]
        return {"commits": commits, "files": files}

    async def get_commit(self, sha: str) -> dict[str, Any]:
        data = await self._req("GET", f"/repos/{self.repo}/commits/{sha}", label="github get commit")
        return {
            "sha": data.get("sha", ""),
            "message": data.get("commit", {}).get("message", ""),
            "date": data.get("commit", {}).get("committer", {}).get("date", "")
            or data.get("commit", {}).get("author", {}).get("date", ""),
            "parents": [p.get("sha", "") for p in data.get("parents", [])],
            "files": [
                {"filename": f.get("filename", ""), "patch": f.get("patch", "")}
                for f in data.get("files", [])
            ],
        }

    async def list_commits(
        self,
        branch: str,
        since: Optional[str] = None,
        path: Optional[str] = None,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"sha": branch, "per_page": per_page}
        if since:
            params["since"] = since
        if path:
            params["path"] = path
        data = await self._req(
            "GET", f"/repos/{self.repo}/commits", params=params, label="github list commits"
        )
        return [
            {
                "sha": c.get("sha", ""),
                "message": c.get("commit", {}).get("message", ""),
                "date": c.get("commit", {}).get("committer", {}).get("date", "")
                or c.get("commit", {}).get("author", {}).get("date", ""),
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
            }
            for c in data
        ]

    # -------------------------------------------------------------- git data

    async def commit_files(self, files: dict[str, str], message: str, branch: str) -> str:
        """ONE real commit containing every file in ``files`` (path -> content),
        via the Git Data API: blobs -> tree -> commit -> update ref."""
        head_sha = await self.get_branch_sha(branch)
        head_commit = await self._req(
            "GET", f"/repos/{self.repo}/git/commits/{head_sha}", label="github get commit obj"
        )
        base_tree = head_commit["tree"]["sha"]
        tree_entries = []
        for path, content in files.items():
            blob = await self._req(
                "POST",
                f"/repos/{self.repo}/git/blobs",
                json={"content": content, "encoding": "utf-8"},
                label="github create blob",
            )
            tree_entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
            )
        tree = await self._req(
            "POST",
            f"/repos/{self.repo}/git/trees",
            json={"base_tree": base_tree, "tree": tree_entries},
            label="github create tree",
        )
        commit = await self._req(
            "POST",
            f"/repos/{self.repo}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [head_sha]},
            label="github create commit",
        )
        await self._req(
            "PATCH",
            f"/repos/{self.repo}/git/refs/heads/{branch}",
            json={"sha": commit["sha"]},
            label="github update ref",
        )
        return commit["sha"]

    async def revert_via_restore(
        self, originals: dict[str, str], message: str, branch: str
    ) -> str:
        """Revert = one new commit restoring the pre-sabotage contents. The
        history stays honest (nothing is force-pushed away)."""
        return await self.commit_files(originals, message, branch)

    # ------------------------------------------------------------------- PRs

    async def create_pr(self, title: str, body: str, head: str, base: str) -> dict[str, Any]:
        data = await self._req(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
            label="github create pr",
        )
        return {"number": data.get("number"), "url": data.get("html_url", "")}

    async def get_pr(self, number: int) -> dict[str, Any]:
        data = await self._req("GET", f"/repos/{self.repo}/pulls/{number}", label="github get pr")
        return {
            "number": data.get("number"),
            "state": data.get("state", ""),
            "merged": bool(data.get("merged")),
            "merge_commit_sha": data.get("merge_commit_sha", ""),
            "head_sha": data.get("head", {}).get("sha", ""),
            "url": data.get("html_url", ""),
        }

    async def merge_pr(self, number: int, method: str = "squash") -> dict[str, Any]:
        data = await self._req(
            "PUT",
            f"/repos/{self.repo}/pulls/{number}/merge",
            json={"merge_method": method},
            label="github merge pr",
        )
        return {"merged": bool(data.get("merged")), "sha": data.get("sha", "")}

    async def close_pr(self, number: int) -> None:
        await self._req(
            "PATCH",
            f"/repos/{self.repo}/pulls/{number}",
            json={"state": "closed"},
            label="github close pr",
        )

    async def comment_pr(self, number: int, body: str) -> str:
        data = await self._req(
            "POST",
            f"/repos/{self.repo}/issues/{number}/comments",
            json={"body": body},
            label="github comment pr",
        )
        return data.get("html_url", "")

    # ---------------------------------------------------------------- checks

    async def get_checks_for_ref(self, sha: str) -> list[dict[str, str]]:
        data = await self._req(
            "GET", f"/repos/{self.repo}/commits/{sha}/check-runs", label="github get checks"
        )
        return [
            {
                "name": run.get("name", ""),
                "status": run.get("status", ""),
                "conclusion": run.get("conclusion") or "",
            }
            for run in data.get("check_runs", [])
        ]

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()
