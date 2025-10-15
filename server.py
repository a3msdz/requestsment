# main.py
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
import sqlite3
import hashlib
import secrets
import uvicorn
from typing import Optional, List
import hmac
import base64
import os

app = FastAPI(title="AwingConnect License Server", version="3.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security - THAY ĐỔI KEY NÀY TRONG MÔI TRƯỜNG PRODUCTION
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")

# Mount static files for admin panel
app.mount("/static", StaticFiles(directory="static"), name="static")

# Helper functions
def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == hashed

def create_session_token(username: str) -> str:
    """Create session token - ĐÃ SỬA LỖI DATABASE LOCK"""
    timestamp = str(int(datetime.now().timestamp()))
    data = f"{username}:{timestamp}"
    signature = base64.b64encode(
        hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).digest()
    ).decode()
    token = f"{signature}:{timestamp}"
    
    # SỬA: Sử dụng connection context manager để tránh database lock
    try:
        conn = sqlite3.connect('licenses.db', timeout=10)  # Thêm timeout
        c = conn.cursor()
        
        # Xóa session cũ của user - SỬA: dùng REPLACE thay vì DELETE + INSERT
        c.execute(
            "INSERT OR REPLACE INTO admin_sessions (session_token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, username, datetime.now().isoformat(), (datetime.now() + timedelta(hours=24)).isoformat())
        )
        
        conn.commit()
        conn.close()
        
        return token
    except sqlite3.Error as e:
        print(f"Database error in create_session_token: {e}")
        # Fallback: tạo token mà không lưu vào database
        return token

def verify_session_token(token: str) -> Optional[str]:
    """Verify session token and return username - ĐÃ SỬA LỖI DATABASE LOCK"""
    try:
        # Tách token và timestamp
        parts = token.split(':')
        if len(parts) != 2:
            return None
            
        token_part, timestamp = parts
        
        # Tìm session trong database - SỬA: dùng connection riêng
        try:
            conn = sqlite3.connect('licenses.db', timeout=10)
            c = conn.cursor()
            c.execute("SELECT username, expires_at FROM admin_sessions WHERE session_token = ?", (token,))
            session_data = c.fetchone()
            conn.close()
        except sqlite3.Error as e:
            print(f"Database error in verify_session_token: {e}")
            return None
        
        if session_data:
            username, expires_at = session_data
            
            # Kiểm tra token hết hạn
            if datetime.now() > datetime.fromisoformat(expires_at):
                # Xóa session hết hạn - SỬA: dùng connection riêng
                try:
                    conn = sqlite3.connect('licenses.db', timeout=10)
                    c = conn.cursor()
                    c.execute("DELETE FROM admin_sessions WHERE session_token = ?", (token,))
                    conn.commit()
                    conn.close()
                except sqlite3.Error:
                    pass  # Bỏ qua lỗi khi xóa session hết hạn
                return None
            
            # Xác thực token signature
            data = f"{username}:{timestamp}"
            expected_token = base64.b64encode(
                hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).digest()
            ).decode()
            
            if hmac.compare_digest(token_part, expected_token):
                return username
    except Exception as e:
        print(f"Token verification error: {e}")
    
    return None
    
# Database setup
def init_db():
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Licenses table
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (key TEXT PRIMARY KEY, created_at TEXT, expires_at TEXT, 
                  is_active INTEGER, hwid TEXT, used_count INTEGER,
                  last_used TEXT, customer_name TEXT, customer_email TEXT)''')
    
    # Chat messages table
    c.execute('''CREATE TABLE IF NOT EXISTS chat_messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT, hwid TEXT, message TEXT, 
                  sender_type TEXT, timestamp TEXT,
                  is_read INTEGER DEFAULT 0)''')
    
    # Admin users table
    c.execute('''CREATE TABLE IF NOT EXISTS admin_users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE, 
                  password_hash TEXT,
                  created_at TEXT,
                  is_active INTEGER DEFAULT 1)''')
    
    # Admin sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS admin_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_token TEXT UNIQUE,
                  username TEXT,
                  created_at TEXT,
                  expires_at TEXT)''')
    
    # Tạo admin mặc định nếu chưa có
    c.execute("SELECT COUNT(*) FROM admin_users WHERE username = 'admin'")
    if c.fetchone()[0] == 0:
        password_hash = hash_password("admin123")
        c.execute("INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
                 ("admin", password_hash, datetime.now().isoformat()))
        print("Default admin user created: admin / admin123")
    
    conn.commit()
    conn.close()

init_db()

# Pydantic models (giữ nguyên từ code của bạn)
class LicenseRequest(BaseModel):
    key: str
    hwid: str

class LicenseCreate(BaseModel):
    days_valid: int = 30
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None

class ChatMessage(BaseModel):
    license_key: Optional[str] = None
    hwid: Optional[str] = None
    message: str
    sender_type: str  # "user" or "admin"

class AdminLogin(BaseModel):
    username: str
    password: str

class AdminCreate(BaseModel):
    username: str
    password: str

class LicenseUpdate(BaseModel):
    is_active: Optional[bool] = None
    days_to_add: Optional[int] = None

def generate_license_key():
    """Generate a secure license key"""
    return f"AWC-{secrets.token_hex(6).upper()}-{secrets.token_hex(4).upper()}"

async def get_current_admin(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # Lấy token từ header "Bearer {token}"
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username = verify_session_token(token)
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username

# Serve admin panel
@app.get("/")
async def serve_admin():
    return FileResponse('static/index.html')

@app.get("/styles.css")
async def serve_css():
    return FileResponse('static/styles.css')

@app.get("/script.js")
async def serve_js():
    return FileResponse('static/script.js')

@app.get("/api/status")
async def server_status():
    """Check server status"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM licenses")
    total_licenses = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE is_active = 1")
    active_licenses = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM chat_messages")
    total_messages = c.fetchone()[0]
    
    conn.close()
    
    return {
        "status": "online",
        "total_licenses": total_licenses,
        "active_licenses": active_licenses,
        "total_messages": total_messages,
        "server_time": datetime.now().isoformat()
    }

@app.post("/api/check_license")
async def check_license(request: LicenseRequest):
    """Validate license key"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM licenses WHERE key = ?", (request.key,))
    license_data = c.fetchone()
    
    if not license_data:
        conn.close()
        raise HTTPException(status_code=404, detail="License key not found")
    
    key, created_at, expires_at, is_active, hwid, used_count, last_used, customer_name, customer_email = license_data
    
    if not is_active:
        conn.close()
        raise HTTPException(status_code=403, detail="License is inactive")
    
    if datetime.now() > datetime.fromisoformat(expires_at):
        conn.close()
        raise HTTPException(status_code=403, detail="License has expired")
    
    # Update usage statistics
    if not hwid:
        c.execute("UPDATE licenses SET hwid = ?, used_count = used_count + 1, last_used = ? WHERE key = ?", 
                 (request.hwid, datetime.now().isoformat(), request.key))
    elif hwid != request.hwid:
        conn.close()
        raise HTTPException(status_code=403, detail="License is already used on another device")
    else:
        c.execute("UPDATE licenses SET used_count = used_count + 1, last_used = ? WHERE key = ?", 
                 (datetime.now().isoformat(), request.key))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "valid",
        "expires_at": expires_at,
        "created_at": created_at,
        "customer_name": customer_name,
        "days_remaining": (datetime.fromisoformat(expires_at) - datetime.now()).days
    }

@app.post("/api/create_license")
async def create_license(data: LicenseCreate):
    """Create a new license"""
    license_key = generate_license_key()
    created_at = datetime.now()
    expires_at = created_at + timedelta(days=data.days_valid)
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("""INSERT INTO licenses 
                 (key, created_at, expires_at, is_active, hwid, used_count, last_used, customer_name, customer_email) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (license_key, created_at.isoformat(), expires_at.isoformat(), 1, "", 0, None, data.customer_name, data.customer_email))
    
    conn.commit()
    conn.close()
    
    return {
        "license_key": license_key,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "customer_name": data.customer_name,
        "days_valid": data.days_valid
    }

@app.post("/api/send_message")
async def send_message(message: ChatMessage):
    """Send a chat message - ĐÃ SỬA ĐỂ LƯU ĐÚNG DATABASE"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    try:
        # Kiểm tra license có tồn tại không (nếu có license_key)
        if message.license_key:
            c.execute("SELECT * FROM licenses WHERE key = ?", (message.license_key,))
            license_data = c.fetchone()
            if not license_data:
                conn.close()
                raise HTTPException(status_code=404, detail="License not found")
        
        # Lưu tin nhắn vào database
        c.execute("""INSERT INTO chat_messages 
                     (license_key, hwid, message, sender_type, timestamp) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (message.license_key, message.hwid, message.message, 
                   message.sender_type, datetime.now().isoformat()))
        
        message_id = c.lastrowid
        conn.commit()
        
        print(f"DEBUG: Message saved - ID: {message_id}, License: {message.license_key}, Sender: {message.sender_type}")  # Debug log
        
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    conn.close()
    
    return {
        "status": "success",
        "message_id": message_id,
        "message": "Message sent successfully"
    }

@app.get("/api/get_messages")
async def get_messages(license_key: Optional[str] = None, hwid: Optional[str] = None):
    """Get chat messages - ĐÃ SỬA ĐỂ LẤY ĐÚNG DỮ LIỆU"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    try:
        if license_key:
            # Lấy tin nhắn theo license_key
            c.execute("""SELECT * FROM chat_messages 
                         WHERE license_key = ? 
                         ORDER BY timestamp ASC""", (license_key,))
        elif hwid:
            # Lấy tin nhắn theo hwid
            c.execute("""SELECT * FROM chat_messages 
                         WHERE hwid = ? 
                         ORDER BY timestamp ASC""", (hwid,))
        else:
            # Lấy tất cả tin nhắn (cho admin)
            c.execute("""SELECT * FROM chat_messages 
                         ORDER BY timestamp ASC""")
        
        messages = c.fetchall()
        
        print(f"DEBUG: Found {len(messages)} messages for license_key: {license_key}")  # Debug log
        
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    conn.close()
    
    return {
        "messages": [
            {
                "id": m[0],
                "license_key": m[1],
                "hwid": m[2],
                "message": m[3],
                "sender_type": m[4],
                "timestamp": m[5],
                "is_read": bool(m[6])
            } for m in messages
        ]
    }
@app.post("/api/messages/{message_id}/mark_read")
async def mark_message_read(message_id: int):
    """Mark message as read"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("UPDATE chat_messages SET is_read = 1 WHERE id = ?", (message_id,))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Message not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Message marked as read"}

@app.get("/api/get_active_users")
async def get_active_users(current_admin: str = Depends(get_current_admin)):
    """Get list of active users with their chat status - ENDPOINT MỚI"""
    conn = sqlite3.connect('licenses.db', timeout=10)
    c = conn.cursor()
    
    try:
        # Lấy tất cả license đang active
        c.execute("""
            SELECT key, hwid, last_used 
            FROM licenses 
            WHERE is_active = 1 AND hwid IS NOT NULL AND hwid != ''
        """)
        licenses = c.fetchall()
        
        active_users = []
        
        for license_key, hwid, last_used in licenses:
            # Kiểm tra tin nhắn chưa đọc
            c.execute("""
                SELECT COUNT(*) FROM chat_messages 
                WHERE license_key = ? AND sender_type = 'user' AND is_read = 0
            """, (license_key,))
            unread_count = c.fetchone()[0]
            
            # Lấy tin nhắn cuối cùng
            c.execute("""
                SELECT message FROM chat_messages 
                WHERE license_key = ? 
                ORDER BY timestamp DESC LIMIT 1
            """, (license_key,))
            last_message_data = c.fetchone()
            last_message = last_message_data[0] if last_message_data else None
            
            # Kiểm tra online status (nếu last_used trong 5 phút gần đây)
            is_online = False
            if last_used:
                last_used_time = datetime.fromisoformat(last_used)
                time_diff = datetime.now() - last_used_time
                is_online = time_diff.total_seconds() < 300  # 5 minutes
            
            active_users.append({
                'license_key': license_key,
                'hwid': hwid,
                'last_seen': last_used or datetime.now().isoformat(),
                'is_online': is_online,
                'unread_count': unread_count,
                'last_message': last_message
            })
        
        # Sắp xếp: có tin nhắn chưa đọc lên đầu, sau đó theo thời gian
        active_users.sort(key=lambda x: (-x['unread_count'], x['last_seen']), reverse=True)
        
        conn.close()
        
        return {
            "users": active_users
        }
        
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    
@app.post("/api/mark_messages_read")
async def mark_messages_read(data: dict, current_admin: str = Depends(get_current_admin)):
    """Mark messages as read for a specific license"""
    license_key = data.get('license_key')
    
    if not license_key:
        raise HTTPException(status_code=400, detail="License key is required")
    
    conn = sqlite3.connect('licenses.db', timeout=10)
    c = conn.cursor()
    
    try:
        c.execute("""
            UPDATE chat_messages 
            SET is_read = 1 
            WHERE license_key = ? AND sender_type = 'user'
        """, (license_key,))
        
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": "Messages marked as read"}
        
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
# Admin endpoints
@app.post("/api/admin/login")
async def admin_login(login: AdminLogin):
    """Admin login - ĐÃ SỬA LỖI DATABASE LOCK"""
    try:
        conn = sqlite3.connect('licenses.db', timeout=10)  # Thêm timeout
        c = conn.cursor()
        
        c.execute("SELECT * FROM admin_users WHERE username = ? AND is_active = 1", (login.username,))
        admin_data = c.fetchone()
        
        if not admin_data or not verify_password(login.password, admin_data[2]):
            conn.close()
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Tạo session token - SỬA: tách riêng database operation
        access_token = create_session_token(login.username)
        
        conn.close()
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "username": login.username
        }
    except sqlite3.Error as e:
        print(f"Database error in admin_login: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        print(f"Unexpected error in admin_login: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/admin/logout")
async def admin_logout(current_admin: str = Depends(get_current_admin)):
    """Admin logout"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Xóa session của user hiện tại
    c.execute("DELETE FROM admin_sessions WHERE username = ?", (current_admin,))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Logged out successfully"}

@app.post("/api/admin/create_user")
async def create_admin_user(user: AdminCreate, current_admin: str = Depends(get_current_admin)):
    """Create new admin user"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Check if username already exists
    c.execute("SELECT COUNT(*) FROM admin_users WHERE username = ?", (user.username,))
    if c.fetchone()[0] > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Create new admin user
    password_hash = hash_password(user.password)
    c.execute("INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
             (user.username, password_hash, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "message": f"Admin user '{user.username}' created successfully"
    }

@app.get("/api/admin/users")
async def get_admin_users(current_admin: str = Depends(get_current_admin)):
    """Get all admin users"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT id, username, created_at, is_active FROM admin_users")
    users = c.fetchall()
    conn.close()
    
    return {
        "users": [
            {
                "id": u[0],
                "username": u[1],
                "created_at": u[2],
                "is_active": bool(u[3])
            } for u in users
        ]
    }

@app.delete("/api/admin/users/{username}")
async def delete_admin_user(username: str, current_admin: str = Depends(get_current_admin)):
    """Delete admin user (cannot delete yourself)"""
    if username == current_admin:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("DELETE FROM admin_users WHERE username = ?", (username,))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": f"User '{username}' deleted successfully"}

@app.get("/api/admin/stats")
async def get_admin_stats(current_admin: str = Depends(get_current_admin)):
    """Get admin statistics"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # License stats
    c.execute("SELECT COUNT(*) FROM licenses")
    total_licenses = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE is_active = 1")
    active_licenses = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE datetime(expires_at) < datetime('now')")
    expired_licenses = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE hwid != '' AND hwid IS NOT NULL")
    activated_licenses = c.fetchone()[0]
    
    # Chat stats
    c.execute("SELECT COUNT(*) FROM chat_messages")
    total_messages = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM chat_messages WHERE is_read = 0")
    unread_messages = c.fetchone()[0]
    
    # User stats
    c.execute("SELECT COUNT(*) FROM admin_users")
    total_admins = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM admin_users WHERE is_active = 1")
    active_admins = c.fetchone()[0]
    
    # Recent activity
    c.execute("SELECT COUNT(*) FROM licenses WHERE datetime(last_used) > datetime('now', '-7 days')")
    recent_activity = c.fetchone()[0]
    
    conn.close()
    
    return {
        "licenses": {
            "total": total_licenses,
            "active": active_licenses,
            "expired": expired_licenses,
            "activated": activated_licenses
        },
        "chat": {
            "total_messages": total_messages,
            "unread_messages": unread_messages
        },
        "admins": {
            "total": total_admins,
            "active": active_admins
        },
        "recent_activity": recent_activity,
        "server_time": datetime.now().isoformat()
    }

@app.get("/api/licenses")
async def get_licenses(active_only: bool = False):
    """Get all licenses"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    if active_only:
        c.execute("SELECT * FROM licenses WHERE is_active = 1")
    else:
        c.execute("SELECT * FROM licenses")
    
    licenses = c.fetchall()
    conn.close()
    
    return {
        "licenses": [
            {
                "key": l[0],
                "created_at": l[1],
                "expires_at": l[2],
                "is_active": bool(l[3]),
                "hwid": l[4],
                "used_count": l[5],
                "last_used": l[6],
                "customer_name": l[7],
                "customer_email": l[8],
                "is_expired": datetime.now() > datetime.fromisoformat(l[2]) if l[2] else False
            } for l in licenses
        ]
    }

@app.put("/api/licenses/{license_key}")
async def update_license(license_key: str, update: LicenseUpdate):
    """Update license information"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM licenses WHERE key = ?", (license_key,))
    license_data = c.fetchone()
    
    if not license_data:
        conn.close()
        raise HTTPException(status_code=404, detail="License not found")
    
    updates = []
    params = []
    
    if update.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if update.is_active else 0)
    
    if update.days_to_add is not None and update.days_to_add > 0:
        current_expires = datetime.fromisoformat(license_data[2])
        new_expires = current_expires + timedelta(days=update.days_to_add)
        updates.append("expires_at = ?")
        params.append(new_expires.isoformat())
    
    if updates:
        query = f"UPDATE licenses SET {', '.join(updates)} WHERE key = ?"
        params.append(license_key)
        c.execute(query, params)
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "License updated successfully"}

@app.delete("/api/licenses/{license_key}")
async def delete_license(license_key: str):
    """Delete a license"""
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("DELETE FROM licenses WHERE key = ?", (license_key,))
    
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="License not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "License deleted successfully"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
