# WebSocket 서비스 자동 관리 가이드

## 개요
이 시스템은 systemd 서비스 템플릿을 사용하여 9001-9100 포트에서 웹소켓 서버를 자동으로 관리합니다.

## 주요 기능
- **자동 재시작**: 서비스 충돌 시 자동 복구
- **동적 모델 배치**: S3에서 모델을 자동으로 할당
- **배치 시작**: 시스템 부하를 방지하기 위한 단계별 시작
- **모니터링**: 실시간 상태 확인

## 사용 방법

### 1. 기본 설정
```bash
# 서버 설정 생성
cd /home/ubuntu/team5-waterandfish-BE
python3 scripts/generate_server_config.py

# systemd 서비스 설치
python3 scripts/manage_websocket_services.py install
```

### 2. 서비스 관리

#### 모든 서비스 배포
```bash
./scripts/deploy_all_websocket_services.sh
```

#### 특정 포트 범위 관리
```bash
# 포트 9001-9010 활성화
python3 scripts/manage_websocket_services.py enable --start-port 9001 --end-port 9010

# 포트 9001-9010 시작
python3 scripts/manage_websocket_services.py start --start-port 9001 --end-port 9010

# 포트 9001-9010 상태 확인
python3 scripts/manage_websocket_services.py status --start-port 9001 --end-port 9010

# 포트 9001-9010 중지
python3 scripts/manage_websocket_services.py stop --start-port 9001 --end-port 9010
```

#### 특정 포트 관리
```bash
# 특정 포트들만 관리
python3 scripts/manage_websocket_services.py start --ports 9001 9005 9010
python3 scripts/manage_websocket_services.py status --ports 9001 9005 9010
```

### 3. 모니터링
```bash
# 전체 상태 모니터링
./scripts/monitor_websocket_services.sh

# systemd 로그 확인
sudo journalctl -u websocket-server@9001 -f

# 서비스 상태 확인
sudo systemctl status websocket-server@9001
```

### 4. 문제 해결

#### 서비스 재시작
```bash
# 특정 서비스 재시작
sudo systemctl restart websocket-server@9001

# 여러 서비스 재시작
python3 scripts/manage_websocket_services.py restart --start-port 9001 --end-port 9005
```

#### 로그 확인
```bash
# 래퍼 스크립트 로그
tail -f logs/websocket_wrapper_9001.log

# systemd 로그
sudo journalctl -u websocket-server@9001 --since "1 hour ago"
```

#### 포트 정리
```bash
# 모든 웹소켓 포트 정리
./scripts/cleanup_websocket_ports.sh
```

## 설정 파일

### 서버 설정 (config/websocket_servers.json)
```json
{
  "servers": [
    {
      "port": 9001,
      "model_info": "model-info-20250704_022235.json",
      "enabled": true
    }
  ]
}
```

### systemd 서비스 템플릿 (websocket-server@.service)
- 위치: `/etc/systemd/system/websocket-server@.service`
- 자동 재시작: `Restart=always`
- 재시작 간격: `RestartSec=10`

## 장점
1. **자동 복구**: 서비스 충돌 시 자동 재시작
2. **확장성**: 최대 99개 포트 지원
3. **모니터링**: 실시간 상태 확인
4. **배치 관리**: 시스템 부하 최소화
5. **로그 관리**: 중앙화된 로그 시스템

## 주의사항
- 서비스 시작 시 시스템 리소스 사용량 모니터링 필요
- 많은 수의 서비스 동시 시작 시 시스템 부하 주의
- 정기적인 로그 파일 정리 권장
