import { displayText, type Page, type Token } from "../lib/pages";

export type FlashLine = {
  tokens: Token[];
  text: string;
  /** 相对本页起点的出现时间 */
  appearMs: number;
  /** 整行都是虚词——不管排第几行，字号都钉死在最小档 */
  isParticle: boolean;
  /** 行内是否有重点词（数字/关键实体），有就整行走渐变色 */
  hasEmphasis: boolean;
};

// 常见虚词：单字和高频连词各收一份。没做分词，只能靠字表近似——
// 宁可漏判（虚词被当成实词放大）也不要错判实词（会把该放大的词压小）。
const PARTICLE_CHARS = new Set(
  "的了着过是在和与但而也就又还都很更最被把让给对从向为以及或且之其该地得吗呢吧啊嘛么啦呀个这那你我他她它们".split(
    "",
  ),
);
const PARTICLE_WORDS = new Set([
  "虽然", "因为", "所以", "但是", "不过", "而且", "只要", "只有", "即使",
  "无论", "不管", "尽管", "仍然", "于是", "然而", "接着", "随后", "此外",
  "另外", "总之", "因此", "如果", "假如", "倘若", "哪怕", "可能", "应该",
  "已经", "还是", "现在",
]);

const isParticleWord = (word: string, emphasis: boolean) => {
  if (emphasis || word === "") {
    return false;
  }
  if (PARTICLE_WORDS.has(word)) {
    return true;
  }
  return [...word].every((ch) => PARTICLE_CHARS.has(ch));
};

/** 一行最多攒几个可见字——太长会把左对齐的行顶出屏幕右边 */
const MAX_LINE_CHARS = 4;

/**
 * 把一页的 token 切成几行短句，供逐行弹出。
 * 纯按字数攒行（没有分词器），但数字/关键词的整词绝不拆到两行——
 * 那是 markEmphasis 费劲连起来的（"二零二六年"不能把"年"甩出去）。
 */
export const buildFlashLines = (page: Page): FlashLine[] => {
  const lines: FlashLine[] = [];
  let current: Token[] = [];
  let currentChars = 0;

  const flush = () => {
    if (current.length === 0) {
      return;
    }
    const text = current.map((t) => displayText(t.text)).join("");
    lines.push({
      tokens: current,
      text,
      appearMs: current[0].fromMs - page.startMs,
      isParticle: isParticleWord(text, current.some((t) => t.emphasis)),
      hasEmphasis: current.some((t) => t.emphasis),
    });
    current = [];
    currentChars = 0;
  };

  for (const token of page.tokens) {
    const word = displayText(token.text);
    if (word === "") {
      continue;
    }

    const continuesEmphasisGroup = token.emphasis && current[current.length - 1]?.emphasis;
    if (current.length > 0 && !continuesEmphasisGroup && currentChars + word.length > MAX_LINE_CHARS) {
      flush();
    }

    current.push(token);
    currentChars += word.length;
  }
  flush();

  return lines;
};

/** 短句 + 带重点词 = 整句当"重点句"超大单行播出，不走逐行堆叠 */
export const isHeroPage = (page: Page) => {
  const chars = page.tokens.reduce((n, t) => n + displayText(t.text).length, 0);
  return chars > 0 && chars <= 10 && page.tokens.some((t) => t.emphasis);
};
