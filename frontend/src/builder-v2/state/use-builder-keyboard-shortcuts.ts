"use client";

import { useEffect } from "react";

interface BuilderKeyboardShortcutsOptions {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  if (target.isContentEditable) {
    return true;
  }

  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select";
}

export function useBuilderKeyboardShortcuts({
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}: BuilderKeyboardShortcutsOptions) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || isEditableTarget(event.target)) {
        return;
      }

      const isPrimaryModifier = event.metaKey || event.ctrlKey;
      if (!isPrimaryModifier) {
        return;
      }

      const key = event.key.toLowerCase();
      const isUndoShortcut = key === "z" && !event.shiftKey;
      const isRedoShortcut = (key === "z" && event.shiftKey) || key === "y";

      if (isUndoShortcut && canUndo) {
        event.preventDefault();
        onUndo();
        return;
      }

      if (isRedoShortcut && canRedo) {
        event.preventDefault();
        onRedo();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [canRedo, canUndo, onRedo, onUndo]);
}