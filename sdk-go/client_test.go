package parry

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCheckBeforeCall_Allowed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(proxyCheckResponse{
			Allowed: true, Reason: "", Detector: "", Confidence: 0,
		})
	}))
	defer srv.Close()

	c := NewClient("sk-test", WithBaseURL(srv.URL))
	err := c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "hello"})
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
}

func TestCheckBeforeCall_Blocked(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sev := "high"
		json.NewEncoder(w).Encode(proxyCheckResponse{
			Allowed: false, Reason: "Injection detected", Detector: "prompt_injection",
			Severity: &sev, Confidence: 0.95,
		})
	}))
	defer srv.Close()

	c := NewClient("sk-test", WithBaseURL(srv.URL))
	err := c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "evil"})
	if err == nil {
		t.Fatal("expected error, got nil")
	}

	var blocked *ParryBlockedError
	if !errors.As(err, &blocked) {
		t.Fatalf("expected ParryBlockedError, got %T", err)
	}
	if blocked.Detector != "prompt_injection" {
		t.Errorf("expected detector prompt_injection, got %s", blocked.Detector)
	}
	if blocked.Confidence != 0.95 {
		t.Errorf("expected confidence 0.95, got %f", blocked.Confidence)
	}
}

func TestCheckBeforeCall_PermissionDenied(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sev := "high"
		json.NewEncoder(w).Encode(proxyCheckResponse{
			Allowed: false, Reason: "Tool 'delete_db' is explicitly blocked",
			Detector: "permission_boundary", Severity: &sev, Confidence: 1.0,
		})
	}))
	defer srv.Close()

	c := NewClient("sk-test", WithBaseURL(srv.URL))
	err := c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "test"})

	var permErr *ParryPermissionDeniedError
	if !errors.As(err, &permErr) {
		t.Fatalf("expected ParryPermissionDeniedError, got %T", err)
	}
	if permErr.ToolName != "delete_db" {
		t.Errorf("expected tool name delete_db, got %s", permErr.ToolName)
	}

	// Should also match ParryBlockedError via Unwrap
	var blocked *ParryBlockedError
	if !errors.As(err, &blocked) {
		t.Fatal("expected errors.As to match ParryBlockedError via Unwrap")
	}
}

func TestCheckBeforeCall_FailOpenOnNetworkError(t *testing.T) {
	c := NewClient("sk-test", WithBaseURL("http://localhost:1"))
	err := c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "hello"})
	if err != nil {
		t.Fatalf("expected fail-open (nil), got %v", err)
	}
}

func TestCheckBeforeCall_FailOpenOn500(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()

	c := NewClient("sk-test", WithBaseURL(srv.URL))
	err := c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "hello"})
	if err != nil {
		t.Fatalf("expected fail-open (nil), got %v", err)
	}
}

func TestCheckBeforeCall_SendsAuthHeader(t *testing.T) {
	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		json.NewEncoder(w).Encode(proxyCheckResponse{Allowed: true})
	}))
	defer srv.Close()

	c := NewClient("sk-parry-abc123", WithBaseURL(srv.URL))
	_ = c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "test"})

	if gotAuth != "Bearer sk-parry-abc123" {
		t.Errorf("expected Bearer auth, got %s", gotAuth)
	}
}

func TestCheckBeforeCall_UsesDefaultAgentID(t *testing.T) {
	var gotBody ProxyCheckRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&gotBody)
		json.NewEncoder(w).Encode(proxyCheckResponse{Allowed: true})
	}))
	defer srv.Close()

	c := NewClient("sk-test", WithBaseURL(srv.URL), WithAgentID("my-agent"))
	_ = c.CheckBeforeCall(context.Background(), ProxyCheckRequest{Prompt: "test"})

	if gotBody.AgentID != "my-agent" {
		t.Errorf("expected agent_id my-agent, got %s", gotBody.AgentID)
	}
}

func TestNewClient_Defaults(t *testing.T) {
	c := NewClient("key")
	if c.baseURL != defaultBaseURL {
		t.Errorf("expected default base URL, got %s", c.baseURL)
	}
	if c.DefaultAgentID != "" {
		t.Errorf("expected empty agent ID, got %s", c.DefaultAgentID)
	}
}

func TestNewClient_Options(t *testing.T) {
	c := NewClient("key",
		WithBaseURL("http://custom:9000/"),
		WithAgentID("agent-1"),
	)
	if c.baseURL != "http://custom:9000" {
		t.Errorf("expected trimmed URL, got %s", c.baseURL)
	}
	if c.DefaultAgentID != "agent-1" {
		t.Errorf("expected agent-1, got %s", c.DefaultAgentID)
	}
}
