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

## ⚠️ 注意

- 仅供个人学习交流使用，请勿滥用。
- Token 只保存在 AstrBot 本地配置中（`data/config/`），不会上传到任何第三方。
- 一键登录的滑块识别依赖 `geeked` 模块（基于 [xKiian/GeekedTest](https://github.com/xKiian/GeekedTest)，MIT 协议），需要安装 `curl_cffi / pycryptodome / opencv-python-headless / numpy`。
- 库街区接口可能随版本更新而变化，若登录/签到失败请查看 AstrBot 日志。

## 🙏 致谢

- [mxyooR/Kuro-autosignin](https://github.com/mxyooR/Kuro-autosignin) — API 逻辑参考
- [TomyJan/Kuro-API-Collection](https://github.com/TomyJan/Kuro-API-Collection) — 库街区 API 文档
- [huanx-b/astrbot_plugin_kuro_sign](https://github.com/huanx-b/astrbot_plugin_kuro_sign) — AstrBot 插件与 GeeTest 登录实现参考
- [xKiian/GeekedTest](https://github.com/xKiian/GeekedTest) — GeeTest v4 滑块验证码求解

