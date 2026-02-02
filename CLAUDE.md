# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StandX Market Maker - an automated market-making system for cryptocurrency perpetual futures with multi-account hedging support. The system provides bilateral order placement for liquidity provision, real-time monitoring, and risk management.

## Commands

```bash
# Production mode - serves frontend+backend on localhost:9999
./start.sh

# Development mode - backend:9999, frontend:3000 with hot reload
./start.sh --dev

# Force rebuild frontend before starting
./start.sh --rebuild

# Frontend only
cd frontend && npm run build   # Build to src/web/frontend_dist/
cd frontend && npm run dev     # Dev server with HMR
cd frontend && npm run lint    # ESLint

# Tests
pytest                         # Run all tests
pytest -v                      # Verbose
```

## Architecture

```
Frontend (React 18 + Vite + TypeScript)
        ↓ WebSocket + REST API
Backend (FastAPI + Uvicorn on :9999)
        ↓
Trading Adapters → Strategy Engine → Risk Management
```

### Key Modules

| Path | Purpose |
|------|---------|
| `src/web/auto_dashboard.py` | Main entry point, FastAPI app startup |
| `src/web/system_manager.py` | Adapter lifecycle, multi-strategy management |
| `src/web/api/` | REST endpoints (config, mm, accounts, simulation) |
| `src/adapters/` | Exchange integrations (StandX, GRVT, CCXT) |
| `src/strategy/market_maker_executor.py` | Core MM logic (event-driven) |
| `src/strategy/mm_state.py` | Thread-safe state management |
| `src/strategy/hedge_engine.py` | Multi-account hedging |
| `src/config/account_config.py` | Account pool and strategy configuration |
| `frontend/src/pages/` | React page components |
| `frontend/src/hooks/useWebSocket.ts` | Real-time data subscription |

### Design Patterns

- **Adapter Pattern**: `BasePerpAdapter` base class with `create_adapter()` factory in `src/adapters/factory.py`
- **Event-Driven MM**: Price updates trigger order actions; `EventDeduplicator` prevents duplicate fills
- **Account Pool Architecture**: Accounts managed separately from strategies; strategies reference accounts by ID
- **WebSocket Broadcasting**: Real-time updates pushed to frontend via `/ws` endpoint

## Configuration

### Environment Variables (.env)
```
EXCHANGE_NAME=standx
STANDX_API_TOKEN=...
STANDX_ED25519_PRIVATE_KEY=...
HEDGE_TARGET=standx_hedge|grvt|none
STANDX_HEDGE_*=...              # Secondary account credentials
STANDX_HEDGE_PROXY_*=...        # Proxy for Sybil prevention
```

### Multi-Account Config (config/accounts.yaml)
Two sections: `accounts` (pool of credentials with optional proxies) and `strategies` (pairs accounts for main/hedge roles).

## API Endpoints

- `GET/POST /api/config/*` - Exchange configuration
- `GET/POST /api/mm/*` - Market maker control and status
- `GET/POST /api/accounts/*` - Account pool CRUD
- `GET/POST /api/strategies/*` - Strategy CRUD and control
- `WS /ws` - Real-time streaming (prices, orders, fills, PnL)

## Language

The UI and user-facing text use Traditional Chinese (繁體中文). Code comments and documentation may be in English or Chinese.
