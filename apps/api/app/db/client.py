"""Minimal data access over Supabase PostgREST using the service role key.

`Database` is the interface the app uses; `SupabaseRestDatabase` talks to
PostgREST, `MemoryDatabase` backs the tests. Filters are equality only.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

Row = dict[str, Any]


class Database(Protocol):
    async def select(self, table: str, filters: Row | None = None, order: str | None = None) -> list[Row]: ...
    async def insert(self, table: str, row: Row) -> Row: ...
    async def update(self, table: str, filters: Row, values: Row) -> list[Row]: ...
    async def delete(self, table: str, filters: Row) -> list[Row]: ...
    async def delete_older_than(self, table: str, column: str, cutoff: datetime) -> None: ...
    async def rpc(self, fn: str, args: Row) -> Any: ...


def _eq_params(filters: Row | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in (filters or {}).items():
        if value is None:
            params[key] = "is.null"
        elif isinstance(value, bool):
            params[key] = f"is.{str(value).lower()}"
        else:
            params[key] = f"eq.{value}"
    return params


class SupabaseRestDatabase:
    def __init__(self, supabase_url: str, service_key: str, http: httpx.AsyncClient):
        self._base = f"{supabase_url.rstrip('/')}/rest/v1"
        self._http = http
        headers = {"apikey": service_key, "Content-Type": "application/json"}
        # Legacy keys are JWTs and go in Authorization; new sb_secret_ keys use apikey only.
        if service_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {service_key}"
        self._headers = headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        resp = await self._http.request(method, f"{self._base}/{path}", headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {path} failed with {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    async def select(self, table: str, filters: Row | None = None, order: str | None = None) -> list[Row]:
        params = {"select": "*", **_eq_params(filters)}
        if order:
            params["order"] = order
        return await self._request("GET", table, params=params)

    async def insert(self, table: str, row: Row) -> Row:
        rows = await self._request("POST", table, json=row, headers={"Prefer": "return=representation"})
        return rows[0]

    async def update(self, table: str, filters: Row, values: Row) -> list[Row]:
        return await self._request(
            "PATCH", table, params=_eq_params(filters), json=values, headers={"Prefer": "return=representation"}
        )

    async def delete(self, table: str, filters: Row) -> list[Row]:
        if not filters:
            raise ValueError("refusing unfiltered delete")
        return await self._request(
            "DELETE", table, params=_eq_params(filters), headers={"Prefer": "return=representation"}
        )

    async def delete_older_than(self, table: str, column: str, cutoff: datetime) -> None:
        await self._request("DELETE", table, params={column: f"lt.{cutoff.isoformat()}"})

    async def rpc(self, fn: str, args: Row) -> Any:
        return await self._request("POST", f"rpc/{fn}", json=args)


class MemoryDatabase:
    """In-memory stand-in with the same semantics, for tests."""

    def __init__(self) -> None:
        self.tables: dict[str, list[Row]] = {}
        self.rpcs: dict[str, Any] = {}

    def _rows(self, table: str) -> list[Row]:
        return self.tables.setdefault(table, [])

    @staticmethod
    def _match(row: Row, filters: Row | None) -> bool:
        return all(str(row.get(k)) == str(v) if v is not None else row.get(k) is None
                   for k, v in (filters or {}).items())

    async def select(self, table: str, filters: Row | None = None, order: str | None = None) -> list[Row]:
        return [copy.deepcopy(r) for r in self._rows(table) if self._match(r, filters)]

    async def insert(self, table: str, row: Row) -> Row:
        row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **row}
        if table == "connections":
            row.setdefault("status", "active")
            row.setdefault("auto_approve_writes", False)
            for other in self._rows(table):
                if all(other.get(k) == row.get(k) for k in ("user_id", "provider", "account_label")):
                    raise RuntimeError("duplicate key value violates unique constraint")
        self._rows(table).append(row)
        return copy.deepcopy(row)

    async def update(self, table: str, filters: Row, values: Row) -> list[Row]:
        out = []
        for row in self._rows(table):
            if self._match(row, filters):
                row.update(values)
                out.append(copy.deepcopy(row))
        return out

    async def delete(self, table: str, filters: Row) -> list[Row]:
        rows = self._rows(table)
        gone = [r for r in rows if self._match(r, filters)]
        self.tables[table] = [r for r in rows if not self._match(r, filters)]
        return gone

    async def delete_older_than(self, table: str, column: str, cutoff: datetime) -> None:
        self.tables[table] = [
            r for r in self._rows(table) if datetime.fromisoformat(r[column]) >= cutoff
        ]

    async def rpc(self, fn: str, args: Row) -> Any:
        return self.rpcs[fn](**args)
