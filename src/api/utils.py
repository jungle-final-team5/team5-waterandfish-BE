from fastapi import Request, HTTPException, status, Cookie
from bson import ObjectId
from jose import jwt, JWTError
from ..core.config import settings

def convert_objectid(doc):
    """ObjectId를 JSON에 맞게 문자열로 변환"""
    if isinstance(doc, list):
        return [convert_objectid(item) for item in doc]
    elif isinstance(doc, dict):
        new_doc = {}
        for key, value in doc.items():
            if key == "_id":
                new_doc["id"] = str(value)
            elif isinstance(value, ObjectId):
                new_doc[key] = str(value)
            else:
                new_doc[key] = convert_objectid(value)
        return new_doc
    return doc

def get_user_id_from_token(request: Request, access_token: str = Cookie(None)):
    """토큰에서 user_id 추출"""
    # access_token이 Cookie 객체인지 문자열인지 확인
    if access_token and hasattr(access_token, 'value'):
        token = access_token.value
    elif access_token and isinstance(access_token, str):
        token = access_token
    else:
        token = request.cookies.get("access_token")
    
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

def require_auth(request: Request, access_token: str = Cookie(None)):
    """인증이 필요한 엔드포인트용"""
    user_id = get_user_id_from_token(request, access_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Authentication required"
        )
    return user_id

def validate_object_id(id_str: str, field_name: str = "ID"):
    """ObjectId 유효성 검사"""
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid {field_name}"
        )

def create_success_response(data=None, message: str = "Success"):
    """성공 응답 생성"""
    response = {
        "success": True,
        "message": message
    }
    if data is not None:
        response["data"] = data
    return response

def create_error_response(message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
    """에러 응답 생성"""
    raise HTTPException(
        status_code=status_code,
        detail=message
    ) 