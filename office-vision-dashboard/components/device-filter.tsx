"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { serverApi, type AgentInfo } from "@/lib/server-api";

// 设备筛选状态存于 URL ?device= 参数：跨页面保留、可分享（null = 全部设备）。
// 注意：useSearchParams 要求调用方包在 <Suspense> 内。
export function useDeviceFilter(): {
  device: string | null;
  setDevice: (device: string | null) => void;
} {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const device = params.get("device");

  const setDevice = (next: string | null) => {
    const sp = new URLSearchParams(params.toString());
    if (next) sp.set("device", next);
    else sp.delete("device");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  return { device, setDevice };
}

// 设备筛选下拉：仅多设备（>1）时渲染，单设备场景 UI 零变化。
export function DeviceFilter() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const { device, setDevice } = useDeviceFilter();

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await serverApi.agents();
        if (active) setAgents(next.agents);
      } catch {
        // Server 不可达时隐藏筛选器（页面已有各自错误提示）
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (agents.length <= 1) return null;

  return (
    <select
      value={device ?? ""}
      onChange={(e) => setDevice(e.target.value || null)}
      className="rounded-md border border-zinc-800 bg-zinc-800/60 px-3 py-1.5 text-sm text-zinc-300"
      aria-label="设备筛选"
    >
      <option value="">全部设备</option>
      {agents.map((a) => (
        <option key={a.device_id} value={a.device_id}>
          {a.device_id}
          {a.online ? " · 在线" : " · 离线"}
        </option>
      ))}
    </select>
  );
}
