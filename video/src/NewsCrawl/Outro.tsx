import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { NotoSansSC } from "../load-font";

/** 收尾总长（帧）。正文念完后文字继续飘远，然后落收尾卡 */
export const OUTRO_FRAMES = 135;
/** 收尾卡在收尾段的第几帧出现 */
const CARD_IN = 40;

const GOLD_GRADIENT = "linear-gradient(180deg, #ffeab0 0%, #f2c14b 48%, #b98a24 100%)";

export const Outro: React.FC<{ readonly dateStr: string }> = ({ dateStr }) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(
    frame,
    [CARD_IN, CARD_IN + 24, OUTRO_FRAMES - 22, OUTRO_FRAMES],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        fontFamily: NotoSansSC,
        opacity,
      }}
    >
      <div
        style={{
          fontSize: 84,
          fontWeight: 800,
          letterSpacing: "0.2em",
          textIndent: "0.2em",
          background: GOLD_GRADIENT,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}
      >
        世界要闻
      </div>
      <div
        style={{
          marginTop: 26,
          width: 240,
          height: 2,
          background:
            "linear-gradient(90deg, transparent, rgba(242,193,75,0.6), transparent)",
        }}
      />
      <div
        style={{
          marginTop: 26,
          fontSize: 30,
          fontWeight: 400,
          letterSpacing: "0.32em",
          textIndent: "0.32em",
          color: "rgba(255,255,255,0.5)",
        }}
      >
        {dateStr}
      </div>
    </AbsoluteFill>
  );
};
