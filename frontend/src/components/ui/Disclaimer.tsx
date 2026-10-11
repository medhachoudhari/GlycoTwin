import { DISCLAIMER } from "../../lib/config";

/** The investigational-use disclaimer, verbatim. `bar` is the persistent strip shown on every dashboard screen. */
export function Disclaimer({ variant = "bar" }: { variant?: "bar" | "block" }) {
  return (
    <p className={`disclaimer disclaimer-${variant}`} role="note" data-testid="disclaimer">
      <span className="eyebrow" aria-hidden="true">Research prototype</span>
      <span>{DISCLAIMER}</span>
    </p>
  );
}
