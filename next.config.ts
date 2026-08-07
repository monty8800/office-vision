import type { NextConfig } from "next";

// Server API 走 :8000；Agent Debug API 走 :8100（仅开发模式存在）。
// 经 Next 代理转发可避免浏览器 CORS，MJPEG 流同样可透传。
const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.OVA_SERVER_URL ?? "http://localhost:8000"}/api/:path*`,
      },
      {
        source: "/agent-debug/:path*",
        destination: `${process.env.OVA_AGENT_DEBUG_URL ?? "http://localhost:8100"}/debug/:path*`,
      },
    ];
  },
};

export default nextConfig;
