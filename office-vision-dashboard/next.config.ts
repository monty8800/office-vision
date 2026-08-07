import type { NextConfig } from "next";

// Server API 走 :8000；Agent Debug API 走 :8100（仅开发模式存在）。
// 经 Next 代理转发可避免浏览器 CORS，MJPEG 流同样可透传。

// PaaS（如 Railway 模板）可能注入裸域名（无协议），统一补 https://。
function withScheme(url: string | undefined, fallback: string): string {
  if (!url) return fallback;
  return url.startsWith("http") ? url : `https://${url}`;
}

const serverUrl = withScheme(process.env.OVA_SERVER_URL, "http://localhost:8000");
const agentDebugUrl = withScheme(process.env.OVA_AGENT_DEBUG_URL, "http://localhost:8100");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${serverUrl}/api/:path*`,
      },
      {
        source: "/agent-debug/:path*",
        destination: `${agentDebugUrl}/debug/:path*`,
      },
    ];
  },
};

export default nextConfig;
