import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { NotoSansSC } from "../load-font";
import { displayText, type Page } from "../lib/pages";

const HIGHLIGHT = "#ffd400";
const EMPHASIS_COLOR = "#ffd400";
const FONT_SIZE = 96;
/** 重点词放大到普通字的多少倍 */
const EMPHASIS_SCALE = 1.42;
const MAX_WIDTH = 940;

export const CaptionLine: React.FC<{ readonly page: Page }> = ({ page }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeInMs = (frame / fps) * 1000;

  // 整页入场：螺旋推进——绕 Z 轴转 90° 的同时从纵深推到眼前。
  // 转和推用同一条 spring，所以是拧着上来的一整个动作，不是两段动画拼的。
  const enter = spring({
    frame,
    fps,
    config: { damping: 16, mass: 0.7 },
    durationInFrames: 14,
  });
  const rotateZ = interpolate(enter, [0, 1], [90, 0]);
  const translateZ = interpolate(enter, [0, 1], [-1800, 0]);
  const opacity = interpolate(enter, [0, 0.4], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        perspective: 1400,
      }}
    >
      <div
        style={{
          fontFamily: NotoSansSC,
          fontWeight: 900,
          fontSize: FONT_SIZE,
          lineHeight: 1.3,
          maxWidth: MAX_WIDTH,
          textAlign: "center",
          color: "white",
          WebkitTextStroke: "15px #06080f",
          paintOrder: "stroke",
          letterSpacing: "-0.01em",
          opacity,
          transform: `translateZ(${translateZ}px) rotateZ(${rotateZ}deg)`,
          transformOrigin: "center center",
          transformStyle: "preserve-3d",
        }}
      >
        {groupTokens(page.tokens).map((group, gi) => {
          const inner = group.map((token, i) => {
            const text = displayText(token.text);
            if (text === "") {
              return null;
            }

            // Sequence 内 useCurrentFrame() 是相对帧，时间戳要减掉整页起点才对得上
            const fromMs = token.fromMs - page.startMs;
            const toMs = token.toMs - page.startMs;

            // 当前正在念的词：变色 + 弹一下。
            // 峰值必须夹在词长之内——有些词只有 60ms，写死 +90ms 会让 interpolate
            // 的 inputRange 不再单调递增，整个渲染会崩。
            const active = fromMs <= timeInMs && toMs > timeInMs;
            const duration = Math.max(1, toMs - fromMs);
            const peakMs = fromMs + Math.min(90, duration * 0.5);
            const pop = active
              ? interpolate(timeInMs, [fromMs, peakMs, toMs], [1, 1.14, 1.06], {
                  extrapolateLeft: "clamp",
                  extrapolateRight: "clamp",
                })
              : 1;
            // 已经念过的词稍微压暗，视线自然跟着走
            const spoken = toMs <= timeInMs;

            const color =
              active || token.emphasis
                ? token.emphasis
                  ? EMPHASIS_COLOR
                  : HIGHLIGHT
                : "white";

            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  // 重点词整体放大；行内混排不同字号会错开基线，统一按中线对齐
                  fontSize: token.emphasis
                    ? FONT_SIZE * EMPHASIS_SCALE
                    : FONT_SIZE,
                  verticalAlign: "middle",
                  WebkitTextStroke: token.emphasis ? "18px #06080f" : undefined,
                  transform: `scale(${pop})`,
                  color,
                  opacity: spoken && !active ? 0.72 : 1,
                }}
              >
                {text}
              </span>
            );
          });

          // 放大的整词要整块不拆行，否则「二零二六年」的「年」会被甩到下一行
          return group[0].emphasis ? (
            <span key={gi} style={{ whiteSpace: "nowrap" }}>
              {inner}
            </span>
          ) : (
            <React.Fragment key={gi}>{inner}</React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** 把相邻的重点词收成一组，普通词各自一组 */
const groupTokens = (tokens: Page["tokens"]): Page["tokens"][] => {
  const groups: Page["tokens"][] = [];
  for (const token of tokens) {
    const last = groups[groups.length - 1];
    if (token.emphasis && last?.[0].emphasis) {
      last.push(token);
    } else {
      groups.push([token]);
    }
  }
  return groups;
};
