# 桌面灵伴 2.1 验收记录

验收环境：Windows 11 x64，当前用户安装，Qt/PySide6 6.11.1。

## 自动门禁

- `pip check`：通过，无损坏依赖。
- 源码测试：`145 passed`。
- 冻结版自检测试：`1 passed`。
- 覆盖率：`90%`，高于 85% 门槛。
- PyInstaller 冻结：通过；`DesktopCompanion.exe --self-test` 返回 `ok=true`、WebP 可用、每只宠物 74 帧。
- Inno Setup 6.7.3：成功生成“桌面灵伴安装程序.exe”。
- 真实发布验证：普通安装、自检、自启动值生命周期、卸载清理、覆盖升级、设置保留和状态恢复全部通过。

自检中的宠物清单为：

```json
{"pets":["shiyi","ziling"]}
```

## 原生界面检查

| 项目 | 结果 |
|---|---|
| 首次/默认角色 | 显示十一，窗口为 192×208，透明边缘正常 |
| 右键菜单 | 动态显示“切换宠物”子菜单，并提供“重新扫描宠物”“打开宠物目录” |
| 十一切换到紫灵 | 单击后无需重启，窗口中立即显示紫灵 |
| 第三方宠物包 | 在 `%APPDATA%\DesktopCompanion\pets\qa_pet` 放入标准 `pet.json` 和 `spritesheet.webp` 后，安装版成功扫描并显示该图集；测试后已移除 |
| 运行时刷新 | 自动化测试覆盖新增、切换和移除当前宠物；当前宠物移除后安全回退到内置宠物 |
| 设置持久化 | `settings.ini` 立即写入 `schema_version = 2`、`pet_id = ziling` |
| 重启恢复 | 退出并重新启动后仍显示紫灵 |
| 资源契约 | 所有宠物包统一使用 v2、1536×2288、透明 WebP；注册器校验 ID、清单、大小、路径和动作占用表 |
| 图标 | 功能候选包暂用 2.0 图标；2.1 通用产品图标将在用户选定方案后替换并重新构建 |
| 托盘图标 | 控制器加载的图标非空，提示为“桌面灵伴”；真实安装运行后 Windows `NotifyIconSettings` 已登记 `DesktopCompanion.exe` |
| 桌面快捷方式 | 覆盖安装后实际生成 `%USERPROFILE%\Desktop\桌面灵伴.lnk`，目标为已安装的 `DesktopCompanion.exe` |
| 1.0 共存 | 2.1 延续 2.0 的独立 EXE、目录、设置、日志、自启动项、互斥量、IPC 名称和卸载 GUID，不覆盖 1.0 |

## 产品身份

- 显示名称：桌面灵伴
- 版本：2.1.0
- 可执行文件：`DesktopCompanion.exe`
- 安装目录：`%LOCALAPPDATA%\Programs\DesktopCompanion`
- 设置：`%APPDATA%\DesktopCompanion\settings.ini`
- 日志：`%LOCALAPPDATA%\DesktopCompanion\logs\DesktopCompanion.log`
- 自启动值：`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DesktopCompanion`

## 说明

原 1.0 的历史验收记录保存在 `docs/manual-qa-1.0.md`。本次没有删除或覆盖原项目、原安装包或原安装目录。2.1 覆盖升级 2.0 时保留设置和用户宠物目录。Windows 11 可能把新通知图标放入右下角 `^` 的隐藏区域，应用不强制修改用户的任务栏固定偏好。安装包未做商业 Authenticode 签名，首次从其他电脑运行时可能出现 Windows SmartScreen 提示。
