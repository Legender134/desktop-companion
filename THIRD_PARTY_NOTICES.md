# Third-Party Notices

桌面灵伴 2.3 的源码、测试和 Windows 构建使用以下第三方项目。本文件是组件与许可证索引，不替代各项目随附的完整许可证文本；发布二进制时应同时保留所分发 wheel、Qt 组件和运行库中的许可证及版权文件。

版本号来自本仓库的固定依赖或明确的构建目标。

## Runtime and redistributed build components

### Python 3.12.10

- Project: Python
- License: Python Software Foundation License Version 2；标准发行版还包含其 `LICENSE.txt` 中列出的历史许可证和第三方声明
- Official project: https://www.python.org/
- Official license: https://docs.python.org/3.12/license.html

### Qt for Python / PySide6 6.11.1

- Projects: Qt 6, Qt for Python (PySide6), Shiboken6, PySide6 Essentials and PySide6 Addons
- License: Qt for Python 社区版由上游以 LGPLv3/GPLv3 提供，并另有商业许可选项；已安装 PySide6 wheel 的元数据声明 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`。Qt 模块和其中第三方代码以各自随附许可证为准
- Official project: https://doc.qt.io/qtforpython-6/
- Official licensing: https://doc.qt.io/qt-6/licensing.html
- Qt for Python component notices: https://doc.qt.io/qtforpython-6/licenses.html

PyInstaller 打包结果会动态使用随应用分发的 Qt DLL 和插件。发布包必须保留相应许可证信息，并允许用户按适用的 LGPLv3 条款替换这些库；本项目不使用商业 Qt 许可来覆盖社区 wheel。

## Build and test tools

### PyInstaller 6.21.0

- License: GPL version 2 or later with the PyInstaller bootloader/packaging special exception；少量文件为 Apache License 2.0，具体范围由上游 `COPYING.txt` 决定
- Official project: https://pyinstaller.org/
- Official license: https://pyinstaller.org/en/v6.21.0/license.html

PyInstaller 是构建工具；其特例允许分发由它生成的应用。应用仍须遵守 Python、Qt 及其他依赖各自的许可证。

### Pillow 12.3.0

- License: MIT-CMU
- Official project: https://python-pillow.github.io/
- Official license and credits: https://pillow.readthedocs.io/en/stable/about.html

Pillow 在本项目中读取批准图集并生成多尺寸 Windows 图标，也参与资源测试。

### pytest 9.1.1

- License: MIT
- Official project: https://pytest.org/
- Official license: https://docs.pytest.org/en/stable/license.html

### pytest-qt 4.5.0

- License: MIT
- Official project: https://pytest-qt.readthedocs.io/
- Official license: https://github.com/pytest-dev/pytest-qt/blob/master/LICENSE

### coverage.py 7.15.1

- License: Apache License 2.0
- Official project: https://coverage.readthedocs.io/en/7.15.1/
- Official source and license: https://github.com/coveragepy/coveragepy

### setuptools (build-system requirement `>=80`)

- License: MIT
- Official project: https://setuptools.pypa.io/
- Official source and license: https://github.com/pypa/setuptools

### Inno Setup

- Planned build target: 7.0.2；若该版本无法从官方渠道取得，项目计划只接受经过签名验证的官方兼容版本 `>=6.7.3,<8`
- License: Inno Setup License（允许任何用途，包括商业应用）
- Official project: https://jrsoftware.org/isinfo.php
- Official license: https://jrsoftware.org/files/is/license.txt
- Official purchase/licensing information: https://jrsoftware.org/isorder.php

上游请求其定义范围内的商业用户购买商业许可证以支持开发，但官方购买说明的 Q&A 明确说明购买并非严格要求；详情请参阅上面的官方购买/许可链接。

Inno Setup 仅用于生成 Windows 安装程序，编译器本身不随桌面灵伴安装。

## Project visual assets

`src/shiyi_desktop_pet/resources/pets/shiyi`、`pets/ziling`、`pets/nangongwan` 中的图集与清单，以及从十一休息帧确定性派生的 `app.ico`，是本项目提供的角色视觉资源，不属于上面任何第三方软件项目。南宫婉和紫灵为基于《凡人修仙传》角色制作的非官方同人内容，仅用于学习与交流；角色及原作相关权利归其各自权利人所有。视觉资源的使用权限由项目资源提供者单独负责。
