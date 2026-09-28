"""کلاینت REST پنل PasarGuard.

- احراز هویت: ترجیحاً API Key (هدر X-Api-Key) وگرنه لاگین یوزر/پسورد.
- ساخت یوزر → گرفتن subscription_url → تحویل به خریدار.
- مستندات پنل: https://docs.pasarguard.org
"""
from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("vpnbot.panel")


class PanelError(Exception):
    """خطای پنل (نمایش به ادمین)."""


class PasarPanel:
    def __init__(self, base_url: str, api_key: str = "", username: str = "",
                 password: str = "", timeout: int = 20) -> None:
        self.base = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self.timeout = timeout
        self._token: str | None = None

    # ---------------------------------------------------------- زیرساخت
    async def _login(self, session: aiohttp.ClientSession) -> None:
        """گرفتن JWT با یوزر/پسورد ادمین پنل."""
        if not (self.username and self.password):
            raise PanelError("کلید API یا یوزر/پسورد پنل تنظیم نشده.")
        try:
            async with session.post(
                f"{self.base}/api/admin/token",
                data={"username": self.username, "password": self.password},
                timeout=self.timeout,
            ) as r:
                j = await r.json(content_type=None)
        except Exception as e:
            raise PanelError(f"پنل در دسترس نیست: {e}")
        if r.status != 200 or not j.get("access_token"):
            raise PanelError(f"لاگین پنل ناموفق بود ({r.status}): {j}")
        self._token = j["access_token"]

    async def _headers(self, session: aiohttp.ClientSession) -> dict:
        if self.api_key:
            return {"X-Api-Key": self.api_key}
        if not self._token:
            await self._login(session)
        return {"Authorization": f"Bearer {self._token}"}

    async def _req(self, method: str, path: str, **kwargs) -> dict | None:
        """درخواست با تلاش مجدد خودکار بعد از 401 (توکن منقضی)."""
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in (1, 2):
                headers = await self._headers(session)
                try:
                    async with session.request(method, f"{self.base}{path}",
                                               headers=headers, **kwargs) as r:
                        if r.status == 401 and attempt == 1 and not self.api_key:
                            self._token = None  # توکن مرده؛ دوباره لاگین
                            continue
                        if r.status == 204:
                            return None
                        try:
                            body = await r.json(content_type=None)
                        except Exception:
                            body = {"raw": await r.text()}
                        if r.status >= 400:
                            raise PanelError(f"خطای پنل ({r.status}): {body}")
                        return body
                except PanelError:
                    raise
                except Exception as e:
                    raise PanelError(f"ارتباط با پنل قطع شد: {e}")
        raise PanelError("خطای ناشناخته پنل.")

    # ---------------------------------------------------------- عملیات
    async def test_connection(self) -> str:
        """تست اتصال: گرفتن پروفایل ادمین جاری."""
        me = await self._req("GET", "/api/admin")
        if isinstance(me, dict):
            return me.get("username", "ok")
        return "ok"

    async def create_user(self, username: str, expire_ts: int, data_limit_bytes: int,
                          note: str = "", group_ids: list[int] | None = None) -> dict:
        """ساخت یوزر تازه. expire_ts=0 یعنی بدون انقضا."""
        payload: dict = {"username": username, "expire": expire_ts,
                         "data_limit": data_limit_bytes, "note": note[:500]}
        if group_ids:
            payload["group_ids"] = group_ids
        return await self._req("POST", "/api/user", json=payload)

    async def get_user(self, username: str) -> dict:
        return await self._req("GET", f"/api/user/{username}")

    async def extend_user(self, username: str, expire_ts: int,
                          add_data_bytes: int = 0) -> dict:
        """تمدید: انقضای جدید + (اختیاری) اضافه کردن حجم به سقف فعلی."""
        payload: dict = {"expire": expire_ts}
        if add_data_bytes:
            cur = await self.get_user(username)
            cur_limit = (cur or {}).get("data_limit") or 0
            payload["data_limit"] = cur_limit + add_data_bytes if cur_limit else add_data_bytes
        return await self._req("PUT", f"/api/user/{username}", json=payload)

    async def delete_user(self, username: str) -> None:
        await self._req("DELETE", f"/api/user/{username}")

    def absolute_sub_url(self, resp: dict) -> str:
        """لینک سابسکرایبشن مطلق (اگر نسبی بود با آدرس پنل کامل می‌شود)."""
        u = (resp or {}).get("subscription_url") or ""
        if u.startswith("/"):
            u = self.base + u
        return u
