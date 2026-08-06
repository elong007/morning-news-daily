import type { Caption } from "@remotion/captions";
import { getAudioDurationInSeconds } from "@remotion/media-utils";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  cancelRender,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
  useDelayRender,
  useVideoConfig,
  watchStaticFile,
} from "remotion";
import { z } from "zod";
import { buildKeywords, groupChineseCaptions, type Page } from "../lib/pages";
import { loadFont } from "../load-font";
import { CrawlLine } from "./CrawlLine";
import { Intro, INTRO_FRAMES } from "./Intro";
import { Outro, OUTRO_FRAMES } from "./Outro";
import { StarField } from "./StarField";

// ---- crawl 的几何参数，调这几个数就能改观感 ----
/** 每行占多高 */
const LINE_H = 142;
/** 整块文字往后仰多少度 */
const TILT = 58;
/** 透视强度：越小越夸张 */
const PERSPECTIVE = 720;
/** 正在念的那行落在屏幕的哪个高度（也是 3D 旋转的原点，此处不变形） */
const ORIGIN_Y = 1380;
/** 当前行前后各渲染几行——全渲 300 多行没必要 */
const WINDOW_BEFORE = 16;
const WINDOW_AFTER = 4;
/** 念完之后文字继续飘远的速度（像素/毫秒） */
const TAIL_DRIFT = 0.09;

export const newsCrawlSchema = z.object({
  audioFile: z.string(),
  captionsFile: z.string(),
  dateStr: z.string(),
});

type Props = z.infer<typeof newsCrawlSchema>;

export const calculateNewsCrawlMetadata: CalculateMetadataFunction<Props> = async ({
  props,
}) => {
  const fps = 30;
  const durationInSeconds = await getAudioDurationInSeconds(
    staticFile(props.audioFile),
  );

  return {
    fps,
    durationInFrames:
      INTRO_FRAMES + Math.ceil(durationInSeconds * fps) + OUTRO_FRAMES,
  };
};

/**
 * 滚动位移由语音时间戳驱动，不是匀速播放——
 * 这样"正在念的那行"永远停在 ORIGIN_Y，念得快的地方滚得快，停顿时也跟着停。
 * 念完之后转成匀速漂移，让文字继续飞向深空。
 */
const crawlOffset = (pages: Page[], timeMs: number) => {
  if (pages.length === 0 || timeMs <= pages[0].startMs) {
    return 0;
  }

  const last = pages[pages.length - 1];
  if (timeMs >= last.endMs) {
    return pages.length * LINE_H + (timeMs - last.endMs) * TAIL_DRIFT;
  }

  const index = pages.findIndex((p) => timeMs < p.endMs);
  const page = pages[index];
  const span = Math.max(1, page.endMs - page.startMs);
  const progress = Math.min(1, Math.max(0, (timeMs - page.startMs) / span));
  return (index + progress) * LINE_H;
};

const Crawl: React.FC<{
  readonly audioSrc: string;
  readonly captionsSrc: string;
  readonly audioFrames: number;
}> = ({ audioSrc, captionsSrc, audioFrames }) => {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [headlines, setHeadlines] = useState<string[]>([]);
  const { delayRender, continueRender } = useDelayRender();
  const [handle] = useState(() => delayRender());
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const timeMs = (frame / fps) * 1000;

  const fetchCaptions = useCallback(async () => {
    try {
      await loadFont();
      const [capRes, metaRes] = await Promise.all([
        fetch(captionsSrc),
        fetch(staticFile("meta.json")),
      ]);
      setCaptions((await capRes.json()) as Caption[]);
      const meta = (await metaRes.json()) as { boards?: { headlines?: string[] }[] };
      setHeadlines((meta.boards ?? []).flatMap((b) => b.headlines ?? []));
      continueRender(handle);
    } catch (e) {
      cancelRender(e);
    }
  }, [captionsSrc, continueRender, handle]);

  useEffect(() => {
    fetchCaptions();
    const c = watchStaticFile(captionsSrc, fetchCaptions);
    return () => c.cancel();
  }, [fetchCaptions, captionsSrc]);

  const keywords = useMemo(() => buildKeywords(headlines), [headlines]);
  // crawl 一行一句，所以切得比翻页版更短，保证不折行
  const pages = useMemo(
    () =>
      groupChineseCaptions(captions, keywords, {
        maxChars: 9,
        minChars: 4,
        maxMs: 2600,
      }),
    [captions, keywords],
  );

  const offset = crawlOffset(pages, timeMs);
  const currentIndex = Math.floor(offset / LINE_H);
  const from = Math.max(0, currentIndex - WINDOW_BEFORE);
  const to = Math.min(pages.length, currentIndex + WINDOW_AFTER + 1);

  // 镜头呼吸：后仰角和透视原点极慢地摆，画面才不死板
  const t = frame / fps;
  const tilt = TILT + Math.sin(t * 0.11) * 1.2;
  const originX = 50 + Math.sin(t * 0.08) * 1.6;

  // 念完之后整块淡出，交给收尾卡
  const fadeOut = interpolate(
    frame,
    [audioFrames, audioFrames + OUTRO_FRAMES * 0.55],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ opacity: fadeOut }}>
      <Audio src={audioSrc} />
      <AbsoluteFill
        style={{ perspective: PERSPECTIVE, perspectiveOrigin: `${originX}% 18%` }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            width: "100%",
            top: ORIGIN_Y,
            transform: `rotateX(${tilt}deg)`,
            transformOrigin: "50% 100%",
            transformStyle: "preserve-3d",
          }}
        >
          <div style={{ position: "relative", transform: `translateY(${-offset}px)` }}>
            {pages.slice(from, to).map((page, i) => {
              const index = from + i;
              return (
                <div
                  key={index}
                  style={{
                    position: "absolute",
                    left: 0,
                    width: "100%",
                    top: index * LINE_H,
                    height: LINE_H,
                  }}
                >
                  <CrawlLine
                    page={page}
                    timeMs={timeMs}
                    isCurrent={index === currentIndex}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** 底部一条 2px 暗金细线，比进度条克制 */
const ProgressHairline: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames, width } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames - 1));

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end" }}>
      <div
        style={{
          height: 2,
          width: width * progress,
          backgroundColor: "rgba(242,193,75,0.42)",
        }}
      />
    </AbsoluteFill>
  );
};

export const NewsCrawl: React.FC<Props> = ({ audioFile, captionsFile, dateStr }) => {
  const { durationInFrames } = useVideoConfig();
  const audioFrames = durationInFrames - INTRO_FRAMES - OUTRO_FRAMES;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <StarField />

      <Sequence durationInFrames={INTRO_FRAMES}>
        <Intro dateStr={dateStr} />
      </Sequence>

      <Sequence from={INTRO_FRAMES}>
        <Crawl
          audioSrc={staticFile(audioFile)}
          captionsSrc={staticFile(captionsFile)}
          audioFrames={audioFrames}
        />
      </Sequence>

      <Sequence from={INTRO_FRAMES + audioFrames}>
        <Outro dateStr={dateStr} />
      </Sequence>

      {/* 四周压暗，视线收进画面中心 */}
      <AbsoluteFill
        style={{
          background:
            // 中心要对齐当前行所在的高度，否则暗角会把最该亮的那行压暗
            "radial-gradient(ellipse 86% 70% at 50% 64%, transparent 0%, rgba(0,0,0,0.18) 66%, rgba(0,0,0,0.55) 100%)",
          pointerEvents: "none",
        }}
      />

      <ProgressHairline />
    </AbsoluteFill>
  );
};

export const newsCrawlDefaultProps: Props = {
  audioFile: "audio.mp3",
  captionsFile: "captions.json",
  dateStr: "2026年8月5日",
};
