# OpenCV 제거 - 이미지 처리는 프론트엔드에서 처리
# import cv2
import numpy as np
# MediaPipe 제거 - 프론트엔드에서 처리
# import mediapipe as mp
import tensorflow as tf
import json
import sys
import os
import asyncio
import websockets
import logging
from collections import deque
# PIL, base64, io 제거 - 이미지 처리 불필요
# from PIL import ImageFont, ImageDraw, Image
# import base64
# import io
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
    def __init__(self, model_info_url, host, port, debug_mode=False, prediction_interval=5, enable_profiling=False, result_buffer_size=15):
        """수어 분류 WebSocket 서버 초기화 (벡터 데이터 처리용)"""
        self.host = host
        self.port = port
        self.clients = set()  # 연결된 클라이언트들
        self.debug_mode = debug_mode  # 디버그 모드
        self.enable_profiling = enable_profiling  # 성능 프로파일링 모드
        
        # 종료 대기 태스크
        self.shutdown_task = None
        
        
        # 성능 최적화 설정 (벡터 처리에 최적화)
        self.prediction_interval = prediction_interval  # N개 벡터마다 예측 실행
        self.result_buffer_size = result_buffer_size  # 분류 결과 버퍼 크기 (기본값: 15개 프레임)
        
        # 성능 통계 추적
        self.performance_stats = {
            'total_vectors': 0,
            'avg_preprocessing_time': 0,
            'avg_prediction_time': 0,
            'max_processing_time': 0,
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
            logger.info(f"S3에서 모델 파일 다운로드 중: {model_path}")
            # S3에서 모델 파일 다운로드
            self.MODEL_SAVE_PATH = s3_utils.download_file_from_s3(model_path)
            logger.info(f"S3 모델 파일 다운로드 완료: {self.MODEL_SAVE_PATH}")
        except Exception as e:
            logger.warning(f"S3 다운로드 실패, 로컬 경로로 시도: {e}")
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
        
        logger.info(f"로드된 라벨: {self.ACTIONS}")
        logger.info(f"퀴즈 라벨: {self.QUIZ_LABELS}")
        logger.info(f"원본 모델 경로: {self.model_info['model_path']}")
        logger.info(f"변환된 모델 경로: {self.MODEL_SAVE_PATH}")
        logger.info(f"시퀀스 길이: {self.MAX_SEQ_LENGTH}")
        logger.info(f"성능 설정: 예측 간격={self.prediction_interval}, 결과 버퍼 크기={self.result_buffer_size}")
        
        # 모델 파일 존재 확인
        if not os.path.exists(self.MODEL_SAVE_PATH):
            logger.error(f"모델 파일을 찾을 수 없습니다: {self.MODEL_SAVE_PATH}")
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {self.MODEL_SAVE_PATH}")
        logger.info(f"모델 파일 존재 확인: {self.MODEL_SAVE_PATH}")
        
        # MediaPipe 관련 초기화 제거 - 프론트엔드에서 처리
        logger.info("벡터 처리 모드 - MediaPipe는 프론트엔드에서 처리됩니다")
        
        # 모델 로드
        try:
            # Keras 3와 tf-keras 호환성을 위한 모델 로딩
            model_loaded = False
            
            # 방법 1: tf-keras로 시도
            if not model_loaded:
                try:
                    self.model = tf.keras.models.load_model(self.MODEL_SAVE_PATH)
                    logger.info(f"tf-keras로 모델 로드 성공: {self.MODEL_SAVE_PATH}")
                    model_loaded = True
                except Exception as tf_error:
                    logger.info(f"tf-keras 로딩 실패: {tf_error}")
            
            # 방법 2: keras로 시도
            if not model_loaded:
                try:
                    import keras
                    self.model = keras.models.load_model(self.MODEL_SAVE_PATH)
                    logger.info(f"keras로 모델 로드 성공: {self.MODEL_SAVE_PATH}")
                    model_loaded = True
                except Exception as keras_error:
                    logger.info(f"keras 로딩 실패: {keras_error}")
            
            # 방법 3: tf-keras with compile=False
            if not model_loaded:
                try:
                    self.model = tf.keras.models.load_model(self.MODEL_SAVE_PATH, compile=False)
                    logger.info(f"tf-keras (compile=False)로 모델 로드 성공: {self.MODEL_SAVE_PATH}")
                    model_loaded = True
                except Exception as compile_false_error:
                    logger.info(f"tf-keras (compile=False) 로딩 실패: {compile_false_error}")
            
            # 방법 4: keras with compile=False
            if not model_loaded:
                try:
                    import keras
                    self.model = keras.models.load_model(self.MODEL_SAVE_PATH, compile=False)
                    logger.info(f"keras (compile=False)로 모델 로드 성공: {self.MODEL_SAVE_PATH}")
                    model_loaded = True
                except Exception as keras_compile_false_error:
                    logger.info(f"keras (compile=False) 로딩 실패: {keras_compile_false_error}")
            
            # 방법 5: custom_objects 없이 시도
            if not model_loaded:
                try:
                    self.model = tf.keras.models.load_model(self.MODEL_SAVE_PATH, custom_objects={})
                    logger.info(f"tf-keras (custom_objects={{}})로 모델 로드 성공: {self.MODEL_SAVE_PATH}")
                    model_loaded = True
                except Exception as custom_objects_error:
                    logger.info(f"tf-keras (custom_objects={{}}) 로딩 실패: {custom_objects_error}")
            
            if not model_loaded:
                raise Exception("모든 모델 로딩 방법이 실패했습니다.")
            
            # TensorFlow 성능 최적화 설정
            tf.config.optimizer.set_jit(True)  # XLA JIT 컴파일 활성화
            
            # 모델 warming up (첫 번째 예측 시 느린 속도 방지)
            dummy_input = np.zeros((1, self.MAX_SEQ_LENGTH, 675))
            _ = self.model.predict(dummy_input, verbose=0)
            logger.info("모델 warming up 완료")
            
        except Exception as e:
            logger.error(f"모델 로딩 실패: {e}")
            raise
        
        # 시퀀스 버퍼 (클라이언트별로 관리)
        self.client_sequences = {}  # {client_id: deque}
        
        # 분류 상태 (클라이언트별로 관리)
        self.client_states = {}  # {client_id: {prediction, confidence, is_processing}}
        
        # 벡터 카운터 (클라이언트별)
        self.client_vector_counters = {}  # {client_id: vector_count}
        
        # 분류 결과 버퍼 (클라이언트별로 관리) - 15개 프레임의 분류 결과를 저장
        self.client_result_buffers = {}  # {client_id: deque(maxlen=15)}
        
        # 분류 통계
        self.classification_count = 0
        self.last_log_time = 0
        self.log_interval = 1.0  # 1초마다 로그 출력 (너무 빈번한 로그 방지)
        
        # 시퀀스 관리 (클라이언트별로 관리)
        self.client_sequence_managers = {}  # {client_id: {last_prediction, same_count}}
    
    def load_model_info(self, model_info_url):
        """모델 정보 파일을 로드합니다."""
        try:
            # S3 URL인지 확인
            if model_info_url.startswith('s3://'):
                logger.info(f"📁 S3에서 모델 정보 파일 다운로드 중: {model_info_url}")
                
                # S3에서 파일 다운로드
                local_path = s3_utils.download_file_from_s3(model_info_url)
                model_info_url = local_path
                logger.info(f"✅ S3 파일 다운로드 완료: {local_path}")
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
            
            logger.info(f"📁 모델 정보 파일 경로: {model_info_url}")
            
            # 파일 존재 여부 확인 (S3에서 다운로드한 경우는 이미 존재함)
            if not model_info_url.startswith('s3://') and not os.path.exists(model_info_url):
                logger.error(f"❌ 모델 정보 파일을 찾을 수 없습니다: {model_info_url}")
                return None
            
            with open(model_info_url, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ 모델 정보 파일 로드 실패: {e}")
            return None
    
    def get_client_id(self, connection):
        """클라이언트 ID 생성"""
        return f"{connection.remote_address[0]}:{connection.remote_address[1]}"
    
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
            self.client_vector_counters[client_id] = 0
            # 분류 결과 버퍼 초기화
            self.client_result_buffers[client_id] = deque(maxlen=self.result_buffer_size)
        logger.info(f"클라이언트 초기화: {client_id}")
    
    def cleanup_client(self, client_id):
        """클라이언트 정리"""
        if client_id in self.client_sequences:
            del self.client_sequences[client_id]
        if client_id in self.client_states:
            del self.client_states[client_id]
        if client_id in self.client_sequence_managers:
            del self.client_sequence_managers[client_id]
        if client_id in self.client_vector_counters:
            del self.client_vector_counters[client_id]
        if client_id in self.client_result_buffers:
            del self.client_result_buffers[client_id]
        
        # 벡터 처리 모드에서는 별도 정리 작업 없음
        
        logger.info(f"클라이언트 정리: {client_id}")
    
    def validate_landmarks_data(self, landmarks_data):
        """랜드마크 데이터 유효성 검사"""
        try:
            # 필수 키 확인
            required_keys = ["pose", "left_hand", "right_hand"]
            for key in required_keys:
                if key not in landmarks_data:
                    logger.warning(f"누락된 랜드마크 키: {key}")
                    return False
            
            # 데이터 형식 확인
            for key in required_keys:
                data = landmarks_data[key]
                if data is not None:
                    # 리스트 형태인지 확인
                    if not isinstance(data, list):
                        logger.warning(f"잘못된 데이터 형식 - {key}: 리스트가 아님")
                        return False
                    
                    # 각 랜드마크가 3차원 좌표인지 확인
                    for i, landmark in enumerate(data):
                        if not isinstance(landmark, list) or len(landmark) != 3:
                            logger.warning(f"잘못된 랜드마크 형식 - {key}[{i}]: 3차원 좌표가 아님")
                            return False
            
            return True
            
        except Exception as e:
            logger.error(f"랜드마크 데이터 검증 실패: {e}")
            return False
    
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
            logger.info(f"동적특성 추출 성능:")
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
            pose_landmarks = frame["pose"]
            
            # MediaPipe 객체인지 리스트인지 확인
            if hasattr(pose_landmarks, 'landmark'):
                # MediaPipe 객체인 경우 (기존 방식)
                left_shoulder = pose_landmarks.landmark[11]
                right_shoulder = pose_landmarks.landmark[12]
                shoulder_center_x = (left_shoulder.x + right_shoulder.x) / 2
                shoulder_center_y = (left_shoulder.y + right_shoulder.y) / 2
                shoulder_center_z = (left_shoulder.z + right_shoulder.z) / 2
                shoulder_width = abs(right_shoulder.x - left_shoulder.x)
            else:
                # 리스트인 경우 (프론트엔드에서 전송된 데이터)
                left_shoulder = pose_landmarks[11]  # [x, y, z]
                right_shoulder = pose_landmarks[12]  # [x, y, z]
                shoulder_center_x = (left_shoulder[0] + right_shoulder[0]) / 2
                shoulder_center_y = (left_shoulder[1] + right_shoulder[1]) / 2
                shoulder_center_z = (left_shoulder[2] + right_shoulder[2]) / 2
                shoulder_width = abs(right_shoulder[0] - left_shoulder[0])
            
            if shoulder_width == 0:
                shoulder_width = 1.0
            shoulder_calc_time += time.time() - shoulder_start
            
            new_frame = {}
            
            # 포즈 랜드마크 처리
            if frame["pose"]:
                pose_start = time.time()
                relative_pose = []
                
                if hasattr(pose_landmarks, 'landmark'):
                    # MediaPipe 객체인 경우
                    for landmark in pose_landmarks.landmark:
                        rel_x = (landmark.x - shoulder_center_x) / shoulder_width
                        rel_y = (landmark.y - shoulder_center_y) / shoulder_width
                        rel_z = (landmark.z - shoulder_center_z) / shoulder_width
                        relative_pose.append([rel_x, rel_y, rel_z])
                else:
                    # 리스트인 경우
                    for landmark in pose_landmarks:
                        rel_x = (landmark[0] - shoulder_center_x) / shoulder_width
                        rel_y = (landmark[1] - shoulder_center_y) / shoulder_width
                        rel_z = (landmark[2] - shoulder_center_z) / shoulder_width
                        relative_pose.append([rel_x, rel_y, rel_z])
                
                new_frame["pose"] = relative_pose
                pose_calc_time += time.time() - pose_start
            
            # 손 랜드마크 처리
            hand_start = time.time()
            for hand_key in ["left_hand", "right_hand"]:
                if frame[hand_key]:
                    relative_hand = []
                    hand_landmarks = frame[hand_key]
                    
                    if hasattr(hand_landmarks, 'landmark'):
                        # MediaPipe 객체인 경우
                        for landmark in hand_landmarks.landmark:
                            rel_x = (landmark.x - shoulder_center_x) / shoulder_width
                            rel_y = (landmark.y - shoulder_center_y) / shoulder_width
                            rel_z = (landmark.z - shoulder_center_z) / shoulder_width
                            relative_hand.append([rel_x, rel_y, rel_z])
                    else:
                        # 리스트인 경우
                        for landmark in hand_landmarks:
                            rel_x = (landmark[0] - shoulder_center_x) / shoulder_width
                            rel_y = (landmark[1] - shoulder_center_y) / shoulder_width
                            rel_z = (landmark[2] - shoulder_center_z) / shoulder_width
                            relative_hand.append([rel_x, rel_y, rel_z])
                    
                    new_frame[hand_key] = relative_hand
                else:
                    new_frame[hand_key] = None
            hand_calc_time += time.time() - hand_start
            
            relative_landmarks.append(new_frame)
        
        total_time = time.time() - start_time
        
        # 성능 프로파일링 출력 (20ms 이상 걸리는 경우만)
        if self.enable_profiling and total_time > 0.02:
            logger.info(f"상대좌표 변환 성능:")
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
                        # 이미 리스트 형태인 경우 (프론트엔드에서 전송된 데이터)
                        combined.extend(frame[key])
                    else:
                        # MediaPipe 객체인 경우
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
            logger.info(f"랜드마크 전처리 성능:")
            logger.info(f"   전체: {total_time*1000:.1f}ms")
            logger.info(f"   상대좌표: {relative_time*1000:.1f}ms")
            logger.info(f"   프레임처리: {processing_time*1000:.1f}ms")
            logger.info(f"   정규화: {normalize_time*1000:.1f}ms")
            logger.info(f"   동적특성: {dynamic_time*1000:.1f}ms")
        
        return sequence
    
    def add_result_to_buffer(self, result, client_id):
        """분류 결과를 버퍼에 추가"""
        self.client_result_buffers[client_id].append(result)
    
    def calculate_averaged_result(self, client_id):
        """버퍼의 분류 결과들의 평균을 계산"""
        buffer = self.client_result_buffers[client_id]
        if not buffer:
            return None
        
        # 모든 라벨에 대한 확률 합계 초기화
        total_probabilities = {}
        for label in self.ACTIONS:
            total_probabilities[label] = 0.0
        
        # 버퍼의 모든 결과에서 확률 합계 계산
        for result in buffer:
            for label, prob in result['probabilities'].items():
                total_probabilities[label] += prob
        
        # 평균 확률 계산
        buffer_size = len(buffer)
        avg_probabilities = {}
        for label in self.ACTIONS:
            avg_probabilities[label] = total_probabilities[label] / buffer_size
        
        # 평균 확률이 가장 높은 라벨 찾기
        best_label = max(avg_probabilities, key=avg_probabilities.get)
        best_confidence = avg_probabilities[best_label]
        
        # 평균 결과 생성
        averaged_result = {
            "prediction": best_label,
            "confidence": best_confidence,
            "probabilities": avg_probabilities,
            "buffer_size": buffer_size  # 디버깅용 정보
        }
        
        return averaged_result
    
    def log_classification_result(self, result, client_id):
        """분류 결과를 로그로 출력"""
        current_time = asyncio.get_event_loop().time()
        
        # 로그 출력 주기 제한 (너무 빈번한 로그 방지)
        if current_time - self.last_log_time >= self.log_interval:
            # 디버그 모드에서 버퍼 정보 출력
            if self.debug_mode and 'buffer_size' in result:
                logger.info(f"[{client_id}] 예측: {result['prediction']} (신뢰도: {result['confidence']:.3f}, 버퍼크기: {result['buffer_size']})")
            else:
                logger.info(f"[{client_id}] 예측: {result['prediction']} (신뢰도: {result['confidence']:.3f})")

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
    
    def process_landmarks(self, landmarks_data, client_id):
        """랜드마크 벡터 처리 및 분류 (성능 최적화 + 프로파일링)"""
        process_start_time = time.time()
        
        # 벡터 카운터 증가
        self.client_vector_counters[client_id] += 1
        vector_count = self.client_vector_counters[client_id]
        
        # 이미 처리 중인 경우 스킵
        if self.client_states[client_id]["is_processing"]:
            return None
        
        self.client_states[client_id]["is_processing"] = True
        
        # 성능 측정 변수들
        preprocessing_time = 0
        prediction_time = 0
        
        try:
            # 1. 랜드마크 데이터 유효성 검사
            if not self.validate_landmarks_data(landmarks_data):
                logger.warning(f"[{client_id}] 잘못된 랜드마크 데이터")
                return None
            
            # 2. 랜드마크 데이터 수집
            landmarks_list = []
            landmarks_list.append({
                "pose": landmarks_data["pose"],
                "left_hand": landmarks_data["left_hand"],
                "right_hand": landmarks_data["right_hand"]
            })
            
            # 시퀀스에 추가
            self.client_sequences[client_id].extend(landmarks_list)
            
            # 3. 예측 실행 빈도 제한 (성능 향상)
            should_predict = (
                len(self.client_sequences[client_id]) >= self.MAX_SEQ_LENGTH and
                vector_count % self.prediction_interval == 0
            )
            
            # should_predict = False
            
            result = None
            if should_predict:
                # 4. 랜드마크 전처리 (예측할 때만)
                preprocessing_start = time.time()
                sequence = self.improved_preprocess_landmarks(list(self.client_sequences[client_id]))
                preprocessing_time = time.time() - preprocessing_start
                
                # 5. 모델 예측
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
                
                # 분류 결과를 버퍼에 추가
                self.add_result_to_buffer(result, client_id)
                
                # 버퍼의 평균 결과 계산
                averaged_result = self.calculate_averaged_result(client_id)
                
                # 클라이언트 상태 업데이트 (평균 결과 기준)
                if averaged_result:
                    self.client_states[client_id]["prediction"] = averaged_result["prediction"]
                    self.client_states[client_id]["confidence"] = averaged_result["confidence"]
                    
                    # 평균 결과를 로그로 출력
                    self.log_classification_result(averaged_result, client_id)
                    
                    # 평균 결과 반환
                    result = averaged_result
            
            # 성능 프로파일링 출력
            total_time = time.time() - process_start_time
            
            # 성능 통계 업데이트
            self.performance_stats['total_vectors'] += 1
            if preprocessing_time > 0:
                self.performance_stats['avg_preprocessing_time'] = (
                    (self.performance_stats['avg_preprocessing_time'] * (self.performance_stats['total_vectors'] - 1) + preprocessing_time) /
                    self.performance_stats['total_vectors']
                )
            if prediction_time > 0:
                self.performance_stats['avg_prediction_time'] = (
                    (self.performance_stats['avg_prediction_time'] * (self.performance_stats['total_vectors'] - 1) + prediction_time) /
                    self.performance_stats['total_vectors']
                )
            if total_time > self.performance_stats['max_processing_time']:
                self.performance_stats['max_processing_time'] = total_time
                # 병목 컴포넌트 식별
                times = {
                    'preprocessing': preprocessing_time,
                    'prediction': prediction_time,
                }
                self.performance_stats['bottleneck_component'] = max(times, key=times.get)
            
            # 성능 프로파일링 출력 (프로파일링 모드가 활성화된 경우)
            if self.enable_profiling and total_time > 0.05:  # 50ms 이상 걸리는 경우만 로그
                logger.info(f"[{client_id}] 프레임 #{self.performance_stats['total_vectors']}: {total_time*1000:.1f}ms (전처리:{preprocessing_time*1000:.1f}ms, 예측:{prediction_time*1000:.1f}ms)")
                # 100프레임마다 성능 요약 출력
                if self.performance_stats['total_vectors'] % 100 == 0:
                    logger.info(f"성능 요약 (100벡터 평균):")
                    logger.info(f"   평균 전처리: {self.performance_stats['avg_preprocessing_time']*1000:.1f}ms")
                    logger.info(f"   평균 예측: {self.performance_stats['avg_prediction_time']*1000:.1f}ms")
                    logger.info(f"   최대 프레임 시간: {self.performance_stats['max_processing_time']*1000:.1f}ms")
                    logger.info(f"   주요 병목: {self.performance_stats['bottleneck_component']}")
            
            # 디버그 모드에서는 간단한 성능 정보만 출력
            elif self.debug_mode and total_time > 0.1:  # 100ms 이상 걸리는 경우만 로그
                logger.info(f"[{client_id}] 느린 벡터 감지: {total_time*1000:.1f}ms")
            
            return result
                
        except Exception as e:
            logger.error(f"예측 실패: {e}")
            return None
        finally:
            self.client_states[client_id]["is_processing"] = False
    
    async def handle_client(self, websocket):
        """클라이언트 연결 처리"""
        client_id = self.get_client_id(websocket)
        
        self.clients.add(websocket)
        self.initialize_client(client_id)

        # 만약 종료 대기 태스크가 있다면 취소
        if self.shutdown_task is not None and not self.shutdown_task.done():
            logger.info("[WS] 새 클라이언트 접속: 종료 대기 취소")
            self.shutdown_task.cancel()
            self.shutdown_task = None

        logger.info(f"[WS] 클라이언트 연결됨: {client_id}")
        logger.info(f"[WS] 기대 메시지 포맷: JSON with 'type': 'landmarks' or 'landmarks_sequence'")

        try:
            async for message in websocket:
                logger.info(f"[WS] [{client_id}] 메시지 수신: {str(message)[:200]}")
                try:
                    # 메시지 타입 확인 (텍스트 또는 바이너리)
                    if isinstance(message, bytes):
                        logger.warning(f"[WS] [{client_id}] 바이너리 메시지 수신됨 (길이: {len(message)} bytes) - 지원하지 않음")
                        try:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "바이너리 메시지는 지원되지 않습니다. JSON 형식의 랜드마크 데이터를 전송해주세요."
                            }))
                        except:
                            pass
                        continue

                    data = json.loads(message)
                    logger.info(f"[WS] [{client_id}] 파싱된 데이터: {data}")

                    if data.get("type") == "landmarks":
                        landmarks_data = data.get("data")
                        if landmarks_data:
                            logger.info(f"[WS] [{client_id}] landmarks 데이터 수신 및 처리 시작")
                            result = self.process_landmarks(landmarks_data, client_id)
                            logger.info(f"[WS] [{client_id}] landmarks 예측 결과: {result}")
                            if result:
                                response = {
                                    "type": "classification_result",
                                    "data": result,
                                    "timestamp": asyncio.get_event_loop().time()
                                }
                                logger.info(f"[WS] [{client_id}] landmarks 결과 전송: {response}")
                                await websocket.send(json.dumps(response))
                        else:
                            logger.warning(f"[WS] [{client_id}] 빈 landmarks 데이터")

                    elif data.get("type") == "landmarks_sequence":
                        sequence_data = data.get("data")
                        if sequence_data and "sequence" in sequence_data:
                            sequence = sequence_data["sequence"]
                            frame_count = sequence_data.get("frame_count", len(sequence))
                            timestamp = sequence_data.get("timestamp", asyncio.get_event_loop().time())
                            logger.info(f"[WS] [{client_id}] landmarks_sequence 수신: {frame_count}개 프레임")
                            # 시퀀스의 각 프레임을 처리
                            for i, landmarks_data in enumerate(sequence):
                                logger.info(f"[WS] [{client_id}] 시퀀스 프레임 {i} 처리 시작")
                                result = self.process_landmarks(landmarks_data, client_id)
                                logger.info(f"[WS] [{client_id}] 시퀀스 프레임 {i} 예측 결과: {result}")
                                if result:
                                    response = {
                                        "type": "classification_result",
                                        "data": result,
                                        "timestamp": timestamp + (i * 16.67),  # 60fps 기준
                                        "frame_index": i
                                    }
                                    logger.info(f"[WS] [{client_id}] 시퀀스 프레임 {i} 결과 전송: {response}")
                                    await websocket.send(json.dumps(response))
                        else:
                            logger.warning(f"[WS] [{client_id}] 잘못된 landmarks_sequence 데이터")

                    elif data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))

                    else:
                        logger.warning(f"[WS] [{client_id}] 알 수 없는 메시지 타입: {data.get('type')}")

                except json.JSONDecodeError:
                    logger.warning(f"[WS] 잘못된 JSON 메시지: {client_id}")
                except UnicodeDecodeError as e:
                    logger.warning(f"[WS] UTF-8 디코딩 오류 [{client_id}]: {e} - 바이너리 데이터가 텍스트로 전송됨")
                except Exception as e:
                    logger.error(f"[WS] 메시지 처리 실패 [{client_id}]: {e}")
                    try:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "랜드마크 처리 중 오류가 발생했습니다."
                        }))
                    except:
                        pass

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[WS] 클라이언트 연결 종료: {client_id}")
        except websockets.exceptions.ConnectionClosedError:
            logger.info(f"[WS] 클라이언트 연결 오류로 종료: {client_id}")
        except Exception as e:
            logger.error(f"[WS] 클라이언트 처리 중 오류 [{client_id}]: {e}")
            import traceback
            logger.error(f"[WS] 상세 오류 정보: {traceback.format_exc()}")
        finally:
            try:
                self.clients.remove(websocket)
                self.cleanup_client(client_id)
                if not self.clients:
                    logger.info("[WS] 모든 클라이언트 연결 종료됨. 20초 후 서버 프로세스 종료 예정.")
                    loop = asyncio.get_event_loop()
                    self.shutdown_task = loop.create_task(self.delayed_shutdown())
            except Exception as cleanup_error:
                logger.error(f"[WS] 클라이언트 정리 중 오류 [{client_id}]: {cleanup_error}")

    async def delayed_shutdown(self):
        """20초 후 서버 종료 (새 클라이언트 접속 시 취소 가능)"""
        try:
            await asyncio.sleep(20)
            if not self.clients:
                logger.info("[WS] 20초 대기 후에도 클라이언트 없음. 서버 프로세스 종료.")
                os._exit(0)
            else:
                logger.info("[WS] 20초 대기 중 새 클라이언트 접속. 종료 취소.")
        except asyncio.CancelledError:
            logger.info("[WS] 종료 대기 태스크가 취소되었습니다.")
    
    async def run_server(self):
        """WebSocket 서버 실행"""
        server = await websockets.serve(
            self.handle_client, 
            self.host, 
            self.port
        )
        logger.info(f"수어 분류 WebSocket 서버 시작: ws://{self.host}:{self.port}")
        logger.info(f"서버 정보:")
        logger.info(f"   - 호스트: {self.host}")
        logger.info(f"   - 포트: {self.port}")
        logger.info(f"   - 모델: {self.MODEL_SAVE_PATH}")
        logger.info(f"   - 라벨 수: {len(self.ACTIONS)}")
        logger.info(f"   - 시퀀스 길이: {self.MAX_SEQ_LENGTH}")
        logger.info(f"   - 디버그 모드: {self.debug_mode}")
        logger.info(f"성능 최적화 설정:")
        logger.info(f"   - 예측 간격: {self.prediction_interval}벡터마다 예측")
        logger.info(f"   - 결과 버퍼 크기: {self.result_buffer_size}개 프레임")
        logger.info(f"   - TensorFlow XLA JIT: 활성화")
        logger.info(f"   - Performance profiling: {self.enable_profiling}")
        logger.info(f"벡터 처리 모드 - JSON 랜드마크 데이터만 지원")
        logger.info(f"결과 버퍼링 모드 - {self.result_buffer_size}개 프레임의 분류 결과를 평균화하여 전송")
        logger.info(f"Starting server with optimized settings...")
        
        try:
            await server.wait_closed()
        except KeyboardInterrupt:
            logger.info(" 서버 종료 중...")
        finally:
            # 벡터 처리 모드에서는 별도 정리 작업 없음
            logger.info("🔄 벡터 처리 서버 종료 완료")

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
    
    parser = argparse.ArgumentParser(description='Sign Classifier WebSocket Server (Vector Processing Mode)')
    parser.add_argument("--port", type=int, required=True, help="Port number for the server")
    parser.add_argument("--env", type=str, required=True, help="Environment variable model_info_URL")
    parser.add_argument("--host", type=str, default="localhost", help="Host to bind the server to (default: localhost)")
    parser.add_argument("--log-level", type=str, default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'OFF'],
                       help="Set logging level (default: INFO, use OFF to disable all logs)")
    parser.add_argument("--debug", action='store_true',
                       help="Enable debug mode for additional logging")
    parser.add_argument("--prediction-interval", type=int, default=5,
                       help="Prediction interval (run prediction every N vectors, default: 5)")
    parser.add_argument("--result-buffer-size", type=int, default=6,
                       help="Result buffer size (number of frames to average, default: 15)")
    parser.add_argument("--profile", action='store_true',
                       help="Enable detailed performance profiling")
    args = parser.parse_args()
    
    port = args.port
    model_info_url = args.env
    host = args.host
    log_level = args.log_level
    debug_mode = args.debug
    prediction_interval = args.prediction_interval
    result_buffer_size = args.result_buffer_size
    enable_profiling = args.profile
    
    # 로깅 설정 (동적으로 설정)
    global logger
    logger = setup_logging(log_level)
    
    # 로그가 꺼져있지 않은 경우에만 시작 메시지 출력 (이모지 제거)
    if log_level.upper() != 'OFF':
        print(f"Starting sign classifier WebSocket server (Vector Processing Mode)...")
        print(f"Model data URL: {model_info_url}")
        print(f"Port: {port}")
        print(f"Log level: {log_level}")
        print(f"Debug mode: {debug_mode}")
        print(f"Performance settings:")
        print(f"   - Prediction interval: {prediction_interval}")
        print(f"   - Result buffer size: {result_buffer_size}")
        print(f"   - Performance profiling: {enable_profiling}")
        print(f"Vector processing mode - MediaPipe processing moved to frontend")
        print(f"Starting server with optimized vector processing...")
    
    # 현재 스크립트 파일의 위치를 기준으로 프로젝트 루트 계산
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # src/services에서 프로젝트 루트로 이동 (2단계 상위)
    project_root = os.path.dirname(os.path.dirname(current_dir))
    
    # 파일명만 전달된 경우 s3://waterandfish-s3/model-info/ 디렉터리에서 찾기
    model_info_url_processed = model_info_url
    if os.path.basename(model_info_url) == model_info_url:
        # 파일명만 전달된 경우
        model_info_url_processed = f"s3://waterandfish-s3/model-info/{model_info_url}"
    
    logger.info(f"원본 모델 데이터 URL: {model_info_url}")
    logger.info(f"처리된 모델 데이터 경로: {model_info_url_processed}")
    logger.info(f"포트: {port}")
    
    # S3 URL인지 확인
    if model_info_url_processed.startswith('s3://'):
        logger.info(f"S3 모델 경로 확인됨: {model_info_url_processed}")
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
        
        logger.info(f"로컬 모델 정보 파일 확인됨: {model_info_url_full}")
    
    # 서버 생성 및 실행
    # localhost should be changed to the server's IP address when deploying to a server
    server = SignClassifierWebSocketServer(
        model_info_url_processed, 
        host="0.0.0.0", 
        port=port,
        debug_mode=debug_mode,
        prediction_interval=prediction_interval,
        enable_profiling=enable_profiling,
        result_buffer_size=result_buffer_size
    )
    
    # 디버그 모드 활성화 시 알림
    if debug_mode:
        logger.info("디버그 모드 활성화 - 추가 로깅 정보가 출력됩니다")
        logger.info("   - 벡터 처리 성능 정보")
        logger.info("   - 랜드마크 데이터 유효성 검사 결과")
        logger.info("   - 클라이언트별 상세 처리 정보")
        logger.info("   - 분류 결과 버퍼링 정보")
    
    asyncio.run(server.run_server())

if __name__ == "__main__":
    main() 
