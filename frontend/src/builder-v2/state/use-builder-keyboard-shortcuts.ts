"use client";

import { useEffect } from "react";

interface BuilderKeyboardShortcutsOptions {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onCopy?: () => void;
  onPaste?: () => void;
  onDuplicate?: () => void;
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
  onCopy,
  onPaste,
  onDuplicate,
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
        return;
      }

      if (key === "c" && onCopy) {
        event.preventDefault();
        onCopy();
        return;
      }

      if (key === "v" && onPaste) {
        event.preventDefault();
        onPaste();
        return;
      }

      if (key === "d" && onDuplicate) {
        event.preventDefault();
        onDuplicate();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [canRedo, canUndo, onRedo, onUndo, onCopy, onPaste, onDuplicate]);
}