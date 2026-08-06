import React from "react";
import { interpolate } from "remotion";
import { NotoSansSC } from "../load-font";
import { displayText, type Page } from "../lib/pages";

// 平涂的黄看着廉价。上缘偏亮、下缘偏暗的渐变才有金属质感。
const GOLD_GRADIENT = "linear-gradient(180deg, #ffe9ad 0%, #f0be45 52%, #b8881f 100%)";
/** 正在念到的词：不换色相，改用更高的明度，靠亮度分层 */
const ACTIVE_COLOR = "#fffaea";

export const BASE_FONT_SIZE = 94;
/** 一行最宽多少像素，超了整行等比缩小 */
const MAX_LINE_WIDTH = 990;
/** 字距，和下面样式里的 letterSpacing 保持一致 */
const LETTER_SPACING_EM = 0.04;

// 估算字符宽度（相对字号的倍数）。汉字接近 1em，数字和拉丁字母窄得多，
// 小数点更窄。用来判断整行要不要缩，避免长数字把字顶出屏幕。
const charWidthEm = (ch: string) => {
  if (/[　-〿＀-￯一-鿿]/.test(ch)) {
    return 1;
  }
  if (/[.]/.test(ch)) {
    return 0.3;
  }
  if (/[0-9]/.test(ch)) {
    return 0.56;
  }
  if (/%/.test(ch)) {
    return 0.9;
  }
  return 0.55;
};

const estimateWidth = (tokens: Page["tokens"]) =>
  tokens.reduce((sum, token) => {
    const size = token.emphasis ? BASE_FONT_SIZE * EMPHASIS_SCALE : BASE_FONT_SIZE;
    const text = displayText(token.text);
    const em = [...text].reduce((w, ch) => w + charWidthEm(ch) + LETTER_SPACING_EM, 0);
    return sum + em * size;
  }, 0);
/** 重点词放大到普通字的多少倍 */
const EMPHASIS_SCALE = 1.36;
/** 正在念的那个词再额外放大一点 */
const ACTIVE_SCALE = 1.1;

export const CrawlLine: React.FC<{
  readonly page: Page;
  /** 绝对时间（毫秒），整块 crawl 共用一条时间轴，不是 Sequence 相对帧 */
  readonly timeMs: number;
  /** 这一行是不是正在被念 */
  readonly isCurrent: boolean;
}> = ({ page, timeMs, isCurrent }) => {
  // 已经念过的行淡出，还没念到的行压得更暗——
  // 未念的行在近处、字最大，不压暗会抢走当前行的注意力
  const read = timeMs >= page.endMs;
  const baseOpacity = isCurrent ? 1 : read ? 0.48 : 0.2;

  // 行内不能折行（折了 crawl 的行距就乱了），所以太宽的行整行等比缩
  const width = estimateWidth(page.tokens);
  const shrink = width > MAX_LINE_WIDTH ? MAX_LINE_WIDTH / width : 1;

  return (
    <div
      style={{
        fontFamily: NotoSansSC,
        fontWeight: 800,
        fontSize: BASE_FONT_SIZE,
        lineHeight: 1.2,
        textAlign: "center",
        whiteSpace: "nowrap",
        letterSpacing: `${LETTER_SPACING_EM}em`,
        opacity: baseOpacity,
        transform: shrink < 1 ? `scale(${shrink})` : undefined,
      }}
    >
      {groupTokens(page.tokens).map((group, gi) => {
        const inner = group.map((token, i) => {
          const text = displayText(token.text);
          if (text === "") {
            return null;
          }

          const active = token.fromMs <= timeMs && token.toMs > timeMs;
          const duration = Math.max(1, token.toMs - token.fromMs);
          const peakMs = token.fromMs + Math.min(90, duration * 0.5);
          const pop = active
            ? interpolate(
                timeMs,
                [token.fromMs, peakMs, token.toMs],
                [1, ACTIVE_SCALE, ACTIVE_SCALE * 0.96],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              )
            : 1;

          // 渐变金是靠 background-clip 裁出来的，文字填充必须透明，
          // 这种状态下 text-shadow 会糊成一团光斑，所以发光只给纯色的当前词用。
          const paint: React.CSSProperties = active
            ? {
                color: ACTIVE_COLOR,
                textShadow: "0 0 38px rgba(255,225,150,0.9)",
              }
            : {
                background: GOLD_GRADIENT,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              };

          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontSize: token.emphasis
                  ? BASE_FONT_SIZE * EMPHASIS_SCALE
                  : BASE_FONT_SIZE,
                verticalAlign: "middle",
                transform: `scale(${pop})`,
                ...paint,
              }}
            >
              {text}
            </span>
          );
        });

        // 放大的整词要整块不拆行
        return group[0].emphasis ? (
          <span key={gi} style={{ whiteSpace: "nowrap" }}>
            {inner}
          </span>
        ) : (
          <React.Fragment key={gi}>{inner}</React.Fragment>
        );
      })}
    </div>
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
