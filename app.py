from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)
VERIFICATION_TOKEN = "gradingbot123securetokenverysecure"  # 32-80 chars alphanumeric + _ and -
ENDPOINT_PATH = '/ebay-deletion-notify'  # Must match the registered endpoint path exactly

@app.route(ENDPOINT_PATH, methods=['GET', 'POST'])
def ebay_deletion_notify():
    if request.method == 'GET':
        # Extract the challenge code from query parameters
        challenge_code = request.args.get('challenge_code')
        if not challenge_code:
            return "Missing challenge_code", 400

        # Compute SHA-256 hash as hex digest
        to_hash = challenge_code + VERIFICATION_TOKEN + ENDPOINT_PATH
        challenge_response = hashlib.sha256(to_hash.encode('utf-8')).hexdigest()

        # Return JSON with challengeResponse key, status 200, correct content-type
        return jsonify({"challengeResponse": challenge_response}), 200

    elif request.method == 'POST':
        # Here handle actual notifications from eBay after verification
        data = request.json or {}
        # You can verify your verification token or other logic here
        token_valid = data.get('verification_token') == VERIFICATION_TOKEN
        if token_valid:
            print("✅ eBay account deletion notification received and verified.")
            # process deletion notification
            return "Notification processed", 200
        else:
            print("❌ Invalid verification token in POST notification.")
            return "Invalid token", 400

    else:
        return "Method not allowed", 405

if __name__ == '__main__':
    app.run()
