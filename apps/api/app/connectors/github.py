"""GitHub App (user access tokens). Permissions live on the App, not in scopes."""

from __future__ import annotations

import re

import httpx

from app.connectors.base import (
    ConnectorManifest, CredentialField, ResolvedApp, TokenSet, ToolContext, ToolDef, ToolError,
    oauth_client_fields, object_schema, raise_for_status,
)

API = "https://api.github.com"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _h(token: TokenSet) -> dict[str, str]:
    return {"Authorization": f"Bearer {token.access_token}", "Accept": "application/vnd.github+json"}


def _repo(repo: str) -> str:
    repo = repo.strip().removeprefix("https://github.com/").rstrip("/")
    if not REPO_RE.match(repo):
        raise ToolError("repo must look like 'owner/name'")
    return repo


async def account_label(http: httpx.AsyncClient, token: TokenSet, settings) -> str | None:
    resp = await http.get(f"{API}/user", headers=_h(token))
    raise_for_status(resp, "GitHub /user")
    return resp.json().get("login")


async def revoke(http: httpx.AsyncClient, m: ConnectorManifest, token: TokenSet, settings,
                 app: ResolvedApp) -> None:
    client_id, client_secret = m.client_credentials(app)
    await http.request(
        "DELETE",
        f"{API}/applications/{client_id}/token",
        json={"access_token": token.access_token},
        auth=httpx.BasicAuth(client_id, client_secret),
        headers={"Accept": "application/vnd.github+json"},
    )


async def list_repos(ctx: ToolContext) -> dict:
    h = _h(ctx.token)
    inst = await ctx.http.get(f"{API}/user/installations", headers=h, params={"per_page": 100})
    raise_for_status(inst, "Listing GitHub App installations")
    repos: list[dict] = []
    for i in inst.json().get("installations", []):
        resp = await ctx.http.get(f"{API}/user/installations/{i['id']}/repositories", headers=h,
                                  params={"per_page": 100})
        raise_for_status(resp, "Listing repositories")
        repos += [{"full_name": r["full_name"], "private": r.get("private"), "url": r.get("html_url")}
                  for r in resp.json().get("repositories", [])]
    out: dict = {"repos": repos}
    if not repos:
        out["hint"] = "The GitHub App is not installed on any repository yet. Install it from the Connections page."
    return out


async def list_issues(ctx: ToolContext, repo: str, state: str | None) -> dict:
    resp = await ctx.http.get(f"{API}/repos/{_repo(repo)}/issues", headers=_h(ctx.token),
                              params={"state": state or "open", "per_page": 30})
    raise_for_status(resp, "Listing issues")
    return {"issues": [
        {"number": i["number"], "title": i["title"], "state": i["state"], "url": i.get("html_url"),
         "user": (i.get("user") or {}).get("login"), "labels": [lb.get("name") for lb in i.get("labels", [])]}
        for i in resp.json() if "pull_request" not in i
    ]}


async def search_repositories(ctx: ToolContext, query: str, limit: int | None) -> dict:
    resp = await ctx.http.get(f"{API}/search/repositories", headers=_h(ctx.token),
                              params={"q": query, "per_page": max(1, min(limit or 10, 25))})
    raise_for_status(resp, "Searching repositories")
    return {"repos": [{"full_name": r["full_name"], "private": r.get("private"), "url": r.get("html_url"),
                       "description": r.get("description")} for r in resp.json().get("items", [])]}


async def search_issues(ctx: ToolContext, query: str, kind: str, limit: int | None) -> dict:
    """GitHub requires `is:issue` or `is:pull-request` for GitHub App user tokens (search docs)."""
    qualifier = "is:pull-request" if kind == "pull_request" else "is:issue"
    resp = await ctx.http.get(f"{API}/search/issues", headers=_h(ctx.token),
                              params={"q": f"{query} {qualifier}", "per_page": max(1, min(limit or 10, 25))})
    raise_for_status(resp, "Searching issues")
    return {"items": [{"repo": (i.get("repository_url") or "").removeprefix(f"{API}/repos/"), "number": i["number"],
                       "title": i["title"], "state": i["state"], "url": i.get("html_url")}
                      for i in resp.json().get("items", [])]}


async def create_issue(ctx: ToolContext, repo: str, title: str, body: str) -> dict:
    resp = await ctx.http.post(f"{API}/repos/{_repo(repo)}/issues", headers=_h(ctx.token),
                               json={"title": title, "body": body})
    raise_for_status(resp, "Creating the issue")
    i = resp.json()
    return {"number": i["number"], "url": i.get("html_url")}


async def comment_on_issue(ctx: ToolContext, repo: str, number: int, body: str) -> dict:
    resp = await ctx.http.post(f"{API}/repos/{_repo(repo)}/issues/{int(number)}/comments",
                               headers=_h(ctx.token), json={"body": body})
    raise_for_status(resp, "Commenting on the issue")
    return {"id": resp.json().get("id"), "url": resp.json().get("html_url")}


REPO = {"type": "string", "description": "Repository as 'owner/name'."}

from app.connectors.base import LoaderDef, option  # noqa: E402


async def load_repos(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_repos(ctx)
    items = [option(r["full_name"], r["full_name"], "private" if r.get("private") else "public", r.get("url"))
             for r in out["repos"]]
    return [i for i in items if not query or query.lower() in i["name"].lower()]


async def load_issues(ctx: ToolContext, params: dict, query: str | None) -> list[dict]:
    out = await list_issues(ctx, params["repo"], "open")
    return [option(i["number"], f"#{i['number']} {i['title']}", i.get("state"), i.get("url")) for i in out["issues"]]


LOADERS = [
    LoaderDef(name="repos", description="Repositories the GitHub App can see.", handler=load_repos),
    LoaderDef(name="issues", description="Open issues of a repository.", handler=load_issues, needs=["repo"]),
]
_REPO = {"kind": "locator", "loader": "repos", "modes": ["list", "url", "id"], "url_pattern": r"github\.com/([^/\s]+/[^/\s#?]+)"}
PARAM_UI = {
    "github__list_issues": {"repo": _REPO},
    "github__create_issue": {"repo": _REPO},
    "github__comment_on_issue": {
        "repo": _REPO, "number": {"kind": "options", "loader": "issues", "depends_on": ["repo"]}},
}


MANIFEST = ConnectorManifest(
    id="github",
    name="GitHub",
    icon="/icons/github.svg",
    description="List repos and issues, open issues and comment, on repos where the app is installed.",
    auth_type="oauth2",
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    scopes=[],
    token_auth_style="body",
    pkce=True,
    credential_fields=oauth_client_fields(
        id_help="GitHub > Settings > Developer settings > GitHub Apps > your app > Client ID (not the App ID).",
        secret_help="Same page > Generate a new client secret.",
        id_pattern=r"Iv[0-9A-Za-z._]+", id_hint="GitHub App client IDs start with Iv",
        extra=[CredentialField(key="app_slug", label="App slug", required=False, pattern=r"[a-z0-9-]+",
                               pattern_hint="Lowercase letters, digits and dashes",
                               help_text="From the app's public URL github.com/apps/SLUG; used for the install link.")],
    ),
    console_url="https://github.com/settings/apps",
    localhost_redirect="unverified",
    redirect_note="GitHub's docs do not state a localhost rule (its own tutorials use http://localhost "
                  "callbacks). Try localhost first; if GitHub rejects it, use the public HTTPS tunnel.",
    setup_guide=[
        "Create a GitHub App (Settings > Developer settings > GitHub Apps > New GitHub App), not an OAuth App.",
        "Callback URL: the redirect URI below. Tick 'Expire user authorization tokens'. Webhook: off.",
        "Repository permissions: Issues read & write (Metadata read-only is added automatically). No other permission is needed.",
        "Copy the client ID, generate a client secret, and paste both here with the app slug.",
        "After connecting, install the app on the repositories you want to use.",
    ],
    invalid_client_errors=frozenset({"incorrect_client_credentials", "invalid_client"}),
    reauth_errors=frozenset({"invalid_grant", "bad_refresh_token", "bad_verification_code"}),
    setup_url="https://github.com/apps/{app_slug}/installations/new",
    account_label=account_label,
    revoke=revoke,
    health_tool="github__list_repos", health_args={},
    loaders=LOADERS, param_ui=PARAM_UI,
    tools=[
        ToolDef(
            name="github__list_repos",
            description="List repositories the GitHub App can access for this user.",
            parameters=object_schema({}),
            risk="read", handler=list_repos,
        ),
        ToolDef(
            name="github__list_issues",
            description="List issues (not pull requests) in a repository.",
            parameters=object_schema({
                "repo": REPO,
                "state": {"type": ["string", "null"], "enum": ["open", "closed", "all", None],
                          "description": "Issue state filter; null means open."},
            }),
            risk="read", handler=list_issues,
        ),
        ToolDef(
            name="github__search_repositories",
            description="Find repositories by keywords (GitHub search syntax allowed, e.g. 'user:octocat api'). Use "
                        "to turn a name into owner/repo; never ask the user for the full name.",
            parameters=object_schema({
                "query": {"type": "string"},
                "limit": {"type": ["integer", "null"], "description": "1 to 25, or null for 10."}}),
            risk="read", handler=search_repositories,
        ),
        ToolDef(
            name="github__search_issues",
            description="Find issues or pull requests by keywords (add 'repo:owner/name' to narrow). Returns repo, "
                        "number, title and state.",
            parameters=object_schema({
                "query": {"type": "string"},
                "kind": {"enum": ["issue", "pull_request"]},
                "limit": {"type": ["integer", "null"], "description": "1 to 25, or null for 10."}}),
            risk="read", handler=search_issues,
        ),
        ToolDef(
            name="github__create_issue",
            description="Open a new issue in a repository.",
            parameters=object_schema({"repo": REPO, "title": {"type": "string"}, "body": {"type": "string"}}),
            risk="write", handler=create_issue,
        ),
        ToolDef(
            name="github__comment_on_issue",
            description="Add a comment to an existing issue or pull request.",
            parameters=object_schema({"repo": REPO, "number": {"type": "integer"}, "body": {"type": "string"}}),
            risk="write", handler=comment_on_issue,
        ),
    ],
)
