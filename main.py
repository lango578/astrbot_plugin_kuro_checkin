# -*- coding: utf-8 -*-
"""
AstrBot 插件：库街区每日签到

每天自动在库街区进行每日签到，支持：
1. 鸣潮游戏签到（gameId=3）
2. 战双游戏签到（gameId=2）
3. 库街区社区签到（user/signIn，获得库洛币）
4. （可选）论坛每日任务（浏览/点赞/分享）

聊天指令：
/库街区登录 <手机号>   自动登录（自动过GeeTest滑块 → 发短信 → 回复验证码即可登录+签到）
/库街区绑定 <token>   绑定库街区 token（登录 www.kurobbs.com 后 F12 → Cookie → user_token）
/库街区签到           手动执行每日签到
/库街区解绑           清除已绑定的 token
/库街区状态           查看绑定状态
/库街区帮助           查看帮助

说明：
- token 只在 AstrBot 本地配置中保存，不会上传。
- 自动签到时间可在 AstrBot WebUI 的插件配置中调整（默认 07:30，服务器时区）。
- 自动签到完成后会把结果推送到你绑定/签到时所在的会话。
- 注：库街区已停用网页端「扫码登录」，本插件提供「手机号+短信验证码」登录方式。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

# 将插件目录加入 sys.path，保证可以 import geeked 滑块求解模块
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


# ---------------------------------------------------------------------------
# 库街区 API 常量
# ---------------------------------------------------------------------------

API_BASE = "https://api.kurobbs.com"

# GeeTest v4 服务端点（与 geeked/geeked.py 保持一致，此处显式拼绝对 URL，
# 不再依赖 session.base_url 这个非标准属性）
GEETEST_BASE = "https://gcaptcha4.geevisit.com"

ENDPOINTS = {
    "user_mine": f"{API_BASE}/user/mineV2",
    "user_sign_in": f"{API_BASE}/user/signIn",
    "role_list": f"{API_BASE}/gamer/role/list",
    "role_list_fallback": f"{API_BASE}/user/role/findRoleList",
    "forum_list": f"{API_BASE}/forum/list",
    "post_detail": f"{API_BASE}/forum/getPostDetail",
    "forum_like": f"{API_BASE}/forum/like",
    "task_share": f"{API_BASE}/encourage/level/shareTask",
    "gold_total": f"{API_BASE}/encourage/gold/getTotalGold",
    "game_sign_in": f"{API_BASE}/encourage/signIn/v2",
    "game_sign_record": f"{API_BASE}/encourage/signIn/queryRecordV2",
}

# gameId：战双=2，鸣潮=3
GAMES = {
    "wuwa": {"id": "3", "name": "鸣潮", "server_id": "7f574e49b1f24c4c915e74bb1dfd4e4d"},
    "pgr": {"id": "2", "name": "战双", "server_id": "1000"},
}

HELP_TEXT = (
    "【库街区每日签到】\n"
    "/库街区登录 <手机号>  一键登录（自动过滑块→发短信→回复验证码）\n"
    "                  已绑定要换号时：/库街区登录 确认 <手机号>\n"
    "/库街区绑定 <token>  绑定 token（登录 www.kurobbs.com → F12 → Cookie → user_token）\n"
    "/库街区签到          立即执行每日签到（鸣潮/战双 + 社区）\n"
    "/库街区解绑          清除 token\n"
    "/库街区状态          查看绑定与自动签到状态\n"
    "/库街区帮助          查看本帮助\n"
    "自动签到时间在 AstrBot WebUI 插件配置中调整，默认 07:30。"
)

# 库街区接口错误码
ERR_SUCCESS = 200
ERR_ALREADY_SIGNED = 1511
ERR_USER_INFO_ERROR = 1513
ERR_LOGIN_EXPIRED = 220

# 登录（H5 版）使用的固定设备标识，保证登录与后续签到设备一致
LOGIN_DEVCODE = "QZlE9fzPUlHON9FGUsfLfWwyM2dRKr6K"
LOGIN_DISTINCT_ID = "19dafdce461609-023472cbe40c9b-1e462c69-2073600-19dafdce462ebd"

# 等待用户回复短信验证码的超时时间（秒）
PENDING_TIMEOUT = 120

# 同一用户两次申请短信的最小间隔（秒），防止被当作群发短信工具
SMS_COOLDOWN = 90


def _h5_login_headers() -> dict:
    """H5 版登录接口请求头（配合 sdkLoginForH5 / getSmsCodeForH5 使用）。"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.kurobbs.com",
        "Referer": "https://www.kurobbs.com/",
        "source": "h5",
        "version": "3.0.1",
        "devCode": LOGIN_DEVCODE,
        "distinct_id": LOGIN_DISTINCT_ID,
        "sec-ch-ua": '"Google Chrome";v="126", "Chromium";v="126", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

def _h5_headers(token: str, devcode: str, distinct_id: str) -> dict:
    """构造与网页版库街区一致的 H5 请求头。"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Host": "api.kurobbs.com",
        "Origin": "https://www.kurobbs.com",
        "Referer": "https://www.kurobbs.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "source": "h5",
        "version": "3.0.1",
        "devCode": devcode,
        "distinct_id": distinct_id,
        "token": token,
    }


class KuroClient:
    """库街区 API 异步客户端（H5 版请求头）。"""

    def __init__(self, token: str, devcode: str = "", distinct_id: str = ""):
        self.token = token.strip()
        # 缺设备标识时落到与 H5 登录同一个常量，而不是每次随机 —— 随机值会让
        # 「登录设备」与「签到设备」不一致，属于被风控的常见诱因
        self.devcode = devcode or LOGIN_DEVCODE
        self.distinct_id = distinct_id or LOGIN_DISTINCT_ID
        if not devcode or not distinct_id:
            logger.warning("【库街区签到】KuroClient 未取得设备标识，已回落到登录用常量")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def post(self, url: str, data: dict | None = None) -> dict:
        """统一的 POST 请求，返回 JSON 字典（网络异常时返回 -1 code）。"""
        client = await self._get_client()
        try:
            resp = await client.post(
                url,
                headers=_h5_headers(self.token, self.devcode, self.distinct_id),
                data=data or {},
                timeout=30,
            )
        except httpx.HTTPError as e:
            return {"code": -1, "msg": f"网络请求失败: {e}", "success": False}
        try:
            return resp.json()
        except Exception:
            return {"code": -1, "msg": f"响应解析失败: HTTP {resp.status_code}", "success": False}

    async def get_user_id(self) -> str:
        """获取库街区 userId（用于展示，失败不阻塞签到）。"""
        try:
            result = await self.post(ENDPOINTS["user_mine"], {"size": "10"})
            if result.get("code") == ERR_SUCCESS and result.get("data"):
                uid = result["data"].get("mine", {}).get("userId")
                if uid:
                    return str(uid)
        except Exception as e:
            logger.warning(f"获取 userId 失败: {e}")
        return ""

    async def get_role_info(self, game_id: str) -> dict:
        """获取某游戏的角色信息，返回 {roleId, serverId, roleName} 或空字典。"""
        for endpoint in (ENDPOINTS["role_list"], ENDPOINTS["role_list_fallback"]):
            try:
                result = await self.post(endpoint, {"gameId": game_id})
                code = result.get("code", -1)
                if code == ERR_LOGIN_EXPIRED:
                    return {"expired": True}
                if code == ERR_SUCCESS and result.get("data"):
                    data = result["data"]
                    role_list = data if isinstance(data, list) else data.get("roleList", [])
                    if isinstance(role_list, list) and role_list:
                        r = role_list[0]
                        return {
                            "roleId": str(r.get("roleId", "")),
                            "serverId": str(r.get("serverId", "")),
                            "roleName": str(r.get("roleName", "")),
                        }
            except Exception as e:
                logger.warning(f"获取角色信息失败（{endpoint}）: {e}")
        return {}

    async def game_sign(self, game: dict, role_info: dict) -> str:
        """执行单个游戏签到，返回结果文本。"""
        data = {
            "gameId": game["id"],
            "serverId": role_info.get("serverId", game["server_id"]),
            "roleId": role_info.get("roleId", ""),
            "reqMonth": datetime.now().strftime("%m"),
        }
        result = await self.post(ENDPOINTS["game_sign_in"], data)
        code = result.get("code", -1)
        msg = result.get("msg", result.get("message", "未知错误"))
        if code == ERR_SUCCESS:
            reward = await self.query_sign_reward(game, role_info)
            return f"✅ {game['name']} 签到成功{('，奖励: ' + reward) if reward else ''}"
        if code == ERR_ALREADY_SIGNED:
            return f"ℹ️ {game['name']} 今天已签到"
        if code == ERR_LOGIN_EXPIRED:
            return f"❌ {game['name']} 登录已过期，请重新绑定 token"
        if code == ERR_USER_INFO_ERROR:
            return f"❌ {game['name']} 签到失败：用户信息异常"
        return f"❌ {game['name']} 签到失败：{msg} (code:{code})"

    async def query_sign_reward(self, game: dict, role_info: dict) -> str:
        """查询今日签到奖励名称（尽力而为，失败返回空串）。"""
        try:
            data = {
                "gameId": game["id"],
                "serverId": role_info.get("serverId", game["server_id"]),
                "roleId": role_info.get("roleId", ""),
            }
            result = await self.post(ENDPOINTS["game_sign_record"], data)
            if result.get("code") == ERR_SUCCESS and result.get("data"):
                records = result["data"]
                if isinstance(records, list) and records:
                    return str(records[0].get("goodsName", ""))
        except Exception as e:
            logger.debug(f"【库街区签到】查询签到奖励失败: {e}")
        return ""

    async def forum_sign(self) -> str:
        """库街区社区签到（获得库洛币）。"""
        try:
            result = await self.post(ENDPOINTS["user_sign_in"], {"gameId": "3"})
            code = result.get("code", -1)
            if code == ERR_SUCCESS or result.get("success"):
                data = result.get("data") or {}
                days = data.get("continueDays")
                return f"✅ 社区签到成功{('，连签 ' + str(days) + ' 天') if days else ''}"
            if code == ERR_ALREADY_SIGNED:
                return "ℹ️ 社区今天已签到"
            if code == ERR_LOGIN_EXPIRED:
                return "❌ 社区签到：登录已过期，请重新绑定 token"
            return f"❌ 社区签到失败：{result.get('msg', '未知错误')} (code:{code})"
        except Exception as e:
            return f"❌ 社区签到异常：{e}"

    async def forum_tasks(self) -> List[str]:
        """执行论坛每日任务：浏览帖子、点赞、分享。"""
        results: list[str] = []
        # 1. 获取帖子列表
        try:
            resp = await self.post(
                ENDPOINTS["forum_list"],
                {
                    "forumId": "9",
                    "gameId": "3",
                    "pageIndex": "1",
                    "pageSize": "20",
                    "searchType": "3",
                    "timeType": "0",
                },
            )
            posts = []
            if resp.get("success") and resp.get("data"):
                posts = resp["data"].get("postList", []) or []
        except Exception:
            posts = []
        if not posts:
            results.append("⚠️ 获取帖子列表失败，跳过论坛任务")
            return results
        # 2. 浏览 3 篇
        view_count = 0
        for post in posts[:3]:
            try:
                await self.post(
                    ENDPOINTS["post_detail"],
                    {
                        "isOnlyPublisher": "0",
                        "postId": str(post["postId"]),
                        "showOrderTyper": "2",
                    },
                )
                view_count += 1
            except Exception:
                pass
            await asyncio.sleep(1)
        results.append(f"📖 浏览帖子 {view_count}/3")
        # 3. 点赞 5 篇
        like_count = 0
        for post in posts[:5]:
            try:
                like_data = {
                    "forumId": 11,
                    "gameId": 3,
                    "likeType": 1,
                    "operateType": 1,
                    "postCommentId": "",
                    "postCommentReplyId": "",
                    "postId": str(post["postId"]),
                    "postType": 1,
                    "toUserId": str(post.get("userId", "")),
                }
                resp = await self.post(ENDPOINTS["forum_like"], like_data)
                if resp.get("success") or resp.get("code") == ERR_SUCCESS:
                    like_count += 1
            except Exception:
                pass
            await asyncio.sleep(1)
        results.append(f"👍 点赞 {like_count}/5")
        # 4. 分享
        try:
            resp = await self.post(ENDPOINTS["task_share"], {"gameId": 3})
            if resp.get("success") or resp.get("code") == ERR_SUCCESS:
                results.append("🔗 分享成功")
            else:
                results.append("🔗 分享失败")
        except Exception:
            results.append("🔗 分享异常")
        return results

    async def gold_total(self) -> str:
        """查询当前库洛币数量。"""
        try:
            resp = await self.post(ENDPOINTS["gold_total"], {})
            if resp.get("success") and resp.get("data"):
                gold = resp["data"].get("goldNum", 0)
                return f"💰 当前库洛币: {gold}"
        except Exception as e:
            logger.debug(f"【库街区签到】查询库洛币失败: {e}")
        return ""


# ---------------------------------------------------------------------------
# AstrBot 插件入口
# ---------------------------------------------------------------------------

@register(
    "astrbot_plugin_kuro_checkin",
    "AstrBot User",
    "每天自动在库街区进行每日签到（鸣潮/战双+社区）",
    "1.2.0",
)
class KuroCheckinPlugin(Star):
    """库街区每日签到插件。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._auto_task: Optional[asyncio.Task] = None
        self._sms_last: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self):
        """插件加载后自动调用：启动每日定时签到任务。"""
        try:
            self._ensure_device()
        except Exception as e:
            logger.error(f"【库街区签到】初始化设备信息失败: {e}")
        if self.config.get("auto_sign_enable", True):
            if self._auto_task is not None and not self._auto_task.done():
                # 重复加载时先取消旧任务，避免留下游离协程
                await self.terminate()
            self._auto_task = asyncio.create_task(self._auto_sign_loop())
            logger.info("【库街区签到】每日自动签到任务已启动")
        logger.info("【库街区签到】插件初始化完成")

    async def terminate(self):
        """插件卸载/停用时调用。"""
        task, self._auto_task = self._auto_task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Python 3.8+ 起 CancelledError 继承 BaseException，except Exception 接不住
                pass
            except Exception as e:
                logger.warning(f"【库街区签到】停止自动签到任务时出现异常: {e}")

    # ------------------------------------------------------------------
    # 配置辅助
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        return str(self.config.get("token", "") or "").strip()

    # ------------------------------------------------------------------
    # 权限与审计
    # ------------------------------------------------------------------

    def _operator_ids(self) -> Set[str]:
        """读取白名单（兼容 str / list 两种配置写法）。"""
        raw = self.config.get("operators", "") or ""
        if isinstance(raw, str):
            items = re.split(r"[,\s;，、]+", raw)
        elif isinstance(raw, (list, tuple, set)):
            items = [str(x) for x in raw]
        else:
            items = [str(raw)]
        return {x.strip() for x in items if str(x).strip()}

    def _is_operator(self, event: AstrMessageEvent) -> Tuple[bool, str]:
        """写操作（登录/绑定/解绑）与手动签到的权限判定。"""
        if self.config.get("allow_all_users", True):
            return True, ""
        sender = str(event.get_sender_id() or "")
        allowed = self._operator_ids()
        if not allowed:
            logger.error("【库街区签到】allow_all_users=false 但 operators 为空，所有指令被拒绝")
            return False, (
                "❌ 已开启权限限制，但白名单为空。\n"
                "请在 AstrBot 插件配置里填写 operators（你的 QQ 号），"
                "或将 allow_all_users 设为 true。"
            )
        if sender in allowed:
            return True, ""
        logger.warning(
            f"【库街区签到】拒绝非白名单操作：sender={sender} cmd={event.message_str[:20]}"
        )
        return False, "❌ 没有权限执行该操作。"

    def _sms_throttle_ok(self, user_id: str) -> Tuple[bool, str]:
        """短信发送频控：同一用户窗口内只允许一次，防群发短信滥用。"""
        now = time.time()
        window = float(self.config.get("login_cooldown", SMS_COOLDOWN))
        last = self._sms_last.get(user_id, 0)
        if now - last < window:
            wait = int(window - (now - last)) + 1
            logger.info(f"【库街区签到】短信频控拦截：user={user_id}")
            return False, f"⏳ 操作过于频繁，请 {wait} 秒后再试。"
        self._sms_last[user_id] = now
        return True, ""

    @staticmethod
    def _mask_token(token: str) -> str:
        """token 摘要：只用于人工核对是否同一个 token，不可还原内容。"""
        if len(token) < 8:
            return "****"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        return f"sha256:{digest}（共 {len(token)} 位）"

    def _ensure_device(self):
        """确保 devcode / distinct_id 存在并持久化（保持设备标识稳定）。

        与 H5 登录接口使用的设备标识保持一致：登录成功后 config 里存的就是
        LOGIN_DEVCODE / LOGIN_DISTINCT_ID，此处不再另生成随机 UUID，
        否则「登录设备」与「签到设备」不一致，容易被库街区风控判为异常。
        """
        changed = False
        if not self.config.get("devcode"):
            self.config["devcode"] = LOGIN_DEVCODE
            changed = True
        if not self.config.get("distinct_id"):
            self.config["distinct_id"] = LOGIN_DISTINCT_ID
            changed = True
        if changed:
            try:
                self.config.save_config()
            except Exception as e:
                logger.warning(f"【库街区签到】保存设备信息失败: {e}")
        return (
            str(self.config.get("devcode", "")),
            str(self.config.get("distinct_id", "")),
        )

    @staticmethod
    def _extract_token(raw: str) -> Tuple[Optional[str], str]:
        """从粘贴内容中提取 user_token。

        返回 (token, 错误说明)。token 为 None 时错误说明可直接回复给用户。
        粘贴整串 Cookie 但没有 user_token 的情况必须拒绝——否则整串 Cookie
        会被当成 token 存进配置并持久化，属于凭据误存。
        """
        raw = (raw or "").strip()
        if not raw:
            return None, "❌ 未检测到 token 内容。"
        if "user_token=" in raw:
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith("user_token="):
                    raw = part[len("user_token="):].strip()
                    break
            else:
                return None, "❌ 粘贴的 Cookie 里没有 user_token 字段。"
        elif "=" in raw and ";" in raw:
            return None, (
                "❌ 看起来你粘贴了整串 Cookie，但其中没有 user_token。\n"
                "请只复制 user_token 那一项的值（F12 → Application → Cookies → user_token）。"
            )
        token = raw.strip('"').strip("'").strip()
        if len(token) < 20:
            return None, "❌ token 过短（少于 20 位），请检查是否复制完整。"
        if "," in token or " " in token:
            return None, "❌ token 含空格或逗号，请只复制 user_token 的值本身。"
        return token, ""

    # ------------------------------------------------------------------
    # 登录辅助（手机号 + 短信验证码）
    # ------------------------------------------------------------------

    def _get_data_dir(self) -> str:
        """获取本插件的数据目录（AstrBot data 目录下，可持久化）。"""
        base = str(self.context.get_config().get("data_dir", "data") or "data")
        path = os.path.join(base, "plugin_data", "astrbot_plugin_kuro_checkin")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(path, exist_ok=True)
        return path

    def _pending_path(self) -> str:
        return os.path.join(self._get_data_dir(), "pending_logins.json")

    def _load_pending(self) -> dict:
        """读取等待验证码的登录状态（顺带丢弃已过期条目）。"""
        try:
            path = self._pending_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.warning("【库街区签到】登录状态文件格式异常，已忽略")
                    return {}
                now = time.time()
                return {
                    uid: entry
                    for uid, entry in data.items()
                    if isinstance(entry, dict)
                    and now - float(entry.get("time", 0)) <= PENDING_TIMEOUT
                }
        except Exception as e:
            logger.warning(f"【库街区签到】读取登录状态失败: {e}")
        return {}

    def _save_pending(self, data: dict):
        """原子保存登录状态：先写临时文件再 replace，避免并发覆写留下半截 JSON。

        该文件含明文手机号，只保留未过期条目，插件卸载/解绑时应一并清理。
        """
        tmp = ""
        try:
            path = self._pending_path()
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception as e:
            logger.warning(f"【库街区签到】保存登录状态失败: {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _solve_geetest(self):
        """解决 GeeTest 滑块验证码，返回 seccode dict 或 None。"""
        try:
            from geeked import Geeked
            from geeked.sign import Signer
        except ImportError as e:
            logger.error(f"【库街区签到】GeeTest 模块导入失败（请先安装依赖）: {e}")
            return None

        captcha_id = "ec4aa4174277d822d73f2442a165a2cd"
        geeked = None
        try:
            geeked = Geeked(captcha_id, risk_type="slide")
            data = geeked.load_captcha()
            geeked.lot_number = data["lot_number"]
            w = Signer.generate_w(data, captcha_id, "slide")

            params = {
                "callback": geeked.callback,
                "captcha_id": captcha_id,
                "client_type": "web",
                "lot_number": geeked.lot_number,
                "risk_type": "slide",
                "payload": data.get("payload", ""),
                "process_token": data.get("process_token", ""),
                "payload_protocol": "1",
                "pt": "1",
                "w": w,
            }
            res = geeked.session.get(f"{GEETEST_BASE}/verify", params=params)
            parsed = json.loads(res.text.split(f"{geeked.callback}(")[1][:-1])
            if parsed["data"]["result"] == "success":
                logger.info("【库街区签到】GeeTest 滑块验证成功")
                return parsed["data"]["seccode"]
            # 失败时把服务端给出的细节带进日志，否则用户只能看到「滑块验证失败」
            logger.warning(
                "【库街区签到】GeeTest 验证未通过: result={} detail={}".format(
                    parsed["data"].get("result"),
                    json.dumps(parsed["data"].get("fail_ct") or parsed["data"], ensure_ascii=False)[:200],
                )
            )
        except Exception as e:
            logger.error(f"【库街区签到】GeeTest 滑块解决失败: {type(e).__name__}: {e}")
        finally:
            # 该 Session 建在 asyncio.to_thread 里，不关闭会每次登录留一个连接池
            if geeked is not None:
                try:
                    geeked.session.close()
                except Exception as e:
                    logger.debug(f"【库街区签到】关闭 GeeTest 会话失败: {e}")
        return None

    def _send_sms(self, phone: str, seccode: dict) -> bool:
        """发送短信验证码，返回是否发送成功。"""
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError as e:
            logger.error(f"【库街区签到】缺少依赖 curl_cffi: {e}")
            return False
        sess = None
        try:
            sess = cffi_requests.Session(impersonate="chrome124")
            # 先触发一次，确保会话就绪
            sess.post(
                "https://api.kurobbs.com/user/getSmsCodeForH5",
                data={"mobile": phone, "geeTestData": ""},
                headers=_h5_login_headers(),
            )
            # 携带验证结果发送短信
            r = sess.post(
                "https://api.kurobbs.com/user/getSmsCodeForH5",
                data={"mobile": phone, "geeTestData": json.dumps(seccode)},
                headers=_h5_login_headers(),
            )
            logger.info(f"【库街区签到】发送短信结果: {r.text[:120]}")
            return r.json().get("data", {}).get("geeTest") is False
        except Exception as e:
            logger.error(f"【库街区签到】发送短信失败: {type(e).__name__}: {e}")
            return False
        finally:
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass

    def _do_sdk_login(self, phone: str, code: str) -> dict:
        """用短信验证码登录，返回接口 JSON。"""
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError as e:
            logger.error(f"【库街区签到】缺少依赖 curl_cffi: {e}")
            return {"code": -1, "msg": f"缺少依赖 curl_cffi: {e}"}
        sess = None
        try:
            sess = cffi_requests.Session(impersonate="chrome124")
            r = sess.post(
                "https://api.kurobbs.com/user/sdkLoginForH5",
                data={"mobile": phone, "code": code},
                headers=_h5_login_headers(),
            )
            return r.json()
        except Exception as e:
            logger.error(f"【库街区签到】登录请求失败: {type(e).__name__}: {e}")
            return {"code": -1, "msg": str(e)}
        finally:
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 指令处理
    # ------------------------------------------------------------------

    @filter.command("库街区绑定", alias={"库街绑定", "kuro_bind", "kurobind"})
    async def bind_token(self, event: AstrMessageEvent):
        """绑定库街区 token"""
        ok, deny = self._is_operator(event)
        if not ok:
            yield event.plain_result(deny)
            return

        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result(
                "使用方法: /库街区绑定 <token>\n"
                "token 获取方式：登录 https://www.kurobbs.com → F12 → Application → Cookies → 复制 user_token 的值"
            )
            return

        token, err = self._extract_token(parts[1])
        if token is None:
            yield event.plain_result(err)
            return

        old_token = self._get_token()
        self.config["token"] = token
        self.config["bind_umo"] = event.unified_msg_origin
        self.config["bind_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.config.save_config()
        except Exception as e:
            self.config["token"] = old_token
            logger.error(f"【库街区签到】保存配置失败，已回滚 token: {e}")
            yield event.plain_result(f"❌ 配置写入失败，本次绑定未生效：{e}")
            return

        # 只记摘要，绝不把 token 本体写进日志
        logger.info(
            f"【库街区签到】token 已由 sender={event.get_sender_id()} "
            f"会话={event.unified_msg_origin} 绑定（{self._mask_token(token)}）"
        )
        yield event.plain_result(
            "✅ 库街区 token 绑定成功！\n"
            "发送 /库街区签到 立即签到；之后每天会按配置的时间自动签到。"
        )

    @filter.command("库街区签到", alias={"库街签到", "kuro_sign", "kurosign"})
    async def manual_sign(self, event: AstrMessageEvent):
        """手动执行库街区每日签到"""
        token = self._get_token()
        if not token:
            yield event.plain_result(
                "❌ 尚未绑定库街区 token\n"
                "发送: /库街区绑定 <token>\n"
                "token 获取方式：登录 www.kurobbs.com → F12 → Cookie → user_token"
            )
            return
        ok, deny = self._is_operator(event)
        if not ok:
            yield event.plain_result(deny)
            return

        # 记住推送会话，自动签到结果将推送到这里
        if self.config.get("push_result", True):
            try:
                self.config["bind_umo"] = event.unified_msg_origin
                self.config.save_config()
            except Exception as e:
                logger.warning(f"【库街区签到】保存推送会话失败: {e}")

        yield event.plain_result("⏳ 正在执行库街区签到，请稍候…")
        lines = await self.do_sign_all()
        yield event.plain_result("\n".join(lines))

    @filter.command("库街区解绑", alias={"库街解绑", "kuro_unbind"})
    async def unbind(self, event: AstrMessageEvent):
        """清除已绑定的库街区 token"""
        ok, deny = self._is_operator(event)
        if not ok:
            yield event.plain_result(deny)
            return
        had = bool(self._get_token())
        old_token = self._get_token()
        self.config["token"] = ""
        try:
            self.config.save_config()
        except Exception as e:
            self.config["token"] = old_token
            logger.error(f"【库街区签到】保存配置失败: {e}")
            yield event.plain_result(f"❌ 配置写入失败，解绑未生效：{e}")
            return
        if had:
            # 解绑顺带清掉待验证码状态，避免残留明文手机号
            self._save_pending({})
        logger.info(f"【库街区签到】token 已由 sender={event.get_sender_id()} 解绑")
        yield event.plain_result("✅ 已解绑库街区 token")

    @filter.command("库街区状态", alias={"库街状态", "kuro_status"})
    async def status(self, event: AstrMessageEvent):
        """查看绑定与自动签到状态"""
        token = self._get_token()
        if not token:
            yield event.plain_result("❌ 未绑定库街区 token")
            return
        # 旧版会打印 token 前 6 后 4 个字符，群聊里等于泄露凭据片段，改为不可还原摘要
        masked = self._mask_token(token)
        bind_time = str(self.config.get("bind_time", "未知") or "未知")
        auto_enabled = "开启" if self.config.get("auto_sign_enable", True) else "关闭"
        auto_time = str(self.config.get("auto_sign_time", "07:30"))
        push_state = "开启" if self.config.get("push_result", True) else "关闭"
        gate = (
            "公开（任何人可操作）"
            if self.config.get("allow_all_users", True)
            # 不打印具体 QQ 号，群聊里白名单本身是隐私
            else f"白名单（{len(self._operator_ids())} 人）"
        )
        yield event.plain_result(
            f"📊 库街区状态：\n"
            f"Token: {masked}\n"
            f"绑定时间: {bind_time}\n"
            f"自动签到: {auto_enabled}（每日 {auto_time}）\n"
            f"结果推送: {push_state}\n"
            f"操作权限: {gate}"
        )

    @filter.command("库街区帮助", alias={"库街帮助", "kuro_help"})
    async def help_cmd(self, event: AstrMessageEvent):
        """查看帮助"""
        yield event.plain_result(HELP_TEXT)

    @filter.command("库街区登录", alias={"库街登录", "kuro_login", "kuologin"})
    async def login(self, event: AstrMessageEvent):
        """手机号+短信验证码一键登录（自动过 GeeTest 滑块）"""
        ok, deny = self._is_operator(event)
        if not ok:
            yield event.plain_result(deny)
            return

        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("使用方法: /库街区登录 <手机号>")
            return

        phone = parts[1].strip()
        confirmed = False
        if phone.startswith("确认"):
            tail = phone[len("确认"):].strip()
            if not tail:
                yield event.plain_result(
                    "⚠️ 用法是 /库街区登录 确认 <手机号>\n（这是覆盖已有绑定前的二次确认）"
                )
                return
            phone = tail
            confirmed = True
        if not phone.isdigit() or len(phone) != 11:
            yield event.plain_result("❌ 手机号格式不正确（需 11 位数字）")
            return

        user_id = str(event.get_sender_id())
        # 先看是不是要覆盖已有绑定：只是被要求二次确认时不应烧掉短信配额
        if self._get_token() and not confirmed:
            yield event.plain_result(
                "⚠️ 当前已绑定 token，登录成功会覆盖它。\n"
                "如确认无误，请重新发送：/库街区登录 确认 " + phone
            )
            return

        allowed, hint = self._sms_throttle_ok(user_id)
        if not allowed:
            yield event.plain_result(hint)
            return

        yield event.plain_result("⏳ 正在过滑块验证，请稍候（约需 3~10 秒）...")

        # 同步的滑块求解放到线程中执行，避免阻塞事件循环
        seccode = await asyncio.to_thread(self._solve_geetest)
        if not seccode:
            yield event.plain_result(
                "❌ 滑块验证失败，具体原因见控制台日志。\n"
                "提示：可改用 /库街区绑定 <token>"
            )
            return

        ok = await asyncio.to_thread(self._send_sms, phone, seccode)
        if not ok:
            yield event.plain_result(
                "❌ 发送验证码失败，请稍后重试。\n"
                f"提示：发送过于频繁（{SMS_COOLDOWN} 秒内）会失败。"
            )
            return

        masked = phone[:3] + "****" + phone[-4:]
        pending = self._load_pending()
        pending[user_id] = {"phone": phone, "time": time.time()}
        self._save_pending(pending)
        yield event.plain_result(
            f"📱 验证码已发送到 {masked}，请在 {PENDING_TIMEOUT // 60} 分钟内直接回复验证码数字。"
        )

    @filter.regex(r"^\d{4,6}$")
    async def on_sms_code(self, event: AstrMessageEvent):
        """捕获用户回复的短信验证码并完成登录"""
        user_id = str(event.get_sender_id())
        pending = self._load_pending()
        entry = pending.get(user_id)
        if not entry or time.time() - float(entry.get("time", 0)) > PENDING_TIMEOUT:
            # 没有待登录状态，或已超时：不消费这条消息，交给其它逻辑处理
            return

        phone = entry["phone"]
        code = event.message_str.strip()
        # 先移除 pending，避免重复处理
        pending.pop(user_id, None)
        self._save_pending(pending)

        yield event.plain_result("⏳ 正在登录，请稍候...")
        result = await asyncio.to_thread(self._do_sdk_login, phone, code)
        if not (result.get("code") == 200 and result.get("data", {}).get("token")):
            msg = result.get("msg", result.get("message", "未知错误"))
            yield event.plain_result(
                f"❌ 登录失败：{msg}\n提示：验证码可能已过期，请重新 /库街区登录"
            )
            return

        token = result["data"]["token"]
        nickname = result["data"].get("signature") or result["data"].get("userName", "未知")

        # 保存 token，并使用登录时的设备标识，保证后续接口一致
        old_token = self._get_token()
        self.config["token"] = token
        self.config["devcode"] = LOGIN_DEVCODE
        self.config["distinct_id"] = LOGIN_DISTINCT_ID
        self.config["bind_umo"] = event.unified_msg_origin
        self.config["bind_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.config.save_config()
        except Exception as e:
            self.config["token"] = old_token
            logger.error(f"【库街区签到】登录后保存配置失败，已回滚: {e}")
            yield event.plain_result(f"❌ 登录成功但配置写入失败，本次绑定未生效：{e}")
            return

        logger.info(
            f"【库街区签到】登录成功 sender={user_id} 昵称={nickname}（{self._mask_token(token)}）"
        )
        yield event.plain_result(f"✅ 登录成功！{nickname}")

        # 登录成功后立即签到
        lines = await self.do_sign_all()
        yield event.plain_result(f"📋 签到结果:\n" + "\n".join(lines))

    # ------------------------------------------------------------------
    # 签到主流程
    # ------------------------------------------------------------------

    async def do_sign_all(self) -> List[str]:
        """执行全部签到，返回结果文本行列表。"""
        lines: list[str] = ["【库街区每日签到】"]
        token = self._get_token()
        if not token:
            lines.append("❌ 未绑定库街区 token")
            return lines

        devcode, distinct_id = self._ensure_device()
        client = KuroClient(token, devcode, distinct_id)
        try:
            # 1. 获取用户信息（仅用于判断 token 有效性）
            user_id = await client.get_user_id()
            if not user_id:
                lines.append("⚠️ 获取用户信息失败，token 可能已失效")

            # 2. 游戏签到（鸣潮 / 战双）
            for game_key in ("wuwa", "pgr"):
                if not self.config.get(f"enable_{game_key}", True):
                    continue
                game = GAMES[game_key]
                role_info = await client.get_role_info(game["id"])
                if role_info.get("expired"):
                    lines.append("❌ 登录已过期，请重新绑定 token")
                    break
                if not role_info.get("roleId"):
                    lines.append(f"⚠️ {game['name']} 未查询到角色信息，跳过游戏签到")
                    await asyncio.sleep(1)
                    continue
                lines.append(await client.game_sign(game, role_info))
                await asyncio.sleep(1)

            # 3. 社区签到（库洛币）
            if self.config.get("enable_forum_sign", True):
                lines.append(await client.forum_sign())
                await asyncio.sleep(1)

            # 4. 论坛每日任务（可选）
            if self.config.get("enable_forum_tasks", False):
                lines.extend(await client.forum_tasks())

            # 5. 库洛币余额
            gold = await client.gold_total()
            if gold:
                lines.append(gold)
        except Exception as e:
            logger.error(f"【库街区签到】签到流程异常: {e}")
            lines.append(f"❌ 签到流程异常：{e}")
        finally:
            await client.close()
        return lines

    # ------------------------------------------------------------------
    # 每日自动签到
    # ------------------------------------------------------------------

    async def _auto_sign_loop(self):
        """每日自动签到循环：读取配置时间，等到点后执行签到并循环。"""
        while True:
            try:
                cfg_time = str(self.config.get("auto_sign_time", "07:30")).strip() or "07:30"
                try:
                    hour, minute = int(cfg_time.split(":")[0]), int(cfg_time.split(":")[1])
                    hour = max(0, min(hour, 23))
                    minute = max(0, min(minute, 59))
                except Exception:
                    hour, minute = 7, 30

                now = datetime.now()
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                logger.info(
                    f"【库街区签到】下次自动签到时间：{target.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await asyncio.sleep((target - now).total_seconds())
                await self._run_auto_sign()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"【库街区签到】自动签到循环异常：{e}")
                await asyncio.sleep(60)

    async def _run_auto_sign(self):
        """执行一次自动签到并推送结果。"""
        try:
            lines = await self.do_sign_all()
            text = "\n".join(lines)
            logger.info(f"【库街区签到】自动签到完成：\n{text}")
            if not self.config.get("push_result", True):
                return
            umo = str(self.config.get("bind_umo", "") or "")
            if not umo:
                logger.warning("【库街区签到】未绑定推送会话，跳过推送（发送 /库街区签到 即可绑定）")
                return
            try:
                chain = MessageChain().message(text)
                await self.context.send_message(umo, chain)
            except Exception as e:
                logger.error(f"【库街区签到】推送签到结果失败：{e}")
        except Exception as e:
            logger.error(f"【库街区签到】自动签到执行异常：{e}")
