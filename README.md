# youtube-transcript-cli: YouTube transcripts from the command line

`yt-transcript <link>` prints the transcript of a YouTube video, or saves it as **text, SRT, VTT, Markdown with
time links, or JSON**. It works the same on your laptop, a server or CI, where direct caption requests often get
blocked, because the transcript comes from the [okdata](https://okdata.online/signup/?src=gh-youtube-transcript-cli)
API. One Python file, standard library only, Python 3.9+. $0.004 per video.

## Install

```bash
pipx install git+https://github.com/okdataapi/youtube-transcript-cli
# or just run the file:  python3 yt_transcript.py <link>
```

Get a key at [okdata.online](https://okdata.online/signup/?src=gh-youtube-transcript-cli) and keep it in the
environment, not in scripts you commit:

```bash
export OKDATA_API_KEY=okd_...
```

## Use it

```bash
yt-transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ              # plain text to stdout
yt-transcript https://youtu.be/dQw4w9WgXcQ --format srt -o talk.srt    # subtitles
yt-transcript dQw4w9WgXcQ --lang en --format md                        # Markdown, every line links to its moment
yt-transcript URL1 URL2 URL3 --format txt -o transcripts/              # several videos, one file each
yt-transcript URL1 URL2 --dry-run                                      # what it would cost
```

Accepts `watch?v=` links, `youtu.be` links, Shorts, live and embed links, or bare 11-character ids. Duplicates are
fetched once.

| Option | |
|---|---|
| `--format` | `txt` (default), `srt`, `vtt`, `md`, `json` (segments with start and end in seconds) |
| `--lang` | preferred language, e.g. `en`, `zh`; the original language when left out |
| `-o` | a file for one video, a folder for several |
| `--budget` | refuse runs that could cost more than this many dollars (default 1) |
| `--dry-run` | print the cost and stop; needs no key |

Pipe it into an AI tool: `yt-transcript <link> | llm "summarise in five bullets"`.

## What it costs

[`youtube.videos.transcript.get`](https://okdata.online/apis/youtube/videos/transcript/get/) costs $0.004 per
video; 250 videos cost $1. Failed calls are free. Prices: [prices.json](https://github.com/okdataapi/okdata/blob/main/docs/prices.json).

## Notes

- A sample project by [okdata](https://okdata.online), not affiliated with YouTube or Google. The script only calls
  the okdata API.
- Respect creators: summarise and quote, do not republish whole transcripts.
- In an AI agent? Connect okdata's remote MCP server `https://api.okdata.online/mcp`, or install the
  `okdata-transcripts` skill from [okdataapi/skills](https://github.com/okdataapi/skills).
- Tests: `python3 -m unittest discover -s tests` (a local mock server; no network, no cost).
- Issues and ideas welcome. MIT licence.

---

## 中文

`yt-transcript <链接>` 取 YouTube 视频字幕，输出纯文本、SRT、VTT、带时间跳转链接的 Markdown 或 JSON。
服务器和 CI 上也能用（直接请求字幕经常被拦），因为字幕来自 okdata 的接口。每个视频 $0.004，失败不扣钱。
在 [okdata](https://okdata.online/zh/signup/?src=gh-youtube-transcript-cli) 注册拿 key，放进 `OKDATA_API_KEY` 即可。MIT 许可证。
