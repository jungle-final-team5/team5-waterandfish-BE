import asyncio
import json
import logging
import websockets
from typing import Dict, Set, Optional
from dataclasses import dataclass
from datetime import datetime
import cv2
import numpy as np
import mediapipe as mp
import tensorflow as tf
import base64
import io
from PIL import Image

logger = logging.getLogger(__name__)

@dataclass
class WebRTCClient:
    websocket: websockets.WebSocketServerProtocol
    client_id: str
    room_id: Optional[str] = None
    is_offerer: bool = False
    peer_id: Optional[str] = None

class WebRTCSignalingServer:
    def __init__(self, model_data_url: str, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Dict[str, WebRTCClient] = {}
        self.rooms: Dict[str, Set[str]] = {}
        
        # MediaPipe 및 모델 초기화
        self.mp_holistic = mp.solutions.holistic
        self.holistic = self.mp_holistic.Holistic(
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
            model_complexity=0
        )
        
        # 모델 로드
        self.model_info = self.load_model_info(model_data_url)
        self.model = tf.keras.models.load_model(self.model_info["model_path"])
        self.ACTIONS = self.model_info["labels"]
        self.MAX_SEQ_LENGTH = self.model_info["input_shape"][0]
        
        # 시퀀스 버퍼
        self.client_sequences = {}
        self.client_frame_counters = {}
        
        logger.info(f"WebRTC 시그널링 서버 초기화 완료: {host}:{port}")
    
    def load_model_info(self, model_data_url: str):
        """모델 정보 로드"""
        try:
            with open(model_data_url, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"모델 정보 로드 실패: {e}")
            raise
    
    def get_client_id(self, websocket: websockets.WebSocketServerProtocol) -> str:
        """클라이언트 ID 생성"""
        return f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    
    async def handle_client(self, websocket: websockets.WebSocketServerProtocol):
        """클라이언트 연결 처리"""
        client_id = self.get_client_id(websocket)
        client = WebRTCClient(websocket=websocket, client_id=client_id)
        self.clients[client_id] = client
        
        logger.info(f"클라이언트 연결: {client_id}")
        
        try:
            async for message in websocket:
                await self.handle_message(client, message)
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"클라이언트 연결 종료: {client_id}")
        except Exception as e:
            logger.error(f"클라이언트 처리 중 오류 [{client_id}]: {e}")
        finally:
            await self.cleanup_client(client_id)
    
    async def handle_message(self, client: WebRTCClient, message: str):
        """메시지 처리"""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            
            if message_type == "join":
                await self.handle_join(client, data)
            elif message_type == "offer":
                await self.handle_offer(client, data)
            elif message_type == "answer":
                await self.handle_answer(client, data)
            elif message_type == "ice-candidate":
                await self.handle_ice_candidate(client, data)
            elif message_type == "video-frame":
                await self.handle_video_frame(client, data)
            elif message_type == "leave":
                await self.handle_leave(client)
            else:
                logger.warning(f"알 수 없는 메시지 타입: {message_type}")
                
        except json.JSONDecodeError:
            logger.error(f"잘못된 JSON 메시지: {message}")
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
    
    async def handle_join(self, client: WebRTCClient, data: dict):
        """방 참가 처리"""
        room_id = data.get("room_id", "default")
        client.room_id = room_id
        
        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        
        self.rooms[room_id].add(client.client_id)
        
        # 방에 다른 클라이언트가 있으면 Offerer로 설정
        other_clients = [cid for cid in self.rooms[room_id] if cid != client.client_id]
        if other_clients:
            client.is_offerer = True
            client.peer_id = other_clients[0]
            
            # 기존 클라이언트에게 새 클라이언트 알림
            if client.peer_id in self.clients:
                await self.send_to_client(client.peer_id, {
                    "type": "new-peer",
                    "peer_id": client.client_id
                })
        
        await self.send_to_client(client.client_id, {
            "type": "joined",
            "room_id": room_id,
            "is_offerer": client.is_offerer,
            "peer_id": client.peer_id
        })
        
        logger.info(f"클라이언트 {client.client_id} 방 {room_id} 참가")
    
    async def handle_offer(self, client: WebRTCClient, data: dict):
        """Offer 처리"""
        if client.peer_id and client.peer_id in self.clients:
            await self.send_to_client(client.peer_id, {
                "type": "offer",
                "offer": data["offer"],
                "peer_id": client.client_id
            })
            logger.info(f"Offer 전달: {client.client_id} -> {client.peer_id}")
    
    async def handle_answer(self, client: WebRTCClient, data: dict):
        """Answer 처리"""
        if client.peer_id and client.peer_id in self.clients:
            await self.send_to_client(client.peer_id, {
                "type": "answer",
                "answer": data["answer"],
                "peer_id": client.client_id
            })
            logger.info(f"Answer 전달: {client.client_id} -> {client.peer_id}")
    
    async def handle_ice_candidate(self, client: WebRTCClient, data: dict):
        """ICE 후보 처리"""
        if client.peer_id and client.peer_id in self.clients:
            await self.send_to_client(client.peer_id, {
                "type": "ice-candidate",
                "candidate": data["candidate"],
                "peer_id": client.client_id
            })
    
    async def handle_video_frame(self, client: WebRTCClient, data: dict):
        """비디오 프레임 처리"""
        try:
            # Base64 디코딩
            image_data = base64.b64decode(data["frame"])
            nparr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                # MediaPipe 처리
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.holistic.process(frame_rgb)
                
                # 랜드마크 수집
                landmarks_list = []
                landmarks_list.append({
                    "pose": results.pose_landmarks,
                    "left_hand": results.left_hand_landmarks,
                    "right_hand": results.right_hand_landmarks
                })
                
                # 시퀀스 버퍼 초기화
                if client.client_id not in self.client_sequences:
                    self.client_sequences[client.client_id] = []
                    self.client_frame_counters[client.client_id] = 0
                
                self.client_sequences[client.client_id].extend(landmarks_list)
                self.client_frame_counters[client.client_id] += 1
                
                # 시퀀스 길이 제한
                if len(self.client_sequences[client.client_id]) > self.MAX_SEQ_LENGTH:
                    self.client_sequences[client.client_id] = self.client_sequences[client.client_id][-self.MAX_SEQ_LENGTH:]
                
                # 예측 실행 (10프레임마다)
                if self.client_frame_counters[client.client_id] % 10 == 0 and len(self.client_sequences[client.client_id]) >= self.MAX_SEQ_LENGTH:
                    prediction = await self.run_prediction(client.client_id)
                    if prediction:
                        await self.send_to_client(client.client_id, {
                            "type": "classification-result",
                            "data": prediction
                        })
        
        except Exception as e:
            logger.error(f"비디오 프레임 처리 실패: {e}")
    
    async def run_prediction(self, client_id: str):
        """예측 실행"""
        try:
            sequence = self.preprocess_landmarks(self.client_sequences[client_id])
            pred_probs = self.model.predict(sequence.reshape(1, *sequence.shape), verbose=0)
            pred_idx = np.argmax(pred_probs[0])
            pred_label = self.ACTIONS[pred_idx]
            confidence = float(pred_probs[0][pred_idx])
            
            return {
                "prediction": pred_label,
                "confidence": confidence,
                "probabilities": {label: float(prob) for label, prob in zip(self.ACTIONS, pred_probs[0])}
            }
        except Exception as e:
            logger.error(f"예측 실행 실패: {e}")
            return None
    
    def preprocess_landmarks(self, landmarks_list):
        """랜드마크 전처리"""
        if not landmarks_list:
            return np.zeros((self.MAX_SEQ_LENGTH, 675))
        
        # 상대 좌표 변환
        relative_landmarks = []
        for frame in landmarks_list:
            combined = []
            for key in ["pose", "left_hand", "right_hand"]:
                if frame[key]:
                    if isinstance(frame[key], list):
                        combined.extend(frame[key])
                    else:
                        combined.extend([[l.x, l.y, l.z] for l in frame[key].landmark])
                else:
                    num_points = {"pose": 33, "left_hand": 21, "right_hand": 21}[key]
                    combined.extend([[0, 0, 0]] * num_points)
            if combined:
                relative_landmarks.append(np.array(combined).flatten())
            else:
                relative_landmarks.append(np.zeros(75 * 3))
        
        if not relative_landmarks:
            return np.zeros((self.MAX_SEQ_LENGTH, 675))
        
        # 시퀀스 길이 정규화
        sequence = np.array(relative_landmarks)
        if len(sequence) != self.MAX_SEQ_LENGTH:
            sequence = self.normalize_sequence_length(sequence, self.MAX_SEQ_LENGTH)
        
        # 동적 특성 추출
        velocity = np.diff(sequence, axis=0, prepend=sequence[0:1])
        acceleration = np.diff(velocity, axis=0, prepend=velocity[0:1])
        sequence = np.concatenate([sequence, velocity, acceleration], axis=1)
        
        return sequence
    
    def normalize_sequence_length(self, sequence, target_length=30):
        """시퀀스 길이 정규화"""
        current_length = len(sequence)
        if current_length == target_length:
            return sequence
        x_old = np.linspace(0, 1, current_length)
        x_new = np.linspace(0, 1, target_length)
        normalized_sequence = []
        for i in range(sequence.shape[1]):
            f = np.interp(x_new, x_old, sequence[:, i])
            normalized_sequence.append(f)
        return np.array(normalized_sequence).T
    
    async def handle_leave(self, client: WebRTCClient):
        """방 나가기 처리"""
        await self.cleanup_client(client.client_id)
    
    async def send_to_client(self, client_id: str, message: dict):
        """클라이언트에게 메시지 전송"""
        if client_id in self.clients:
            try:
                await self.clients[client_id].websocket.send(json.dumps(message))
            except Exception as e:
                logger.error(f"메시지 전송 실패 [{client_id}]: {e}")
    
    async def cleanup_client(self, client_id: str):
        """클라이언트 정리"""
        if client_id in self.clients:
            client = self.clients[client_id]
            
            # 방에서 제거
            if client.room_id and client.room_id in self.rooms:
                self.rooms[client.room_id].discard(client_id)
                if not self.rooms[client.room_id]:
                    del self.rooms[client.room_id]
            
            # 피어에게 알림
            if client.peer_id and client.peer_id in self.clients:
                await self.send_to_client(client.peer_id, {
                    "type": "peer-disconnected",
                    "peer_id": client_id
                })
            
            # 시퀀스 버퍼 정리
            if client_id in self.client_sequences:
                del self.client_sequences[client_id]
            if client_id in self.client_frame_counters:
                del self.client_frame_counters[client_id]
            
            del self.clients[client_id]
            logger.info(f"클라이언트 정리 완료: {client_id}")
    
    async def run_server(self):
        """서버 실행"""
        server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port
        )
        logger.info(f"WebRTC 시그널링 서버 시작: ws://{self.host}:{self.port}")
        
        try:
            await server.wait_closed()
        except KeyboardInterrupt:
            logger.info("서버 종료 중...")
        finally:
            # MediaPipe 정리
            self.holistic.close()

async def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description='WebRTC Signaling Server')
    parser.add_argument("--port", type=int, default=8765, help="Port number")
    parser.add_argument("--host", type=str, default="localhost", help="Host address")
    parser.add_argument("--model-data-url", type=str, required=True, help="Model data URL")
    args = parser.parse_args()
    
    server = WebRTCSignalingServer(
        model_data_url=args.model_data_url,
        host=args.host,
        port=args.port
    )
    
    await server.run_server()

if __name__ == "__main__":
    asyncio.run(main()) 