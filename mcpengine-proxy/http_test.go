package mcpengine

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"go.uber.org/zap"
)

// RequestData holds details about each HTTP request received by the test server.
type RequestData struct {
	Body       string
	AuthHeader string
	URL        string
}

// ===== HTTP Post Sender Tests =====

func TestHTTPPostSender_WritesMessages(t *testing.T) {
	// Test that HTTPPostSender posts messages to the given endpoint.
	var mu sync.Mutex
	var requests []RequestData

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bodyBytes, _ := io.ReadAll(r.Body)
		mu.Lock()
		requests = append(requests, RequestData{
			Body:       string(bodyBytes),
			AuthHeader: r.Header.Get("Authorization"),
			URL:        r.URL.String(),
		})
		mu.Unlock()
		w.WriteHeader(http.StatusAccepted)
	}))
	defer ts.Close()

	// Create input and output channels
	inputChan := make(chan string, 3)
	outputChan := make(chan string, 3)
	endpointChan := make(chan string, 1)

	// Create messages
	messages := []string{"msg1", "msg2", "msg3"}
	for _, m := range messages {
		inputChan <- m
	}
	close(inputChan)

	// Send endpoint
	endpointChan <- "/test-endpoint"

	logger := zap.NewNop().Sugar()
	client := &http.Client{Timeout: 2 * time.Second}
	auth := NewAuthManager(nil, logger)

	// Set token
	auth.tokenMutex.Lock()
	auth.accessToken = "test-token"
	auth.tokenMutex.Unlock()

	sender := NewHTTPPostSender(client, ts.URL, endpointChan, inputChan, outputChan, auth, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	go sender.Run(ctx)

	// Allow some time for processing.
	time.Sleep(200 * time.Millisecond)

	mu.Lock()
	defer mu.Unlock()
	if len(requests) != len(messages) {
		t.Fatalf("expected %d requests, got %d", len(messages), len(requests))
	}
	for i, m := range messages {
		if requests[i].Body != m {
			t.Errorf("request %d: expected body %q, got %q", i, m, requests[i].Body)
		}
		if requests[i].AuthHeader != "Bearer test-token" {
			t.Errorf("request %d: expected auth header %q, got %q", i, "Bearer test-token", requests[i].AuthHeader)
		}
	}
}

func TestHTTPPostSender_Cancellation(t *testing.T) {
	// Test cancellation while waiting for endpoint
	endpointChan := make(chan string)
	inputChan := make(chan string)
	outputChan := make(chan string)

	logger := zap.NewNop().Sugar()
	client := &http.Client{}
	auth := NewAuthManager(nil, logger)

	sender := NewHTTPPostSender(client, "http://example.com", endpointChan, inputChan, outputChan, auth, logger)

	ctx, cancel := context.WithCancel(context.Background())

	errCh := make(chan error, 1)
	go func() {
		errCh <- sender.Run(ctx)
	}()

	// Cancel immediately
	cancel()

	select {
	case err := <-errCh:
		if err != context.Canceled {
			t.Errorf("Expected context.Canceled error, got: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("HTTPPostSender did not respect cancellation")
	}
}

func TestHTTPPostSender_InvalidURL(t *testing.T) {
	endpointChan := make(chan string, 1)
	inputChan := make(chan string)
	outputChan := make(chan string)

	// Send invalid URL
	endpointChan <- ":\\invalid"

	logger := zap.NewNop().Sugar()
	client := &http.Client{}
	auth := NewAuthManager(nil, logger)

	sender := NewHTTPPostSender(client, "http://example.com", endpointChan, inputChan, outputChan, auth, logger)

	ctx := context.Background()
	err := sender.Run(ctx)

	// Should return an error for invalid URL
	if err == nil {
		t.Fatal("Expected error for invalid URL, got nil")
	}
}

func TestHTTPPostSender_HTTPError(t *testing.T) {
	// Test handling of HTTP errors (connection refused, timeout, etc.)
	endpointChan := make(chan string, 1)
	inputChan := make(chan string, 1)
	outputChan := make(chan string)

	// Set up endpoint
	endpointChan <- "/api"

	// Set up message
	inputChan <- "test message"

	logger := zap.NewNop().Sugar()

	// Create client that always returns an error
	client := &http.Client{
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			return nil, fmt.Errorf("simulated network error")
		}),
	}

	auth := NewAuthManager(nil, logger)

	sender := NewHTTPPostSender(client, "http://localhost:1", endpointChan, inputChan, outputChan, auth, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	// This should not crash despite the HTTP error
	go sender.Run(ctx)

	// Allow time for processing
	time.Sleep(200 * time.Millisecond)

	// Success is that no crash occurred and execution reaches here
}

func TestHTTPPostSender_UnexpectedStatusCode(t *testing.T) {
	// Test handling of unexpected HTTP status codes (not 202/401/403)
	endpointChan := make(chan string, 1)
	inputChan := make(chan string, 1)
	outputChan := make(chan string)

	// Create test server that returns 500
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer ts.Close()

	// Set up endpoint and message
	endpointChan <- "/api"
	inputChan <- "test message"

	logger := zap.NewNop().Sugar()
	client := &http.Client{}
	auth := NewAuthManager(nil, logger)

	sender := NewHTTPPostSender(client, ts.URL, endpointChan, inputChan, outputChan, auth, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	// This should not crash despite the 500 error
	go sender.Run(ctx)

	// Allow time for processing
	time.Sleep(200 * time.Millisecond)

	// Success is that no crash occurred and execution reaches here
}
