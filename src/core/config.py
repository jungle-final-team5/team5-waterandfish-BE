from pydantic_settings import BaseSettings
from typing import List
from pydantic import Field
import os

class Settings(BaseSettings):
    # CORS 설정 (쉼표로 구분된 문자열)
    CORS_ORIGINS: str = Field("http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173", env="CORS_ORIGINS")
    root_path: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 프론트엔드 URL 설정 (배포 환경용)
    FRONTEND_URL: str = Field("http://localhost:5173", env="FRONTEND_URL")

    # JWT 설정
    SECRET_KEY: str = Field("", env="SECRET_KEY")
    ALGORITHM: str = Field("HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(30, env="ACCESS_TOKEN_EXPIRE_MINUTES")

    # Google OAuth2 설정
    GOOGLE_CLIENT_ID: str = Field("", env="GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str = Field("", env="GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = Field("", env="GOOGLE_REDIRECT_URI")

    # Kakao OAuth2 설정
    KAKAO_CLIENT_ID: str = Field("", env="KAKAO_CLIENT_ID")
    KAKAO_CLIENT_SECRET: str = Field("", env="KAKAO_CLIENT_SECRET")
    KAKAO_REDIRECT_URI: str = Field("", env="KAKAO_REDIRECT_URI")

    # MongoDB 설정
    MONGODB_URL: str = Field("", env="MONGODB_URL")
    DATABASE_NAME: str = Field("waterandfish", env="DATABASE_NAME")
    
    # AWS S3 설정
    AWS_ACCESS_KEY_ID: str = Field("", env="AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str = Field("", env="AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str = Field("ap-northeast-2", env="AWS_REGION")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origins_list(self) -> List[str]:
        """CORS origins를 리스트로 반환"""
        if isinstance(self.CORS_ORIGINS, str):
            origins = []
            # 대괄호 제거하고 쉼표로 분리
            cors_str = self.CORS_ORIGINS.strip("[]").replace('"', '').replace("'", "")
            for origin in cors_str.split(","):
                origin = origin.strip()
                if origin:  # 빈 문자열 제외
                    origins.append(origin)
            return origins
        return self.CORS_ORIGINS if isinstance(self.CORS_ORIGINS, list) else [self.CORS_ORIGINS]

settings = Settings()