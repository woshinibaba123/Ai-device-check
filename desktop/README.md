# 巡测桌面版

桌面窗口复用原有测试工作台。默认后端端口18765、专用Appium端口14723，与网页版8765/4723分开。关闭窗口前要求停止任务并等待清理；不会停止其他工具的Appium。数据保存在用户可写目录，不写入安装目录，也不打包测试报告、凭据或源码副本。

## 开发与构建

使用目标系统上的 Python 3.12，创建项目专用环境：

```sh
python3 -m venv .runtime/desktop-venv
.runtime/desktop-venv/bin/python -m pip install -r desktop/requirements.txt
.runtime/desktop-venv/bin/python desktop_main.py
.runtime/desktop-venv/bin/python desktop/build.py
```

Windows 可安装 Python 3.12 和 Inno Setup 6 后双击 `desktop/构建Windows安装包.cmd`，或按下列路径规则手动构建。Windows 将python3替换为 `py -3.12`，虚拟环境Python路径替换为 `.runtime\desktop-venv\Scripts\python.exe`。

Mac输出 `dist/desktop/巡测.app`；Windows输出 `dist/desktop/DeviceCheck/DeviceCheck.exe`，再用Inno Setup编译 `desktop/DeviceCheck.iss` 生成用户级安装程序。

GitHub Actions 的 Desktop installers 工作流在Windows和Mac分别原生构建，输出可下载的安装包。工作流尚未在远端运行；本机不能验证Windows原生DLL、凭据管理器或模拟器行为。产物未签名；正式分发前需要Windows代码签名及Mac开发者签名、公证。不能将Mac构建产物改后缀当成Windows程序。

运行环境配置与功能范围见 `安装说明.txt`。Appium下载从官方npm源进行；Node/Java/SDK/Flutter/Xcode由用户安装。不会将开发机现有SDK、账号、AI密钥或报告打包进安装程序。
