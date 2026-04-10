package parry

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

const (
	defaultBaseURL = "https://api.parry.dev"
	defaultTimeout = 2 * time.Second
)

// ClientOption configures a Client.
type ClientOption func(*Client)

// WithBaseURL sets the Parry API base URL.
func WithBaseURL(url string) ClientOption {
	return func(c *Client) {
		c.baseURL = strings.TrimRight(url, "/")
	}
}

// WithAgentID sets the default agent ID for all requests.
func WithAgentID(id string) ClientOption {
	return func(c *Client) {
		c.DefaultAgentID = id
	}
}

// WithTimeout sets the HTTP timeout for proxy checks.
func WithTimeout(d time.Duration) ClientOption {
	return func(c *Client) {
		c.timeout = d
	}
}

// WithHTTPClient sets a custom HTTP client.
func WithHTTPClient(hc *http.Client) ClientOption {
	return func(c *Client) {
		c.httpClient = hc
	}
}

// Client is the Parry SDK client. It handles event ingest and
// proxy checks with a fail-open contract: any error other than
// an explicit block results in the call being allowed through.
type Client struct {
	apiKey         string
	baseURL        string
	DefaultAgentID string
	timeout        time.Duration
	httpClient     *http.Client
}

// NewClient creates a new Parry client.
func NewClient(apiKey string, opts ...ClientOption) *Client {
	c := &Client{
		apiKey:  apiKey,
		baseURL: defaultBaseURL,
		timeout: defaultTimeout,
	}
	for _, opt := range opts {
		opt(c)
	}
	if c.httpClient == nil {
		c.httpClient = &http.Client{Timeout: c.timeout}
	}
	return c
}

// ProxyCheckRequest is the request body for a pre-call proxy check.
type ProxyCheckRequest struct {
	AgentID   string                   `json:"agent_id,omitempty"`
	SessionID string                   `json:"session_id,omitempty"`
	Prompt    string                   `json:"prompt,omitempty"`
	Model     string                   `json:"model,omitempty"`
	ToolCalls []map[string]interface{} `json:"tool_calls"`
}

type proxyCheckResponse struct {
	Allowed    bool    `json:"allowed"`
	Reason     string  `json:"reason"`
	Detector   string  `json:"detector"`
	Severity   *string `json:"severity"`
	Confidence float64 `json:"confidence"`
}

// CheckBeforeCall performs a pre-flight check before an LLM call.
//
// Returns nil if the call is allowed. Returns *ParryBlockedError or
// *ParryPermissionDeniedError if the call is blocked. Any other
// error (network, timeout, etc.) is logged and nil is returned
// (fail open).
func (c *Client) CheckBeforeCall(ctx context.Context, req ProxyCheckRequest) error {
	if req.AgentID == "" {
		req.AgentID = c.DefaultAgentID
	}
	if req.ToolCalls == nil {
		req.ToolCalls = []map[string]interface{}{}
	}

	body, err := json.Marshal(req)
	if err != nil {
		slog.Debug("parry: marshal failed, failing open", "error", err)
		return nil
	}

	resp, err := c.post(ctx, "/api/v1/proxy/check", body)
	if err != nil {
		slog.Debug("parry: proxy check failed, failing open", "error", err)
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		slog.Debug("parry: proxy check returned non-200, failing open", "status", resp.StatusCode)
		return nil
	}

	var result proxyCheckResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		slog.Debug("parry: proxy check parse failed, failing open", "error", err)
		return nil
	}

	if !result.Allowed {
		severity := "high"
		if result.Severity != nil {
			severity = *result.Severity
		}

		if result.Detector == "permission_boundary" {
			return &ParryPermissionDeniedError{
				ParryBlockedError: ParryBlockedError{
					Reason:     result.Reason,
					Detector:   result.Detector,
					Severity:   severity,
					Confidence: result.Confidence,
				},
				ToolName: extractToolName(result.Reason),
			}
		}

		return &ParryBlockedError{
			Reason:     result.Reason,
			Detector:   result.Detector,
			Severity:   severity,
			Confidence: result.Confidence,
		}
	}

	return nil
}

// EventIngestRequest is the request body for event ingestion.
type EventIngestRequest struct {
	AgentID    string                   `json:"agent_id,omitempty"`
	SessionID  string                   `json:"session_id,omitempty"`
	Prompt     string                   `json:"prompt,omitempty"`
	Response   string                   `json:"response,omitempty"`
	Model      string                   `json:"model,omitempty"`
	ToolCalls  []map[string]interface{} `json:"tool_calls"`
	LatencyMs  *int                     `json:"latency_ms,omitempty"`
	TokenCount *int                     `json:"token_count,omitempty"`
	Metadata   map[string]interface{}   `json:"metadata,omitempty"`
}

// IngestEvent sends a telemetry event to Parry (fire-and-forget).
// Never returns an error — all failures are logged and swallowed.
func (c *Client) IngestEvent(ctx context.Context, req EventIngestRequest) {
	if req.AgentID == "" {
		req.AgentID = c.DefaultAgentID
	}
	if req.ToolCalls == nil {
		req.ToolCalls = []map[string]interface{}{}
	}

	body, err := json.Marshal(req)
	if err != nil {
		slog.Debug("parry: ingest marshal failed", "error", err)
		return
	}

	// Fire and forget in a goroutine
	go func() {
		resp, err := c.post(ctx, "/api/v1/events/ingest", body)
		if err != nil {
			slog.Debug("parry: ingest failed", "error", err)
			return
		}
		resp.Body.Close()
	}()
}

func (c *Client) post(ctx context.Context, path string, body []byte) (*http.Response, error) {
	url := c.baseURL + path
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)
	httpReq.Header.Set("User-Agent", "parry-go/0.1.0")

	return c.httpClient.Do(httpReq)
}

func extractToolName(reason string) string {
	// Reason format: "Tool 'get_weather' is explicitly blocked"
	start := strings.Index(reason, "'")
	if start == -1 {
		return ""
	}
	end := strings.Index(reason[start+1:], "'")
	if end == -1 {
		return ""
	}
	return reason[start+1 : start+1+end]
}

// VerifyWebhookSignature checks that a webhook payload was signed by Parry.
// Use this in your webhook handler to verify authenticity.
func VerifyWebhookSignature(payload []byte, secret, signature string) bool {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(payload)
	expected := hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(expected), []byte(signature))
}
