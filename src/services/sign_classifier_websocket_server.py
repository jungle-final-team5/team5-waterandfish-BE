import cv2
import numpy as np
import mediapipe as mp
import tensorflow as tf
import json
import sys
import os
import asyncio
import websockets
import logging
from collections import deque
from PIL import ImageFont, ImageDraw, Image
import base64
import io
from datetime import datetime
import argparse
import time  # 성능 측정용

# Add the current directory to sys.path to enable imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from s3_utils import s3_utils

# 로깅 설정은 main() 함수에서 동적으로 설정됩니다
logger = logging.getLogger(__name__)

class SignClassifierWebSocketServer:
    def __init__(self, model_info_url, host, port, debug_video=False, frame_skip=3, prediction_interval=10, max_frame_width=640, enable_profiling=False, aggressive_mode=False, accuracy_mode=False):
        """수어 분류 WebSocket 서버 초기화"""
        self.host = host
        self.port = port
        self.clients = set()  # 연결된 클라이언트들
        self.debug_video = debug_video  # 비디오 디버그 모드
        self.enable_profiling = enable_profiling  # 성능 프로파일링 모드
        self.aggressive_mode = aggressive_mode  # 공격적 최적화 모드
        self.accuracy_mode = accuracy_mode  # 정확도 우선 모드
        
        # 성능 최적화 설정
        self.frame_skip_rate = frame_skip  # N프레임 중 1프레임만 처리
        self.prediction_interval = prediction_interval  # N프레임마다 예측 실행
        self.debug_update_interval = 10  # 10프레임마다 디버그 화면 업데이트 (성능 향상)
        self.max_frame_width = max_frame_width  # 최대 프레임 너비
        
        # 모드별 설정 조정
        if self.accuracy_mode:
            # 정확도 우선 모드: 더 자주 처리
            self.frame_skip_rate = 1
            self.prediction_interval = max(5, prediction_interval - 3)  # 더 자주 예측
            self.debug_update_interval = 5  # 더 자주 업데이트
            logger.info(f" 정확도 모드 설정: 프레임스킵={self.frame_skip_rate}, 예측간격={self.prediction_interval}")
        elif self.aggressive_mode:
            # 공격적 모드: 더 적게 처리
            self.frame_skip_rate = frame_skip + 2  # 더 많이 스킵
            self.prediction_interval = prediction_interval + 5  # 더 적게 예측
            self.debug_update_interval = 15  # 더 적게 업데이트
            logger.info(f" 공격적 모드 설정: 프레임스킵={self.frame_skip_rate}, 예측간격={self.prediction_interval}")
        
        # 디버그 렌더링 최적화 설정
        self.debug_frame_width = 480  # 디버그 화면 너비 (더 작게)
        self.debug_frame_height = 360  # 디버그 화면 높이 (더 작게)
        
        # 성능 통계 추적
        self.performance_stats = {
            'total_frames': 0,
            'avg_decode_time': 0,
            'avg_mediapipe_time': 0,
            'avg_preprocessing_time': 0,
            'avg_prediction_time': 0,
            'max_frame_time': 0,
            'bottleneck_component': 'unknown'
        }
        
        # 모델 정보 로드
        self.model_info = self.load_model_info(model_info_url)
        if not self.model_info:
            raise ValueError("모델 정보를 로드할 수 없습니다.")
        
        # 설정값
        self.MAX_SEQ_LENGTH = self.model_info["input_shape"][0]
        
        # 모델 경로 처리 (S3 URL 또는 로컬 경로)
        model_path = self.model_info["model_path"]
        
        # s3://waterandfish-s3/models/ 디렉터리에서 찾기
        model_path = f"s3://waterandfish-s3/{model_path}"
        
        # 먼저 S3에서 시도
        
        try:
            logger.info(f" S3에서 모델 파일 다운로드 중: {model_path}")
            
            # S3에서 모델 파일 다운로드
            self.MODEL_SAVE_PATH = s3_utils.download_file_from_s3(model_path)
            
            logger.info(f" S3 모델 파일 다운로드 완료: {self.MODEL_SAVE_PATH}")
        except Exception as e:
            logger.warning(f" S3 다운로드 실패, 로컬 경로로 시도: {e}")
            # 로컬 경로 처리
            # model_path가 이미 "models/"로 시작하는 경우 중복 방지
            if model_path.startswith("models/"):
                # "models/" 부분을 제거하고 파일명만 사용
                model_filename = model_path[7:]  # "models/" 제거
                local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "models", model_filename)
            else:
                # 그대로 사용
                local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "models", model_path)
            
            self.MODEL_SAVE_PATH = local_path
            # self._setup_local_model_path(model_path)
        
        self.ACTIONS = self.model_info["labels"]
        self.QUIZ_LABELS = [a for a in self.ACTIONS if a != "None"]
        
        logger.info(f" 로드된 라벨: {self.ACTIONS}")
        logger.info(f" 퀴즈 라벨: {self.QUIZ_LABELS}")
        logger.info(f" 원본 모델 경로: {self.model_info['model_path']}")
        logger.info(f" 변환된 모델 경로: {self.MODEL_SAVE_PATH}")
        logger.info(f" 시퀀스 길이: {self.MAX_SEQ_LENGTH}")
        logger.info(f" 성능 설정: 프레임 스킵={self.frame_skip_rate}, 예측 간격={self.prediction_interval}")
        
        # 모델 파일 존재 확인
        if not os.path.exists(self.MODEL_SAVE_PATH):
            logger.error(f" 모델 파일을 찾을 수 없습니다: {self.MODEL_SAVE_PATH}")
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {self.MODEL_SAVE_PATH}")
        
        logger.info(f"✅ 모델 파일 존재 확인: {self.MODEL_SAVE_PATH}")
        
        # MediaPipe 초기화 (성능 최적화 설정)
        self.mp_holistic = mp.solutions.holistic
        
        # 모드에 따른 설정 조정
        if self.aggressive_mode:
            detection_confidence = 0.9  # 매우 높은 임계값 (속도 우선)
            tracking_confidence = 0.8   # 매우 높은 추적 신뢰도
            logger.info(" 공격적 최적화 모드 활성화 - 속도 우선")
        elif self.accuracy_mode:
            detection_confidence = 0.5  # 낮은 임계값 (정확도 우선)
            tracking_confidence = 0.3   # 낮은 추적 신뢰도 (정확도 우선)
            logger.info(" 정확도 우선 모드 활성화 - 정확도 우선")
        else:
            detection_confidence = 0.6  # 균형 설정 (기본값)
            tracking_confidence = 0.5   # 균형 추적 신뢰도
            logger.info(" 균형 최적화 모드 - 정확도와 성능의 균형")
        
        self.holistic = self.mp_holistic.Holistic(
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
            model_complexity=0,            # 모델 복잡도 감소 (0: 가장 빠름)
            smooth_landmarks=False,        # 랜드마크 스무딩 비활성화로 성능 향상
            enable_segmentation=False,     # 세그멘테이션 비활성화 (성능 향상)
            refine_face_landmarks=False,   # 얼굴 랜드마크 정제 비활성화
            static_image_mode=False        # 비디오 모드 최적화
        )
        
        # MediaPipe 드로잉 유틸리티 (디버그용)
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        
        # 모델 로드
        try:
            self.model = tf.keras.models.load_model(self.MODEL_SAVE_PATH)
            logger.info(f" 모델 로드 성공: {self.MODEL_SAVE_PATH}")
            
            # TensorFlow 성능 최적화 설정
            tf.config.optimizer.set_jit(True)  # XLA JIT 컴파일 활성화
            
            # 모델 warming up (첫 번째 예측 시 느린 속도 방지)
            dummy_input = np.zeros((1, self.MAX_SEQ_LENGTH, 675))
            _ = self.model.predict(dummy_input, verbose=0)
            logger.info(" 모델 warming up 완료")
            
        except Exception as e:
            logger.error(f" 모델 로딩 실패: {e}")
            raise
        
        # 시퀀스 버퍼 (클라이언트별로 관리)
        self.client_sequences = {}  # {client_id: deque}
        
        # 분류 상태 (클라이언트별로 관리)
        self.client_states = {}  # {client_id: {prediction, confidence, is_processing}}
        
        # 프레임 카운터 (클라이언트별)
        self.client_frame_counters = {}  # {client_id: frame_count}
        
        # 분류 통계
        self.classification_count = 0
        self.last_log_time = 0
        self.log_interval = 1.0  # 1초마다 로그 출력 (너무 빈번한 로그 방지)
        
        # 시퀀스 관리 (클라이언트별로 관리)
        self.client_sequence_managers = {}  # {client_id: {last_prediction, same_count}}
    async def shutdown_if_idle(self, delay: float = 5.0):
        await asyncio.sleep(delay)
        if not self.clients:
            logger.info("클라이언트 없음. 서버 종료를 진행합니다.")
            await self.shutdown_server()

    async def shutdown_server(self):
        logger.info("모델 서버 리소스를 정리하고 프로세스를 종료합니다.")
        os._exit(0)
    def load_model_info(self, model_info_url):
        """모델 정보 파일을 로드합니다."""
        try:
            # S3 URL인지 확인
            if model_info_url.startswith('s3://'):
                logger.info(f" S3에서 모델 정보 파일 다운로드 중: {model_info_url}")
                
                # S3에서 파일 다운로드
                local_path = s3_utils.download_file_from_s3(model_info_url)
                model_info_url = local_path
                logger.info(f" S3 파일 다운로드 완료: {local_path}")
            else:
                # 로컬 파일 경로 처리
                # 현재 스크립트 파일의 위치를 기준으로 프로젝트 루트 계산
                current_dir = os.path.dirname(os.path.abspath(__file__))
                # src/services에서 프로젝트 루트로 이동 (2단계 상위)
                project_root = os.path.dirname(os.path.dirname(current_dir))
                
                # 파일명만 전달된 경우 public/model-info/ 디렉터리에서 찾기
                if os.path.basename(model_info_url) == model_info_url:
                    # 파일명만 전달된 경우
                    model_info_url = os.path.join("public", "model-info", model_info_url)
                
                # 상대 경로인 경우 프로젝트 루트를 기준으로 절대 경로로 변환
                if not os.path.isabs(model_info_url):
                    model_info_url = os.path.join(project_root, model_info_url)
                
                # 경로 정규화
                model_info_url = os.path.normpath(model_info_url)
            
            logger.info(f" 모델 정보 파일 경로: {model_info_url}")
            
            # 파일 존재 여부 확인 (S3에서 다운로드한 경우는 이미 존재함)
            if not model_info_url.startswith('s3://') and not os.path.exists(model_info_url):
                logger.error(f" 모델 정보 파일을 찾을 수 없습니다: {model_info_url}")
                return None
            
            with open(model_info_url, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f" 모델 정보 파일 로드 실패: {e}")
            return None
    
    def get_client_id(self, websocket):
        """클라이언트 ID 생성"""
        return f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    
    def initialize_client(self, client_id):
        """클라이언트 초기화"""
        if client_id not in self.client_sequences:
            self.client_sequences[client_id] = deque(maxlen=self.MAX_SEQ_LENGTH)
            self.client_states[client_id] = {
                "prediction": "None",
                "confidence": 0.0,
                "is_processing": False
            }
            self.client_sequence_managers[client_id] = {
                "last_prediction": None,
                "same_count": 0
            }
            self.client_frame_counters[client_id] = 0
            logger.info(f"🆕 클라이언트 초기화: {client_id}")
    
    def cleanup_client(self, client_id):
        """클라이언트 정리"""
        if client_id in self.client_sequences:
            del self.client_sequences[client_id]
        if client_id in self.client_states:
            del self.client_states[client_id]
        if client_id in self.client_sequence_managers:
            del self.client_sequence_managers[client_id]
        if client_id in self.client_frame_counters:
            del self.client_frame_counters[client_id]
        
        # 디버그 모드인 경우 해당 클라이언트의 윈도우 정리
        if self.debug_video:
            cv2.destroyWindow(f"Debug - {client_id}")
        
        logger.info(f"🧹 클라이언트 정리: {client_id}")
    
    def bytes_to_frame(self, image_bytes):
        """바이트 데이터를 OpenCV 프레임으로 변환"""
        start_time = time.time()
        
        try:
            # 바이트를 numpy 배열로 변환
            decode_start = time.time()
            nparr = np.frombuffer(image_bytes, np.uint8)
            
            # 이미지 디코딩 (JPEG, PNG 등 지원)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            decode_time = time.time() - decode_start
            
            if frame is None:
                logger.warning("이미지 디코딩 실패 - 지원되지 않는 포맷이거나 손상된 데이터")
                return None
            
            # 프레임 크기 확인
            if frame.size == 0:
                logger.warning("빈 프레임")
                return None
            
            # 검은색 프레임 감지
            if frame.max() == 0:
                logger.warning("검은색 프레임 감지")
                return None
            
            total_time = time.time() - start_time
            
            # 성능 로깅 (디버그 모드에서만)
            if self.enable_profiling and total_time > 0.01:  # 10ms 이상 걸리는 경우만 로그
                logger.debug(f"🔍 Frame decode: {decode_time*1000:.1f}ms, Total: {total_time*1000:.1f}ms")
            
            return frame
            
        except Exception as e:
            logger.error(f"프레임 변환 실패: {e}")
            return None
    
    def normalize_sequence_length(self, sequence, target_length=30):
        """시퀀스 길이를 정규화"""
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
    
    def extract_dynamic_features(self, sequence):
        """동적 특성 추출 (성능 프로파일링 포함)"""
        start_time = time.time()
        
        velocity_start = time.time()
        velocity = np.diff(sequence, axis=0, prepend=sequence[0:1])
        velocity_time = time.time() - velocity_start
        
        acceleration_start = time.time()
        acceleration = np.diff(velocity, axis=0, prepend=velocity[0:1])
        acceleration_time = time.time() - acceleration_start
        
        concat_start = time.time()
        dynamic_features = np.concatenate([sequence, velocity, acceleration], axis=1)
        concat_time = time.time() - concat_start
        
        total_time = time.time() - start_time
        
        # 성능 프로파일링 출력 (10ms 이상 걸리는 경우만)
        if self.enable_profiling and total_time > 0.01:
            logger.info(f"🏃 동적특성 추출 성능:")
            logger.info(f"   전체: {total_time*1000:.1f}ms")
            logger.info(f"   속도계산: {velocity_time*1000:.1f}ms")
            logger.info(f"   가속도계산: {acceleration_time*1000:.1f}ms")
            logger.info(f"   결합: {concat_time*1000:.1f}ms")
        
        return dynamic_features
    
    def convert_to_relative_coordinates(self, landmarks_list):
        """상대 좌표로 변환 (성능 프로파일링 포함)"""
        start_time = time.time()
        
        relative_landmarks = []
        shoulder_calc_time = 0
        pose_calc_time = 0
        hand_calc_time = 0
        
        for frame in landmarks_list:
            if not frame["pose"]:
                relative_landmarks.append(frame)
                continue
            
            # 어깨 중심점 계산
            shoulder_start = time.time()
            pose_landmarks = frame["pose"].landmark
            left_shoulder = pose_landmarks[11]
            right_shoulder = pose_landmarks[12]
            shoulder_center_x = (left_shoulder.x + right_shoulder.x) / 2
            shoulder_center_y = (left_shoulder.y + right_shoulder.y) / 2
            shoulder_center_z = (left_shoulder.z + right_shoulder.z) / 2
            shoulder_width = abs(right_shoulder.x - left_shoulder.x)
            if shoulder_width == 0:
                shoulder_width = 1.0
            shoulder_calc_time += time.time() - shoulder_start
            
            new_frame = {}
            
            # 포즈 랜드마크 처리
            if frame["pose"]:
                pose_start = time.time()
                relative_pose = []
                for landmark in pose_landmarks:
                    rel_x = (landmark.x - shoulder_center_x) / shoulder_width
                    rel_y = (landmark.y - shoulder_center_y) / shoulder_width
                    rel_z = (landmark.z - shoulder_center_z) / shoulder_width
                    relative_pose.append([rel_x, rel_y, rel_z])
                new_frame["pose"] = relative_pose
                pose_calc_time += time.time() - pose_start
            
            # 손 랜드마크 처리
            hand_start = time.time()
            for hand_key in ["left_hand", "right_hand"]:
                if frame[hand_key]:
                    relative_hand = []
                    for landmark in frame[hand_key].landmark:
                        rel_x = (landmark.x - shoulder_center_x) / shoulder_width
                        rel_y = (landmark.y - shoulder_center_y) / shoulder_width
                        rel_z = (landmark.z - shoulder_center_z) / shoulder_width
                        relative_hand.append([rel_x, rel_y, rel_z])
                    new_frame[hand_key] = relative_hand
                else:
                    new_frame[hand_key] = None
            hand_calc_time += time.time() - hand_start
            
            relative_landmarks.append(new_frame)
        
        total_time = time.time() - start_time
        
        # 성능 프로파일링 출력 (20ms 이상 걸리는 경우만)
        if self.enable_profiling and total_time > 0.02:
            logger.info(f" 상대좌표 변환 성능:")
            logger.info(f"   전체: {total_time*1000:.1f}ms")
            logger.info(f"   어깨계산: {shoulder_calc_time*1000:.1f}ms")
            logger.info(f"   포즈계산: {pose_calc_time*1000:.1f}ms")
            logger.info(f"   손계산: {hand_calc_time*1000:.1f}ms")
        
        return relative_landmarks
    
    def improved_preprocess_landmarks(self, landmarks_list):
        """랜드마크 전처리 (성능 프로파일링 포함)"""
        start_time = time.time()
        
        if not landmarks_list:
            return np.zeros((self.MAX_SEQ_LENGTH, 675))
        
        # 1. 상대 좌표 변환
        relative_start = time.time()
        relative_landmarks = self.convert_to_relative_coordinates(landmarks_list)
        relative_time = time.time() - relative_start
        
        # 2. 프레임 처리
        processing_start = time.time()
        processed_frames = []
        for frame in relative_landmarks:
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
                processed_frames.append(np.array(combined).flatten())
            else:
                processed_frames.append(np.zeros(75 * 3))
        processing_time = time.time() - processing_start
        
        if not processed_frames:
            return np.zeros((self.MAX_SEQ_LENGTH, 675))
        
        # 3. 시퀀스 길이 정규화
        normalize_start = time.time()
        sequence = np.array(processed_frames)
        if len(sequence) != self.MAX_SEQ_LENGTH:
            sequence = self.normalize_sequence_length(sequence, self.MAX_SEQ_LENGTH)
        normalize_time = time.time() - normalize_start
        
        # 4. 동적 특성 추출
        dynamic_start = time.time()
        sequence = self.extract_dynamic_features(sequence)
        dynamic_time = time.time() - dynamic_start
        
        total_time = time.time() - start_time
        
        # 성능 프로파일링 출력 (50ms 이상 걸리는 경우만)
        if self.enable_profiling and total_time > 0.05:
            logger.info(f" 랜드마크 전처리 성능:")
            logger.info(f"   전체: {total_time*1000:.1f}ms")
            logger.info(f"   상대좌표: {relative_time*1000:.1f}ms")
            logger.info(f"   프레임처리: {processing_time*1000:.1f}ms")
            logger.info(f"   정규화: {normalize_time*1000:.1f}ms")
            logger.info(f"   동적특성: {dynamic_time*1000:.1f}ms")
        
        return sequence
    
    def log_classification_result(self, result, client_id):
        """분류 결과를 로그로 출력"""
        current_time = asyncio.get_event_loop().time()
        
        # 로그 출력 주기 제한 (너무 빈번한 로그 방지)
        if current_time - self.last_log_time >= self.log_interval:
            logger.info(f" [{client_id}] 예측: {result['prediction']} (신뢰도: {result['confidence']:.3f})")

            message = json.dumps({
                "type": "classification_log",
                "data": result,
                "client_id": client_id,
                "timestamp": asyncio.get_event_loop().time()
            })
            for ws in list(self.clients):
                asyncio.create_task(ws.send(message))

            self.last_log_time = current_time
        
        # 분류 횟수 증가
        self.classification_count += 1
    
    def process_frame(self, frame, client_id):
        """프레임 처리 및 분류 (성능 최적화 + 프로파일링)"""
        frame_start_time = time.time()
        
        # 프레임 카운터 증가
        self.client_frame_counters[client_id] += 1
        frame_count = self.client_frame_counters[client_id]
        
        # 프레임 스킵 로직 (매 N프레임 중 1프레임만 처리)
        if frame_count % self.frame_skip_rate != 0:
            return None
        
        # 이미 처리 중인 경우 스킵
        if self.client_states[client_id]["is_processing"]:
            return None
        
        self.client_states[client_id]["is_processing"] = True
        
        # 성능 측정 변수들
        resize_time = 0
        debug_time = 0
        mediapipe_time = 0
        preprocessing_time = 0
        prediction_time = 0
        
        try:
            # 1. 프레임 크기 사전 제한 (큰 프레임 처리 시간 단축)
            resize_start = time.time()
            height, width = frame.shape[:2]
            if width > self.max_frame_width:  # 최대 프레임 너비보다 크면 크기 조정
                scale = self.max_frame_width / width
                new_width = int(width * scale)
                new_height = int(height * scale)
                frame = cv2.resize(frame, (new_width, new_height))
                height, width = new_height, new_width
            resize_time = time.time() - resize_start
            
            # 2. 디버그 모드: 업데이트 빈도 제한 (최적화)
            debug_start = time.time()
            if self.debug_video and frame_count % self.debug_update_interval == 0:
                # 더 작은 디버그 프레임 생성 (성능 향상)
                debug_frame = cv2.resize(frame, (self.debug_frame_width, self.debug_frame_height))
                
                # 간단한 정보만 표시 (성능 향상)
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.5  # 더 작은 폰트
                thickness = 1     # 더 얇은 선
                
                # 기본 정보
                cv2.putText(debug_frame, f"ID: {client_id}", (5, 20), font, font_scale, (0, 255, 0), thickness)
                cv2.putText(debug_frame, f"Frames: {len(self.client_sequences[client_id])}", (5, 40), font, font_scale, (0, 255, 0), thickness)
                
                # 현재 예측 결과 (있는 경우만)
                if client_id in self.client_states and self.client_states[client_id]["prediction"] != "None":
                    pred_text = f"{self.client_states[client_id]['prediction']}"
                    conf_text = f"{self.client_states[client_id]['confidence']:.2f}"
                    cv2.putText(debug_frame, pred_text, (5, 60), font, font_scale, (0, 0, 255), thickness)
                    cv2.putText(debug_frame, conf_text, (5, 80), font, font_scale, (0, 0, 255), thickness)
                
                # 프레임 표시
                cv2.imshow(f"Debug - {client_id}", debug_frame)
                
                # ESC 키로 종료 (비블로킹)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC key
                    logger.info("ESC 키가 눌렸습니다. 디버그 모드를 종료합니다.")
                    cv2.destroyAllWindows()
                    self.debug_video = False
            debug_time = time.time() - debug_start
            
            # 3. MediaPipe 처리
            mediapipe_start = time.time()
            # BGR을 RGB로 변환
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # MediaPipe로 랜드마크 추출
            results = self.holistic.process(frame_rgb)
            mediapipe_time = time.time() - mediapipe_start
            
            # 4. 랜드마크 데이터 수집
            landmarks_list = []
            landmarks_list.append({
                "pose": results.pose_landmarks,
                "left_hand": results.left_hand_landmarks,
                "right_hand": results.right_hand_landmarks
            })
            
            # 시퀀스에 추가
            self.client_sequences[client_id].extend(landmarks_list)
            
            # 5. 예측 실행 빈도 제한 (성능 향상)
            should_predict = (
                len(self.client_sequences[client_id]) >= self.MAX_SEQ_LENGTH and
                frame_count % self.prediction_interval == 0
            )
            
            # should_predict = False
            
            result = None
            if should_predict:
                # 랜드마크 전처리
                preprocessing_start = time.time()
                sequence = self.improved_preprocess_landmarks(list(self.client_sequences[client_id]))
                preprocessing_time = time.time() - preprocessing_start
                
                # 모델 예측
                prediction_start = time.time()
                pred_probs = self.model.predict(sequence.reshape(1, *sequence.shape), verbose=0)
                pred_idx = np.argmax(pred_probs[0])
                pred_label = self.ACTIONS[pred_idx]
                confidence = float(pred_probs[0][pred_idx])
                prediction_time = time.time() - prediction_start
                
                # 결과 생성
                result = {
                    "prediction": pred_label,
                    "confidence": confidence,
                    "probabilities": {label: float(prob) for label, prob in zip(self.ACTIONS, pred_probs[0])}
                }
                
                # 클라이언트 상태 업데이트 (디버그 표시용)
                self.client_states[client_id]["prediction"] = pred_label
                self.client_states[client_id]["confidence"] = confidence
                
                # 분류 결과를 로그로 출력
                self.log_classification_result(result, client_id)
            
            # 성능 프로파일링 출력
            total_time = time.time() - frame_start_time
            
            # 성능 통계 업데이트
            self.performance_stats['total_frames'] += 1
            if mediapipe_time > 0:
                self.performance_stats['avg_mediapipe_time'] = (
                    (self.performance_stats['avg_mediapipe_time'] * (self.performance_stats['total_frames'] - 1) + mediapipe_time) /
                    self.performance_stats['total_frames']
                )
            if preprocessing_time > 0:
                self.performance_stats['avg_preprocessing_time'] = (
                    (self.performance_stats['avg_preprocessing_time'] * (self.performance_stats['total_frames'] - 1) + preprocessing_time) /
                    self.performance_stats['total_frames']
                )
            if prediction_time > 0:
                self.performance_stats['avg_prediction_time'] = (
                    (self.performance_stats['avg_prediction_time'] * (self.performance_stats['total_frames'] - 1) + prediction_time) /
                    self.performance_stats['total_frames']
                )
            if total_time > self.performance_stats['max_frame_time']:
                self.performance_stats['max_frame_time'] = total_time
                # 병목 컴포넌트 식별
                times = {
                    'mediapipe': mediapipe_time,
                    'preprocessing': preprocessing_time,
                    'prediction': prediction_time,
                    'debug': debug_time,
                    'resize': resize_time
                }
                self.performance_stats['bottleneck_component'] = max(times, key=times.get)
            
            # 성능 프로파일링 출력 (프로파일링 모드가 활성화된 경우)
            if self.enable_profiling and total_time > 0.05:  # 50ms 이상 걸리는 경우만 로그
                if self.aggressive_mode:
                    # 공격적 모드에서는 간단한 프로파일링
                    logger.info(f" [{client_id}] 프레임 #{self.performance_stats['total_frames']}: {total_time*1000:.1f}ms (MP:{mediapipe_time*1000:.1f}ms)")
                else:
                    # 기본 프로파일링
                    logger.info(f" [{client_id}] 성능 프로파일 (프레임 #{self.performance_stats['total_frames']}):")
                    logger.info(f"   전체: {total_time*1000:.1f}ms")
                    logger.info(f"   리사이즈: {resize_time*1000:.1f}ms")
                    logger.info(f"   디버그: {debug_time*1000:.1f}ms")
                    logger.info(f"   MediaPipe: {mediapipe_time*1000:.1f}ms")
                    if should_predict:
                        logger.info(f"   전처리: {preprocessing_time*1000:.1f}ms")
                        logger.info(f"   예측: {prediction_time*1000:.1f}ms")
                    logger.info(f"    병목: {self.performance_stats['bottleneck_component']}")
                
                # 100프레임마다 성능 요약 출력
                if self.performance_stats['total_frames'] % 100 == 0:
                    logger.info(f" 성능 요약 (100프레임 평균):")
                    logger.info(f"   평균 MediaPipe: {self.performance_stats['avg_mediapipe_time']*1000:.1f}ms")
                    logger.info(f"   평균 전처리: {self.performance_stats['avg_preprocessing_time']*1000:.1f}ms")
                    logger.info(f"   평균 예측: {self.performance_stats['avg_prediction_time']*1000:.1f}ms")
                    logger.info(f"   최대 프레임 시간: {self.performance_stats['max_frame_time']*1000:.1f}ms")
                    logger.info(f"   주요 병목: {self.performance_stats['bottleneck_component']}")
            
            # 디버그 모드에서는 간단한 성능 정보만 출력
            elif self.debug_video and total_time > 0.1:  # 100ms 이상 걸리는 경우만 로그
                logger.info(f" [{client_id}] 느린 프레임 감지: {total_time*1000:.1f}ms")
            
            return result
                
        except Exception as e:
            logger.error(f"예측 실패: {e}")
            return None
        finally:
            self.client_states[client_id]["is_processing"] = False

    async def monitor_shutdown(self, check_interval: float = 5.0):
        """클라이언트가 모두 종료되었는지 주기적으로 확인하고 서버 종료"""
        while True:
            await asyncio.sleep(check_interval)
            if not self.clients:  # 클라이언트가 아무도 없을 때
                logger.info("모든 클라이언트가 종료됨. 서버를 종료합니다.")
                await self.shutdown_server()
                
    async def handle_client(self, websocket):
        """클라이언트 연결 처리"""
        client_id = self.get_client_id(websocket)
        self.clients.add(websocket)
        self.initialize_client(client_id)
        
        logger.info(f" client connected: {client_id}")
        
        try:
            async for message in websocket:
                try:
                    # 바이너리 데이터인지 확인
                    if isinstance(message, bytes):
                        # 바이너리 데이터를 직접 처리
                        frame = self.bytes_to_frame(message)
                        
                        if frame is not None:
                            result = self.process_frame(frame, client_id)
                            
                            if result:
                                # 결과를 클라이언트로 전송
                                response = {
                                    "type": "classification_result",
                                    "data": result,
                                    "timestamp": asyncio.get_event_loop().time()
                                }
                                await websocket.send(json.dumps(response))
                        
                        # 메모리 최적화: 프레임 명시적 해제
                        del frame
                        
                    else:
                        # JSON 메시지 처리 (기존 방식 유지)
                        data = json.loads(message)
                        
                        if data.get("type") == "video_chunk":
                            # 비디오 청크 처리
                            chunk_data = base64.b64decode(data["data"])
                            frame = self.bytes_to_frame(chunk_data)
                            
                            if frame is not None:
                                result = self.process_frame(frame, client_id)
                                
                                if result:
                                    # 결과를 클라이언트로 전송
                                    response = {
                                        "type": "classification_result",
                                        "data": result,
                                        "timestamp": asyncio.get_event_loop().time()
                                    }
                                    await websocket.send(json.dumps(response))
                            
                            # 메모리 최적화: 변수 명시적 해제
                            del chunk_data, frame
                        
                        elif data.get("type") == "ping":
                            # 핑 응답
                            await websocket.send(json.dumps({"type": "pong"}))
                        
                except json.JSONDecodeError:
                    logger.warning(f"잘못된 JSON 메시지: {client_id}")
                except Exception as e:
                    logger.error(f"메시지 처리 실패 [{client_id}]: {e}")
                    # 에러 발생 시 클라이언트에게 알림
                    try:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "프레임 처리 중 오류가 발생했습니다."
                        }))
                    except:
                        pass  # 연결이 끊어진 경우 무시
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f" 클라이언트 연결 종료: {client_id}")
        except Exception as e:
            logger.error(f"클라이언트 처리 중 오류 [{client_id}]: {e}")
        finally:
            self.clients.remove(websocket)
            self.cleanup_client(client_id)

            if not self.clients:
                logger.info("모든 클라이언트가 연결 종료됨. 서버 종료 예약.")
                asyncio.create_task(self.shutdown_if_idle())
    
    async def run_server(self):
        """WebSocket 서버 실행"""
        server = await websockets.serve(
            self.handle_client, 
            self.host, 
            self.port
        )
        logger.info(f" 수어 분류 WebSocket 서버 시작: ws://{self.host}:{self.port}")
        logger.info(f" 서버 정보:")
        logger.info(f"   - 호스트: {self.host}")
        logger.info(f"   - 포트: {self.port}")
        logger.info(f"   - 모델: {self.MODEL_SAVE_PATH}")
        logger.info(f"   - 라벨 수: {len(self.ACTIONS)}")
        logger.info(f"   - 시퀀스 길이: {self.MAX_SEQ_LENGTH}")
        logger.info(f"   - 디버그 모드: {self.debug_video}")
        logger.info(f" 성능 최적화 설정:")
        logger.info(f"   - 프레임 스킵: {self.frame_skip_rate}프레임 중 1프레임 처리")
        logger.info(f"   - 예측 간격: {self.prediction_interval}프레임마다 예측")
        logger.info(f"   - 디버그 업데이트: {self.debug_update_interval}프레임마다 화면 업데이트")
        logger.info(f"   - MediaPipe 복잡도: 0 (최고 성능)")
        logger.info(f"   - 프레임 크기 제한: {self.max_frame_width}px")
        logger.info(f"   - TensorFlow XLA JIT: 활성화")
        logger.info(f"   - Performance profiling: {self.enable_profiling}")
        logger.info(f" Starting server with optimized settings...")
        asyncio.create_task(self.monitor_shutdown())
        try:
            await server.wait_closed()
        except KeyboardInterrupt:
            logger.info(" 서버 종료 중...")
        finally:
            # 디버그 모드인 경우 모든 OpenCV 윈도우 정리
            if self.debug_video:
                cv2.destroyAllWindows()
                logger.info(" 디버그 윈도우 정리 완료")

def setup_logging(log_level='INFO'):
    """로깅 설정을 동적으로 구성"""
    # 로그 레벨 매핑
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
        'OFF': logging.CRITICAL + 1  # 로그를 완전히 끄기 위한 레벨
    }
    
    # 로그 레벨 설정
    numeric_level = level_map.get(log_level.upper(), logging.INFO)
    
    # 로깅 기본 설정
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True  # 기존 로깅 설정 덮어쓰기
    )
    
    # 로그가 완전히 꺼진 경우 알림 (단, 이 알림은 출력되지 않음)
    if log_level.upper() == 'OFF':
        # 로그를 끄기 위해 모든 로거의 레벨을 높임
        logging.getLogger().setLevel(logging.CRITICAL + 1)
        # 핸들러도 같은 레벨로 설정
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.CRITICAL + 1)
    
    return logging.getLogger(__name__)

def main():
    """메인 함수"""
    
    parser = argparse.ArgumentParser(description='Sign Classifier WebSocket Server')
    parser.add_argument("--port", type=int, required=True, help="Port number for the server")
    parser.add_argument("--env", type=str, required=True, help="Environment variable model_info_URL")
    parser.add_argument("--log-level", type=str, default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'OFF'],
                       help="Set logging level (default: INFO, use OFF to disable all logs)")
    parser.add_argument("--debug-video", action='store_true',
                       help="Enable video debug mode to display received frames")
    parser.add_argument("--frame-skip", type=int, default=3,
                       help="Frame skip rate (process 1 frame every N frames, default: 3)")
    parser.add_argument("--prediction-interval", type=int, default=10,
                       help="Prediction interval (run prediction every N frames, default: 10)")
    parser.add_argument("--max-frame-width", type=int, default=640,
                       help="Maximum frame width for processing (default: 640)")
    parser.add_argument("--profile", action='store_true',
                       help="Enable detailed performance profiling")
    parser.add_argument("--aggressive-mode", action='store_true',
                       help="Enable aggressive optimization mode (may reduce accuracy)")
    parser.add_argument("--accuracy-mode", action='store_true',
                       help="Enable accuracy-first mode (may reduce performance)")
    args = parser.parse_args()
    
    port = args.port
    model_info_url = args.env
    log_level = args.log_level
    debug_video = args.debug_video
    frame_skip = args.frame_skip
    prediction_interval = args.prediction_interval
    max_frame_width = args.max_frame_width
    enable_profiling = args.profile
    aggressive_mode = args.aggressive_mode
    accuracy_mode = args.accuracy_mode
    
    # 로깅 설정 (동적으로 설정)
    global logger
    logger = setup_logging(log_level)
    
    # 로그가 꺼져있지 않은 경우에만 시작 메시지 출력
    if log_level.upper() != 'OFF':
        print(f" Starting sign classifier WebSocket server...")
        print(f" Model data URL: {model_info_url}")
        print(f" Port: {port}")
        print(f" Log level: {log_level}")
        print(f" Debug video: {debug_video}")
        print(f" Performance settings:")
        print(f"   - Frame skip: {frame_skip}")
        print(f"   - Prediction interval: {prediction_interval}")
        print(f"   - Max frame width: {max_frame_width}")
        print(f"   - Performance profiling: {enable_profiling}")
        print(f"   - Aggressive mode: {aggressive_mode}")
        print(f"   - Accuracy mode: {accuracy_mode}")
        print(f" Starting server with optimized settings...")
    
    # 현재 스크립트 파일의 위치를 기준으로 프로젝트 루트 계산
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # src/services에서 프로젝트 루트로 이동 (2단계 상위)
    project_root = os.path.dirname(os.path.dirname(current_dir))
    
    # 파일명만 전달된 경우 s3://waterandfish-s3/model-info/ 디렉터리에서 찾기
    model_info_url_processed = model_info_url
    if os.path.basename(model_info_url) == model_info_url:
        # 파일명만 전달된 경우
        model_info_url_processed = f"s3://waterandfish-s3/model-info/{model_info_url}"
    
    logger.info(f" 원본 모델 데이터 URL: {model_info_url}")
    logger.info(f" 처리된 모델 데이터 경로: {model_info_url_processed}")
    logger.info(f" 포트: {port}")
    
    # S3 URL인지 확인
    if model_info_url_processed.startswith('s3://'):
        logger.info(f"✅ S3 모델 경로 확인됨: {model_info_url_processed}")
    else:
        # 로컬 파일 경로인 경우 존재 여부 확인
        if not os.path.isabs(model_info_url_processed):
            model_info_url_full = os.path.join(project_root, model_info_url_processed)
        else:
            model_info_url_full = model_info_url_processed
        
        # 경로 정규화
        model_info_url_full = os.path.normpath(model_info_url_full)
        
        if not os.path.exists(model_info_url_full):
            logger.error(f"❌ 모델 정보 파일을 찾을 수 없습니다: {model_info_url_full}")
            sys.exit(1)
        
        logger.info(f"✅ 로컬 모델 정보 파일 확인됨: {model_info_url_full}")
    
    # 서버 생성 및 실행
    # localhost should be changed to the server's IP address when deploying to a server
    server = SignClassifierWebSocketServer(model_info_url_processed, host="localhost", port=port, debug_video=debug_video, frame_skip=frame_skip, prediction_interval=prediction_interval, max_frame_width=max_frame_width, enable_profiling=enable_profiling, aggressive_mode=aggressive_mode, accuracy_mode=accuracy_mode)
    
    # 디버그 모드 활성화 시 알림
    if debug_video:
        logger.info(" 비디오 디버그 모드 활성화 - 수신된 프레임을 실시간으로 표시합니다")
        logger.info("   - ESC 키를 눌러 디버그 모드를 종료할 수 있습니다")
        logger.info("   - 각 클라이언트별로 별도의 창이 표시됩니다")
    
    asyncio.run(server.run_server())

if __name__ == "__main__":
    main() 