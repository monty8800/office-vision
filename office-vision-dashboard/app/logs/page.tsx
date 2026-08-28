"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import {
  serverApi,
  type LogChunkDetail,
  type LogChunkMeta,
} from "@/lib/server-api";
import { Badge, Card, EmptyState } from "@/components/ui";
import { DeviceFilter, useDeviceFilter } from "@/components/device-filter";

const PAGE_SIZE = 50;

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

// useSearchParams 需要 Suspense 边界（仅多设备时筛选器可见）
export default function LogsPage() {
  return (
    <Suspense fallback={null}>
      <LogsContent />
    </Suspense>
  );
}

function LogsContent() {
  const { device } = useDeviceFilter();
  const [chunks, setChunks] = useState<LogChunkMeta[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LogChunkDetail | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const result = await serverApi.logs(PAGE_SIZE, 0, device);
        if (active) {
          setChunks(result.chunks);
          setTotal(result.total);
          setError(null);
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [device]);

  const openChunk = useCallback(async (chunkId: string) => {
    setSelectedId(chunkId);
    setDetail(null);
    try {
      setDetail(await serverApi.logDetail(chunkId));
    } catch {
      setDetail(null);
    }
  }, []);

  const download = () => {
    if (!detail) return;
    const blob = new Blob([detail.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${detail.device_id}-${detail.chunk_id.slice(0, 8)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6">
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold">客户端日志</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Agent 上报的日志片段（共 {total} 条，每 10 秒刷新）；错误触发的片段标红
          </p>
        </div>
        <DeviceFilter />
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(320px,2fr)_3fr]">
        <Card>
          {error ? (
            <p className="text-sm text-red-400">加载失败：{error}</p>
          ) : chunks.length === 0 ? (
            <EmptyState text="暂无日志（等待 Agent 上报）" />
          ) : (
            <ul className="max-h-[70vh] divide-y divide-zinc-800/80 overflow-y-auto">
              {chunks.map((chunk) => (
                <li key={chunk.chunk_id}>
                  <button
                    type="button"
                    onClick={() => openChunk(chunk.chunk_id)}
                    className={`flex w-full items-center gap-3 px-1 py-2.5 text-left transition-colors hover:bg-zinc-800/50 ${
                      selectedId === chunk.chunk_id ? "bg-zinc-800/60" : ""
                    }`}
                  >
                    <span className="w-36 shrink-0 text-xs tabular-nums text-zinc-500">
                      {formatDateTime(chunk.logged_at)}
                    </span>
                    <Badge tone={chunk.trigger === "error" ? "red" : "zinc"}>
                      {chunk.trigger === "error" ? "错误触发" : "定时"}
                    </Badge>
                    <span className="truncate text-xs text-zinc-500">
                      {chunk.device_id}
                    </span>
                    <span className="ml-auto shrink-0 text-xs tabular-nums text-zinc-600">
                      {formatBytes(chunk.size)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          {!detail ? (
            <EmptyState
              text={selectedId ? "加载中…" : "点击左侧日志片段查看内容"}
            />
          ) : (
            <div className="flex h-full flex-col">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs text-zinc-500">
                  {detail.device_id} · {formatDateTime(detail.logged_at)} ·{" "}
                  {formatBytes(detail.size)}
                </p>
                <button
                  type="button"
                  onClick={download}
                  className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 transition-colors hover:bg-zinc-800"
                >
                  下载
                </button>
              </div>
              <pre className="max-h-[64vh] flex-1 overflow-auto rounded-lg bg-zinc-950/80 p-3 font-mono text-xs leading-relaxed text-zinc-300">
                {detail.content}
              </pre>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
