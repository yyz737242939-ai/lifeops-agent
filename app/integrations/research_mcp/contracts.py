"""Stable MCP wire contracts shared by the server and adapter."""

SEARCH_PAPERS_INPUT_SCHEMA = {
    "properties": {
        "query": {
            "maxLength": 200,
            "minLength": 1,
            "title": "Query",
            "type": "string",
        },
        "limit": {
            "default": 5,
            "maximum": 10,
            "minimum": 1,
            "title": "Limit",
            "type": "integer",
        },
    },
    "required": ["query"],
    "title": "search_papersArguments",
    "type": "object",
}
