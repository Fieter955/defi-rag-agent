import firebase_admin
from firebase_admin import credentials, firestore, auth


#Ini adalah fungsi untuk inisialisasi database yaitu "firebase"
def init_firebase():
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Koneksi ke Firebase Firestore berhasil.")
        return db
    except Exception as e:
        print(f"Error koneksi ke Firebase: {e}")
        return None, None
