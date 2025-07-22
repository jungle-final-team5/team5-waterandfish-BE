import os
import subprocess
import threading
import queue
import asyncio
# model_server_manager.running_servers: model_id(str) -> ws_url(str)
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from ..core.config import settings
from .model_server_manager import ModelServerManager, model_server_manager
from ..db.session import get_db
from bson import ObjectId
from collections import defaultdict
from bson import ObjectId
import re

# 우선순위 락 구현 (PriorityLock)
class PriorityLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._waiters = queue.PriorityQueue()
        self._cond = threading.Condition()

    def acquire(self, priority=0):
        with self._cond:
            self._waiters.put(priority)
            while self._waiters.queue[0] != priority or not self._lock.acquire(blocking=False):
                self._cond.wait()
            self._waiters.get()
            self._cond.notify_all()

    def release(self):
        with self._cond:
            self._lock.release()
            self._cond.notify_all()

# 동시성 제어를 위한 우선순위 락들 (종료 작업이 더 높은 우선순위)
models_lock = PriorityLock()
shutdown_lock = PriorityLock()  # 종료 작업 전용 락 (priority=0: 높음, priority=1: 낮음)

# 사용 예시:
# shutdown_lock.acquire(priority=0)  # 종료 작업(높은 우선순위)
# models_lock.acquire(priority=1)    # 일반 작업(낮은 우선순위)
# ...
# models_lock.release()
# shutdown_lock.release()
# 종료 중인 모델들을 추적
shutting_down_models = set()

import signal
import heapq


# 포트 풀 및 락 (9001~9100, 작은 번호부터 할당)
PORT_RANGE_START = 9001
PORT_RANGE_END = 9100
available_ports = list(range(PORT_RANGE_START, PORT_RANGE_END + 1))
heapq.heapify(available_ports)
ports_lock = threading.Lock()

# 모델별 할당된 포트 추적용 (model_id -> port)
model_ports = {}


# 포트 할당 함수 (작은 번호부터 할당)
def allocate_port(model_id):
    with ports_lock:
        if model_id in model_ports:
            return model_ports[model_id]
        if not available_ports:
            raise Exception("No available ports in pool")
        port = heapq.heappop(available_ports)
        model_ports[model_id] = port
        return port

# 포트 회수 함수 (작은 번호부터 할당 유지)
def release_port(model_id):
    with ports_lock:
        port = model_ports.pop(model_id, None)
        if port is not None:
            heapq.heappush(available_ports, port)
def is_server_alive_by_pid(pid):
    try:
        if pid is None:
            return False
        # Windows
        if os.name == 'nt':
            import psutil
            return psutil.pid_exists(pid)
        # Unix
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False

    # 관리 객체에서 죽은 서버 정보 정리
def cleanup_dead_servers():
    # 종료 작업: 우선순위 0 (가장 높음)
    shutdown_lock.acquire(priority=0)
    try:
        models_lock.acquire(priority=1)
        try:
            dead_ids = []
            for model_id, process in list(model_server_manager.server_processes.items()):
                # 종료 중인 모델은 정리 대상에서 제외 (종료 작업이 처리)
                if model_id in shutting_down_models:
                    continue
                pid = process.pid if process else None
                if not is_server_alive_by_pid(pid):
                    dead_ids.append(model_id)
            for model_id in dead_ids:
                print(f"[CLEANUP] Removing dead server info for {model_id}")
                model_server_manager.running_servers.pop(model_id, None)
                model_server_manager.server_processes.pop(model_id, None)
                # 포트 회수
                release_port(model_id)
        finally:
            models_lock.release()
    finally:
        shutdown_lock.release()

async def deploy_model(chapter_id, db=None):
    """챕터에 해당하는 모델 서버를 배포"""
    if db is None:
        # db가 없으면 새로 가져오기 (이상적으로는 의존성 주입 사용)
        db = await get_db().__anext__()
    
    # 챕터 정보 조회
    chapter = await db.Chapters.find_one({"_id": chapter_id})
    if not chapter:
        raise Exception(f"Chapter with id {chapter_id} not found")
    
    # 해당 챕터의 레슨들 조회
    lessons = await db.Lessons.find({"_id": {"$in": chapter["lesson_ids"]}}, {"embedding": 0}).to_list(length=None)
    
    # 모델 데이터 URL이 있는 레슨 확인
    model_data_urls = [lesson.get("model_data_url") for lesson in lessons if lesson.get("model_data_url")]
    cleanup_dead_servers()

    ws_urls = []

    for model_data_url in model_data_urls:
        model_id = model_data_url

        # 1단계: 종료 중인지 먼저 확인 (우선순위 존중)
        shutdown_in_progress = False
        shutdown_lock.acquire(priority=1)  # 생성 작업은 낮은 우선순위
        try:
            models_lock.acquire(priority=1)
            try:
                if model_id in shutting_down_models:
                    print(f"Model server {model_id} is shutting down, will start new one")
                    shutdown_in_progress = True
            finally:
                models_lock.release()
        finally:
            shutdown_lock.release()

        # 2단계: 종료 중이 아니라면 일반적인 상태 확인
        if not shutdown_in_progress:
            models_lock.acquire(priority=1)
            try:
                # 직접 프로세스 상태 확인
                process = model_server_manager.server_processes.get(model_id)
                pid = process.pid if process else None
                server_alive = False

                if model_id in model_server_manager.running_servers:
                    try:
                        server_alive = is_server_alive_by_pid(pid)
                    except Exception:
                        server_alive = False

                    if server_alive:
                        print(f"Model server already running for {model_id}")
                        ws_urls.append(model_server_manager.running_servers[model_id])
                        continue
                    else:
                        print(f"Model server for {model_id} is not alive. Restarting...")
                        model_server_manager.running_servers.pop(model_id, None)
                        model_server_manager.server_processes.pop(model_id, None)
            finally:
                models_lock.release()

        # 3단계: 서버 시작 전에 다시 한번 종료 상태 확인
        shutdown_lock.acquire(priority=1)
        try:
            models_lock.acquire(priority=1)
            try:
                if model_id in shutting_down_models:
                    print(f"Model server {model_id} shutdown detected during startup, skipping...")
                    continue
            finally:
                models_lock.release()
        finally:
            shutdown_lock.release()

        # 4단계: 포트 할당 및 모델 서버 시작 (락 외부에서 실행)
        port = allocate_port(model_id)
        try:
            ws_url = await model_server_manager.start_model_server(model_id, model_data_url, port=port)
        except Exception as e:
            print(f"Failed to start model server for {model_id}: {str(e)}")
            release_port(model_id)
            raise Exception(f"Failed to start model server for {model_id}: {str(e)}")

        # 5단계: 결과 저장 (종료 작업과 충돌하지 않도록)
        models_lock.acquire(priority=1)
        try:
            # 시작 완료 후에도 종료되지 않았는지 확인
            if model_id not in shutting_down_models:
                ws_urls.append(ws_url)
                model_server_manager.running_servers[model_id] = ws_url
            else:
                print(f"Model server {model_id} was shut down during startup, not registering")
                release_port(model_id)
        finally:
            models_lock.release()
        print(f"model server deployed for chapter {chapter_id}: {ws_url}")
        print(f"현재 model_server_manager.running_servers: {dict(model_server_manager.running_servers)}")
        print(f"현재 model_server_manager.server_processes: {{k: v.pid if v else None for k, v in model_server_manager.server_processes.items()}}")
    
    lesson_mapper = defaultdict(str)
    for lesson in lessons:
        lesson_mapper[str(lesson["_id"])] = model_server_manager.running_servers[lesson["model_data_url"]]
    print('[ml_service]lesson_mapper', lesson_mapper)
    return ws_urls, lesson_mapper

# 단일 레슨 모델 서버 배포
async def deploy_lesson_model(lesson_id, db=None):
    cleanup_dead_servers()
    if db is None:
        db = await get_db().__anext__()
    obj_id = ObjectId(lesson_id)
    lesson = await db.Lessons.find_one({"_id": obj_id})
    if not lesson:
        raise Exception(f"Lesson with id {lesson_id} not found")
    model_data_url = lesson.get("model_data_url")
    if not model_data_url:
        raise Exception(f"Lesson {lesson_id} does not have a model_data_url")
    model_id = model_data_url
    
    # 락으로 동시성 제어 (생성 작업: 낮은 우선순위)
    models_lock.acquire(priority=1)
    try:
        if model_id in model_server_manager.running_servers:
            # 서버가 실제로 살아있는지 확인
            process = model_server_manager.server_processes.get(model_id)
            pid = process.pid if process else None
            if is_server_alive_by_pid(pid):
                ws_url = model_server_manager.running_servers[model_id]
            else:
                # 죽은 서버 정보 정리
                print(f"Model server for {model_id} is not alive. Restarting...")
                model_server_manager.running_servers.pop(model_id, None)
                model_server_manager.server_processes.pop(model_id, None)
                ws_url = None
        else:
            ws_url = None
    finally:
        models_lock.release()

    # 서버가 없으면 새로 시작 (락 외부에서 실행)
    if ws_url is None:
        port = allocate_port(model_id)
        try:
            ws_url = await model_server_manager.start_model_server(model_id, model_data_url, port=port)
        except Exception as e:
            release_port(model_id)
            raise
        models_lock.acquire(priority=1)
        try:
            model_server_manager.running_servers[model_id] = ws_url
        finally:
            models_lock.release()
    return ws_url