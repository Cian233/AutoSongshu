// ── useChatScroll ────────────────────────────────────────────────
// Migrated from /src/autosongshu_agent/web/static/render.js
//
// Auto-scroll hook for the chat thread container.
// Provides bottom-following behavior that pauses when the user
// scrolls up manually, and resumes when the user scrolls back
// to the bottom.
//
// Key behaviors:
//   - Auto-follow: sticks to the bottom as new messages arrive.
//   - User scroll up: detected via wheel deltaY < 0 or touch drag.
//   - Programmatic scroll guard: ignores user-scroll detection for a
//     short window after a programmatic scroll to avoid false positives.

import { useCallback, useEffect, useRef, useState } from "react";

const AUTOFOLLOW_THRESHOLD_PX = 40;
const TOUCH_RELEASE_DELTA_PX = 8;
const PROGRAMMATIC_SCROLL_GUARD_MS = 180;

function nowMs(): number {
  if (
    typeof window !== "undefined" &&
    window.performance &&
    typeof window.performance.now === "function"
  ) {
    return window.performance.now();
  }
  return Date.now();
}

function isNearBottom(
  el: HTMLElement | null,
  threshold = AUTOFOLLOW_THRESHOLD_PX,
): boolean {
  if (!el) return true;
  return (
    el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
  );
}

interface UseChatScrollOptions {
  /** The session ID currently being viewed.  Resets auto-follow on change. */
  sessionId: string | null;
}

interface UseChatScrollReturn {
  /** Ref to attach to the scrollable container (parent of the thread). */
  scrollContainerRef: React.RefObject<HTMLDivElement>;
  /** Whether the hook thinks we should stick to the bottom. */
  shouldStickToBottom: boolean;
  /** Programmatically scroll to the bottom (sets the guard window). */
  stickToBottom: () => void;
}

export function useChatScroll({
  sessionId,
}: UseChatScrollOptions): UseChatScrollReturn {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [autoFollow, setAutoFollow] = useState(true);
  const programmaticScrollUntilRef = useRef(0);
  const touchStartYRef = useRef<number | null>(null);
  const lastScrollTopRef = useRef(0);
  const prevSessionIdRef = useRef<string>("");

  // Reset auto-follow when session changes
  useEffect(() => {
    const normalized = String(sessionId || "");
    if (prevSessionIdRef.current !== normalized) {
      prevSessionIdRef.current = normalized;
      setAutoFollow(true);
      programmaticScrollUntilRef.current = 0;
      touchStartYRef.current = null;
      const el = scrollContainerRef.current;
      lastScrollTopRef.current = el ? el.scrollTop : 0;
    }
  }, [sessionId]);

  // Bind scroll tracking events
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;

    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < -1) {
        setAutoFollow(false);
      }
    };

    const onTouchStart = (e: TouchEvent) => {
      const touch = e.touches?.[0];
      touchStartYRef.current =
        typeof touch?.clientY === "number" ? touch.clientY : null;
    };

    const onTouchMove = (e: TouchEvent) => {
      const touch = e.touches?.[0];
      const touchY =
        typeof touch?.clientY === "number" ? touch.clientY : null;
      const startY = touchStartYRef.current;
      if (
        touchY !== null &&
        startY !== null &&
        touchY > startY + TOUCH_RELEASE_DELTA_PX
      ) {
        setAutoFollow(false);
      }
    };

    const resetTouch = () => {
      touchStartYRef.current = null;
    };

    const onScroll = () => {
      if (nowMs() < programmaticScrollUntilRef.current) {
        lastScrollTopRef.current = el.scrollTop;
        return;
      }

      if (isNearBottom(el)) {
        setAutoFollow(true);
      } else if (el.scrollTop < lastScrollTopRef.current - 1) {
        setAutoFollow(false);
      }

      lastScrollTopRef.current = el.scrollTop;
    };

    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    el.addEventListener("touchend", resetTouch, { passive: true });
    el.addEventListener("touchcancel", resetTouch, { passive: true });
    el.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", resetTouch);
      el.removeEventListener("touchcancel", resetTouch);
      el.removeEventListener("scroll", onScroll);
    };
  }, [scrollContainerRef]);

  const stickToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    programmaticScrollUntilRef.current =
      nowMs() + PROGRAMMATIC_SCROLL_GUARD_MS;
    el.scrollTo({ top: el.scrollHeight, behavior: "instant" });
    lastScrollTopRef.current = el.scrollTop;
  }, []);

  const shouldStickToBottom = autoFollow;

  return { scrollContainerRef, shouldStickToBottom, stickToBottom };
}
