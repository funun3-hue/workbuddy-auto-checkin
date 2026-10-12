# WorkBuddy 自动签到技能

通过 OpenCV 图片模板匹配和 Windows 鼠标操作完成 WorkBuddy 每日积分签到。包含完整 `SKILL.md`、Python 脚本与浅色/深色界面模板。

## 功能

- 自动打开或激活 WorkBuddy，识别签到入口与领取按钮。
- 点击领取后等待 2 秒，优先匹配浅色弹窗关闭区域，匹配不到再使用深色版本，点击叉号中心。
- 使用“今日已领取”图片确认签到成功。确认失败或未找到关闭区域时保留主窗口。
- 已有实例存在活动任务或任务状态不可读时，不重启该实例。
- 原先未打开的实例在成功后可关闭；原先在后台的实例成功后最小化。
- 支持每天 09:42 的 Windows 计划任务。

## 安装和运行

需要 Windows、Python 3.11（含 `py` 启动器）、已安装并登录的 WorkBuddy。默认程序路径为 `%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe`。

下载仓库并解压后，在仓库目录执行：

```powershell
py -3.11 .\workbuddy_checkin.py --run --close-after-run --json
```

首次执行会创建 `%LOCALAPPDATA%\CheckinRuntime\py311` 虚拟环境，通过 pip 安装 `requirements.txt` 中的固定版本依赖。首次安装需要联网。

安装每日计划任务：

```powershell
py -3.11 .\workbuddy_checkin.py --install-daily-schedule
```

任务仅在用户已登录时运行。签到需要桌面解锁；脚本会等待键鼠空闲。请在点击流程期间避免切换窗口。更改时间可编辑 `DAILY_TASK_TIME` 后重新安装任务；移动仓库目录后也应重新安装任务。

仅检查窗口（会打开或激活应用，但不点击签到）：

```powershell
py -3.11 .\workbuddy_checkin.py --diagnose
```

## 作为 AI 技能使用

将整个仓库文件夹放入你的 AI 工具支持的技能目录，保留 `SKILL.md`、两个 Python 文件、依赖文件和 `assets` 的相对位置。让 AI 按 `SKILL.md` 运行打包脚本。

## 工作原理和限制

截图仅在内存中进行模板匹配；坐标由匹配位置和模板内叉号偏移计算。当前不做自动缩放适配，界面缩放、字体或布局改变可能需要重新制作模板。签到弹窗关闭按钮已在本机浅色界面实测；这不代表其他电脑的完整签到流程已经验证。

本项目不读取登录令牌，也不调用签到接口。为保护正在运行的任务，只读查询本机 `~/.workbuddy/workbuddy.db` 中会话的状态字段，不发布或上传数据库。

日志位于 `%LOCALAPPDATA%\WorkBuddyAutoCheckin\logs\checkin.log`。公开仓库不包含运行日志、会话数据库、虚拟环境或账号凭据。故障日志包含窗口坐标、进程 ID 和错误信息，分享前请检查内容。

非官方项目，与 WorkBuddy 官方无隶属关系。

## 许可证

项目代码采用 [MIT License](LICENSE)。界面截图模板中的 WorkBuddy 标识及界面元素归各自权利人所有。
