# 🚀 Quick Start Guide

## Installation (5 minutes)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Create `.env` file in project root
```bash
# Copy the file
cp .env .env.local

# Edit .env with your database credentials
DB_USER=root
DB_PASS=your_password
DB_HOST=127.0.0.1
DB_NAME=oxymora_sign
DB_PORT=3307
JWT_KEY=oxy_secret_786
OTP_CODE=0002
MQTT_BROKER=otplcloud.com
MQTT_PORT=1883
```

### 3. Initialize database
```python
from app_improved import app, db

with app.app_context():
    db.create_all()
    print("✅ Database tables created!")
```

### 4. Run the app
```bash
python app_improved.py
```

Server will start on `http://localhost:5000`

---

## 📱 Testing the API

### Using cURL

#### 1. Sign up user
```bash
curl -X POST http://localhost:5000/signup \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "email": "john@example.com",
    "password": "pass123",
    "otp": "0002"
  }'
```

#### 2. Login
```bash
curl -X POST http://localhost:5000/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com",
    "password": "pass123"
  }'
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

**Save the `access_token`!** You'll need it for other requests.

#### 3. Add device
```bash
curl -X POST http://localhost:5000/add_device \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "location=bedroom" \
  -F "device_type=fan" \
  -F "mac_address=AA:BB:CC:DD:EE:FF"
```

#### 4. Get devices
```bash
curl -X GET http://localhost:5000/get_devices \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 🔗 Account Linking (For Alexa)

### Step 1: Get Auth Code
```bash
curl -X POST http://localhost:5000/account-linking/auth-code \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com",
    "password": "pass123"
  }'
```

Response:
```json
{
  "success": true,
  "auth_code": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### Step 2: Exchange for Access Token (Alexa backend does this)
```bash
curl -X POST http://localhost:5000/account-linking/exchange-token \
  -H "Content-Type: application/json" \
  -d '{
    "auth_code": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "alexa_user_id": "amzn1.ask.account.UNIQUE_ID"
  }'
```

### Step 3: Check Linking Status
```bash
curl -X GET http://localhost:5000/account-linking/status \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Step 4: Unlink Account
```bash
curl -X POST http://localhost:5000/account-linking/unlink \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 🗣️ Test Alexa Commands

Send this to `/alexa` endpoint:

```bash
curl -X POST http://localhost:5000/alexa \
  -H "Content-Type: application/json" \
  -d '{
    "version": "1.0",
    "session": {
      "user": {
        "accessToken": "YOUR_ACCESS_TOKEN"
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
  }'
```

**Try these commands:**
- "turn on fan in bedroom"
- "turn off light in kitchen"
- "set speed 50"
- "set brightness 75"
- "set color red"

---

## 🔑 Using Postman

1. Import this collection
2. Set `{{token}}` variable after login
3. All requests will auto-include Authorization header

### Environment Variables
```
token = access_token from login response
user_id = user_id from login response
base_url = http://localhost:5000
```

---

## 🐛 Common Issues

### Issue: "Database does not exist"
```
Solution:
1. Create database manually:
   CREATE DATABASE oxymora_sign;

2. Or update .env with correct DB_NAME
```

### Issue: "Unauthorized" error
```
Solution:
1. Make sure token is in Authorization header: Bearer {token}
2. Check token hasn't expired (24 hour expiry)
3. Login again to get fresh token
```

### Issue: "Device not found"
```
Solution:
1. Add a device first using /add_device
2. Check device was saved with GET /get_devices
3. Use exact location and type names in voice commands
```

### Issue: MQTT not publishing
```
Solution:
1. Check MQTT broker is running
2. Verify mac_address is correct
3. Check console logs for MQTT topic
```

---

## 📊 Database Schema

### Users Table
```sql
CREATE TABLE users (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    access_token VARCHAR(500),
    alexa_user_id VARCHAR(255) UNIQUE,
    is_alexa_linked BOOLEAN DEFAULT FALSE
);
```

### Devices Table
```sql
CREATE TABLE devices (
    device_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    type_id INT NOT NULL,
    loc_id INT NOT NULL,
    mac_address VARCHAR(50) NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (type_id) REFERENCES device_types(type_id),
    FOREIGN KEY (loc_id) REFERENCES locations(loc_id)
);
```

### Locations Table
```sql
CREATE TABLE locations (
    loc_id INT PRIMARY KEY AUTO_INCREMENT,
    loc_name VARCHAR(50) UNIQUE NOT NULL
);
```

### Device Types Table
```sql
CREATE TABLE device_types (
    type_id INT PRIMARY KEY AUTO_INCREMENT,
    type_name VARCHAR(50) UNIQUE NOT NULL
);
```

---

## 🎯 Key Points to Remember

1. **OTP is 0002** - Change in `.env` if needed
2. **Tokens expire in 24 hours** - Re-login for new token
3. **All requests except /signup, /login, /update-password need Authorization header**
4. **Devices are user-specific** - User can only control their own devices
5. **Voice commands are case-insensitive** - "Turn On Fan" = "turn on fan"
6. **Location and device_type must match exactly** - Check with `/get_devices`

---

## 📝 Code Examples

### Using Python requests library

```python
import requests

BASE_URL = "http://localhost:5000"

# 1. Sign up
signup_data = {
    "username": "john",
    "email": "john@example.com",
    "password": "pass123",
    "otp": "0002"
}
response = requests.post(f"{BASE_URL}/signup", json=signup_data)
print(response.json())

# 2. Login
login_data = {
    "email": "john@example.com",
    "password": "pass123"
}
response = requests.post(f"{BASE_URL}/login", json=login_data)
token = response.json()["access_token"]

# 3. Add device
headers = {"Authorization": f"Bearer {token}"}
device_data = {
    "location": "bedroom",
    "device_type": "fan",
    "mac_address": "AA:BB:CC:DD:EE:FF"
}
response = requests.post(
    f"{BASE_URL}/add_device",
    files=device_data,
    headers=headers
)
print(response.json())

# 4. Get devices
response = requests.get(f"{BASE_URL}/get_devices", headers=headers)
print(response.json())
```

---

## 🚀 Production Deployment

Before deploying:

1. ✅ Change JWT_KEY to a secure random string
2. ✅ Change OTP_CODE to a secure OTP
3. ✅ Set FLASK_ENV=production
4. ✅ Use strong database password
5. ✅ Enable HTTPS/SSL
6. ✅ Use environment-based configuration
7. ✅ Setup proper logging
8. ✅ Use production WSGI server (Gunicorn)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app_improved:app
```

---

Need help? Check DOCUMENTATION.md for detailed API reference!
