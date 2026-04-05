from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import time
import random
import threading
import asyncio
import json

app = FastAPI(title="Helios Compute Scheduler")

HEARTBEAT_TIMEOUT = 10   # seconds before node is considered offline
WATCHDOG_INTERVAL = 3    # how often watchdog checks node health

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory state ──────────────────────────────────────────────
nodes: dict = {}       # node_id -> node info
tasks: dict = {}       # task_id -> task info
task_queue: list = []  # ordered list of pending task_ids
lock = threading.Lock()

# ── WebSocket manager ────────────────────────────────────────────
ws_clients: set = set()
ws_loop: asyncio.AbstractEventLoop = None

def get_full_state():
    """Snapshot of everything the frontend needs."""
    total = len(tasks)
    completed = sum(1 for t in tasks.values() if t["status"] == "completed")
    failed    = sum(1 for t in tasks.values() if t["status"] == "failed")
    pending   = sum(1 for t in tasks.values() if t["status"] == "pending")
    running   = sum(1 for t in tasks.values() if t["status"] == "running")
    return {
        "type": "state",
        "stats": {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "running": running,
            "active_nodes": sum(1 for n in nodes.values() if n["status"] != "offline"),
            "total_nodes": len(nodes),
        },
        "nodes": list(nodes.values()),
        "tasks": list(tasks.values()),
        "queue": {
            "queue_length": len(task_queue),
            "pending_ids": task_queue[:10],
        },
        "server_time": time.time(),
    }

def broadcast(event: dict = None):
    """Push full state (or a specific event) to all WS clients from any thread."""
    if not ws_loop or not ws_clients:
        return
    payload = json.dumps(event or get_full_state())
    async def _send():
        dead = set()
        for ws in list(ws_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        ws_clients.difference_update(dead)
    asyncio.run_coroutine_threadsafe(_send(), ws_loop)

TASK_TYPES = ["text-generation", "embedding", "reranking", "summarization", "classification"]
MODEL_REQUIREMENTS = {
    "text-generation": {"min_vram": 8, "avg_latency": 4.0},
    "embedding":       {"min_vram": 2, "avg_latency": 0.8},
    "reranking":       {"min_vram": 2, "avg_latency": 1.2},
    "summarization":   {"min_vram": 6, "avg_latency": 3.0},
    "classification":  {"min_vram": 1, "avg_latency": 0.5},
}

# ── Models ───────────────────────────────────────────────────────
class NodeRegister(BaseModel):
    name: str
    vram_gb: float
    green_energy: bool = False

class TaskSubmit(BaseModel):
    task_type: str
    priority: str = "batch"   # "realtime" or "batch"
    budget: float = 1.0
    payload: Optional[str] = None

class NodePull(BaseModel):
    node_id: str

# ── Helpers ──────────────────────────────────────────────────────
def pick_task_for_node(node: dict) -> Optional[str]:
    """Find the best task for this node from the queue."""
    with lock:
        # Prefer realtime tasks first
        candidates = [
            tid for tid in task_queue
            if tasks[tid]["status"] == "pending"
            and MODEL_REQUIREMENTS[tasks[tid]["task_type"]]["min_vram"] <= node["vram_gb"]
        ]
        if not candidates:
            return None
        realtime = [t for t in candidates if tasks[t]["priority"] == "realtime"]
        chosen = realtime[0] if realtime else candidates[0]
        tasks[chosen]["status"] = "running"
        tasks[chosen]["assigned_node"] = node["node_id"]
        tasks[chosen]["started_at"] = time.time()
        task_queue.remove(chosen)
        return chosen

def simulate_execution(task_id: str, node_id: str):
    """Simulate async task execution with random success/failure."""
    task = tasks.get(task_id)
    node = nodes.get(node_id)
    if not task or not node:
        return

    latency = MODEL_REQUIREMENTS[task["task_type"]]["avg_latency"]
    jitter = random.uniform(-0.3, 0.5)
    time.sleep(max(0.5, latency + jitter))

    # 10% chance node drops mid-task (triggers failover)
    if random.random() < 0.10:
        with lock:
            task["status"] = "failed"
            task["assigned_node"] = None
            task["retries"] = task.get("retries", 0) + 1
            node["status"] = "offline"
            node["current_task"] = None
            if task["retries"] < 3:
                task["status"] = "pending"
                task_queue.insert(0, task_id)
        broadcast()
        return

    with lock:
        task["status"] = "completed"
        task["completed_at"] = time.time()
        task["result"] = f"[mock] {task['task_type']} output for: {task.get('payload','<no payload>')[:40]}"
        node["status"] = "idle"
        node["current_task"] = None
        node["tasks_completed"] = node.get("tasks_completed", 0) + 1
        reward = round(task["budget"] * (1.3 if node["green_energy"] else 1.0), 4)
        node["bsai_earned"] = round(node.get("bsai_earned", 0) + reward, 4)
    broadcast()

# ── Routes ───────────────────────────────────────────────────────
@app.post("/nodes/register")
def register_node(body: NodeRegister):
    nid = str(uuid.uuid4())[:8]
    nodes[nid] = {
        "node_id": nid,
        "name": body.name,
        "vram_gb": body.vram_gb,
        "green_energy": body.green_energy,
        "status": "idle",
        "current_task": None,
        "tasks_completed": 0,
        "bsai_earned": 0.0,
        "registered_at": time.time(),
        "last_seen": time.time(),
    }
    result = {"node_id": nid, "message": f"Node '{body.name}' registered."}
    broadcast()
    return result

@app.post("/tasks/submit")
def submit_task(body: TaskSubmit):
    if body.task_type not in TASK_TYPES:
        raise HTTPException(400, f"Unknown task type. Choose from {TASK_TYPES}")
    tid = str(uuid.uuid4())[:8]
    tasks[tid] = {
        "task_id": tid,
        "task_type": body.task_type,
        "priority": body.priority,
        "budget": body.budget,
        "payload": body.payload or "sample input",
        "status": "pending",
        "assigned_node": None,
        "retries": 0,
        "submitted_at": time.time(),
        "completed_at": None,
        "result": None,
    }
    with lock:
        if body.priority == "realtime":
            task_queue.insert(0, tid)
        else:
            task_queue.append(tid)
    result = {"task_id": tid, "message": "Task queued."}
    broadcast()
    return result

@app.post("/nodes/pull")
def pull_task(body: NodePull):
    node = nodes.get(body.node_id)
    if not node:
        raise HTTPException(404, "Node not found.")
    if node["status"] == "offline":
        raise HTTPException(403, "Node is offline.")
    if node["status"] == "busy":
        return {"message": "Node is busy.", "task": None}

    task_id = pick_task_for_node(node)
    if not task_id:
        return {"message": "No suitable tasks available.", "task": None}

    node["status"] = "busy"
    node["current_task"] = task_id

    thread = threading.Thread(target=simulate_execution, args=(task_id, body.node_id), daemon=True)
    thread.start()

    result = {"task_id": task_id, "task": tasks[task_id]}
    broadcast()
    return result

@app.get("/nodes")
def list_nodes():
    return list(nodes.values())

@app.get("/tasks")
def list_tasks():
    return list(tasks.values())

@app.get("/queue")
def get_queue():
    return {"queue_length": len(task_queue), "pending_ids": task_queue[:10]}

@app.get("/stats")
def get_stats():
    total = len(tasks)
    completed = sum(1 for t in tasks.values() if t["status"] == "completed")
    failed = sum(1 for t in tasks.values() if t["status"] == "failed")
    pending = sum(1 for t in tasks.values() if t["status"] == "pending")
    running = sum(1 for t in tasks.values() if t["status"] == "running")
    return {
        "total_tasks": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "running": running,
        "active_nodes": sum(1 for n in nodes.values() if n["status"] != "offline"),
        "total_nodes": len(nodes),
    }

@app.delete("/nodes/{node_id}/reset")
def reset_node(node_id: str):
    if node_id not in nodes:
        raise HTTPException(404, "Node not found.")
    nodes[node_id]["status"] = "idle"
    nodes[node_id]["last_seen"] = time.time()
    return {"message": "Node reset to idle."}

@app.post("/nodes/heartbeat")
def heartbeat(body: NodePull):
    node = nodes.get(body.node_id)
    if not node:
        raise HTTPException(404, "Node not found.")
    changed = False
    with lock:
        node["last_seen"] = time.time()
        if node["status"] == "offline":
            node["status"] = "idle"
            changed = True
    if changed:
        broadcast()
    return {"status": "ok", "server_time": time.time()}

# ── WebSocket endpoint ───────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    # Send full state immediately on connect
    await websocket.send_text(json.dumps(get_full_state()))
    try:
        while True:
            # Keep connection alive — client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)

# ── Watchdog ─────────────────────────────────────────────────────
def watchdog():
    """Background thread — marks nodes offline if heartbeat times out."""
    while True:
        time.sleep(WATCHDOG_INTERVAL)
        now = time.time()
        changed = False
        with lock:
            for node in nodes.values():
                if node["status"] == "offline":
                    continue
                age = now - node.get("last_seen", now)
                if age > HEARTBEAT_TIMEOUT:
                    node["status"] = "offline"
                    changed = True
                    tid = node.get("current_task")
                    if tid and tid in tasks:
                        task = tasks[tid]
                        if task["status"] == "running":
                            task["retries"] = task.get("retries", 0) + 1
                            if task["retries"] < 3:
                                task["status"] = "pending"
                                task["assigned_node"] = None
                                task_queue.insert(0, tid)
                            else:
                                task["status"] = "failed"
                    node["current_task"] = None
        if changed:
            broadcast()

@app.on_event("startup")
async def startup():
    global ws_loop
    ws_loop = asyncio.get_event_loop()
    t = threading.Thread(target=watchdog, daemon=True)
    t.start()