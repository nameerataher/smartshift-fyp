import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";

export function KeyboardShortcutsModal() {
  const { shortcutsOpen, setShortcutsOpen } = useKeyboardShortcuts();

  if (!shortcutsOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={() => setShortcutsOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-modal-title">
      <div
        className="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="shortcuts-modal-title" className="text-xl font-semibold text-foreground mb-4">
          Keyboard shortcuts
        </h2>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">?</kbd> — View shortcuts
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Tab</kbd> — Move between elements
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Enter</kbd> /{" "}
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Space</kbd> — Activate
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Escape</kbd> — Close dialog
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then{" "}
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">d</kbd> — Go to Dashboard
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then{" "}
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">m</kbd> — Go to Map
          </li>
          <li>
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then{" "}
            <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">s</kbd> — Go to Settings
          </li>
        </ul>
        <button
          onClick={() => setShortcutsOpen(false)}
          className="mt-4 w-full py-2 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          Close
        </button>
      </div>
    </div>
  );
}
