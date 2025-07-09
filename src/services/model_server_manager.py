import subprocess
import asyncio
import os
import threading
import time
from typing import Dict, Optional

from ..core.config import settings

class ModelServerManager:
    def __init__(self):
        self.MODEL_PORT_BASE = 9000
        self.MAX_PORT = 9099
        self.running_servers: Dict[str, int] = {}  # {model_id: port}
        self.server_processes: Dict[str, subprocess.Popen] = {}  # {model_id: process}
        self.log_threads: Dict[str, threading.Thread] = {}  # {model_id: thread}

    def _find_free_port(self):
        used_ports = set(self.running_servers.values())
        for port in range(self.MODEL_PORT_BASE + 1, self.MAX_PORT + 1):
            if port not in used_ports:
                return port
        raise Exception("No free ports available")

    def _make_ws_url(self, port):
        MODEL_SERVER_HOST = settings.MODEL_SERVER_HOST
        if MODEL_SERVER_HOST == "localhost":
            return f"ws://0.0.0.0:{port}/ws"
        else:
            return f"wss://{MODEL_SERVER_HOST}/ws/{port}/ws"

    async def get_or_start_server(self, model_id: str, model_data_url: str, use_webrtc: bool = False) -> str:
        # Check if already running and process is alive
        if model_id in self.running_servers:
            process = self.server_processes.get(model_id)
            if process and process.poll() is None:
                port = self.running_servers[model_id]
                return self._make_ws_url(port)
            else:
                # Clean up dead process
                if model_id in self.server_processes:
                    del self.server_processes[model_id]
                if model_id in self.running_servers:
                    del self.running_servers[model_id]
                if model_id in self.log_threads:
                    del self.log_threads[model_id]
        # Find a truly free port
        port = self._find_free_port()
        # Start new process
        env = os.environ.copy()
        env["MODEL_DATA_URL"] = model_data_url
        env["PYTHONUNBUFFERED"] = "1"
        script_path = os.path.join(os.path.dirname(__file__), "sign_classifier_websocket_server.py")
        working_dir = os.path.dirname(os.path.dirname(__file__))
        process = subprocess.Popen([
            "python", "-u", script_path,
            "--port", str(port),
            "--env", model_data_url,
            "--log-level", "INFO",
            # "--host", "0.0.0.0",
            # "--debug-video",
            "--accuracy-mode",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=0,
        universal_newlines=True,
        cwd=working_dir)
        print(f"Model server process PID: {process.pid}")
        self.running_servers[model_id] = port
        self.server_processes[model_id] = process
        # Start log thread
        log_thread = threading.Thread(
            target=self._handle_logs_thread,
            args=(model_id, process),
            daemon=True
        )
        log_thread.start()
        self.log_threads[model_id] = log_thread
        print(f"Started WebSocket model server for {model_id} on port {port}")
        await asyncio.sleep(2)
        return self._make_ws_url(port)

    def stop_model_server(self, model_id: str) -> bool:
        if model_id in self.running_servers:
            if model_id in self.server_processes:
                process = self.server_processes[model_id]
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                del self.server_processes[model_id]
            if model_id in self.log_threads:
                del self.log_threads[model_id]
            del self.running_servers[model_id]
            print(f"Stopped model server for {model_id}")
            return True
        return False

    def get_server_url(self, model_id: str) -> Optional[str]:
        if model_id in self.running_servers:
            process = self.server_processes.get(model_id)
            if process and process.poll() is None:
                port = self.running_servers[model_id]
                return self._make_ws_url(port)
            else:
                # Clean up dead process
                if model_id in self.server_processes:
                    del self.server_processes[model_id]
                if model_id in self.running_servers:
                    del self.running_servers[model_id]
                if model_id in self.log_threads:
                    del self.log_threads[model_id]
        return None

    def _handle_logs_thread(self, model_id: str, process: subprocess.Popen):
        try:
            print(f"[{model_id}] Log monitoring started")
            while True:
                if process.poll() is not None:
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.splitlines():
                            if line.strip():
                                print(f"[{model_id}] {line}")
                    break
                try:
                    line = process.stdout.readline()
                    if line:
                        print(f"[{model_id}] {line.rstrip()}")
                    else:
                        time.sleep(0.01)
                except Exception as read_error:
                    print(f"[{model_id}] Error reading line: {read_error}")
                    break
        except Exception as e:
            print(f"Error handling logs for {model_id}: {e}")
        finally:
            print(f"[{model_id}] Log monitoring stopped")

    def get_server_logs(self, model_id: str) -> Optional[str]:
        if model_id in self.server_processes:
            process = self.server_processes[model_id]
            try:
                stdout, stderr = process.communicate(timeout=1)
                return f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            except subprocess.TimeoutExpired:
                return "Server is still running, logs not available"
        return None

# 전역 인스턴스
model_server_manager = ModelServerManager() 
