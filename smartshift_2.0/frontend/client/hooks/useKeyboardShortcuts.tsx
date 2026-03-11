import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";

export function useKeyboardShortcuts() {
  const navigate = useNavigate();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const gPendingRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const clearGPending = () => {
      gPendingRef.current = false;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const inInput = target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      if (inInput && e.key !== "Escape") return;

      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen((o) => !o);
        clearGPending();
        return;
      }

      if (e.key === "Escape") {
        setShortcutsOpen(false);
        clearGPending();
        return;
      }

      if (e.key === "g" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        gPendingRef.current = true;
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        timeoutRef.current = setTimeout(clearGPending, 1500);
        return;
      }

      if (gPendingRef.current && (e.key === "d" || e.key === "m" || e.key === "s")) {
        e.preventDefault();
        clearGPending();
        if (e.key === "d") navigate("/dashboard");
        else if (e.key === "m") navigate("/map");
        else if (e.key === "s") navigate("/settings");
      } else if (gPendingRef.current) {
        clearGPending();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      clearGPending();
    };
  }, [navigate]);

  return { shortcutsOpen, setShortcutsOpen };
}
