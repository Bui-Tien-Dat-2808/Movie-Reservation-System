import random
import string
import uuid
from io import BytesIO

from captcha.image import ImageCaptcha

from app.dependencies import get_redis

CAPTCHA_TTL_SECONDS = 300
CAPTCHA_CHARS = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"


class CaptchaService:
    @staticmethod
    def _generate_code(length: int = 5) -> str:
        return "".join(random.choices(CAPTCHA_CHARS, k=length))

    @classmethod
    async def create_challenge(cls) -> tuple[str, bytes]:
        """Generate (captcha_id, PNG bytes) and store code in Redis."""
        code = cls._generate_code()
        captcha_id = str(uuid.uuid4())

        redis = await get_redis()
        await redis.set(f"captcha:{captcha_id}", code, ex=CAPTCHA_TTL_SECONDS)

        image = ImageCaptcha(width=220, height=90, fonts=None)
        buf = BytesIO()
        image.write(code, buf, format="PNG")
        return captcha_id, buf.getvalue()

    @classmethod
    async def verify(cls, captcha_id: str, answer: str) -> bool:
        """Verify CAPTCHA answer and delete key immediately (single-use)."""
        if not captcha_id or not answer:
            return False
        redis = await get_redis()
        key = f"captcha:{captcha_id}"
        stored = await redis.get(key)
        await redis.delete(key)  # Delete key immediately regardless of result

        if not stored:
            return False

        stored_str = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
        return stored_str.upper() == answer.strip().upper()
