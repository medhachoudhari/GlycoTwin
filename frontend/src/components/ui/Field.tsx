import { useId, type InputHTMLAttributes } from "react";

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  label: string; value: string; onChange: (v: string) => void; hint?: string; error?: string | null; unit?: string;
}
export function Field({ label, value, onChange, hint, error, unit, id, ...rest }: Props) {
  const auto = useId();
  const fid = id ?? auto;
  const describedBy = [hint ? `${fid}-h` : "", error ? `${fid}-e` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}{unit && <span className="unit"> ({unit})</span>}</label>
      <input id={fid} className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...rest} />
      {hint && <span className="hint" id={`${fid}-h`}>{hint}</span>}
      {error && <span className="err" id={`${fid}-e`}>{error}</span>}
    </div>
  );
}

/** Parses a numeric text field; returns an error text instead of letting NaN reach the API. */
export function parseNumber(text: string, label: string, min: number, max: number, required = true): { value: number | undefined; error: string | null } {
  const t = text.trim();
  if (t === "") return required ? { value: undefined, error: `${label} is required.` } : { value: undefined, error: null };
  const v = Number(t);
  if (!Number.isFinite(v)) return { value: undefined, error: `${label} must be a number.` };
  if (v < min || v > max) return { value: undefined, error: `${label} must be between ${min} and ${max}.` };
  return { value: v, error: null };
}
