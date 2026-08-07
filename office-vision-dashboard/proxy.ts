import { NextResponse, type NextRequest } from "next/server";
import { getMonitorEndpoints } from "@/lib/monitor-endpoints";

// 多 Agent 监控代理（运行时按 env 决策，优先级高于 rewrite 与文件系统路由）：
// - 未配置 OVA_AGENT_MONITOR_URLS → 放行，走 next.config.ts 的 /agent-monitor rewrite 单设备回退
// - /agent-monitor/devices → 返回映射中的设备列表（供监控页渲染切换器）
// - /agent-monitor/<device>/<path> → 转发至映射地址 /monitor/<path>
//   （外部 rewrite 由 Next 代理层透传响应体，MJPEG 流不缓冲）
// - 映射外的 device 返回 404（防 SSRF）

export default function proxy(req: NextRequest) {
  const endpoints = getMonitorEndpoints();
  if (Object.keys(endpoints).length === 0) return NextResponse.next();

  const rest = req.nextUrl.pathname.slice("/agent-monitor/".length);
  if (rest === "devices") {
    return NextResponse.json({ devices: Object.keys(endpoints) });
  }

  const [device, ...segments] = rest.split("/");
  const base = endpoints[device];
  if (!base || segments.length === 0) {
    return NextResponse.json({ error: `未知设备：${device}` }, { status: 404 });
  }
  const search = req.nextUrl.searchParams.toString();
  return NextResponse.rewrite(
    new URL(`${base}/monitor/${segments.join("/")}${search ? `?${search}` : ""}`)
  );
}

export const config = {
  matcher: ["/agent-monitor/:path*"],
};
