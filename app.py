from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
import jwt
import datetime
import os
import urllib.parse
import paho.mqtt.client as mqtt
from webcolors import name_to_rgb
import re
from dotenv import load_dotenv
import random
import resend
import time

load_dotenv()

app = Flask(__name__)

# ================= CONFIGURATION =================
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASS')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
JWT_KEY = os.getenv('JWT_SECRET')
DB_PORT = os.getenv('DB_PORT')

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

resend.api_key = os.getenv('RESEND_API_KEY')
MAIL_FROM = os.getenv('MAIL_FROM', 'Oxy App <onboarding@otplai.com>')

db = SQLAlchemy(app)

# ================= MQTT SETUP =================
class MQTTState:
    def __init__(self):
        self.is_connected = False
        self.connection_time = None
        self.last_publish = None

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
        mqtt_state.connection_time = datetime.datetime.now()
        client.subscribe("alexa/+/TX", qos=1)
    else:
        print(f"❌ [MQTT] Failed: {rc}")
        mqtt_state.is_connected = False

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"⚠️ [MQTT] Disconnected: {rc}")
    mqtt_state.is_connected = False

def on_publish(client, userdata, mid):
    print(f"✅ [MQTT] Published! MID: {mid}")
    mqtt_state.last_publish = datetime.datetime.now()

def on_message(client, userdata, msg):
    print(f"📨 [MQTT] {msg.topic}: {msg.payload.decode()}")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_publish = on_publish
mqtt_client.on_message = on_message

def connect_mqtt():
    try:
        print(f"🔌 [MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
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

# ================= DATABASE MODELS (Code 1 Schema) =================
class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    otp = db.Column(db.String(6), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('device_types.type_id'), nullable=False)
    loc_id = db.Column(db.Integer, db.ForeignKey('locations.loc_id'), nullable=False)
    mac_address = db.Column(db.String(50), nullable=False)
    device_type = db.relationship('DeviceType', backref='devices')
    location = db.relationship('Location', backref='devices')

with app.app_context():
    db.create_all()

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
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

def publish_mqtt(topic, message):
    if not mqtt_state.is_connected:
        try:
            mqtt_client.reconnect()
            time.sleep(2)
        except:
            connect_mqtt()

    if not mqtt_state.is_connected:
        connect_mqtt()

    if not mqtt_state.is_connected:
        return False, "MQTT not connected"

    try:
        print(f"📤 [MQTT] Publishing to '{topic}': {message}")
        result = mqtt_client.publish(topic, message, qos=1)
        result.wait_for_publish(timeout=5)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            return True, f"Message sent (MID: {result.mid})"
        else:
            return False, mqtt.error_string(result.rc)
    except Exception as e:
        return False, str(e)

def build_alexa_response(text, end_session=True, session_attrs=None):
    return jsonify({
        "version": "1.0",
        "sessionAttributes": session_attrs or {},
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session
        }
    })

def send_otp_email(to_email, name, otp):
    try:
        resend.Emails.send({
            "from": MAIL_FROM,
            "to": [to_email],
            "subject": "Oxy Account Verification",
            "text": f"""Hello {name},

Your OTP verification code is:

🔐 {otp}

Enter this code into your app to verify your account.

If you did not request this, please ignore it.

Thanks,
Team Oxy 🚀"""
        })
        print(f"✉️ [EMAIL] OTP sent to {to_email}")
        return True, None
    except Exception as e:
        print(f"❌ [EMAIL] Error: {str(e)}")
        return False, str(e)

# ================= AUTH ROUTES (Code 2 API) =================

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password') or not data.get('name'):
            return jsonify({"success": False, "message": "Name, email, and password are required!"}), 400

        email = data['email'].lower().strip()
        name = data['name'].strip()
        password = data['password']
        otp = "0001"

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            if existing_user.is_verified:
                return jsonify({"success": False, "message": "This email is already registered!"}), 400
            else:
                existing_user.otp = otp
                existing_user.full_name = name
                existing_user.password = password
                send_otp_email(email, name, otp)
                db.session.commit()
                return jsonify({
                    "success": True,
                    "message": "Previous registration was pending. Default OTP (0001) set.",
                    "email": email
                }), 200

        new_user = User(full_name=name, email=email, password=password, otp=otp, is_verified=False)
        send_otp_email(email, name, otp)
        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Testing Mode: Use OTP 0001.",
            "email": email
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"❌ [SIGNUP] Error: {str(e)}")
        return jsonify({"success": False, "message": "Something went wrong!"}), 500


@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('otp'):
            return jsonify({"success": False, "message": "Email and OTP are required!"}), 400

        email = data['email'].lower().strip()
        user_otp = str(data['otp']).strip()

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"success": False, "message": "Email not registered!"}), 400

        if user.is_verified:
            return jsonify({"success": False, "message": "Already verified!"}), 400

        if user.otp != user_otp:
            return jsonify({"success": False, "message": "❌ Wrong OTP!"}), 400

        user.is_verified = True
        user.otp = None
        db.session.commit()

        return jsonify({"success": True, "message": "✅ Verified successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({"success": False, "message": "Email and password are required!"}), 400

        email = data['email'].lower().strip()
        user = User.query.filter_by(email=email, password=data['password']).first()

        if not user:
            return jsonify({"success": False, "message": "❌ Incorrect email or password!"}), 401

        if not user.is_verified:
            return jsonify({"success": False, "message": "Please verify your email first!"}), 403

        access_token = generate_token(user.id)

        return jsonify({
            "success": True,
            "message": "Login successful!",
            "access_token": access_token,
            "token_type": "Bearer",
            "user": {
                "id": user.id,
                "name": user.full_name,
                "email": user.email
            }
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/update-password', methods=['POST'])
def update_password():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"success": False, "message": "Token missing!"}), 401

    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(decoded['user_id'])

        if not user:
            return jsonify({"success": False, "message": "User not found!"}), 404

        data = request.get_json()
        new_pass = data.get('new_password', '').strip()

        if not new_pass:
            return jsonify({"success": False, "message": "New password required!"}), 400

        user.password = new_pass
        db.session.commit()
        return jsonify({"success": True, "message": "Password updated successfully!"}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"success": False, "message": "Token expired!"}), 401
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 401


@app.route('/logout', methods=['GET'])
def logout():
    email = request.args.get('email', '').lower().strip()
    user = User.query.filter_by(email=email).first()
    if user:
        db.session.commit()
        return jsonify({"success": True, "message": f"Logout success for {email}"}), 200
    return jsonify({"success": False, "message": "User not found!"}), 404

# ================= DEVICE MANAGEMENT (Code 1 Schema) =================

@app.route('/api/add-device', methods=['POST'])
def add_device():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"success": False, "message": "Token missing!"}), 401

    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(decoded['user_id'])

        if not user:
            return jsonify({"success": False, "message": "User not found!"}), 404

        if not user.is_verified:
            return jsonify({"success": False, "message": "Please verify your email first!"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Data required!"}), 400

        mac_input = data.get('mac_address', '').strip().upper()
        loc_raw = data.get('location', 'default').lower().strip()
        type_raw = data.get('device_type', '').lower().strip()

        if not mac_input or not type_raw:
            return jsonify({"success": False, "message": "MAC and device_type are required!"}), 400

        location = Location.query.filter_by(loc_name=loc_raw).first()
        if not location:
            location = Location(loc_name=loc_raw)
            db.session.add(location)
            db.session.flush()

        device_type = DeviceType.query.filter_by(type_name=type_raw).first()
        if not device_type:
            device_type = DeviceType(type_name=type_raw)
            db.session.add(device_type)
            db.session.flush()

        if Device.query.filter_by(mac_address=mac_input).first():
            return jsonify({"success": False, "message": "This device is already registered!"}), 400

        new_device = Device(
            user_id=user.id,
            loc_id=location.loc_id,
            type_id=device_type.type_id,
            mac_address=mac_input
        )
        db.session.add(new_device)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"✅ Device '{type_raw}' in '{loc_raw}' registered!",
            "device": {
                "id": new_device.device_id,
                "mac_address": mac_input,
                "location": loc_raw,
                "device_type": type_raw
            }
        }), 201

    except jwt.ExpiredSignatureError:
        return jsonify({"success": False, "message": "Token expired!"}), 401
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400


@app.route('/get_devices', methods=['GET'])
def get_devices():
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"success": False, "message": "Token missing!"}), 401

    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(decoded['user_id'])

        if not user:
            return jsonify({"success": False, "message": "User not found!"}), 404

        devices = Device.query.filter_by(user_id=user.id).all()
        devices_list = [{
            "device_id": d.device_id,
            "type": d.device_type.type_name if d.device_type else "Unknown",
            "location": d.location.loc_name if d.location else "Unknown",
            "mac_address": d.mac_address
        } for d in devices]

        return jsonify({"success": True, "devices": devices_list, "total": len(devices_list)}), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"success": False, "message": "Token expired!"}), 401
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ================= MQTT STATUS =================
@app.route('/api/mqtt-status', methods=['GET'])
def mqtt_status():
    return jsonify({
        "connected": mqtt_state.is_connected,
        "broker": MQTT_BROKER,
        "port": MQTT_PORT,
        "connection_time": mqtt_state.connection_time.isoformat() if mqtt_state.connection_time else None,
        "last_publish": mqtt_state.last_publish.isoformat() if mqtt_state.last_publish else None
    }), 200

# ================= ALEXA ACCOUNT LINKING =================
@app.route('/auth', methods=['GET', 'POST'])
def authorize():
    state = request.args.get('state') or request.form.get('state')
    redirect_uri = request.args.get('redirect_uri') or request.form.get('redirect_uri')

    if request.method == 'GET':
        if not state or not redirect_uri:
            return "Invalid Request: Missing state or redirect_uri", 400
        return render_template('login.html', state=state, redirect_uri=redirect_uri)

    email = request.form.get('email', '').lower().strip()
    password = request.form.get('password', '')

    user = User.query.filter_by(email=email, password=password, is_verified=True).first()

    if user:
        auth_code = f"CODE_{user.id}"
        final_url = f"{redirect_uri}?state={state}&code={auth_code}"
        print(f"✅ [AUTH] User {user.id} linked!")
        return redirect(final_url)

    print(f"❌ [AUTH] Failed for: {email}")
    return render_template('login.html', state=state, redirect_uri=redirect_uri,
                           error="Invalid Email or Password!")


@app.route('/token', methods=['POST'])
def token_exchange():
    auth_code = request.form.get('code', '')
    try:
        user_id = int(auth_code.split('_')[1])
        access_token = generate_token(user_id)
        print(f"✅ [TOKEN] Token issued for user {user_id}")
        return jsonify({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 31536000
        }), 200
    except Exception as e:
        print(f"❌ [TOKEN] Error: {e}")
        return jsonify({"error": "invalid_grant"}), 400

# ================= ALEXA SKILL HANDLER (Code 1 - OxyControlIntent) =================
@app.route('/alexa', methods=['POST'])
def alexa_handler():
    try:
        data = request.get_json()
        req_type = data.get("request", {}).get("type")

        access_token = data.get('session', {}).get('user', {}).get('accessToken')
        user = get_user_from_token(access_token) if access_token else None

        if not user:
            return build_alexa_response("Please link your account in the Alexa app first.")

        first_name = user.full_name.split()[0]

        # --- Launch Request ---
        if req_type == "LaunchRequest":
            return build_alexa_response(
                f"Floro active hai, boliye {first_name}?",
                end_session=False
            )

        # --- Intent Request ---
        if req_type == "IntentRequest":
            intent_name = data.get("request", {}).get("intent", {}).get("name")

            if intent_name == "OxyControlIntent":
                try:
                    slots = data['request']['intent']['slots']
                    voice = slots.get("command", {}).get("value", "").lower().strip()

                    user_devices = Device.query.filter_by(user_id=user.id).all()
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
                        if 1 <= val <= 100:
                            speed_val = 101 - val
                            payload   = f"S={speed_val};"
                            res_text  = f"Speed {val} set kar di."
                        else:
                            return build_alexa_response("Speed 1 se 100 ke beech boliye.", end_session=False)

                    # Brightness
                    elif "brightness" in voice or "light" in voice:
                        if val is not None:
                            bright   = val if val <= 8 else max(1, min(8, round((val / 100) * 8)))
                            payload  = f"B={bright};"
                            res_text = f"Brightness {bright} set kar di."
                        else:
                            return build_alexa_response("Brightness value boliye.", end_session=False)

                    # Color - webcolors + fallback map
                    elif "color" in voice or "rang" in voice:
                        color_words = re.sub(r'color|rang|change|kar|do|dena', '', voice).strip()
                        color_name  = color_words.split()[0] if color_words else "white"
                        try:
                            rgb      = name_to_rgb(color_name)
                            payload  = f"C={rgb.red},{rgb.green},{rgb.blue};"
                            res_text = f"Color {color_name} kar diya."
                        except:
                            fallback = {
                                "red": "255,0,0", "green": "0,255,0", "blue": "0,0,255",
                                "white": "255,255,255", "pink": "255,192,203",
                                "yellow": "255,255,0", "orange": "255,165,0",
                                "purple": "128,0,128", "cyan": "0,255,255"
                            }
                            found_color = next((c for c in fallback if c in voice), "white")
                            payload     = f"C={fallback[found_color]};"
                            res_text    = f"Color {found_color} kar diya."

                    # Mode
                    elif "mode" in voice and val is not None:
                        mode_val = min(200, val)
                        payload  = f"M{mode_val}"
                        res_text = f"Mode {mode_val} active kar diya."

                    # On
                    elif any(w in voice for w in ['on', 'start', 'turn on', 'chalu']):
                        payload  = "O"
                        res_text = f"{found_type or 'Device'} on kar diya."

                    # Off
                    elif any(w in voice for w in ['off', 'stop', 'turn off', 'band']):
                        payload  = "F"
                        res_text = f"{found_type or 'Device'} band kar diya."

                    if payload:
                        query = Device.query.filter_by(user_id=user.id)
                        if found_type:
                            query = query.join(DeviceType).filter(DeviceType.type_name == found_type)
                        if found_loc:
                            query = query.join(Location).filter(Location.loc_name == found_loc)

                        device = query.first()

                        if device:
                            topic = f"alexa/{device.mac_address}/RX"
                            success, msg = publish_mqtt(topic, payload)
                            if success:
                                return build_alexa_response(res_text, end_session=False)
                            else:
                                return build_alexa_response(
                                    f"Device respond nahi kar raha.", end_session=False
                                )
                        else:
                            return build_alexa_response("Woh device nahi mili.", end_session=False)

                    return build_alexa_response(
                        "Kya karun? On/Off, Speed, Brightness ya Color bolo.",
                        end_session=False
                    )

                except Exception as e:
                    print(f"❌ [ALEXA Intent] Error: {e}")
                    return build_alexa_response("Processing mein error aayi.")

        return build_alexa_response("Samajh nahi aaya.")

    except Exception as e:
        print(f"❌ [ALEXA] Top-level Error: {e}")
        return build_alexa_response("Server mein kuch gadbad hai.")

# ================= APP STARTUP =================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "="*60)
    print("🚀 STARTING OXY SERVER")
    print("="*60)
    print(f"Server  : 0.0.0.0:{port}")
    print(f"MQTT    : {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Database: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=port, debug=False)