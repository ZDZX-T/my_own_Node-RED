# ESPHome Desktop 数据迁移脚本

将 C 盘上的 ESPHome Desktop 相关数据迁移到脚本所在目录，文件夹名保持原名。
解决 ESPHome Desktop 将大量数据（构建产物、工具链、配置文件）写入 C 盘、占用系统盘空间的问题。

## 功能特性

- **一键迁移**：自动检测并迁移 5 类 ESPHome 数据到脚本所在目录
- **环境变量设置**：自动写入用户级环境变量 `ESPHOME_DATA_DIR` 与 `ESPHOME_ESP_IDF_PREFIX`（永久生效，无需管理员权限）
- **配置文件重定向**：修改 `%APPDATA%\io.esphome.builder\settings.json` 中的 `config_dir`
- **NTFS junction 迁移**：对无官方配置项的应用数据目录（Roaming / Local），通过 junction 链接实现零感知迁移
- **安全校验**：迁移前检测 `esphome-desktop.exe` / `esphome.exe` 进程，运行中会阻止迁移
- **交互式确认**：执行前展示完整操作计划，逐项请求用户确认
- **幂等执行**：已配置好的项目会自动跳过，可重复运行

## 迁移数据一览

| 数据 | 默认位置（C 盘） | 迁移后位置（脚本目录） | 迁移方式 |
|------|------------------|------------------------|----------|
| 构建数据 + 工具链 | `C:\esphb\<id>\` | `./esphb/` | 移动目录 + 环境变量 |
| ESP-IDF 工具链 | `%LOCALAPPDATA%\esphome\Cache\idf` | `./esphb/idf/` | 移动目录 + 环境变量 |
| ESPHome 配置文件 (.yaml) | `~/esphome/` | `./esphome/` | 移动目录 + settings.json |
| Roaming 应用数据 | `%APPDATA%\io.esphome.builder\` | `./io.esphome.builder(roaming)/` | junction 链接 |
| Local 应用数据 | `%LOCALAPPDATA%\io.esphome.builder\` | `./io.esphome.builder(Local)/` | junction 链接 |

> 说明：迁移后原路径保留 junction 指向新位置，ESPHome Desktop 无需重新配置即可继续工作。

## 环境要求

- Windows 系统（依赖 `setx`、`reg`、`mklink /J`、`tasklist` 等系统命令）
- Python 3.10+（使用了 `str \| None` 类型注解语法）
- 无需管理员权限

## 使用方法

0. **下载安装ESPHome Desktop**：[https://esphome.io/install/](https://esphome.io/install/)  

1. **放置脚本**：将脚本放置于迁移的目标目录（一般是 ESPHome 的安装目录，脚本会将所有数据迁移到其所在目录）

2. **执行迁移**：进入脚本所在目录，运行：

```powershell
python esphome-desktop-大迁徙.py
```

执行流程：

1. **检测当前状态** — 检查环境变量、settings.json、各数据目录是否存在
2. **进程检查** — 若 ESPHome 正在运行则中止（需先退出）
3. **展示操作计划** — 列出所有将要执行的操作，输入 `y` 确认
4. **执行迁移** — 依次设置环境变量、修改配置、迁移数据、创建 junction
5. **完成提示** — 重启 ESPHome Desktop 并 Clean Build 即可

## 注意事项

- 迁移前请**备份重要数据**，并先退出 ESPHome Desktop（托盘图标 → 退出）
- 环境变量设置后需**重启 ESPHome Desktop** 才生效
- 构建数据迁移后，已有项目首次编译需选择 **Clean Build**（工具链路径已变更）
- 机器级 IDF 缓存（`%LOCALAPPDATA%\esphome`）迁移后不再使用，脚本会询问是否删除以释放空间
- 迁移操作不可自动回滚，目标目录已存在时会提示是否删除后继续
- 脚本所在目录需与 C 盘处于**不同磁盘分区**才能实现"搬家"目的（脚本本身支持跨盘移动）

## 脚本主要函数

| 函数 | 职责 |
|------|------|
| `is_esphome_running()` | 检测 ESPHome 相关进程是否运行 |
| `get_user_env_var()` / `set_user_env_var()` | 读取 / 写入用户级环境变量（注册表 / setx） |
| `read_settings()` / `write_settings()` | 读写 `settings.json`（含 config_dir 修改） |
| `is_junction()` / `create_junction()` | 检测 / 创建 NTFS junction |
| `robust_move()` | 跨盘安全移动（rename 失败则 copytree + rmtree） |
| `move_directory()` | 安全移动目录（含冲突提示） |
| `_do_appdata_junction()` / `_migrate_appdata_junction()` | 应用数据目录迁移 + junction 创建 |
| `main()` | 主流程：检测 → 进程检查 → 计划展示 → 确认 → 执行 |