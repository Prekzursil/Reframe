// DeviceStatusStrip.tsx — a compact device + per-job ETA status strip
// (WU-models/device, deliverable G — "device+ETA status strip"). Shows, at a
// glance, the four headroom facts a user weighs before a run — FREE DISK, RAM,
// VRAM, GPU — plus the live per-job ETA when a job is running. Pure presentation:
// the hardware comes from system.probe and the ETA is passed in by the host.
import React from 'react';
import type { HardwareInfo } from '../lib/rpc';
import { fmtMb, fmtMbOrUnknown } from './advisorMeta';

/** Format an ETA (seconds) as "m:ss", or "—" when there is no running job. */
export function formatEta(etaSeconds: number | null | undefined): string {
  if (
    etaSeconds === null ||
    etaSeconds === undefined ||
    !Number.isFinite(etaSeconds) ||
    etaSeconds < 0
  ) {
    return '—';
  }
  const total = Math.round(etaSeconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export interface DeviceStatusStripProps {
  /** Probed hardware (system.probe). Any field null when undetectable. */
  hardware: HardwareInfo;
  /** Live ETA for the active job in seconds, or null/undefined when idle. */
  etaSeconds?: number | null;
}

interface Chip {
  key: string;
  label: string;
  value: string;
}

/** Build the ordered chip list (exported so the chip logic is unit-tested). */
export function deviceChips(hardware: HardwareInfo, etaSeconds: number | null | undefined): Chip[] {
  return [
    { key: 'disk', label: 'Free disk', value: fmtMb(hardware.diskFreeMb ?? null) },
    { key: 'ram', label: 'RAM', value: fmtMbOrUnknown(hardware.ramMb) },
    { key: 'vram', label: 'VRAM', value: fmtMb(hardware.vramMb) },
    { key: 'gpu', label: 'GPU', value: hardware.gpuPresent ? 'yes' : 'none' },
    { key: 'eta', label: 'ETA', value: formatEta(etaSeconds) },
  ];
}

export function DeviceStatusStrip({
  hardware,
  etaSeconds,
}: DeviceStatusStripProps): React.ReactElement {
  const chips = deviceChips(hardware, etaSeconds);
  return (
    <div
      className="device-strip"
      data-section="device-strip"
      role="group"
      aria-label="Device status"
    >
      {chips.map((chip) => (
        <span key={chip.key} className="device-strip__chip" data-chip={chip.key}>
          <span className="device-strip__label">{chip.label}</span>
          <span className="device-strip__value">{chip.value}</span>
        </span>
      ))}
    </div>
  );
}

export default DeviceStatusStrip;
