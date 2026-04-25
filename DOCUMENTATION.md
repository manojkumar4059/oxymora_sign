# 🚀 Floro Flask App - Complete Documentation

## ✅ Major Changes

### 1. **Hardcoding Removed** ✨
- All database credentials now come from `.env` file
- OTP code is configurable via `.env`
- MQTT broker settings from `.env`
- JWT key from `.env`

### 2. **Account Linking Added** 🔗
New endpoints for Alexa account linking:
- `/account-linking/auth-code` - Generate auth code
- `/account-linking/exchange-token` - Exchange code for access token
- `/account-linking/status` - Check linking status
- `/account-linking/unlink` - Unlink Alexa account

### 3. **User Authentication Fixed** 🔐
- All routes now use token-based authentication
- `get_user_from_token()` helper function
- Device operations require valid token
- User_id extracted from JWT, not hardcoded

### 4. **Database Models Enhanced**
```python
User:
- user_id (primary key)
- username
- email
- password
- access_token        # NEW
- alexa_user_id       # NEW - For account linking
- is_alexa_linked     # NEW - Linking status flag

Device:
- Relationships added for easier access
- user, device_type, location relationships
- All foreign keys properly defined
```

---

## 📋 Environment Variables (.env)

```env
# Database
DB_USER=root
DB_PASS=your_password
DB_HOST=127.0.0.1
DB_NAME=oxymora_sign
DB_PORT=3307

# Security
JWT_KEY=oxy_secret_786
OTP_CODE=0002

# MQTT
MQTT_BROKER=otplcloud.com
MQTT_PORT=1883

# Flask
FLASK_ENV=development
FLASK_DEBUG=True
```

---

## 🔐 API Endpoints

### Authentication Routes

#### **POST /signup**
Register new user with OTP
```json
{
  "username": "john",
  "email": "john@example.com",
  "password": "pass123",
  "otp": "0002"
}
```

#### **POST /login**
Login user and get access token
```json
{
  "email": "john@example.com",
  "password": "pass123"
}
```

Response:
```json
{
  "success": true,
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user_id": 1,
  "is_alexa_linked": false
}
```

#### **POST /update-password**
Update password with OTP verification
```json
{
  "email": "john@example.com",
  "new_password": "newpass123",
  "otp": "0002"
}
```

---

### Account Linking Routes (NEW!)

#### **POST /account-linking/auth-code**
Step 1: Generate authorization code
```json
{
  "email": "john@example.com",
  "password": "pass123"
}
```

Response:
```json
{
  "success": true,
  "auth_code": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "message": "Auth code generated successfully"
}
```

#### **POST /account-linking/exchange-token**
Step 2: Exchange auth code for access token (called by Alexa backend)
```json
{
  "auth_code": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "alexa_user_id": "amzn1.ask.account.UNIQUE_ID"
}
```

Response:
```json
{
  "success": true,
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "message": "Alexa account linked successfully"
}
```

#### **GET /account-linking/status**
Check if Alexa is linked
```
Headers:
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

Response:
```json
{
  "success": true,
  "is_linked": true,
  "username": "john"
}
```

#### **POST /account-linking/unlink**
Unlink Alexa account
```
Headers:
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

---

### Device Management Routes

#### **POST /add_device**
Add device to user's account
```
Headers:
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

Body (form-data):
- location: "bedroom"
- device_type: "fan"
- mac_address: "AA:BB:CC:DD:EE:FF"
```

Response:
```json
{
  "success": true,
  "message": "Device 'fan' in 'bedroom' successfully added!",
  "device_id": 1
}
```

#### **GET /get_devices**
Get all devices for logged-in user
```
Headers:
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

Response:
```json
{
  "success": true,
  "devices": [
    {
      "device_id": 1,
      "type": "fan",
      "location": "bedroom",
      "mac_address": "AA:BB:CC:DD:EE:FF"
    }
  ],
  "total": 1
}
```

---

## 🗣️ Alexa Voice Command Route

#### **POST /alexa**
Handle Alexa voice commands

The request must include user's access token in session:
```json
{
  "version": "1.0",
  "session": {
    "user": {
      "accessToken": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
  },
  "request": {
    "type": "IntentRequest",
    "intent": {
      "name": "OxyControlIntent",
      "slots": {
        "command": {
          "value": "turn on fan in bedroom"
        }
      }
    }
  }
}
```

**Supported Commands:**
- `turn on/off {device} in {location}`
- `set speed 50` (0-100)
- `set brightness 75` (0-100)
- `set color red/blue/green/white/pink/yellow/orange`
- `activate/deactivate {device}`
- `start/stop {device}`

---

## 🔄 Account Linking Flow (For Alexa)

### Step 1: User initiates linking in Alexa App
- Alexa App redirects to your auth endpoint
- User enters email & password
- Backend generates `auth_code`

### Step 2: Alexa exchanges code for access token
```javascript
POST /account-linking/exchange-token
{
  "auth_code": "...",
  "alexa_user_id": "amzn1.ask.account.XXXXX"
}
```

### Step 3: Store linked state in database
- `user.alexa_user_id` = Alexa's unique ID
- `user.is_alexa_linked` = True

### Step 4: Alexa stores returned access_token
- Uses token in all future requests
- Token is JWT with 24-hour expiry

---

## 🛠️ Installation

### 1. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Create `.env` file
```bash
cp .env.example .env
# Edit .env with your settings
```

### 4. Create database tables
```python
from app import app, db
with app.app_context():
    db.create_all()
    print("✅ Tables created!")
```

### 5. Run the app
```bash
python app_improved.py
```

---

## 📦 Updated requirements.txt

```
Flask==2.3.0
Flask-SQLAlchemy==3.0.0
Flask-Bcrypt==1.0.1
PyJWT==2.8.0
paho-mqtt==1.6.1
PyMySQL==1.1.0
python-dotenv==1.0.0
```

---

## 🔑 Key Improvements

| Feature | Before | After |
|---------|--------|-------|
| Hardcoded values | ❌ Everywhere | ✅ All in .env |
| User authentication | ❌ Hardcoded user_id=1 | ✅ Token-based per user |
| Alexa account linking | ❌ Not implemented | ✅ Full OAuth flow |
| Device ownership | ❌ Global database | ✅ User-specific devices |
| Configuration | ❌ In code | ✅ Environment variables |
| API Security | ⚠️ Basic | ✅ JWT token validation |

---

## ⚠️ Important Notes

1. **OTP Code** (0002) is still hardcoded in `.env`
   - Can be changed in `.env` file
   - Not in Python code anymore

2. **Alexa Account Linking**
   - Requires Alexa Developer Console setup
   - OAuth 2.0 Authorization Code Flow
   - Redirect URI must be configured in Alexa

3. **JWT Tokens**
   - 24-hour expiry
   - User must re-login after expiry
   - Token sent as Bearer token in Authorization header

4. **MQTT Publishing**
   - Only works for user's own devices
   - MAC address must be correct
   - Topic format: `alexa/{mac_address}/RX`

---

## 🐛 Debugging

Enable detailed logging:
```python
if __name__ == '__main__':
    app.run(port=5000, debug=True)  # Already enabled
```

Check logs for:
- ✅ MQTT Connected successfully!
- 👤 User {user_id} ke devices: ...
- 🎯 Found Location: ..., Found Type: ...
- ✅ MQTT Published: topic -> payload

---

## 📞 Troubleshooting

### "Unauthorized" error
- Check Authorization header has Bearer token
- Token may have expired (24 hours)
- Try login again to get fresh token

### Device not found
- Ensure device is registered for this user
- Check location and device_type spelling (case-sensitive after lowercasing)
- Use `/get_devices` endpoint to verify

### MQTT not publishing
- Check MQTT broker is running
- Verify MAC address is correct
- Check topic format in logs

### Alexa not responding
- Verify account is linked (`is_alexa_linked=true`)
- Check `alexa_user_id` is stored in database
- Ensure access token is valid and not expired

---

## 🎯 Next Steps

1. Setup Alexa Developer Console
2. Configure OAuth 2.0 in Alexa
3. Point authorization URI to `/account-linking/auth-code`
4. Test account linking
5. Deploy to production
