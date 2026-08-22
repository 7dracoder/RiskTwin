"use client";

import { useEffect, useRef, useState } from "react";
import type { PointCloud, ReconstructionStatus } from "@/lib/types";

export function PointCloudViewer({
  cloud,
  status,
  onBuild,
}: {
  cloud: PointCloud | null;
  status: ReconstructionStatus | null;
  onBuild: () => Promise<void>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [yaw, setYaw] = useState(-0.45);
  const [pitch, setPitch] = useState(-0.2);
  const [building, setBuilding] = useState(false);
  const drag = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const points = cloud?.points ?? [];
    if (!canvas || !points.length) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const draw = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, Math.floor(rect.width * ratio));
      const height = Math.max(1, Math.floor(rect.height * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.fillStyle = "#070a0f";
      context.fillRect(0, 0, rect.width, rect.height);
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const projected = points.map((point) => {
        const rx = point.x * cy - point.z * sy;
        const rz = point.x * sy + point.z * cy;
        const ry = point.y * cp - rz * sp;
        const depth = point.y * sp + rz * cp;
        const perspective = 1 / Math.max(1.2, 3.2 + depth);
        return { x: rect.width / 2 + rx * rect.height * perspective * 2.4, y: rect.height / 2 - ry * rect.height * perspective * 2.4, depth, color: `rgb(${point.r} ${point.g} ${point.b})` };
      }).sort((a, b) => b.depth - a.depth);
      for (const point of projected) {
        context.fillStyle = point.color;
        context.globalAlpha = 0.82;
        context.fillRect(point.x, point.y, 1.7, 1.7);
      }
      context.globalAlpha = 1;
    };
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [cloud, pitch, yaw]);

  const run = async () => {
    setBuilding(true);
    try { await onBuild(); } finally { setBuilding(false); }
  };
  const running = Boolean(status?.running);
  const ready = Boolean(status?.outputReady && cloud?.points.length);

  return (
    <div className="relative flex h-full min-h-[27rem] flex-col overflow-hidden rounded-lg border border-edge bg-slate-950">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-edge bg-black/30 px-3 py-2">
        <div>
          <p className="text-xs font-semibold text-white">COLMAP sparse reconstruction</p>
          <p className="mt-0.5 text-[10px] text-slate-500">real camera poses + triangulated scene points from the MP4</p>
        </div>
        <button className="rounded border border-cyan-400/40 bg-cyan-400/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-200 disabled:opacity-50" disabled={running || building || !status?.available} onClick={() => void run()}>
          {running ? "building…" : ready ? "rebuild 3D" : "build 3D from video"}
        </button>
      </div>

      {ready ? (
        <canvas
          ref={canvasRef}
          className="min-h-0 flex-1 cursor-grab touch-none active:cursor-grabbing"
          aria-label={`Interactive COLMAP point cloud with ${status?.pointCount ?? 0} points`}
          onPointerDown={(event) => { drag.current = { x: event.clientX, y: event.clientY, yaw, pitch }; event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerMove={(event) => { if (!drag.current) return; setYaw(drag.current.yaw + (event.clientX - drag.current.x) * 0.008); setPitch(Math.max(-1.2, Math.min(1.2, drag.current.pitch + (event.clientY - drag.current.y) * 0.008))); }}
          onPointerUp={() => { drag.current = null; }}
        />
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
          <div className={`mb-4 h-14 w-14 rounded-full border ${running ? "animate-spin border-cyan-300 border-t-transparent" : "border-slate-700"}`} />
          <p className="text-sm font-semibold text-slate-200">{status?.message ?? "Checking COLMAP…"}</p>
          <p className="mt-2 max-w-md text-[11px] leading-relaxed text-slate-500">
            Uses sampled frames and sequential matching for speed. Reconstruction needs camera movement with overlapping views and visible texture.
          </p>
        </div>
      )}

      <div className="border-t border-edge bg-black/30 px-3 py-2">
        <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-slate-500">
          <span>{status?.phase ?? "connecting"}</span><span>{status?.progress ?? 0}%</span>
        </div>
        <div className="h-1 overflow-hidden rounded bg-slate-800"><div className="h-full bg-cyan-300 transition-all duration-500" style={{ width: `${status?.progress ?? 0}%` }} /></div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[10px] text-slate-400">
          <span>{status?.framesExtracted ?? 0} frames</span><span>{status?.registeredImages ?? 0} cameras solved</span><span>{status?.pointCount ?? 0} 3D points</span>
          {ready ? <span className="ml-auto text-cyan-300">drag to rotate</span> : null}
        </div>
      </div>
    </div>
  );
}
