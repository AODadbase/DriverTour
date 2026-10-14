# Week 2 Design Doc：Agent Team 与有据可查的讲解（Grounded Narration）

> 作者：Wang Zhi Neng
> 日期：2026-10-13
> 分支：`week-2-agent-team`
> 状态：Draft

---

## 1. 背景（Background）

Week 1 打通了 **GPX → 轨迹重放 → Mapbox 周边 POI** 的数据管道，但输出只是一份 POI 列表。Week 2 要把它变成司机能"听"的讲解词：车开到某个地标前方时，系统挑出这个地标，查资料，写一段在到达前能讲完的解说。

这是系统第一次调用 LLM，因此也是第一次可能"编造事实"。本周的核心约束是：**每一句讲解都必须能追溯到一个真实来源；没有来源，就不讲。**

## 2. 目标与非目标（Goals / Non-Goals）

### Goals
- 用 LangGraph 编排 4 个单一职责节点：Scout → Researcher → Writer → Checker
- 计算车辆航向（heading），只讲解位于车辆前方的地标
- 从 Wikipedia 检索事实并保留来源 URL；找不到可靠来源时跳过
- LLM 只基于检索到的事实写讲解，输出经 Pydantic 校验的结构化 JSON
- 讲解长度适配"到达前剩余时间"
- 每个决策写一行 JSONL 日志，事后可以解释每个地标为何被讲解或跳过

### Non-Goals（本周不做）
- TTS 语音合成与真实播放
- 多语言讲解（本周只输出英文，语速按英文 2.5 词/秒估算）
- 缓存、长期记忆、向量检索
- 前端界面；FastAPI 接口不改动

## 3. 系统概览（System Overview）

```
GPX ─▶ Replayer ─▶ HeadingTracker ─▶ 候选池（每 400 m 刷新 Mapbox）
                     (heading, speed)          │
                                               ▼
                               select_landmark()  ←── 每个 ping 调用，纯计算、不联网
                                               │ 有新目标且当前没在讲？
                                               ▼
              ┌──────────────── LangGraph ────────────────────────────┐
              │ scout ─▶ researcher ─▶ writer ─▶ checker ─▶ END       │
              │   │          │           │         │  ▲              │
              │   ▼          ▼           ▼         └──┘ 不通过时重写一次│
              │  END     END(no_source) END                          │
              └───────────────────────────────────────────────────────┘
                                               │
                                               ▼
                                打印讲解词 + logs/run.jsonl
```

| 节点 | 文件 | 是否调用 LLM | 是否联网 | 职责 |
|---|---|---|---|---|
| Scout | `app/agents/scout.py` | 否 | 否 | 过滤（前方 / 未讲过 / 距离合适），按距离选出 0 或 1 个地标 |
| Researcher | `app/agents/researcher.py` | 否 | Wikipedia | 按坐标匹配条目，把摘要切成 3–5 条事实，附带 URL |
| Writer | `app/agents/writer.py` | 是 | DeepSeek | 只用事实写讲解；每句标注引用的事实编号；按时间窗口截断 |
| Checker | `app/agents/checker.py` | 是 | DeepSeek | 逐句核验是否被引用的事实支持；不通过则带着反馈退回 Writer 一次 |

### 目录结构（新增部分）

```
app/
├── geo/
│   └── bearing.py          # bearing / angle_diff / is_ahead / HeadingTracker
├── agents/
│   ├── state.py            # Pydantic 共享状态
│   ├── scout.py
│   ├── researcher.py       # 含 WikipediaClient
│   ├── writer.py
│   ├── checker.py
│   ├── llm.py              # DeepSeek 结构化输出封装（可注入假实现用于测试）
│   ├── decision_log.py     # JSONL 决策日志
│   └── graph.py            # StateGraph 组装与条件路由
scripts/run_tour.py         # 端到端运行：GPX → 讲解词
tests/test_bearing.py, test_scout.py, test_researcher.py, test_writer.py, test_graph.py
logs/run.jsonl              # 一次完整运行的日志
```

## 4. 共享状态（State Schema）

所有模型定义在 `app/agents/state.py`。**代码必须与本节逐字段一致。**

```python
Landmark = POI   # 复用 Week 1 的 app.models.schemas.POI；landmark_id 即 POI.id（Mapbox id）

class Research(BaseModel):
    landmark_id: str
    title: str                  # Wikipedia 条目标题
    facts: List[str]            # 3–5 条，原文句子，不经过 LLM
    source_url: str             # Wikipedia 条目 URL，非空

class Citation(BaseModel):
    sentence: str               # 讲解中的一句
    fact_indices: List[int]     # 该句依据的事实编号（从 1 开始），至少 1 个

class Script(BaseModel):
    landmark_id: str
    text: str                   # 各 citation.sentence 拼接而成
    word_count: int             # 代码计算
    est_seconds: float          # word_count / 2.5，代码计算
    source_url: str             # 从 Research 复制，不由 LLM 生成
    citations: List[Citation]
    window_s: float             # 生成时距离到达的秒数；保证 est_seconds <= window_s

class TourState(BaseModel):
    position: GPSPoint
    heading: Optional[float]            # 度，0=北，顺时针；未知时为 None
    speed_mps: float
    candidates: List[Landmark]
    selected: Optional[Landmark] = None
    research: Optional[Research] = None
    script: Optional[Script] = None
    narrated_ids: List[str] = []        # 已讲解过的地标
    skipped_ids: List[str] = []         # 已尝试但放弃的地标（no_source / failed_check 等），不再重试
    feedback: Optional[str] = None      # Checker 给 Writer 的反馈（指出不被支持的句子）
    write_attempts: int = 0             # Writer 已执行次数，最多 2 次
```

与作业要求相比的增量：`Citation` / `Script.citations` / `Script.window_s`（溯源与时间窗口校验）、`skipped_ids`（避免对没有来源的地标反复查询）、`feedback` / `write_attempts`（Checker 自我纠错环）。

**约定：图运行结束后，`script` 非空，当且仅当该讲解通过了全部检查、可以播放。**

## 5. 图结构与路由（Graph）

```python
g = StateGraph(TourState)
g.add_edge(START, "scout")
g.add_conditional_edges("scout",      lambda s: "researcher" if s.selected else END)
g.add_conditional_edges("researcher", lambda s: "writer" if s.research else END)
g.add_conditional_edges("writer",     route_after_writer)      # 有 script→checker；输出无效且 write_attempts<2→writer；否则→END
g.add_conditional_edges("checker",    route_after_check)   # 通过→END；不通过且 write_attempts<2→writer；否则→END
```

节点都是 async 函数，只返回自己更新的字段。外部依赖（Wikipedia 客户端、LLM、日志）在 `build_graph(...)` 时以闭包注入，方便测试替换。

**图的调用时机**：`run_tour.py` 每个 ping 都调用 `select_landmark()`（纯函数，与 Scout 节点同一份逻辑）。只有当它选出一个地标、而且上一段讲解已经播完（按模拟时间计算）时，才调用 `graph.ainvoke()`。这样 LLM 调用次数不会超过"新地标数 × 2～4"。

## 6. 关键实现细节

### 6.1 方位角与"是否在前方"（`app/geo/bearing.py`）

- `bearing(a, b)`：初始方位角 θ = atan2(sin Δλ·cos φ2, cos φ1·sin φ2 − sin φ1·cos φ2·cos Δλ)，归一到 [0, 360)。
- `angle_diff(a, b) = (b − a + 180) % 360 − 180`，结果在 [−180, 180)。例如 350° → 10° 的差是 +20°，而不是 −340°。
- `is_ahead(heading, bearing_to_target, cone_deg=60)`：`|angle_diff| <= cone_deg`。**`cone_deg` 指单侧半角**，即前方左右各 60°，总宽 120°。
- `HeadingTracker`：用相邻两点计算速度 = 距离 / Δt、航向 = bearing(prev, cur)。**速度 < 2 m/s 时保留上一个有效航向**（避免停车时 GPS 抖动导致航向乱跳）；速度仍然更新。没有时间戳时速度视为未知（0），航向照常计算。

### 6.2 Scout：选择规则

对每个候选地标（按当前位置重新计算距离），按顺序判断，命中第一条即停：

| 顺序 | 条件 | reason |
|---|---|---|
| 1 | id ∈ narrated_ids | `already_narrated` |
| 2 | id ∈ skipped_ids | `already_skipped` |
| 3 | 距离 > 600 m | `out_of_range` |
| 4 | heading 未知，或 `not is_ahead(heading, bearing)`，或距离 < 20 m（视为正在经过） | `behind` |
| 5 | 时间窗口 < 8 s（来不及讲完一句话） | `too_close` |
| — | 其余地标中距离最近的一个 | `selected` |

时间窗口 `window_s = distance_m / speed_mps`，上限为 45 s（约 110 词）；车速 < 2 m/s 时直接取上限。

### 6.3 Researcher：Wikipedia 匹配（宁缺毋滥）

1. Geosearch：`list=geosearch&gscoord=LAT|LON&gsradius=500&gslimit=10`，以地标坐标为中心。
2. 对每个结果计算 **名称相似度**：先把两边名称归一化（转小写、去掉括号内容和标点），再取 `difflib.SequenceMatcher` 比值与"词集合包含"两者中的较大值。
3. 接受条件：相似度 ≥ 0.6 **且** 条目坐标距地标 ≤ 300 m；多个结果都满足时，取相似度最高的。
4. 拉取 REST summary：`type` 必须为 `standard`（排除消歧义页），`extract` 非空。
5. facts = `extract` 按句切分后的前 5 句（至少 2 句，否则视为来源不足）；source_url = `content_urls.desktop.page`。

任何一步失败 → `research = None`，地标进入 `skipped_ids`，日志 reason 记为 `no_source` 并附具体原因（`no_geosearch_hit` / `no_name_match` / `not_standard_page` / `too_few_facts` / `http_error`）。所有请求都带描述性的 `User-Agent`。

### 6.4 Writer：只用事实，按时间窗口限长

- 输入给 LLM 的只有：地标名、编号后的事实列表、词数上限 `max_words = floor(window_s × 2.5)`、可能有的 Checker 反馈。
- System prompt 规定：只能使用给出的事实，不得引入任何外部知识（包括年份、数字、形容词性评价）；每句话必须列出所依据的事实编号；第二人称、口语化。
- 输出 `ScriptDraft { citations: List[Citation] }`，用 DeepSeek function calling 加 Pydantic 校验，`temperature = 0`。
- 代码侧校验：句子非空；`fact_indices` 非空且都在 1..len(facts) 范围内。校验失败或 LLM 调用出错计为一次失败的写作尝试（reason `bad_output`）：`write_attempts < 2` 时把错误写进 `feedback` 重写一次，否则放弃。
- **超长处理**：如果总词数 > `max_words`，从末尾逐句删除，直到不超长（每句都独立有引用，所以删句不会破坏溯源）。如果连第一句都超长，就放弃，reason 记为 `too_long`。
- `word_count`、`est_seconds`、`source_url`、`window_s` 全部由代码填写。

### 6.5 Checker：逐句核验（自我纠错环）

- 第二次 LLM 调用：输入事实列表和每句（附其引用编号），要求对每句返回 `supported: bool` 与理由。
- 全部通过 → 地标加入 `narrated_ids`，日志记 `passed_check`。
- 有不支持的句子且 `write_attempts < 2` → 把不支持的句子写进 `feedback`，退回 Writer。
- 第二次仍不通过 → `script = None`，地标进入 `skipped_ids`，日志记 `failed_check`。

### 6.6 决策日志（`logs/run.jsonl`）

每行一个 JSON 对象：

```json
{"ts": "2026-10-13T10:00:00.123Z", "t_sim": 152.0, "node": "writer", "landmark_id": "dXJu...", "landmark": "Krannert Center",
 "decision": "write", "reason": "written", "latency_ms": 812.4,
 "word_count": 41, "est_seconds": 16.4, "window_s": 23.5}
```

- `reason` 取值：`selected`、`nothing_selected`、`behind`、`already_narrated`、`already_skipped`、`out_of_range`、`too_close`、`researched`、`no_source`、`written`、`too_long`、`bad_output`、`passed_check`、`failed_check`、`retry`。
- Scout 的拒绝类日志**按 (地标, reason) 去重**：只有当某地标的拒绝原因发生变化时才写一行，避免每个 ping 都刷屏，但仍然能看出每个地标在什么时候、因为什么被跳过。
- 不记录任何 API key。

## 7. 备选方案与取舍（Alternatives & Trade-offs）

| 方案 | 结论 | 理由 |
|---|---|---|
| **单个大 prompt**：把位置、heading、全部 POI 交给 LLM，让它自己挑选并写讲解 | 否决 | 无法定位错误出在哪一步；LLM 会用自身记忆补充事实，无法溯源；每个 ping 都要调用，成本高 |
| **让 LLM 从 Wikipedia 摘要中"提取事实"** | 否决 | 多了一次可能产生幻觉的环节。按句切分原文得到的事实是零幻觉的，代价是事实不够精炼——对讲解来说可以接受 |
| **按名称搜索 Wikipedia**（`list=search&srsearch=NAME`） | 否决 | 同名问题严重（"Starbucks" 会匹配到公司条目）。改为按坐标 geosearch，再做名称和距离校验 |
| **让 LLM 直接输出 word_count / est_seconds / source_url** | 否决 | 模型数不准词，也可能编造 URL；这些都是可以确定性计算的字段 |
| **超长时让 LLM 重写** | 否决 | 多一次调用，而且不一定能写短；按句截断是确定性的，并且保留每句的引用 |
| **Scout 使用 LLM 判断"值不值得讲"** | 暂不做 | 本周用距离排序就够；后续可以加入兴趣打分 |

## 8. 风险与待确认问题（Risks / Open Questions）

- **Mapbox 分类与 Wikipedia 覆盖率**：Week 1 默认分类是 `restaurant`，餐馆基本没有 Wikipedia 条目。本周改为同时查询多个"地标类"分类（博物馆、公园、历史遗迹、宗教场所、大学、剧院等，以 Mapbox category list 为准），以保证示例路线上至少有 3 个可讲的地标。
- **路线较短**：示例 GPX 约 3.8 km、约 6 分钟车程。每段讲解最长 45 s，并且不重叠播放，理论上能讲 5～8 个地标。
- **按句切分**：遇到 "St." "U.S." 这类缩写可能切错，用简单的缩写白名单缓解。
- **Checker 自身也可能误判**：Checker 只是一道防线；PR 中仍然人工核对 3 个脚本的每一句。
- **Python 3.9**：使用 langgraph 0.6.x 与 langchain-deepseek 0.1.x（两者都支持 3.9）。

## 9. 测试计划（Testing）

- `tests/test_bearing.py`：正北/正东方位角；heading 350° 与目标 10° 判为前方；正后方判为非前方；0/360 边界；锥角边缘；HeadingTracker 低速时保留航向。
- `tests/test_scout.py`：每条拒绝规则各一个用例；选择最近的地标；时间窗口计算。
- `tests/test_researcher.py`：用 respx mock Wikipedia：正常匹配；名称不匹配；距离过远；消歧义页；事实不足。
- `tests/test_writer.py`：用假 LLM 测试：引用编号越界被拒；超长时截断；`source_url` 来自 Research。
- `tests/test_graph.py`：用假 LLM 和假 Wikipedia 跑全图：无地标 → END；无来源 → END 并记 `no_source`；Checker 第一次失败、第二次通过；连续失败 → `failed_check`。
- 所有测试不联网、不需要 API key。

## 10. 本周交付物（Deliverables）

- `app/agents/`：`state.py`、`scout.py`、`researcher.py`、`writer.py`、`checker.py`、`llm.py`、`decision_log.py`、`graph.py`
- `app/geo/bearing.py` 与 `tests/test_bearing.py`
- `scripts/run_tour.py`：在真实 GPX 上产出讲解词
- `logs/run.jsonl`：一次完整运行的日志
- 本文档；从 `week-2-agent-team` 提交的 PR，附日志节选、示例讲解词，以及 3 个脚本的"句子 → 事实"对照
