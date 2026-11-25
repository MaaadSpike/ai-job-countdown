// Cloudflare Pages Function：GET /api/search?q=software+engineer+AI&lang=en&days=30[&impact=0]
// 在服务器端查 Google News RSS（浏览器不能直接跨域请求它），返回 JSON。不需要 API key。
// 默认（impact=1）跑两组查询，按标题关键词粗分：
//   signal「AI 进展」：取代、裁员、自动化、岗位……
//   check 「现实检验」：出错、幻觉、重新招人、不会取代、短缺……
// 只看标题、不调模型，分类会有错；页面上标明「自动搜索，未经人工核实」。以后可以在这里加一步 LLM 分类。
// 同一个查询在 Cloudflare 边缘缓存 6 小时，避免频繁请求 Google。
// 部署：functions/ 要在仓库根目录（wrangler 运行的目录），`wrangler pages deploy web` 会自动带上。
// 本地测试：在仓库根目录运行 `npx wrangler pages dev web`（python -m http.server 不会运行这个函数）。

const UA = "Mozilla/5.0 (compatible; ai-job-countdown/1.0)";
const EDITIONS = {
  en: { hl: "en-US", gl: "US", ceid: "US:en" },
  zh: { hl: "zh-CN", gl: "CN", ceid: "CN:zh-Hans" },
};

const QUERY = {
  signal: {
    en: '(replace OR replacing OR replaced OR layoffs OR "job cuts" OR automate OR automation OR jobs OR hiring OR workforce OR obsolete)',
    zh: "(取代 OR 替代 OR 代替 OR 裁员 OR 失业 OR 岗位 OR 饭碗 OR 就业 OR 自动化 OR 淘汰)",
  },
  check: {
    en: '(errors OR mistakes OR fails OR failed OR hallucinations OR fabricated OR rehire OR rehiring OR "won\'t replace" OR "can\'t replace" OR overhyped OR backlash OR shortage OR "still need")',
    zh: "(出错 OR 失误 OR 幻觉 OR 翻车 OR 重新招聘 OR 不会取代 OR 无法取代 OR 高估 OR 局限 OR 短缺)",
  },
};
// 按标题分类：先看是不是「现实检验」，再看是不是「AI 进展」，都不是就丢掉（招聘广告、课程、泛泛的介绍）
const TITLE = {
  check: {
    en: /\b(errors?|mistakes?|fail\w*|flaw\w*|hallucinat\w*|fabricat\w*|fake|wrong|rehir\w*|revers\w*|backtrack\w*|scal\w* back|pull\w* back|paus\w*|halt\w*|ban\w*|sanction\w*|lawsuits?|sued|backlash|protest\w*|overhyped|hype|limits?|limitations?|struggl\w*|shortages?|still need\w*|(won't|can't|cannot|will not|isn't|not) (replace|take)\w*|slower|worse|risks?)\b/i,
    zh: /出错|错误|失误|幻觉|编造|翻车|重新招聘|回聘|叫停|暂停|起诉|处罚|抗议|高估|局限|短缺|不会取代|无法取代|难以取代|取代不了|风险/,
  },
  signal: {
    en: /\b(replac\w*|layoffs?|laid off|lay off|job cuts?|cut\w* jobs?|jobs?|automat\w*|obsolete|displac\w*|hiring|hires?|workforce|unemploy\w*|eliminat\w*|redundan\w*|take over|taking over|threat\w*|wipe out|wiping out|headcount|entry-level|junior|agents?)\b/i,
    zh: /取代|替代|代替|裁员|失业|岗位|饭碗|就业|自动化|淘汰|消失|冲击|抢走|招聘|入门级|初级/,
  },
};

export function classify(title) {
  if (TITLE.check.en.test(title) || TITLE.check.zh.test(title)) return "check";
  if (TITLE.signal.en.test(title) || TITLE.signal.zh.test(title)) return "signal";
  return null;
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function decode(s) {
  return s
    .replace(/^<!\[CDATA\[|\]\]>$/g, "")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&quot;/g, '"').replace(/&apos;|&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .trim();
}

function tag(block, name) {
  const m = block.match(new RegExp("<" + name + "(?:\\s[^>]*)?>([\\s\\S]*?)</" + name + ">"));
  return m ? decode(m[1]) : "";
}

export function parseRss(xml, limit = 10) {
  const out = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const b = m[1];
    let t = tag(b, "title");
    const src = tag(b, "source");
    if (src && t.endsWith(" - " + src)) t = t.slice(0, -(src.length + 3)).trim();
    const url = tag(b, "link");
    const d = new Date(tag(b, "pubDate"));
    if (!t || !/^https?:\/\//.test(url) || isNaN(d)) continue;
    out.push({ t, src, url, date: d.toISOString().slice(0, 10) });
    if (out.length >= limit) break;
  }
  return out;
}

async function fetchRss(q, lang, days) {
  const url = "https://news.google.com/rss/search?" + new URLSearchParams({ q: `${q} when:${days}d`, ...EDITIONS[lang] });
  const r = await fetch(url, { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error("upstream " + r.status);
  return parseRss(await r.text(), 50);
}

// 两组结果合并、去重、分类，每类最多 per 条，按日期倒序
export function mergeGroups(groups, per = 6) {
  const seen = new Set();
  const kept = { signal: [], check: [] };
  for (const it of groups.flat()) {
    const key = it.t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim(); // 保留中文，否则中文标题都会变成同一个 key
    if (seen.has(it.url) || seen.has(key)) continue;
    seen.add(it.url); seen.add(key);
    const k = classify(it.t);
    if (k && kept[k].length < per) kept[k].push({ ...it, k });
  }
  return [...kept.signal, ...kept.check].sort((a, b) => b.date.localeCompare(a.date));
}

export async function onRequestGet(context) {
  const u = new URL(context.request.url);
  const q = (u.searchParams.get("q") || "").replace(/\s+/g, " ").trim().slice(0, 120);
  if (q.length < 2) return json({ error: "q is required" }, 400);
  const lang = u.searchParams.get("lang") === "zh" ? "zh" : "en";
  const days = Math.min(365, Math.max(1, parseInt(u.searchParams.get("days"), 10) || 30));
  const impact = u.searchParams.get("impact") !== "0";

  const cache = caches.default;
  const key = new Request("https://cache.internal/search?" + new URLSearchParams({ q: q.toLowerCase(), lang, days, impact: impact ? 2 : 0 }));
  const hit = await cache.match(key);
  if (hit) return hit;

  let items;
  try {
    if (impact) {
      const groups = await Promise.all([
        fetchRss(`${q} ${QUERY.signal[lang]}`, lang, days),
        fetchRss(`${q} ${QUERY.check[lang]}`, lang, days),
      ]);
      items = mergeGroups(groups);
    } else {
      items = (await fetchRss(q, lang, days)).slice(0, 10);
    }
  } catch (e) {
    return json({ error: String(e.message || e) }, 502);
  }

  const resp = json({ q, lang, days, impact, items }, 200, { "Cache-Control": "public, max-age=1800" });
  context.waitUntil(cache.put(key, new Response(resp.clone().body, {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=21600" },
  })));
  return resp;
}
