# 库街区每日签到 AstrBot 插件

每天自动在库街区进行每日签到，支持：

- 📱 **手机号+短信验证码一键登录**（自动过 GeeTest 滑块，无需手动复制 token）
- 🎮 **鸣潮游戏签到**（gameId=3）
- 🎮 **战双游戏签到**（gameId=2）
- 📝 **库街区社区签到**（获得库洛币）
- 💰 查询当前库洛币余额
- 🔧 （可选）论坛每日任务（浏览/点赞/分享，额外获得库洛币）
- ⏰ 每日自动签到 + 结果推送到你的会话

> ⚠️ 说明：库街区官方已停用网页端「扫码登录」（已接入 GeeTest 滑块验证），
> 本插件提供等价的**一键登录**方式：手机号 + 短信验证码，自动过滑块、全自动完成。

## 📋 命令

| 命令 | 说明 |
|------|------|
| `/库街区登录 <手机号>` | **一键登录**：自动过滑块 → 发送短信 → 回复验证码 → 自动绑定并签到 |
| `/库街区登录 确认 <手机号>` | 已绑定 token 时，换号需要带 `确认` 前缀 |
| `/库街区绑定 <token>` | 绑定库街区 token |
| `/库街区签到` | 立即执行每日签到 |
| `/库街区解绑` | 清除已绑定的 token |
| `/库街区状态` | 查看绑定与自动签到状态 |
| `/库街区帮助` | 查看帮助 |

## 🚀 快速开始（推荐：一键登录）

```
/库街区登录 138xxxx8888
```

Bot 会自动：
1. 自动过 GeeTest 滑块验证（约 3~10 秒）
2. 发送短信验证码到你的手机
3. 提示你回复验证码

你只需要：**看手机短信，把验证码数字发给 Bot**。登录成功后会立即自动签到。

## 📦 安装

### 1. 安装插件

把 `astrbot_plugin_kuro_checkin` 文件夹放到 AstrBot 的插件目录：

```bash
cd /path/to/astrbot/data/plugins
# 将本文件夹拷贝到此处即可
```

然后在 AstrBot WebUI 的「插件管理」中启用/重载该插件。

### 2. 安装依赖

```bash
# 在 AstrBot 的 Python 环境中执行
pip install -r requirements.txt
# 或逐个安装：
pip install httpx curl_cffi pycryptodome opencv-python-headless numpy requests
```

> 如果 AstrBot 使用 venv 或 Docker，请在对应的 Python 环境中安装。
>
> `requirements.txt` 已加上版本区间（特别是 `numpy<2.0`），是为了避开 opencv 与 numpy 2.x 的 ABI 冲突；
> 请勿改回 `>=` 无上限写法。运行环境需要 **Python 3.10+**（代码使用了 `X | None` 与 `dict | dict`）。

### 3. 重启 / 重载 AstrBot

## 🔑 备选：手动绑定 Token

如果一键登录不可用（如 GeeTest 风控升级），可手动绑定：

1. 用浏览器打开并登录 [https://www.kurobbs.com](https://www.kurobbs.com)
2. 按 `F12` → `Application` → `Cookies` → 找到 `user_token`
3. 复制它的**值**（形如 `eyJhbGci...`），发送 `/库街区绑定 eyJ...`

## ⚙️ 配置（可选）

在 AstrBot WebUI 的插件配置页可以调整：

| 配置项 | 说明 | 默认 |
|--------|------|------|
| `token` | 库街区 token | 空 |
| `auto_sign_enable` | 每天自动签到 | 开 |
| `auto_sign_time` | 每天自动签到时间（服务器时区，24小时制） | `07:30` |
| `push_result` | 自动签到后推送结果到绑定会话 | 开 |
| `enable_wuwa` | 鸣潮游戏签到 | 开 |
| `enable_pgr` | 战双游戏签到 | 开 |
| `enable_forum_sign` | 社区签到（库洛币） | 开 |
| `enable_forum_tasks` | 论坛每日任务（浏览/点赞/分享） | 关 |
| `allow_all_users` | 是否允许任何会话成员使用登录/绑定/解绑/签到 | 开（见下） |
| `operators` | 白名单 QQ 号列表，`allow_all_users=false` 时生效 | 空 |
| `login_cooldown` | 同一用户两次申请短信的最小间隔（秒） | 90 |

### 🔒 权限建议（重要）

token 在本插件里是**全局唯一一份**。`allow_all_users` 保持 `true`（默认，为了不改变已部署实例的行为）时，
任何能对 bot 发消息的人都可以：

- 发 `/库街区绑定 <他的token>` 覆盖你的 token，并把每日签到结果改推到他那；
- 发 `/库街区解绑` 让你的签到失效；
- 发 `/库街区登录 <任意手机号>` 借用你的出口 IP 申请短信。

**群聊或多人 bot 请务必设为 `false` 并把你的号填进 `operators`。**

## 📚 教程

- [自动签到结果推送教程](docs/自动签到结果推送教程.md) — 了解「自动签到后推送结果到绑定会话」的绑定、配置与工作原理

## ⚠️ 注意

- 仅供个人学习交流使用，请勿滥用。
- Token 只保存在 AstrBot 本地配置中（`data/config/`），不会上传到任何第三方。`/库街区状态` 现在只显示 token 的 sha256 摘要与长度，不再打印首尾字符。
- 一键登录过程中，待验证码状态会临时写入 `data/plugin_data/astrbot_plugin_kuro_checkin/pending_logins.json`，**含明文手机号**，120 秒后自动失效，`/库街区解绑` 会清空该文件。
- 一键登录的滑块识别依赖 `geeked` 模块（基于 [xKiian/GeekedTest](https://github.com/xKiian/GeekedTest)，MIT 协议，许可正文见仓库根 `LICENSE`），需要安装 `curl_cffi / pycryptodome / opencv-python-headless / numpy`。
- `geeked` 里的 **icon 型验证码分支未构建**：它需要可选模块 `geeked/dddd_server.py` 与 `ddddocr`（约 200 MB，且上游以 `git+main` 方式引用）。本插件固定按 `risk_type="slide"` 运行，正常永远不会进入该分支；若将来 GeeTest 改下发 icon 型，日志会明确告诉你缺什么，而不是笼统的「滑块验证失败」。
- 库街区接口可能随版本更新而变化，若登录/签到失败请查看 AstrBot 日志。

## 🗂 版本

- **v1.2.0**
  - 修复插件重载/停用时报错（合并 PR #1 的 `terminate()` 修正，并整理写法）
  - 同步上游 `geeked/sign.py`：`LotParser.mapping`、`abo` 常量、`generate_pow` 实现（此前是旧快照，很可能是「滑块验证失败」反复出现的真因）
  - 新增 `allow_all_users` / `operators` / `login_cooldown` 三个配置
  - `/库街区状态` 不再输出 token 首尾字符；`_extract_token` 拒绝把不含 `user_token` 的整串 Cookie 存进配置
  - 登录与签到的设备标识统一；`save_config` 失败时回滚并明确报错，不再静默半绑定
  - `/库街区登录` 加同用户频控与覆盖前的二次确认
  - GeeTest 会话与 curl_cffi 会话显式关闭；`/load` 改用绝对 URL
  - `pending_logins.json` 原子写（临时文件 + `os.replace`）并自动丢弃过期条目
  - 重复 `initialize()` 不再遗留游离协程
  - 依赖加版本区间；补上游 MIT `LICENSE`

## 🙏 致谢

- [mxyooR/Kuro-autosignin](https://github.com/mxyooR/Kuro-autosignin) — API 逻辑参考
- [TomyJan/Kuro-API-Collection](https://github.com/TomyJan/Kuro-API-Collection) — 库街区 API 文档
- [huanx-b/astrbot_plugin_kuro_sign](https://github.com/huanx-b/astrbot_plugin_kuro_sign) — AstrBot 插件与 GeeTest 登录实现参考
- [xKiian/GeekedTest](https://github.com/xKiian/GeekedTest) — GeeTest v4 滑块验证码求解

