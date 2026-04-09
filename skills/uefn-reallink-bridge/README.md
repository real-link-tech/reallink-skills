# Reallink UEFN Bridge 使用文档

## 1. 工具简介

`uefn-reallink-bridge` 是一个连接 **UEFN 编辑器** 与 **独立桌面工具** 的桥接工具，主要用于：

- 在 UEFN 中执行常用控制台命令
- 查看 World Partition / Streaming Cell 布局
- 触发并解析 StreamingGeneration 日志
- 做当前视角内存分析与全图内存扫描
- 快速定位 Actor 和资源到 UEFN 编辑器中

这个工具的用户界面名称是 **Reallink UEFN Editor**。

---

## 2. 适用场景

这个工具适合以下几类工作：

1. **检查 Streaming Cell 布局是否合理**
2. **查某个区域加载了哪些 Cell / Actor**
3. **分析当前视角或整张地图的资源内存占用**
4. **从资源列表快速跳回 UEFN 资产浏览器或编辑器**
5. **从 Cell / Actor 列表快速聚焦到关卡中的对象**

---

## 3. 使用前准备

在使用前，请先确认：

- 你的 UEFN 项目已经安装好本插件
- UEFN 项目已经启动
- 插件已成功加载
- 右下角连接状态显示为 **Connected**

如果你还没有安装，先参考：

- `references/INSTALL.md`

默认情况下，工具通过本地地址连接编辑器：

- `http://127.0.0.1:19877`

如果连接失败，常见原因通常是：

- UEFN 没有打开
- 插件没有安装到当前项目
- UEFN 打开后尚未完成插件初始化
- 当前项目不是已安装本工具的项目

---

## 4. 如何打开工具

### 方式一：在 UEFN 工具栏中打开

插件正常加载后，UEFN 视口工具栏会出现一个 **`Reallink`** 按钮。

点击它后，会启动独立窗口 **Reallink UEFN Editor**。

### 方式二：通过 Python 方式手动启动

如果工具栏按钮没有出现，可以先按安装文档重新检查安装；必要时可按 `references/INSTALL.md` 中的方法手动启动。

---

## 5. 界面结构总览

Reallink UEFN Editor 主要包含 3 个页签：

- **Common**
- **StreamingLayout**
- **MemoryTest**

窗口右下角会显示连接状态：

- **Connected**：已连接到正在运行的 UEFN
- **Disconnected**：当前未连接，部分功能不可用

---

## 6. Common 页签

### 作用

`Common` 页签用于向 UEFN 发送**控制台命令**，并查看执行历史。

它适合做一些快速验证，例如：

- 打开统计信息
- 执行 UEFN 控制台命令
- 做简单调试操作

### 使用方法

1. 打开 `Common` 页签
2. 在输入框中输入控制台命令
3. 点击 **Send** 或直接回车
4. 在下方 `History` 区域查看执行结果

### 示例命令

可以尝试输入：

- `stat fps`
- `stat unit`
- `wp.Editor.DumpStreamingGenerationLog`

### 注意

- 这里输入的是**控制台命令**，不是 Python 代码
- 当状态为 **Disconnected** 时，输入框和发送按钮会自动禁用

---

## 7. StreamingLayout 页签

### 作用

`StreamingLayout` 用来查看 Streaming Cell 的布局、筛选结果以及 Cell 内部的 Actor 信息。

你可以在这个页签中：

- 刷新并重新读取 StreamingGeneration 数据
- 按 Grid / Level 过滤 Cell
- 搜索 Cell、Actor 名称或资源包名
- 在地图上框选 / 点选 Cell
- 查看某个 Cell 中包含哪些 Actor
- 双击 Actor 让 UEFN 视口聚焦到该对象

### 推荐使用流程

首次打开工具时，通常没有预加载的数据，建议这样操作：

1. 打开 `StreamingLayout`
2. 点击右上角 **Refresh**
3. 等待工具触发日志导出并完成解析
4. 解析完成后，再进行筛选、搜索或切换到 `MemoryTest`

### 常用操作

#### 1）过滤 Cell

顶部可以按以下维度过滤：

- **Grid**
- **Level**

选择后，地图和列表会同步更新。

#### 2）搜索

在 `Search` 输入框中输入关键字后点击 **Search**，可以搜索：

- Cell 名称
- Cell 坐标标识
- Actor 名称
- Actor 类名
- Package 名称

搜索结果会同时体现在：

- 地图高亮
- Cell 列表
- Actor 列表

#### 3）查看 Cell 和 Actor

- 点击地图中的 Cell，下面会显示对应 Cell 列表
- 选中某个 Cell 后，下面会展示该 Cell 的 Actor 列表
- **双击 Actor** 可以让 UEFN 直接选中并聚焦该 Actor

### 地图操作

在地图区域可以使用：

- **鼠标左键点击**：选择 Cell
- **鼠标左键拖拽**：框选多个 Cell
- **Ctrl + 左键 / 框选**：追加选择
- **鼠标右键拖拽**：平移视图
- **鼠标滚轮**：缩放
- **Fit**：重置到适合当前视图范围

---

## 8. MemoryTest 页签

### 作用

`MemoryTest` 是本工具中最核心的分析页签，用于做：

- 当前相机位置的内存采样
- 全图网格扫描
- 资源去重后的内存统计
- Texture Streaming 开关对比
- 资源与 Actor 的关联查看

这个页签主要有两种分析方式：

1. **Capture**：分析当前视角附近已加载内容
2. **Scan All**：按网格遍历全图并生成热力图

---

### 8.1 Capture：分析当前视角

#### 适用场景

- 你已经把 UEFN 摄像机移动到某个区域
- 想知道这个位置加载了哪些 Cell / Actor / 资源
- 想快速查看该区域的内存构成

#### 使用步骤

1. 先在 UEFN 中把视角移动到目标区域
2. 切换到 `MemoryTest`
3. 点击右下角 **Capture**
4. 等待工具完成采集与计算
5. 查看左侧地图、Cell 列表、Actor 列表和右侧资源列表

#### Capture 后你能看到什么

- 当前相机位置加载到的 Cell
- 每个 Cell 的内存占用
- 每个 Actor 的估算内存占用
- 资源列表及其大小、类型、引用数量
- 汇总统计图表

#### 结果说明

状态栏中会显示类似信息：

- 当前坐标
- 加载到的 Cell 数量
- 参与统计的资源数量
- 去重后的总内存
- 缓存条目数量

---

### 8.2 Scan All：全图扫描

#### 适用场景

- 想从全局角度查看哪些区域最重
- 想比较不同网格尺寸下的内存热点
- 想把扫描结果保存下来离线分析

#### 使用步骤

1. 打开 `MemoryTest`
2. 在顶部 `Grid` 输入框中设置网格尺寸（单位：米）
3. 点击 **Scan All**
4. 等待扫描完成
5. 查看左侧热力图
6. 点击某个格子查看该格子的 Cell / Actor / Resource 详情

#### 使用建议

- 默认可以先从 `200m` 开始
- 网格越小，结果越细，但扫描通常越慢
- 网格越大，结果越粗，但适合快速看全局热点

#### 扫描完成后可以做什么

- 点击某个网格格子查看该区域详细内容
- **双击某个网格格子**，让 UEFN 摄像机跳到对应位置
- 查看该格子下加载的 Cell、Actor 和 Resource
- 用右侧统计图观察资源类型分布

---

### 8.3 Tex Streaming 开关

顶部有一个 **Tex Streaming** 选项。

它的作用是：

- **开启时**：按纹理流送逻辑估算更接近运行时的内存结果
- **关闭时**：按原始资源大小做统计

建议：

- 想看更接近实际加载效果时，保持开启
- 想看原始资源总量时，可以关闭后重新比较

切换后，工具会自动重新计算当前结果。

---

### 8.4 Save / Load

`MemoryTest` 支持保存和加载扫描结果。

#### Save

点击 **Save** 可以把当前扫描数据导出为 `.json` 文件，用于后续复查。

#### Load

点击 **Load** 可以重新载入之前保存的扫描结果，无需重新跑完整扫描。

#### 适合的场景

- 需要把结果分享给别人
- 需要在离线状态下继续查看
- 想对比不同时间点的扫描数据

---

### 8.5 Clear Cache

点击 **Clear Cache** 可以清空当前依赖缓存。

适合在以下情况使用：

- 你怀疑缓存已经过期
- 资源依赖有较大变动
- 想重新生成一份干净的数据

注意：清空缓存后，下一次采集或扫描通常会更慢，因为需要重新建立缓存。

---

### 8.6 资源列表交互

在 `Resources` 列表中：

- **双击资源**：在 UEFN 内容浏览器中定位资源
- **右键资源**：打开快捷菜单，可进行：
  - `Browse to Asset`
  - `Open in Editor`
  - `Select Actor`（选择关联 Actor）

这对排查“某个资源为什么会出现在这个区域”非常有帮助。

---

## 9. 推荐的基本工作流

如果你只是第一次上手，建议按下面流程使用：

### 场景 A：先看 Streaming 布局

1. 打开 UEFN
2. 点击工具栏 `Reallink`
3. 在 `StreamingLayout` 中点击 **Refresh**
4. 查看 Cell 分布
5. 搜索你关心的区域或 Actor
6. 双击 Actor 回到编辑器定位

### 场景 B：分析当前区域内存

1. 在 UEFN 中把摄像机移动到目标区域
2. 打开 `MemoryTest`
3. 点击 **Capture**
4. 观察：
   - Loaded Cells
   - Actors
   - Resources
   - Total 内存统计

### 场景 C：分析整张地图热点

1. 打开 `MemoryTest`
2. 输入合适的 Grid 尺寸
3. 点击 **Scan All**
4. 点击热力图中的高亮格子
5. 查看该格子的资源与 Actor 构成
6. 需要时点击 **Save** 保存结果

---

## 10. 常见问题

### Q1：右下角一直显示 Disconnected

请检查：

- UEFN 是否已经打开
- 当前项目是否安装了本插件
- 是否已经等待插件初始化完成
- 是否是在正确的项目里打开了工具

如果你刚完成安装，通常重启 UEFN 后再试一次即可。

### Q2：打开工具后没有任何 Cell 数据

这是正常现象。当前版本默认不会在启动时自动加载历史日志。

请先到 `StreamingLayout` 页签点击 **Refresh**，让工具重新触发并读取最新日志。

### Q3：Capture 按钮不可用

通常是因为当前没有连接到 UEFN。

只有在线连接状态下，工具才能获取：

- 当前相机位置
- 实时加载状态
- 资源浏览与 Actor 聚焦能力

### Q4：离线状态下还能做什么

离线状态下，仍然可以做部分分析，但能力会受限：

- 如果之前跑过在线扫描并建立了缓存，可以继续做部分离线扫描
- 可以加载之前保存的扫描结果进行查看
- 不能执行实时 Capture
- 不能直接跳转资源或聚焦 Actor

### Q5：Scan All 很慢怎么办

可以尝试：

- 增大 Grid 尺寸
- 先清理无关内容再分析
- 先跑一次建立缓存，后续重复分析会更快

---

## 11. 一句话理解三个页签

- **Common**：发控制台命令
- **StreamingLayout**：看 Cell 和 Actor 布局
- **MemoryTest**：看内存热点和资源构成

---

## 12. 相关文件

- 安装说明：`references/INSTALL.md`
- GUI 入口：`assets/Python/UefnReallink/reallink_uefn_editor.py`
- Streaming Layout 页签：`assets/Python/UefnReallink/tabs/streaming_layout_tab.py`
- Memory Test 页签：`assets/Python/UefnReallink/tabs/memory_test_tab.py`

如果你后面还想继续完善，我建议下一步可以补两类内容：

1. **带截图的操作说明**
2. **典型问题排查案例**
