package parry

import (
	"context"
	"time"
)

// ChatCompletionMessage mirrors openai.ChatCompletionMessage for
// decoupled usage — callers pass their own message structs.
type ChatCompletionMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatCompletionRequest is the input for a wrapped OpenAI call.
type ChatCompletionRequest struct {
	Model    string                  `json:"model"`
	Messages []ChatCompletionMessage `json:"messages"`
	Tools    []map[string]interface{} `json:"tools,omitempty"`
}

// ChatCompletionResponse is the output from a wrapped OpenAI call.
type ChatCompletionResponse struct {
	Content    string                   `json:"content"`
	Model      string                   `json:"model"`
	ToolCalls  []map[string]interface{} `json:"tool_calls,omitempty"`
	TokenCount int                      `json:"token_count,omitempty"`
	Raw        interface{}              `json:"raw,omitempty"`
}

// OpenAICallFunc is the signature for the actual OpenAI API call.
// Users provide this so the SDK doesn't depend on any specific
// OpenAI Go library.
//
// Example:
//
//	callFn := func(ctx context.Context, req parry.ChatCompletionRequest) (parry.ChatCompletionResponse, error) {
//	    openaiReq := openai.ChatCompletionRequest{
//	        Model:    req.Model,
//	        Messages: convertMessages(req.Messages),
//	    }
//	    resp, err := client.CreateChatCompletion(ctx, openaiReq)
//	    if err != nil {
//	        return parry.ChatCompletionResponse{}, err
//	    }
//	    return parry.ChatCompletionResponse{
//	        Content:    resp.Choices[0].Message.Content,
//	        Model:      resp.Model,
//	        TokenCount: resp.Usage.TotalTokens,
//	        Raw:        resp,
//	    }, nil
//	}
type OpenAICallFunc func(ctx context.Context, req ChatCompletionRequest) (ChatCompletionResponse, error)

// WrapOpenAI wraps an OpenAI call function with Parry security checks.
//
// The returned function performs:
//  1. Pre-call proxy check (returns error if blocked)
//  2. The actual LLM call with latency measurement
//  3. Post-call event ingest (fire-and-forget)
//
// Usage:
//
//	wrapped := parry.WrapOpenAI(parryClient, callFn, parry.WrapOptions{})
//	resp, err := wrapped(ctx, req)
func WrapOpenAI(
	parryClient *Client,
	callFn OpenAICallFunc,
	opts WrapOptions,
) OpenAICallFunc {
	agentID := opts.AgentID
	if agentID == "" {
		agentID = parryClient.DefaultAgentID
	}
	sessionID := opts.SessionID

	return func(ctx context.Context, req ChatCompletionRequest) (ChatCompletionResponse, error) {
		// Extract last user message as prompt
		var prompt string
		for i := len(req.Messages) - 1; i >= 0; i-- {
			if req.Messages[i].Role == "user" {
				prompt = req.Messages[i].Content
				break
			}
		}

		// Pre-call check
		if err := parryClient.CheckBeforeCall(ctx, ProxyCheckRequest{
			AgentID:   agentID,
			SessionID: sessionID,
			Prompt:    prompt,
			Model:     req.Model,
			ToolCalls: toolsToCallSlice(req.Tools),
		}); err != nil {
			return ChatCompletionResponse{}, err
		}

		// Execute the LLM call
		start := time.Now()
		resp, err := callFn(ctx, req)
		latencyMs := int(time.Since(start).Milliseconds())

		if err != nil {
			return resp, err
		}

		// Post-call ingest (fire-and-forget)
		parryClient.IngestEvent(ctx, EventIngestRequest{
			AgentID:    agentID,
			SessionID:  sessionID,
			Prompt:     prompt,
			Response:   resp.Content,
			Model:      resp.Model,
			ToolCalls:  resp.ToolCalls,
			LatencyMs:  &latencyMs,
			TokenCount: intPtr(resp.TokenCount),
		})

		return resp, nil
	}
}

// WrapOptions configures the OpenAI wrapper.
type WrapOptions struct {
	AgentID   string
	SessionID string
}

func toolsToCallSlice(tools []map[string]interface{}) []map[string]interface{} {
	if tools == nil {
		return []map[string]interface{}{}
	}
	result := make([]map[string]interface{}, len(tools))
	for i, t := range tools {
		if fn, ok := t["function"].(map[string]interface{}); ok {
			result[i] = map[string]interface{}{"name": fn["name"]}
		} else {
			result[i] = t
		}
	}
	return result
}

func intPtr(v int) *int {
	if v == 0 {
		return nil
	}
	return &v
}
