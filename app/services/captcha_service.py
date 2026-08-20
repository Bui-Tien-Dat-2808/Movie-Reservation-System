import random
import string
import time
import uuid
from io import BytesIO

from captcha.image import ImageCaptcha
import structlog

from app.dependencies import get_redis

logger = structlog.get_logger()

CAPTCHA_TTL_SECONDS = 300
CAPTCHA_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"

_memory_captcha_store: dict[str, tuple[str, float]] = {}


class CaptchaService:
    @staticmethod
    def _generate_code(length: int = 5) -> str:
        return "".join(random.choices(CAPTCHA_CHARS, k=length))

    @classmethod
    async def create_challenge(cls) -> tuple[str, bytes]:
        """Generate (captcha_id, PNG bytes) and store code in Redis (or memory fallback)."""
        code = cls._generate_code()
        captcha_id = str(uuid.uuid4())

        stored_in_redis = False
        try:
            redis = await get_redis()
            await redis.set(f"captcha:{captcha_id}", code, ex=CAPTCHA_TTL_SECONDS)
            stored_in_redis = True
        except Exception as e:
            logger.warning("Redis unavailable for CAPTCHA set, using memory fallback", error=str(e))

        if not stored_in_redis:
            now = time.time()
            expired_keys = [k for k, v in _memory_captcha_store.items() if v[1] < now]
            for k in expired_keys:
                _memory_captcha_store.pop(k, None)
            _memory_captcha_store[captcha_id] = (code, now + CAPTCHA_TTL_SECONDS)

        image = ImageCaptcha(width=220, height=90, fonts=None)
        buf = BytesIO()
        image.write(code, buf, format="PNG")
        return captcha_id, buf.getvalue()

    @classmethod
    async def verify(cls, captcha_id: str, answer: str) -> bool:
        """Verify CAPTCHA answer and delete key immediately (single-use)."""
        if not captcha_id or not answer:
            return False

        stored_code = None
        try:
            redis = await get_redis()
            key = f"captcha:{captcha_id}"
            stored = await redis.get(key)
            await redis.delete(key)
            if stored:
                stored_code = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        except Exception as e:
            logger.warning("Redis verify failed for CAPTCHA, checking memory fallback", error=str(e))

        if not stored_code and captcha_id in _memory_captcha_store:
            code, expires_at = _memory_captcha_store.pop(captcha_id, ("", 0))
            if time.time() < expires_at:
                stored_code = code

        if not stored_code:
            return False

        return stored_code.upper() == answer.strip().upper()
