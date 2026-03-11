---
name: Accessibility Features Plan
overview: A plan to add accessibility features to SmartShift, all surfaced in Settings with explanations. Includes light/dark/contrast mode, font size controls, and keyboard accessibility (skip link, ARIA, landmarks, focus, shortcuts).
todos: []
isProject: false
---

# Accessibility Features for SmartShift

---

## Part 1: Appearance and Theme

### 1.1 Light / Dark / Contrast Mode

- **Theme options**: Light | Dark | System | Contrast (high-contrast variant).
- **Implementation**:
  - Extend [use-dark-mode.tsx](smartshift_2.0/frontend/client/hooks/use-dark-mode.tsx) to `useTheme` with values: `"light" | "dark" | "system" | "contrast"`.
  - Add `.contrast` CSS block in [global.css](smartshift_2.0/frontend/client/global.css) with higher contrast (e.g. darker text, stronger borders).
  - System: use `prefers-color-scheme`; Contrast: use `prefers-contrast: more` if available, else apply custom contrast palette.
- **Storage**: `localStorage` key `smartshift-theme`.
- **UI**: Theme dropdown in App header (compact) and Settings > Appearance section (full).
- **Files**: [use-dark-mode.tsx](smartshift_2.0/frontend/client/hooks/use-dark-mode.tsx) (rename/refactor to `useTheme.tsx`), [global.css](smartshift_2.0/frontend/client/global.css), [AppLayout.tsx](smartshift_2.0/frontend/client/components/AppLayout.tsx), [Settings.tsx](smartshift_2.0/frontend/client/pages/Settings.tsx), [Map.tsx](smartshift_2.0/frontend/client/pages/Map.tsx) (Map has its own header).

### 1.2 Font Size Controls

- **Options**: Small (90%), Default (100%), Large (115%), Extra Large (130%).
- **Implementation**: CSS variable `--font-scale` on `:root`, applied to `html { font-size: calc(1rem * var(--font-scale, 1)); }`.
- **Storage**: `localStorage` key `smartshift-font-size`.
- **Location**: Settings > Appearance.
- **Files**: New `useFontSize` hook, [global.css](smartshift_2.0/frontend/client/global.css), [Settings.tsx](smartshift_2.0/frontend/client/pages/Settings.tsx).

---

## Part 2: Settings UI - Accessibility Section

All accessibility features live in Settings with clear explanations. Add a new **"Accessibility"** section (or merge with **"Appearance"** as **"Appearance & Accessibility"**).

### 2.1 Settings Structure

**Section: Appearance & Accessibility** (or split into "Appearance" + "Accessibility")


| Control                | Explanation (shown in UI)                                                                                                                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Theme**              | "Choose how SmartShift looks. Light and Dark follow your preference; Contrast increases contrast for easier reading."                                                                                             |
| **Font size**          | "Adjust text size across the app. Larger sizes can help reduce eye strain and improve readability."                                                                                                               |
| **Keyboard shortcuts** | Info card + "View shortcuts" button. Text: "SmartShift supports full keyboard navigation. Press Tab to move between elements, Enter/Space to activate. Dialogs close with Escape. Press ? to view all shortcuts." |
| **Skip to content**    | Info card (no control). Text: "When using the keyboard, the first Tab takes you to a 'Skip to content' link that jumps past the navigation to the main content."                                                  |
| **Semantic landmarks** | Info card (no control). Text: "The app uses landmarks (header, navigation, main content) so screen readers can jump between sections quickly."                                                                    |
| **Focus management**   | Info card (no control). Text: "When you open a dialog or panel, focus stays inside it until you close it. Focus is always visible with a clear ring around the active element."                                   |


### 2.2 Implementation Notes

- Each control has a **label** and **description** (muted text below).
- Info-only items (skip link, landmarks, focus) are **expandable cards** or **callout boxes**—no toggle, just explanation.
- "View shortcuts" opens a modal/dialog listing all keyboard shortcuts (e.g. `?` = help, `g` + `d` = Dashboard).

---

## Part 3: Keyboard Accessibility (Implementation)

### 2.1 Skip-to-Content Link

- **Behavior**: First focusable element; on activation, moves focus to `main` content and scrolls into view.
- **Implementation**: Visually hidden (`sr-only`) link at top of layout; on focus, show with `focus:not-sr-only` or similar. Use `#main-content` and `id="main-content"` on main.
- **Files**: [AppLayout.tsx](smartshift_2.0/frontend/client/components/AppLayout.tsx), [Map.tsx](smartshift_2.0/frontend/client/pages/Map.tsx) (Map has its own header, needs its own skip link).

### 2.2 ARIA Labels for Icon-Only Buttons

- **Targets**: Theme toggle, logout, collapse sidebar, play/pause time, any button with only an icon.
- **Implementation**: Add `aria-label` (e.g. `aria-label="Toggle dark mode"`, `aria-label="Sign out"`).
- **Files**: [AppLayout.tsx](smartshift_2.0/frontend/client/components/AppLayout.tsx), [Index.tsx](smartshift_2.0/frontend/client/pages/Index.tsx), [Map.tsx](smartshift_2.0/frontend/client/pages/Map.tsx), [Settings.tsx](smartshift_2.0/frontend/client/pages/Settings.tsx).

### 2.3 Semantic Landmarks

- **Ensure**: `main` with `id="main-content"` for skip target; `nav` with `aria-label="Main navigation"`; `header` where appropriate.
- **Files**: [AppLayout.tsx](smartshift_2.0/frontend/client/components/AppLayout.tsx), [Map.tsx](smartshift_2.0/frontend/client/pages/Map.tsx), page components that use AppLayout.

### 2.4 Focus Management

- **Verify**: All interactive elements are focusable (`tabIndex` where needed; avoid `tabIndex="-1"` on primary actions).
- **Focus trap**: Radix handles dialogs/sheets; verify custom modals (e.g. site popup on Map) trap focus.
- **Focus visibility**: Ensure `focus-visible:ring-2` is applied; consider stronger focus ring for contrast mode.

### 2.5 Global Keyboard Shortcuts (Optional)

- **Examples**: `?` to open shortcuts help; `g` then `d` for Dashboard, `g` then `m` for Map; `Escape` to close overlays (Radix handles this).
- **Implementation**: `useEffect` with `keydown` listener at app level; show shortcuts modal on `?`.
- **Files**: New `useKeyboardShortcuts` hook, [App.tsx](smartshift_2.0/frontend/client/App.tsx) or layout, optional shortcuts dialog component.

---

## Implementation Order

| Phase | Feature                                              | Effort |
| ----- | ---------------------------------------------------- | ------ |
| 1     | Light/Dark/Contrast + Font size (Appearance section) | Medium |
| 2     | Theme toggle in App header and Map header            | Low    |
| 3     | Skip-to-content link                                 | Low    |
| 4     | ARIA labels for icon-only buttons                    | Low    |
| 5     | Semantic landmarks (main, nav)                       | Low    |
| 6     | Global keyboard shortcuts (optional)                 | Medium |
