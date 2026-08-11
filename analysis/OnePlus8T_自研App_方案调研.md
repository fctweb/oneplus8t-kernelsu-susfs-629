# 自研伪装管理器 App —— 方案调研报告

> 2026-08-11 · 基于抹机王逆向分析 + 1996 款机型库 + 现有内核/SUSFS 能力

---

## 1. 抹机王功能拆解(40+ 页面归类)

逆向 `activity_*.xml` 布局,功能归为 10 大模块:

| # | 模块 | 页面 | 说明 |
|---|---|---|---|
| 1 | **机型伪装** | device_info / device_info2 / brand_mode_setting / brandsetting / phone_model_setting | 选品牌 → 选型号 → 伪装 15 字段(imei/android_id/序列号/bssid/mac/蓝牙mac/型号/厂商/固件/系统版本/软件版本/CPU/电话/sim序列号/ICCID) |
| 2 | **环境管理** | env_manager / env_restore / app_env_guide | 多套"环境配置"保存/修改/删除/还原/全选(类似"场景") |
| 3 | **IMEI/号码** | imei_setting2 / phone_num_setting | IMEI/手机号生成(TAC/号段规则) |
| 4 | **定位伪装** | location_setting / location_setting2 / country_setting | 模拟定位 + 国家地区 |
| 5 | **数据清理** | data_clean_setting2 / dataclean_setting / data_save_setting | 清理 App 数据/保存 |
| 6 | **隐藏 App** | hideapp_setting | 隐藏指定应用 |
| 7 | **网络** | net_setting / ftp_server | 网络设置 + FTP 同步 |
| 8 | **检测** | dev_env_detect / app_tool | 环境检测 + 工具 |
| 9 | **账号/付费** | login / register / order / order_detail | 登录/充值(我们不需要) |
| 10 | **其他** | other_setting / quick_setting / privacy_setting / process / log_manage | 杂项/进程/日志 |

**主界面结构**:3 Tab(首页 / 充值绑定 / 更多)+ 各功能入口列表。

**核心交互**:device_info 页显示 15 字段 → 修改 → 保存环境 → 重启生效(沙盒模式下仅选定 App 生效)。

---

## 2. 我们的功能范围(取舍)

**核心差异**:抹机王是"沙盒内 Hook 应用进程"(Java 层,只改指定 App 看到的信息);我们是 **SUSFS 内核级全局伪装**(改系统属性/文件,所有 App 看到伪装值)。

**已验证前提**:全局伪装 + 现有内核 → 农业/兴业银行、Momo TEE 均通过 → **全局方案可行,App 定位为"配置器"**。

### 功能取舍表

| 功能 | 是否做 | 理由 |
|---|---|---|
| **机型伪装(核心)** | ✅ 必做 | 1996 款机型库 → 选机型 → 生成 SUSFS 配置 |
| **环境管理(多场景)** | ✅ 必做 | 多套配置(如"银行场景"/"日常场景")保存切换 |
| **检测自检** | ✅ 必做 | 内置检测:当前暴露面预览(属性/文件/进程)——替代手动开 Hunter |
| **一键还原** | ✅ 必做 | 恢复真实设备配置(SUSFS 配置清空) |
| IMEI/序列号生成 | 🟡 二期 | 规则已逆向,但改 IMEI 影响大(需恢复出厂/双卡异常) |
| 定位伪装 | ❌ 不做 | 系统级定位伪装需 Hook LocationManager——不是 SUSFS 能力,另立项目 |
| 数据清理 | ❌ 不做 | 与应用伪装无关 |
| FTP/账号/付费 | ❌ 不做 | 自研无此需求 |

---

## 3. 架构方案(MVI + Jetpack + 银行检测影响)

### 3.1 对银行检测的影响分析(架构约束)

| 约束 | 方案 |
|---|---|
| **App 自身被检测到** | 包名不可含敏感词(如 hide/spoof/change);App 本体不常驻 root(配置器模式:启动时提权写入配置 → 退出);后续可做"隐藏 App"(sus_paths 隐藏其安装目录/图标) |
| **伪装逻辑不引入新暴露面** | 伪装数据全部由**内核 SUSFS 生效**(set_props/sus_paths),App 只写 `/data/adb/ksu/susfs_config.json` 配置——不常驻、不注入、不改系统文件 |
| **root 操作痕迹** | App 仅在用户点"应用"时通过 ksud 提权(一次性);不保留 root 服务 |
| **伪装后系统一致性** | 机型库 1996 款保证 device/fingerprint 自洽;应用后**必须重启**(属性缓存)——UI 明确提示 |

### 3.2 MVI 架构(Google 官方推荐组合)

**不使用第三方 MVI 框架,用官方组件实现单向数据流**(用户要求"Google 官方推荐"):

```
UI(Compose) → Intent → ViewModel(StateFlow 状态管理) → Repository → 数据源
                     ↑                                        ↓
                     └──────── State 回传(单向数据流)─────────
```

| 层 | 组件 | 职责 |
|---|---|---|
| UI 层 | **Compose + Material3** | 声明式 UI;机型列表/环境卡片/自检结果 |
| 状态层 | **ViewModel + StateFlow**(lifecycle-viewmodel-compose) | MVI 的 State 持有;`uiState: StateFlow<AppUiState>` |
| 意图层 | 事件函数(sealed class Intent) | `UserIntent.LoadDevices / SelectProfile / ApplyConfig` |
| 数据层 | **Repository + Room + DataStore** | 机型库查询、环境配置 CRUD、设置 |
| DI | **Hilt** | 依赖注入 |
| 导航 | **Navigation Compose** | 单 Activity 多页面 |

### 3.3 关键页面(交互设计——比抹机王更适合我们)

| 页面 | 交互 |
|---|---|
| **首页(仪表盘)** | 当前伪装状态卡片(已伪装机型/字段数/是否生效)+ 检测自检摘要(绿/黄/红)+ "应用新伪装"主按钮 |
| **机型库**(搜索) | 顶部搜索框(品牌/型号模糊搜索)+ 品牌筛选 Chips + 列表(品牌/型号/SoC/Android 版本)+ 选中预览 15 字段 |
| **环境管理** | 场景列表(如"银行场景"/"日常")+ 保存当前配置 + 切换 + 删除 |
| **检测自检** | 逐项列出暴露面(属性/文件/进程/内核标识)+ 每项状态(已隐藏/暴露)+ 一键复制检测报告 |
| **设置** | 开机自检开关 / 还原确认 / 关于 |

---

## 4. 数据层设计(Room 决策)

### 4.1 数据分类

| 数据 | 类型 | 存储方案 |
|---|---|---|
| **机型库 1996 款**(固定只读) | 静态数据 | **Room 预置 db**(assets 内预生成 SQLite,首启导入) |
| **环境配置**(用户创建) | 可变数据 | **Room**(entity: Profile{id, name, deviceId, fields, updatedAt}) |
| **设置**(自检开关等) | 轻量 KV | **DataStore Preferences** |
| **自检历史**(可选) | 可变数据 | Room 或 DataStore |

### 4.2 机型库:Room vs assets JSON 对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| **Room 预置 db**(推荐) | 支持 SQL 模糊搜索(品牌/型号/SoC);分页加载(1962 行流畅);后续可增量更新 | 需预生成 db 文件(构建时脚本从 JSON 生成);首次导入约几十 ms |
| assets JSON 直接读 | 简单;无导入 | 需全量加载内存;搜索只能内存过滤;1962 行全量解析慢 |

**决策**:机型库用 **Room 预置 db**(构建时用 Python/SQLite 脚本从 `device_profiles.json` 生成 `devices.db` 放 assets,首启 `createFromAsset` 导入)——**支持 1962 行的搜索/过滤/分页**,且与用户配置同库统一 DAO。

### 4.3 表结构

```sql
-- 机型库(只读,预置)
CREATE TABLE devices (
  id INTEGER PRIMARY KEY,
  brand TEXT, model TEXT, device TEXT, manufacturer TEXT,
  soc TEXT, soc_name TEXT, density INTEGER,
  fingerprint TEXT, source TEXT
);
CREATE INDEX idx_devices_brand_model ON devices(brand, model);

-- 环境配置(用户创建)
CREATE TABLE profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,                    -- 场景名("银行场景")
  device_id INTEGER,            -- 关联 devices.id
  custom_fields TEXT,           -- 用户覆盖字段 JSON(IMEI 等)
  enabled INTEGER DEFAULT 0,
  updated_at INTEGER
);
```

---

## 5. 技术选型清单(2026 稳定版)

| 组件 | 选型 | 说明 |
|---|---|---|
| 语言 | Kotlin 2.x | |
| UI | **Compose BOM + Material3** | 声明式 UI |
| 架构 | ViewModel + StateFlow(MVI) | 官方单向数据流 |
| 本地存储 | **Room 2.8.x** | 机型库 + 配置 |
| 设置 | **DataStore Preferences** | |
| DI | **Hilt 2.5x** | |
| 导航 | Navigation Compose | |
| 异步 | Coroutines + Flow | |
| minSdk / targetSdk | 26 / 34(Android 13 设备) | |
| 构建 | Gradle KTS + version catalog | |

---

## 6. 开放问题(需用户决策/后续实验)

| # | 问题 | 现状 | 建议 |
|---|---|---|---|
| 1 | **伪装后是否重启** | SUSFS 属性伪装需重启(zygote 缓存)——但可在 `post-fs-data` 生效 | MVP 强制重启;后续调研免重启(ksud 热重载 susfs_config?) |
| 2 | **per-app 伪装(SUSFS uid 扩展)** | SUSFS 全局生效;KernelSU 有 per-app umount | 二期调研:按 uid 区分 sus_path(内核 patch) |
| 3 | **App 自身隐藏** | 检测器可看到"伪装 App"本身 | 二期:sus_paths 隐藏安装目录 + 桌面图标(需保留入口——通知栏/拨号暗码) |
| 4 | **IMEI 是否做** | 规则已逆向;改 IMEI 影响大 | 默认不做,二期可选 |
| 5 | **机型库精确 fingerprint** | 固件源有精确;设备树/知识库为格式自洽 | 后续从 EMUI/固件补 compiler 字段 |
| 6 | **免 root 模式** | App 需 root 写配置 | 仅"应用/还原"时提权,非常驻 |
| 7 | **多设备机型交叉验证** | 部分机型 device 与 fingerprint 需核对 | 应用前 App 内做一致性校验提示 |

---

## 7. 实施里程碑

| 里程碑 | 内容 | 预估 |
|---|---|---|
| **M1 MVP** | 项目骨架(MVI+Room+Compose)+ 机型库导入 + 机型选择 UI + SUSFS 配置生成/应用 + 检测自检(基础) | 核心 |
| **M2** | 环境管理(多场景)+ 一键还原 + 自检完善 | 增量 |
| **M3** | App 自身隐藏 + per-app 伪装(内核 patch)+ 免重启 | 增强 |
| **M4** | IMEI/序列号等扩展 + 机型库增量更新机制 | 可选 |

---

## 8. 结论

1. **方案可行**:全局 SUSFS 伪装已验证(银行通过)——App 作为"配置器 + 环境管理器"落地 1996 款机型库
2. **架构**:Google 官方 MVI(Compose + ViewModel + StateFlow + Hilt + Room)
3. **数据**:机型库 Room 预置 db(1962 行搜索/分页),配置 Room,设置 DataStore
4. **银行检测**:App 不常驻 root、伪装走内核、包名避开敏感词——不引入新暴露面
5. **最大开放问题**:重启生效(可接受,MVP 强制重启)、App 自身隐藏(二期)
