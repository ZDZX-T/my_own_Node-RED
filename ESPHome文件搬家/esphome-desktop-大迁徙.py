r"""
ESPHome Desktop 数据迁移脚本
将 C 盘上的 ESPHome 相关数据迁移到脚本所在目录，文件夹名保持原名。

用法: python esphome-desktop-大迁徙.py

==============================================================================
官方文档中 Windows 下涉及的所有路径及其可变性
(来源: https://github.com/esphome/esphome-desktop README "Data Locations" 段)
==============================================================================

┌─────────────────────┬──────────────────────────────────────────────┬────────────┐
│ 内容                │ 默认位置                                     │ 可否更改   │
├─────────────────────┼──────────────────────────────────────────────┼────────────┤
│ 程序安装本体        │ %LOCALAPPDATA%\ESPHome Device Builder\       │ 安装时可选 │
│                     │ 即 C:\Users\<用户>\AppData\Local\...         │            │
├─────────────────────┼──────────────────────────────────────────────┼────────────┤
│ 应用数据            │ %APPDATA%\io.esphome.builder\                │ 无官方选项 │
│ (Python运行时/日志/ │ 即 C:\Users\<用户>\AppData\Roaming\...       │ 只能junction│
│  settings.json)     │                                              │            │
├─────────────────────┼──────────────────────────────────────────────┼────────────┤
│ ESPHome 配置文件    │ ~/esphome/                                   │ ★ 可配置   │
│ (.yaml 设备配置)    │ 即 C:\Users\<用户>\esphome\                  │            │
├─────────────────────┼──────────────────────────────────────────────┼────────────┤
│ 构建数据 + 工具链   │ C:\esphb\<id>\                               │ ★ 可配置   │
│ (PlatformIO/ESP-IDF)│                                              │            │
└─────────────────────┴──────────────────────────────────────────────┴────────────┘

==============================================================================
可变项的官方修改方式
==============================================================================

1. ESPHOME_DATA_DIR (用户环境变量)
   - 作用: 覆盖构建数据的根目录，程序直接使用该路径，不再自动重定位到 C:\esphb
   - 设置方法: setx ESPHOME_DATA_DIR "<目标路径>"  (用户级，无需管理员)
   - 附加效果: 设置后代码跳过全部重定位逻辑，PLATFORMIO_CORE_DIR 和
     ESPHOME_ESP_IDF_PREFIX 也不再被自动覆盖
   - 注意: 设置后需重启 ESPHome Desktop；已有项目需 Clean Build
   - 本脚本对应函数: get_user_env_var() 读取 / set_user_env_var() 写入

2. ESPHOME_ESP_IDF_PREFIX (用户环境变量)
   - 作用: 指定 ESP-IDF 工具链的安装前缀目录
   - 默认值: 未设置时回退到 %LOCALAPPDATA%\esphome\Cache\idf
   - 设置方法: setx ESPHOME_ESP_IDF_PREFIX "<目标路径>\idf"
   - 重要: 设置 ESPHOME_DATA_DIR 后必须同时设置此变量，否则 IDF 仍装入 C 盘
   - 本脚本对应函数: get_user_env_var() 读取 / set_user_env_var() 写入

3. settings.json 中的 config_dir 字段
   - 位置: %APPDATA%\io.esphome.builder\settings.json
   - 作用: 指定 .yaml 配置文件的存储目录 (null = 默认 ~/esphome)
   - 格式: {"config_dir": "F:\\esphome", ...}
   - 本脚本对应函数: read_settings() 读取 / write_settings() 写入

4. settings.json 中的 port 字段 (附带说明，本脚本不修改)
   - 作用: Dashboard 监听端口，默认 6052

5. 程序安装路径
   - NSIS 安装器允许在安装时选择目录，本脚本不处理

6. 应用数据目录 (Roaming: %APPDATA%\io.esphome.builder\, Local: %LOCALAPPDATA%\io.esphome.builder\)
   - 无官方配置项；通过 NTFS junction 变通:
     将目录移动到目标位置，再在原位置创建 junction 指向新位置
   - 两处目录同名但内容不同，目标文件夹用后缀区分:
       Roaming → io.esphome.builder(roaming)   (含 logs/、settings.json)
       Local   → io.esphome.builder(Local)     (含 python/ 运行时)
   - junction 链接名必须保持原名，目标文件夹名可任意
   - 本脚本对应函数: is_junction() 检测 / create_junction() 创建 /
     _migrate_appdata_junction() 迁移 / _do_appdata_junction() 执行

==============================================================================
本脚本函数索引
==============================================================================

  函数名                  职责
  ─────────────────────   ──────────────────────────────────────────
  is_esphome_running()    检测 esphome-desktop.exe / esphome.exe 进程
  get_user_env_var()      从注册表读取用户级环境变量 (DATA_DIR / IDF_PREFIX)
  set_user_env_var()      通过 setx 写入用户级环境变量（永久生效）
  read_settings()         读取 %APPDATA%\io.esphome.builder\settings.json
  write_settings()        写入 settings.json（含 config_dir 修改）
  is_junction()           检测路径是否为 NTFS junction
  create_junction()       创建 NTFS junction (mklink /J)
  _on_rm_error()          rmtree 只读文件错误回调
  robust_move()           跨盘安全移动 (copytree + rmtree)
  move_directory()        安全移动目录（含冲突提示）
  _do_appdata_junction()  移动应用数据 + 创建 junction
  _migrate_appdata_junction()  单个应用数据目录迁移（含冲突处理）
  confirm()               用户确认交互
  main()                  主流程: 检测→进程检查→计划展示→确认→执行
"""

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# ============================================================
# 配置区 - 目标路径自动取脚本所在目录，文件夹名保持原名
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent
TARGET_BUILD_DATA = SCRIPT_DIR / "esphb"                       # 构建数据 + 工具链
TARGET_CONFIG_DIR = SCRIPT_DIR / "esphome"                     # ESPHome 配置文件
TARGET_APPDATA_DIR = SCRIPT_DIR / "io.esphome.builder(roaming)"  # Roaming 应用数据 (junction 目标)
TARGET_LOCAL_APPDATA_DIR = SCRIPT_DIR / "io.esphome.builder(Local)"  # Local 应用数据 (junction 目标)
TARGET_IDF_PREFIX = TARGET_BUILD_DATA / "idf"                  # ESP-IDF 工具链前缀
# ============================================================

APPDATA_DIR = Path(os.environ["APPDATA"]) / "io.esphome.builder"          # Roaming 应用数据
LOCAL_APPDATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "io.esphome.builder"  # Local 应用数据
SETTINGS_FILE = APPDATA_DIR / "settings.json"
DEFAULT_CONFIG_DIR = Path.home() / "esphome"
DEFAULT_BUILD_DATA = Path("C:\\esphb")
DEFAULT_IDF_CACHE = Path(os.environ.get("LOCALAPPDATA", "")) / "esphome"  # 机器级 IDF 缓存

ENV_VAR_DATA = "ESPHOME_DATA_DIR"
ENV_VAR_IDF = "ESPHOME_ESP_IDF_PREFIX"


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_step(text: str):
    print(f"\n  [>] {text}")


def print_ok(text: str):
    print(f"  [✓] {text}")


def print_warn(text: str):
    print(f"  [!] {text}")


def print_err(text: str):
    print(f"  [✗] {text}")


def is_esphome_running() -> list[str]:
    """检查 ESPHome 相关进程是否在运行，返回匹配的进程名列表。"""
    targets = ["esphome-desktop.exe", "esphome.exe"]
    found = []
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.splitlines():
            for t in targets:
                if t.lower() in line.lower():
                    found.append(t)
    except Exception:
        pass
    return list(set(found))


def get_user_env_var(name: str) -> str | None:
    """读取当前用户级环境变量。"""
    try:
        result = subprocess.run(
            ["reg", "query",
             "HKCU\\Environment",
             "/v", name],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.splitlines():
            if name in line:
                parts = line.split("REG_SZ")
                if len(parts) == 2:
                    return parts[1].strip()
    except Exception:
        pass
    return None


def set_user_env_var(name: str, value: str):
    """设置用户级环境变量（永久生效）。"""
    subprocess.run(
        ["setx", name, value],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    os.environ[name] = value


def read_settings() -> dict:
    """读取 settings.json。"""
    if SETTINGS_FILE.is_file():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def write_settings(settings: dict):
    """写入 settings.json。"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def is_junction(path: Path) -> bool:
    """检测路径是否为 NTFS junction（目录符号链接）。"""
    if not path.exists() and not path.is_symlink():
        return False
    try:
        # junction 是 reparse point，os.path.islink 在 Python 3.12+ 可检测
        # 但为兼容性，用 fsutil 或检查 FILE_ATTRIBUTE_REPARSE_POINT
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False


def create_junction(link: Path, target: Path) -> bool:
    """创建 NTFS junction: link → target。"""
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return True
        print_err(f"mklink 失败: {result.stderr.strip()}")
        return False
    except Exception as e:
        print_err(f"创建 junction 异常: {e}")
        return False


def _on_rm_error(func, path, exc_info):
    """删除失败时清除只读属性后重试（处理 .git 等含只读文件的目录）。"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def robust_move(src: Path, dst: Path):
    """跨盘安全移动: 先尝试 rename，失败则 copytree + rmtree(带只读处理)。"""
    try:
        os.rename(str(src), str(dst))
    except OSError:
        # 跨盘: 复制后删除源
        if src.is_dir():
            shutil.copytree(str(src), str(dst), symlinks=True)
            shutil.rmtree(str(src), onerror=_on_rm_error)
        else:
            shutil.copy2(str(src), str(dst))
            os.remove(str(src))


def move_directory(src: Path, dst: Path, label: str) -> bool:
    """移动目录，返回是否成功。"""
    if not src.is_dir():
        return True
    if dst.exists():
        print_warn(f"目标已存在: {dst}")
        resp = input(f"      是否删除目标后继续迁移? (y/N): ").strip().lower()
        if resp != "y":
            print_warn(f"跳过迁移: {label}")
            return False
        shutil.rmtree(str(dst), onerror=_on_rm_error)

    print_step(f"正在移动: {src} → {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        robust_move(src, dst)
        print_ok(f"{label} 迁移完成")
        return True
    except OSError as e:
        print_err(f"迁移失败: {e}")
        print_warn("请手动移动该目录")
        return False


def confirm(prompt: str) -> bool:
    resp = input(f"\n  {prompt} (y/N): ").strip().lower()
    return resp == "y"


def _do_appdata_junction(src: Path, dst: Path):
    """移动应用数据目录并在原位置创建 junction。"""
    try:
        robust_move(src, dst)
        print_ok(f"数据已移动到: {dst}")
    except OSError as e:
        print_err(f"移动应用数据失败: {e}")
        print_warn("请手动移动该目录")
        return
    if create_junction(src, dst):
        print_ok(f"已创建 junction: {src} → {dst}")
    else:
        print_err(f"创建 junction 失败，请手动执行:")
        print(f"      mklink /J \"{src}\" \"{dst}\"")


def _migrate_appdata_junction(src: Path, dst: Path, label: str):
    """迁移单个应用数据目录（含目标冲突处理）。"""
    print_step(f"迁移{label}: {src} → {dst}")
    if dst.exists():
        print_warn(f"目标已存在: {dst}")
        resp = input("      是否删除目标后继续迁移? (y/N): ").strip().lower()
        if resp != "y":
            print_warn(f"跳过{label}迁移")
            return
        shutil.rmtree(str(dst), onerror=_on_rm_error)
    _do_appdata_junction(src, dst)


def main():
    print_header("ESPHome Desktop 数据迁移工具")
    print(f"""
  本脚本将完成以下操作:
    1. 设置用户环境变量:
       - {ENV_VAR_DATA} = {TARGET_BUILD_DATA}
       - {ENV_VAR_IDF} = {TARGET_IDF_PREFIX}
    2. 修改 settings.json 中 config_dir = {TARGET_CONFIG_DIR}
    3. 迁移已有数据（如果存在）:
       - 构建数据:  {DEFAULT_BUILD_DATA} → {TARGET_BUILD_DATA}
       - 配置文件:  {DEFAULT_CONFIG_DIR} → {TARGET_CONFIG_DIR}
       - Roaming 数据: {APPDATA_DIR} → {TARGET_APPDATA_DIR} (junction)
       - Local 数据:  {LOCAL_APPDATA_DIR} → {TARGET_LOCAL_APPDATA_DIR} (junction)
       - IDF 缓存:  {DEFAULT_IDF_CACHE} → 清理或迁移
""")

    # ----------------------------------------------------------
    # 第一步: 检测当前状态
    # ----------------------------------------------------------
    print_header("检测当前状态")

    env_data_current = get_user_env_var(ENV_VAR_DATA)
    if env_data_current:
        print_ok(f"环境变量 {ENV_VAR_DATA} 已设置: {env_data_current}")
        if Path(env_data_current) == TARGET_BUILD_DATA:
            print_ok("已指向目标路径，无需重复设置")
    else:
        print_warn(f"环境变量 {ENV_VAR_DATA} 未设置（构建数据默认写入 C:\\esphb）")

    env_idf_current = get_user_env_var(ENV_VAR_IDF)
    if env_idf_current:
        print_ok(f"环境变量 {ENV_VAR_IDF} 已设置: {env_idf_current}")
        if Path(env_idf_current) == TARGET_IDF_PREFIX:
            print_ok("已指向目标路径，无需重复设置")
    else:
        print_warn(f"环境变量 {ENV_VAR_IDF} 未设置（IDF 工具链默认装入 %LOCALAPPDATA%\\esphome）")

    settings = read_settings()
    current_config_dir = settings.get("config_dir")
    if current_config_dir:
        print_ok(f"settings.json config_dir 已设置: {current_config_dir}")
    else:
        print_warn(f"settings.json config_dir 未设置（配置文件默认在 {DEFAULT_CONFIG_DIR}）")

    build_data_exists = DEFAULT_BUILD_DATA.is_dir()
    config_dir_exists = DEFAULT_CONFIG_DIR.is_dir() and any(DEFAULT_CONFIG_DIR.iterdir())

    if build_data_exists:
        # 估算大小
        print_warn(f"发现构建数据: {DEFAULT_BUILD_DATA}")
    else:
        print_ok(f"构建数据目录不存在: {DEFAULT_BUILD_DATA}（无需迁移）")

    if config_dir_exists:
        print_warn(f"发现配置文件: {DEFAULT_CONFIG_DIR}")
    else:
        print_ok(f"配置文件目录不存在或为空: {DEFAULT_CONFIG_DIR}（无需迁移）")

    # 检测 Roaming 应用数据目录
    appdata_is_junction = is_junction(APPDATA_DIR)
    appdata_exists = APPDATA_DIR.is_dir() and not appdata_is_junction
    if appdata_is_junction:
        print_ok(f"Roaming 应用数据已是 junction: {APPDATA_DIR}（无需处理）")
    elif appdata_exists:
        print_warn(f"发现 Roaming 应用数据: {APPDATA_DIR}")
    else:
        print_ok(f"Roaming 应用数据不存在: {APPDATA_DIR}（无需迁移）")

    # 检测 Local 应用数据目录
    local_appdata_is_junction = is_junction(LOCAL_APPDATA_DIR)
    local_appdata_exists = LOCAL_APPDATA_DIR.is_dir() and not local_appdata_is_junction
    if local_appdata_is_junction:
        print_ok(f"Local 应用数据已是 junction: {LOCAL_APPDATA_DIR}（无需处理）")
    elif local_appdata_exists:
        print_warn(f"发现 Local 应用数据: {LOCAL_APPDATA_DIR}")
    else:
        print_ok(f"Local 应用数据不存在: {LOCAL_APPDATA_DIR}（无需迁移）")

    # 检测机器级 IDF 缓存
    idf_cache_exists = DEFAULT_IDF_CACHE.is_dir() and any(DEFAULT_IDF_CACHE.iterdir())
    if idf_cache_exists:
        print_warn(f"发现机器级 IDF 缓存: {DEFAULT_IDF_CACHE}")
    else:
        print_ok(f"机器级 IDF 缓存不存在: {DEFAULT_IDF_CACHE}（无需处理）")

    need_migrate = (
        build_data_exists or config_dir_exists or appdata_exists
        or local_appdata_exists or idf_cache_exists
    )

    # ----------------------------------------------------------
    # 第二步: 如果需要迁移，检查进程
    # ----------------------------------------------------------
    if need_migrate:
        print_header("检查 ESPHome 进程")
        running = is_esphome_running()
        if running:
            print_err(f"检测到 ESPHome 正在运行: {', '.join(running)}")
            print_err("请先关闭 ESPHome Desktop（托盘图标 → 退出），然后重新运行本脚本。")
            input("\n  按回车键退出...")
            sys.exit(1)
        else:
            print_ok("未检测到 ESPHome 进程，可以安全迁移")

    # ----------------------------------------------------------
    # 第三步: 列出操作计划，请求确认
    # ----------------------------------------------------------
    print_header("操作计划")

    actions = []

    if env_data_current != str(TARGET_BUILD_DATA):
        actions.append(f"设置用户环境变量: {ENV_VAR_DATA} = {TARGET_BUILD_DATA}")

    if env_idf_current != str(TARGET_IDF_PREFIX):
        actions.append(f"设置用户环境变量: {ENV_VAR_IDF} = {TARGET_IDF_PREFIX}")

    if current_config_dir != str(TARGET_CONFIG_DIR):
        actions.append(f"修改 settings.json: config_dir = {TARGET_CONFIG_DIR}")

    if build_data_exists:
        actions.append(f"迁移构建数据: {DEFAULT_BUILD_DATA} → {TARGET_BUILD_DATA}")

    if config_dir_exists:
        actions.append(f"迁移配置文件: {DEFAULT_CONFIG_DIR} → {TARGET_CONFIG_DIR}")

    if appdata_exists:
        actions.append(f"迁移 Roaming 应用数据: {APPDATA_DIR} → {TARGET_APPDATA_DIR} (创建 junction)")

    if local_appdata_exists:
        actions.append(f"迁移 Local 应用数据: {LOCAL_APPDATA_DIR} → {TARGET_LOCAL_APPDATA_DIR} (创建 junction)")

    if idf_cache_exists:
        actions.append(f"清理机器级 IDF 缓存: {DEFAULT_IDF_CACHE} (设置环境变量后不再使用)")

    if not actions:
        print_ok("所有配置已就绪，无需任何操作。")
        input("\n  按回车键退出...")
        return

    for i, action in enumerate(actions, 1):
        print(f"    {i}. {action}")

    print(f"""
  注意:
    - 环境变量设置后需重启 ESPHome Desktop 生效
    - 构建数据迁移后，已有项目需要 clean 重新编译
    - 迁移不会删除源目录的父文件夹（如 C:\\esphb 下有其他实例数据）
""")

    if not confirm("确认执行以上操作?"):
        print_warn("已取消，未做任何更改。")
        input("\n  按回车键退出...")
        return

    # ----------------------------------------------------------
    # 第四步: 执行
    # ----------------------------------------------------------
    print_header("开始执行")

    # 4.1 设置环境变量
    if env_data_current != str(TARGET_BUILD_DATA):
        print_step(f"设置用户环境变量 {ENV_VAR_DATA} = {TARGET_BUILD_DATA}")
        set_user_env_var(ENV_VAR_DATA, str(TARGET_BUILD_DATA))
        print_ok(f"{ENV_VAR_DATA} 已设置（用户级，永久生效）")

    if env_idf_current != str(TARGET_IDF_PREFIX):
        print_step(f"设置用户环境变量 {ENV_VAR_IDF} = {TARGET_IDF_PREFIX}")
        set_user_env_var(ENV_VAR_IDF, str(TARGET_IDF_PREFIX))
        print_ok(f"{ENV_VAR_IDF} 已设置（用户级，永久生效）")

    # 4.2 修改 settings.json
    if current_config_dir != str(TARGET_CONFIG_DIR):
        print_step(f"修改 settings.json: config_dir = {TARGET_CONFIG_DIR}")
        settings["config_dir"] = str(TARGET_CONFIG_DIR)
        write_settings(settings)
        print_ok(f"settings.json 已更新: {SETTINGS_FILE}")

    # 4.3 迁移构建数据
    if build_data_exists:
        move_directory(DEFAULT_BUILD_DATA, TARGET_BUILD_DATA, "构建数据")

    # 4.4 迁移配置文件
    if config_dir_exists:
        TARGET_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # 逐个子项移动，避免目标目录已存在时 move 报错
        print_step(f"正在迁移配置文件: {DEFAULT_CONFIG_DIR} → {TARGET_CONFIG_DIR}")
        moved_count = 0
        for item in DEFAULT_CONFIG_DIR.iterdir():
            dst_item = TARGET_CONFIG_DIR / item.name
            if dst_item.exists():
                print_warn(f"  跳过（目标已存在）: {item.name}")
                continue
            robust_move(item, dst_item)
            moved_count += 1
        print_ok(f"配置文件迁移完成（移动了 {moved_count} 项）")
        # 如果源目录已空，删除
        if not any(DEFAULT_CONFIG_DIR.iterdir()):
            DEFAULT_CONFIG_DIR.rmdir()
            print_ok(f"已删除空目录: {DEFAULT_CONFIG_DIR}")

    # 4.5 迁移应用数据 (junction)
    if appdata_exists:
        _migrate_appdata_junction(APPDATA_DIR, TARGET_APPDATA_DIR, "Roaming 应用数据")

    if local_appdata_exists:
        _migrate_appdata_junction(LOCAL_APPDATA_DIR, TARGET_LOCAL_APPDATA_DIR, "Local 应用数据")

    # 4.6 清理机器级 IDF 缓存
    if idf_cache_exists:
        print_step(f"清理机器级 IDF 缓存: {DEFAULT_IDF_CACHE}")
        print_warn("设置 ESPHOME_ESP_IDF_PREFIX 后，此目录不再被使用。")
        resp = input("      是否删除该目录以回收磁盘空间? (y/N): ").strip().lower()
        if resp == "y":
            try:
                shutil.rmtree(str(DEFAULT_IDF_CACHE), onerror=_on_rm_error)
                print_ok(f"已删除: {DEFAULT_IDF_CACHE}")
            except OSError as e:
                print_err(f"删除失败: {e}")
                print_warn(f"请手动删除: {DEFAULT_IDF_CACHE}")
        else:
            print_warn(f"保留: {DEFAULT_IDF_CACHE}（可稍后手动删除）")

    # ----------------------------------------------------------
    # 完成
    # ----------------------------------------------------------
    print_header("迁移完成")
    print(f"""
  已完成所有操作。接下来请:
    1. 重启 ESPHome Desktop（直接启动即可）
    2. 首次编译已有项目时选择 "Clean Build"（工具链路径已变更）
    3. 确认一切正常后，C 盘上不再有 ESPHome 数据残留

  数据位置:
    - 构建数据:    {TARGET_BUILD_DATA}
    - IDF 工具链:  {TARGET_IDF_PREFIX}
    - 配置文件:    {TARGET_CONFIG_DIR}
    - Roaming 数据: {TARGET_APPDATA_DIR} (原位置 junction 指向此处)
    - Local 数据:  {TARGET_LOCAL_APPDATA_DIR} (原位置 junction 指向此处)
""")
    input("  按回车键退出...")


if __name__ == "__main__":
    main()
