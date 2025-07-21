import subprocess
import asyncio
import os
import threading
import time
import json
from typing import Dict, Optional
import sys
from ..core.config import settings
from .s3_utils import s3_utils

ppath = sys.executable
class ModelServerManager:
    
    def __init__(self):
        self.MODEL_PORT_BASE = 9001
        self.running_servers: Dict[str, int] = {}  # {model_id: port}
        self.server_processes: Dict[str, subprocess.Popen] = {}  # {model_id: process}
        self.log_threads: Dict[str, threading.Thread] = {}  # {model_id: thread}
        self.count = 0

    async def start_model_server(self, model_id: str, model_data_url: str, port: int = None) -> str:
        """모델 서버를 시작하고 웹소켓 URL을 반환. port가 주어지면 해당 포트 사용"""

        if model_id not in self.running_servers:
            # 외부에서 포트가 주어지면 그대로 사용, 아니면 기존 방식대로 할당
            if port is None:
                port = self.MODEL_PORT_BASE + (self.count % 100)
                self.count = ((self.count + 1) % 100)
            # 모델 서버 프로세스 시작
            env = os.environ.copy()
            env["MODEL_DATA_URL"] = model_data_url
            env["PYTHONUNBUFFERED"] = "1"  # Python 출력 버퍼링 비활성화

            script_path = os.path.join(os.path.dirname(__file__), "sign_classifier_websocket_server.py")
            # Set the working directory to the parent of the services directory
            working_dir = os.path.dirname(os.path.dirname(__file__))
            process = subprocess.Popen([
                ppath, "-u", script_path,
                "--port", str(port),
                "--env", model_data_url,
                "--log-level", "OFF",
                # "--host", "0.0.0.0", #외부에서 접근 가능하게 바인딩 해야함
                # "--debug-video",
                # "--accuracy-mode",
                "--profile", # 프로파일링 모드 활성화
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

            # 로그 처리 스레드 시작
            log_thread = threading.Thread(
                target=self._handle_logs_thread,
                args=(model_id, process),
                daemon=True
            )
            log_thread.start()
            self.log_threads[model_id] = log_thread

            print(f"Started model server for {model_id} on port {port}")

            # 서버가 시작될 때까지 잠시 대기
            await asyncio.sleep(2)
        else:
            port = self.running_servers[model_id]
        MODEL_SERVER_HOST = settings.MODEL_SERVER_HOST

        if MODEL_SERVER_HOST == "localhost":
            return f"ws://localhost:{port}"
        else:
            return f"wss://{MODEL_SERVER_HOST}/ws/{port}/ws"
    
    def stop_model_server(self, model_id: str) -> bool:
        """모델 서버를 중지 (높은 우선순위)"""
        # 종료 작업은 우선순위가 높음 - shutdown_lock을 먼저 획득
        from . import ml_service
        with ml_service.shutdown_lock:
            with ml_service.models_lock:
                ml_service.shutting_down_models.add(model_id)
                print(f"[PRIORITY] Starting shutdown for {model_id}")
        
        if model_id in self.running_servers:
            # 프로세스 종료
            if model_id in self.server_processes:
                process = self.server_processes[model_id]
                process.terminate()
                try:
                    process.wait(timeout=5)  # 5초 대기
                except subprocess.TimeoutExpired:
                    process.kill()  # 강제 종료
                del self.server_processes[model_id]
            
            # 로그 스레드 정리
            if model_id in self.log_threads:
                del self.log_threads[model_id]
            
            del self.running_servers[model_id]
            print(f"Stopped model server for {model_id}")
            
            # 종료 완료 후 정리 (shutdown_lock 유지하여 우선순위 보장)
            with ml_service.models_lock:
                ml_service.shutting_down_models.discard(model_id)
                model_server_manager.running_servers.pop(model_id, None)
            
            return True
        else:
            # 서버가 없어도 shutting_down_models에서 제거
            with ml_service.models_lock:
                ml_service.shutting_down_models.discard(model_id)
        return False
    
    def get_server_url(self, model_id: str) -> Optional[str]:
        """실행 중인 모델 서버의 URL 반환"""
        if model_id in self.running_servers:
            port = self.running_servers[model_id]
            return f"ws://0.0.0.0:{port}/ws"
        return None
    
    def _handle_logs_thread(self, model_id: str, process: subprocess.Popen):
        """스레드에서 실시간으로 프로세스 로그를 처리"""
        try:
            print(f"[{model_id}] Log monitoring started")
            
            while True:
                # 프로세스가 종료되었는지 확인
                if process.poll() is not None:
                    # 프로세스 종료 후 남은 출력 모두 읽기
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.splitlines():
                            if line.strip():
                                print(f"[{model_id}] {line}")
                    break
                
                # 한 줄씩 읽기
                try:
                    line = process.stdout.readline()
                    if line:
                        print(f"[{model_id}] {line.rstrip()}")
                    else:
                        # 출력이 없으면 잠시 대기
                        time.sleep(0.01)
                except Exception as read_error:
                    print(f"[{model_id}] Error reading line: {read_error}")
                    break
                        
        except Exception as e:
            print(f"Error handling logs for {model_id}: {e}")
        finally:
            print(f"[{model_id}] Log monitoring stopped")
    
    def get_server_logs(self, model_id: str) -> Optional[str]:
        """모델 서버의 로그 반환"""
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
