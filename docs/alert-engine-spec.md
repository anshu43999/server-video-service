# 公共告警引擎规格（Alert Engine Specification）

规格版本：`v1`
状态：**冻结**。两处实现共用，改动必须先改本文与 `alert-engine.schema.json`，再改实现。
机器可读契约：[alert-engine.schema.json](alert-engine.schema.json)
一致性向量：[alert-engine-conformance/](alert-engine-conformance/)
相关决策：[ADR-002 生产传输协议](adr-002-production-transport.md)

## 0. 定位与边界

这是一个**告警**引擎，不是预警引擎。它做的事只有一件：把模型对图片或视频的识别结果，按用户设置的阈值判定为事件并告警。它**不做**趋势外推、不做起火预判、不推测未来状态。所有判定都基于已经观测到的事实。

引擎**与具体模型、具体业务场景无关**。场景通过「场景包」注入，场景包 = 模型产物 + Manifest 标签契约 + 推荐规则模板 + 推荐 ROI 形态 + 已知误报源清单。这是模型影响引擎行为的**唯一接缝**：引擎源码中不得出现任何业务类别名（`Hardhat`、`smoke`、`person` 等一律来自配置）。

两处实现：

| 实现 | 位置 | 覆盖范围 |
|---|---|---|
| 服务端 | `server-video-service`，`M11` | 远程视频流事件。一路流推理一次，事件在服务端产生 |
| App 侧 | `mobile-app`，`M15` | 本地相册图片与本地相机预览事件。App 对**接收到的远程流不做任何推理**，只订阅服务端下发的事件 |

同一份规格、同一套算子语义、同一套阈值含义、同一套金样向量。两侧的差异只允许出现在存储、界面与投递通道上。

## 1. 三条硬约束

**C-1 求值器是纯函数，时间只来自观测。**
所有算子求值与状态推进都写成 `(状态, 观测) → (新状态, 判定)`。引擎内部**不得**读取系统时钟（`System.currentTimeMillis`、`time.time()`、`Instant.now()` 等一律禁止出现在求值路径上）。所有时间戳由观测携带。这条约束让两侧行为可比、可重放、可用向量验证。

**C-2 一份规格两处实现，冲突时改规格。**
金样向量是唯一裁判。某一侧向量失败时，按「规格不完整」处理：回到本文与 Schema 补全定义，再同步两侧。**不允许**某一侧单方面改实现或改向量去对齐另一侧。

**C-3 能力不足必须显式拒绝，不允许静默不触发。**
规则声明它需要的能力，来源声明它提供的能力。两者不匹配时，规则绑定动作返回明确的拒绝原因，并在管理页可见。一条规则绝不能因为「模型不输出框」这类原因安静地永不触发 —— 那是最难排查的失效形态。

## 2. 五层结构

```text
① 观测接入   统一观测信封：检测框 / 分类结果 / 分割掩膜 / 标量读数
      │      来源标识、帧序号、观测时间戳、帧尺寸、模型标识
      ▼
② 特征聚合   按 subjectKey 归集：目标级、区域级、指标级、来源级、整帧级
      │      跟踪关联、ROI 关系判定、滑动窗口维护
      ▼
③ 规则求值   算子 × 阈值 → 命中（RuleHit）。纯函数，无副作用
      │
      ▼
④ 事件生命周期  候选 → 确认 → 冷却 → 结束；严重级别分档；未处置提级
      │
      ▼
⑤ 投递处置   管理页实时推送 / App 内通知 / 邮件·短信·企业IM；确认、误报标记、误报回流
```

层与层之间只允许单向数据流。②③ 层必须满足 C-1；④ 层的时间推进同样由观测或显式的「时钟观测」驱动（见 §11.4）。

## 3. 主体标识 subjectKey

`subjectKey` 是引擎的核心抽象：**告警的对象是谁**。它取代了原先只能表达「某个被跟踪目标」的 `trackId`。

格式为 `<kind>:<id>`，`kind` 取五个值之一，`id` 为非空且不含 `:` 的安全字符串（`[A-Za-z0-9_.\-]{1,64}`）：

| kind | 形如 | 含义 | 典型算子 |
|---|---|---|---|
| `track` | `track:12` | 单个被跟踪目标实例 | `PRESENCE`、`IN_REGION`、`LINE_CROSS`、`DWELL` |
| `roi` | `roi:pit-north` | 一个感兴趣区域整体 | `COUNT`、`AREA_RATIO`、`ABSENCE`、`RATE` |
| `metric` | `metric:pm25-01` | 一路标量读数 | `METRIC_THRESHOLD`（预留） |
| `source` | `source:cam-07` | 整路来源 | `COUNT`、`RATE`、`ABSENCE` |
| `frame` | `frame:img-8a3f` | 单张图片（无时序） | `PRESENCE`、`AREA_RATIO` |

约定：

1. `subjectKey` 在同一主体的生命周期内**必须稳定**。`track:{id}` 的稳定性由跟踪器负责；跟踪丢失后重新分配的 id 是**另一个主体**。
2. `frame:` 用于本地相册图片这类单帧场景。单帧主体**不得**用于任何依赖时序的算子（`DWELL`、`LINE_CROSS`、`RATE`、`ABSENCE`），违反时按 C-3 拒绝。
3. 事件、去重键、快照与存储索引一律以 `subjectKey` 为准，不得再以 `trackId` 作为主键维度。
4. `roi:` 与 `source:` 主体在一帧内**至多产生一个**命中，聚合发生在命中之前（§4.4）。
5. `id` 由观测**确定性派生**，两侧不得各自命名：`track:{detections[].trackId}`、`roi:{roiId}`、`source:{sourceId}`、`frame:{sourceId}`、`metric:{scalars[].metricId}`。单张图片以 `sourceId` 作为图片标识，因此同一张图片的 `frame:` 与 `source:` 主体 `id` 相同、`kind` 不同，两者仍是**两个不同主体**，各自独立走生命周期与冷却。

## 4. 观测信封（Observation）

引擎的唯一入口。一帧（或一张图片）产生一个信封，四类载荷可同时存在，也可全部为空。

```json
{
  "sourceId": "cam-07",
  "frameSeq": 1024,
  "capturedAtUs": 1772500800123456,
  "frameWidth": 1920,
  "frameHeight": 1080,
  "model": { "modelId": "site-ppe-v1", "classNames": ["Person", "Hardhat", "NO-Hardhat"] },
  "provides": ["BOX", "TRACK"],
  "detections": [
    { "label": "NO-Hardhat", "confidence": 0.83,
      "box": { "x": 0.31, "y": 0.22, "w": 0.12, "h": 0.34 }, "trackId": "12" }
  ],
  "classifications": [ { "label": "fire", "confidence": 0.77 } ],
  "masks": [ { "label": "smoke", "confidence": 0.71, "areaRatio": 0.14,
               "polygon": [[0.1,0.2],[0.4,0.2],[0.4,0.6]] } ],
  "scalars": [ { "metricId": "pm25-01", "value": 83.2, "unit": "ug/m3" } ]
}
```

### 4.1 时间与单位

- `capturedAtUs`：**微秒**，观测发生时刻。这是引擎唯一的时间来源。
- 所有时长与窗口配置用**毫秒**（`minDwellMs`、`cooldownMs`、`rateWindowMs`、`escalateAfterMs`）。
- 同一 `sourceId` 的 `capturedAtUs` **必须单调不减**。违反时实现必须抛错而不是排序或丢弃 —— 静默容忍会让延迟与频次计算失去意义。`frameSeq` 允许跳号（latest-only 丢帧是正常的），跳号不构成错误。

### 4.2 坐标与归一化

`box` 与 `polygon` 一律使用归一化坐标，原点左上，`x`/`y` ∈ [0,1]，`w`/`h` ∈ (0,1]，且 `x+w ≤ 1`、`y+h ≤ 1`。归一化让规则与 ROI 不随分辨率变化而失效。`frameWidth`/`frameHeight` 仅用于存证与展示换算，不参与判定。

### 4.3 四类载荷与能力

| 载荷 | 提供的能力 | 缺失时的后果 |
|---|---|---|
| `detections` 带 `box` | `BOX` | 所有区域与几何算子不可用 |
| `detections` 带 `trackId` | `TRACK` | `LINE_CROSS`、`DWELL`、按目标的 `RATE` 不可用 |
| `classifications` | 无（整帧标签） | 只能支撑 `frame:` 主体的 `PRESENCE` |
| `masks` 带 `areaRatio` | `MASK` | `AREA_RATIO` 退化为按 `box` 面积估算（精度更低，必须在事件快照里标记 `areaSource`） |
| `scalars` | `SCALAR` | `METRIC_THRESHOLD`（预留）不可用 |

`provides` 字段是来源的**显式声明**，用于 §6 的绑定检查。它必须与实际载荷一致；声明 `BOX` 却从不给框，属于来源实现缺陷，引擎不负责纠正，但应在指标中暴露「声明能力与实际载荷不符」的计数。

**分类模型的特别说明**：`yolo11-cls` 一类的分类权重只产生 `classifications`，没有框、进不了跟踪器，因此拿不到 `track:` 主体，也无法参与 `AREA_RATIO` 与任何 ROI 算子。这类模型只能绑定 `frame:` 或 `source:` 主体的 `PRESENCE`/`RATE` 规则。绑定其他规则时按 C-3 显式拒绝。

### 4.4 聚合发生在命中之前

`roi:`、`source:`、`frame:` 主体的算子需要「一帧内的全部命中」，因此必须先做**按主体的反向聚合**：遍历本帧全部载荷，按 ROI（或来源、整帧）归集出计数、面积与标签集合，再交给算子。这与 `track:` 主体逐目标求值的方向相反，两条路径必须都实现。

## 5. ROI 几何

三种形态，`shape` 为判别字段。**多边形是必须支持的形态**（工地基坑、通道、料场大多不是矩形）。

```json
{ "roiId": "pit-north", "shape": "POLYGON",
  "points": [[0.10,0.20],[0.55,0.18],[0.60,0.72],[0.12,0.70]] }
{ "roiId": "gate-line", "shape": "LINE",
  "points": [[0.20,0.50],[0.80,0.55]], "positiveDirection": "LEFT_TO_RIGHT" }
{ "roiId": "yard", "shape": "RECT", "rect": { "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.4 } }
```

### 5.1 构造期校验（必须拒绝的退化输入）

| 形态 | 拒绝条件 |
|---|---|
| `RECT` | `w ≤ 0` 或 `h ≤ 0`；越界（`x < 0`、`y < 0`、`x + w > 1`、`y + h > 1`） |
| `POLYGON` | 点数 < 3；存在重复相邻点（含末点与首点）；边自相交；面积为 0（`|shoelace| ≤ ε`） |
| `LINE` | 点数 ≠ 2；两点重合（零长，两点距离 `≤ ε`） |

退化几何在**构造时**拒绝，不在求值时静默返回「不相交」。理由与 C-3 相同：一个永不触发的规则比一个报错的规则难查得多。

**「边自相交」的判定**（两侧必须一致，否则同一份 ROI 一侧能建一侧建不了）：把多边形看作首尾相接的 `n` 条边，逐对检查。

- **非相邻的两条边**：交集非空即拒绝 —— 包含正常穿越、只在端点接触、以及共线重叠三种情况。
- **相邻的两条边**（共享一个端点）：只允许恰好在该共享端点相交。两条非共线的线段最多只有一个交点，故只需拒绝**共线且重叠长度 > 0** 的情况（折回的尖刺）。
- **共线但不重叠的相邻边**（一条直边上的多余顶点）**不拒绝**：它不改变区域，只是冗余点。

面积用鞋带公式（shoelace）的绝对值，与顶点绕向无关；`RECT` 与 `POLYGON` 的顶点顺序不参与任何判定。

### 5.2 判定语义

- **点在多边形内**：射线法（even-odd）。边界上的点算**在内**。
- **框与区域相交**：目标框与区域的交叠面积 > 0 即为相交；**仅边线接触（交叠面积为 0）算不相交**，与 M07 既有实现一致。
- **框在区域内**（「在内」）：目标框的**中心点**在区域内。用中心点而不是整框包含，是因为工地目标常被遮挡或截断，整框包含会大量漏报。
- **跨线方向**：取目标中心点相对线段的**有向侧**符号，符号翻转即为一次跨越。同一次观测不产生跨越（需要两个时间点）。设线段两端为 `A = points[0]`、`B = points[1]`，`d = B − A`，中心点 `p` 的有向侧为

  ```
  side(p) = (p.x − A.x) · d.y − (p.y − A.y) · d.x
  ```

  `side(p_prev) < 0` 且 `side(p_curr) > 0`（**由负变正**）记为 `LEFT_TO_RIGHT`；由正变负记为 `RIGHT_TO_LEFT`。命中条件是本次跨越方向与该 ROI 的 `positiveDirection` **相同**，反向跨越不命中也不计数。

  三条配套约定，缺一两侧就会差一次跨越：

  1. `|side(p)| ≤ ε` 视为**落在线上**，既不算左侧也不算右侧：它不产生跨越，也**不覆盖**已记录的上一个非零符号 —— 判定始终拿「上一个非零符号」与「本次非零符号」比较，因此贴着线走再离开不会被算成跨越；
  2. 某主体的**首个非零符号**只记录、不判定（没有上一个符号可比）；
  3. 线段是**无限长直线**的有向侧判定，不检查交点是否落在 `A`、`B` 之间。这与 M07 一致，也是「闸门线画短一点仍然拦得住」的实际需要；要限制范围就把线段换成多边形区域。

  `LEFT_TO_RIGHT` / `RIGHT_TO_LEFT` 只是上式两个符号方向的**标签**：在归一化坐标（`x` 向右、`y` 向下）里，一条竖直线（`A` 在上、`B` 在下）的 `LEFT_TO_RIGHT` 恰好就是屏幕上从左向右；其他朝向请按上式判断，不要按名字猜。

**「在内」是 ROI 归属的唯一判据。** `ENTER`/`INSIDE`/`EXIT` 三种关系，以及 `COUNT`、`AREA_RATIO`、`ABSENCE` 按 ROI 归集本帧目标（§4.4）时的归属判定，一律使用上面的中心点规则，不得一处用中心点另一处用整框包含或相交。上面的「相交」定义只用在一个地方：`AREA_RATIO` 只有框、没有掩膜时的降级面积估算（§8.1），此时用框与区域的交叠面积，并在快照标记 `areaSource: "BOX_FALLBACK"`。

`ENTER` / `INSIDE` / `EXIT` 三种关系的时序定义沿用 M07：`ENTER` 为「上一帧不在内、本帧在内」，`EXIT` 为「上一帧在内、本帧不在内」，`INSIDE` 为「本帧在内」。首次观测到某主体时没有上一帧，`ENTER`/`EXIT` 均不成立。

**与 M07 的差异**：M07 的 `INSIDE` 判据是**整框包含**（`NormalizedRoi.contains`，四边全部在内），本规格改为**中心点**。这会让跨边界、被截断的目标从「不在内」变为「在内」，是对已验收行为的实质性修改，登记为 §17 第 11 行，必须有成对向量锁定。M07 的「仅边线接触算不相交」（`intersects` 用严格小于）与本规格一致，不属于变更。

### 5.3 数值约定

几何判定的容差固定为 `ε = 1e-9`（归一化坐标下）。它与 §15.1 向量比对的 `1e-6` 是两件事：前者决定「算不算在边界上」，后者决定「两个浮点数算不算相等」。

| 判定 | 约定 |
|---|---|
| 点在多边形边界上 | `|side| ≤ ε` 算**在内**（射线法遇到边界点直接返回「在内」，不依赖奇偶计数） |
| 零面积多边形 | `|shoelace| ≤ ε` |
| 零长线段 | 两点距离 `≤ ε` |
| 中心点落在跨线的线上 | `|side(p)| ≤ ε`，见 §5.2 |
| 框与区域相交 | 交叠面积 `> ε` 才算相交（仅边线接触的交叠面积为 0，算不相交） |

所有几何函数都是纯函数：只吃归一化坐标，不读时钟、不读配置、不做 I/O，同样的输入在两侧必须给出同样的输出。

## 6. 能力（Capability）与绑定检查

能力枚举：`BOX`、`TRACK`、`MASK`、`SCALAR`、`POLYGON_ROI`、`LINE_ROI`。

- 规则声明 `requires`；来源（模型 + 输入形态）声明 `provides`；ROI 形态贡献 `POLYGON_ROI` / `LINE_ROI`。
- 绑定时求差集。差集非空 → 拒绝，返回结构化原因：

```json
{ "accepted": false, "code": "CAPABILITY_UNSATISFIED",
  "ruleId": "no-hardhat-pit", "sourceId": "cam-07",
  "missing": ["TRACK"],
  "message": "规则需要跟踪能力，来源 cam-07 的模型未输出 trackId" }
```

- 拒绝必须可在管理页看到，并计入指标。**规则处于「已拒绝」状态时不参与求值，也不得显示为「已启用」。**
- 单帧主体（`frame:`）与时序算子的组合按同一机制拒绝，`code` 为 `SUBJECT_KIND_UNSUPPORTED`。

绑定检查**顺序固定**，返回**第一个**失败的原因，不合并多个原因 —— 否则两侧对同一条坏规则会给出不同的 `code`，向量无法比对：

1. 算子是否已实现（`OPERATOR_NOT_IMPLEMENTED`）；
2. 该算子是否支持这种主体类型（`SUBJECT_KIND_UNSUPPORTED`）；
3. `requires` 与 `provides` 的差集（`CAPABILITY_UNSATISFIED`，带 `missing`）；
4. 需要 ROI 的算子：`roiId` 是否给出且可解析（`ROI_REQUIRED`）、ROI 几何是否合法（`ROI_GEOMETRY_INVALID`，见 §5.1）、ROI 形态与算子是否匹配（`ROI_GEOMETRY_INVALID`：`LINE_CROSS` 必须绑定 `LINE`；`IN_REGION`、`COUNT`、`AREA_RATIO`、`ABSENCE` 的 `roi:` 归集必须绑定有内部的形态即 `RECT` 或 `POLYGON` —— 线段没有内部，「在内」无定义）；
5. 要求 `targetLabels` 非空的算子是否给出了标签（`TARGET_LABELS_REQUIRED`）。

例：`metric:` 主体上的 `METRIC_THRESHOLD` 规则返回 `OPERATOR_NOT_IMPLEMENTED`（第 1 步就失败），不返回 `SUBJECT_KIND_UNSUPPORTED`。

## 7. 规则（Rule）

```json
{
  "ruleId": "no-hardhat-pit",
  "ruleVersion": 3,
  "name": "基坑区域未戴安全帽",
  "enabled": true,
  "subjectKind": "track",
  "operator": "DWELL",
  "requires": ["BOX", "TRACK", "POLYGON_ROI"],
  "targetLabels": ["NO-Hardhat"],
  "roiId": "pit-north",
  "roiRelation": "INSIDE",
  "thresholds": {
    "minConfidence": 0.55,
    "minConsecutiveFrames": 3,
    "minDwellMs": 2000,
    "cooldownMs": 60000
  },
  "severityBands": [
    { "severity": "MINOR",    "atLeast": 2000 },
    { "severity": "MAJOR",    "atLeast": 8000 },
    { "severity": "CRITICAL", "atLeast": 20000 }
  ],
  "escalation": { "escalateAfterMs": 300000, "toSeverity": "CRITICAL" },
  "scope": { "sourceIds": ["cam-07"], "thresholdOverrides": {} }
}
```

- `targetLabels` 允许为空**当且仅当**算子为 `ABSENCE` 的补集语义或主体为 `metric:`；其余情况非空。这修正了 M07 中「`targetLabels` 必须非空」的无条件断言 —— 那条断言是模型耦合的根源。
- `ruleVersion` 每次配置变更自增，随事件快照落库，用于事后复现判定依据。
- `scope.thresholdOverrides` 提供**按来源覆盖**：同一条规则在不同摄像机上可以有不同阈值，不需要复制规则。
- 规则、阈值与 ROI 必须支持**运行时增删改且不重启进程**，变更写审计记录（谁、何时、改了哪个字段、旧值新值）。

## 8. 算子集

八个算子已实现，三个仅在 Schema 中预留。算子**只能组合模型已经输出的东西**，不能让模型看见它没输出的内容。唯一的例外是由跟踪派生的量（方向、速度、停留、越线、轨迹形状）。

| 算子 | 允许主体 | 需要能力 | 用到的阈值 | 分档量 |
|---|---|---|---|---|
| `PRESENCE` | `track` `frame` `source` | 无（分类可用） | 置信度、连续帧 | 置信度 |
| `IN_REGION` | `track` | `BOX` + ROI | 置信度、连续帧 | 置信度 |
| `LINE_CROSS` | `track` | `BOX` `TRACK` `LINE_ROI` | 置信度 | 跨越次数 |
| `DWELL` | `track` | `BOX` `TRACK` | 置信度、连续帧、持续时长 | 停留时长 |
| `COUNT` | `roi` `source` | `BOX` | 置信度、数量 | 数量 |
| `AREA_RATIO` | `roi` `frame` | `MASK`（或 `BOX` 降级） | 置信度、面积占比 | 面积占比 |
| `RATE` | `track` `roi` `source` | 无 | 置信度、频次窗口、频次 | 窗口内命中数 |
| `ABSENCE` | `roi` `source` | `BOX` | 置信度、持续时长 | 缺失时长 |

### 8.1 逐算子语义

**`PRESENCE`** —— 目标标签出现且 `confidence ≥ minConfidence`，连续 `minConsecutiveFrames` 帧成立即命中。分类型观测按整帧标签参与。

**`IN_REGION`** —— 在 `PRESENCE` 基础上追加 ROI 关系约束（`ENTER`/`INSIDE`/`EXIT`，见 §5.2）。

**`LINE_CROSS`** —— 主体中心点跨越线段，方向与 `positiveDirection` 一致时命中。**一次跨越只产生一次命中**；同一主体来回摆动时，每次方向翻转都是一次新的跨越，靠 `cooldownMs` 抑制抖动而不是靠去重。

**`DWELL`** —— 条件连续成立的累计时长达到 `minDwellMs`。时长由观测时间戳相减得到。中途条件中断则计时**清零**（不是暂停）；`离岗`、`徘徊`、`长时间占用通道` 都走这个算子。

**`COUNT`** —— 同一帧内，主体范围内满足标签与置信度约束的目标数 ≥ `minCount`。`超员`、`聚集` 用它。连续帧约束对 `COUNT` 同样生效，用于压制单帧误检导致的计数尖峰。

**`AREA_RATIO`** —— 目标面积 / 主体面积 ≥ `minAreaRatio`。烟雾面积扩散、积水面积、料堆占用都走这个算子。

- **分母**：`roi:` 主体取该区域面积；`frame:` 主体取整帧面积，恒为 `1`。
- **分子**按以下次序取第一个可用者，多个目标重叠的部分**只计一次**（面积求并，不是求和）：
  1. 掩膜携带 `polygon` → 掩膜多边形与主体区域的交叠面积之并集，`areaSource: "MASK"`；
  2. 掩膜只有 `areaRatio`（无法定位）且主体为 `frame:` → 命中掩膜 `areaRatio` 之和，上限 `1`，`areaSource: "MASK"`；
  3. 其余情况（掩膜无法定位到区域，或来源只给框）→ 命中框与主体区域的交叠面积之并集，`areaSource: "BOX_FALLBACK"`。
- 三条都不可用时，该规则应在绑定期就被 C-3 拒绝（`CAPABILITY_UNSATISFIED`，`missing: ["MASK"]`），不允许求值期静默返回 0。
- 第 3 条是本规格中**唯一**使用「交叠面积」的地方；ROI 归属一律用中心点（§5.2）。

**`RATE`** —— 滑动窗口 `rateWindowMs` 内的命中次数 ≥ `minRateHits`。这是行为告警的主力算子（`频繁玩手机`、`反复闯入`、`同一区域重复违规`）。

- 窗口内存**必须有界**：实现为按时间戳的环形缓冲或时间桶，容量上限 = `ceil(rateWindowMs / 最小观测间隔)` 并设硬上限；过期数据在每次求值时回收。这是唯一带内存增长风险的算子，两侧实现都必须有「窗口容量上限」测试。
- 窗口只在观测到来时推进（C-1），不靠定时器滑动。
- 窗口是**左闭右闭**区间 `[capturedAtUs - rateWindowMs, capturedAtUs]`：恰好落在窗口起点上的命中**算在窗口内**。边界差一个命中就会差一档，两侧必须一致。

**`ABSENCE`** —— 应当存在的标签在连续 `minDwellMs` 内**未出现**。`值守岗位无人`、`灭火器被移走` 走这个算子。

缺失计时的**起点是第一个未出现该标签的观测**的 `capturedAtUs`，与 `DWELL` 取「条件首次成立那一次观测」同一规则，而不是取上一次出现该标签的观测。`capturedAtUs - 起点 ≥ minDwellMs` 时命中，`measuredValue` 为该差值（毫秒）。标签重新出现时计时**清零**（与 `DWELL` 一致，不是暂停）。首个观测就没有该标签时，起点即首个观测 —— 引擎不假设「开始时目标一定在场」。

`ABSENCE` 是唯一「没有观测也要判定」的算子，因此它需要一个时间推进信号。约定：**每个信封即使载荷全空也必须送入引擎**（空帧仍带 `capturedAtUs`），由空信封推进 `ABSENCE` 计时。输入完全断流时不产生 `ABSENCE` 告警 —— 断流由流状态与 `NFR-02` 负责报警，不由告警引擎伪造为「目标缺失」。这条区分必须有金样向量覆盖。

### 8.2 仅预留、未实现

| 算子 | 用途 | 未实现原因 |
|---|---|---|
| `RELATION` | 目标间空间关系（`人` 与 `手机` 贴合 → 打电话） | 需要关系标注或姿态输入；当前走「把行为编码为模型类」的路线 |
| `METRIC_THRESHOLD` | 标量读数越限（扬尘、噪声、塔吊力矩） | 传感器接入未立项 |
| `COMPOSITE` | 多规则布尔组合 | 先确认单规则语义稳定再引入 |

Schema 中保留它们的枚举值与字段位置，实现遇到时按 `code: "OPERATOR_NOT_IMPLEMENTED"` 显式拒绝。**不允许**解析通过后静默不触发。

## 9. 阈值（七类）

七类阈值互相独立，含义不得混用：

| # | 阈值 | 字段 | 单位 | 作用 |
|---|---|---|---|---|
| 1 | 置信度 | `minConfidence` | 0–1 | 单条检测是否算「看见了」 |
| 2 | 连续帧 / 持续时长 | `minConsecutiveFrames` / `minDwellMs` | 帧 / 毫秒 | 抑制单帧闪烁；确认条件稳定 |
| 3 | 数量 | `minCount` | 个 | 超员、聚集 |
| 4 | 面积占比 | `minAreaRatio` | 0–1 | 烟雾扩散、积水、料堆占用 |
| 5 | 频次 | `rateWindowMs` + `minRateHits` | 毫秒 + 次 | 行为的反复发生 |
| 6 | 冷却窗口 | `cooldownMs` | 毫秒 | 抑制同级重复告警 |
| 7 | 分档 | `severityBands[].atLeast` | 随算子 | 决定严重级别 |

统一要求：

1. **运行时可改且不重启进程**，改完立即对后续观测生效，不追溯已产生的事件。
2. **可按来源覆盖**（`scope.thresholdOverrides`），因为不同摄像机的视角、光照与目标尺度差别很大。
3. **生效阈值随事件快照落库**。事后复盘必须能回答「这条告警当时用的是哪套阈值」，否则改过阈值的历史事件无法解释。
4. 借来的第三方权重需要**更严的默认值**：缺失类（`NO-Hardhat` 这种「没戴」）与单帧行为类（`smoking`）的误报率明显高于普通物体类，规则模板的默认 `minConfidence` 与 `minConsecutiveFrames` 必须高于物体类模板。具体数值由场景包给出，不写进引擎。

## 10. 严重级别（三档）

```text
MINOR（一般） < MAJOR（重要） < CRITICAL（严重）
```

只有三档。**不设「预警」档** —— 那是趋势语义，本引擎不做。

### 10.1 阈值分档（同一时刻的事实）

`severityBands` 是按 `atLeast` 升序的边界表，比较对象是算子的**分档量**（见 §8 表格最后一列）。取「成立的最高档」。

例：`COUNT` 规则 `atLeast: 3 → MINOR`、`6 → MAJOR`、`10 → CRITICAL`，某帧数到 7 个人 → `MAJOR`。

分档量必须与算子匹配；`severityBands` 缺省时全部事件为 `MINOR`。分档是**对同一时刻观测事实的分级**，不是对未来的预测。

分档量**低于最低档** `atLeast` 时取**最低档**的 `severity`，不产生「无级别事件」。理由：能走到分档这一步说明规则的确认阈值已经满足（这是一次命中），级别只是它有多严重；`severityBands` 与 `minCount` 之类的确认阈值是两套独立的数，把分档表的下界设得比确认阈值高是配置的自由，不该让引擎吞掉告警。

### 10.2 未处置提级（只提升通知，不改写事实）

`escalation.escalateAfterMs` 之后事件仍未被确认，则提级。提级**只影响通知**：

| 字段 | 含义 | 提级时是否变化 |
|---|---|---|
| `severity` | 判定时的事实级别 | **不变** |
| `notifySeverity` | 当前通知级别 | 变为 `toSeverity` |
| `escalatedAtUs` | 提级时刻 | 从空变为时间戳 |

这条区分是刻意的：把「当时观测到了什么」和「这条告警多久没人管」分开记录，事后统计才能区分「现场变严重了」和「值班没响应」。

提级计时的起点是 `confirmedAtUs`，不是 `startedAtUs`：候选期不投递，没有人可以「未处置」。`capturedAtUs - confirmedAtUs ≥ escalateAfterMs` 且 `disposition.status` 仍为 `OPEN` 时提级；已 `ACKNOWLEDGED` 的事件停止计时（§14.2）。一个事件**只提级一次**，`escalatedAtUs` 落值后不再变化，`notifySeverity` 也不再二次抬升。

提级同样受 C-1 约束 —— 由观测（含空信封）推进，不由定时器触发。

## 11. 事件生命周期

```text
                 条件成立
   （无事件） ─────────────► CANDIDATE
                              │ 满足连续帧/时长/数量等确认阈值
                              ▼
                          CONFIRMED ──── 条件消失 ───► ENDED
                              │                        │
                              │ 冷却窗口内再次命中      │ 冷却窗口内再次命中
                              ▼                        │
                          COOLDOWN ◄───────────────────┘
```

四个状态沿用 M07 定义：`CANDIDATE`、`CONFIRMED`、`ENDED`、`COOLDOWN`。

1. **`CANDIDATE`**：条件首次成立。候选期不投递、不落库为告警（可落为诊断记录）。
2. **`CONFIRMED`**：确认阈值满足，产生告警并进入投递。事件此刻生成快照（§13）。
3. **`ENDED`**：条件消失（或主体消失）。`endedAtUs` 记录结束时刻，**且只在条件消失或主体消失时落值** —— 被冷却抑制不改写 `endedAtUs`，那是投递被压掉，不是事实结束。
4. **`COOLDOWN`**：冷却窗口内的重复命中落入此状态，不重复投递，但**必须累计次数**（`suppressedCount`），否则运维看不出「这个点一直在报」。

「条件持续成立」与「条件消失后再次成立」是两件不同的事：前者只更新同一个事件实例，后者要重新走一次冷却闸门（§12）。

### 11.1 候选中断即丢弃

条件在候选期中断（本次观测不再成立）时，**候选整体丢弃**：连续帧计数、计时与候选事件对象一并清除。条件重新成立时开一个**新候选**，`startedAtUs` 取重新成立那一次观测的 `capturedAtUs`。

这与 §8.1 `DWELL`「中断清零」是同一条规则的两面，保证事件的 `startedAtUs` 与分档量的计时起点**永远一致**。M07 的实现只重置了连续帧计数、保留了候选事件对象，中断后再确认时 `startedAtUs` 仍是旧起点、与已清零的停留时长互相矛盾，属于对已验收行为的修改，登记为 §17 第 12 行。

### 11.2 主体消失

`track:` 主体的跟踪状态变为丢失时，其进行中的事件立即 `ENDED`。同一主体上可能同时存在多个级别的事件实例（§12 的四元组），主体消失时**全部**一并 `ENDED`。这里修正 M07 的一处行为：M07 的 `TemporalRuleEvaluator` 对非活跃跟踪**直接抛错**（`require(track.state == ACTIVE)`）。新规格要求把「跟踪丢失」作为**正常的生命周期输入**处理并结束事件，而不是抛错。这是需要金样向量锁定的行为变更点。

### 11.3 时间单调性

同一 `sourceId` 上，事件状态推进要求 `capturedAtUs` 单调不减，违反时抛错。M07 已有的三处单调性断言（候选评估、去重闸门、状态机）全部保留并写入本规格。

### 11.4 时间推进与空信封

引擎没有内部时钟，因此「时间流逝」必须由输入表达。约定：**采集侧即使本帧没有任何检测结果，也要送入一个载荷为空的信封**。空信封推进 `DWELL` 清零、`RATE` 窗口过期、`ABSENCE` 计时与未处置提级。

采集侧完全停止（断流、进程退出、会话关闭）时引擎不再推进，此时**不产生任何告警**。断流本身由流状态与 `NFR-02` 报警，不由告警引擎伪装成目标缺失。

## 12. 冷却语义

去重键包含**四个**维度：

```text
(ruleId, sourceId, subjectKey, severity)
```

比 M07 的 `(ruleId, sourceId, trackId)` 多了 `severity`，并把 `trackId` 换成 `subjectKey`。多出的级别维度是「冷却只抑制同级重复」的实现基础。

判定顺序（必须按此顺序，两侧一致）：

1. 若本次命中由**未处置提级**产生 → **放行**，不查冷却。
2. 若本次命中的 `severity` **高于**该 `(ruleId, sourceId, subjectKey)` 上一次已放行的级别 → **放行**，不查冷却。
3. 否则查 `(ruleId, sourceId, subjectKey, severity)` 的冷却窗口：窗口内 → 抑制，`suppressedCount + 1`；窗口外 → 放行并刷新窗口起点。

窗口边界与全文阈值取同一约定（**达到即算**，取 `≥`）：设窗口起点为该四元组**上一次放行**的 `capturedAtUs`，则 `capturedAtUs - 窗口起点 < cooldownMs` 为窗口内（抑制），`≥ cooldownMs` 为窗口外（放行，并把窗口起点刷成本次 `capturedAtUs`）。**被抑制的命中不刷新窗口起点** —— 否则条件反复命中会把冷却无限续期，一个持续违规点将永远只报一次。

「级别升高必然放行」是这套语义的要点：现场从 3 个人变成 12 个人，运维必须立刻收到，不能因为 5 分钟前报过一次 `MINOR` 就被压掉。级别**降低**不放行（走第 3 步），避免在边界值附近反复抖动刷屏。

两条同样重要的补充：

- **闸门只在「产生新事件实例」时查。** 条件持续成立期间，已 `CONFIRMED` 的实例只更新自己：不重新入闸，也不累加 `suppressedCount`。只有三种情况算新实例并走上面三步 —— 事件从无到有、条件消失后**再次成立**、本次命中的级别与当前实例不同。否则 `cooldownMs` 为 0 的规则会在每一帧都产生一个新事件，而 `suppressedCount` 会变成「条件持续了多少帧」这种毫无意义的计数。
- **事件状态按四元组分别维护。** 同一主体上不同级别的实例互不覆盖：`MINOR` 实例进了 `COOLDOWN`，`MAJOR` 实例照样可以是 `CONFIRMED`。被抑制的命中记在**与自己同级**的那个实例上，因此级别降低时的抑制计入较低级别的实例，不计入当前级别最高的实例。

M07 现有实现在 `InspectionEventStateMachine` 的确认分支里**无条件**调用冷却闸门。按本规格必须改成先走第 1、2 步的分支判定。这是本规格对冷却语义的唯一实质性修改（对已验收行为的实质性修改共四处，见 §17 第 4、5、11、12 行），必须有金样向量同时锁定新语义与「原有同级抑制行为不变」。

## 13. 事件快照与存证

事件确认时生成快照，快照是**不可变**的判定证据：

```json
{
  "eventId": "evt-01JC9…",
  "ruleId": "no-hardhat-pit", "ruleVersion": 3,
  "sourceId": "cam-07", "subjectKey": "track:12",
  "operator": "DWELL",
  "severity": "MAJOR", "notifySeverity": "MAJOR", "escalatedAtUs": null,
  "startedAtUs": 1772500800123456, "confirmedAtUs": 1772500802130000, "endedAtUs": null,
  "state": "CONFIRMED", "suppressedCount": 0,
  "measuredValue": 8200,
  "effectiveThresholds": { "minConfidence": 0.55, "minConsecutiveFrames": 3,
                           "minDwellMs": 2000, "cooldownMs": 60000 },
  "model": { "modelId": "site-ppe-v1" },
  "labels": ["NO-Hardhat"],
  "areaSource": null,
  "evidence": { "snapshotUri": "…", "startedAtUs": …, "endedAtUs": …, "clipUri": null },
  "disposition": { "status": "OPEN", "actor": null, "actedAtUs": null }
}
```

要求：

- `effectiveThresholds` 记录**实际生效值**（含来源覆盖后的结果），不是规则的默认值。
- `measuredValue` 记录触发时的分档量原始值，用于解释为什么落在这一档。
- `evidence`：MVP 只落**截图 + 时间区间**。`clipUri`（短视频）在 Schema 中预留但**不实现**，环形缓冲接口留在 `M08-T02` 的编码环节。存证深度、保留天数与磁盘上限未定，登记为 `FR-M11-EVIDENCE-DEPTH`。
- 快照与存证**不得**包含令牌、完整 RTSP 凭据或本机绝对路径。

**哪些字段定格、哪些字段可变**（两侧必须一致；向量按「终态」比对，见 §15.1 第 2 条）：

| 类别 | 字段 | 规则 |
|---|---|---|
| 判定证据 | `severity`、`measuredValue`、`effectiveThresholds`、`ruleVersion`、`labels`、`model`、`areaSource`、`startedAtUs`、`confirmedAtUs` | 确认那一刻取值，**此后不再改写** |
| 生命周期 | `state`、`endedAtUs`、`suppressedCount`、`notifySeverity`、`escalatedAtUs`、`disposition`、`evidence.endedAtUs` | 由后续观测与人工处置推进 |

所以后续观测的分档量更高时**不改写** `severity`，而是按 §12 第 2 步放行一个**新实例**，旧实例保留它当时的 `severity` 与 `measuredValue`。这是「一条告警是一个事实」的必然结果：把已经投递出去的 `MINOR` 就地改成 `MAJOR`，通知内容与库里的记录会对不上，事后无法复盘。

## 14. 投递与处置

### 14.1 投递通道

| 通道 | 形态 | 状态 |
|---|---|---|
| 管理页实时推送 | WebSocket 推送，页面弹出 | 实现 |
| App 内通知 | 走检测结果旁路之外的事件通道下发 | 实现 |
| 邮件 / 短信 / 企业 IM | 适配器接口 + 本地假实现，凭据注入点预留 | 接口实现，真实通道冻结（`FR-M11-ALERT-CHANNELS`） |
| 面向上游系统的 Webhook 回调 | —— | **明确不做** |

投递失败有重试上限，且**不得阻塞事件生成**。App 为封闭应用，不使用系统级推送。

### 14.2 处置闭环

三个动作，都写入 `disposition` 并记录操作人与时间戳：

1. **确认**（`ACKNOWLEDGED`）—— 停止未处置提级计时。
2. **误报标记**（`FALSE_POSITIVE`）—— 除了关闭事件，还把截图 + 生效阈值 + 原始检测结果导出为**可再训练的数据集条目**。
3. **关闭**（`CLOSED`）—— 已处理完毕。

误报回流是这套系统对抗「借用第三方权重、数据分布不匹配」的主要手段（见 §9 第 4 条），所以导出格式必须能直接进入标注与训练流程，且不含令牌与本机绝对路径。

**权限**：确认与误报标记的权限必须与只读查看权限分离。当前服务端只有 `ADMIN_TOKEN` / `MOBILE_TOKEN` 两级，需要在 `M11-T09` 中细分，具体角色划分待定。

## 15. 一致性金样向量

向量目录：`docs/alert-engine-conformance/`。一个文件一个向量，服务端测试套件加载执行，App 侧**原样复制**到测试资源后逐条执行（`M15-T05`）。

```json
{
  "vectorId": "cooldown-severity-escalates",
  "description": "同级重复被冷却抑制，级别升高立即放行，级别降低仍被抑制",
  "specVersion": "v1",
  "rois": [ { "roiId": "yard", "shape": "RECT", "rect": {"x":0,"y":0,"w":1,"h":1} } ],
  "rules": [ { "ruleId": "crowd", "subjectKind": "roi", "operator": "COUNT", "…": "…" } ],
  "observations": [ { "sourceId": "cam-01", "frameSeq": 1, "capturedAtUs": 1000000, "…": "…" } ],
  "expectedEvents": [
    { "ruleId": "crowd", "sourceId": "cam-01", "subjectKey": "roi:yard", "operator": "COUNT",
      "severity": "MINOR", "measuredValue": 3, "startedAtUs": 1000000, "confirmedAtUs": 1000000,
      "state": "COOLDOWN", "suppressedCount": 2 },
    { "ruleId": "crowd", "sourceId": "cam-01", "subjectKey": "roi:yard", "operator": "COUNT",
      "severity": "MAJOR", "measuredValue": 7, "startedAtUs": 4000000, "confirmedAtUs": 4000000,
      "state": "COOLDOWN", "suppressedCount": 1 }
  ],
  "expectedRejections": []
}
```

上面是 `docs/alert-engine-conformance/cooldown-severity-escalates.json` 的**真实内容**（只省略了规则与观测的完整字段）。规格里的示例与向量目录里的向量不允许各说一套：示例改了，向量跟着改。

约定：

1. 向量是**纯数据**，不含任何语言相关结构；两侧解析成各自的领域对象。
2. `expectedEvents` 按 `confirmedAtUs` 升序，逐字段比对。未列出的字段不比对（允许两侧存储差异）。
3. `expectedRejections` 比对 §6 的拒绝 `code` 与 `missing` 集合。
4. 向量必须覆盖的场景：
   - 八个已实现算子各至少一条；
   - 三档分档的边界值（`atLeast` 上下各一帧）；
   - 未处置提级：`severity` 不变、`notifySeverity` 改变、`escalatedAtUs` 落值；
   - 同级冷却抑制（`suppressedCount` 累加）与级别提升放行；
   - 能力不满足的显式拒绝（`CAPABILITY_UNSATISFIED`、`SUBJECT_KIND_UNSUPPORTED`、`OPERATOR_NOT_IMPLEMENTED`）；
   - 空信封推进 `ABSENCE` 计时**且**断流不产生 `ABSENCE`（一对对照向量）；
   - `RATE` 窗口容量上限；
   - 跟踪丢失结束事件（§11.2 的行为变更点）；
   - 候选中断后重新成立取新 `startedAtUs`（§11.1 的行为变更点）；
   - 多边形边界点、仅边线接触、中心点判定三种几何边界；
   - **一组从 M07 既有行为反推的基线向量**，用于证明未静默改变已验收语义。
5. 某一侧失败时按 C-2 处理：改本文与 Schema，再同步两侧。**不得**单方面改实现或改向量。

### 15.1 执行器比对规则（两侧必须一致）

向量只有在两侧**执行器语义一致**时才是裁判，因此比对规则本身也是冻结项：

1. **一条 `expectedEvents` 对应一个事件实例。** 同一 `(ruleId, sourceId, subjectKey)` 上被冷却放行多次就是多个实例，各写一条；被抑制的重复命中**不**单独成条，只体现为所属实例的 `suppressedCount`。
2. **取终态。** 逐条比对的是整个观测序列**执行完毕后**该实例的字段值，不比对中间态。因此 `suppressedCount` 是最终累计值，`state` 是最后一次推进后的状态。
3. **未列出的字段不比对**（允许两侧存储差异）；列出的字段必须逐字段相等，包括显式的 `null`（例如 `escalatedAtUs: null` 表示「必须没有提级」，与不写该字段不同）。
4. **数值容差。** 时间戳、计数、帧号必须**精确相等**；浮点量（置信度、面积占比）容差 `1e-6`。
5. **排序。** `expectedEvents` 按 `confirmedAtUs` 升序；相同则按 `subjectKey` 字典序，再相同则按 `severity` 升序（`MINOR` < `MAJOR` < `CRITICAL`）。执行器按同一规则排序后位置对齐比对。
6. **只到候选的事件不出现在 `expectedEvents` 中**（候选不投递、不落库为告警）。
7. **`expectedEvents: []` 是强断言**，表示「必须没有任何事件」，与「字段不比对」是两件事。断流不产生 `ABSENCE` 这类向量依赖这一条。
8. `expectedRejections` 只比对 `code`、`missing` 与（给出时）`ruleId`：`missing` 按集合比较、忽略顺序，`message` 文案不比对 —— 两侧允许本地化。同一向量里出现多条拒绝时，靠 `ruleId` 对齐，不靠顺序。
9. 未列出 `expectedRejections` 等价于空数组：**所有规则都必须绑定成功**。

## 16. 预留未实现清单

以下在 Schema 中有字段与枚举值，实现遇到时必须显式拒绝或留空，**不允许**静默通过：

| 项 | 位置 | 拒绝码 / 取值 | 解冻条件 |
|---|---|---|---|
| `RELATION` 算子 | `operator` 枚举 | `OPERATOR_NOT_IMPLEMENTED` | 关系标注或姿态输入立项 |
| `METRIC_THRESHOLD` 算子 | `operator` 枚举 | `OPERATOR_NOT_IMPLEMENTED` | 传感器接入立项 |
| `COMPOSITE` 算子 | `operator` 枚举 | `OPERATOR_NOT_IMPLEMENTED` | 单规则语义稳定后 |
| `metric:` 主体 | `subjectKind` 枚举 | `SUBJECT_KIND_UNSUPPORTED` | 同上（随 `METRIC_THRESHOLD`） |
| `scalars` 载荷 | 观测信封 | 允许携带，不参与判定 | 同上 |
| 短视频存证 `clipUri` | 事件快照 | 恒为 `null` | `FR-M11-EVIDENCE-DEPTH` 解除 |
| 邮件 / 短信 / 企业 IM | 投递通道 | 接口 + 本地假实现 | `FR-M11-ALERT-CHANNELS` 解除 |
| 上游 Webhook 回调 | —— | 不在 Schema 中 | **不做**，非冻结项 |

## 17. 与 M07 既有实现的差异

App 侧 M07 已验收的事件引擎是本规格的实现起点。下表列出必须改动的点，每一条都要有向量或单元测试锁定（`M15-T01`~`M15-T05`）：

| # | M07 现状 | 本规格要求 | 性质 |
|---|---|---|---|
| 1 | 主体标识为 `trackId` | 改为 `subjectKey`（五类），存储与索引维度同步 | 扩展 + Room 迁移 |
| 2 | `targetLabels` 无条件要求非空 | `ABSENCE` 补集语义与 `metric:` 主体可为空 | 放宽（原为模型耦合来源） |
| 3 | 去重键 `(ruleId, sourceId, trackId)` | 加 `severity` 维度 | 扩展 |
| 4 | 确认分支无条件调用冷却闸门 | 先判提级与级别升高，再查冷却 | **行为变更** |
| 5 | 非活跃跟踪直接抛错 | 跟踪丢失是正常生命周期输入，结束事件 | **行为变更** |
| 6 | 算子逻辑内联在 `matchesRule` 条件里 | 按规则声明分派 | 重构（行为不变） |
| 7 | ROI 仅矩形 | 增多边形与线段 | 扩展 |
| 8 | 无严重级别 | 三档 + 分档量 + 未处置提级 | 新增 |
| 9 | 入口为检测列表 | 统一观测信封，四类载荷 | 扩展 |
| 10 | 无能力声明 | `requires` / `provides` 差集拒绝 | 新增 |
| 11 | ROI `INSIDE` 判据是整框包含（`contains`） | 改为中心点在内，且 `COUNT`/`AREA_RATIO`/`ABSENCE` 的 ROI 归属用同一判据 | **行为变更** |
| 12 | 候选期条件中断只重置连续帧计数，候选事件对象保留（`startedAtUs` 仍是旧起点） | 候选整体丢弃，重新成立后 `startedAtUs` 取新起点 | **行为变更** |

第 4、5、11、12 条是对**已验收行为**的修改，必须成对提供「新语义生效」与「原有行为不变」两组向量，否则不得合入：第 4 条锁定「级别升高放行」与「同级仍被抑制」，第 5 条锁定「跟踪丢失结束事件」与「活跃跟踪照旧求值」，第 11 条锁定「跨边界目标由不在内变为在内」与「整框在内、整框在外两种情形结论不变」，第 12 条锁定「中断后重新成立取新 `startedAtUs`」与「未中断时 `startedAtUs` 不变」。其余各条以「原有测试改造后全部通过」为准，**不允许删除测试来回避迁移**。

## 18. 变更流程

本规格状态为**冻结**。改动顺序固定：

```text
① 改 alert-engine-spec.md（本文）
② 改 alert-engine.schema.json
③ 增 / 改 alert-engine-conformance/ 向量
④ 服务端实现跟随（M11）
⑤ App 侧实现跟随（M15）
```

跳过 ①②③ 直接改实现的变更一律视为规格违背。`specVersion` 在语义发生不兼容变化时递增（`v1` → `v2`），届时两侧必须同时升级，不支持混跑两个版本。

