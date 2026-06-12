# 2026世界杯预测 + 体彩投注优化

基于 Elo评分 + 泊松分布 + XGBoost 的2026美加墨世界杯比赛预测系统，对比中国体育彩票（竞彩足球）赔率，自动发现价值投注并推荐最优过关组合。

## 快速启动

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
rm worldcup.db                          # 清除旧数据（如有）
python data/seed/seed_database.py       # 初始化数据库
python run.py                           # 启动服务器
```

浏览器打开 **http://localhost:8000**

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python FastAPI + SQLAlchemy(aiosqlite) |
| ML | scikit-learn GradientBoosting + scipy 泊松分布 |
| 前端 | Jinja2 模板 + Chart.js + HTMX |
| 爬虫 | httpx + APScheduler |
| 优化 | 凯利准则 + 枚举组合 |

## 项目结构

```
世界杯赌神/
├── app/
│   ├── main.py              # FastAPI入口 + 调度器 + 启动时后台爬虫
│   ├── config.py            # 全局配置（Elo参数、凯利系数、爬虫间隔等）
│   ├── models/
│   │   ├── database.py      # SQLAlchemy引擎（async + sync双引擎）
│   │   ├── team.py          # Team表 + TeamSquad表
│   │   ├── match.py         # Match表 + Group表
│   │   ├── odds.py          # Odds表（竞彩赔率）
│   │   ├── prediction.py    # Prediction + BetRecommendation + MatchResult
│   │   └── external_factors.py  # 场外因素表
│   ├── routes/
│   │   ├── dashboard.py     # GET / 仪表盘  POST /api/predict-all
│   │   ├── matches.py       # GET /match/{id} 比赛详情
│   │   ├── predictions.py   # GET /api/predictions/match/{id} 预测API
│   │   ├── betting.py       # GET /betting/ 投注页  POST /betting/api/optimize
│   │   └── admin.py         # GET/POST /admin 管理后台
│   ├── services/
│   │   ├── elo.py           # Elo评分（胜平负概率、xG、Elo更新）
│   │   ├── predictor.py     # 预测引擎（集成Elo+泊松+ML+因子修正）
│   │   ├── odds_parser.py   # 赔率加载（优先真实竞彩→模型生成）
│   │   ├── bet_optimizer.py # 投注优化（EV计算、凯利准则、过关组合）
│   │   ├── feature_engine.py    # 33维特征工程
│   │   ├── external_factors.py  # 场外因素评估
│   │   ├── squad_service.py     # 球员身价+伤病服务
│   │   └── scraper.py       # 懂球帝爬虫（比分+伤病）
│   ├── templates/           # Jinja2 HTML模板（5个）
│   └── static/              # CSS/JS静态文件（预留）
├── data/
│   ├── seed/
│   │   ├── teams.json       # 48队种子数据
│   │   ├── groups.json      # 12组分组
│   │   ├── odds_real.json   # 真实竞彩赔率（24场）
│   │   └── seed_database.py # 种子脚本
│   └── model.pkl            # ML模型文件（训练后生成）
├── requirements.txt
├── run.py
└── README.md
```

## 预测模型

### 三层集成
```
最终预测 = Elo模型 × 40% + 泊松xG × 35% + GradientBoosting × 25%
```

### 四大因子修正
1. **球员因子** — 球队身价比、板凳深度、伤病影响 → 修正 xG
2. **主场优势** — 东道主分级（L1/L2/L3）、球迷支持、旅行疲劳
3. **场外因素** — 天气、海拔、裁判、战意、媒体压力
4. **市场信号** — 赔率变动趋势、资金流向

### 特征维度（33维）
- 基础实力 6维 + 球员因子 7维 + 主场优势 8维 + 场外因素 8维 + 交互特征 4维

## 数据源

| 数据 | 来源 | 验证 |
|------|------|------|
| 48队分组名单 | 懂球帝/FIFA | ✅ |
| 104场赛程(北京时间) | 懂球帝/zhibo8 | ✅ |
| 24场竞彩赔率 | sporttery.cn 竞彩官网 | ✅ |
| 48队身价 | Transfermarkt via 懂球帝 | ✅ |
| 球员伤病 | - | ⏳ 待爬取 |

## API 端点

```
GET  /                    仪表盘
GET  /match/{id}          比赛详情
GET  /betting/            投注推荐页
GET  /admin               管理后台

POST /api/predict-all     生成全部赛前预测
POST /api/refresh         触发懂球帝爬虫刷新
POST /api/predictions/generate/{id}  单场预测
GET  /api/predictions/match/{id}     预测JSON
POST /betting/api/optimize           运行投注优化器
GET  /betting/api/recommendations    投注推荐JSON
GET  /api/health          健康检查
```

## 配置

`app/config.py` 中可调整：
- `ELO_K_FACTOR` — Elo灵敏度（默认60）
- `KELLY_FRACTION` — 凯利保守系数（默认0.25）
- `MAX_STAKE_PCT` — 单注最大比例（默认5%）
- `ODDS_UPDATE_INTERVAL` — 赔率刷新间隔（300秒）
- `SCORE_UPDATE_INTERVAL` — 比分刷新间隔（120秒）

## 注意事项

- 数据库使用 Beijing Time (UTC+8) 存储所有时间
- 模板使用 Jinja2 Environment 直接渲染（非 Starlette Jinja2Templates，避免版本兼容问题）
- Windows GBK终端需注意 emoji 编码
- 淘汰赛球队为占位符，需根据小组赛结果更新
