from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import jwt
import datetime
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import re
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)

# ================= DATABASE SETTINGS (FROM .ENV) =================
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASS', '')
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_NAME = os.getenv('DB_NAME', 'oxymora_sign')
DB_PORT = os.getenv('DB_PORT', '3307')
JWT_KEY = os.getenv('JWT_KEY', 'oxy_secret_786')
OTP_CODE = os.getenv('OTP_CODE', '0002')
MQTT_BROKER = os.getenv('MQTT_BROKER', 'otplcloud.com')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))

app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = JWT_KEY
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_recycle": 280,
    "pool_pre_ping": True,
}
db = SQLAlchemy(app)

# ================= DATABASE MODELS =================
class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    access_token = db.Column(db.String(500), nullable=True)
    # Account linking fields
    alexa_user_id = db.Column(db.String(255), unique=True, nullable=True)
    is_alexa_linked = db.Column(db.Boolean, default=False)

class DeviceType(db.Model):
    __tablename__ = 'device_types'
    type_id = db.Column(db.Integer, primary_key=True)
    type_name = db.Column(db.String(50), unique=True)

class Location(db.Model):
    __tablename__ = 'locations'
    loc_id = db.Column(db.Integer, primary_key=True)
    loc_name = db.Column(db.String(50), unique=True)

class Device(db.Model):
    __tablename__ = 'devices'
    device_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('device_types.type_id'), nullable=False)
    loc_id = db.Column(db.Integer, db.ForeignKey('locations.loc_id'), nullable=False)
    mac_address = db.Column(db.String(50), nullable=False)
    
    # Relationships for easier access
    user = db.relationship('User', backref='devices')
    device_type = db.relationship('DeviceType', backref='devices')
    location = db.relationship('Location', backref='devices')


# ================= MQTT SETUP =================
mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print("✅ MQTT Connected successfully!")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

connect_mqtt()

# ================= HELPER FUNCTIONS =================
def get_user_from_token(token):
    """Extract user from JWT token"""
    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(decoded['user_id'])
        return user
    except:
        return None

def generate_access_token(user_id):
    """Generate JWT token for user"""
    token_payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }
    return jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm='HS256')

# ================= ROUTES =================
@app.route('/')
def home():
    return "<h1>Oxy Backend is Live!</h1><p>Server is running perfectly.</p>"

# ================= AUTHENTICATION ROUTES =================
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    
    # 1. OTP Check (HARDCODED OTP from .env)
    if data.get('otp') != OTP_CODE:
        return jsonify({"success": False, "message": "Galat OTP! Data save nahi kiya gaya."}), 403

    # 2. Data extraction
    email = data.get('email', '').lower().strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    # 3. Validation
    if not email or not username or not password:
        return jsonify({"success": False, "message": "Sab fields zaroori hain!"}), 400
    
    # 4. Check if user already exists
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Email pehle se registered hai!"}), 400

    try:
        # 5. Password Encryption
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        
        new_user = User(
            username=username,
            email=email,
            password=hashed_pw
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Sahi OTP! User save ho gaya.",
            "user_id": new_user.user_id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/login', methods=['GET', 'POST']) # GET add kiya Alexa ke liye
def login():
    # --- CASE 1: Alexa Account Linking (GET Request) ---
    if request.method == 'GET':
        state = request.args.get('state')
        redirect_uri = request.args.get('redirect_uri')
        
        # Agar ye parameters hain, matlab user Alexa app se aaya hai
        if state and redirect_uri:
            return render_template('login.html', state=state, redirect_uri=redirect_uri)
        
        return "Invalid Linking Request", 400

    # --- CASE 2: Mobile App Login (POST Request with JSON) ---
    if request.is_json:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password')

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            access_token = generate_access_token(user.user_id)
            try:
                user.access_token = access_token
                db.session.commit()
                return jsonify({
                    "success": True,
                    "access_token": access_token,
                    "user_id": user.user_id,
                    "is_alexa_linked": user.is_alexa_linked
                }), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({"success": False, "message": "Token save error"}), 500
        
        return jsonify({"success": False, "message": "Invalid Email or Password!"}), 401

    # --- CASE 3: Alexa Form Submit (POST Request from HTML Form) ---
    else:
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password')
        state = request.form.get('state')
        redirect_uri = request.form.get('redirect_uri')

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            access_token = generate_access_token(user.user_id)
            # Alexa Implicit Grant flow: Token ko URL fragment (#) mein bhejte hain
            final_url = f"{redirect_uri}#state={state}&access_token={access_token}&token_type=Bearer"
            return redirect(final_url)
        
        return "Invalid Login. Please go back and try again.", 401

@app.route('/update-password', methods=['POST'])
def update_password():
    data = request.get_json()
    
    # OTP Check
    if data.get('otp') != OTP_CODE:
        return jsonify({"success": False, "message": "Invalid OTP! Update denied."}), 403

    email = data.get('email', '').lower().strip()
    new_password = data.get('new_password')

    if not new_password:
        return jsonify({"success": False, "message": "Naya password zaroori hai!"}), 400

    user = User.query.filter_by(email=email).first()
    if user:
        try:
            user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
            db.session.commit()
            return jsonify({"success": True, "message": "Password updated successfully!"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500
        
    return jsonify({"success": False, "message": "User nahi mila!"}), 404

# ================= ACCOUNT LINKING ROUTES =================
@app.route('/account-linking/auth-code', methods=['POST'])
def get_auth_code():
    """Alexa account linking step 1: Generate auth code"""
    data = request.get_json()
    email = data.get('email', '').lower().strip()
    password = data.get('password')
    
    user = User.query.filter_by(email=email).first()
    
    if user and bcrypt.check_password_hash(user.password, password):
        # Generate a random auth code (normally would be something more secure)
        auth_code = os.urandom(16).hex()
        
        # Store temporarily (in production, use Redis with TTL)
        # For now, we'll just use the user's token
        user.access_token = generate_access_token(user.user_id)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "auth_code": user.access_token,
            "message": "Auth code generated successfully"
        }), 200
    
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/account-linking/exchange-token', methods=['POST'])
def exchange_token():
    """Alexa account linking step 2: Exchange auth code for access token"""
    data = request.get_json()
    auth_code = data.get('auth_code')
    alexa_user_id = data.get('alexa_user_id')  # From Alexa API
    
    if not auth_code or not alexa_user_id:
        return jsonify({"success": False, "message": "Missing parameters"}), 400
    
    try:
        # Verify the auth code
        decoded = jwt.decode(auth_code, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(decoded['user_id'])
        
        if user:
            # Link Alexa account
            user.alexa_user_id = alexa_user_id
            user.is_alexa_linked = True
            db.session.commit()
            
            # Return access token for Alexa to use
            return jsonify({
                "success": True,
                "access_token": auth_code,
                "message": "Alexa account linked successfully"
            }), 200
    except Exception as e:
        print(f"Token exchange error: {e}")
    
    return jsonify({"success": False, "message": "Invalid auth code"}), 401

@app.route('/account-linking/status', methods=['GET'])
def linking_status():
    """Check if Alexa is linked"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    return jsonify({
        "success": True,
        "is_linked": user.is_alexa_linked,
        "username": user.username
    }), 200

@app.route('/account-linking/unlink', methods=['POST'])
def unlink_alexa():
    """Unlink Alexa account"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        user.is_alexa_linked = False
        user.alexa_user_id = None
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Alexa account unlinked successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# ================= DEVICE MANAGEMENT ROUTES =================
@app.route('/add_device', methods=['POST'])
def add_device():
    """Add device to user's account"""
    # Get user from token
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    # Get device details
    loc_raw = request.form.get('location')
    type_raw = request.form.get('device_type')
    mac_input = request.form.get('mac_address')

    if not all([loc_raw, type_raw, mac_input]):
        return jsonify({"success": False, "message": "Sab fields zaroori hain!"}), 400

    try:
        # Convert to lowercase
        loc_input = loc_raw.lower().strip()
        type_input = type_raw.lower().strip()

        # ✅ STEP 1: Get or create Location
        location = Location.query.filter_by(loc_name=loc_input).first()
        if not location:
            location = Location(loc_name=loc_input)
            db.session.add(location)
            db.session.flush()

        # ✅ STEP 2: Get or create Device Type
        device_type = DeviceType.query.filter_by(type_name=type_input).first()
        if not device_type:
            device_type = DeviceType(type_name=type_input)
            db.session.add(device_type)
            db.session.flush()

        # ✅ STEP 3: Save Device with ACTUAL user_id
        new_device = Device(
            user_id=user.user_id,  # From token, not hardcoded!
            loc_id=location.loc_id,
            type_id=device_type.type_id,
            mac_address=mac_input
        )
        db.session.add(new_device)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Device '{type_input}' in '{loc_input}' successfully added!",
            "device_id": new_device.device_id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/get_devices', methods=['GET'])
def get_devices():
    """Get all devices for logged-in user"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        devices = Device.query.filter_by(user_id=user.user_id).all()
        
        devices_list = []
        for device in devices:
            devices_list.append({
                "device_id": device.device_id,
                "type": device.device_type.type_name if device.device_type else "Unknown",
                "location": device.location.loc_name if device.location else "Unknown",
                "mac_address": device.mac_address
            })
        
        return jsonify({
            "success": True,
            "devices": devices_list,
            "total": len(devices_list)
        }), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ================= ALEXA CONTROL ROUTE =================
@app.route('/alexa', methods=['POST'])
def alexa_handler():
    """Handle Alexa voice commands"""
    data = request.get_json()
    req_type = data.get("request", {}).get("type")
    
    # Extract user_id from Alexa token
    user_id = None
    try:
        access_token = data.get('session', {}).get('user', {}).get('accessToken')
        if access_token:
            user = get_user_from_token(access_token)
            if user:
                user_id = user.user_id
    except:
        pass
    
    if not user_id:
        return build_alexa_response("Pehle apne account ko Alexa app mein link karo.")
    
    if req_type == "LaunchRequest":
        return build_alexa_response("Floro active hai, boliye?", end_session=False)

    elif req_type == "IntentRequest":
        intent_name = data.get("request", {}).get("intent", {}).get("name")
        
        if intent_name == "OxyControlIntent":
            try:
                # Get voice command
                slots = data['request']['intent']['slots']
                raw_voice = slots.get("command", {}).get("value", "").lower()
                print(f"🔥 Original Voice: {raw_voice}")

                # NO TRANSLATION - Direct matching
                translated_voice = raw_voice.lower().strip()
                print(f"📝 Processing Voice: {translated_voice}")

                # ✅ STEP 1: Get all devices for THIS USER
                user_devices = Device.query.filter_by(user_id=user_id).all()
                
                if not user_devices:
                    return build_alexa_response(f"Aapke paas koi device registered nahi hai.")

                # ✅ STEP 2: Get user's device types and locations
                user_device_types = set()
                user_locations = set()
                
                for device in user_devices:
                    if device.device_type:
                        user_device_types.add(device.device_type.type_name.lower())
                    if device.location:
                        user_locations.add(device.location.loc_name.lower())
                
                print(f"👤 User {user_id} ke devices: {[(d.device_type.type_name if d.device_type else '', d.location.loc_name if d.location else '') for d in user_devices]}")
                
                # ✅ STEP 3: Match from USER'S devices
                found_loc = next((loc for loc in user_locations if loc in translated_voice), None)
                found_type = next((dtype for dtype in user_device_types if dtype in translated_voice), None)
                
                print(f"🎯 Found Location: {found_loc}, Found Type: {found_type}")
                
                # ✅ STEP 4: Extract numbers
                nums = re.findall(r'\d+', translated_voice)
                val = int(nums[0]) if nums else None

                payload = None
                res_text = ""

                # ✅ STEP 5: Command Logic
                
                if "speed" in translated_voice and val is not None:
                    speed_val = 101 - val if val <= 100 else 1
                    payload = f"S={speed_val};"
                    res_text = f"Speed {val} set kar di hai."

                elif "brightness" in translated_voice or "light" in translated_voice:
                    if val:
                        bright = val if val <= 8 else (8 + (val - 8) // 10)
                        payload = f"B={bright};"
                        res_text = f"Brightness {val} percent kar di hai."
                    else:
                        payload = "B=5;"
                        res_text = f"Brightness set kar di hai."

                elif "color" in translated_voice or "rang" in translated_voice:
                    colors = {
                        "red": "255,0,0",
                        "green": "0,255,0",
                        "blue": "0,0,255",
                        "white": "255,255,255",
                        "pink": "255,192,203",
                        "yellow": "255,255,0",
                        "orange": "255,165,0"
                    }
                    found_color = next((c for c in colors.keys() if c in translated_voice), "white")
                    rgb = colors[found_color]
                    payload = f"C={rgb};"
                    res_text = f"Color {found_color} kar diya hai."

                elif "mode" in translated_voice and val:
                    payload = f"M{val}"
                    res_text = f"Mode {val} active kar diya."

                elif any(w in translated_voice for w in ['on', 'start', 'turn on', 'activate', 'chalu']):
                    payload = "O"
                    res_text = f"{found_type if found_type else 'Device'} on kar diya."
                    
                elif any(w in translated_voice for w in ['off', 'stop', 'turn off', 'deactivate', 'band']):
                    payload = "F"
                    res_text = f"{found_type if found_type else 'Device'} band kar diya."

                # ✅ STEP 6: Find device and publish MQTT
                if payload:
                    query = Device.query.filter_by(user_id=user_id)
                    
                    if found_type:
                        query = query.join(DeviceType).filter(DeviceType.type_name == found_type)
                    
                    if found_loc:
                        query = query.join(Location).filter(Location.loc_name == found_loc)
                    
                    device = query.first()

                    if device:
                        topic = f"alexa/{device.mac_address}/RX"
                        mqtt_client.publish(topic, payload)
                        print(f"✅ MQTT Published: {topic} -> {payload}")
                        return build_alexa_response(res_text)
                    else:
                        loc_str = f" {found_loc} mein" if found_loc else ""
                        return build_alexa_response(f"Bhai, aapke paas{loc_str} {found_type if found_type else 'device'} nahi hai.")

                return build_alexa_response("Bhai, kya karun? On/Off, Speed, Brightness ya Color?")

            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
                return build_alexa_response("Processing mein error aayi hai.")

    return build_alexa_response("Samajh nahi aaya.")


# ================= HELPER FUNCTIONS =================
def build_alexa_response(text, end_session=True):
    """Build Alexa JSON response"""
    return jsonify({
        "version": "1.0",
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": text
            },
            "shouldEndSession": end_session
        }
    })


if __name__ == '__main__':
    # Production mein 'port' environment variable se milta hai
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)