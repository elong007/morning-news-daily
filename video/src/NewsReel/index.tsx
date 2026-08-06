import type { Caption } from "@remotion/captions";
import { getAudioDurationInSeconds } from "@remotion/media-utils";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  cancelRender,
  Sequence,
  staticFile,
  useCurrentFrame,
  useDelayRender,
  useVideoConfig,
  watchStaticFile,
} from "remotion";
import { z } from "zod";
import { buildKeywords, groupChineseCaptions } from "../lib/pages";
import { loadFont, NotoSansSC } from "../load-font";
import { Background } from "./Background";
import { CaptionLine } from "./CaptionLine";

// 两个 src 是 public/ 下的文件名，组件内部再包 staticFile()——
// 这样 props.json 可以由 Python 脚本直接生成，不用知道 Remotion 的 URL 规则。
export const newsReelSchema = z.object({
  audioFile: z.string(),
  captionsFile: z.string(),
  dateStr: z.string(),
});

type Props = z.infer<typeof newsReelSchema>;

export const calculateNewsReelMetadata: CalculateMetadataFunction<Props> = async ({
  props,
}) => {
  const fps = 30;
  const durationInSeconds = await getAudioDurationInSeconds(
    staticFile(props.audioFile),
  );

  return {
    fps,
    durationInFrames: Math.ceil(durationInSeconds * fps),
  };
};

const Header: React.FC<{ readonly dateStr: string }> = ({ dateStr }) => (
  <AbsoluteFill
    style={{
      justifyContent: "flex-start",
      alignItems: "center",
      paddingTop: 110,
      fontFamily: NotoSansSC,
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "16px 34px",
        borderRadius: 999,
        backgroundColor: "rgba(255,255,255,0.09)",
        border: "2px solid rgba(255,255,255,0.16)",
        backdropFilter: "blur(12px)",
      }}
    >
      <div
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          backgroundColor: "#ff3b30",
        }}
      />
      <span style={{ fontSize: 38, fontWeight: 900, color: "white", letterSpacing: 2 }}>
        每日晨报
      </span>
      <span style={{ fontSize: 32, fontWeight: 500, color: "rgba(255,255,255,0.66)" }}>
        {dateStr}
      </span>
    </div>
  </AbsoluteFill>
);

const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames, width } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames - 1));

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end" }}>
      <div style={{ height: 8, width, backgroundColor: "rgba(255,255,255,0.14)" }}>
        <div
          style={{
            height: "100%",
            width: width * progress,
            background: "linear-gradient(90deg, #ffd400, #ff7a00)",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export const NewsReel: React.FC<Props> = ({ audioFile, captionsFile, dateStr }) => {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [headlines, setHeadlines] = useState<string[]>([]);
  const { delayRender, continueRender } = useDelayRender();
  const [handle] = useState(() => delayRender());
  const { fps } = useVideoConfig();

  const audioSrc = staticFile(audioFile);
  const captionsSrc = staticFile(captionsFile);

  const fetchCaptions = useCallback(async () => {
    try {
      await loadFont();
      const [capRes, metaRes] = await Promise.all([
        fetch(captionsSrc),
        fetch(staticFile("meta.json")),
      ]);
      setCaptions((await capRes.json()) as Caption[]);
      // 当天的新闻标题就是最好的重点词来源
      const meta = (await metaRes.json()) as {
        boards?: { headlines?: string[] }[];
      };
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
  const pages = useMemo(
    () => groupChineseCaptions(captions, keywords),
    [captions, keywords],
  );

  return (
    <AbsoluteFill>
      <Background />
      <Audio src={audioSrc} />
      {pages.map((page, i) => {
        const from = Math.round((page.startMs / 1000) * fps);
        const durationInFrames = Math.max(
          1,
          Math.round((page.endMs / 1000) * fps) - from,
        );

        return (
          <Sequence key={i} from={from} durationInFrames={durationInFrames}>
            <CaptionLine page={page} />
          </Sequence>
        );
      })}
      <Header dateStr={dateStr} />
      <ProgressBar />
    </AbsoluteFill>
  );
};

export const newsReelDefaultProps: Props = {
  audioFile: "audio.mp3",
  captionsFile: "captions.json",
  dateStr: "2026年8月5日",
};
