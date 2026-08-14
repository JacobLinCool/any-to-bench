"""Agentic backend: model strings with the ``codex:`` prefix run the Codex CLI
in a sandboxed workspace instead of direct LLM calls, with a validate-and-fix
loop until the outputs satisfy the bundle contracts.
"""
