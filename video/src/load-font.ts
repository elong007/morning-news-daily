import { continueRender, delayRender, staticFile } from "remotion";

export const NotoSansSC = `NotoSansSC`;

let loaded = false;

// Noto Sans SC 是可变字重字体（100–900），字幕用 900 才够冲。
export const loadFont = async (): Promise<void> => {
  if (loaded) {
    return Promise.resolve();
  }

  const waitForFont = delayRender();

  loaded = true;

  const font = new FontFace(
    NotoSansSC,
    `url('${staticFile("NotoSansSC-VF.ttf")}') format('truetype')`,
    { weight: "100 900" },
  );

  await font.load();
  document.fonts.add(font);

  continueRender(waitForFont);
};
