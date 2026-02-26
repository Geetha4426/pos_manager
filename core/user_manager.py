"""
Multi-User Manager with Encrypted Key Storage

Handles:
- User registration with encrypted private key storage
- AES-256-GCM encryption (password-based, PBKDF2 key derivation)
- Per-user ClobClient instances
- Session management (auto-lock after timeout)

Security model:
- Private keys encrypted with user's password before storage
- Password is NEVER stored — only used to derive encryption key
- Encrypted blob stored in SQLite — useless without password
- Decryption happens in-memory only, during order signing
- Telegram message containing key is immediately deleted
"""

import os
import time
import hashlib
import secrets
import asyncio
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

import aiosqlite

# Encryption imports
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

try:
    from py_clob_client.client import ClobClient
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# ENCRYPTION HELPERS
# ═══════════════════════════════════════════════════════════════════

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,  # 256 bits
        salt=salt,
        iterations=480000,  # OWASP recommended minimum
    )
    return kdf.derive(password.encode('utf-8'))


def encrypt_private_key(private_key: str, password: str) -> str:
    """Encrypt a private key with a password.
    
    Returns: base64-encoded string containing salt + nonce + ciphertext
    Format: base64(salt[16] + nonce[12] + ciphertext[...])
    """
    salt = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    
    ciphertext = aesgcm.encrypt(nonce, private_key.encode('utf-8'), None)
    
    # Pack: salt + nonce + ciphertext
    packed = salt + nonce + ciphertext
    return base64.b64encode(packed).decode('utf-8')


def decrypt_private_key(encrypted: str, password: str) -> Optional[str]:
    """Decrypt a private key with password.
    
    Returns: plaintext private key, or None if password is wrong
    """
    try:
        packed = base64.b64decode(encrypted.encode('utf-8'))
        salt = packed[:16]
        nonce = packed[16:28]
        ciphertext = packed[28:]
        
        key = _derive_key(password, salt)
        aesgcm = AESGCM(key)
        
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except Exception:
        return None  # Wrong password or corrupted data


# ═══════════════════════════════════════════════════════════════════
# USER SESSION
# ═══════════════════════════════════════════════════════════════════

@dataclass
class UserSession:
    """Active user session with decrypted ClobClient."""
    telegram_id: int
    funder_address: str
    clob_client: Optional[object] = None  # ClobClient instance
    last_activity: float = 0.0
    session_start: float = 0.0
    
    # Cached data
    display_name: str = ""
    signature_type: int = 1
    
    @property
    def is_expired(self) -> bool:
        """Session expires after configured timeout of inactivity."""
        timeout = Config.SESSION_TIMEOUT if hasattr(Config, 'SESSION_TIMEOUT') else 1800
        return (time.time() - self.last_activity) > timeout
    
    def touch(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()


# ═══════════════════════════════════════════════════════════════════
# USER MANAGER
# ═══════════════════════════════════════════════════════════════════

class UserManager:
    """Manages multi-user encrypted key storage and sessions.
    
    Flow:
    1. User sends /connect → enters private key + password
    2. Key encrypted with password, stored in DB
    3. User sends /unlock <password> → key decrypted, ClobClient created
    4. User trades normally (session active)
    5. Session auto-expires after 30 min inactivity
    6. User sends /lock → session destroyed immediately
    """
    
    def __init__(self):
        self._db_path = Config.USERS_DB_PATH if hasattr(Config, 'USERS_DB_PATH') else Config.DATABASE_PATH.replace('favorites.db', 'users.db')
        self._sessions: Dict[int, UserSession] = {}  # telegram_id -> session
        self._db_initialized = False
    
    async def _init_db(self):
        """Initialize the users database."""
        if self._db_initialized:
            return
        
        os.makedirs(os.path.dirname(self._db_path) or '.', exist_ok=True)
        
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    encrypted_key TEXT NOT NULL,
                    funder_address TEXT DEFAULT '',
                    signature_type INTEGER DEFAULT 1,
                    display_name TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT DEFAULT NULL
                )
            ''')
            await db.commit()
        
        self._db_initialized = True
    
    async def register_user(
        self,
        telegram_id: int,
        private_key: str,
        password: str,
        funder_address: str = '',
        signature_type: int = 1,
        display_name: str = ''
    ) -> Tuple[bool, str]:
        """Register a new user with encrypted private key.
        
        Returns: (success, message)
        """
        await self._init_db()
        
        # Validate private key format (basic check)
        key_clean = private_key.strip()
        if key_clean.startswith('0x'):
            key_clean = key_clean[2:]
        if len(key_clean) != 64:
            return False, "Invalid private key format. Must be 64 hex characters (with or without 0x prefix)."
        
        # Validate password strength
        if len(password) < 6:
            return False, "Password too short. Use at least 6 characters."
        
        # Encrypt the private key
        encrypted = encrypt_private_key(private_key.strip(), password)
        
        # Verify encryption worked (decrypt test)
        test = decrypt_private_key(encrypted, password)
        if test != private_key.strip():
            return False, "Encryption verification failed. Please try again."
        
        # Store in database
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO users 
                    (telegram_id, encrypted_key, funder_address, signature_type, display_name)
                    VALUES (?, ?, ?, ?, ?)
                ''', (telegram_id, encrypted, funder_address, signature_type, display_name))
                await db.commit()
            
            return True, "Wallet connected and encrypted successfully!"
        except Exception as e:
            return False, f"Database error: {e}"
    
    async def unlock_session(
        self,
        telegram_id: int,
        password: str
    ) -> Tuple[bool, str]:
        """Unlock a user session by decrypting their key and creating ClobClient.
        
        Returns: (success, message)
        """
        await self._init_db()
        
        # Check if already unlocked
        if telegram_id in self._sessions and not self._sessions[telegram_id].is_expired:
            self._sessions[telegram_id].touch()
            return True, "Session already active!"
        
        # Fetch encrypted key from DB
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    'SELECT encrypted_key, funder_address, signature_type, display_name FROM users WHERE telegram_id = ?',
                    (telegram_id,)
                )
                row = await cursor.fetchone()
                
                if not row:
                    return False, "No wallet connected. Use /connect first."
                
                encrypted_key, funder_address, sig_type, display_name = row
        except Exception as e:
            return False, f"Database error: {e}"
        
        # Decrypt private key
        private_key = decrypt_private_key(encrypted_key, password)
        if not private_key:
            return False, "Wrong password. Try again."
        
        # Create ClobClient for this user
        try:
            clob_url = Config.get_clob_url()
            
            funder = funder_address if funder_address else None
            
            clob_client = ClobClient(
                clob_url,
                key=private_key,
                chain_id=Config.POLYGON_CHAIN_ID,
                signature_type=sig_type,
                funder=funder
            )
            
            # Inject relay auth if needed
            if Config.is_relay_enabled() and Config.CLOB_RELAY_AUTH_TOKEN:
                try:
                    session = getattr(clob_client, 'session', None)
                    if session and hasattr(session, 'headers'):
                        session.headers['Authorization'] = f'Bearer {Config.CLOB_RELAY_AUTH_TOKEN}'
                except Exception:
                    pass
            
            clob_client.set_api_creds(clob_client.create_or_derive_api_creds())
            
            # Create session
            session = UserSession(
                telegram_id=telegram_id,
                funder_address=funder_address or clob_client.get_address(),
                clob_client=clob_client,
                last_activity=time.time(),
                session_start=time.time(),
                display_name=display_name,
                signature_type=sig_type
            )
            
            self._sessions[telegram_id] = session
            
            # Update last login
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    await db.execute(
                        'UPDATE users SET last_login = ? WHERE telegram_id = ?',
                        (datetime.now().isoformat(), telegram_id)
                    )
                    await db.commit()
            except Exception:
                pass
            
            # Clear the decrypted key from local variable
            private_key = None
            
            return True, f"Session unlocked! Wallet: `{session.funder_address[:8]}...{session.funder_address[-4:]}`"
            
        except Exception as e:
            private_key = None  # Clear on error too
            return False, f"Failed to initialize wallet: {e}"
    
    def get_session(self, telegram_id: int) -> Optional[UserSession]:
        """Get active session for a user. Returns None if locked/expired."""
        session = self._sessions.get(telegram_id)
        if session is None:
            return None
        if session.is_expired:
            self.lock_session(telegram_id)
            return None
        session.touch()
        return session
    
    def get_clob_client(self, telegram_id: int) -> Optional[object]:
        """Get ClobClient for a user. Returns None if not unlocked."""
        session = self.get_session(telegram_id)
        return session.clob_client if session else None
    
    def lock_session(self, telegram_id: int) -> bool:
        """Lock a user session (destroy ClobClient, clear from memory)."""
        if telegram_id in self._sessions:
            session = self._sessions[telegram_id]
            session.clob_client = None
            del self._sessions[telegram_id]
            return True
        return False
    
    async def is_registered(self, telegram_id: int) -> bool:
        """Check if a user has a connected wallet."""
        await self._init_db()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    'SELECT 1 FROM users WHERE telegram_id = ?',
                    (telegram_id,)
                )
                return await cursor.fetchone() is not None
        except Exception:
            return False
    
    def is_unlocked(self, telegram_id: int) -> bool:
        """Check if user has an active (unlocked) session."""
        return self.get_session(telegram_id) is not None
    
    async def delete_user(self, telegram_id: int) -> bool:
        """Delete a user's encrypted key and session."""
        self.lock_session(telegram_id)
        await self._init_db()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
                await db.commit()
            return True
        except Exception:
            return False
    
    async def get_user_count(self) -> int:
        """Get total registered users."""
        await self._init_db()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute('SELECT COUNT(*) FROM users')
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0
    
    def get_active_session_count(self) -> int:
        """Get count of active (unlocked) sessions."""
        # Clean up expired sessions
        expired = [tid for tid, s in self._sessions.items() if s.is_expired]
        for tid in expired:
            self.lock_session(tid)
        return len(self._sessions)
    
    async def cleanup_expired(self):
        """Clean up expired sessions (call periodically)."""
        expired = [tid for tid, s in self._sessions.items() if s.is_expired]
        for tid in expired:
            self.lock_session(tid)
        if expired:
            print(f"🔒 Auto-locked {len(expired)} expired sessions")


# ═══════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════

_user_manager: Optional[UserManager] = None

def get_user_manager() -> UserManager:
    """Get the UserManager singleton."""
    global _user_manager
    if _user_manager is None:
        _user_manager = UserManager()
    return _user_manager
