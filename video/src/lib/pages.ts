import type { Caption } from "@remotion/captions";

export type Token = {
  text: string;
  fromMs: number;
  toMs: number;
  /** 重点词，渲染时放大 */
  emphasis: boolean;
};

export type Page = {
  text: string;
  startMs: number;
  endMs: number;
  tokens: Token[];
};

// Remotion 自带的 createTikTokStyleCaptions 是靠「单词前的空格」分页的，
// 中文没有空格，整篇稿子会被塞进同一页。这里按中文标点 + 字数 + 时长分页。
const STRONG_BREAK = /[。！？；…]$/; // 句末，必断
const WEAK_BREAK = /[，、：]$/; // 停顿，够长才断

// 显示时去掉的标点。感叹号问号保留，它们带语气。
const STRIP_FOR_DISPLAY = /[。，、；：…]/g;

export type PageOptions = {
  /** 一页最多几个汉字，超了硬断 */
  maxChars?: number;
  /** 弱标点处至少攒够这么多字才断，避免出现「不过，」这种两字页 */
  minChars?: number;
  /** 一页最长多少毫秒，超了硬断（防止长句糊成一片） */
  maxMs?: number;
};

const visibleLength = (s: string) => s.replace(STRIP_FOR_DISPLAY, "").length;

// ---- 重点词识别 ----
// 稿子里确切数值用阿拉伯数字（"3900.35点"、"2.04%"），概数用中文（"几十亿"），两种都要认。
// 好消息是 edge-tts 会把数字和它的单位切进同一个 token（"2.04%；"、"64708美元，"、
// "2026年8月6日，"），所以阿拉伯数字这一路不用再做跨 token 合并。
const HAS_DIGIT = /[0-9]/;
const NUMERAL_ONLY = /^[零〇一二三四五六七八九十百千万亿两点几多]{2,}$/;
const QUANTITY = /百分之|万亿|亿|万元|美元|欧元|人民币/;

// 出现在新闻标题里、但本身是虚词的，不算重点
const STOPWORDS = new Set([
  "这个", "那个", "可能", "应该", "已经", "还是", "不过", "但是", "因为", "所以",
  "如果", "现在", "今天", "他们", "我们", "你们", "这些", "那些", "一直", "就是",
  "而且", "结果", "问题", "没有", "这样", "那样", "什么", "怎么", "为了", "表示",
  "一个", "一些", "自己", "开始", "继续", "认为", "说白", "咱们", "大家", "听众",
]);

/** 一页里最多放大几处——全放大就等于没放大。稿子里约 40% 的词能命中，必须收紧 */
const MAX_EMPHASIS_PER_PAGE = 1;

// TTS 的分词会把数字切碎（"二零二六年" -> 二零二 / 六 / 年），
// 所以放大要以「整词」为单位：先把相邻的数字 token 连成一段，再吃掉后面的量词。
const NUMERAL_RUN = /^[零〇一二三四五六七八九十百千万亿两点]+$/;
const UNIT = /^(年|月|日|号|个|人|次|元|倍|票|美元|欧元|人民币|万元|亿元)$/;

const isSingleEmphasis = (word: string, keywords: Set<string>) => {
  if (word.length < 2 || STOPWORDS.has(word)) {
    return false;
  }
  return NUMERAL_ONLY.test(word) || QUANTITY.test(word) || keywords.has(word);
};

type Span = { start: number; end: number; score: number };

/**
 * 在一页内找出要放大的整词，标到 token 上。
 * 优先级：数字串(+量词) > 跨两个 token 的关键词 > 单 token 关键词。
 */
const markEmphasis = (tokens: Token[], keywords: Set<string>) => {
  const words = tokens.map((t) => displayText(t.text));
  const spans: Span[] = [];

  // 0) 带阿拉伯数字的 token 本身就是完整的「数值+单位」，直接整块放大
  for (let i = 0; i < words.length; i++) {
    if (HAS_DIGIT.test(words[i])) {
      spans.push({ start: i, end: i, score: 3 });
    }
  }

  // 1) 连续的中文数字 token 连成一段，再吃掉紧跟的量词
  for (let i = 0; i < words.length; ) {
    if (!NUMERAL_RUN.test(words[i])) {
      i++;
      continue;
    }
    let end = i;
    while (end + 1 < words.length && NUMERAL_RUN.test(words[end + 1])) {
      end++;
    }
    if (end + 1 < words.length && UNIT.test(words[end + 1])) {
      end++;
    }
    if (words.slice(i, end + 1).join("").length >= 2) {
      spans.push({ start: i, end, score: 3 });
    }
    i = end + 1;
  }

  // 2) 关键词：先试相邻两个 token 拼起来，拼不中再看单个 token
  for (let i = 0; i < words.length; i++) {
    const pair = words[i] + (words[i + 1] ?? "");
    if (
      words[i + 1] &&
      pair.length <= 6 &&
      keywords.has(pair) &&
      !STOPWORDS.has(pair)
    ) {
      spans.push({ start: i, end: i + 1, score: 2 });
    } else if (isSingleEmphasis(words[i], keywords)) {
      spans.push({ start: i, end: i, score: 1 });
    }
  }

  // 分高的优先，同分取更长的一段；重叠的丢掉
  spans.sort(
    (a, b) =>
      b.score - a.score || b.end - b.start - (a.end - a.start) || a.start - b.start,
  );

  const taken = new Array<boolean>(words.length).fill(false);
  let used = 0;
  for (const span of spans) {
    if (used >= MAX_EMPHASIS_PER_PAGE) {
      break;
    }
    let overlaps = false;
    for (let i = span.start; i <= span.end; i++) {
      if (taken[i]) {
        overlaps = true;
      }
    }
    if (overlaps) {
      continue;
    }
    for (let i = span.start; i <= span.end; i++) {
      taken[i] = true;
      tokens[i].emphasis = true;
    }
    used++;
  }
};

/** 从当天的新闻标题里取出可以当重点词的实体（2–4 字的中文词） */
export const buildKeywords = (headlines: string[]): Set<string> => {
  const out = new Set<string>();
  for (const line of headlines) {
    for (const run of line.match(/[一-龥]{2,}/g) ?? []) {
      // 标题里的连续汉字串，切成 2/3/4 字的候选，后面靠"是否真出现在稿子里"过滤
      for (let len = 2; len <= 4; len++) {
        for (let i = 0; i + len <= run.length; i++) {
          const w = run.slice(i, i + len);
          if (!STOPWORDS.has(w)) {
            out.add(w);
          }
        }
      }
    }
  }
  return out;
};

export const groupChineseCaptions = (
  captions: Caption[],
  keywords: Set<string> = new Set(),
  { maxChars = 14, minChars = 5, maxMs = 3000 }: PageOptions = {},
): Page[] => {
  const pages: Page[] = [];
  let tokens: Token[] = [];

  const flush = () => {
    if (tokens.length === 0) {
      return;
    }
    markEmphasis(tokens, keywords);
    pages.push({
      text: tokens.map((t) => t.text).join(""),
      startMs: tokens[0].fromMs,
      endMs: tokens[tokens.length - 1].toMs,
      tokens,
    });
    tokens = [];
  };

  for (const caption of captions) {
    // 先判断加进来会不会撑爆，再决定要不要提前断页。
    // 不能等加完再判断——像 "25530.28点，" 这种 token 一个就 9 个字符，
    // 一次能把整行冲过头一倍，字会被切出屏幕。
    const incoming = visibleLength(displayText(caption.text));
    if (tokens.length > 0) {
      const current = visibleLength(tokens.map((t) => t.text).join(""));
      if (current + incoming > maxChars) {
        flush();
      }
    }

    tokens.push({
      text: caption.text,
      fromMs: caption.startMs,
      toMs: caption.endMs,
      emphasis: false, // 整页攒齐后由 markEmphasis 按整词标记
    });

    const text = tokens.map((t) => t.text).join("");
    const chars = visibleLength(text);
    const elapsed = caption.endMs - tokens[0].fromMs;

    if (
      STRONG_BREAK.test(caption.text) ||
      (WEAK_BREAK.test(caption.text) && chars >= minChars) ||
      chars >= maxChars ||
      elapsed >= maxMs
    ) {
      flush();
    }
  }
  flush();

  // 把每页拉长到下一页开始，朗读停顿时字幕不会闪掉
  for (let i = 0; i < pages.length - 1; i++) {
    pages[i].endMs = pages[i + 1].startMs;
  }

  return pages;
};

/** 屏幕上显示的文字：去掉逗号句号这类标点，保留语气标点 */
export const displayText = (s: string) => s.replace(STRIP_FOR_DISPLAY, "");
