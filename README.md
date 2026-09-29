# DriverTour

基于用户实时位置检索周边 POI 的多 Agent 系统。Week 1 目标：打通数据管道 **GPX 轨迹 → 轨迹重放 → Mapbox 周边 POI → JSON**。设计见 [week1_design_doc.md](week1_design_doc.md)。

## 快速开始

需要 Python 3.9+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入 MAPBOX_ACCESS_TOKEN（https://account.mapbox.com/access-tokens/ 获取，默认 public token 即可）

uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 可以查看并调试所有接口。

启动时会自动加载 `data/sample.gpx`，轨迹 id 为 `sample`（从香槟市中心开车到厄巴纳，全程约 3.8 km，38 个点，每 10 秒一个点）。

## 接口

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/tracks` | 上传 GPX（multipart，字段名 `file`），返回解析后的 `Track`（含 `id`） |
| GET | `/tracks/{track_id}/replay?speed=10` | 返回全部点，以及每个点按倍速换算后的"应到达时间" `offset_s` |
| GET | `/pois?lat=..&lng=..&radius=500&category=cafe` | 查询周边 POI，按距离升序排列 |
| GET | `/tracks/{track_id}/pois?step=5` | Demo：每 N 个点查一次 POI；传 `min_distance_m=400` 时改为按移动距离触发 |

```bash
curl -F file=@data/sample.gpx localhost:8000/tracks
curl "localhost:8000/tracks/sample/replay?speed=10"
curl "localhost:8000/pois?lat=40.1106&lng=-88.2073&radius=500&category=cafe"
curl "localhost:8000/tracks/sample/pois?min_distance_m=500&category=cafe"
```

`category` 是 Mapbox 的 canonical category id（如 `cafe`、`restaurant`、`museum`、`park`），不传时使用 `DEFAULT_POI_CATEGORY`。完整列表见 [Search Box API: List categories](https://docs.mapbox.com/api/search/search-box/#list-categories)。

## 命令行 Demo（实时重放）

```bash
python -m scripts.demo_replay --speed 20 --min-distance 400 --category cafe
```

按真实时间差除以 `speed` 逐点 sleep，每移动 `--min-distance` 米查一次周边 POI 并打印。未配置 Token 时只重放位置。

## 测试

```bash
pytest
```

Mapbox 调用全部走 mock（`respx` / 依赖注入），测试不需要 Token，也不消耗额度。

## 项目结构

```
app/
├── main.py              # FastAPI 入口，lifespan 中创建共享的 httpx.AsyncClient 并加载示例轨迹
├── config.py            # 从 .env 读取配置
├── models/schemas.py    # Pydantic 数据模型
├── services/
│   ├── gpx_parser.py    # GPX → 按时间排序的 GPSPoint 列表
│   ├── geo.py           # Haversine 距离、累计距离、半径 → bbox
│   ├── replayer.py      # 轨迹重放（sync / async generator）+ 查询点选择策略
│   ├── poi_client.py    # Mapbox Search Box API 封装（lng,lat 转换只在此处发生）
│   └── track_store.py   # 内存轨迹存储
└── api/routes.py        # REST 路由
scripts/demo_replay.py   # 命令行实时重放 Demo
data/sample.gpx          # 示例轨迹
tests/
```

## 实现说明（相对 design doc 的补充）

- **Python 版本**：本机为 3.9，所以用 `Optional[X]` 代替 `X | None`（3.10+ 语法），字段语义与文档一致
- **`Track.id`**：文档中的 `Track` 没有 id，但 `/tracks/{track_id}/...` 需要，因此补上了
- **半径过滤**：Search Box category search 没有 radius 参数，因此先用 `bbox` 粗筛，再用 Haversine 按 `radius` 精确过滤并排序
- **额度保护**：`/tracks/{id}/pois` 单次最多调用 Mapbox `MAX_POI_QUERIES_PER_TRACK` 次（默认 20），超出时截断并返回 `truncated: true`；并发上限为 3
- **存储**：轨迹存在内存中，服务重启后丢失（本周 Non-Goal）
