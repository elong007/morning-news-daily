import { Composition } from "remotion";
import {
  calculateNewsCrawlMetadata,
  NewsCrawl,
  newsCrawlDefaultProps,
  newsCrawlSchema,
} from "./NewsCrawl";
import {
  calculateNewsFlashMetadata,
  NewsFlash,
  newsFlashDefaultProps,
  newsFlashSchema,
} from "./NewsFlash";
import {
  calculateNewsReelMetadata,
  NewsReel,
  newsReelDefaultProps,
  newsReelSchema,
} from "./NewsReel";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 星战片头式：整块文字在透视里持续飞向深处 */}
      <Composition
        id="NewsCrawl"
        component={NewsCrawl}
        calculateMetadata={calculateNewsCrawlMetadata}
        schema={newsCrawlSchema}
        width={1080}
        height={1920}
        defaultProps={newsCrawlDefaultProps}
      />
      {/* 逐页翻入式：一句一屏，螺旋推进 */}
      <Composition
        id="NewsReel"
        component={NewsReel}
        calculateMetadata={calculateNewsReelMetadata}
        schema={newsReelSchema}
        width={1080}
        height={1920}
        defaultProps={newsReelDefaultProps}
      />
      {/* 快闪式：纯黑底，一行比一行大地蹦出来，旧行被挤着往上走 */}
      <Composition
        id="NewsFlash"
        component={NewsFlash}
        calculateMetadata={calculateNewsFlashMetadata}
        schema={newsFlashSchema}
        width={1080}
        height={1920}
        defaultProps={newsFlashDefaultProps}
      />
    </>
  );
};
