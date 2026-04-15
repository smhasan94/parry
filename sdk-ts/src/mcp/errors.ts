/**
 * Exceptions raised by the Parry MCP wrapper.
 */

export interface MCPDetection {
  detector?: string;
  severity?: string;
  reason?: string;
  [key: string]: unknown;
}

export class MCPBlockedError extends Error {
  readonly reason: string;
  readonly detections: MCPDetection[];
  readonly serverUri: string | undefined;

  constructor(
    reason: string,
    options?: { detections?: MCPDetection[]; serverUri?: string }
  ) {
    super(reason);
    this.name = "MCPBlockedError";
    this.reason = reason;
    this.detections = options?.detections ?? [];
    this.serverUri = options?.serverUri;
    Object.setPrototypeOf(this, MCPBlockedError.prototype);
  }
}

export class MCPManifestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MCPManifestError";
    Object.setPrototypeOf(this, MCPManifestError.prototype);
  }
}
