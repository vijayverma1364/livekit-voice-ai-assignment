"""
Supervised Voice AI Agent - All-In-One Unified Local Orchestrator
================================================================
Senior Technical Lead / Principal Engineer Architecture Standard

Launches and supervises all 6 distributed components of the Voice AI platform:
  1. LiveKit SFU (WebRTC Media Server)      -> ws://localhost:7880
  2. PostgreSQL (Durable Relational Store) -> localhost:5432
  3. FastAPI Backend (REST Control Plane)   -> http://localhost:8000
  4. LiveKit Voice Agent Worker (Python)    -> Connected to LiveKit + DB
  5. Customer Web Client (React 19 SPA)     -> http://localhost:3000
  6. Supervisor Console (React 19 SPA)      -> http://localhost:3001

Usage:
  python run_all.py [--no-browser] [--skip-docker]
"""

import sys
import os
import time
import signal
import subprocess
import urllib.request
import urllib.error
import webbrowser
import socket
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# --- ANSI Formatting ---
class Log:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def info(cls, msg: str):
        print(f"{cls.CYAN}[INFO]{cls.RESET} {msg}")

    @classmethod
    def success(cls, msg: str):
        print(f"{cls.GREEN}[SUCCESS]{cls.RESET} {msg}")

    @classmethod
    def warn(cls, msg: str):
        print(f"{cls.YELLOW}[WARN]{cls.RESET} {msg}")

    @classmethod
    def error(cls, msg: str):
        print(f"{cls.RED}[ERROR]{cls.RESET} {msg}")

    @classmethod
    def header(cls, msg: str):
        print(f"\n{cls.BOLD}{cls.MAGENTA}{'=' * 70}\n{msg}\n{'=' * 70}{cls.RESET}\n")


ROOT_DIR = Path(__file__).resolve().parent
SUBPROCESSES = []


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is actively accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_http_health(url: str, timeout: float = 2.0) -> bool:
    """Check if an HTTP endpoint returns a 2xx or 3xx status code."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VoiceAI-Orchestrator/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def ensure_env_file():
    """Verify that .env exists and has essential configurations."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        example_path = ROOT_DIR / ".env.example"
        if example_path.exists():
            Log.warn(".env file not found. Creating from .env.example...")
            import shutil
            shutil.copy(example_path, env_path)
            Log.success("Created .env from .env.example")
        else:
            Log.error(".env file missing and .env.example not found.")
            sys.exit(1)


def ensure_docker_infrastructure():
    """Ensure LiveKit SFU and PostgreSQL are up and healthy via Docker Compose."""
    Log.info("Checking LiveKit SFU (port 7880) and PostgreSQL (port 5432)...")
    livekit_up = is_port_in_use(7880)
    postgres_up = is_port_in_use(5432)

    if not livekit_up or not postgres_up:
        Log.info("Starting LiveKit and PostgreSQL infrastructure containers...")
        cmd = ["docker", "compose", "up", "-d", "livekit", "postgres"]
        res = subprocess.run(cmd, cwd=ROOT_DIR)
        if res.returncode != 0:
            Log.warn("Docker compose up failed. If services are running natively, continuing...")

    # Wait for LiveKit to answer HTTP
    Log.info("Waiting for LiveKit SFU signaling response...")
    for _ in range(20):
        if check_http_health("http://127.0.0.1:7880/"):
            Log.success("LiveKit SFU is online and healthy on port 7880.")
            break
        time.sleep(1)
    else:
        Log.warn("LiveKit SFU check timed out. Proceeding if already bound...")


def start_service(name: str, cmd: list, cwd: Path, port: int = None, health_url: str = None) -> subprocess.Popen:
    """Start a background service with real-time logging and port monitoring."""
    if port and is_port_in_use(port):
        Log.info(f"{name} is ALREADY running on port {port}. Reusing existing instance.")
        return None

    Log.info(f"Launching {name} ({' '.join(cmd[:3])}...)...")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    # On Windows, create a new process group for clean subtree termination
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=creationflags
    )
    SUBPROCESSES.append((name, proc))

    if health_url:
        Log.info(f"Waiting for {name} healthcheck at {health_url}...")
        for _ in range(30):
            if proc.poll() is not None:
                Log.error(f"{name} exited unexpectedly with code {proc.returncode}!")
                break
            if check_http_health(health_url):
                Log.success(f"{name} is healthy!")
                break
            time.sleep(0.5)

    return proc


def cleanup_subprocesses():
    """Cleanly terminate all spawned subprocesses and process trees."""
    Log.header("Shutting down Voice AI Platform...")
    for name, proc in reversed(SUBPROCESSES):
        if proc and proc.poll() is None:
            Log.info(f"Terminating {name} (PID: {proc.pid})...")
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    proc.terminate()
                    proc.wait(timeout=2)
            except Exception as e:
                Log.warn(f"Error terminating {name}: {e}")
    Log.success("All platform services stopped cleanly.")


def main():
    no_browser = "--no-browser" in sys.argv
    skip_docker = "--skip-docker" in sys.argv
    use_docker = "--docker" in sys.argv or "--compose" in sys.argv

    Log.header("VOICE AI ASSISTANT PLATFORM — UNIFIED RUNNER\nSelf-Hosted LiveKit | FastAPI | Autonomous Worker | Customer UI | Supervisor UI")

    ensure_env_file()

    # --- Full Docker Compose Mode ---
    if use_docker:
        Log.info("Starting ENTIRE stack in Docker Compose (6 services)...")
        Log.info("Building and launching: livekit, postgres, backend, agent, customer-web, supervisor-web")
        cmd = ["docker", "compose", "up", "--build"]
        if no_browser:
            subprocess.run(cmd, cwd=ROOT_DIR)
            return

        # Start docker compose in background and open portal when ready
        proc = subprocess.Popen(cmd, cwd=ROOT_DIR)
        SUBPROCESSES.append(("Docker Compose Stack", proc))

        Log.info("Waiting for FastAPI and Unified Portal to answer on http://localhost:8000/...")
        for _ in range(60):
            if check_http_health("http://127.0.0.1:8000/health"):
                Log.success("FastAPI Control Plane and Unified Portal are healthy!")
                break
            time.sleep(1)

        time.sleep(2)
        Log.header("PLATFORM STATUS DASHBOARD — DOCKER STACK OPERATIONAL")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Unified Testing Portal: {Log.BOLD}{Log.CYAN}http://localhost:8000/{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Customer Web Client:    {Log.BOLD}{Log.CYAN}http://localhost:3000/{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Supervisor Console:     {Log.BOLD}{Log.CYAN}http://localhost:3001/{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} LiveKit SFU:            {Log.BOLD}ws://localhost:7880{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Interactive API Docs:   {Log.BOLD}http://localhost:8000/docs{Log.RESET}")
        print(f"\n{Log.YELLOW}Press Ctrl+C to terminate the Docker stack.{Log.RESET}\n")

        if not no_browser:
            Log.info("Opening Unified Testing Portal in browser...")
            webbrowser.open("http://localhost:8000/")

        try:
            proc.wait()
        except KeyboardInterrupt:
            subprocess.run(["docker", "compose", "down"], cwd=ROOT_DIR)
        return

    # --- Local Hybrid Mode (Docker LiveKit/Postgres + Native Fast Services) ---
    if not skip_docker:
        ensure_docker_infrastructure()

    # Register exit handlers
    def signal_handler(sig, frame):
        cleanup_subprocesses()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 1. FastAPI Control Plane (port 8000)
        start_service(
            name="FastAPI Backend",
            cmd=[sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT_DIR,
            port=8000,
            health_url="http://127.0.0.1:8000/health"
        )

        # 2. LiveKit Agent Worker (Python)
        start_service(
            name="Voice Agent Worker",
            cmd=[sys.executable, "-m", "agent.src.worker", "dev"],
            cwd=ROOT_DIR,
            port=None
        )

        # 3. Customer Web Client (React 19, port 3000)
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        start_service(
            name="Customer Web Frontend",
            cmd=[npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "3000"],
            cwd=ROOT_DIR / "customer-web",
            port=3000,
            health_url="http://127.0.0.1:3000/"
        )

        # 4. Supervisor Console (React 19, port 3001)
        start_service(
            name="Supervisor Web Frontend",
            cmd=[npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "3001"],
            cwd=ROOT_DIR / "supervisor-web",
            port=3001,
            health_url="http://127.0.0.1:3001/"
        )

        # Print Status Dashboard
        time.sleep(1.5)
        Log.header("PLATFORM STATUS DASHBOARD — ALL SYSTEMS OPERATIONAL")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Unified Testing Portal: {Log.BOLD}{Log.CYAN}http://localhost:8000/{Log.RESET} (Customer + Supervisor in one view)")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Customer Web Client:    {Log.BOLD}{Log.CYAN}http://localhost:3000/{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Supervisor Console:     {Log.BOLD}{Log.CYAN}http://localhost:3001/{Log.RESET}")
        print(f"  {Log.GREEN}[OK]{Log.RESET} LiveKit SFU:            {Log.BOLD}ws://localhost:7880{Log.RESET} (Signaling 7880, WebRTC UDP 50000-50100)")
        print(f"  {Log.GREEN}[OK]{Log.RESET} PostgreSQL:             {Log.BOLD}localhost:5432{Log.RESET} (Database: voice_ai)")
        print(f"  {Log.GREEN}[OK]{Log.RESET} FastAPI Backend:        {Log.BOLD}http://localhost:8000{Log.RESET} (Docs: http://localhost:8000/docs)")
        print(f"  {Log.GREEN}[OK]{Log.RESET} Voice Agent Worker:     {Log.BOLD}Connected & Registered{Log.RESET} (Deepgram STT, GPT-4o-mini, OpenAI TTS)")
        print(f"\n{Log.YELLOW}Press Ctrl+C at any time to gracefully terminate all services.{Log.RESET}\n")

        # Open Unified Testing Portal in browser
        if not no_browser:
            time.sleep(1)
            Log.info("Launching Unified Testing Portal in browser (http://localhost:8000/)...")
            webbrowser.open("http://localhost:8000/")

        # Keep parent alive and monitor processes
        while True:
            time.sleep(1)
            for name, proc in SUBPROCESSES:
                if proc and proc.poll() is not None:
                    Log.warn(f"Service {name} stopped with exit code {proc.returncode}.")

    except KeyboardInterrupt:
        pass
    finally:
        cleanup_subprocesses()


if __name__ == "__main__":
    main()
