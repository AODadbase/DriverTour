# Week 1 Design Doc：位置数据管道（GPS 轨迹 → 周边 POI）

> 作者：<你的名字>
> 日期：2026-09-28
> 分支：`week1`
> 状态：Draft（待课上评审）

---

## 1. 背景（Background）

本项目的最终目标是构建一个基于 LangGraph 的多 Agent 系统（Agent Team）。系统根据用户的实时位置，检索周边 POI，研究这些 POI 并生成内容。

所有 Agent 都依赖同一个基础能力：**知道用户在哪里，以及周围有什么**。第一周的任务就是把这条数据管道打通，为后续的 RAG、Grounding 和 Agent 编排打好基础。

## 2. 目标与非目标（Goals / Non-Goals）

### Goals
- 用 FastAPI 搭建可运行的后端服务骨架
- 用 Pydantic 定义统一的数据模型，作为后续 Agent 间传递数据的格式
- 解析 GPX 文件，得到按时间排序的 GPS 点序列
- 实现两点间的球面距离计算
- 实现轨迹重放，模拟用户移动
- 调用 Mapbox API，根据当前坐标检索周边 POI
- 产出端到端 Demo：轨迹重放 → 按位置查 POI → 返回 JSON

### Non-Goals（本周不做）
- LangGraph / 多 Agent 编排
- LLM 调用、RAG、Memory、Caching
- 前端地图可视化
- 数据库持久化
- 用户鉴权

## 3. 系统概览（System Overview）

```
 ┌───────────┐     ┌──────────────┐     ┌────────────────┐     ┌────────────┐
 │  GPX 文件  │ ──▶ │  GPX Parser  │ ──▶ │ Track Replayer │ ──▶ │ POI Service│ ──▶ Mapbox API
 └───────────┘     └──────────────┘     └────────────────┘     └────────────┘
                                                │                      │
                                                ▼                      ▼
                                        ┌─────────────────────────────────┐
                                        │     FastAPI (REST 接口层)         │
                                        └─────────────────────────────────┘
```

### 模块划分

| 模块 | 职责 |
|---|---|
| `models/` | Pydantic 数据模型 |
| `services/gpx_parser.py` | 读取并解析 GPX 文件 |
| `services/geo.py` | 地理计算，包括距离和累计距离 |
| `services/replayer.py` | 按时间顺序重放轨迹 |
| `services/poi_client.py` | 封装 Mapbox API 调用 |
| `api/routes.py` | FastAPI 路由 |
| `config.py` | 从 `.env` 读取配置，如 API Token |

### 目录结构（初稿）

```
project/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   └── schemas.py
│   ├── services/
│   │   ├── gpx_parser.py
│   │   ├── geo.py
│   │   ├── replayer.py
│   │   └── poi_client.py
│   └── api/
│       └── routes.py
├── data/
│   └── sample.gpx
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

## 4. 数据模型（Data Models）

```python
from datetime import datetime
from pydantic import BaseModel, Field

class GPSPoint(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    elevation: float | None = None
    timestamp: datetime | None = None

class Track(BaseModel):
    name: str | None = None
    points: list[GPSPoint]
    total_distance_m: float

class POI(BaseModel):
    id: str
    name: str
    category: str | None = None
    lat: float
    lng: float
    address: str | None = None
    distance_m: float | None = None   # 距当前位置的距离

class POISearchResponse(BaseModel):
    center: GPSPoint
    radius_m: int
    results: list[POI]
```

**设计考虑**：`POI` 是自己定义的模型，不直接透传 Mapbox 的原始返回。这样以后更换数据源（例如改用 Google Places 或 OSM）时，下游的 Agent 不需要改动。

## 5. API 设计（REST Endpoints）

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/tracks` | 上传 GPX 文件，返回解析后的 `Track` |
| GET | `/tracks/{track_id}/replay?speed=10` | 重放轨迹，逐点返回位置 |
| GET | `/pois?lat=..&lng=..&radius=500&category=cafe` | 查询周边 POI |
| GET | `/tracks/{track_id}/pois?step=5` | Demo 用：每隔 N 个点查一次 POI |

### 示例返回：`GET /pois`

```json
{
  "center": {"lat": 40.1106, "lng": -88.2073},
  "radius_m": 500,
  "results": [
    {
      "id": "poi.123",
      "name": "Example Cafe",
      "category": "cafe",
      "lat": 40.1110,
      "lng": -88.2080,
      "address": "...",
      "distance_m": 72.4
    }
  ]
}
```

## 6. 关键实现细节

### 6.1 GPX 解析
- 使用 `gpxpy` 库，遍历 `tracks → segments → points`
- 按 `timestamp` 排序，丢弃缺少坐标的点

### 6.2 球面距离计算（Haversine）

```
a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
d = 2R · atan2(√a, √(1−a))      R = 6371000 m
```

### 6.3 轨迹重放
- 根据相邻点的时间差 `Δt`，按 `Δt / speed` 进行 sleep，模拟真实移动
- 用 Python generator 或 `async` generator 实现，逐点 `yield`
- 接口层可以先一次性返回全部点加上"应到达时间"，后续再升级为 SSE 或 WebSocket 流式推送

### 6.4 POI 检索
- 使用 Mapbox **Search Box API** 的 category search。注意：Geocoding API v6 不再返回 POI，实施前请查阅官方文档确认
- 传入 `proximity=lng,lat`（注意 Mapbox 坐标顺序是**经度在前**）
- 用 `httpx.AsyncClient` 发起异步请求
- Token 通过 `.env` 注入，`.env` 加入 `.gitignore`

## 7. 备选方案与取舍（Alternatives & Trade-offs）

| 决策点 | 方案 A（选用） | 方案 B | 取舍理由 |
|---|---|---|---|
| 距离计算 | 手写 Haversine | `geopy.distance.geodesic` | Haversine 简单、零依赖、可解释，适合面试讲解；误差约 0.5%，在 POI 场景可接受。geodesic 更精确，但依赖更重 |
| GPX 解析 | `gpxpy` | 手写 XML 解析 | 库更稳，能处理多种 GPX 变体；手写有助于理解格式，但容易出错 |
| POI 数据源 | Mapbox | Google Places / OSM Overpass | Mapbox 免费额度充足、文档清晰；Google 数据最全但需绑卡；Overpass 完全免费但查询语法复杂、速度不稳定 |
| HTTP 客户端 | `httpx`（async） | `requests` | FastAPI 是异步框架，用同步请求会阻塞事件循环 |
| 重放实时推送 | 本周先返回列表 | SSE / WebSocket | 先保证功能正确，流式推送留到后续迭代 |

## 8. 风险与待确认问题（Risks / Open Questions）

- **API 限额**：Mapbox 免费额度的具体数值需确认，Demo 中要控制调用频率（例如每 N 个点或每移动 X 米才查一次）
- **GPS 噪声**：原始轨迹可能存在漂移点，是否需要过滤（例如去掉速度异常的点）？
- **查询频率策略**：按"点数间隔"触发，还是按"移动距离阈值"触发？后者更合理，也能自然引出后续的缓存设计
- **坐标顺序**：Mapbox 使用 `lng,lat`，内部模型统一用 `lat, lng`，需要在 client 层统一转换

## 9. 测试计划（Testing）

- `geo.py`：用已知两点（如两座城市）验证距离，误差在 1% 以内
- `gpx_parser.py`：用 `data/sample.gpx` 验证点数与时间顺序
- `poi_client.py`：mock Mapbox 返回，验证字段映射
- 端到端：手动运行 Demo 接口，检查返回的 JSON

## 10. 本周交付物（Deliverables）

- [ ] `week1` 分支，包含上述模块
- [ ] 可运行的 FastAPI 服务，`/docs` 中可以看到所有接口
- [ ] 一个示例 GPX 文件
- [ ] Working Demo：重放轨迹并输出沿途 POI
- [ ] README：说明如何启动项目、配置 Token
