"""Outbound integrations: Dynatrace MCP gateway, GitHub REST, Gemini on Vertex,
Dynatrace classic Events API. All clients are async (httpx), constructor-injected,
and report per-call wall time through an optional ``on_call`` hook so the medic
can record every real call.
"""
