import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from django.conf import settings

def verify_play_integrity_token(integrity_token, package_name="com.piyush123abc.attendance_app"):
    # Pointing to the root where your play-integrity-key.json is sitting
    key_path = os.path.join(settings.BASE_DIR, 'play-integrity-key.json')

    if not os.path.exists(key_path):
        print(f"⚠️ [DEBUG] Key not found at: {key_path}")
        return False

    try:
        credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=['https://www.googleapis.com/auth/playintegrity']
        )

        service = build('playintegrity', 'v1', credentials=credentials)

        request_body = {'integrityToken': integrity_token}
        
        response = service.v1().decodeIntegrityToken(
            packageName=package_name,
            body=request_body
        ).execute()

        token_payload = response.get('tokenPayloadExternal', {})
        app_integrity = token_payload.get('appIntegrity', {})
        verdict = app_integrity.get('appRecognitionVerdict')

        if verdict == 'PLAY_RECOGNIZED':
            return True
        
        print(f"❌ [SECURITY] Integrity Failed! Verdict: {verdict}")
        return False

    except Exception as e:
        print(f"⚠️ [DEBUG] Play Integrity Error: {e}")
        return False