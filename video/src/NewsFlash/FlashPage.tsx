import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { NotoSansSC } from "../load-font";
import { displayText, type Page } from "../lib/pages";
import { buildFlashLines, isHeroPage } from "./lines";

// 蓝紫渐变只给重点词用——大片纯白里一撞色，眼睛会自己找过去
const GRADIENT = "linear-gradient(120deg, #60a5fa 0%, #818cf8 48%, #c084fc 100%)";
const PARTICLE_SIZE = 46;
/** 逐行递增：第几行、放大到多少倍，封顶避免字顶出屏幕 */
const BASE_SIZE = 52;
const GROWTH = 1.38;
const SIZE_CAP = 176;
const HERO_SIZE = 184;
const LINE_GAP = 20;
const PAD_LEFT = 72;
/** 整组入场时从多少度转正 */
const SPIN_FROM_DEG = -28;

const sizeForLine = (index: number, isParticle: boolean) =>
  isParticle ? PARTICLE_SIZE : Math.min(SIZE_CAP, BASE_SIZE * GROWTH ** index);

/** 整页绕屏幕中心转正：一页从头到尾是一个整体，入场时拧着转进来，弹簧回弹就是"轻微回弹" */
const groupSpin = (frame: number, fps: number) => {
  const progress = spring({
    frame,
    fps,
    config: { damping: 11, mass: 0.5 },
    durationInFrames: 12,
  });
  return interpolate(progress, [0, 1], [SPIN_FROM_DEG, 0]);
};

/** 单行的弹入：从小放大，不再自己旋转，旋转交给整组 */
const popIn = (frame: number, fps: number, appearFrame: number) => {
  const local = frame - appearFrame;
  if (local < 0) {
    return { scale: 0.3, opacity: 0 };
  }
  const progress = spring({
    frame: local,
    fps,
    config: { damping: 11, mass: 0.5 },
    durationInFrames: 10,
  });
  return {
    scale: interpolate(progress, [0, 1], [0.3, 1]),
    opacity: interpolate(local, [0, 4], [0, 1], { extrapolateRight: "clamp" }),
  };
};

const GradientText: React.FC<{
  readonly children: React.ReactNode;
  readonly style?: React.CSSProperties;
}> = ({ children, style }) => (
  <span
    style={{
      backgroundImage: GRADIENT,
      backgroundClip: "text",
      WebkitBackgroundClip: "text",
      color: "transparent",
      ...style,
    }}
  >
    {children}
  </span>
);

/** 短平快的"重点句"：不走堆叠，整句直接超大蹦出来 */
const HeroLine: React.FC<{ readonly page: Page }> = ({ page }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const text = page.tokens.map((t) => displayText(t.text)).join("");
  const { scale, opacity } = popIn(frame, fps, 0);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        paddingLeft: PAD_LEFT,
        transform: `rotate(${groupSpin(frame, fps)}deg)`,
        transformOrigin: "center center",
      }}
    >
      <GradientText
        style={{
          fontFamily: NotoSansSC,
          fontWeight: 900,
          fontSize: HERO_SIZE,
          lineHeight: 1.08,
          maxWidth: 960,
          transform: `scale(${scale})`,
          transformOrigin: "left center",
          opacity,
        }}
      >
        {text}
      </GradientText>
    </AbsoluteFill>
  );
};

/** 常规页：整组绕中心转进来，逐行从小蹦到大，新行出现时旧行一起被挤着往上走 */
const FlowLines: React.FC<{ readonly page: Page }> = ({ page }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lines = React.useMemo(() => buildFlashLines(page), [page]);
  const appearFrame = (ms: number) => Math.round((ms / 1000) * fps);

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        paddingLeft: PAD_LEFT,
        paddingBottom: 340,
        transform: `rotate(${groupSpin(frame, fps)}deg)`,
        transformOrigin: "center center",
      }}
    >
      <div style={{ position: "relative" }}>
        {lines.map((line, i) => {
          const myFrame = appearFrame(line.appearMs);
          const { scale, opacity } = popIn(frame, fps, myFrame);
          const fontSize = sizeForLine(i, line.isParticle);

          // 后面每新来一行，自己就再往上挪一行的高度；每挪一次都单独起一条弹簧，
          // 挤上去的瞬间带一点弹性，不是干巴巴地瞬移
          let push = 0;
          for (let j = i + 1; j < lines.length; j++) {
            const laterFrame = appearFrame(lines[j].appearMs);
            const laterSize = sizeForLine(j, lines[j].isParticle);
            const p = spring({
              frame: frame - laterFrame,
              fps,
              config: { damping: 18, mass: 0.6 },
              durationInFrames: 10,
            });
            push += p * (laterSize * 1.15 + LINE_GAP);
          }

          const textStyle: React.CSSProperties = {
            fontFamily: NotoSansSC,
            fontWeight: line.isParticle ? 700 : 900,
            fontSize,
            lineHeight: 1.1,
          };

          return (
            <div
              key={i}
              style={{
                transform: `translateY(${-push}px)`,
                marginTop: i === 0 ? 0 : LINE_GAP,
              }}
            >
              <div
                style={{
                  display: "inline-block",
                  transform: `scale(${scale})`,
                  transformOrigin: "left center",
                  opacity,
                }}
              >
                {line.hasEmphasis ? (
                  <GradientText style={textStyle}>{line.text}</GradientText>
                ) : (
                  <span style={{ ...textStyle, color: line.isParticle ? "rgba(255,255,255,0.68)" : "#ffffff" }}>
                    {line.text}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const FlashPage: React.FC<{ readonly page: Page }> = ({ page }) => {
  if (isHeroPage(page)) {
    return <HeroLine page={page} />;
  }
  return <FlowLines page={page} />;
};
