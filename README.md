# otterwiki-mcp

An MCP server that lets Claude read, write, search, and navigate an [An Otter Wiki](https://otterwiki.com/) instance over Streamable HTTP.

It sits between Claude (or any MCP client) and Otterwiki's REST API, translating tool calls into HTTP requests. It does not run inside Otterwiki — it's a standalone service.

## Tools

| Tool | What it does |
|------|-------------|
| `read_note` | Read a page (optionally at a specific revision) |
| `write_note` | Create or update a page with markdown + YAML frontmatter |
| `delete_note` | Delete a page |
| `list_notes` | List pages with optional filters (prefix, category, tag, date) |
| `search_notes` | Full-text keyword search |
| `semantic_search` | Vector similarity search via ChromaDB |
| `get_links` | Show incoming/outgoing WikiLinks for a page |
| `get_history` | Show revision history for a page |
| `get_recent_changes` | Show recent edits across the wiki |
| `find_orphaned_notes` | Find pages not linked from any index page |

## Running

The included `docker-compose.yml` brings up Otterwiki (with API and semantic search plugins), ChromaDB, and the MCP server:

```sh
cp .env.example .env   # fill in your secrets
docker compose up
```

The MCP endpoint will be at `http://localhost:8090/mcp`.

## Configuration

All via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OTTERWIKI_API_URL` | yes | | Base URL of the Otterwiki instance |
| `OTTERWIKI_API_KEY` | yes | | API key for authenticating with Otterwiki |
| `MCP_BASE_URL` | yes | | Externally-reachable URL of this MCP server (e.g. `https://mcp.example.com`). Used for OAuth discovery endpoints. |
| `MCP_AUTH_TOKEN` | no | | Optional bearer token for Claude Code access. If set, clients can authenticate with `Authorization: Bearer <token>` in addition to OAuth. |
| `MCP_PORT` | no | `8090` | Port the MCP server listens on |

## Authentication

The server supports two authentication methods:

- **OAuth 2.1** (primary) — Used by Claude.ai. The server acts as its own OAuth authorization server via FastMCP's `InMemoryOAuthProvider`, handling Dynamic Client Registration, PKCE, and token management. OAuth state is in-memory; a server restart requires re-authentication.
- **Bearer token** (optional) — Used by Claude Code. Enabled when `MCP_AUTH_TOKEN` is set. Clients send `Authorization: Bearer <token>` in HTTP headers.

### Connecting from Claude.ai

1. In Claude.ai, go to Settings > Connectors > Add custom connector
2. Enter the server URL (e.g. `https://mcp.example.com/mcp`)
3. Leave Client ID and Client Secret blank — Dynamic Client Registration handles it
4. Click Add

### Connecting from Claude Code

Add to your MCP server configuration with the bearer token in headers:

```json
{
  "mcpServers": {
    "otterwiki": {
      "type": "streamable-http",
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

## Deployment

Terminate TLS in front of the MCP server (nginx, Caddy, etc.) so tokens aren't sent in cleartext.

## Dependencies

- [FastMCP](https://github.com/jlowin/fastmcp) >= 2.0
- [httpx](https://www.python-httpx.org/) >= 0.27

Requires the [otterwiki-api](../otterwiki-api) plugin installed in the Otterwiki instance. The [otterwiki-semantic-search](../otterwiki-semantic-search) plugin is needed for the `semantic_search` tool.

## Development

```sh
pip install -e ".[dev]"
pytest
```

## License

MIT. See [LICENSE](LICENSE) for details.
