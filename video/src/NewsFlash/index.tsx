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
import { loadFont } from "../load-font";
import { FlashPage } from "./FlashPage";

export const newsFlashSchema = z.object({
  audioFile: z.string(),
  captionsFile: z.string(),
  dateStr: z.string(),
});

type Props = z.infer<typeof newsFlashSchema>;

export const calculateNewsFlashMetadata: CalculateMetadataFunction<Props> = async ({
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

const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames, width } = useVideoConfig();
  const progress = Math.min(1, frame / Math.max(1, durationInFrames - 1));

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end" }}>
      <div style={{ height: 6, width, backgroundColor: "rgba(255,255,255,0.1)" }}>
        <div
          style={{
            height: "100%",
            width: width * progress,
            background: "linear-gradient(90deg, #60a5fa, #c084fc)",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export const NewsFlash: React.FC<Props> = ({ audioFile, captionsFile }) => {
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
  // minChars 卡得接近 maxChars，基本只在句末（。！？）断页——
  // 快闪要的是一整句话连续堆几行再清空，逗号处断早了堆叠就只剩一两行，没有递增的铺垫感
  const pages = useMemo(
    () =>
      groupChineseCaptions(captions, keywords, {
        maxChars: 16,
        minChars: 11,
        maxMs: 3400,
      }),
    [captions, keywords],
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      <Audio src={audioSrc} />
      {pages.map((page, i) => {
        const from = Math.round((page.startMs / 1000) * fps);
        const durationInFrames = Math.max(
          1,
          Math.round((page.endMs / 1000) * fps) - from,
        );

        return (
          <Sequence key={i} from={from} durationInFrames={durationInFrames}>
            <FlashPage page={page} />
          </Sequence>
        );
      })}
      <ProgressBar />
    </AbsoluteFill>
  );
};

export const newsFlashDefaultProps: Props = {
  audioFile: "audio.mp3",
  captionsFile: "captions.json",
  dateStr: "2026年8月5日",
};
