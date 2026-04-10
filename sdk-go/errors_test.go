package parry

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"testing"
)

func TestParryBlockedError_Message(t *testing.T) {
	err := &ParryBlockedError{
		Reason:   "Injection detected",
		Detector: "prompt_injection",
		Severity: "high",
		Confidence: 0.92,
	}
	msg := err.Error()
	if msg == "" {
		t.Fatal("expected non-empty message")
	}
	if !contains(msg, "prompt_injection") {
		t.Errorf("expected message to contain detector, got %s", msg)
	}
}

func TestParryBlockedError_IsError(t *testing.T) {
	var err error = &ParryBlockedError{
		Reason: "test", Detector: "test", Severity: "low", Confidence: 0.5,
	}
	if err == nil {
		t.Fatal("expected non-nil error")
	}
}

func TestParryPermissionDeniedError_Message(t *testing.T) {
	err := &ParryPermissionDeniedError{
		ParryBlockedError: ParryBlockedError{
			Reason: "Blocked", Detector: "permission_boundary",
			Severity: "high", Confidence: 1.0,
		},
		ToolName: "delete_account",
	}
	msg := err.Error()
	if !contains(msg, "delete_account") {
		t.Errorf("expected tool name in message, got %s", msg)
	}
}

func TestParryPermissionDeniedError_Unwrap(t *testing.T) {
	err := &ParryPermissionDeniedError{
		ParryBlockedError: ParryBlockedError{
			Reason: "test", Detector: "permission_boundary",
			Severity: "high", Confidence: 1.0,
		},
	}
	var blocked *ParryBlockedError
	if !errors.As(err, &blocked) {
		t.Fatal("expected Unwrap to match ParryBlockedError")
	}
}

func TestParryPermissionDeniedError_EmptyToolName(t *testing.T) {
	err := &ParryPermissionDeniedError{
		ParryBlockedError: ParryBlockedError{
			Reason: "Denied", Detector: "permission_boundary",
			Severity: "high", Confidence: 1.0,
		},
	}
	msg := err.Error()
	if contains(msg, "''") {
		t.Errorf("expected no empty quotes in message, got %s", msg)
	}
}

func TestVerifyWebhookSignature_Valid(t *testing.T) {
	payload := []byte(`{"event":"test"}`)
	secret := "whsec_abc123"

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(payload)
	sig := hex.EncodeToString(mac.Sum(nil))

	if !VerifyWebhookSignature(payload, secret, sig) {
		t.Fatal("expected valid signature")
	}
}

func TestVerifyWebhookSignature_Invalid(t *testing.T) {
	if VerifyWebhookSignature([]byte("test"), "secret", "wrong") {
		t.Fatal("expected invalid signature")
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsHelper(s, substr))
}

func containsHelper(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
