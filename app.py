from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)

# Your secret verification token (32-80 chars, only alnum, underscore, hyphen)
VERIFICATION_TOKEN = "gradingbot123securetokenverysecure"
# This must exactly match the path portion of your endpoint URL
ENDPOINT_PATH = '/ebay-deletion-notify'

@app.route(ENDPOINT_PATH, methods=['GET', 'POST'])
def ebay_deletion_notify():
    if request.method == 'GET':
        challenge_code = request.args.get('challenge_code')
        if not challenge_code:
            return jsonify({"error": "Missing challenge_code"}), 400

        # Compute SHA-256 hash of challenge_code + verification_token + endpoint_path
        to_hash = challenge_code + VERIFICATION_TOKEN + ENDPOINT_PATH
        challenge_response = hashlib.sha256(to_hash.encode('utf-8')).hexdigest()

        # Return JSON with no BOM and correct content-type using jsonify
        return jsonify({"challengeResponse": challenge_response}), 200

    elif request.method == 'POST':
        # Your webhook notification handling here
        data = request.json or {}
        if data.get('verification_token') == VERIFICATION_TOKEN:
            print("✅ Verified eBay notification received.")
            # Process your notification logic here
            return "Notification processed", 200
        else:
            print("❌ Invalid verification token in notification.")
            return "Invalid token", 400

    else:
        return jsonify({"error": "Method not allowed"}), 405


if __name__ == '__main__':
    # Run on port 8080 or your desired port
    app.run(host='0.0.0.0', port=8080)
