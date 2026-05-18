"""The Darn agent pipeline: detect -> diagnose -> fix -> pr -> verify.

Every stage emits typed receipts (app.models.Receipt) through the StageEmitter
the orchestrator provides. Receipts only ever record REAL executed calls —
when a dependency is missing or a scope is denied, the pipeline degrades to an
honest note, never to fabricated data.

Entry point for the core server: ``app.agent.wiring.build_backends()``.
"""
