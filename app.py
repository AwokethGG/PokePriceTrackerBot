from flask import Flask, request
import os

app = Flask(__name__)
VERIFICATION_TOKEN = "gradingbot123securetokenverysecure"  # Must match eBay portal token

@app.route('/ebay-deletion-notify', methods=['POST'])
def ebay_deletion_notify():
    data = request.json
    if data and data.get('verification_token') == VERIFICATION_TOKEN:
        print("✅ eBay account deletion verification successful.")
        return "Token verified", 200
    else:
        print("❌ eBay account deletion verification failed.")
        return "Invalid token", 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
