"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, wsUrl } from "./api";

/**
 * Subscribe to the API's change feed over the WebSocket and refetch on change.
 *
 * The store's change feed is what drives the agent loop, so the dashboard learns
 * about a new decision the same way the agents do (spec section 6.2). A slow
 * poll runs alongside it purely as a reconnect safety net.
 */
export function useLive<T>(path: string, intervalMs = 4000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef(false);

  const refresh = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      setData(await getJson<T>(path));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      inflight.current = false;
    }
  }, [path]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [refresh, intervalMs]);

  useEffect(() => {
    const unsubscribe = subscribe(() => void refresh());
    return unsubscribe;
  }, [refresh]);

  return { data, error, refresh };
}

type Listener = (message: ChangeMessage) => void;

export interface ChangeMessage {
  kind: string;
  collection?: string;
  operation?: string;
  document?: Record<string, unknown>;
  system?: unknown;
}

let socket: WebSocket | null = null;
let retry: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<Listener>();

function connect() {
  if (typeof window === "undefined" || socket) return;
  socket = new WebSocket(wsUrl());
  socket.onmessage = (event) => {
    let message: ChangeMessage;
    try {
      message = JSON.parse(event.data as string) as ChangeMessage;
    } catch {
      return;
    }
    listeners.forEach((listener) => listener(message));
  };
  const reconnect = () => {
    socket = null;
    if (listeners.size && !retry) {
      retry = setTimeout(() => {
        retry = null;
        connect();
      }, 1500);
    }
  };
  socket.onclose = reconnect;
  socket.onerror = reconnect;
}

/** Register a change-feed listener. Returns the unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  connect();
  return () => {
    listeners.delete(listener);
    if (!listeners.size && socket) {
      socket.close();
      socket = null;
    }
  };
}

/** Live connection state, for the header indicator. */
export function useFeedStatus() {
  const [connected, setConnected] = useState(false);
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  useEffect(() => {
    const unsubscribe = subscribe(() => {
      setConnected(true);
      setLastMessageAt(Date.now());
    });
    const timer = setInterval(() => {
      setConnected(socket?.readyState === WebSocket.OPEN);
    }, 1000);
    return () => {
      unsubscribe();
      clearInterval(timer);
    };
  }, []);
  return { connected, lastMessageAt };
}
