from flask import Flask, request
import os

app = Flask(__name__)
VERIFICATION_TOKEN = "gradingbot123securetokenverysecure"  # Must match eBay portal token

@app.route('/ebay-deletion-notify', methods=['GET', 'POST'])
def ebay_deletion_notify():
    if request.method == 'POST':
        data = request.json
        if data and data.get('verification_token') == VERIFICATION_TOKEN:
            print("✅ eBay account deletion verification successful.")
            return "Token verified", 200
        else:
            print("❌ eBay account deletion verification failed.")
            return "Invalid token", 400
    else:
        # For GET requests, just return a simple 200 OK or some info
        return "eBay webhook endpoint active", 200
