// 多 Agent 监控端点映射（proxy.ts 运行时读取）。
// 环境变量 OVA_AGENT_MONITOR_URLS：device_id=url 逗号分隔，如
//   OVA_AGENT_MONITOR_URLS=macbook=http://192.168.1.10:8100,office-pc=http://192.168.1.11:8100
// 未配置时实时监控回退单设备模式（next.config.ts 的 /agent-monitor rewrite → OVA_AGENT_MONITOR_URL）。

// PaaS（如 Railway 模板）可能注入裸域名（无协议），统一补 https://。
export function withScheme(url: string | undefined, fallback: string): string {
  if (!url) return fallback;
  return url.startsWith("http") ? url : `https://${url}`;
}

export function getMonitorEndpoints(): Record<string, string> {
  const raw = process.env.OVA_AGENT_MONITOR_URLS ?? "";
  const result: Record<string, string> = {};
  for (const item of raw.split(",")) {
    const idx = item.indexOf("=");
    if (idx <= 0) continue;
    const device = item.slice(0, idx).trim();
    const url = item.slice(idx + 1).trim();
    if (device && url) result[device] = withScheme(url, url);
  }
  return result;
}
