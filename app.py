from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import jwt
import datetime
import os
import urllib.parse
import paho.mqtt.client as mqtt
import re
from dotenv import load_dotenv
import random
import time

load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)

# ================= CONFIGURATION =================
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASS')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
JWT_KEY = os.getenv('JWT_SECRET')
DB_PORT = os.getenv('DB_PORT')
OTP_CODE = os.getenv('OTP_CODE', '0002')

safe_password = urllib.parse.quote_plus(DB_PASS)
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f"mysql+pymysql://{DB_USER}:{safe_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?ssl_verify_cert=false&ssl_verify_identity=false"
)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
    'pool_timeout': 30,
    'pool_size': 5,
    'max_overflow': 10
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = JWT_KEY

db = SQLAlchemy(app)

# ================= MQTT SETUP =================
class MQTTState:
    def __init__(self):
        self.is_connected = False

mqtt_state = MQTTState()

MQTT_BROKER = os.getenv('MQTT_BROKER', 'otplcloud.com')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
MQTT_USER = os.getenv('MQTT_USER', '')
MQTT_PASS = os.getenv('MQTT_PASS', '')

mqtt_client = mqtt.Client(
    client_id=f"OxyServer_{random.randint(10000, 99999)}",
    clean_session=True,
    protocol=mqtt.MQTTv311
)

if MQTT_USER and MQTT_PASS:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ [MQTT] Connected!")
        mqtt_state.is_connected = True
    else:
        print(f"❌ [MQTT] Failed: {rc}")
        mqtt_state.is_connected = False

def on_disconnect(client, userdata, rc):
    mqtt_state.is_connected = False

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        for _ in range(10):
            if mqtt_state.is_connected:
                return True
            time.sleep(0.5)
        return False
    except Exception as e:
        print(f"❌ [MQTT] Error: {e}")
        return False

connect_mqtt()

# ================= DATABASE MODELS =================
class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    devices = db.relationship('Device', backref='owner', lazy=True)

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
    device_type = db.relationship('DeviceType', backref='devices')
    location = db.relationship('Location', backref='devices')

# ================= HELPER FUNCTIONS =================
def get_user_from_token(token):
    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return User.query.get(decoded['user_id'])
    except:
        return None

def generate_token(user_id, days=365):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=days)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

def publish_mqtt(topic, message):
    if not mqtt_state.is_connected:
        try:
            mqtt_client.reconnect()
            time.sleep(2)
        except:
            connect_mqtt()

    if not mqtt_state.is_connected:
        return False, "MQTT not connected"

    try:
        result = mqtt_client.publish(topic, message, qos=1)
        result.wait_for_publish(timeout=5)
        return result.rc == mqtt.MQTT_ERR_SUCCESS, "OK"
    except Exception as e:
        return False, str(e)

def build_alexa_response(text, end_session=True):
    return jsonify({
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session
        }
    })

# ================= AUTH ROUTES =================
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()

    if data.get('otp') != OTP_CODE:
        return jsonify({"success": False, "message": "Invalid OTP!"}), 403

    email = data.get('email', '').lower().strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not email or not username or not password:
        return jsonify({"success": False, "message": "All fields required!"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Email already registered!"}), 400

    try:
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"success": True, "message": "Signup successful!", "user_id": new_user.user_id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').lower().strip()
    password = data.get('password')

    user = User.query.filter_by(email=email).first()
    if user and bcrypt.check_password_hash(user.password, password):
        return jsonify({
            "success": True,
            "access_token": generate_token(user.user_id),
            "user_id": user.user_id
        }), 200

    return jsonify({"success": False, "message": "Invalid email or password!"}), 401

@app.route('/update-password', methods=['POST'])
def update_password():
    data = request.get_json()

    if data.get('otp') != OTP_CODE:
        return jsonify({"success": False, "message": "Invalid OTP!"}), 403

    email = data.get('email', '').lower().strip()
    new_password = data.get('new_password')

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "User not found!"}), 404

    try:
        user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# ================= ALEXA ACCOUNT LINKING =================
@app.route('/auth', methods=['GET', 'POST'])
def authorize():
    state = request.args.get('state')
    redirect_uri = request.args.get('redirect_uri')

    if request.method == 'GET':
        return render_template('login.html', state=state, redirect_uri=redirect_uri)

    email = request.form.get('email', '').lower().strip()
    password = request.form.get('password', '')
    state = request.form.get('state')
    redirect_uri = request.form.get('redirect_uri')

    user = User.query.filter_by(email=email).first()
    if user and bcrypt.check_password_hash(user.password, password):
        auth_code = f"CODE_{user.user_id}"
        return redirect(f"{redirect_uri}?state={state}&code={auth_code}")

    return render_template('login.html', state=state, redirect_uri=redirect_uri, error="Invalid credentials!")

@app.route('/token', methods=['POST'])
def token_exchange():
    auth_code = request.form.get('code', '')
    try:
        user_id = int(auth_code.split('_')[1])
        access_token = generate_token(user_id)
        return jsonify({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 31536000
        }), 200
    except:
        return jsonify({"error": "invalid_grant"}), 400

# ================= DEVICE MANAGEMENT =================
@app.route('/add_device', methods=['POST'])
def add_device():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    loc_raw = request.form.get('location')
    type_raw = request.form.get('device_type')
    mac_input = request.form.get('mac_address')

    if not all([loc_raw, type_raw, mac_input]):
        return jsonify({"success": False, "message": "All fields required!"}), 400

    try:
        loc_input = loc_raw.lower().strip()
        type_input = type_raw.lower().strip()

        location = Location.query.filter_by(loc_name=loc_input).first()
        if not location:
            location = Location(loc_name=loc_input)
            db.session.add(location)
            db.session.flush()

        device_type = DeviceType.query.filter_by(type_name=type_input).first()
        if not device_type:
            device_type = DeviceType(type_name=type_input)
            db.session.add(device_type)
            db.session.flush()

        new_device = Device(
            user_id=user.user_id,
            loc_id=location.loc_id,
            type_id=device_type.type_id,
            mac_address=mac_input
        )
        db.session.add(new_device)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Device '{type_input}' in '{loc_input}' added!",
            "device_id": new_device.device_id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/get_devices', methods=['GET'])
def get_devices():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        devices = Device.query.filter_by(user_id=user.user_id).all()
        devices_list = [{
            "device_id": d.device_id,
            "type": d.device_type.type_name if d.device_type else "Unknown",
            "location": d.location.loc_name if d.location else "Unknown",
            "mac_address": d.mac_address
        } for d in devices]

        return jsonify({"success": True, "devices": devices_list, "total": len(devices_list)}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ================= ALEXA SKILL HANDLER =================
@app.route('/alexa', methods=['POST'])
def alexa_handler():
    data = request.get_json()
    req_type = data.get("request", {}).get("type")

    access_token = data.get('session', {}).get('user', {}).get('accessToken')
    user = get_user_from_token(access_token) if access_token else None

    if not user:
        return build_alexa_response("Please link your account in the Alexa app first.")

    if req_type == "LaunchRequest":
        return build_alexa_response(f"Floro active hai, boliye {user.username}?", end_session=False)

    if req_type == "IntentRequest":
        intent_name = data.get("request", {}).get("intent", {}).get("name")

        if intent_name == "OxyControlIntent":
            try:
                slots = data['request']['intent']['slots']
                voice = slots.get("command", {}).get("value", "").lower().strip()

                user_devices = Device.query.filter_by(user_id=user.user_id).all()
                if not user_devices:
                    return build_alexa_response("Aapke paas koi device registered nahi hai.")

                user_types = {d.device_type.type_name.lower() for d in user_devices if d.device_type}
                user_locs = {d.location.loc_name.lower() for d in user_devices if d.location}

                found_loc = next((loc for loc in user_locs if loc in voice), None)
                found_type = next((t for t in user_types if t in voice), None)
                nums = re.findall(r'\d+', voice)
                val = int(nums[0]) if nums else None

                payload = None
                res_text = ""

                if "speed" in voice and val is not None:
                    speed_val = 101 - val if val <= 100 else 1
                    payload = f"S={speed_val};"
                    res_text = f"Speed {val} set kar di."

                elif "brightness" in voice or "light" in voice:
                    bright = val if val and val <= 8 else (8 + (val - 8) // 10 if val else 5)
                    payload = f"B={bright};"
                    res_text = f"Brightness set kar di."

                elif "color" in voice or "rang" in voice:
                    colors = {
                        "red": "255,0,0", "green": "0,255,0", "blue": "0,0,255",
                        "white": "255,255,255", "pink": "255,192,203",
                        "yellow": "255,255,0", "orange": "255,165,0"
                    }
                    found_color = next((c for c in colors if c in voice), "white")
                    payload = f"C={colors[found_color]};"
                    res_text = f"Color {found_color} kar diya."

                elif "mode" in voice and val:
                    payload = f"M{val}"
                    res_text = f"Mode {val} active kar diya."

                elif any(w in voice for w in ['on', 'start', 'turn on', 'chalu']):
                    payload = "O"
                    res_text = f"{found_type or 'Device'} on kar diya."

                elif any(w in voice for w in ['off', 'stop', 'turn off', 'band']):
                    payload = "F"
                    res_text = f"{found_type or 'Device'} band kar diya."

                if payload:
                    query = Device.query.filter_by(user_id=user.user_id)
                    if found_type:
                        query = query.join(DeviceType).filter(DeviceType.type_name == found_type)
                    if found_loc:
                        query = query.join(Location).filter(Location.loc_name == found_loc)

                    device = query.first()
                    if device:
                        topic = f"alexa/{device.mac_address}/RX"
                        publish_mqtt(topic, payload)
                        return build_alexa_response(res_text)
                    else:
                        return build_alexa_response(f"Woh device nahi mili.")

                return build_alexa_response("Kya karun? On/Off, Speed, Brightness ya Color bolo.")

            except Exception as e:
                print(f"❌ Error: {e}")
                return build_alexa_response("Processing mein error aayi.")

    return build_alexa_response("Samajh nahi aaya.")

# ================= APP STARTUP =================
if __name__ == "__main__":
   
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)