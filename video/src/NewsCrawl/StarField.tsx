import React, { useMemo } from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";

const STAR_COUNT = 220;

// 确定性伪随机：位置只跟序号有关。
// 不能用 Math.random()——每帧重算会让星星逐帧乱跳。
//
// 星星是静态的，不闪。除了真实的星战片头本来就不闪，还有个现实原因：
// 逐帧变化的 1~4px 亮点是 h264 最难压的东西，加闪烁会让 6 分钟的成片从 30MB 涨到 350MB，
// 平台二次压缩时还会糊成噪点。
const rand = (n: number) => {
  const x = Math.sin(n * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

export const StarField: React.FC = () => {
  const { width, height } = useVideoConfig();

  const stars = useMemo(
    () =>
      Array.from({ length: STAR_COUNT }, (_, i) => ({
        x: rand(i * 3 + 1) * width,
        y: rand(i * 3 + 2) * height,
        size: 2 + rand(i * 3 + 3) * 3.4,
        opacity: 0.28 + rand(i * 7 + 5) * 0.6,
      })),
    [width, height],
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {stars.map((star, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: star.x,
            top: star.y,
            width: star.size,
            height: star.size,
            borderRadius: "50%",
            backgroundColor: "white",
            opacity: star.opacity,
          }}
        />
      ))}
    </AbsoluteFill>
  );
};
