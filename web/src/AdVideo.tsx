import { useEffect, useRef, useState } from "react";
import "./AdVideo.css";

export type AdVideoProps = {
  src?: string;
  /** Alternative encodings of the same video, such as the public SD source. */
  sources?: string[];
  poster?: string;
  adUrl?: string;
  label?: string;
};

export function safeMediaUrl(value?: string): string | undefined {
  try {
    const url = new URL(value ?? "");
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function VideoPlayer({
  urls,
  poster,
  adUrl,
  label,
}: {
  urls: string[];
  poster?: string;
  adUrl?: string;
  label: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [sourceIndex, setSourceIndex] = useState(0);
  const [posterFailed, setPosterFailed] = useState(false);
  const unavailable = urls.length === 0;
  const failed = !unavailable && sourceIndex >= urls.length;
  const src = urls[sourceIndex];

  useEffect(() => {
    const video = videoRef.current;
    return () => {
      // Keep the captured node: React may clear the ref before cleanup runs.
      video?.pause();
    };
  }, [src]);

  return (
    <div className="ad-video">
      {!unavailable && !failed ? (
        <video
          key={src}
          ref={videoRef}
          src={src}
          poster={poster}
          controls
          playsInline
          preload="metadata"
          aria-label={label}
          onError={() => setSourceIndex((index) => index + 1)}
        />
      ) : (
        <div className="ad-video-fallback" role="status">
          {poster && !posterFailed && (
            <img
              src={poster}
              alt="Video preview"
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={() => setPosterFailed(true)}
            />
          )}
          <div className="ad-video-message">
            <strong>
              {failed ? "Video could not be played" : "Video unavailable"}
            </strong>
            <p>
              {failed
                ? "The video may have expired or could not be loaded."
                : poster
                  ? "Only a preview image was available for this video."
                  : "No playable video was available from the public ad."}
            </p>
            {failed && (
              <button onClick={() => setSourceIndex(0)}>Retry video</button>
            )}
            {adUrl && (
              <a href={adUrl} target="_blank" rel="noreferrer">
                Open original ad
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AdVideo({
  src,
  sources = [],
  poster,
  adUrl,
  label = "Ad video",
}: AdVideoProps) {
  const urls = [
    ...new Set([src, ...sources].map(safeMediaUrl).filter(Boolean)),
  ] as string[];
  const safePoster = safeMediaUrl(poster);
  return (
    <VideoPlayer
      key={JSON.stringify([urls, safePoster])}
      urls={urls}
      poster={safePoster}
      adUrl={safeMediaUrl(adUrl)}
      label={label}
    />
  );
}
