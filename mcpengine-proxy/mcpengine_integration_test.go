package mcpengine

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/r3labs/sse/v2"
	"go.uber.org/zap"
)

// integrationSSEClient mocks the SSE client for integration testing
type integrationSSEClient struct {
	mu           sync.Mutex
	subscribers  map[string]chan *sse.Event
	triggerError bool
}

func newIntegrationSSEClient() *integrationSSEClient {
	return &integrationSSEClient{
		subscribers: make(map[string]chan *sse.Event),
	}
}

func (c *integrationSSEClient) SubscribeChan(stream string, msgChan chan *sse.Event) error {
	if c.triggerError {
		return fmt.Errorf("simulated subscription error")
	}

	c.mu.Lock()
	c.subscribers[stream] = msgChan
	c.mu.Unlock()

	return nil
}

func (c *integrationSSEClient) SendEvent(stream string, event *sse.Event) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if ch, ok := c.subscribers[stream]; ok {
		ch <- event
	}
}

// TestMCPEngine_Integration tests the entire engine working together
func TestMCPEngine_Integration(t *testing.T) {
	// Create a logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		t.Fatalf("Failed to create logger: %v", err)
	}
	sugarLogger := logger.Sugar()

	// Write messages to the input file
	messages := []string{
		`{"id": 1, "method": "test", "params": {"message": "hello"}}`,
		`{"id": 2, "method": "test", "params": {"message": "world"}}`,
	}
	fileContent := ""
	for _, msg := range messages {
		fileContent += msg + "\n"
	}
	// Create temp files for input and output
	inputFile := createTempFile(t, "mcpengine_input_int", fileContent)
	outputFile := createTempFile(t, "mcpengine_output_int", "")
	defer os.Remove(inputFile.Name())
	defer os.Remove(outputFile.Name())

	// Create a mock HTTP server
	var requestCount int
	var requestMu sync.Mutex
	var receivedRequests []string

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		requestMu.Lock()
		requestCount++
		receivedRequests = append(receivedRequests, string(body))
		requestMu.Unlock()

		w.WriteHeader(http.StatusAccepted)
	}))
	defer mockServer.Close()

	// Create a mock SSE client
	sseClient := newIntegrationSSEClient()

	// Create the engine with mocked components
	engine := &MCPEngine{
		endpoint:   mockServer.URL,
		inputFile:  inputFile,
		outputFile: outputFile,
		useSse:     true,
		sseClient:  sseClient,
		httpClient: mockServer.Client(),
		logger:     sugarLogger,
		auth:       NewAuthManager(nil, sugarLogger.With("svc", "auth")),
	}

	// Start the engine in a goroutine
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	engineDone := make(chan struct{})
	go func() {
		engine.Start(ctx)
		close(engineDone)
	}()

	// Allow time for the engine to initialize
	time.Sleep(100 * time.Millisecond)

	// Send an endpoint event via SSE
	endpointPath := "/messages/test-session"
	sseClient.SendEvent("messages", &sse.Event{
		Data: []byte(endpointPath),
	})

	// Allow time for the endpoint to be processed
	time.Sleep(100 * time.Millisecond)

	// Allow time for messages to be processed
	time.Sleep(200 * time.Millisecond)

	// Send some SSE events that should go to output
	sseResponses := []string{
		`{"id": 1, "result": "success"}`,
		`{"id": 2, "result": "success"}`,
	}

	for _, resp := range sseResponses {
		sseClient.SendEvent("messages", &sse.Event{
			Data: []byte(resp),
		})
	}

	// Allow time for processing
	time.Sleep(200 * time.Millisecond)

	// Cancel the context to stop the engine
	cancel()

	// Wait for the engine to stop
	select {
	case <-engineDone:
		// Success - engine has stopped
	case <-time.After(500 * time.Millisecond):
		t.Fatal("Engine did not stop after context cancellation")
	}

	// Verify HTTP requests
	requestMu.Lock()
	if len(receivedRequests) != len(messages) {
		t.Errorf("Expected %d HTTP requests, got %d", len(messages), len(receivedRequests))
	}

	for i, expected := range messages {
		if i < len(receivedRequests) {
			if receivedRequests[i] != expected {
				t.Errorf("HTTP request %d: expected %q, got %q", i, expected, receivedRequests[i])
			}
		}
	}
	requestMu.Unlock()

	// Read the output file and verify its contents
	outputData, err := os.ReadFile(outputFile.Name())
	if err != nil {
		t.Fatalf("Failed to read output file: %v", err)
	}

	outputLines := strings.Split(strings.TrimSpace(string(outputData)), "\n")

	// Check output file contents
	expectedOutputs := sseResponses

	if len(outputLines) != len(expectedOutputs) {
		t.Errorf("Expected %d output lines, got %d", len(expectedOutputs), len(outputLines))
	}

	for i, expected := range expectedOutputs {
		if i < len(outputLines) {
			if outputLines[i] != expected {
				t.Errorf("Output line %d: expected %q, got %q", i, expected, outputLines[i])
			}
		}
	}
}

// TestMCPEngine_StressTest tests the engine under high load
func TestMCPEngine_StressTest(t *testing.T) {
	// Skip this test in normal runs as it's resource-intensive
	if testing.Short() {
		t.Skip("Skipping stress test in short mode")
	}

	// Create a logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		t.Fatalf("Failed to create logger: %v", err)
	}
	sugarLogger := logger.Sugar()

	const messageCount = 100
	// Generate and write a large number of messages
	expectedMessages := make([]string, messageCount)
	fileContent := ""
	for i := 0; i < messageCount; i++ {
		msg := fmt.Sprintf(`{"id": %d, "method": "stress-test", "params": {"iteration": %d}}`, i, i)
		fileContent += msg + "\n"
		expectedMessages[i] = msg
	}

	// Create temp files for input and output
	inputFile := createTempFile(t, "mcpengine_stress_input", fileContent)
	outputFile := createTempFile(t, "mcpengine_stress_output", "")
	defer os.Remove(inputFile.Name())
	defer os.Remove(outputFile.Name())

	// Create a mock HTTP server
	var requestCount int
	var requestMu sync.Mutex

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestMu.Lock()
		requestCount++
		requestMu.Unlock()
		w.WriteHeader(http.StatusAccepted)
	}))
	defer mockServer.Close()

	// Create a mock SSE client
	sseClient := newIntegrationSSEClient()

	// Create the engine with mocked components
	engine := &MCPEngine{
		endpoint:   mockServer.URL,
		inputFile:  inputFile,
		outputFile: outputFile,
		sseClient:  sseClient,
		httpClient: mockServer.Client(),
		logger:     sugarLogger,
		auth:       NewAuthManager(nil, sugarLogger.With("svc", "auth")),
	}

	// Start the engine in a goroutine
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	engineDone := make(chan struct{})
	go func() {
		engine.Start(ctx)
		close(engineDone)
	}()

	// Allow time for the engine to initialize
	time.Sleep(100 * time.Millisecond)

	// Send an endpoint event via SSE
	endpointPath := "/messages/stress-test"
	sseClient.SendEvent("messages", &sse.Event{
		Data: []byte(endpointPath),
	})

	// Allow time for the endpoint to be processed
	time.Sleep(100 * time.Millisecond)

	// Send SSE responses
	go func() {
		for i := 0; i < messageCount; i++ {
			resp := fmt.Sprintf(`{"id": %d, "result": "ok"}`, i)
			sseClient.SendEvent("messages", &sse.Event{
				Data: []byte(resp),
			})
			time.Sleep(1 * time.Millisecond) // Slight delay to avoid overwhelming
		}
	}()

	// Wait for all messages to be processed
	// We'll poll the request count
	deadline := time.Now().Add(5 * time.Second)
	success := false

	for time.Now().Before(deadline) {
		requestMu.Lock()
		count := requestCount
		requestMu.Unlock()

		if count >= messageCount {
			success = true
			break
		}

		time.Sleep(100 * time.Millisecond)
	}

	if !success {
		requestMu.Lock()
		t.Errorf("Not all messages were processed. Expected %d, got %d", messageCount, requestCount)
		requestMu.Unlock()
	}

	// Cancel the context to stop the engine
	cancel()

	// Wait for the engine to stop
	select {
	case <-engineDone:
		// Success - engine has stopped
	case <-time.After(500 * time.Millisecond):
		t.Fatal("Engine did not stop after context cancellation")
	}
}

// TestMCPEngine_WorkerError tests how the engine handles worker errors
func TestMCPEngine_WorkerError(t *testing.T) {
	// Create a logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		t.Fatalf("Failed to create logger: %v", err)
	}
	sugarLogger := logger.Sugar()

	// Create temp files for input and output
	inputFile := createTempFile(t, "mcpengine_error_input", "")
	outputFile := createTempFile(t, "mcpengine_error_output", "")
	defer os.Remove(inputFile.Name())
	defer os.Remove(outputFile.Name())

	// Create a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer mockServer.Close()

	// Create a mock SSE client that errors on subscribe
	sseClient := newIntegrationSSEClient()
	sseClient.triggerError = true

	// Create the engine with mocked components
	engine := &MCPEngine{
		endpoint:   mockServer.URL,
		inputFile:  inputFile,
		outputFile: outputFile,
		sseClient:  sseClient,
		httpClient: mockServer.Client(),
		logger:     sugarLogger,
		auth:       NewAuthManager(nil, sugarLogger.With("svc", "auth")),
	}

	// Start the engine with a short timeout
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	// The engine should gracefully handle the SSE error
	// and exit when the context is canceled
	engine.Start(ctx)

	// If we reach here without hanging, the test is successful
}

// TestMCPEngine_Shutdown tests that the engine shuts down gracefully
func TestMCPEngine_Shutdown(t *testing.T) {
	// Create a logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		t.Fatalf("Failed to create logger: %v", err)
	}
	sugarLogger := logger.Sugar()

	// Create temp files for input and output
	inputFile := createTempFile(t, "mcpengine_shutdown_input", "")
	outputFile := createTempFile(t, "mcpengine_shutdown_output", "")
	defer os.Remove(inputFile.Name())
	defer os.Remove(outputFile.Name())

	// Create a mock HTTP server
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer mockServer.Close()

	// Create a mock SSE client
	sseClient := newIntegrationSSEClient()

	// Create the engine with mocked components
	engine := &MCPEngine{
		endpoint:   mockServer.URL,
		inputFile:  inputFile,
		outputFile: outputFile,
		sseClient:  sseClient,
		httpClient: mockServer.Client(),
		logger:     sugarLogger,
		auth:       NewAuthManager(nil, sugarLogger.With("svc", "auth")),
	}

	// Start the engine in a goroutine
	ctx, cancel := context.WithCancel(context.Background())

	engineDone := make(chan struct{})
	go func() {
		engine.Start(ctx)
		close(engineDone)
	}()

	// Allow time for the engine to initialize
	time.Sleep(100 * time.Millisecond)

	// Cancel the context to initiate shutdown
	cancel()

	// Check that the engine exits within a reasonable time
	select {
	case <-engineDone:
		// Success - engine has shut down
	case <-time.After(1 * time.Second):
		t.Fatal("Engine did not shut down within timeout")
	}
}
