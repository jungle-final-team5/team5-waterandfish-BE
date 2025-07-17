#!/usr/bin/env python3

import sys
import json
import subprocess
import os
import logging
from pathlib import Path

def setup_logging(port: int):
    """로깅 설정"""
    log_dir = Path("/home/ubuntu/team5-waterandfish-BE/logs")
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / f"websocket_wrapper_{port}.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def get_model_for_port(port: int) -> str:
    """포트에 해당하는 모델 정보 조회"""
    config_path = "/home/ubuntu/team5-waterandfish-BE/config/websocket_servers.json"
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        for server in config['servers']:
            if server['port'] == port and server['enabled']:
                return server['model_info']
        
        raise ValueError(f"No model configured for port {port}")
    
    except Exception as e:
        raise RuntimeError(f"Error reading configuration: {e}")

def run_websocket_server(port: int, model_info: str, logger):
    """웹소켓 서버 실행"""
    logger.info(f"Starting WebSocket server on port {port} with model {model_info}")
    
    # 작업 디렉터리 설정
    work_dir = "/home/ubuntu/team5-waterandfish-BE"
    os.chdir(work_dir)
    
    # 가상환경 Python 경로
    python_path = "/home/ubuntu/team5-waterandfish-BE/venv/bin/python3"
    script_path = "/home/ubuntu/team5-waterandfish-BE/src/services/sign_classifier_websocket_server.py"
    
    # 실행 명령어
    cmd = [
        python_path,
        script_path,
        "--port", str(port),
        "--env", model_info,
        "--log-level", "INFO",
        # "--frame-skip", "3",
        "--prediction-interval", "10",
        # "--max-frame-width", "640"
    ]
    
    logger.info(f"Executing command: {' '.join(cmd)}")
    
    # 환경 변수 설정
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    
    # 프로세스 실행
    try:
        process = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            check=True
        )
        logger.info(f"WebSocket server on port {port} terminated normally")
        return process.returncode
        
    except subprocess.CalledProcessError as e:
        logger.error(f"WebSocket server on port {port} failed with return code {e.returncode}")
        return e.returncode
    except Exception as e:
        logger.error(f"Unexpected error running WebSocket server on port {port}: {e}")
        return 1

def main():
    if len(sys.argv) != 2:
        print("Usage: websocket_server_wrapper.py <port>")
        sys.exit(1)
    
    try:
        port = int(sys.argv[1])
    except ValueError:
        print("Error: Port must be an integer")
        sys.exit(1)
    
    # 로깅 설정
    logger = setup_logging(port)
    
    try:
        # 모델 정보 조회
        model_info = get_model_for_port(port)
        logger.info(f"Found model configuration: {model_info}")
        
        # 서버 실행
        exit_code = run_websocket_server(port, model_info, logger)
        sys.exit(exit_code)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
