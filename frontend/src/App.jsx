import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { fetchTranscript, streamArticleGeneration } from "./lib/api";

const EMPTY_TRANSCRIPT = null;
const EMPTY_ARTICLE = null;
const MIN_TEMPERATURE = 0.2;
const MAX_TEMPERATURE = 1.0;
const TEMPERATURE_STEP = 0.1;
const MODEL_OPTIONS = {
  openai: [
    { value: "gpt-5.4", label: "gpt-5.4 (Default)" },
    { value: "gpt-5.4-mini", label: "gpt-5.4-mini" },
    { value: "gpt-5.4-nano", label: "gpt-5.4-nano" },
  ],
  gemini: [
    { value: "gemini-3.1-pro-preview", label: "gemini-3.1-pro-preview" },
    { value: "gemini-3-flash-preview", label: "gemini-3-flash-preview" },
    { value: "gemini-3.1-flash-lite-preview", label: "gemini-3.1-flash-lite-preview" },
  ],
};
const DEFAULT_MODEL = "gpt-5.4";

function getProviderForModel(model) {
  return MODEL_OPTIONS.gemini.some((option) => option.value === model) ? "gemini" : "openai";
}

function getYoutubeUrlValidation(value) {
  if (!value) {
    return { state: "empty", message: "Paste a YouTube URL to get started" };
  }

  try {
    const parsedUrl = new URL(value);
    const hostname = parsedUrl.hostname.replace(/^www\./, "").replace(/^m\./, "");
    const protocol = parsedUrl.protocol.toLowerCase();

    if (!["http:", "https:"].includes(protocol)) {
      return { state: "invalid", message: "Use a supported YouTube URL with http or https." };
    }

    const pathname = parsedUrl.pathname.replace(/\/+$/, "");

    if (hostname === "youtu.be" && pathname.length > 1) {
      return { state: "valid", message: "Supported YouTube URL detected." };
    }

    if (hostname !== "youtube.com") {
      return {
        state: "invalid",
        message: "Enter a supported YouTube watch, short, embed, or youtu.be URL.",
      };
    }

    if (pathname === "/watch" && parsedUrl.searchParams.get("v")) {
      return { state: "valid", message: "Supported YouTube URL detected." };
    }

    if (pathname.startsWith("/shorts/") || pathname.startsWith("/embed/")) {
      return { state: "valid", message: "Supported YouTube URL detected." };
    }

    return {
      state: "invalid",
      message: "Enter a supported YouTube watch, short, embed, or youtu.be URL.",
    };
  } catch {
    return {
      state: "invalid",
      message: "Enter a valid YouTube URL to continue.",
    };
  }
}

function clampTemperature(value) {
  const roundedValue = Math.round(value / TEMPERATURE_STEP) * TEMPERATURE_STEP;
  return Number(Math.min(MAX_TEMPERATURE, Math.max(MIN_TEMPERATURE, roundedValue)).toFixed(1));
}

function getDownloadFilename(article) {
  const markdownPath = article?.markdown_path;
  if (markdownPath) {
    const normalizedPath = String(markdownPath).replaceAll("\\", "/");
    return normalizedPath.split("/").pop() || "generated-article.md";
  }

  const title = article?.title?.trim();
  if (!title) {
    return "generated-article.md";
  }

  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${slug || "generated-article"}.md`;
}

function getTextDownloadFilename(article) {
  return getDownloadFilename(article).replace(/\.md$/i, ".txt");
}

function getTranscriptDownloadFilename(transcript) {
  const videoId = transcript?.video_id?.trim();
  return `${videoId || "youtube"}_cleaned_transcript.txt`;
}

function convertMarkdownToPlainText(markdownContent) {
  return String(markdownContent)
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/_(.*?)_/g, "$1")
    .replace(/`(.*?)`/g, "$1")
    .replace(/^>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "• ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function getArticleMetrics(markdownContent) {
  const plainText = convertMarkdownToPlainText(markdownContent);
  const words = plainText ? plainText.split(/\s+/).filter(Boolean).length : 0;
  const sections = (String(markdownContent).match(/^##\s/gm) || []).length;
  const readingTime = words > 0 ? Math.ceil(words / 200) : 0;

  return {
    words,
    readingTime,
    sections,
  };
}

function formatDuration(secondsMs) {
  return `${(secondsMs / 1000).toFixed(1)}s`;
}

export default function App() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [tone, setTone] = useState("editorial");
  const [temperature, setTemperature] = useState(0.6);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [transcript, setTranscript] = useState(EMPTY_TRANSCRIPT);
  const [article, setArticle] = useState(EMPTY_ARTICLE);
  const [error, setError] = useState("");
  const [isFetchingTranscript, setIsFetchingTranscript] = useState(false);
  const [isGeneratingArticle, setIsGeneratingArticle] = useState(false);
  const [copyState, setCopyState] = useState("Copy Article");
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);
  const trimmedYoutubeUrl = youtubeUrl.trim();
  const urlValidation = getYoutubeUrlValidation(trimmedYoutubeUrl);
  const transcriptLoadedForCurrentUrl = Boolean(
    transcript?.cleaned_text && transcript?.source_url === trimmedYoutubeUrl,
  );
  const provider = getProviderForModel(model);

  const articleCacheLabel = article
    ? article.cached
      ? "Cached"
      : "New"
    : null;
  const articleMetrics = article?.markdown_content
    ? getArticleMetrics(article.markdown_content)
    : null;
  const articlePerformanceLabel = article
    ? article.cached
      ? "Loaded from cache"
      : article.generationTimeMs
        ? `Generated in ${formatDuration(article.generationTimeMs)}`
        : null
    : null;
  const panelStatus = isGeneratingArticle
    ? { label: "Generating", tone: "loading" }
    : isFetchingTranscript
      ? { label: "Fetching", tone: "loading" }
      : { label: "Ready", tone: "ready" };

  function adjustTemperature(direction) {
    setTemperature((currentTemperature) =>
      clampTemperature(currentTemperature + direction * TEMPERATURE_STEP),
    );
  }

  async function handleTranscriptFetch() {
    if (!trimmedYoutubeUrl) {
      setError("Enter a YouTube URL first.");
      return;
    }

    setError("");
    setIsFetchingTranscript(true);

    try {
      const data = await fetchTranscript(trimmedYoutubeUrl);
      setTranscript({
        ...data,
        source_url: trimmedYoutubeUrl,
      });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsFetchingTranscript(false);
    }
  }

  async function handleArticleGeneration() {
    if (!trimmedYoutubeUrl) {
      setError("Enter a YouTube URL first.");
      return;
    }

    setError("");
    setIsGeneratingArticle(true);
    setArticle({
      title: "Generating article...",
      markdown_content: "",
      markdown_path: "",
      saved: false,
      cached: false,
      generationTimeMs: null,
    });
    setCopyState("Copy Article");
    setShowDownloadMenu(false);

    try {
      const generationStartTime = performance.now();

      await streamArticleGeneration({
        youtubeUrl: trimmedYoutubeUrl,
        provider,
        model,
        tone,
        temperature,
      }, {
        onTranscript: (transcriptData) => {
          setTranscript({
            video_id: transcriptData.video_id,
            language: transcriptData.language,
            segment_count: transcriptData.segment_count,
            cleaned_text: transcriptData.cleaned_text,
            source_url: trimmedYoutubeUrl,
          });
        },
        onChunk: ({ delta }) => {
          setArticle((currentArticle) => ({
            title: currentArticle?.title || "Generating article...",
            markdown_content: `${currentArticle?.markdown_content || ""}${delta}`,
            markdown_path: currentArticle?.markdown_path || "",
            saved: false,
            cached: false,
            generationTimeMs: currentArticle?.generationTimeMs || null,
          }));
        },
        onDone: (articleData) => {
          setArticle({
            title: articleData.title,
            markdown_content: articleData.markdown_content,
            markdown_path: articleData.markdown_path,
            saved: articleData.saved,
            cached: articleData.cached,
            generationTimeMs: performance.now() - generationStartTime,
          });
        },
      });
    } catch (requestError) {
      setArticle(EMPTY_ARTICLE);
      setError(requestError.message);
    } finally {
      setIsGeneratingArticle(false);
    }
  }

  async function handleCopyArticle() {
    if (!article?.markdown_content) {
      return;
    }

    try {
      await navigator.clipboard.writeText(article.markdown_content);
      setCopyState("Copied");
      window.setTimeout(() => setCopyState("Copy Article"), 1400);
    } catch {
      setError("Clipboard access failed.");
    }
  }

  function handleDownloadArticle() {
    if (!article?.markdown_content) {
      return;
    }

    const blob = new Blob([article.markdown_content], { type: "text/markdown;charset=utf-8" });
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = getDownloadFilename(article);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    setShowDownloadMenu(false);
  }

  function handleDownloadTextArticle() {
    if (!article?.markdown_content) {
      return;
    }

    const plainTextContent = convertMarkdownToPlainText(article.markdown_content);
    const blob = new Blob([plainTextContent], { type: "text/plain;charset=utf-8" });
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = getTextDownloadFilename(article);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
    setShowDownloadMenu(false);
  }

  function handleDownloadTranscript() {
    if (!transcript?.cleaned_text) {
      return;
    }

    const blob = new Blob([transcript.cleaned_text], { type: "text/plain;charset=utf-8" });
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = getTranscriptDownloadFilename(transcript);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <h1 className="brand-title">
            <span className="brand-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <rect x="2" y="5" width="20" height="14" rx="4" fill="#ff0000" />
                <path d="M10 9.25v5.5l5-2.75-5-2.75Z" fill="#ffffff" />
              </svg>
            </span>
            <span>
              <span className="brand-accent">YouTube</span> Transcript to Article
            </span>
          </h1>
          <p className="brand-subtitle">Readable articles from YouTube transcripts</p>
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <section className="panel controls-panel">
            <div className="panel-heading">
              <div>
                <p className="panel-label">Input</p>
                <h2>Pipeline Controls</h2>
              </div>
              {!error ? (
                <span className={`panel-status ${panelStatus.tone}`}>
                  {panelStatus.label}
                </span>
              ) : null}
            </div>

            <label className="field">
              <span>YouTube URL</span>
              <input
                className={`text-input ${
                  urlValidation.state === "valid"
                    ? "is-valid"
                    : urlValidation.state === "invalid"
                      ? "is-invalid"
                      : ""
                }`}
                type="url"
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                aria-invalid={urlValidation.state === "invalid"}
              />
              <p
                className={`field-helper ${
                  urlValidation.state === "valid"
                    ? "success"
                    : urlValidation.state === "invalid"
                      ? "error"
                      : ""
                }`}
              >
                {urlValidation.state === "valid" ? "✓ " : ""}
                {urlValidation.message}
              </p>
            </label>

            <label className="field">
              <span>Model</span>
              <div className="select-shell">
                <select
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  aria-label="Model"
                >
                  <optgroup label="OpenAI">
                    {MODEL_OPTIONS.openai.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Gemini">
                    {MODEL_OPTIONS.gemini.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </optgroup>
                </select>
                <span className="select-indicator" aria-hidden="true">▼</span>
              </div>
            </label>

            <fieldset className="field tone-field">
              <legend>Tone</legend>
              <div className="tone-options" role="radiogroup" aria-label="Tone">
                <label className={`tone-option${tone === "editorial" ? " selected" : ""}`}>
                  <input
                    type="radio"
                    name="tone"
                    value="editorial"
                    checked={tone === "editorial"}
                    onChange={(event) => setTone(event.target.value)}
                  />
                  <span>Editorial</span>
                </label>
                <label className={`tone-option${tone === "casual" ? " selected" : ""}`}>
                  <input
                    type="radio"
                    name="tone"
                    value="casual"
                    checked={tone === "casual"}
                    onChange={(event) => setTone(event.target.value)}
                  />
                  <span>Casual</span>
                </label>
                <label className={`tone-option${tone === "technical" ? " selected" : ""}`}>
                  <input
                    type="radio"
                    name="tone"
                    value="technical"
                    checked={tone === "technical"}
                    onChange={(event) => setTone(event.target.value)}
                  />
                  <span>Technical</span>
                </label>
              </div>
            </fieldset>

            <div className="advanced-panel">
              <button
                className="advanced-toggle"
                type="button"
                onClick={() => setShowAdvanced((currentValue) => !currentValue)}
                aria-expanded={showAdvanced}
              >
                <span>Advanced</span>
                <span
                  className={`advanced-arrow${showAdvanced ? " open" : ""}`}
                  aria-hidden="true"
                >
                  ▼
                </span>
              </button>

              {showAdvanced ? (
                <div className="advanced-content">
                  <div className="slider-header">
                    <span className="status-label">
                      Temperature ({temperature.toFixed(1)})
                    </span>
                  </div>
                  <div className="slider-row">
                    <button
                      className="stepper-button"
                      type="button"
                      onClick={() => adjustTemperature(-1)}
                      aria-label="Decrease temperature"
                    >
                      ‹
                    </button>
                    <input
                      className="slider"
                      type="range"
                      min="0.2"
                      max="1.0"
                      step="0.1"
                      value={temperature}
                      onChange={(event) => setTemperature(clampTemperature(Number(event.target.value)))}
                    />
                    <button
                      className="stepper-button"
                      type="button"
                      onClick={() => adjustTemperature(1)}
                      aria-label="Increase temperature"
                    >
                      ›
                    </button>
                  </div>
                  <p className="helper-text">
                    Lower = more consistent, higher = more creative
                  </p>
                </div>
              ) : null}
            </div>

            <div className="actions">
              <button
                className="button transcript-button"
                type="button"
                onClick={handleTranscriptFetch}
                disabled={isFetchingTranscript || transcriptLoadedForCurrentUrl}
              >
                {isFetchingTranscript ? (
                  <>
                    <span className="button-spinner" aria-hidden="true" />
                    Fetching...
                  </>
                ) : transcriptLoadedForCurrentUrl ? (
                  "Transcript Loaded"
                ) : (
                  "Fetch Transcript"
                )}
              </button>
              <button
                className="button primary"
                type="button"
                onClick={handleArticleGeneration}
                disabled={isGeneratingArticle}
              >
                {isGeneratingArticle ? (
                  <>
                    <span className="button-spinner" aria-hidden="true" />
                    Generating...
                  </>
                ) : (
                  "Generate Article"
                )}
              </button>
            </div>

            <div className="status-stack">
              {error ? (
                <div className="status-card error-card">
                  <span className="status-label">Request Error</span>
                  <p>{error}</p>
                </div>
              ) : null}
            </div>
          </section>

          <section className="panel transcript-panel">
            <div className="panel-heading compact">
              <div>
                <p className="panel-label">Transcript</p>
                <h2>Info Snapshot</h2>
              </div>
              {transcript?.cleaned_text ? (
                <div className="transcript-header-actions">
                  <button
                    className="action-icon-button"
                    type="button"
                    onClick={handleDownloadTranscript}
                    aria-label="Download cleaned transcript"
                    title="Download transcript"
                    data-tooltip="Download transcript"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path
                      d="M12 4v10"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                    <path
                      d="m8 10 4 4 4-4"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                    <path
                      d="M5 18h14"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeWidth="2"
                    />
                    </svg>
                  </button>
                </div>
              ) : null}
            </div>

            {transcript ? (
              <>
                <dl className="transcript-details">
                  <div className="transcript-row">
                    <dt>Video ID</dt>
                    <dd>{transcript.video_id}</dd>
                  </div>
                  <div className="transcript-row">
                    <dt>Language</dt>
                    <dd>{transcript.language}</dd>
                  </div>
                  <div className="transcript-row">
                    <dt>Segments</dt>
                    <dd>{transcript.segment_count}</dd>
                  </div>
                  <div className="transcript-row">
                    <dt>Status</dt>
                    <dd>{article ? "Article ready" : "Ready"}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <div className="empty-panel">
                <strong>No transcript data yet.</strong>
                <p>Fetch transcript info to inspect the parsed video metadata.</p>
              </div>
            )}
          </section>
        </aside>

        <section className="panel article-panel">
          <div className="panel-heading article-heading">
            <p className="panel-label">Article</p>
            <div className="article-actions">
              <div className="download-menu">
                <button
                  className="action-icon-button"
                  type="button"
                  onClick={() => setShowDownloadMenu((currentValue) => !currentValue)}
                  disabled={!article?.markdown_content}
                  aria-label="Download options"
                  title="Download"
                  data-tooltip="Download"
                  aria-expanded={showDownloadMenu}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M12 4v10"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                    <path
                      d="m8 10 4 4 4-4"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                    <path
                      d="M5 18h14"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeWidth="2"
                    />
                  </svg>
                </button>
                {showDownloadMenu && article?.markdown_content ? (
                  <div className="download-menu-popover">
                    <button
                      className="download-option"
                      type="button"
                      onClick={handleDownloadArticle}
                    >
                      Download .md
                    </button>
                    <button
                      className="download-option"
                      type="button"
                      onClick={handleDownloadTextArticle}
                    >
                      Download .txt
                    </button>
                  </div>
                ) : null}
              </div>
              <button
                className={`copy-icon-button${copyState === "Copied" ? " copied" : ""}`}
                type="button"
                onClick={handleCopyArticle}
                disabled={!article?.markdown_content}
                aria-label={copyState === "Copied" ? "Article copied" : "Copy article markdown"}
                title={copyState === "Copied" ? "Copied" : "Copy article"}
              >
                {copyState === "Copied" ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M20 6 9 17l-5-5"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect
                      x="9"
                      y="9"
                      width="10"
                      height="10"
                      rx="2"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    />
                    <path
                      d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                    />
                  </svg>
                )}
              </button>
              {articleCacheLabel ? (
                <span
                  className={`mini-state cache-state ${
                    article?.cached ? "success-soft" : "accent-soft"
                  }`}
                >
                  {articleCacheLabel}
                </span>
              ) : null}
            </div>
          </div>

          <div className={`article-surface${article ? "" : " article-surface-empty"}`}>
            {article ? (
              <>
                <ReactMarkdown className="markdown-body" remarkPlugins={[remarkGfm]}>
                  {article.markdown_content}
                </ReactMarkdown>
                {articleMetrics ? (
                  <>
                    <div className="article-metrics">
                      Word Count: {articleMetrics.words} | Reading Time: {articleMetrics.readingTime} min | Sections: {articleMetrics.sections}
                    </div>
                    {articlePerformanceLabel ? (
                      <div className="article-performance">{articlePerformanceLabel}</div>
                    ) : null}
                  </>
                ) : null}
              </>
            ) : (
              <div className="empty-panel article-empty">
                <strong>No article generated.</strong>
                <p>
                  Generate an article to review the rendered Markdown output from the backend.
                </p>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
