// Package parry provides the Parry SDK for Go — AI Agent Runtime Security.
//
// Parry sits between AI agents and the LLMs they call, detecting prompt
// injection, tool misuse, and anomalous behavior in real time.
package parry

import "fmt"

// ParryBlockedError is returned when the Parry proxy blocks an LLM call
// due to a threat detection.
type ParryBlockedError struct {
	Reason     string  `json:"reason"`
	Detector   string  `json:"detector"`
	Severity   string  `json:"severity"`
	Confidence float64 `json:"confidence"`
}

func (e *ParryBlockedError) Error() string {
	return fmt.Sprintf("parry blocked this call: [%s] %s", e.Detector, e.Reason)
}

// ParryPermissionDeniedError is returned when an agent's tool call is
// denied by a permission boundary. It wraps ParryBlockedError so type
// assertions on *ParryBlockedError still work via errors.As.
type ParryPermissionDeniedError struct {
	ParryBlockedError
	ToolName string `json:"tool_name"`
}

func (e *ParryPermissionDeniedError) Error() string {
	if e.ToolName != "" {
		return fmt.Sprintf("parry permission denied: tool '%s' — %s", e.ToolName, e.Reason)
	}
	return fmt.Sprintf("parry permission denied: %s", e.Reason)
}

// Unwrap allows errors.As to match *ParryBlockedError.
func (e *ParryPermissionDeniedError) Unwrap() error {
	return &e.ParryBlockedError
}
