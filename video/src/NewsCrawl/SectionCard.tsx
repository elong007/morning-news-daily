import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { NotoSansSC } from "../load-font";

/** 板块卡停留多久（帧） */
export const SECTION_CARD_FRAMES = 54;

const GOLD_GRADIENT = "linear-gradient(180deg, #ffeab0 0%, #f2c14b 48%, #b98a24 100%)";

export const SectionCard: React.FC<{
  readonly board: string;
  readonly emoji: string;
}> = ({ board, emoji }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 18, mass: 0.7 }, durationInFrames: 14 });
  // 尾巴淡出，别硬切回 crawl
  const exit = interpolate(
    frame,
    [SECTION_CARD_FRAMES - 14, SECTION_CARD_FRAMES],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const opacity = Math.min(interpolate(enter, [0, 0.4], [0, 1], { extrapolateRight: "clamp" }), exit);

  // 两条横线从中间向两侧拉开，卡片有"展开"的动作而不是直接出现
  const ruleWidth = interpolate(enter, [0, 1], [0, 420]);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        fontFamily: NotoSansSC,
        opacity,
      }}
    >
      {/* 几乎全黑地盖住底下正在滚的 crawl。
          试过 0.82，金色字透上来会和卡片文字撞在一起糊成一片——
          板块卡要的是"断一下"，不是半透明叠加。 */}
      <AbsoluteFill style={{ backgroundColor: "rgba(0,0,0,0.96)" }} />

      <div style={{ zIndex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ fontSize: 96, lineHeight: 1, marginBottom: 30 }}>{emoji}</div>
        <div style={{ width: ruleWidth, height: 2, background: "rgba(242,193,75,0.55)" }} />
        <div
          style={{
            margin: "28px 0",
            fontSize: 104,
            fontWeight: 800,
            letterSpacing: "0.14em",
            textIndent: "0.14em",
            background: GOLD_GRADIENT,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          {board}
        </div>
        <div style={{ width: ruleWidth, height: 2, background: "rgba(242,193,75,0.55)" }} />
      </div>
    </AbsoluteFill>
  );
};
