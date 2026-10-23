# DeepSeek Harness Launcher

Windows 图形启动器，用来管本机 [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness) 的 `dsh web`：窗口关掉会进托盘，插件市场点「立即重启」时启动器自己不会跟着退出。

仓库：[github.com/martjay/DSH-Lancher](https://github.com/martjay/DSH-Lancher)

## 需要什么

- Windows 10/11
- [uv](https://docs.astral.sh/uv/)（一键脚本会用它装依赖）
- 本机已能跑 DSH / Node（启动器会尽量帮你找 `dsh` 和 Node）

## 一键脚本

| 文件 | 作用 |
|------|------|
| `install.bat` | `uv sync --extra build` 安装运行和打包依赖 |
| `start.bat` | 启动图形界面 |
| `build-exe.bat` | 打出 `dist/DeepSeek Harness.exe`（图标 `assets/dsh.ico`） |

窗口标题、任务栏、exe 都用 DeepSeek Harness 的 `dsh.ico`。

也可以：

```bat
uv sync
uv run dsh-launcher
```

测试：

```bat
uv sync --extra dev
uv run pytest
```

## 启动器会做什么

- 独立进程监督 `dsh web`（官方默认 `http://127.0.0.1:3080/`；若改过补丁则按 `cordis.patch.yml`）
- **改端口 / 恢复默认**：自定义写成数字；恢复默认写回官方表达式 `!!js ctx.webStartup.port ?? 3080`
- **关闭窗口缩到托盘**，右键：显示窗口、打开网页、启动/停止/手动重启、退出（退出才会停 Harness）
- 市场「立即重启」会杀掉原进程并拉起新实例：启动器继续留着，端口恢复后显示「运行中」
- 若进程和端口都没了，会自动再拉起
- **手动重启**会停掉占用该端口的进程树再启动，日志重新接到窗口里
- 开关「暂时关闭 DSH 自带网络搜索」写入 `~/.dsh/profiles/web/cordis.patch.yml`；Harness 若在跑会自动重启使补丁生效
- 国内镜像、Chrome 打开、语言、开机自启等写在启动器自己的设置里
- **插件页**：对照 npm `latest` 显示可更新项；GitHub 热更新已经比 npm 新的包会标出来，不会当成「该降级」。装/卸其它插件时尽量保住这些热更新目录，避免 pnpm 按 `package.json` 钉死版本把它们盖回去
- 启动日志若出现 `package.json.lock` 超时，会提示多半是插件启动瞬间抢写配置，而不是「清一次过期锁就好了」

## 布局

```
src/dsh_launcher/   启动器源码
tests/              pytest
scripts/build_exe.py
assets/dsh.ico
```
