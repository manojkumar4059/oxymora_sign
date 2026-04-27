from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
import jwt
import datetime
import os
import paho.mqtt.client as mqtt
import re
import time

app = Flask(__name__)

# ================= LOCAL DB SETTINGS =================
DB_USER = 'root'
DB_PASS = ''
DB_HOST = '127.0.0.1'
DB_NAME = 'oxymora_sign'
DB_PORT = '3307'
JWT_KEY = 'oxy_secret_786'

app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = JWT_KEY

db = SQLAlchemy(app)

# ================= DATABASE MODELS =================
class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

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
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    type_id = db.Column(db.Integer, db.ForeignKey('device_types.type_id'))
    loc_id = db.Column(db.Integer, db.ForeignKey('locations.loc_id'))
    mac_address = db.Column(db.String(50), nullable=False)
    device_type = db.relationship('DeviceType', backref='devices')
    location = db.relationship('Location', backref='devices')

# ================= MQTT SETUP =================
MQTT_BROKER = "otplcloud.com"
mqtt_client = mqtt.Client()

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_BROKER, 1883, 60)
        mqtt_client.loop_start()
        print("✅ MQTT Connected!")
    except Exception as e:
        print(f"❌ MQTT Connection Failed: {e}")

connect_mqtt()

# ================= HELPER =================
def get_user_from_token(token):
    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return User.query.get(decoded['user_id'])
    except:
        return None

def generate_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=365)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

def build_alexa_response(text, end_session=True):
    return jsonify({
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session
        }
    })

# ================= ROUTES =================

# --- SIGNUP (plain text password, OTP check) ---
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()

    if data.get('otp') != "0002":
        return jsonify({"success": False, "message": "Galat OTP!"}), 403

    email = data.get('email', '').lower().strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not email or not username or not password:
        return jsonify({"success": False, "message": "Sab fields required hain!"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Email pehle se registered hai!"}), 400

    try:
        new_user = User(username=username, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"success": True, "message": "User save ho gaya!", "user_id": new_user.user_id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- LOGIN (plain text match, token return) ---
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').lower().strip()
    password = data.get('password', '')

    user = User.query.filter_by(email=email, password=password).first()

    if user:
        return jsonify({
            "success": True,
            "message": "Login successful!",
            "access_token": generate_token(user.user_id),
            "user_id": user.user_id
        }), 200

    return jsonify({"success": False, "message": "Invalid Email or Password!"}), 401

# --- UPDATE PASSWORD ---
@app.route('/update-password', methods=['POST'])
def update_password():
    data = request.get_json()

    if data.get('otp') != "0002":
        return jsonify({"success": False, "message": "Invalid OTP!"}), 403

    email = data.get('email', '').lower().strip()
    new_password = data.get('new_password', '')

    if not new_password:
        return jsonify({"success": False, "message": "New password required!"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"success": False, "message": "User nahi mila!"}), 404

    try:
        user.password = new_password
        db.session.commit()
        return jsonify({"success": True, "message": "Password update ho gaya!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- ADD DEVICE (token se user_id) ---
@app.route('/add_device', methods=['POST'])
def add_device():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    if not user:
        return jsonify({"success": False, "message": "Unauthorized!"}), 401

    loc_raw = request.form.get('location')
    type_raw = request.form.get('device_type')
    mac_input = request.form.get('mac_address')

    if not all([loc_raw, type_raw, mac_input]):
        return jsonify({"success": False, "message": "Sab fields required hain!"}), 400

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
        "message": f"Device '{type_input}' in '{loc_input}' add ho gaya!",
        "device_id": new_device.device_id
    }), 201

# --- GET DEVICES ---
@app.route('/get_devices', methods=['GET'])
def get_devices():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = get_user_from_token(token)
    if not user:
        return jsonify({"success": False, "message": "Unauthorized!"}), 401

    devices = Device.query.filter_by(user_id=user.user_id).all()
    devices_list = [{
        "device_id": d.device_id,
        "type": d.device_type.type_name if d.device_type else "Unknown",
        "location": d.location.loc_name if d.location else "Unknown",
        "mac_address": d.mac_address
    } for d in devices]

    return jsonify({"success": True, "devices": devices_list, "total": len(devices_list)}), 200
@app.route('/auth', methods=['GET', 'POST'])
def authorize():
    # Alexa parameters nikalna
    state = request.args.get('state') or request.form.get('state')
    redirect_uri = request.args.get('redirect_uri') or request.form.get('redirect_uri')

    if request.method == 'GET':
        return render_template('login.html', state=state, redirect_uri=redirect_uri)

    # POST: Login Logic
    email = request.form.get('email', '').lower().strip()
    password = request.form.get('password', '')

    user = User.query.filter_by(email=email, password=password).first()

    if user:
        # Alexa ke liye temporary code bhej rahe hain
        auth_code = f"CODE_{user.user_id}"
        return redirect(f"{redirect_uri}?state={state}&code={auth_code}")

    return render_template('login.html', state=state, redirect_uri=redirect_uri, error="Invalid Credentials!")

@app.route('/token', methods=['POST'])
def token():
    code = request.form.get('code', '')
    try:
        user_id = code.replace('CODE_', '')
        access_token = generate_token(user_id)
        
        return jsonify({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 31536000,
            "refresh_token": "OxyRefreshStatic"
        })
    except:
        return jsonify({"error": "invalid_grant"}), 400

# ================= ALEXA SKILL (OxyControlIntent) =================
@app.route('/alexa', methods=['POST'])
def alexa_handler():
    data = request.get_json()
    req_type = data.get("request", {}).get("type")

    # Token se user fetch karo
    access_token = data.get('session', {}).get('user', {}).get('accessToken')
    user = get_user_from_token(access_token) if access_token else None

    if not user:
        return build_alexa_response("Pehle Alexa app mein account link karein.")

    if req_type == "LaunchRequest":
        return build_alexa_response(f"Floro active hai, boliye {user.username}?", end_session=False)

    if req_type == "IntentRequest":
        intent_name = data.get("request", {}).get("intent", {}).get("name")

        if intent_name == "OxyControlIntent":
            try:
                slots = data['request']['intent']['slots']
                voice = slots.get("command", {}).get("value", "").lower().strip()

                # Sirf is user ke devices
                user_devices = Device.query.filter_by(user_id=user.user_id).all()
                if not user_devices:
                    return build_alexa_response("Aapke paas koi device registered nahi hai.")

                user_types = {d.device_type.type_name.lower() for d in user_devices if d.device_type}
                user_locs  = {d.location.loc_name.lower() for d in user_devices if d.location}

                found_loc  = next((loc for loc in user_locs if loc in voice), None)
                found_type = next((t for t in user_types if t in voice), None)

                nums = re.findall(r'\d+', voice)
                val  = int(nums[0]) if nums else None

                payload  = None
                res_text = ""

                # Speed
                if "speed" in voice and val is not None:
                    speed_val = 101 - val if val <= 100 else 1
                    payload   = f"S={speed_val};"
                    res_text  = f"Speed {val} set kar di."

                # Brightness
                elif "brightness" in voice or "light" in voice:
                    if val:
                        bright = val if val <= 8 else (8 + (val - 8) // 10)
                        payload = f"B={bright};"
                    else:
                        payload = "B=5;"
                    res_text = f"Brightness set kar di."

                # Color
                elif "color" in voice or "rang" in voice:
                    colors = {
                        "red": "255,0,0", "green": "0,255,0", "blue": "0,0,255",
                        "white": "255,255,255", "pink": "255,192,203",
                        "yellow": "255,255,0", "orange": "255,165,0"
                    }
                    found_color = next((c for c in colors if c in voice), "white")
                    payload  = f"C={colors[found_color]};"
                    res_text = f"Color {found_color} kar diya."

                # Mode
                elif "mode" in voice and val:
                    payload  = f"M{val}"
                    res_text = f"Mode {val} active kar diya."

                # On
                elif any(w in voice for w in ['on', 'start', 'turn on', 'activate', 'chalu']):
                    payload  = "O"
                    res_text = f"{found_type or 'Device'} on kar diya."

                # Off
                elif any(w in voice for w in ['off', 'stop', 'turn off', 'deactivate', 'band']):
                    payload  = "F"
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
                        mqtt_client.publish(topic, payload)
                        print(f"✅ MQTT: {topic} -> {payload}")
                        return build_alexa_response(res_text)
                    else:
                        return build_alexa_response("Woh device nahi mili.")

                return build_alexa_response("Kya karun? On/Off, Speed, Brightness ya Color bolo.")

            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
                return build_alexa_response("Processing mein error aayi.")

    return build_alexa_response("Samajh nahi aaya.")
if __name__ == '__main__':
    # MQTT ko yahan start karna behtar hai
    connect_mqtt()
    
    # Render hamesha 'PORT' variable bhejta hai
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)