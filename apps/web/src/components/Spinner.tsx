import { PropsWithChildren } from "react";

export function Spinner({ label }: PropsWithChildren<{ label?: string }>) {
  return (
    <div className="spinner">
      <div className="spinner-dot" />
      <div className="spinner-dot" />
      <div className="spinner-dot" />
      {label && <span className="spinner-label">{label}</span>}
    </div>
  );
}
