import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// 深色底 + 三团缓慢漂移的光斑。字幕是主角，背景只负责别太安静。
const BLOBS = [
  { color: "#2563eb", size: 1500, x: 0.15, y: 0.18, speed: 0.7, drift: 260 },
  { color: "#db2777", size: 1300, x: 0.85, y: 0.42, speed: 1.0, drift: 200 },
  { color: "#0d9488", size: 1600, x: 0.5, y: 0.9, speed: 0.5, drift: 300 },
];

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height, fps } = useVideoConfig();
  const t = frame / fps;

  return (
    <AbsoluteFill style={{ backgroundColor: "#080b14", overflow: "hidden" }}>
      {BLOBS.map((blob, i) => {
        const angle = t * blob.speed * 0.25 + i * 2.1;
        const dx = Math.cos(angle) * blob.drift;
        const dy = Math.sin(angle * 0.8) * blob.drift * 0.6;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              width: blob.size,
              height: blob.size,
              left: width * blob.x - blob.size / 2 + dx,
              top: height * blob.y - blob.size / 2 + dy,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${blob.color} 0%, transparent 65%)`,
              opacity: 0.42,
              filter: "blur(80px)",
            }}
          />
        );
      })}
      {/* 压暗上下两端，让顶部标题和底部进度条读得清 */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 72%, rgba(0,0,0,0.6) 100%)",
        }}
      />
      {/* 极轻的呼吸感，避免画面完全静止 */}
      <AbsoluteFill
        style={{
          backgroundColor: "#ffffff",
          opacity: interpolate(Math.sin(t * 0.6), [-1, 1], [0.005, 0.022]),
        }}
      />
    </AbsoluteFill>
  );
};
