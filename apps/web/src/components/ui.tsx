import { ComponentProps, PropsWithChildren } from "react";

type ButtonProps = PropsWithChildren<
  ComponentProps<"button"> & {
    variant?: "primary" | "secondary" | "ghost" | "danger";
  }
>;

export function Button({ variant = "primary", children, className = "", ...rest }: ButtonProps) {
  return (
    <button className={`btn btn-${variant} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Card({ title, children }: PropsWithChildren<{ title: string }>) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
      </div>
      <div className="card-body">{children}</div>
    </div>
  );
}

export function Chip({ tone = "neutral", children }: PropsWithChildren<{ tone?: "neutral" | "info" | "success" | "danger" | "muted" }>) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

export function Input(props: ComponentProps<"input">) {
  return <input className="input" {...props} />;
}

export function TextArea(props: ComponentProps<"textarea">) {
  return <textarea className="textarea" {...props} />;
}
