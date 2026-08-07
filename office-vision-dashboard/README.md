# Office Vision Dashboard

Office Vision AI 的 Next.js 16 仪表盘：今日统计、趋势分析、行为时间轴、配置页面、系统状态、插件管理。

## 边界

- 纯展示层，只调用 Server 的 REST API，不直连 Agent、不直连数据库
- 技术栈：Next.js 16（App Router）+ TypeScript + Tailwind + shadcn/ui + TanStack Query + Recharts（后续按需安装）

## 开发

```bash
npm install
npm run dev        # http://localhost:3000
```

## 多 Agent 支持

- 每台 Agent 需在 `agent.yaml` 配置唯一的 `agent.device_id`；Server 统计接口均支持 `?device_id=` 过滤
- 概览 / 时间轴 / 行为分析页：多设备时自动出现设备筛选器（状态存于 `?device=` URL 参数）
- 实时监控页：配置 `OVA_AGENT_MONITOR_URLS`（`device_id=url` 逗号分隔）后出现设备切换器，
  由 `proxy.ts` 运行时将 `/agent-monitor/<device>/*` 转发至对应 Agent；未配置时回退单设备模式
  （`OVA_AGENT_MONITOR_URL`，默认 http://localhost:8100）

```bash
# 多 Agent 示例
OVA_AGENT_MONITOR_URLS="macbook=http://192.168.1.10:8100,office-pc=http://192.168.1.11:8100" npm run dev
```

## 计划页面（阶段7迁移自原型 frontend/）

- 首页概览：今日抽烟根数 / 累计时长 / 平均时长 / 在岗状态
- 近 7 天趋势柱状图
- 行为时间轴
- 配置页面：Presence 参数（离开缓冲、自动休眠、恢复等待）
- 系统状态：Agent 在线 / 摄像头 / 插件列表
