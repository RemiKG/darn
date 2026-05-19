"""GitHubClient over httpx.MockTransport: PAT + App auth, the Git Data
multi-file commit flow (blobs -> tree -> commit -> ref), compare, and PRs."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.integrations.github_client import GitHubClient, GitHubError

REPO = "remikg/loose-threads"


def _client(handler, **kw) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    return GitHubClient(REPO, http=httpx.AsyncClient(transport=transport), **kw)


@pytest.mark.asyncio
async def test_pat_mode_sends_bearer_and_reads_file():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer ghp_test"
        assert request.url.path == f"/repos/{REPO}/contents/shop/app/checkout.py"
        assert request.url.params["ref"] == "main"
        content = base64.b64encode(b"def total(cart): ...\n").decode()
        return httpx.Response(200, json={"content": content, "sha": "blob123"})

    client = _client(handler, token="ghp_test")
    out = await client.get_file("shop/app/checkout.py", ref="main")
    assert out == {"content": "def total(cart): ...\n", "sha": "blob123"}
    await client.aclose()


@pytest.mark.asyncio
async def test_app_mode_exchanges_jwt_for_installation_token():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/installations/42/access_tokens":
            auth = request.headers["authorization"]
            assert auth.startswith("Bearer ")
            jwt_token = auth.split(" ", 1)[1]
            assert jwt_token.count(".") == 2  # app JWT shape
            seen["jwt"] = jwt_token
            return httpx.Response(
                201, json={"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"}
            )
        if request.url.path == f"/repos/{REPO}":
            seen["repo_auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"default_branch": "main"})
        raise AssertionError(request.url.path)

    client = _client(
        handler,
        app_id="12345",
        app_private_key_b64=base64.b64encode(pem).decode(),
        app_installation_id="42",
    )
    assert client.mode == "app"
    assert await client.get_repo_default_branch() == "main"
    assert seen["repo_auth"] == "Bearer ghs_installation"

    # JWT really is RS256-signed with our key
    import jwt as pyjwt

    claims = pyjwt.decode(
        seen["jwt"], key.public_key(), algorithms=["RS256"], options={"verify_exp": False}
    )
    assert claims["iss"] == "12345"
    await client.aclose()


@pytest.mark.asyncio
async def test_git_data_multi_file_commit_is_one_commit():
    log: list[str] = []
    blobs = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        log.append(f"{request.method} {path}")
        if path == f"/repos/{REPO}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if path == f"/repos/{REPO}/git/commits/base-sha":
            return httpx.Response(200, json={"tree": {"sha": "tree-0"}})
        if path == f"/repos/{REPO}/git/blobs":
            blobs["n"] += 1
            return httpx.Response(201, json={"sha": f"blob-{blobs['n']}"})
        if path == f"/repos/{REPO}/git/trees":
            body = json.loads(request.content)
            assert body["base_tree"] == "tree-0"
            assert {e["path"] for e in body["tree"]} == {"shop/app/checkout.py", "shop/app/cart.py"}
            assert all(e["mode"] == "100644" and e["type"] == "blob" for e in body["tree"])
            return httpx.Response(201, json={"sha": "tree-1"})
        if path == f"/repos/{REPO}/git/commits" and request.method == "POST":
            body = json.loads(request.content)
            assert body["parents"] == ["base-sha"]
            assert body["message"] == "fix: tidy cart handling"
            return httpx.Response(201, json={"sha": "commit-1"})
        if path == f"/repos/{REPO}/git/refs/heads/main":
            assert json.loads(request.content)["sha"] == "commit-1"
            return httpx.Response(200, json={})
        raise AssertionError(path)

    client = _client(handler, token="ghp_test")
    sha = await client.commit_files(
        {"shop/app/checkout.py": "a\n", "shop/app/cart.py": "b\n"},
        "fix: tidy cart handling",
        "main",
    )
    assert sha == "commit-1"
    # exactly ONE commit object created
    assert log.count(f"POST /repos/{REPO}/git/commits") == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_compare_maps_commits_and_files():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/repos/{REPO}/compare/abc...def"
        return httpx.Response(
            200,
            json={
                "commits": [
                    {
                        "sha": "def",
                        "commit": {
                            "message": "chore: simplify checkout maths",
                            "author": {"name": "remi", "date": "2026-06-11T02:56:36Z"},
                        },
                    }
                ],
                "files": [
                    {
                        "filename": "shop/app/checkout.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "patch": "@@ -115,7 +115,9 @@\n-    safe\n+    boom",
                    }
                ],
            },
        )

    client = _client(handler, token="ghp_test")
    out = await client.compare("abc", "def")
    assert out["commits"][0]["message"] == "chore: simplify checkout maths"
    assert out["files"][0]["filename"] == "shop/app/checkout.py"
    assert "+    boom" in out["files"][0]["patch"]
    await client.aclose()


@pytest.mark.asyncio
async def test_create_merge_close_comment_pr_and_checks():
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == f"/repos/{REPO}/pulls" and method == "POST":
            body = json.loads(request.content)
            assert body["head"] == "darn/fix-checkout-null"
            return httpx.Response(
                201, json={"number": 48, "html_url": f"https://github.com/{REPO}/pull/48"}
            )
        if path == f"/repos/{REPO}/pulls/48/merge":
            return httpx.Response(200, json={"merged": True, "sha": "merge-sha"})
        if path == f"/repos/{REPO}/pulls/48" and method == "PATCH":
            assert json.loads(request.content) == {"state": "closed"}
            return httpx.Response(200, json={})
        if path == f"/repos/{REPO}/issues/48/comments":
            return httpx.Response(201, json={"html_url": "https://github.com/c/1"})
        if path == f"/repos/{REPO}/commits/merge-sha/check-runs":
            return httpx.Response(
                200,
                json={
                    "check_runs": [
                        {"name": "deploy", "status": "completed", "conclusion": "success"}
                    ]
                },
            )
        raise AssertionError(f"{method} {path}")

    client = _client(handler, token="ghp_test")
    pr = await client.create_pr("Mend: null cart", "body", "darn/fix-checkout-null", "main")
    assert pr == {"number": 48, "url": f"https://github.com/{REPO}/pull/48"}
    merged = await client.merge_pr(48)
    assert merged["merged"] and merged["sha"] == "merge-sha"
    checks = await client.get_checks_for_ref("merge-sha")
    assert checks == [{"name": "deploy", "status": "completed", "conclusion": "success"}]
    await client.close_pr(48)
    assert await client.comment_pr(48, "closed!") == "https://github.com/c/1"
    await client.aclose()


@pytest.mark.asyncio
async def test_create_branch_force_updates_when_it_exists():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(422, json={"message": "Reference already exists"})
        if request.method == "PATCH":
            body = json.loads(request.content)
            assert body == {"sha": "new-sha", "force": True}
            return httpx.Response(200, json={})
        raise AssertionError()

    client = _client(handler, token="ghp_test")
    await client.create_branch("new-sha", "darn/fix-checkout-null")
    assert len(calls) == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_errors_carry_status_and_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _client(handler, token="ghp_test")
    with pytest.raises(GitHubError) as exc:
        await client.get_file("missing.py")
    assert exc.value.status == 404
    assert "Not Found" in str(exc.value)
    await client.aclose()
