// ── Debounce Hook ───────────────────────────────────────────────
// A generic debounce hook for delaying value updates.
// Useful for search inputs, auto-save, and other scenarios where
// rapid updates should be coalesced.

import { useState, useEffect, useRef } from "react";

/**
 * Debounce a value by a specified delay.
 *
 * @param value   - The value to debounce.
 * @param delay   - Delay in milliseconds (default: 300).
 * @returns The debounced value that only updates after the delay.
 *
 * @example
 * ```tsx
 * const [search, setSearch] = useState("");
 * const debouncedSearch = useDebounce(search, 300);
 *
 * useEffect(() => {
 *   // This only fires 300ms after the user stops typing
 *   performSearch(debouncedSearch);
 * }, [debouncedSearch]);
 * ```
 */
export function useDebounce<T>(value: T, delay: number = 300): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delay]);

  return debouncedValue;
}

/**
 * Hook that returns a debounced version of a callback function.
 * The callback is only invoked after the specified delay has elapsed
 * since the last call.
 *
 * @param callback - The function to debounce.
 * @param delay    - Delay in milliseconds (default: 300).
 * @returns A debounced version of the callback.
 *
 * @example
 * ```tsx
 * const debouncedSave = useDebouncedCallback(saveDraft, 500);
 *
 * <input onChange={(e) => {
 *   setContent(e.target.value);
 *   debouncedSave(content);
 * }} />
 * ```
 */
export function useDebouncedCallback<T extends (...args: unknown[]) => void>(
  callback: T,
  delay: number = 300,
): T {
  const callbackRef = useRef(callback);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep the callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  return ((...args: unknown[]) => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      callbackRef.current(...args);
    }, delay);
  }) as T;
}
