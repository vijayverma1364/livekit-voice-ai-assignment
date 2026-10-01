# Backend Service (FastAPI Control Plane)

This directory will contain the stateless FastAPI backend service for the **Supervised Voice AI Agent on Self-Hosted LiveKit** platform.

## Responsibilities
- REST API implementation following [API_CONTRACTS.md](../API_CONTRACTS.md).
- Endpoints:
  - `GET /health`
  - `POST /agents`
  - `GET /agents/{id}`
  - `POST /calls`
  - `GET /calls/{id}`
  - `POST /calls/{id}/supervisor-token`
- PostgreSQL integration via async connection pooling.
- LiveKit token generation and room access control.

## Planned Structure (Phase 1)
```
backend/
├── app/
│   ├── api/
│   │   ├── routes_agents.py
│   │   ├── routes_calls.py
│   │   └── routes_health.py
│   ├── core/
│   │   ├── config.py
│   │   └── security.py
│   ├── db/
│   │   ├── session.py
│   │   └── models.py
│   ├── schemas/
│   │   ├── agent.py
│   │   ├── call.py
│   │   └── compliance.py
│   ├── services/
│   │   └── livekit_service.py
│   └── main.py
├── requirements.txt
├── Dockerfile
└── README.md
```
