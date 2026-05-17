"""Secret storage — BYO platform tokens never touch the regular store.

Backends: in-memory (dev/tests) and Google Secret Manager (deployed).
Secret id convention: `darn-byo-<tenant-host>` with non-alphanumerics dashed,
so the name is derivable from the tenant host and nothing extra persists.
"""

from __future__ import annotations

import re
from typing import Optional, Protocol

from app.config import settings


def byo_secret_name(tenant_host: str) -> str:
    return "darn-byo-" + re.sub(r"[^a-zA-Z0-9_-]", "-", tenant_host.lower())


class SecretBackend(Protocol):
    async def put_secret(self, name: str, value: str) -> None: ...
    async def get_secret(self, name: str) -> Optional[str]: ...
    async def delete_secret(self, name: str) -> None: ...


class MemorySecretBackend:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def put_secret(self, name: str, value: str) -> None:
        self._values[name] = value

    async def get_secret(self, name: str) -> Optional[str]:
        return self._values.get(name)

    async def delete_secret(self, name: str) -> None:
        self._values.pop(name, None)


class GcpSecretBackend:
    """Google Secret Manager. Imported lazily so memory mode needs no GCP libs."""

    def __init__(self) -> None:
        from google.cloud import secretmanager

        self._client = secretmanager.SecretManagerServiceAsyncClient()
        self._parent = f"projects/{settings.gcp_project}"

    async def put_secret(self, name: str, value: str) -> None:
        from google.api_core import exceptions as gexc

        try:
            await self._client.create_secret(
                request={
                    "parent": self._parent,
                    "secret_id": name,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        except gexc.AlreadyExists:
            pass
        await self._client.add_secret_version(
            request={
                "parent": f"{self._parent}/secrets/{name}",
                "payload": {"data": value.encode("utf-8")},
            }
        )

    async def get_secret(self, name: str) -> Optional[str]:
        from google.api_core import exceptions as gexc

        try:
            resp = await self._client.access_secret_version(
                request={"name": f"{self._parent}/secrets/{name}/versions/latest"}
            )
            return resp.payload.data.decode("utf-8")
        except gexc.NotFound:
            return None

    async def delete_secret(self, name: str) -> None:
        from google.api_core import exceptions as gexc

        try:
            await self._client.delete_secret(
                request={"name": f"{self._parent}/secrets/{name}"}
            )
        except gexc.NotFound:
            pass


def get_secret_backend() -> SecretBackend:
    if settings.secrets_mode == "gcp":
        return GcpSecretBackend()
    return MemorySecretBackend()
