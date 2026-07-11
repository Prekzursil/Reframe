"""The schema-first RPC contract: source of truth, generator, and runtime loader.

``spec`` is the single source of truth; ``generate`` emits the derived Python +
TypeScript artifacts; ``registry`` + ``validate`` are the runtime consumption
surface. See ``docs/rpc-contract-v2.md``. This package NEVER imports
``media_studio`` (the dependency direction is runtime -> contract, one way).
"""
