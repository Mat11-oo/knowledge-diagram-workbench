# 知识图解工作台

把一份材料变成可核对的图解和讲解视频。

粘贴正文 → 自动提取知识点 → 逐条对照原文核对 → 编排成 3–6 张卡片 → 生成插图 → 编辑动态分镜 → 配音配字幕 → 导出 1080×1920 的 PNG / 编号 ZIP，或 30–60 秒的竖屏 MP4。

本机单用户运行，不需要账号、不需要服务器。

---

## 核心设计原则

**引用必须可追溯。** 每个知识点都带逐字原文片段，由后端按字符偏移精确切片校验，不信任模型自报的位置。引用对上原文不等于事实正确，仍需人工确认。

**补充内容必须标识。** 原文提炼和补充说明分开标注，不混为一谈。

**文字不交给生图模型。** 插图只画概念图，中文由程序用固定字体排版，缺字和溢出直接报错，绝不裁字。

**不静默覆盖。** 卡片、插图、图片版本、分镜、视频都是不可变版本，改动产生新版本，旧版保留可下载。

**费用由代码硬拦截。** 单次授权一次性使用，结果未知时阻止后续所有付费调用，不自动重试。

---

## 技术架构

```
┌─────────────────────────────────────────────┐
│  Next.js 16 + React 19 + TypeScript         │
│  /knowledge 单页工作台（四步分步切换）        │
└──────────────────┬──────────────────────────┘
                   │ /api/knowledge/*（next.config rewrites 转发）
┌──────────────────▼──────────────────────────┐
│  FastAPI + Pydantic                         │
│  knowledge_app.py ← 唯一入口                 │
└──────────────────┬──────────────────────────┘
                   │
   ┌───────────────┼───────────────┬──────────────┐
   ▼               ▼               ▼              ▼
 DeepSeek      阿里云百炼       阿里云百炼     本机 FFmpeg
 文本提取        万相生图        qwen3-tts      视频编码
                              (逐句配音)
                   │
                   ▼
        单份 JSON manifest（原子写入 + 文件锁 + 版本冲突校验）
        data/knowledge/<work_id>.json
```

### 关键模块

| 路径 | 职责 |
| --- | --- |
| `backend/knowledge_app.py` | 唯一后端入口，挂载 `/api/knowledge` 全部路由 |
| `backend/scenarios/knowledge_diagram/` | 全部业务逻辑 |
| ├ `service.py` | 提取、核对、合并、移除、预算 |
| ├ `cards.py` | 卡片编排、生图任务、PNG/ZIP 导出 |
| ├ `scenes.py` | 动态分镜编辑与确认 |
| ├ `videos.py` | 配音计划、TTS 任务、视频合成 |
| ├ `video_render.py` | 逐帧动画绘制 + FFmpeg 组装 |
| ├ `image_provider.py` | 万相异步生图适配 |
| ├ `tts_provider.py` | qwen3-tts 适配 |
| ├ `render_cards.py` | 中文排版 + 字形覆盖/溢出检查 |
| └ `repository.py` | 原子写 + 文件锁 + 修订号冲突保护 |
| `frontend/app/knowledge/` | 工作台页面与样式 |
| `frontend/components/knowledge/` | 5 个业务组件 |

---

## 视频是怎么生成的

**不使用视频生成模型。** 画面由程序逐帧绘制（Pillow），再用 FFmpeg 编码。唯一调用模型的是配音。

```
分镜（对象/动作/说明/旁白）→ 旁白按标点切短句（≤24 字）
→ 每句调 qwen3-tts 合成 → 解码出真实时长
→ 按 25fps 逐帧绘制 → 每句一个片段 → 拼接 + 合轨 → MP4
```

画面里真的在动：

| 动画 | 做法 |
| --- | --- |
| 节点出现 | 86% 缩放到位，颜色从背景渐变，各节点错开 0.08 秒 |
| 箭头生长 | 从节点边缘缓动长出，走到 86% 才显示箭头 |
| 当前节点 | 持续呼吸：尺寸 ±3px，描边 5→9px |
| 说明面板 | 从下方滑入，底部有旁白进度条随时间填充 |
| 字幕 | 淡入 |

三种版式：**流程**（节点横排 + 推进箭头）、**关系**（交错节点 + 连线）、**对照**（高低交替）。

时间轴由同一份分镜驱动：字幕 cue、音频、画面高亮共用一套起止时间，每句边界误差不超过 40ms（按帧对齐）。

**定位**：这是程序化二维图解动画——几何图形的运动，不是 AI 生成的实景画面，也没有人物出镜。好处是完全可控、不额外花钱、音画字幕严格同步。

---

## 快速开始

需要 Python 3.12、Node.js 20+。

```bash
# ── 后端 ──
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # 然后填写 Key
.venv/bin/python -m uvicorn knowledge_app:app --port 8137   # 默认只监听本机

# ── 前端（另开终端）──
cd frontend
npm ci
npm run dev:knowledge
```

然后在浏览器打开本机端口 **3137** 的 `/knowledge` 页面。

> 服务和数据都只在本机，不对外监听，也没有线上地址。

### 环境变量

见 `backend/.env.example`。三个开关默认全是 `0`，不填 Key 也能启动，只是不能调用云端模型。

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `MODEL_API_KEY` | DeepSeek 文本提取 | 空 |
| `DASHSCOPE_API_KEY` | 生图 + 配音（北京地域）| 空 |
| `KNOWLEDGE_ALLOW_PAID` / `KNOWLEDGE_PRICING_CONFIRMED` | 文本调用总开关 | `0` |
| `KNOWLEDGE_ALLOW_IMAGES` / `KNOWLEDGE_IMAGE_PRICING_CONFIRMED` | 生图开关 | `0` |
| `KNOWLEDGE_ALLOW_TTS` / `KNOWLEDGE_TTS_PRICING_CONFIRMED` | 配音开关 | `0` |

两个开关要同时为 `1` 才会真正发起付费调用。

---

## 模型与费用

| 环节 | 模型 | 单价 | 单套约 |
| --- | --- | --- | --- |
| 文本提取 | DeepSeek Flash | 输入 2 元/百万 token，输出 8 元/百万 | 0.0026 元 |
| 生图 | 万相 2.0 Turbo（北京）| 0.04 元/张 | 0.12 元（3 张）|
| 配音 | qwen3-tts-flash / Cherry | 0.8 元/万字符 | 0.056 元（235 字）|
| 视频 | 本机 FFmpeg | 0 | 0 |
| **合计** | | | **约 0.19 元 / 套** |

改文案不重新生图，改一两句旁白只重配那几句，所以实际迭代成本远低于 0.19 元。

预算保护：每个作品全生命周期累计 ≤ 1 元；生图前额外保留 0.22 元给后续配音；配音单批 ≤ 0.06 元；结果未知时阻止后续所有付费调用。

---

## 数据与恢复

每个作品一份 `data/knowledge/<work_id>.json`，`schema_version=1`。

- **原子写入**：临时文件 → fsync → `os.replace` → fsync 目录，崩溃不留半个文件
- **并发**：进程内锁 + `fcntl.flock`，所有写操作带 `expected_revision`，不匹配返回 409
- **中断恢复**：进程重启时 `pending`/`running` 任务转为 `interrupted`；已发送但结果未知的预算条目转为 `uncertain`，占用不放并阻止新付费调用
- **只查询不重发**：有远程 task_id 时可重新 GET 原任务，绝不重新 POST

版本失效规则：改原文 → 知识点全部转为待核对；改卡片文字 → 插图保留；改插图提示词 → 当前关联清除但旧文件保留；改分镜 → 该分镜转为待确认。

---

## 测试

```bash
cd backend && .venv/bin/python -m pytest -q        # 82 项 + 27 subtests
cd frontend && npm test -- --run                    # 15 项
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```

真实模型冒烟脚本在 `backend/tests/` 之外另有入口，需要显式 `--allow-paid` 且带一次性授权标识，同一授权目录不可重复执行。

---

## 目录结构

```
backend/
├── knowledge_app.py              # 唯一入口
├── scenarios/knowledge_diagram/   # 知识图解全部业务逻辑
├── assets/fonts/                 # Noto Sans CJK（SIL OFL）
├── tests/                        # 知识图解相关测试
├── core/ models/ pipelines/ api/ # 短剧 Agent 底座（保留，含独立许可）
└── .env.example

frontend/
├── app/knowledge/                # 工作台页面 + workbench.css
├── components/knowledge/         # MaterialEditor / ClaimReview / CardStudio
│                                 # AnimationStudio / VideoStudio
├── lib/knowledge.ts              # API 客户端与类型
└── next.config.ts                # /api/knowledge 转发

THIRD_PARTY_LICENSES/
├── 知识图解工作台-Agent-LICENSE       # 底座 MIT 许可
└── NotoSansCJK-OFL.txt          # 字体许可
```

---

## 许可

本项目采用 MIT 许可，见 `LICENSE`。

仓库内包含 知识图解工作台 的代码，其原始 MIT 许可保留在 `THIRD_PARTY_LICENSES/知识图解工作台-Agent-LICENSE`。
中文字体 Noto Sans CJK SC 采用 SIL Open Font License 1.1。
