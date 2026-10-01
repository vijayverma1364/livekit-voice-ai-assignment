# Automated & Integration Tests

This directory will contain the test suite for the **Supervised Voice AI Agent on Self-Hosted LiveKit** system.

## Test Categorization
- `unit/`: Unit tests for API schemas, agent state machines, latency calculators, and deterministic compliance evaluators.
- `integration/`: Integration tests testing FastAPI endpoints with PostgreSQL and LiveKit token generation.
- `e2e/`: End-to-end voice and supervisor simulation tests.

## Planned Structure
```
tests/
├── unit/
│   ├── test_compliance_rules.py
│   ├── test_latency_tracking.py
│   └── test_api_schemas.py
├── integration/
│   ├── test_agents_api.py
│   ├── test_calls_api.py
│   └── test_livekit_token.py
├── conftest.py
└── README.md
```
