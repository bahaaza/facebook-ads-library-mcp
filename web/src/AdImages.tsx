import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  ImageOff,
  LayoutGrid,
  X,
} from "lucide-react";
import "./AdImages.css";

export type ImageCreative = {
  creative_image?: string;
  creative_images?: string[];
  variants?: ImageCreative[];
};

function imageUrl(value: unknown): string {
  if (typeof value !== "string") return "";
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

/** Older saved ads and structured variants share the same image viewer. */
export function collectAdImages(data: ImageCreative): string[] {
  const images = new Set<string>();
  const add = (creative: ImageCreative) => {
    const values = [creative.creative_image];
    if (Array.isArray(creative.creative_images))
      values.push(...creative.creative_images);
    for (const value of values) {
      const url = imageUrl(value);
      if (url) images.add(url);
    }
  };
  add(data);
  if (Array.isArray(data.variants)) {
    for (const variant of data.variants) {
      if (variant && typeof variant === "object") add(variant);
    }
  }
  return [...images];
}

function CreativeImage({
  src,
  alt,
  preview = false,
}: {
  src: string;
  alt: string;
  preview?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span className="ad-image-unavailable">
        <ImageOff size={28} />
        Image unavailable
      </span>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      loading={preview ? "lazy" : "eager"}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function ImageViewer({
  images,
  initialIndex,
  label,
  originalAdUrl,
  onClose,
  returnFocus,
}: {
  images: string[];
  initialIndex: number;
  label: string;
  originalAdUrl: string;
  onClose: () => void;
  returnFocus: HTMLElement | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [slide, setIndex] = useState(initialIndex);
  const index = Math.min(slide, images.length - 1);
  const move = (direction: number) =>
    setIndex(
      (current) => (current + direction + images.length) % images.length,
    );

  useEffect(() => {
    const element = dialog.current!;
    const overflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, [returnFocus]);

  return createPortal(
    <dialog
      ref={dialog}
      className="ad-image-viewer"
      aria-label={`${label} image viewer`}
      aria-modal="true"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          event.stopPropagation();
          move(event.key === "ArrowLeft" ? -1 : 1);
        } else if (event.key === "Tab") {
          const controls =
            dialog.current!.querySelectorAll<HTMLElement>("button, a[href]");
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
      }}
    >
      <div className="ad-image-viewer-header">
        <strong>{label}</strong>
        <button
          type="button"
          aria-label="Close image viewer"
          onClick={onClose}
          autoFocus
        >
          <X size={20} />
        </button>
      </div>
      <div className="ad-image-stage">
        <CreativeImage
          key={images[index]}
          src={images[index]}
          alt={`${label}, image ${index + 1} of ${images.length}`}
        />
      </div>
      <div className="ad-image-controls">
        {images.length > 1 && (
          <button
            type="button"
            aria-label="Previous image"
            onClick={() => move(-1)}
          >
            <ChevronLeft size={20} />
          </button>
        )}
        <span role="status" aria-live="polite" aria-atomic="true">
          Image {index + 1} of {images.length}
        </span>
        {images.length > 1 && (
          <button type="button" aria-label="Next image" onClick={() => move(1)}>
            <ChevronRight size={20} />
          </button>
        )}
      </div>
      {originalAdUrl && (
        <a
          className="ad-image-original"
          href={originalAdUrl}
          target="_blank"
          rel="noreferrer"
        >
          Open original ad <ExternalLink size={14} />
        </a>
      )}
    </dialog>,
    document.body,
  );
}

export function AdImages({
  data,
  originalAdUrl,
  label = "Ad creative",
  cover = false,
  onEmpty,
  children,
}: {
  data: ImageCreative;
  originalAdUrl?: string;
  label?: string;
  cover?: boolean;
  onEmpty?: () => void;
  children?: ReactNode;
}) {
  const images = collectAdImages(data);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const close = useCallback(() => setOpenIndex(null), []);
  const original = imageUrl(originalAdUrl);
  const open = (index: number, element: HTMLElement) => {
    trigger.current = element;
    setOpenIndex(index);
  };
  if (!images.length) {
    return cover ? (
      <button
        type="button"
        className="creative"
        onClick={onEmpty}
        aria-label={`View details for ${label}`}
      >
        <span className="creative-fallback">
          <LayoutGrid size={30} />
          <span>View creative in Ad Library</span>
        </span>
        {children}
      </button>
    ) : null;
  }
  return (
    <>
      {cover ? (
        <button
          type="button"
          className="creative ad-images-cover"
          aria-label={`View ${images.length === 1 ? "image" : `${images.length} images`} for ${label}`}
          onClick={(event) => open(0, event.currentTarget)}
        >
          <CreativeImage key={images[0]} src={images[0]} alt={label} preview />
          <span className="ad-image-count">
            {images.length === 1 ? "View image" : `${images.length} images`}
          </span>
          {children}
        </button>
      ) : (
        <div className="ad-image-collection" aria-label={`${label} images`}>
          {images.map((src, index) => (
            <button
              type="button"
              key={src}
              aria-label={`View image ${index + 1} of ${images.length} for ${label}`}
              onClick={(event) => open(index, event.currentTarget)}
            >
              <CreativeImage
                src={src}
                alt={`${label}, image ${index + 1}`}
                preview
              />
            </button>
          ))}
        </div>
      )}
      {openIndex !== null && (
        <ImageViewer
          images={images}
          initialIndex={openIndex}
          label={label}
          originalAdUrl={original}
          onClose={close}
          returnFocus={trigger.current}
        />
      )}
    </>
  );
}
