import React from "react";
import { ExternalLink, MapPin, Video } from "lucide-react";

export const CATEGORY_LABELS = {
  sky: "Sky",
  beach: "Beach",
  coast: "Coast",
  mountain: "Mountain",
  river: "River",
  lake: "Lake",
  lagoon: "Lagoon",
  city: "City",
};

const STATUS_STYLES = {
  online: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  offline: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  unknown: "border-border bg-secondary/40 text-muted-foreground",
};

// Only the two player hosts the backend allowlists may be framed.
const ALLOWED_PLAYER = /^https:\/\/(www\.youtube-nocookie\.com\/embed\/|player\.vimeo\.com\/video\/)[A-Za-z0-9_-]+$/;

export function isAllowedPlayer(url) {
  return typeof url === "string" && ALLOWED_PLAYER.test(url);
}

function Viewer({ camera, showPlayers }) {
  if (showPlayers && isAllowedPlayer(camera.embed_url)) {
    return (
      <iframe
        src={camera.embed_url}
        title={`Live view: ${camera.name}`}
        className="aspect-video w-full rounded-md border-0 bg-black"
        loading="lazy"
        referrerPolicy="strict-origin-when-cross-origin"
        sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
        allowFullScreen
      />
    );
  }
  if (showPlayers && camera.media_url) {
    return (
      <video
        src={camera.media_url}
        controls
        preload="metadata"
        className="aspect-video w-full rounded-md bg-black"
        aria-label={`Video: ${camera.name}`}
      />
    );
  }
  return (
    <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-secondary/20 px-4 text-center">
      <Video className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      <p className="text-xs text-muted-foreground">
        {camera.embed_url || camera.media_url
          ? "Players are off. Open the stream on the owner's page."
          : "The owner has not published an embeddable player. Watch it on their page."}
      </p>
    </div>
  );
}

export default function CameraCard({ camera, showPlayers }) {
  const status = camera.status || "unknown";
  const link = camera.page_url || camera.media_url;
  return (
    <article
      className="flex flex-col gap-3 rounded-xl border border-border bg-card/70 p-3"
      aria-label={camera.name}
      data-testid="sky-camera-card"
    >
      <Viewer camera={camera} showPlayers={showPlayers} />
      <div className="min-w-0 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold leading-snug text-foreground">{camera.name}</h3>
          <span
            className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase ${STATUS_STYLES[status] || STATUS_STYLES.unknown}`}
          >
            {status}
          </span>
        </div>
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          {camera.municipality ? (
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3 w-3" aria-hidden="true" />
              {camera.municipality}
            </span>
          ) : null}
          <span>{camera.provider}</span>
          {camera.contributor ? <span>{`by ${camera.contributor}`}</span> : null}
        </p>
        <ul className="flex flex-wrap gap-1" aria-label="Categories">
          {camera.categories.map((category) => (
            <li key={category} className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {CATEGORY_LABELS[category] || category}
            </li>
          ))}
        </ul>
        {camera.description ? <p className="text-xs text-muted-foreground">{camera.description}</p> : null}
      </div>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
        <span className="font-mono text-[10px] text-muted-foreground">{`checked ${String(camera.checked_at || "").slice(0, 10)}`}</span>
        {link ? (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            {camera.page_url ? "Open live stream" : "Open video"}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
      </div>
    </article>
  );
}
