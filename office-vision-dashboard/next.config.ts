import type { NextConfig } from "next";
import { withScheme } from "./lib/monitor-endpoints";

// Server API 走 :8000；Agent 监控 API 走 :8100（仅开发模式存在）。
// 经 Next 代理转发可避免浏览器 CORS，MJPEG 流同样可透传。
// 多 Agent 模式：配置 OVA_AGENT_MONITOR_URLS（device_id=url 逗号分隔）后，
// 由 proxy.ts 运行时拦截 /agent-monitor/* 转发至各台 Agent（优先级高于 rewrite）；
// 未配置时下方 /agent-monitor rewrite 作为单设备回退。

const serverUrl = withScheme(process.env.OVA_SERVER_URL, "http://localhost:8000");
const agentMonitorUrl = withScheme(process.env.OVA_AGENT_MONITOR_URL, "http://localhost:8100");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${serverUrl}/api/:path*`,
      },
      {
        source: "/agent-monitor/:path*",
        destination: `${agentMonitorUrl}/monitor/:path*`,
      },
    ];
  },
};

export default nextConfig;
