"use client";

import { useEffect, useState } from "react";

/**
 * True after the first client render.
 *
 * Every panel here renders store state and locale-formatted timestamps, none of
 * which exist during prerender, so the tree is only painted once the browser
 * owns it. That keeps the markup stable instead of hydrating over placeholder
 * text.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
