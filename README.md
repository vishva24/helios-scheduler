# Helios — Distributed Compute Scheduler

A full-stack prototype of a **pull-based GPU task scheduler** designed for decentralized AI inference networks. Built to explore the architecture challenges of coordinating distributed compute nodes for LLM workloads.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              Live Dashboard (Frontend)               │
│   Real-time node cards, task log, queue viz,        │
│   WebSocket-powered push updates                     │
└───────────────────────┬─────────────────────────────┘
                        │ WebSocket (ws://localhost:8000/ws)
                        │ REST (node actions)
┌───────────────────────▼─────────────────────────────┐
│           FastAPI Scheduler (Backend)                │
│                                                      │
│  /nodes/register   — GPU node joins the network      │
│  /nodes/pull       — node requests a task (pull)     │
│  /nodes/heartbeat  — liveness ping every 5s          │
│  /tasks/submit     — client submits an AI task       │
│  /ws               — WebSocket broadcast endpoint    │
└──────────┬────────────────────────┬─────────────────┘
           │ threading              │ asyncio
┌──────────▼──────────┐  ┌─────────▼─────────────────┐
│  Execution Engine   │  │  Watchdog Thread           │
│  Simulated LLM      │  │  Checks heartbeats every   │
│  inference per task │  │  3s, marks nodes offline,  │
│  with random        │  │  re-queues orphaned tasks  │
│  failover (10%)     │  └────────────────────────────┘
└─────────────────────┘
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Pull-based model** | Nodes request tasks rather than being pushed to — reduces bottlenecks, scales naturally with variable node availability |
| **Stateless tasks** | Any node can pick up a dropped task — no data loss on node failure |
| **Economic incentives** | Nodes earn BSAI rewards on completion; green energy nodes earn 30% more — outsources reliability enforcement to the protocol |
| **Decoupled scheduler** | Separate coordination layer from execution agent — clean separation of concerns, independently scalable |
| **WebSocket push** | Backend broadcasts state to all connected dashboards instantly on every change — no polling overhead |
| **Heartbeat watchdog** | Nodes ping every 5s; watchdog auto-marks offline after 10s timeout and re-queues orphaned tasks |

---

## Features

- **Pull-based task marketplace** — nodes request work, scheduler matches based on VRAM constraints
- **Priority queue** — realtime tasks jump ahead of batch tasks automatically
- **Constraint-based allocation** — tasks matched to nodes by minimum VRAM requirement
- **Stateless failover** — dropped tasks auto-reassigned, up to 3 retries
- **Node heartbeat + watchdog** — automatic offline detection and task recovery
- **Economic reward layer** — BSAI rewards per completed task, green energy bonus
- **WebSocket live dashboard** — real-time push updates, auto-reconnect on disconnect

---

## Simulated Task Types

The scheduler supports five task categories: `text-generation`, `summarization`, `reranking`, `embedding`, and `classification`. Each has configurable VRAM requirements and simulated latency values used for demonstration purposes — these are not claims about real model performance, which varies by model size, quantization, and hardware.

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/helios-scheduler.git
cd helios-scheduler

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the backend
cd backend
uvicorn main:app --reload --port 8000

# 4. Open the dashboard
# Open frontend/index.html in your browser
```

---

## Project Structure

```
helios-scheduler/
├── backend/
│   └── main.py          # FastAPI scheduler, WebSocket, watchdog
├── frontend/
│   └── index.html       # Live dashboard (vanilla HTML/CSS/JS)
├── requirements.txt
└── README.md
```

> **To run:** start `backend/main.py` with uvicorn, then open `frontend/index.html` directly in your browser.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Real-time | WebSocket (native FastAPI) |
| Concurrency | Python threading + asyncio |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Simulation | Mock LLM inference (swap for real vLLM workers) |

---

## Roadmap

- [ ] WebSocket-based node clients (replace REST heartbeat)
- [ ] Persistent task store (SQLite / PostgreSQL)
- [ ] Node reliability scoring — affects task assignment priority
- [ ] Real vLLM worker integration
- [ ] Docker Compose for multi-node local testing

---

## Why This Project

Modern decentralized AI networks face a core scheduling problem: how do you reliably coordinate GPU compute across untrusted, heterogeneous nodes while maintaining fault tolerance and economic fairness?

This prototype explores the scheduler and inference coordination layer of that problem — specifically the pull-based task marketplace, constraint-aware allocation, stateless failover, and incentive design. The execution engine is simulated but the architecture is designed to be swapped with real vLLM workers.
