from firebase_admin import messaging

def send_fcm_notification(fcm_tokens, title, body, data_payload=None):
    """
    Sends a push notification to a list of FCM tokens.
    """
    # Clean the token list (remove empty/None values)
    valid_tokens = [token for token in fcm_tokens if token]

    if not valid_tokens:
        print("⚠️ FCM: No valid tokens provided, skipping.")
        return {"success": 0, "failure": 0, "message": "No valid tokens"}

    # Construct the message with high priority for the system tray
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data_payload if data_payload else {}, 
        tokens=valid_tokens,
        android=messaging.AndroidConfig(
            priority='high', # Ensures it pops up immediately in the tray
            notification=messaging.AndroidNotification(
                sound='default',
                click_action='FLUTTER_NOTIFICATION_CLICK', # Helps open the app
            ),
        ),
    )

    try:
        # Send the message
        response = messaging.send_each_for_multicast(message)
        print(f"📡 FCM Broadcast: {response.success_count} success, {response.failure_count} failed.")
        return {
            "success": response.success_count,
            "failure": response.failure_count
        }
    except Exception as e:
        print(f"❌ FCM Broadcast Failed: {e}")
        return {"success": 0, "failure": 0, "error": str(e)}