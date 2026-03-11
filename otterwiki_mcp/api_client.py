"""Async HTTP client wrapping the Otterwiki REST API."""

import httpx


class WikiAPIError(Exception):
    """Non-2xx response from the wiki API."""

    def __init__(self, status_code: int, detail: str, path: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.path = path
        super().__init__(f"HTTP {status_code}: {detail}")


class WikiClient:
    """Async wrapper for Otterwiki REST API + semantic search endpoints."""

    def __init__(self, base_url: str, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    @staticmethod
    def _validate_path(path: str) -> None:
        """Reject page paths that could cause traversal or injection."""
        if not path:
            raise ValueError("Page path must not be empty")
        if "\x00" in path:
            raise ValueError("Page path must not contain null bytes")
        if ".." in path:
            raise ValueError("Page path must not contain '..'")
        if path.startswith("/"):
            raise ValueError("Page path must not start with '/'")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an HTTP request; return JSON on success, raise WikiAPIError on failure."""
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("error", resp.text)
            except Exception:
                detail = resp.text
            raise WikiAPIError(resp.status_code, detail, path)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise WikiAPIError(
                resp.status_code,
                resp.text,
                path,
            )

    # --- Pages ---

    async def get_page(self, page_path: str, revision: str | None = None) -> dict:
        self._validate_path(page_path)
        params = {}
        if revision:
            params["revision"] = revision
        return await self._request("GET", f"/api/v1/pages/{page_path}", params=params)

    async def list_pages(
        self,
        prefix: str = "",
        category: str = "",
        tag: str = "",
        updated_since: str = "",
    ) -> dict:
        params = {}
        if prefix:
            params["prefix"] = prefix
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag
        if updated_since:
            params["updated_since"] = updated_since
        return await self._request("GET", "/api/v1/pages", params=params)

    async def put_page(
        self,
        page_path: str,
        content: str,
        commit_message: str | None = None,
    ) -> dict:
        self._validate_path(page_path)
        body: dict = {"content": content}
        if commit_message:
            body["commit_message"] = f"[mcp] {commit_message}"
        else:
            # Let the API auto-generate with its own prefix
            pass
        return await self._request("PUT", f"/api/v1/pages/{page_path}", json=body)

    async def patch_page(
        self,
        page_path: str,
        revision: str,
        old_string: str,
        new_string: str,
        commit_message: str | None = None,
    ) -> dict:
        self._validate_path(page_path)
        body: dict = {
            "revision": revision,
            "old_string": old_string,
            "new_string": new_string,
        }
        if commit_message:
            body["commit_message"] = f"[mcp] {commit_message}"
        return await self._request("PATCH", f"/api/v1/pages/{page_path}", json=body)

    async def delete_page(
        self, page_path: str, commit_message: str | None = None
    ) -> dict:
        self._validate_path(page_path)
        body: dict = {}
        if commit_message:
            body["commit_message"] = f"[mcp] {commit_message}"
        else:
            body["commit_message"] = f"[mcp] Delete: {page_path}"
        return await self._request("DELETE", f"/api/v1/pages/{page_path}", json=body)

    async def rename_page(
        self,
        page_path: str,
        new_path: str,
        commit_message: str | None = None,
    ) -> dict:
        self._validate_path(page_path)
        self._validate_path(new_path)
        body: dict = {"new_path": new_path}
        if commit_message:
            body["commit_message"] = f"[mcp] {commit_message}"
        return await self._request(
            "POST", f"/api/v1/pages/{page_path}/rename", json=body
        )

    async def get_history(self, page_path: str, limit: int | None = None) -> dict:
        self._validate_path(page_path)
        params = {}
        if limit is not None:
            params["limit"] = limit
        return await self._request(
            "GET", f"/api/v1/pages/{page_path}/history", params=params
        )

    # --- Search ---

    async def search(self, query: str) -> dict:
        return await self._request("GET", "/api/v1/search", params={"q": query})

    async def semantic_search(self, query: str, n: int = 5) -> dict:
        return await self._request(
            "GET", "/api/v1/semantic-search", params={"q": query, "n": n}
        )

    # --- Links ---

    async def get_links(self, page_path: str) -> dict:
        self._validate_path(page_path)
        return await self._request("GET", f"/api/v1/links/{page_path}")

    # --- Changelog ---

    async def get_changelog(self, limit: int = 20) -> dict:
        return await self._request(
            "GET", "/api/v1/changelog", params={"limit": limit}
        )

    async def close(self):
        await self._client.aclose()
