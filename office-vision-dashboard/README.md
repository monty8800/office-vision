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

## 计划页面（阶段7迁移自原型 frontend/）

- 首页概览：今日抽烟根数 / 累计时长 / 平均时长 / 在岗状态
- 近 7 天趋势柱状图
- 行为时间轴
- 配置页面：Presence 参数（离开缓冲、自动休眠、恢复等待）
- 系统状态：Agent 在线 / 摄像头 / 插件列表
