// CaptionBox.tsx — the draggable / resizable caption region (P4 §4 position editor).
//
// A controlled overlay placed inside a relatively-positioned preview frame (over
// the Player). The user drags the box body to MOVE the caption region and drags
// a handle to RESIZE it; the geometry is normalised (fractions of the frame) so
// it maps 1:1 onto the 1080x1920 export. All math is the pure
// `lib/captionPosition` helpers — this component only converts pointer pixels to
// fractional deltas against the measured frame and forwards onChange.
//
// `children` render INSIDE the box (the live caption sample), so what the user
// drags is exactly what the caption will look like on the video.
import React, { useRef } from 'react';
import {
  type CaptionBox as Box,
  type ResizeHandle,
  RESIZE_HANDLES,
  boxToCss,
  moveBox,
  resizeBox,
} from '../lib/captionPosition';
import './captionBox.css';

export interface CaptionBoxProps {
  /** The normalised caption box (parent-owned). */
  box: Box;
  /** Called with the next box on every drag/resize step. */
  onChange: (box: Box) => void;
  /** The live caption sample rendered inside the box. */
  children?: React.ReactNode;
  /** Read-only preview (no drag/resize) when true. */
  disabled?: boolean;
  /** Accessible label for the editor region. */
  label?: string;
}

/** Active drag state (null when idle). `handle` null = move the whole box. */
interface DragState {
  handle: ResizeHandle | null;
  startX: number;
  startY: number;
  startBox: Box;
  /** The element that captured the pointer (released on pointer-up). */
  el: Element;
  pointerId: number;
}

/** Fractional delta of a pointer move against the frame size (0 when unmeasured). */
function frac(deltaPx: number, sizePx: number): number {
  return sizePx > 0 ? deltaPx / sizePx : 0;
}

/** One keyboard nudge = 2% of the frame (WCAG 2.1.1 keyboard operability). */
const KEY_STEP = 0.02;

/** Fractional {dx,dy} for an arrow key, or null for any other key. */
function arrowDelta(key: string): { dx: number; dy: number } | null {
  switch (key) {
    case 'ArrowLeft':
      return { dx: -KEY_STEP, dy: 0 };
    case 'ArrowRight':
      return { dx: KEY_STEP, dy: 0 };
    case 'ArrowUp':
      return { dx: 0, dy: -KEY_STEP };
    case 'ArrowDown':
      return { dx: 0, dy: KEY_STEP };
    default:
      return null;
  }
}

export function CaptionBox({
  box,
  onChange,
  children,
  disabled = false,
  label = 'Caption position',
}: CaptionBoxProps): React.ReactElement {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<DragState | null>(null);

  const begin =
    (handle: ResizeHandle | null) =>
    (e: React.PointerEvent): void => {
      if (disabled) return;
      e.preventDefault();
      e.stopPropagation();
      drag.current = {
        handle,
        startX: e.clientX,
        startY: e.clientY,
        startBox: box,
        el: e.currentTarget,
        pointerId: e.pointerId,
      };
      // setPointerCapture is absent in jsdom — guard so tests + real Chromium both run.
      e.currentTarget.setPointerCapture?.(e.pointerId);
    };

  const onPointerMove = (e: React.PointerEvent): void => {
    const d = drag.current;
    if (!d) return;
    const frame = frameRef.current;
    // The frame is the element receiving this move, so it is always mounted here.
    /* v8 ignore next -- runtime-only guard; frameRef is set whenever a drag is active */
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const dx = frac(e.clientX - d.startX, rect.width);
    const dy = frac(e.clientY - d.startY, rect.height);
    onChange(d.handle ? resizeBox(d.startBox, d.handle, dx, dy) : moveBox(d.startBox, dx, dy));
  };

  const onPointerUp = (): void => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    d.el.releasePointerCapture?.(d.pointerId);
  };

  // Keyboard operability (WCAG 2.1.1, bug-sweep fix): arrow keys MOVE the box from
  // the body and RESIZE from a focused handle, mirroring the pointer drag. Guarded
  // on `disabled` exactly like the pointer path.
  const onBoxKeyDown = (e: React.KeyboardEvent): void => {
    if (disabled) return;
    const d = arrowDelta(e.key);
    if (!d) return;
    e.preventDefault();
    onChange(moveBox(box, d.dx, d.dy));
  };

  // Handles only render when NOT disabled, so no `disabled` guard is needed here.
  const onHandleKeyDown =
    (handle: ResizeHandle) =>
    (e: React.KeyboardEvent): void => {
      const d = arrowDelta(e.key);
      if (!d) return;
      e.preventDefault();
      e.stopPropagation();
      onChange(resizeBox(box, handle, d.dx, d.dy));
    };

  return (
    <div
      className="caption-box-frame"
      ref={frameRef}
      role="group"
      aria-label={label}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div
        className={`caption-box${disabled ? ' is-readonly' : ''}`}
        style={boxToCss(box)}
        data-testid="caption-box"
        role="application"
        aria-label="Caption region — arrow keys move; Tab to a handle then arrow keys to resize"
        tabIndex={disabled ? undefined : 0}
        onPointerDown={begin(null)}
        onKeyDown={onBoxKeyDown}
      >
        <div className="caption-box__content">{children}</div>
        {!disabled &&
          RESIZE_HANDLES.map((h) => (
            <span
              key={h}
              className={`caption-box__handle caption-box__handle--${h}`}
              data-handle={h}
              role="button"
              aria-label={`Resize ${h}`}
              tabIndex={0}
              onPointerDown={begin(h)}
              onKeyDown={onHandleKeyDown(h)}
            />
          ))}
      </div>
    </div>
  );
}

export default CaptionBox;
