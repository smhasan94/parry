/**
 * Raised when the Parry proxy blocks an LLM call due to a threat detection.
 *
 * Catch this in your agent code to handle policy blocks:
 * ```ts
 * try {
 *   const response = await openai.chat.completions.create(...)
 * } catch (e) {
 *   if (e instanceof ParryBlockedError) {
 *     console.log(`Blocked by ${e.detector}: ${e.reason}`)
 *   }
 * }
 * ```
 */
export class ParryBlockedError extends Error {
  readonly reason: string;
  readonly detector: string;
  readonly severity: string;
  readonly confidence: number;

  constructor(opts: {
    reason: string;
    detector: string;
    severity: string;
    confidence: number;
  }) {
    super(`Parry blocked this call: [${opts.detector}] ${opts.reason}`);
    this.name = "ParryBlockedError";
    this.reason = opts.reason;
    this.detector = opts.detector;
    this.severity = opts.severity;
    this.confidence = opts.confidence;
  }
}

/**
 * Raised when an agent's tool call is denied by a permission boundary.
 *
 * Subclass of ParryBlockedError so `catch (e instanceof ParryBlockedError)`
 * still works, but you can distinguish permission denials:
 * ```ts
 * catch (e) {
 *   if (e instanceof ParryPermissionDeniedError) {
 *     console.log(`Not authorized: ${e.toolName}`)
 *   }
 * }
 * ```
 */
export class ParryPermissionDeniedError extends ParryBlockedError {
  readonly toolName: string | null;

  constructor(opts: { reason: string; toolName?: string }) {
    super({
      reason: opts.reason,
      detector: "permission_boundary",
      severity: "high",
      confidence: 1.0,
    });
    this.name = "ParryPermissionDeniedError";
    this.toolName = opts.toolName ?? null;
  }
}
