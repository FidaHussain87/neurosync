"""NeuroSync Python SDK — sync and async clients for the NeuroSync REST API."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any, Optional


class NeuroSyncError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"NeuroSync error {status_code}: {message}")
        self.status_code = status_code


class NeuroSyncClient:
    def __init__(
        self,
        api_key: str = "",
        project: str = "",
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._project = project
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict:
        url = f"{self._base_url}/v1/{endpoint}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
                msg = payload.get("detail") or payload.get("message") or str(payload)
            except Exception:
                msg = raw.decode("utf-8", errors="replace")
            raise NeuroSyncError(exc.code, msg) from exc
        except urllib.error.URLError as exc:
            raise NeuroSyncError(0, str(exc.reason)) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NeuroSyncError(0, "Invalid JSON response") from exc

    def _inject_project(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._project and "project" not in body:
            body["project"] = self._project
        return body

    def recall(self, context: str = "", branch: str = "", max_tokens: int = 500) -> dict:
        body: dict[str, Any] = {"context": context, "branch": branch, "max_tokens": max_tokens}
        return self._post("recall", self._inject_project(body))

    def record(
        self,
        events: list[dict],
        session_summary: str = "",
        explicit_remember: Optional[list[str]] = None,
    ) -> dict:
        body: dict[str, Any] = {
            "events": events,
            "session_summary": session_summary,
            "explicit_remember": explicit_remember or [],
        }
        return self._post("record", self._inject_project(body))

    def remember(
        self,
        content: str,
        reasoning: str = "",
        importance: int = 3,
        cause: str = "",
        effect: str = "",
    ) -> dict:
        body: dict[str, Any] = {
            "content": content,
            "reasoning": reasoning,
            "importance": importance,
            "cause": cause,
            "effect": effect,
        }
        return self._post("remember", body)

    def query(
        self,
        query: str,
        scope: str = "all",
        mode: str = "semantic",
        limit: int = 10,
    ) -> dict:
        body: dict[str, Any] = {"query": query, "scope": scope, "mode": mode, "limit": limit}
        return self._post("query", self._inject_project(body))

    def correct(self, wrong: str, right: str, theory_id: str = "") -> dict:
        body: dict[str, Any] = {"wrong": wrong, "right": right, "theory_id": theory_id}
        return self._post("correct", body)

    def status(self) -> dict:
        return self._post("status", {})

    def theories(
        self,
        action: str = "list",
        scope: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 20,
        theory_id: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {"action": action, "limit": limit}
        if scope is not None:
            body["scope"] = scope
        if project is not None:
            body["project"] = project
        if theory_id is not None:
            body["theory_id"] = theory_id
        return self._post("theories", body)

    def consolidate(self, dry_run: bool = False) -> dict:
        return self._post("consolidate", {"dry_run": dry_run})

    def handoff(
        self,
        goal: str,
        accomplished: str,
        remaining: str,
        next_step: str,
        blockers: str = "",
    ) -> dict:
        body: dict[str, Any] = {
            "goal": goal,
            "accomplished": accomplished,
            "remaining": remaining,
            "next_step": next_step,
            "blockers": blockers,
        }
        return self._post("handoff", body)

    def poll(self, context: str = "") -> dict:
        body: dict[str, Any] = {"context": context}
        return self._post("poll", self._inject_project(body))


class AsyncNeuroSyncClient:
    """Async wrapper — delegates to NeuroSyncClient via executor to avoid duplicating method bodies."""

    def __init__(self, **kwargs: Any) -> None:
        self._sync = NeuroSyncClient(**kwargs)

    async def _call(self, method_name: str, *args: Any, **kwargs: Any) -> dict:
        loop = asyncio.get_running_loop()
        fn = getattr(self._sync, method_name)
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def recall(self, context: str = "", branch: str = "", max_tokens: int = 500) -> dict:
        return await self._call("recall", context=context, branch=branch, max_tokens=max_tokens)

    async def record(
        self,
        events: list[dict],
        session_summary: str = "",
        explicit_remember: Optional[list[str]] = None,
    ) -> dict:
        return await self._call("record", events=events, session_summary=session_summary, explicit_remember=explicit_remember)

    async def remember(
        self,
        content: str,
        reasoning: str = "",
        importance: int = 3,
        cause: str = "",
        effect: str = "",
    ) -> dict:
        return await self._call("remember", content=content, reasoning=reasoning, importance=importance, cause=cause, effect=effect)

    async def query(
        self,
        query: str,
        scope: str = "all",
        mode: str = "semantic",
        limit: int = 10,
    ) -> dict:
        return await self._call("query", query=query, scope=scope, mode=mode, limit=limit)

    async def correct(self, wrong: str, right: str, theory_id: str = "") -> dict:
        return await self._call("correct", wrong=wrong, right=right, theory_id=theory_id)

    async def status(self) -> dict:
        return await self._call("status")

    async def theories(
        self,
        action: str = "list",
        scope: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 20,
        theory_id: Optional[str] = None,
    ) -> dict:
        return await self._call("theories", action=action, scope=scope, project=project, limit=limit, theory_id=theory_id)

    async def consolidate(self, dry_run: bool = False) -> dict:
        return await self._call("consolidate", dry_run=dry_run)

    async def handoff(
        self,
        goal: str,
        accomplished: str,
        remaining: str,
        next_step: str,
        blockers: str = "",
    ) -> dict:
        return await self._call("handoff", goal=goal, accomplished=accomplished, remaining=remaining, next_step=next_step, blockers=blockers)

    async def poll(self, context: str = "") -> dict:
        return await self._call("poll", context=context)


NeuroSync = NeuroSyncClient
