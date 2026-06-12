# TypeRelay 打字中转器

**本地复制，远端敲入。** 一款轻量 Windows 工具，将复制的文本逐字符"敲"进云桌面。

![Python](https://img.shields.io/badge/python-3.8+-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## 痛点

在云桌面（RDP / VMware Horizon / Citrix / 深信服等）里干活，**剪贴板共享被禁用了**？本地 Ctrl+C 复制的内容，切到云桌面 Ctrl+V 贴出来的还是远端剪贴板里的东西，跟没复制一样。

## 方案

TypeRelay 直接绕过剪贴板，通过**键盘通道模拟逐字符敲入**——云桌面那边看到的就是一个键盘在打字，不受剪贴板策略影响。

```
┌─ 你的电脑 ────────────────┐     ┌─ 云桌面 ──────────────────┐
│ 1. 把文本粘贴到           │     │                            │
│    TypeRelay 窗口         │     │                            │
│ 2. 设好秒数，点           │     │                            │
│    "Start Typing"         │     │                            │
│ 3. 倒计时中...            │ ──→ │ 4. 切过来，光标放到         │
│                           │     │    目标输入框              │
│ 5. 逐字符自动敲入         │ ──→ │ 6. 文本出现了！             │
└───────────────────────────┘     └────────────────────────────┘
```

## 功能特点

- **倒计时机制** — 给你几秒切窗口、放光标
- **Shift 组合键** — `(){}[]!@#` 等符号显式按 Shift+基础键，绕过中文键盘布局差异
- **速度可调** — 倒计时 1~30 秒，字符间隔可配置
- **窗口置顶** — 切云桌面时中转器一直在最前面
- **极简依赖** — 300 行 Python，仅一个第三方库

## 安装

```bash
# 克隆仓库
git clone https://github.com/tuiangeuaoglea/typerelay.git
cd typerelay

# 安装依赖
pip install -r requirements.txt

# 运行
python typerelay.py
```

**环境要求：** Python 3.8+，Windows

## 使用

1. 本地复制文本
2. 粘贴到 TypeRelay 文本框
3. 设置倒计时秒数（默认 3 秒）
4. 点击 **Start Typing**
5. 切到云桌面，光标点到目标输入框
6. 等倒计时结束 → 自动逐字符敲入

### 快捷启动

在桌面放一个 `.bat` 快捷方式，双击无命令行黑窗启动：

```batch
@echo off
cd /d C:\path\to\typerelay
start "" pythonw typerelay.py
```

## 原理

| 字符类型 | 方式 | 可靠性 |
|---|---|---|
| 英文/数字 | `keyboard.send()` | ✅ 始终可用 |
| 符号 `(){}[]!@#$` | 显式 `Shift + 基础键` | ✅ 绕过键盘布局 |
| 中文/Unicode | `SendInput(KEYEVENTF_UNICODE)` | ⚠️ RDP 可能不转发 |

Shift 组合键是踩坑后的关键 trick：中文键盘的**物理键位**和 US 键盘一样，显式按 `Shift+9` 发出的扫描码到云桌面那边就是 `(`，不受本地输入法软件层面的映射影响。

## 已知限制

- **中文字符**在 RDP 下可能不生效——`KEYEVENTF_UNICODE` 注入会被部分云桌面客户端丢弃
- **换行**自动替换为空格（防止意外触发回车提交）
- 仅支持 Windows（Unicode 注入依赖 `ctypes` Win32 API）

## 参与贡献

欢迎 PR！一些改进方向：

- [ ] 系统托盘模式
- [ ] 全局热键触发
- [ ] 剪贴板监听模式（检测到复制即自动键入）
- [ ] 跨平台支持（Linux/Mac 通过 `uinput`/`CGEvent`）

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

---

[English README](README.md)
