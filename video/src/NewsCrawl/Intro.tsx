import React from "react";
import { AbsoluteFill, Audio, interpolate, staticFile, useCurrentFrame } from "remotion";
import { NotoSansSC } from "../load-font";

/** 序幕总长（帧），正片和音频都从这之后开始。片头音乐正好 5.000 秒 = 150 帧 */
export const INTRO_FRAMES = 150;

// 片头音乐平均响度 -15.3 LUFS，口播是 -23.5，差 8.2 dB。
// 原样播会把紧接着的旁白衬得很小声，所以衰减约 8 dB（10^(-8/20) ≈ 0.4）。
// 音乐尾巴 0.6 秒已经自然衰减到 -66.8 dB，收尾干净，不用再加淡出。
const MUSIC_VOLUME = 0.4;

// 星战片头先出一行安静的蓝字，再落主标题。这里照这个节奏走。
const LEAD_IN = 0;
const LEAD_OUT = 74;
const TITLE_IN = 62;

const GOLD_GRADIENT = "linear-gradient(180deg, #ffeab0 0%, #f2c14b 48%, #b98a24 100%)";

export const Intro: React.FC<{ readonly dateStr: string }> = ({ dateStr }) => {
  const frame = useCurrentFrame();

  // 第一行：淡蓝小字，报日期
  const leadOpacity = interpolate(
    frame,
    [LEAD_IN, LEAD_IN + 18, LEAD_OUT - 18, LEAD_OUT],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  // 主标题：从稍大慢慢沉下去，像退向深空
  const titleOpacity = interpolate(
    frame,
    [TITLE_IN, TITLE_IN + 22, INTRO_FRAMES - 26, INTRO_FRAMES],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const titleScale = interpolate(frame, [TITLE_IN, INTRO_FRAMES], [1.14, 0.9], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ fontFamily: NotoSansSC }}>
      <Audio src={staticFile("music_start.mp3")} volume={MUSIC_VOLUME} />

      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div
          style={{
            opacity: leadOpacity,
            color: "#9fc4dd",
            fontSize: 44,
            fontWeight: 500,
            letterSpacing: "0.42em",
            textIndent: "0.42em",
          }}
        >
          {dateStr} · 晨间
        </div>
      </AbsoluteFill>

      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          opacity: titleOpacity,
          transform: `scale(${titleScale})`,
        }}
      >
        <div
          style={{
            fontSize: 168,
            fontWeight: 800,
            letterSpacing: "0.16em",
            textIndent: "0.16em",
            background: GOLD_GRADIENT,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          世界要闻
        </div>
        <div
          style={{
            marginTop: 34,
            width: 340,
            height: 2,
            background:
              "linear-gradient(90deg, transparent, rgba(242,193,75,0.75), transparent)",
          }}
        />
        <div
          style={{
            marginTop: 30,
            fontSize: 26,
            fontWeight: 400,
            letterSpacing: "0.55em",
            textIndent: "0.55em",
            color: "rgba(242,193,75,0.6)",
          }}
        >
          WORLD NEWS
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
