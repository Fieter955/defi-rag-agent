from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

security = HTTPBearer()

#Ini adalah fungsi untuk mendapatkan id user yang sedang login sehingga proses disemua endpoint selalu dipastikan kecocokan id sesuai di database. Atau singkatnya Memvalidasi Bearer Token dari header Authorization menggunakan Firebase Admin
def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    print(creds)
    if not creds or creds.scheme != "Bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Skema autentikasi salah, gunakan Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = creds.credentials
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid atau kadaluwarsa.",
            headers={"WWW-Authenticate": "Bearer"},
        )