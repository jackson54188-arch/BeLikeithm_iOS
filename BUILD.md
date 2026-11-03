# Brokenithm-32：iPad 32 区手台模拟 App

本目录是 [esterTion/Brokenithm-iOS](https://github.com/esterTion/Brokenithm-iOS) 的完整源码，已改为按 iPad 触摸位置输出 **16 列 × 上下 2 排 = 32 路** 触摸信号。通信协议、端口（24864）、共享内存格式全部不变，所以 `Brokenithm-Evolved-iOS` 桥接端和 `chuniio.dll` 都不用改。

原版 App 只处理 16 路：一根手指落在一列，永远写 `2k`；同一格再落第二根手指才写 `2k+1`。本版把屏幕上的触摸区域按上下分排，上排写 `2k+1`、下排写 `2k`，32 路因此可以独立触发。

---

## 一、真实机台为什么是上下两排

萌娘百科与 B 站中二节奏进阶文都写明了：触摸板是 **16 个水平区域，每个区域再分上下两块，共 32 个传感区域**；下排主要承担 slide 与普通 tap，上排用于同一位置叠第二层 hold/tap（例如「按住下排对付 slide、拍上排对付第二层 hold」）。所以本 App 的上下分排不是硬凑 32 路，而是照真机布局做的。

参考：

- [萌娘百科 CHUNITHM](https://zh.moegirl.org.cn/ja/CHUNITHM)：16 条轨道，每条轨道对应键盘有上下两个分区
- [B 站：中二节奏冷知识和小技巧（进阶篇）](https://www.bilibili.com/read/cv23218390/)：32 个传感区域、下排 slide / 上排第二层

> 注意：真机上下排的编号方向没有公开的固定文档。本 App 默认「下排 = `2k`、上排 = `2k+1`」，如果进游戏输入测试发现上下反了，在设置里打开「交换上下传感器」即可。

---

## 二、改了什么

| 文件 | 改动 |
| --- | --- |
| `Brokenithm-iOS/ViewController.m` | 触摸映射改为上下分排；新增分排线、上/下排提示文字；关闭自动锁屏；状态栏常隐 |
| `Brokenithm-iOS/ViewController.h` | 新增 `rowMode`、`swapRows` 等状态 |
| `Brokenithm-iOS/Settings.bundle/Root.plist` | 新增「触摸排布模式」「交换上下传感器」设置项 |
| `Brokenithm-iOS/Info.plist` | 显示名改为 `Brokenithm-32`；设备能力改 arm64；状态栏隐藏 |
| `Brokenithm-iOS.xcodeproj` | 移除原作者 Development Team；Bundle ID 改为 `com.chuni32.pad`；部署目标统一为 iOS 13.0；仅 iPad |
| `Brokenithm-iOS-Release.xcscheme` | 删除指向原作者电脑绝对路径的 Post Action |
| `Pods/`、`Podfile` | 部署目标统一到 iOS 13.0 |
| `.github/workflows/build-ipa.yml` | 免费云端 macOS 编译，输出未签名 IPA |

设置项说明（设置 → 应用 → Brokenithm-32；改完切回 App 生效）：

| 设置 | 默认 | 含义 |
| --- | --- | --- |
| 触摸排布模式 = 16区（原始） | | 与原版完全相同：单指写 `2k`，同格第二指写 `2k+1` |
| 触摸排布模式 = 32区（上下排独立） | ✓ | 下排写 `2k`，上排写 `2k+1`，32 路独立 |
| 触摸排布模式 = 32区（上排同时带上主通道） | | 上排同时写 `2k+1` 和 `2k`。如果上排的 tap/slide 判定异常，用这个兼容模式 |
| 交换上下传感器 | 关 | 上下排对应关系反过来，用于确认编号方向 |
| 启用 Air 输入 | 开 | 顶部（或底部，取决于「Air区域放到下方」）40% 为 Air，其余 60% 才是触摸区 |

**PC 端务必保持 `segatools.ini` 里 `[slider] pairMirror=0`。** 如果驱动把成对通道再镜像一次，App 的分排信息会被抹掉，32 区就退化成 16 对。当前 `D:\SEGA\Chunithm\bin\segatools.ini` 已经是 `pairMirror=0`。

---

## 三、免费编译 IPA（Windows 电脑即可）

iOS App 必须在 macOS 上编译，Windows 上没有合法的 UIKit/iOS SDK 工具链，所以这里用 **你自己的 GitHub 仓库 + GitHub Actions 的免费 macOS 机器** 编译。整个过程：

- 不上传 Apple ID、证书、描述文件（CI 只编译不签名，产物是未签名 IPA）
- 不需要付费开发者账号
- 不上传任何设备信息
- 私有仓库也免费；macOS 机器按 10 倍时长计费，每月免费额度 2000 分钟 → 相当于 200 分钟 macOS，编译只需几分钟

### 3.1 建仓库并上传

1. 注册/登录 GitHub（免费）。
2. 新建仓库，建议选 **Private**，名字随意，例如 `chunithm-ipad32`。
3. 把本目录 `ipad32` 里的**全部内容**上传（包括 `.github`、`Pods`、`Brokenithm-iOS.xcworkspace`）。`.git` 目录可以不上传。
   - 网页上传：Add file → Upload files，把文件夹拖进去；`.github` 是隐藏目录，网页拖拽可能漏掉，确认仓库里存在 `.github/workflows/build-ipa.yml`。
   - 或者在本目录执行：
     ```bash
     git remote set-url origin https://github.com/<你的用户名>/chunithm-ipad32.git
     git add .
     git commit -m "32-zone app"
     git push -u origin master
     ```
4. 打开仓库的 **Actions** 标签页，左侧选 **Build unsigned IPA** → **Run workflow**。
5. 几分钟后任务完成，在页面底部 **Artifacts** 下载 `Brokenithm-32zone-unsigned`。下载得到的是 zip，解压后里面是 `Brokenithm-32zone-unsigned.ipa`。
6. 以后改了源码，重新 push 或手动 Run workflow 即可。

> 如果编译失败：打开失败的那一步日志，常见原因是 GitHub 升级了 macOS 镜像导致 Xcode 版本变化。workflow 会优先选择机器上的 Xcode 16；如果机器只剩更新版本，把 `runs-on: macos-15` 改成当时还提供 Xcode 16 的镜像即可。

### 3.2 有 Mac 的话（可选）

1. 用较新的 Xcode 打开 `Brokenithm-iOS.xcworkspace`。
2. 选中 `Brokenithm-iOS` target → Signing & Capabilities → Team 选你自己的 Apple ID（免费 Personal Team 即可）。Bundle ID 已是 `com.chuni32.pad`，冲突就改成 `com.你的名字.chuni32`。
3. 连接 iPad，选择设备后 Run。Xcode 会直接把 App 装进 iPad。

> 注意：用旧版 Xcode 可能无法向 iPadOS 27 设备安装。走 Sideloadly + 云端 IPA 不受这个限制。

---

## 四、安装到 iPadOS 27.2（免费 Apple ID）

推荐 **Sideloadly**（Windows 版）。它的作用是把未签名 IPA 用你的免费 Apple ID 重新签名并装进 iPad。

1. 在 Windows 安装 [Sideloadly](https://sideloadly.io/)；如果提示缺少驱动，按提示安装 iTunes / Apple Devices。
2. iPad 打开 **设置 → 隐私与安全性 → 开发者模式**，打开后重启 iPad，再确认一次。
3. iPad 用数据线连接电脑，信任此电脑。
4. 打开 Sideloadly，把 `Brokenithm-32zone-unsigned.ipa` 拖进去，Device 选你的 iPad，Apple ID 填你的免费 Apple ID，点 Start。
   - 如果登录被 2FA 卡住，先在 [appleid.apple.com](https://appleid.apple.com/) 生成一个 App 专用密码再填。
   - 免费账号的限制：证书 **7 天有效**、同一设备最多同时装 3 个自签 App、每 7 天最多 10 个 App ID。到期后用 Sideloadly 重新签一次即可，通常不会丢 App 数据。
5. 第一次启动如果提示「未受信任的开发者」，去 **设置 → 通用 → VPN 与设备管理**，信任对应的开发者证书。
6. 因为 Bundle ID 与原版不同（`com.chuni32.pad`），它会作为 **Brokenithm-32** 和原版共存，方便对照测试。

隐私说明：

- 本 App 没有任何统计、广告、账号或外联请求；唯一的网络行为是在 24864 端口**监听**，等桥接服务端从 USB 连进来。
- 仓库和 IPA 里没有 Apple ID、证书或设备信息。
- Sideloadly 是闭源工具，签名时 Apple ID 会发给 Apple 申请免费开发证书（这是免费签名的必要步骤）。如果介意，可以用开源方案：
  - **AltStore Classic + AltServer**（Windows/macOS）：开源，同样免费 Apple ID，需要电脑常开 AltServer 并每 7 天刷新；
  - **SideStore**：开源，需要先导入配对文件并常开 WireGuard，配置更麻烦。
  - 也可以专门注册一个只用于 sideload 的免费 Apple ID。
- iPadOS 27.2 上 **TrollStore 不可用**，不要走免签名路线。

---

## 五、使用与测试

### 5.1 连接顺序

1. 先把 iPad 上的 **Brokenithm-32** 打开并保持前台。
2. 启动 `Brokenithm-Evolved-iOS` 桥接服务端，确认显示已连接。
3. 再启动游戏。
4. 关闭 mux 的情况下 `segatools.ini` 使用 `[chuniio] path=chuniio.dll`；使用 mux 也可以，但同样要保证 `pairMirror=0`。

### 5.2 32 路输入测试

1. 在 App 设置里把「启用 Air 输入」关掉（或进游戏前关掉），这样整块屏幕都是触摸区，上下各占一半。
2. 进入游戏的输入测试。
3. 屏幕下半区每个格子对应一路（默认 `2k`），上半区对应另一路（默认 `2k+1`）。32 个格子逐个点，应当 32 路都有反应。
4. 如果上下正好反了：打开「交换上下传感器」。
5. 如果上排的 tap/slide 判定怪：把模式切到「32区（上排同时带上主通道）」。
6. 如果只想确认兼容性：切回「16区（原始）」，行为与原版一致。

### 5.3 全屏与手势

- `UIRequiresFullScreen` 已保留。iPadOS 26 起系统允许窗口化，如果 App 被拖成小窗口，坐标会按屏幕尺寸计算而错位。请：
  - **设置 → 多任务与手势 → 全屏幕 App**，或
  - 用 **设置 → 辅助功能 → 引导式访问** 锁定在全屏。
- 状态栏和 Home 指示器会自动隐藏，屏幕不会自动熄灭。
- 退出 App：从底部上滑两次（因为 App 请求了延后系统手势），或先关闭引导式访问。

---

## 六、已知限制

1. **Windows 无法本地编译**：必须走云端 macOS 或借 Mac。仓库里已经配好一键编译，不需要你写命令。
2. **未在 iPadOS 27.2 实机验证**：代码只用了 iOS 13 时代就存在的 API，理论上兼容；如果启动闪退，把 Xcode 日志或闪退时间点发我。
3. **免费签名 7 天**：到期重签即可；如果重签后提示描述文件冲突，先删除旧 App 再装（会丢设置，但不会影响游戏）。
4. **32 区依赖 `pairMirror=0`**：PC 端驱动如果打开成对镜像，App 输出会被合并。
5. **上下排编号方向**：默认下排 `2k`、上排 `2k+1`，这是根据原版 App「第一根手指写 `2k`」和真机「下排滑条」推断的；不对就打开「交换上下传感器」。

---

## 七、常见问题

| 现象 | 处理 |
| --- | --- |
| Actions 编译失败 | 看日志里 Xcode 版本；把 workflow 的 `macos-15` 换成仍有 Xcode 16 的镜像，或把 `CODE_SIGNING_*` 参数保持原样 |
| Sideloadly 报 “Unable to connect” | 换线/换 USB 口，安装 Apple Devices 驱动，iPad 解锁并点信任 |
| 安装后点图标闪退 | 先信任证书；仍闪退则用 Sideloadly 重签一次（免费证书可能已过期） |
| 只有 16 路有反应 | 检查 `segatools.ini` 的 `pairMirror` 是否为 0；检查 App 设置是否被切回 16 区模式 |
| 32 路有反应但游戏手感不对 | 试试交换上下传感器；再不行用「上排同时带上主通道」模式 |
| iPad 灯光不显示/闪烁 | 与本 App 无关，按 `rebuilt/README.md` 的 `tools/shm_monitor.py` 判定是游戏输出还是桥接显示端 |

---

## 八、验证记录（能做到与做不到）

- 已核对原版协议：`struct ioBuf` 仍是 1 字节长度 + `INP` + 6 字节 Air + 32 字节 slider + test + service，未改字段顺序。
- 已核对桥接端：`Brokenithm-Evolved-iOS` 把 32 字节原样写入共享内存偏移 6，驱动原样复制，`pairMirror` 只影响驱动侧。
- 已用 Python 校验 `Info.plist`、`Settings.bundle/Root.plist` 语法。
- 已把触摸映射逻辑抽成 C 程序逐项跑过：16 列 × 上下排共 32 个格子逐个模拟，32/32 全部独立命中；边缘邻格补位、交换上下、三种模式、Air 区域排除、双指同格叠加均符合预期。
- 未在 Windows 上编译 iOS 工程（无 macOS 工具链），也未在 iPadOS 27.2 实机运行；CI 的第一次构建就是实际编译验证。
